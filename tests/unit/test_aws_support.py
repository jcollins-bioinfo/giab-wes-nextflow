"""Offline safety/provenance tests; no AWS credentials or paid resources."""
import copy
import json
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from giab_wes_nextflow import aws_support as aws


@pytest.mark.parametrize("uri", ["s3://private-bucket/source/a.fastq.gz", "s3://bucket-123/results/run/"])
def test_s3_paths(uri):
    bucket, key = aws.parse_s3_uri(uri)
    assert bucket and key


@pytest.mark.parametrize("uri", ["https://bucket/x", "s3://bucket", "s3://bucket/x?versionId=1",
                                    "s3://bucket/a/../b", "s3://bucket/%2e%2e/b", "s3://a/x",
                                    "s3://bucket/file name", "s3://bucket/x#frag", "s3://bucket//x", "s3://bucket/a//b"])
def test_ambiguous_s3_paths_rejected(uri):
    with pytest.raises(ValueError):
        aws.parse_s3_uri(uri)


def test_root_stops_after_identity(monkeypatch):
    calls = []
    class STS:
        def get_caller_identity(self):
            return {"Arn": "arn:aws:iam::123456789012:root", "Account": "123456789012", "UserId": "123456789012"}
    def factory(session, name):
        calls.append(name)
        assert name == "sts", "Root must never inspect more AWS services"
        return STS()
    monkeypatch.setattr(aws, "client", factory)
    report = aws.preflight(SimpleNamespace(region_name="us-west-2"))
    assert calls == ["sts"]
    assert report["is_root"] and not report["safe_to_deploy"]
    assert report["inventory"] == {} and "ROOT IDENTITY BLOCKED" in report["blockers"][0]


def test_requires_temporary_assumed_role():
    with pytest.raises(ValueError, match="temporary assumed-role"):
        aws.require_role({"Arn": "arn:aws:iam::123456789012:user/operator"})
    assert aws.require_role({"Arn": "arn:aws:sts::123456789012:assumed-role/Operator/session"})


def test_quota_insufficiency_and_unknown_spot_are_separate():
    result = aws.quota_assessment([{"QuotaCode": "L-1216C47A", "Value": 5}], 32)
    assert result["on_demand_standard"]["recommended_increase"] == 32
    assert result["spot_standard"]["value"] is None
    assert not result["spot_standard"]["sufficient_quota"]
    assert "L-34B43A08" in result["spot_standard"]["operator_command"]
    result = aws.quota_assessment([{"QuotaCode": "L-1216C47A", "Value": 5}], 4)
    assert result["on_demand_standard"]["sufficient_quota"]
    assert not result["on_demand_standard"]["capacity_or_unused_headroom_verified"]


def test_pagination_keeps_later_resources():
    class API:
        def get_paginator(self, operation):
            assert operation == "list_things"
            return SimpleNamespace(paginate=lambda **kw: [{"items": [1]}, {"items": [2, 3]}])
    assert aws.list_items(API(), "list_things", "items") == [1, 2, 3]


@pytest.fixture
def packaged_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    for name, text in {"cloud.nf": "nextflow.enable.dsl=2\n", "nextflow.config": "manifest.nextflowVersion='>=26.04.6'\n",
                       "README.md": "test\n", "pyproject.toml": "", "LICENSE": "test license\n"}.items():
        (repo / name).write_text(text)
    (repo / "conf").mkdir()
    (repo / "conf" / "cloud_healthomics.config").write_text("params.cloud_allow_spend=false\n")
    for command in (["git", "init", "-q"], ["git", "add", "."],
                    ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"]):
        subprocess.run(command, cwd=repo, check=True, capture_output=True)
    return repo, tmp_path / "workflow.zip"


def test_package_deterministic_and_tampering_detected(packaged_repo):
    repo, path = packaged_repo
    one = aws.package_workflow(repo, path)
    first = path.read_bytes()
    two = aws.package_workflow(repo, path)
    assert first == path.read_bytes() and one == two
    assert not one["source"]["source_worktree_dirty"]
    assert aws.verify_package(path) == one
    with zipfile.ZipFile(path) as z:
        assert set(z.namelist()) == set(one["source"]["files"]) | {"PACKAGE_MANIFEST.json"}
    path.write_bytes(path.read_bytes() + b"modified")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        aws.verify_package(path)


def test_package_rejects_source_symlink(packaged_repo):
    repo, path = packaged_repo
    (repo / "conf" / "escape.config").symlink_to(repo.parent / "secret")
    with pytest.raises(ValueError, match="Symlink"):
        aws.package_workflow(repo, path)


def test_image_mapping_never_changes_reviewed_digest():
    digest = "a" * 64
    mapping = {"imageMappings": [{"sourceImage": "quay.io/tool@sha256:" + digest,
                                 "destinationImage": "123456789012.dkr.ecr.us-west-2.amazonaws.com/tool@sha256:" + digest}]}
    assert aws.validate_registry_map(mapping) == mapping
    altered = copy.deepcopy(mapping)
    altered["imageMappings"][0]["destinationImage"] = altered["imageMappings"][0]["destinationImage"][:-1] + "b"
    with pytest.raises(ValueError, match="preserve exact"):
        aws.validate_registry_map(altered)


def plan_fixture(engine="26.04.6"):
    identity = {"package_sha256": "a" * 64, "engine_version": engine, "parameters": {"cloud_manifest_sha256": "b" * 64}}
    key = aws.sha256(aws.canonical_json(identity))
    return {"identity": identity, "scientific_identity_sha256": key, "blockers": [],
            "request": {"parameters": dict(identity["parameters"]),
                        "engineSettings": {"engineVersion": engine, "profile": "cloud_healthomics"},
                        "tags": {"ScientificIdentitySHA256": key, "PackageSHA256": "a" * 64}}}


def test_patch_version_gate_does_not_accept_minor_alias():
    for engine in ("26.04.0", "26.04.5"):
        with pytest.raises(ValueError, match="blocked"):
            aws.verify_run_plan(plan_fixture(engine))
    with pytest.raises(ValueError, match="Exact Nextflow"):
        aws.engine_version("26.04")
    aws.verify_run_plan(plan_fixture())


@pytest.mark.parametrize("change", ["manifest", "engine", "package"])
def test_changed_identity_is_rejected(change):
    plan = plan_fixture()
    if change == "manifest":
        plan["request"]["parameters"]["cloud_manifest_sha256"] = "c" * 64
    elif change == "engine":
        plan["request"]["engineSettings"]["engineVersion"] = "26.10.0"
    else:
        plan["request"]["tags"]["PackageSHA256"] = "d" * 64
    with pytest.raises(ValueError, match="changed"):
        aws.verify_run_plan(plan)


def test_evidence_distinguishes_cache_hits_misses_and_unknown():
    class API:
        def get_run(self, **kwargs):
            return {"id": kwargs["id"], "status": "COMPLETED", "engineVersion": "26.04.6"}
        def get_paginator(self, operation):
            return SimpleNamespace(paginate=lambda **kw: [{"items": [{"cacheHit": True}, {"cacheHit": False}, {}]}])
    evidence = aws.collect_run_evidence(API(), "123")
    assert evidence["cache"] == {"hits": 1, "misses": 1, "unknown": 1}
    assert evidence["uncached_compute_measurement"] is False


def test_submit_cli_without_authorization_never_contacts_aws():
    script = Path(__file__).resolve().parents[2] / "scripts" / "aws" / "healthomics.py"
    result = subprocess.run([__import__("sys").executable, str(script), "submit", "--plan", "missing.json",
                             "--preflight", "missing.json", "--engine-qualification-run", "1"], capture_output=True, text=True)
    assert result.returncode == 2
    assert "Paid submission is disabled" in result.stderr


def test_package_strips_only_unused_plugin_with_provenance(packaged_repo):
    repo, path = packaged_repo
    original = (repo / "nextflow.config").read_text() + "plugins { id 'nf-schema@2.8.0' }\n"
    (repo / "nextflow.config").write_text(original)
    result = aws.package_workflow(repo, path)
    transform = result["source"]["packaging_transforms"][0]
    assert transform["original_sha256"] == aws.sha256(original.encode())
    with zipfile.ZipFile(path) as archive:
        config = archive.read("nextflow.config")
        assert b">=26.04.6" in config and b"plugins {" not in config
    assert (repo / "nextflow.config").read_text() == original
    (repo / "nextflow.config").write_text("plugins { id 'unknown@1.0.0' }")
    with pytest.raises(ValueError, match="Unqualified"):
        aws.package_workflow(repo, path)


def manifest_fixture(source_sha):
    from giab_wes_nextflow.cloud_contract import ASSETS, QUALIFICATIONS
    return {"schema_version": "1.0.0", "kind": "cloud_canonical_inputs", "repository_sha": source_sha,
            "sample": "HG001", "scope": "hg001_chr20_22_coding",
            "assets": {role: {"uri": "s3://project-data/source/" + role, "sha256": "a" * 64, "bytes": 1}
                       for role in ASSETS},
            "qualifications": {role: {"uri": "s3://project-data/provenance/qualification-" + role + ".json",
                                       "sha256": "b" * 64, "bytes": 1} for role in QUALIFICATIONS}}


def test_run_plan_binds_all_scientific_identity_and_uses_current_api(packaged_repo):
    repo, path = packaged_repo
    evidence = aws.package_workflow(repo, path)
    manifest = manifest_fixture(evidence["source"]["source_head"])
    manifest_path = repo.parent / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    kwargs = {"package": path, "manifest_path": manifest_path, "manifest_uri": "s3://project-data/provenance/manifest.json",
              "support_image": "123456789012.dkr.ecr.us-west-2.amazonaws.com/support@sha256:" + "c" * 64,
              "workflow_id": "123", "role_arn": "arn:aws:iam::123456789012:role/Omics",
              "output_uri": "s3://project-data/results/run/", "run_group_id": "456"}
    blocked = aws.run_plan(**kwargs)
    assert "below required" in blocked["blockers"][0]
    plan = aws.run_plan(**kwargs, engine="26.04.6")
    aws.verify_run_plan(plan)
    cached = aws.run_plan(**kwargs, engine="26.04.6", cache_id="789")
    assert plan["scientific_identity_sha256"] == cached["scientific_identity_sha256"]
    assert cached["request"]["cacheId"] == "789"
    assert cached["request"]["cacheBehavior"] == "CACHE_ON_FAILURE"
    manifest["assets"]["evaluation"]["sha256"] = "d" * 64
    manifest_path.write_text(json.dumps(manifest))
    changed = aws.run_plan(**kwargs, engine="26.04.6")
    assert plan["scientific_identity_sha256"] != changed["scientific_identity_sha256"]
    botocore = pytest.importorskip("botocore.session")
    from botocore.validate import validate_parameters
    model = botocore.Session().get_service_model("omics")
    validate_parameters(cached["request"], model.operation_model("StartRun").input_shape)
    mapping = {"imageMappings": [{"sourceImage": "quay.io/tool@sha256:" + "c" * 64,
                                 "destinationImage": kwargs["support_image"]}]}
    registration = aws.registration_plan(path, "test-workflow", mapping)
    validate_parameters(dict(registration, definitionZip=path.read_bytes()), model.operation_model("CreateWorkflow").input_shape)


def batch_fixture():
    from giab_wes_nextflow.cloud_contract import tool_images
    images = dict(tool_images(), support='project/support@sha256:' + 'a' * 64)
    ordinary, benchmark = 'arn:aws:iam::123456789012:role/ordinary', 'arn:aws:iam::123456789012:role/benchmark'
    definitions = {}
    for key in ('support', 'support-benchmark', 'bwa', 'samtools', 'gatk', 'deepvariant',
                'bcftools', 'bcftools-benchmark', 'rtg', 'rtg-benchmark'):
        definitions[key] = {'name': key + ':1', 'image': images[key.removesuffix('-benchmark')],
                            'job_role_arn': benchmark if key.endswith('-benchmark') else ordinary}
    return definitions, ordinary, benchmark, images['support']


def test_batch_receipt_checks_actual_definition_revision():
    definitions, ordinary, benchmark, support = batch_fixture()
    class API:
        def describe_job_definitions(self, jobDefinitions):
            desired = next(d for d in definitions.values() if d['name'] == jobDefinitions[0])
            return {'jobDefinitions': [{'status': 'ACTIVE', 'type': 'container', 'platformCapabilities': ['EC2'],
                                        'containerProperties': {'image': desired['image'], 'jobRoleArn': desired['job_role_arn']}}]}
    report = aws.verify_batch_definitions(API(), definitions, ordinary, benchmark, support)
    assert report['status'] == 'verified'
    assert len(report['observed_definitions']) == 10
    assert report['definitions_sha256'] == aws.sha256(aws.canonical_json(definitions))


@pytest.mark.parametrize('violation', ['wrong_role', 'wrong_image', 'privileged', 'host_mount', 'arm'])
def test_batch_actual_unsafe_definition_rejected(violation):
    definitions, ordinary, benchmark, support = batch_fixture()
    class API:
        def describe_job_definitions(self, jobDefinitions):
            desired = next(d for d in definitions.values() if d['name'] == jobDefinitions[0])
            props = {'image': desired['image'], 'jobRoleArn': desired['job_role_arn']}
            if violation == 'wrong_role': props['jobRoleArn'] = 'arn:aws:iam::123456789012:role/admin'
            if violation == 'wrong_image': props['image'] = 'image:latest'
            if violation == 'privileged': props['privileged'] = True
            if violation == 'host_mount': props['volumes'] = [{'host': {'sourcePath': '/var/run/docker.sock'}}]
            if violation == 'arm': props['runtimePlatform'] = {'cpuArchitecture': 'ARM64'}
            return {'jobDefinitions': [{'status': 'ACTIVE', 'type': 'container', 'containerProperties': props}]}
    with pytest.raises(ValueError):
        aws.verify_batch_definitions(API(), definitions, ordinary, benchmark, support)


@pytest.mark.parametrize('read_only', [True, False])
def test_batch_cli_mount_is_narrowly_qualified(read_only):
    definitions, ordinary, benchmark, support = batch_fixture()
    class API:
        def describe_job_definitions(self, jobDefinitions):
            desired = next(d for d in definitions.values() if d['name'] == jobDefinitions[0])
            props = {'image': desired['image'], 'jobRoleArn': desired['job_role_arn'],
                     'volumes': [{'name': 'aws-cli', 'host': {'sourcePath': '/opt/giab-awscli'}}],
                     'mountPoints': [{'sourceVolume': 'aws-cli', 'containerPath': '/opt/giab-awscli', 'readOnly': read_only}]}
            return {'jobDefinitions': [{'status': 'ACTIVE', 'type': 'container', 'containerProperties': props}]}
    if read_only:
        assert aws.verify_batch_definitions(API(), definitions, ordinary, benchmark, support)['status'] == 'verified'
    else:
        with pytest.raises(ValueError, match='host mounts'):
            aws.verify_batch_definitions(API(), definitions, ordinary, benchmark, support)


def test_create_group_defaults_to_offline_bounded_plan():
    script = Path(__file__).resolve().parents[2] / 'scripts' / 'aws' / 'healthomics.py'
    result = subprocess.run([__import__('sys').executable, str(script), 'create-group'], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert (plan['maxCpus'], plan['maxRuns'], plan['maxDuration']) == (32, 1, 2880)
    botocore = pytest.importorskip('botocore.session')
    from botocore.validate import validate_parameters
    validate_parameters(plan, botocore.Session().get_service_model('omics').operation_model('CreateRunGroup').input_shape)


@pytest.mark.parametrize("failed,unaffected", [("omics.list_workflows", "awsbatch"), ("quotas.ec2", "healthomics"), ("ecs.list_clusters", "healthomics"), ("route53.list_hosted_zones", "awsbatch")])
def test_backend_inspection_is_independent(failed, unaffected):
    report = {"errors": {failed: "AccessDenied"},
              "batch": aws.quota_assessment([], 32),
              "healthomics": {"engine_compatibility_verified": False}}
    result = aws.backend_readiness(report, 32)
    assert result[unaffected]["inspection_complete"]
    assert not any(failed in x for x in result[unaffected]["blockers"])
    assert not any("EC2" in x for x in result["healthomics"]["blockers"])
    assert not any("HealthOmics" in x for x in result["awsbatch"]["blockers"])
    assert not result[unaffected]["safe_to_deploy"]


def test_common_inspection_failure_blocks_both_backends():
    report = {"errors": {"s3.list_buckets": "AccessDenied"},
              "batch": aws.quota_assessment([], 32),
              "healthomics": {"engine_compatibility_verified": False}}
    assert all(not x["inspection_complete"] for x in aws.backend_readiness(report, 32).values())
