#!/usr/bin/env python3
"""Offline plans by default; every AWS mutation needs an explicit authorization flag."""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from giab_wes_nextflow.aws_support import (
    PROJECT, REGION, client, collect_run_evidence, make_session, package_workflow,
    parse_s3_uri, registration_plan, require_role, run_plan, sha256, verify_run_plan,
)


def read_json(path):
    return json.loads(Path(path).read_text())


def active_clients(args):
    session = make_session(args.profile, args.region)
    identity = require_role(client(session, "sts").get_caller_identity())
    return session, identity, client(session, "omics")


def submit(plan, *, omics, s3, identity, preflight_report, engine_qualification_run):
    """All read gates run before StartRun; no flag bypasses scientific gates."""
    require_role(identity)
    verify_run_plan(plan)
    from giab_wes_nextflow.cloud_contract import validate_manifest
    validate_manifest(plan["identity"]["manifest"])
    report = preflight_report
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(report["observed_at"])).total_seconds()
    if (not report.get("inspection_complete") or report.get("is_root") or not 0 <= age <= 3600
            or report["identity"]["Account"] != identity["Account"] or report["region"] != REGION):
        raise ValueError("A complete same-account us-west-2 non-root preflight less than one hour old is required")
    request = plan["request"]
    role_account = request["roleArn"].split(":")[4]
    if role_account != identity["Account"]:
        raise ValueError("Cross-account execution role is not qualified")
    workflow = omics.get_workflow(id=request["workflowId"], type="PRIVATE")
    if workflow.get("status") != "ACTIVE" or workflow.get("tags", {}).get("PackageSHA256") != plan["identity"]["package_sha256"]:
        raise ValueError("Active registered workflow package identity does not match plan")
    qualification = omics.get_run(id=engine_qualification_run)
    if (qualification.get("status") != "COMPLETED"
            or qualification.get("engineVersion") != plan["identity"]["engine_version"]):
        raise ValueError("Completed HealthOmics engine qualification run with exact required patch not found")
    group = omics.get_run_group(id=request["runGroupId"])
    if not (0 < group.get("maxCpus", 0) <= 32 and group.get("maxRuns") == 1
            and 0 < group.get("maxDuration", 0) <= 2880):
        raise ValueError("Run group must bound CPU <=32, concurrent runs =1 and duration <=2880 minutes")
    bucket, key = parse_s3_uri(request["parameters"]["cloud_manifest"])
    with s3.get_object(Bucket=bucket, Key=key, ExpectedBucketOwner=identity["Account"])["Body"] as stream:
        payload = stream.read(4 * 1024 * 1024 + 1)
    if len(payload) > 4 * 1024 * 1024 or sha256(payload) != plan["identity"]["manifest_sha256"]:
        raise ValueError("S3 manifest bytes differ from reviewed SHA-256 (ETag is not used)")
    if "cacheId" in request:
        cache = omics.get_run_cache(id=request["cacheId"])
        if (cache.get("status") != "ACTIVE" or cache.get("tags", {}).get("ScientificIdentitySHA256")
                != plan["scientific_identity_sha256"]):
            raise ValueError("Run cache is not bound to exactly this scientific identity")
    return omics.start_run(**request)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--profile")
    p.add_argument("--region", default=REGION)
    p.add_argument("--output", type=Path, help="Save JSON plan/evidence")
    commands = p.add_subparsers(dest="command", required=True)
    package = commands.add_parser("package", help="Build deterministic ZIP locally")
    package.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    package.add_argument("--zip", required=True, type=Path)
    register = commands.add_parser("register", help="Print registration plan; optional explicit mutation")
    register.add_argument("--zip", required=True, type=Path)
    register.add_argument("--name", required=True)
    register.add_argument("--registry-map", required=True, type=Path)
    register.add_argument("--allow-register", action="store_true")
    group = commands.add_parser("create-group", help="Plan a bounded run group; optional explicit mutation")
    group.add_argument("--name", default="giab-hg001-canonical")
    group.add_argument("--allow-create-group", action="store_true")
    plan = commands.add_parser("plan", help="Offline canonical StartRun plan, with blockers")
    plan.add_argument("--zip", required=True, type=Path)
    plan.add_argument("--manifest", required=True, type=Path)
    for name in ("manifest-uri", "support-image", "workflow-id", "role-arn", "output-uri", "run-group-id"):
        plan.add_argument("--" + name, required=True)
    plan.add_argument("--engine-version", default="26.04.0")
    plan.add_argument("--cache-id")
    cache = commands.add_parser("create-cache", help="Print cache plan scoped to one scientific identity")
    cache.add_argument("--plan", required=True, type=Path)
    cache.add_argument("--cache-uri", required=True)
    cache.add_argument("--allow-create-cache", action="store_true")
    start = commands.add_parser("submit", help="Submit a reviewed plan only after all gates")
    start.add_argument("--plan", required=True, type=Path)
    start.add_argument("--preflight", required=True, type=Path)
    start.add_argument("--engine-qualification-run", required=True)
    start.add_argument("--allow-paid-run", action="store_true")
    evidence = commands.add_parser("evidence", help="Read run/task/cache evidence")
    evidence.add_argument("--run-id", required=True)
    return p


def main():
    p = parser()
    args = p.parse_args()
    try:
        if args.region != REGION:
            raise ValueError("This initial implementation is qualified only for us-west-2; region change requires review")
        if args.command == "package":
            result = package_workflow(args.repo, args.zip)
        elif args.command == "register":
            result = registration_plan(args.zip, args.name, read_json(args.registry_map))
            if args.allow_register:
                _, _, omics = active_clients(args)
                result = {"request": result, "response": omics.create_workflow(**result, definitionZip=args.zip.read_bytes())}
        elif args.command == "create-group":
            result = {"name": args.name, "maxCpus": 32, "maxRuns": 1, "maxDuration": 2880,
                      "tags": {"Project": PROJECT}, "requestId": sha256((args.name + ":32:1:2880").encode())}
            if args.allow_create_group:
                _, _, omics = active_clients(args)
                result = {"request": result, "response": omics.create_run_group(**result)}
        elif args.command == "plan":
            result = run_plan(package=args.zip, manifest_path=args.manifest, manifest_uri=args.manifest_uri,
                              support_image=args.support_image, workflow_id=args.workflow_id, role_arn=args.role_arn,
                              output_uri=args.output_uri, run_group_id=args.run_group_id, engine=args.engine_version,
                              cache_id=args.cache_id)
        elif args.command == "create-cache":
            plan = read_json(args.plan)
            # Plans with a currently unsupported engine can describe a cache, but cannot create it.
            parse_s3_uri(args.cache_uri)
            key = plan["scientific_identity_sha256"]
            result = {"name": "hg001-" + key[:16], "cacheS3Location": args.cache_uri.rstrip("/") + "/" + key + "/",
                      "cacheBehavior": "CACHE_ON_FAILURE", "requestId": key,
                      "tags": {"Project": PROJECT, "ScientificIdentitySHA256": key}}
            if args.allow_create_cache:
                verify_run_plan(plan)
                _, identity, omics = active_clients(args)
                result["cacheBucketOwnerId"] = identity["Account"]
                result = {"request": result, "response": omics.create_run_cache(**result)}
        elif args.command == "submit":
            if not args.allow_paid_run:
                raise ValueError("Paid submission is disabled; use --allow-paid-run only after separate operator authorization")
            plan = read_json(args.plan)
            verify_run_plan(plan)  # Offline failures happen before any AWS call.
            session, identity, omics = active_clients(args)
            result = submit(plan, omics=omics, s3=client(session, "s3"), identity=identity,
                            preflight_report=read_json(args.preflight), engine_qualification_run=args.engine_qualification_run)
        else:
            _, _, omics = active_clients(args)
            result = collect_run_evidence(omics, args.run_id)
    except Exception as exc:  # CLI boundary: explicit nonzero status; nothing is silently skipped.
        print(f"HealthOmics operation blocked/failed: {exc}", file=sys.stderr)
        return 2
    output = json.dumps(result, indent=2, default=str) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output)
    print(output, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
