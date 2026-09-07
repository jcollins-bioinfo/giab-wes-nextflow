"""Publish and hydrate verified source caches without creating Gate B results.

A mirror is a reusable source cache, never a canonical scientific result. Legacy
mirrors require their exact historical manifest and fresh MD5/SHA-256 byte checks
before recovery. Historical repository and manifest identities remain explicit.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from . import __version__
from .acquisition import (checksum, destination, load_manifest, lock, now, observation,
                          safe_root, validate_acquisition, validate_run_id,
                          validate_source_bytes, validate_timestamp, write_record)
from .resources import config_path, schema_path

def _manifest(source_manifest: str | Path | None) -> tuple[dict[str, Any], str]:
    """Bind explicit historical manifests only when current resource contracts agree."""
    current = load_manifest()
    path = Path(source_manifest) if source_manifest else config_path("m2-resources.json")
    source = load_manifest(path, allow_historical_version=source_manifest is not None)
    current_resources = {item["id"]: item for item in current["resources"]}
    source_resources = {item["id"]: item for item in source["resources"]}
    if source_resources != current_resources:
        raise ValueError("historical resource contracts differ from the current canonical manifest")
    return source, checksum(path)


def _validate_mirror(record: dict[str, Any], spec: dict[str, Any], manifest_hash: str,
                     run_id: str) -> None:
    """Validate record shape and exact identities independently of filesystem bytes."""
    schema = json.loads(schema_path("m2-source-mirror.schema.json").read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(record)
    validate_timestamp(record["created_utc"], "mirror created_utc")
    if record["run_id"] != run_id or record["source_manifest_sha256"] != manifest_hash:
        raise ValueError("mirror run or source manifest identity mismatch")
    resources = {item["id"]: item for item in spec["resources"]}
    objects = record["objects"]
    ids = [item["id"] for item in objects]
    if len(ids) != len(set(ids)) or set(ids) != set(resources):
        raise ValueError("mirror requires a complete unique canonical inventory")
    for item in objects:
        resource = resources[item["id"]]
        if item["destination"] != resource["destination"]:
            raise ValueError("mirror destination disagrees with manifest")
        if resource["bytes"] is not None and item["bytes"] != resource["bytes"]:
            raise ValueError("mirror size disagrees with manifest")
    if "acquisition" in record:
        validate_acquisition(record["acquisition"], spec, manifest_hash, run_id=run_id)
        observations = {item["id"]: item for item in record["acquisition"]["observations"]}
        if any(item["sha256"] != observations[item["id"]]["sha256"] or
               item["bytes"] != observations[item["id"]]["bytes"] for item in objects):
            raise ValueError("mirror objects disagree with embedded acquisition")


def _copy_verified(source: Path, target: Path, resource: dict[str, Any], observed: dict[str, Any]) -> None:
    """Promote a destination only after expected MD5, SHA-256 and size checks."""
    target.parent.mkdir(parents=True, exist_ok=True)
    # Share acquisition's lock namespace so hydration cannot race an acquire
    # operation or another publisher writing the same source object.
    with lock(Path(str(target) + ".lock")):
        target = destination(target.parent, target.name)
        source = destination(source.parent, source.name)
        if target.exists():
            validate_source_bytes(target, resource, observed)
            return
        temporary = destination(target.parent, target.name + ".incomplete")
        shutil.copy2(source, temporary)
        validate_source_bytes(temporary, resource, observed)
        os.replace(temporary, target)


def mirror_sources(staging: str | Path, drive_root: str | Path, run_id: str,
                   repository_sha: str, source_manifest: str | Path | None = None) -> Path:
    """Mirror a complete validated acquisition; identical retries are true no-ops.

    Existing records preserve their original timestamp and provenance. A record
    conflict is checked before copies; cache objects are always rehashed on reuse.
    """
    validate_run_id(run_id)
    if not isinstance(repository_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", repository_sha):
        raise ValueError("repository SHA must be an exact commit")
    stage, drive = safe_root(staging), safe_root(drive_root)
    if stage == drive or stage in drive.parents or drive in stage.parents:
        raise ValueError("staging and Drive must be separate roots")
    spec, manifest_hash = _manifest(source_manifest)
    acquisition_path = destination(stage, f"registry/runs/{run_id}/acquisition.json")
    acquisition = json.loads(acquisition_path.read_text())
    validate_acquisition(acquisition, spec, manifest_hash, stage, run_id=run_id)
    observations = {item["id"]: item for item in acquisition["observations"]}
    out = destination(drive, f"registry/runs/{run_id}/verified-source-mirror.json")
    inventory = [{"id": item["id"], "destination": item["destination"],
                  "sha256": observations[item["id"]]["sha256"], "bytes": observations[item["id"]]["bytes"]}
                 for item in spec["resources"]]
    existing = json.loads(out.read_text()) if out.exists() else None
    if existing is not None:
        _validate_mirror(existing, spec, manifest_hash, run_id)
        if (existing["repository_sha"] != repository_sha or
            {item["id"]: item for item in existing["objects"]} != {item["id"]: item for item in inventory} or
            ("acquisition" in existing and existing["acquisition"] != acquisition)):
            raise FileExistsError("immutable mirror identity conflict")
    for resource in spec["resources"]:
        source = destination(stage, resource["destination"])
        target = destination(drive, "cache/verified-sources/" + resource["destination"])
        _copy_verified(source, target, resource, observations[resource["id"]])
    if existing is not None:
        return out
    record = {"schema_version": "1.1.0", "kind": "verified-source-mirror-not-gate-b",
              "run_id": run_id, "source_manifest_sha256": manifest_hash,
              "repository_sha": repository_sha, "runtime_architecture": platform.machine(),
              "created_utc": now(), "publisher_version": __version__, "objects": inventory,
              "acquisition": acquisition}
    _validate_mirror(record, spec, manifest_hash, run_id)
    write_record(out, record)
    return out


def hydrate_sources(drive_root: str | Path, staging: str | Path, run_id: str,
                    source_manifest: str | Path | None = None,
                    recovery_run_id: str | None = None, *,
                    repository_sha: str | None = None) -> int:
    """Recover source bytes and evidence without downloading or claiming Gate B.

    Legacy records omit acquisition evidence. They require an explicit exact old
    manifest and a distinct recovery run ID. Current observations are generated
    only after source and destination bytes pass declared MD5 and observed SHA-256
    checks, and retain the historical mirror identities as recovery lineage.
    The optional current repository SHA must come from a verified launcher; null
    explicitly means source-code identity is unqualified for this hydration.
    """
    validate_run_id(run_id)
    target_run = validate_run_id(recovery_run_id or run_id)
    if repository_sha is not None and (not isinstance(repository_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", repository_sha)):
        raise ValueError("current repository SHA must be an exact commit or null")
    drive, stage = safe_root(drive_root), safe_root(staging)
    if stage == drive or stage in drive.parents or drive in stage.parents:
        raise ValueError("staging and Drive must be separate roots")
    spec, manifest_hash = _manifest(source_manifest)
    mirror_path = destination(drive, f"registry/runs/{run_id}/verified-source-mirror.json")
    record = json.loads(mirror_path.read_text())
    _validate_mirror(record, spec, manifest_hash, run_id)
    if record["schema_version"] == "1.0.0" and (source_manifest is None or target_run == run_id):
        raise ValueError("legacy recovery requires --source-manifest and a distinct --recovery-run-id")
    resources = {item["id"]: item for item in spec["resources"]}
    for item in record["objects"]:
        source = destination(drive, "cache/verified-sources/" + item["destination"])
        validate_source_bytes(source, resources[item["id"]], item)
    lineage = {"kind": "verified-source-cache-hydration-not-gate-b", "source_run_id": run_id,
               "source_repository_sha": record["repository_sha"],
               "source_manifest_sha256": manifest_hash, "source_mirror_sha256": checksum(mirror_path)}
    acquisition_path = destination(stage, f"registry/runs/{target_run}/acquisition.json")
    current = load_manifest()
    current_hash = checksum(config_path("m2-resources.json"))
    existing = json.loads(acquisition_path.read_text()) if acquisition_path.exists() else None
    if existing is not None:
        if target_run == run_id and "acquisition" in record:
            if existing != record["acquisition"]:
                raise FileExistsError("immutable hydration acquisition conflict")
            validate_acquisition(existing, spec, manifest_hash, run_id=target_run)
        else:
            validate_acquisition(existing, current, current_hash, run_id=target_run)
            if any(item["response"] != lineage for item in existing["observations"]):
                raise FileExistsError("immutable hydration lineage conflict")
    for item in record["objects"]:
        source = destination(drive, "cache/verified-sources/" + item["destination"])
        target = destination(stage, item["destination"])
        _copy_verified(source, target, resources[item["id"]], item)
    if existing is None:
        if target_run == run_id and "acquisition" in record:
            existing = record["acquisition"]
        else:
            observations = [observation(item, destination(stage, item["destination"]), "verified", 0,
                                        lineage, item["url"]) for item in current["resources"]]
            existing = {"schema_version": "1.0.0", "run_id": target_run, "created_utc": now(),
                        "source_manifest_sha256": current_hash, "observations": observations}
    expected_spec, expected_hash = (spec, manifest_hash) if target_run == run_id else (current, current_hash)
    validate_acquisition(existing, expected_spec, expected_hash, stage, run_id=target_run)
    write_record(acquisition_path, existing)
    hydration_path = destination(stage, f"registry/runs/{target_run}/hydration.json")
    prior_hydration = json.loads(hydration_path.read_text()) if hydration_path.exists() else None
    hydration_schema = json.loads(schema_path("m2-source-hydration.schema.json").read_text())
    if prior_hydration is not None:
        Draft202012Validator(hydration_schema, format_checker=FormatChecker()).validate(prior_hydration)
        validate_timestamp(prior_hydration["created_utc"], "hydration created_utc")
        expected_identity = {"run_id": target_run, "repository_sha": repository_sha,
                             "acquisition_sha256": checksum(acquisition_path), "source": lineage,
                             "validated_objects": len(record["objects"])}
        if any(prior_hydration[key] != value for key, value in expected_identity.items()):
            raise FileExistsError("immutable record conflict")
        # A verification retry preserves the producing runtime, timestamp and
        # publisher version rather than attributing old records to new code.
        hydration = prior_hydration
    else:
        hydration = {"schema_version": "1.0.0", "run_id": target_run, "publisher_version": __version__,
                     "repository_sha": repository_sha, "created_utc": now(),
                     "runtime_architecture": platform.machine(), "acquisition_sha256": checksum(acquisition_path),
                     "source": lineage, "validated_objects": len(record["objects"])}
        Draft202012Validator(hydration_schema, format_checker=FormatChecker()).validate(hydration)
        validate_timestamp(hydration["created_utc"], "hydration created_utc")
    write_record(hydration_path, hydration)
    return len(record["objects"])


def main(argv: list[str] | None = None) -> int:
    """Run guarded mirror publication or explicit source-cache hydration."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--drive-root", required=True)
    parser.add_argument("--staging", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--repository-sha")
    parser.add_argument("--hydrate", action="store_true")
    parser.add_argument("--source-manifest")
    parser.add_argument("--recovery-run-id")
    args = parser.parse_args(argv)
    if args.hydrate:
        result = hydrate_sources(args.drive_root, args.staging, args.run_id, args.source_manifest, args.recovery_run_id, repository_sha=args.repository_sha)
    else:
        if args.recovery_run_id:
            parser.error("--recovery-run-id is only valid with --hydrate")
        result = mirror_sources(args.staging, args.drive_root, args.run_id, args.repository_sha, args.source_manifest)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
