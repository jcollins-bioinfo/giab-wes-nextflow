"""Read-only AWS inspection and offline, identity-bound HealthOmics plans.

AWS clients are injected into reusable functions; importing this module never
creates a client, reads credentials, or calls AWS.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

REGION = "us-west-2"
MIN_NEXTFLOW = (26, 4, 6)
DOCUMENTED_OMICS_ENGINE = "26.04.0"
EC2_QUOTAS = {"on_demand_standard": "L-1216C47A", "spot_standard": "L-34B43A08"}
PROJECT = "giab-wes-nextflow"


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def parse_s3_uri(uri):
    parsed = urlsplit(uri)
    if (parsed.scheme != "s3" or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", parsed.netloc)
            or parsed.query or parsed.fragment or not parsed.path.lstrip("/")
            or any(p in {"", ".", ".."} for p in parsed.path[1:].rstrip("/").split("/"))
            or "%" in uri or any(c.isspace() for c in uri)):
        raise ValueError("Expected an unambiguous s3://bucket/key URI without query, fragment or traversal")
    return parsed.netloc, parsed.path[1:]


def require_role(identity):
    arn = identity.get("Arn", "")
    if arn.endswith(":root"):
        raise ValueError("ROOT IDENTITY BLOCKED: authenticate with a temporary project operator role; no further AWS calls allowed")
    if not re.fullmatch(r"arn:aws(?:-us-gov|-cn)?:sts::\d{12}:assumed-role/.+/.+", arn):
        raise ValueError("A temporary assumed-role session is required; IAM users are not automation identities")
    return identity


def make_session(profile=None, region=REGION):
    import boto3
    return boto3.Session(profile_name=profile, region_name=region)


def client(session, service):
    from botocore.config import Config
    return session.client(service, config=Config(
        retries={"total_max_attempts": 3, "mode": "standard"},
        connect_timeout=5, read_timeout=30,
    ))


def list_items(api, operation, key, **kwargs):
    return [item for page in api.get_paginator(operation).paginate(**kwargs)
            for item in page.get(key, [])]


def quota_assessment(ec2_quotas, requested_vcpus, region=REGION):
    if requested_vcpus < 1:
        raise ValueError("requested_vcpus must be positive")
    by_code = {q["QuotaCode"]: q for q in ec2_quotas}
    result = {}
    for label, code in EC2_QUOTAS.items():
        quota = by_code.get(code, {})
        value = quota.get("Value")
        result[label] = {
            "quota_code": code, "value": value, "requested_vcpus": requested_vcpus,
            "sufficient_quota": value is not None and value >= requested_vcpus,
            "capacity_or_unused_headroom_verified": False,
            "recommended_increase": requested_vcpus if value is None or value < requested_vcpus else None,
            "operator_command": (f"aws service-quotas request-service-quota-increase --region {region} "
                                 f"--service-code ec2 --quota-code {code} --desired-value {requested_vcpus}"),
        }
    return result


def preflight(session, requested_vcpus=32, project_prefix="giab-wes"):
    """Only STS is called before rejecting root or non-role identities."""
    report = {"schema_version": "1.0.0", "region": session.region_name,
              "observed_at": datetime.now(timezone.utc).isoformat(), "mutations": [],
              "inventory": {}, "errors": {}, "blockers": [], "safe_to_deploy": False}
    identity = client(session, "sts").get_caller_identity()
    report["identity"] = {k: identity[k] for k in ("Account", "Arn", "UserId")}
    report["is_root"] = identity["Arn"].endswith(":root")
    try:
        require_role(identity)
    except ValueError as exc:
        report["blockers"].append(str(exc))
        return report
    from botocore.exceptions import BotoCoreError, ClientError
    operations = [
        ("s3", "list_buckets", "Buckets", {}),
        ("ecr", "describe_repositories", "repositories", {}),
        ("batch", "describe_compute_environments", "computeEnvironments", {}),
        ("batch", "describe_job_queues", "jobQueues", {}),
        ("batch", "describe_job_definitions", "jobDefinitions", {"status": "ACTIVE"}),
        ("omics", "list_workflows", "items", {"type": "PRIVATE"}),
        ("omics", "list_run_groups", "items", {}),
        ("omics", "list_run_caches", "items", {}),
        ("ecs", "list_clusters", "clusterArns", {}),
        ("logs", "describe_log_groups", "logGroups", {}),
        ("ec2", "describe_vpcs", "Vpcs", {}),
        ("ec2", "describe_subnets", "Subnets", {}),
        ("acm", "list_certificates", "CertificateSummaryList", {}),
        ("route53", "list_hosted_zones", "HostedZones", {}),
    ]
    clients = {}
    for service, operation, key, kwargs in operations:
        name = f"{service}.{operation}"
        try:
            if service not in clients:
                clients[service] = client(session, service)
            items = list_items(clients[service], operation, key, **kwargs)
            report["inventory"][name] = {"count": len(items), "items": items,
                "project_candidates": [x for x in items if project_prefix in json.dumps(x, default=str)]}
        except (ClientError, BotoCoreError) as exc:
            report["errors"][name] = str(exc)
    sq = client(session, "service-quotas")
    report["quotas"] = {}
    for service in ("ec2", "omics"):
        try:
            report["quotas"][service] = list_items(sq, "list_service_quotas", "Quotas", ServiceCode=service)
        except (ClientError, BotoCoreError) as exc:
            report["errors"][f"quotas.{service}"] = str(exc)
    report["batch"] = quota_assessment(report["quotas"].get("ec2", []), requested_vcpus, session.region_name)
    report["healthomics"] = {
        "documented_engine": DOCUMENTED_OMICS_ENGINE, "required_engine": ">=26.04.6",
        "engine_compatibility_verified": False,
        "quota_values": report["quotas"].get("omics", []),
    }
    report["service_availability"] = {
        service: {"sdk_endpoint_advertised": session.region_name in session.get_available_regions(service),
                  "api_read_succeeded": any(k.startswith(service + ".") for k in report["inventory"])}
        for service in ("s3", "ecr", "batch", "omics", "ecs")
    }
    if report["errors"]:
        report["blockers"].append("Inspection incomplete; denied/failed calls are unknown state, never empty state")
    if not report["batch"]["on_demand_standard"]["sufficient_quota"]:
        report["blockers"].append(f"On-Demand EC2 quota below desired {requested_vcpus} vCPU ceiling")
    report["blockers"].extend([
        "HealthOmics documented 26.04.0 engine is below repository minimum 26.04.6",
        "Deployment needs a reviewed Terraform plan and separate explicit operator authorization",
    ])
    report["inspection_complete"] = not report["errors"]
    return report


def package_workflow(repo, destination):
    """Deterministic source ZIP: no generated results, credentials, or user data."""
    repo, destination = Path(repo).resolve(), Path(destination)
    if not (repo / "cloud.nf").is_file():
        raise ValueError("cloud.nf does not exist")
    source_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    paths = {repo / name for name in ("cloud.nf", "nextflow.config", "pyproject.toml", "README.md", "LICENSE")}
    for directory, pattern in (("conf", "*.config"), ("modules", "*.nf"), ("workflows", "*.nf"),
                               ("subworkflows", "*.nf"), ("config", "*.json"), ("src", "*.py"),
                               ("bin", "*.py"), ("bin", "*.sh")):
        paths.update((repo / directory).rglob(pattern))
    payload = {}
    for path in sorted(paths):
        if path.is_symlink() or not path.resolve().is_relative_to(repo):
            raise ValueError(f"Symlink/out-of-tree source forbidden: {path}")
        if path.is_file():
            payload[path.relative_to(repo).as_posix()] = path.read_bytes()
    # nf-schema belongs to the foundation workflow. The cloud entrypoint uses
    # cloud_contract directly and must not trigger an unneeded plugin download.
    config = payload["nextflow.config"]
    plugin_block = b"plugins { id 'nf-schema@2.8.0' }"
    transforms = []
    if plugin_block in config:
        payload["nextflow.config"] = config.replace(
            plugin_block, b"// Unused foundation nf-schema plugin excluded from HealthOmics package.", 1)
        transforms.append({"path": "nextflow.config", "original_sha256": sha256(config),
                           "operation": "remove unused foundation nf-schema@2.8.0 plugin block"})
    if re.search(rb"\bplugins\s*\{", payload["nextflow.config"]):
        raise ValueError("Unqualified Nextflow plugins remain in HealthOmics package")
    manifest = {"schema_version": "1.0.0", "source_head": source_sha,
                "source_worktree_dirty": bool(subprocess.check_output(
                    ["git", "status", "--porcelain"], cwd=repo, text=True).strip()),
                "main": "cloud.nf", "profile": "cloud_healthomics", "packaging_transforms": transforms,
                "files": {name: {"sha256": sha256(data), "bytes": len(data)} for name, data in payload.items()}}
    payload["PACKAGE_MANIFEST.json"] = canonical_json(manifest)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(payload.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    result = {"zip_sha256": sha256(destination.read_bytes()), "source": manifest}
    destination.with_suffix(destination.suffix + ".json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def verify_package(path):
    path = Path(path)
    sidecar = json.loads(path.with_suffix(path.suffix + ".json").read_text())
    if sha256(path.read_bytes()) != sidecar["zip_sha256"]:
        raise ValueError("Workflow ZIP SHA-256 mismatch")
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("PACKAGE_MANIFEST.json"))
        if manifest != sidecar["source"] or set(archive.namelist()) != set(manifest["files"]) | {"PACKAGE_MANIFEST.json"}:
            raise ValueError("Workflow package file manifest mismatch")
        for name, expected in manifest["files"].items():
            data = archive.read(name)
            if sha256(data) != expected["sha256"] or len(data) != expected["bytes"]:
                raise ValueError(f"Workflow package content mismatch: {name}")
    return sidecar


def validate_registry_map(mapping):
    if set(mapping) != {"imageMappings"} or not mapping["imageMappings"]:
        raise ValueError("Explicit digest-preserving imageMappings required; registry-wide aliases are not provenance")
    for item in mapping["imageMappings"]:
        source, destination = item["sourceImage"], item["destinationImage"]
        digest = re.search(r"@sha256:[0-9a-f]{64}$", source)
        if not digest or not destination.endswith(digest.group()):
            raise ValueError("Image mapping must preserve exact reviewed upstream digest")
        if not re.match(r"\d{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/", destination):
            raise ValueError("Destination image must be in private ECR")
    return mapping


def registration_plan(package, name, registry_map):
    evidence = verify_package(package)
    return {"name": name, "engine": "NEXTFLOW", "main": "cloud.nf", "storageType": "DYNAMIC",
            "requestId": evidence["zip_sha256"], "containerRegistryMap": validate_registry_map(registry_map),
            "tags": {"Project": PROJECT, "PackageSHA256": evidence["zip_sha256"],
                     "SourceSHA": evidence["source"]["source_head"]},
            "parameterTemplate": {key: {"description": description, "optional": False} for key, description in {
                "cloud_manifest": "Authenticated immutable S3 cloud input manifest URI",
                "cloud_manifest_sha256": "SHA-256 of manifest bytes",
                "cloud_support_image": "Qualified amd64 support image immutable ECR digest",
                "cloud_repository_sha": "Exact source commit",
                "cloud_allow_spend": "Explicit authorization gate",
            }.items()}}


def engine_version(value):
    if not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise ValueError("Exact Nextflow major.minor.patch is required")
    return tuple(map(int, value.split(".")))


def run_plan(*, package, manifest_path, manifest_uri, support_image, workflow_id,
             role_arn, output_uri, run_group_id, engine="26.04.0", cache_id=None):
    from giab_wes_nextflow.cloud_contract import validate_manifest
    manifest = json.loads(Path(manifest_path).read_text())
    validate_manifest(manifest)
    parse_s3_uri(manifest_uri)
    parse_s3_uri(output_uri)
    if not re.fullmatch(r"arn:aws:iam::\d{12}:role/[A-Za-z0-9+=,.@_/-]+", role_arn):
        raise ValueError("A HealthOmics execution role ARN is required")
    if not re.fullmatch(r"\d{12}\.dkr\.ecr\.us-west-2\.amazonaws\.com/.+@sha256:[0-9a-f]{64}", support_image):
        raise ValueError("Qualified private ECR us-west-2 digest-pinned support image required")
    package_evidence = verify_package(package)
    if manifest["repository_sha"] != package_evidence["source"]["source_head"]:
        raise ValueError("Manifest repository SHA does not match packaged source HEAD")
    manifest_hash = sha256(Path(manifest_path).read_bytes())
    parameters = {"cloud_manifest": manifest_uri, "cloud_manifest_sha256": manifest_hash,
                  "cloud_support_image": support_image, "cloud_repository_sha": manifest["repository_sha"],
                  "cloud_allow_spend": "true"}
    identity = {"package_sha256": package_evidence["zip_sha256"], "manifest_sha256": manifest_hash,
                "manifest": manifest, "parameters": parameters, "engine_version": engine,
                "profile": "cloud_healthomics"}
    key = sha256(canonical_json(identity))
    request = {"workflowId": workflow_id, "workflowType": "PRIVATE", "roleArn": role_arn,
               "name": "hg001-chr20-22-" + key[:12], "outputUri": output_uri,
               "parameters": parameters, "storageType": "DYNAMIC", "logLevel": "ALL",
               "runGroupId": run_group_id, "engineSettings": {"engineVersion": engine, "profile": "cloud_healthomics"},
               "requestId": sha256(canonical_json({"identity": key, "output": output_uri, "workflow": workflow_id,
                                                    "group": run_group_id, "cache": cache_id})),
               "tags": {"Project": PROJECT, "ScientificIdentitySHA256": key,
                        "PackageSHA256": package_evidence["zip_sha256"]}}
    if cache_id:
        request.update(cacheId=cache_id, cacheBehavior="CACHE_ON_FAILURE")
    blockers = []
    if engine_version(engine) < MIN_NEXTFLOW:
        blockers.append(f"Nextflow {engine} is below required 26.04.6; no supported patch compatibility established")
    if package_evidence["source"]["source_worktree_dirty"]:
        blockers.append("Package was built from a dirty worktree; commit and repackage before canonical execution")
    return {"schema_version": "1.0.0", "scientific_identity_sha256": key, "identity": identity,
            "request": request, "blockers": blockers, "mutation_performed": False,
            "cache_measurement_policy": "Cache hits are reuse, never new uncached compute measurements"}


def verify_run_plan(plan):
    key = sha256(canonical_json(plan["identity"]))
    if key != plan["scientific_identity_sha256"] or key != plan["request"]["tags"]["ScientificIdentitySHA256"]:
        raise ValueError("Run plan scientific identity mismatch")
    if plan["request"]["parameters"] != plan["identity"]["parameters"]:
        raise ValueError("Run parameters changed after scientific identity construction")
    if plan["request"]["engineSettings"] != {"engineVersion": plan["identity"]["engine_version"], "profile": "cloud_healthomics"}:
        raise ValueError("Engine/profile changed after scientific identity construction")
    if plan["request"]["tags"]["PackageSHA256"] != plan["identity"]["package_sha256"]:
        raise ValueError("Package identity changed")
    if engine_version(plan["identity"]["engine_version"]) < MIN_NEXTFLOW or plan["blockers"]:
        raise ValueError("Run plan blocked: " + "; ".join(plan["blockers"]))


def collect_run_evidence(omics, run_id):
    run = omics.get_run(id=run_id)
    tasks = list_items(omics, "list_run_tasks", "items", id=run_id)
    counts = {"hits": sum(t.get("cacheHit") is True for t in tasks),
              "misses": sum(t.get("cacheHit") is False for t in tasks),
              "unknown": sum("cacheHit" not in t for t in tasks)}
    return {"schema_version": "1.0.0", "run": run, "tasks": tasks, "cache": counts,
            "uncached_compute_measurement": False,
            "measurement_note": "Task observations only; qualify uncached timing separately and exclude cached tasks"}


def verify_batch_definitions(batch, definitions, ordinary_role, benchmark_role, support_image):
    """Read actual revision-pinned Batch definitions; never register or submit."""
    from giab_wes_nextflow.cloud_contract import tool_images
    names = {'support', 'support-benchmark', 'bwa', 'samtools', 'gatk', 'deepvariant',
             'bcftools', 'bcftools-benchmark', 'rtg', 'rtg-benchmark'}
    if set(definitions) != names:
        raise ValueError('Exact reviewed ten-image Batch job definition inventory required')
    if ordinary_role == benchmark_role:
        raise ValueError('Ordinary and benchmark roles must be distinct')
    expected_images = dict(tool_images(), support=support_image)
    if not re.fullmatch(r'[^\s]+@sha256:[0-9a-f]{64}', support_image):
        raise ValueError('Digest-pinned support image required')
    observed = {}
    for key, desired in sorted(definitions.items()):
        if set(desired) != {'name', 'image', 'job_role_arn'} or not re.search(r':\d+$', desired['name']):
            raise ValueError(f'{key}: exact name:revision and image/job role required')
        expected_role = benchmark_role if key.endswith('-benchmark') else ordinary_role
        source_image = expected_images[key.removesuffix('-benchmark')]
        if (desired['job_role_arn'] != expected_role or '@sha256:' not in desired['image']
                or desired['image'].split('@sha256:')[-1] != source_image.split('@sha256:')[-1]):
            raise ValueError(f'{key}: declared role or scientific digest differs from reviewed identity')
        matches = batch.describe_job_definitions(jobDefinitions=[desired['name']]).get('jobDefinitions', [])
        if len(matches) != 1:
            raise ValueError(f'{key}: exact Batch revision not found')
        actual = matches[0]
        props = actual.get('containerProperties', {})
        if (actual.get('status') != 'ACTIVE' or actual.get('type') != 'container'
                or actual.get('platformCapabilities', ['EC2']) != ['EC2']
                or props.get('image') != desired['image'] or props.get('jobRoleArn') != expected_role
                or props.get('privileged', False)
                or props.get('runtimePlatform', {}).get('cpuArchitecture', 'X86_64') != 'X86_64'):
            raise ValueError(f'{key}: AWS job definition status/image/role/EC2/amd64/privilege mismatch')
        host_volumes = [volume for volume in props.get('volumes', []) if volume.get('host')]
        if host_volumes:
            # Custom definitions do not receive Nextflow's automatic AWS CLI
            # staging mount. Only this read-only CLI installation is qualified;
            # never expose a Docker socket or arbitrary host filesystem.
            allowed_volume = {'name': 'aws-cli', 'host': {'sourcePath': '/opt/giab-awscli'}}
            allowed_mount = {'sourceVolume': 'aws-cli', 'containerPath': '/opt/giab-awscli', 'readOnly': True}
            mounts = [mount for mount in props.get('mountPoints', []) if mount.get('sourceVolume') == 'aws-cli']
            if host_volumes != [allowed_volume] or mounts != [allowed_mount]:
                raise ValueError(f'{key}: unqualified host mounts forbidden')
        observed[key] = actual
    return {'schema_version': '1.0.0', 'kind': 'cloud_batch_definitions', 'status': 'verified',
            'observed_at': datetime.now(timezone.utc).isoformat(), 'region': REGION,
            'ordinary_role': ordinary_role, 'benchmark_role': benchmark_role,
            'definitions_sha256': sha256(canonical_json(definitions)),
            'definitions': definitions, 'observed_definitions': observed,
            'limitations': 'Verifies job definitions only; IAM policy effects, quotas, EC2 architecture and scientific runtime qualification are separate gates'}
