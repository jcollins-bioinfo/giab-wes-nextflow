"""Publish and recover small validated M4 synthetic evidence through guarded paths.

The input contract, selected caller records and manifest form the JSON allowlist. Reference/read/BAM,
Nextflow work, raw logs, and canonical results are outside this interface. A
content-addressed bundle is visible as completed only after destination rehash,
schema/lineage validation, and an immutable registry write per caller selection. Interrupted copies
can be resumed; existing mismatching bytes are preserved and cause failure.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
from typing import Any

from jsonschema import Draft202012Validator

from . import __version__
from .acquisition import (checksum, destination, lock, now, safe_root,
                          validate_run_id, validate_timestamp, write_record)
from .m4_contracts import validate_m4_result_bundle as validate_result_bundle
from .resources import schema_path
from .m3_publication import _copy

SELECTIONS = {"gatk": ("gatk",), "deepvariant": ("deepvariant",),
              "both": ("gatk", "deepvariant")}


def _selection(callers: list[str] | tuple[str, ...]) -> str:
    """Resolve exactly one supported selection without silently sorting inputs."""
    for name, selected in SELECTIONS.items():
        if tuple(callers) == selected:
            return name
    raise ValueError("M4 publication requires an exact supported caller selection")


def _filenames(selection: str) -> tuple[str, ...]:
    """Return the complete stable JSON allowlist for one independent/both mode."""
    if selection not in SELECTIONS:
        raise ValueError("invalid M4 caller selection")
    return ("m4-inputs.json", *(f"m4-{caller}.json" for caller in SELECTIONS[selection]),
            "m4-manifest.json")


MAX_FILE_BYTES = 2 << 20


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject ambiguous duplicate keys at every JSON object depth."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate M4 publication metadata key")
        result[key] = value
    return result


def _read_record(path: Path) -> dict[str, Any]:
    """Read bounded regular JSON metadata after the existing destination guard."""
    source = destination(path.parent, path.name)
    if not source.is_file() or not 0 < source.stat().st_size <= MAX_FILE_BYTES:
        raise ValueError("missing or oversized M4 publication metadata")
    value = json.loads(source.read_text(), object_pairs_hook=_unique_pairs)
    if not isinstance(value, dict):
        raise ValueError("M4 publication metadata must be a JSON object")
    return value


def _root(value: str | Path) -> Path:
    """Apply the existing ancestor, symlink, and prohibited-folder safeguards."""
    return safe_root(value, allow_test_root=True)


def _private_root(value: str | Path) -> Path:
    """Restrict evidence publication to the established private project root."""
    root = safe_root(value)
    if root.name != "giab-wes-nextflow-private":
        raise ValueError("M4 private root must be named giab-wes-nextflow-private")
    return root


def _bundle(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Verify the allowlisted source bytes and their scientific lineage."""
    inventory: list[dict[str, Any]] = []
    manifest_path = destination(root, "m4-manifest.json")
    if not manifest_path.is_file() or not 0 < manifest_path.stat().st_size <= MAX_FILE_BYTES:
        raise ValueError("missing or oversized M4 manifest")
    manifest_header = _read_record(manifest_path)
    selection = _selection(manifest_header["data"]["selected_callers"])
    for name in _filenames(selection):
        path = destination(root, name)
        if not path.is_file() or not 0 < path.stat().st_size <= MAX_FILE_BYTES:
            raise ValueError(f"missing or oversized M4 JSON artifact: {name}")
        inventory.append({"filename": name, "bytes": path.stat().st_size,
                          "sha256": checksum(path)})
    artifacts = validate_result_bundle(root)
    manifest = artifacts["bundle"]
    if not manifest["synthetic"] or manifest["canonical"]:
        raise ValueError("M4 publication is restricted to synthetic evidence")
    return artifacts, inventory


def _validate_record(record: dict[str, Any]) -> None:
    """Validate publication metadata independently of mutable filesystem state."""
    schema = json.loads(schema_path("m4-publication.schema.json").read_text())
    Draft202012Validator(schema).validate(record)
    validate_timestamp(record["created_utc"])
    validate_run_id(record["run_id"])
    if [item["filename"] for item in record["artifacts"]] != list(_filenames(record["selection"])):
        raise ValueError("publication inventory must contain only the selected M4 JSON artifacts")
    manifest = next(item for item in record["artifacts"] if item["filename"] == "m4-manifest.json")
    if manifest["sha256"] != record["bundle_sha256"]:
        raise ValueError("publication manifest identity mismatch")


def _check_identity(record: dict[str, Any], artifacts: dict[str, Any],
                    inventory: list[dict[str, Any]]) -> None:
    """Bind the registry to validated run, code, and destination artifact identities."""
    _validate_record(record)
    manifest = artifacts["bundle"]
    expected = {"run_id": manifest["run_id"],
                "repository_sha": artifacts["bundle"]["data"]["repository_sha"],
                "producer_version": manifest["producer"]["version"],
                "selection": _selection(manifest["data"]["selected_callers"]),
                "artifacts": inventory}
    if any(record[key] != value for key, value in expected.items()):
        raise ValueError("publication provenance or artifact identity mismatch")


def _locations(drive: Path, run_id: str, bundle_hash: str, selection: str) -> tuple[Path, Path]:
    """Keep synthetic evidence and its registry separate from canonical namespaces."""
    final = destination(drive, f"evidence/synthetic/m4/bundles/{bundle_hash}")
    registry = destination(drive, f"registry/milestones/M4/synthetic/{run_id}/{selection}.json")
    return final, registry


def inventory_bundle(source: str | Path) -> dict[str, Any]:
    """Return a read-only publication estimate with no absolute private paths."""
    artifacts, inventory = _bundle(_root(source))
    return {"kind": "m4-synthetic-evidence-inventory", "run_id": artifacts["bundle"]["run_id"],
            "repository_sha": artifacts["bundle"]["data"]["repository_sha"],
            "artifacts": inventory, "bytes": sum(item["bytes"] for item in inventory),
            "canonical": False, "would_copy_genomic_bytes": False}


def publish_bundle(source: str | Path, drive_root: str | Path, *, dry_run: bool = False) -> dict[str, Any]:
    """Publish an append-only synthetic bundle; identical validated retries are no-ops."""
    stage, drive = _root(source), _private_root(drive_root)
    if stage == drive or stage in drive.parents or drive in stage.parents:
        raise ValueError("evidence staging and private root must be separate")
    artifacts, inventory = _bundle(stage)
    manifest = artifacts["bundle"]
    run_id = validate_run_id(manifest["run_id"])
    digest = next(item["sha256"] for item in inventory if item["filename"] == "m4-manifest.json")
    selection = _selection(manifest["data"]["selected_callers"])
    final, registry = _locations(drive, run_id, digest, selection)
    if dry_run:
        if registry.exists():
            _check_identity(_read_record(registry), artifacts, inventory)
        if final.exists():
            copied_artifacts, copied_inventory = _bundle(final)
            if copied_inventory != inventory or copied_artifacts != artifacts:
                raise ValueError("existing bundle identity differs during dry-run")
            if destination(final, "COMPLETED.json").exists():
                validate_publication(drive, run_id, selection=selection)
        return {**inventory_bundle(stage), "dry_run": True,
                "additional_bundle_bytes": 0 if final.exists() else sum(item["bytes"] for item in inventory)}
    drive.mkdir(parents=True, exist_ok=True)
    lock_path = destination(drive, "registry/milestones/M4/.publication.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock(lock_path):
        final, registry = _locations(drive, run_id, digest, selection)
        marker = destination(final, "COMPLETED.json")
        record = {"schema_version": "1.0.0", "kind": "m4-synthetic-evidence-publication",
                  "run_id": run_id, "selection": selection, "bundle_sha256": digest,
                  "repository_sha": artifacts["bundle"]["data"]["repository_sha"],
                  "producer_version": manifest["producer"]["version"],
                  "publisher_version": __version__, "publisher_architecture": platform.machine(),
                  "created_utc": now(), "synthetic": True, "canonical": False, "artifacts": inventory}
        if registry.exists():
            record = _read_record(registry)
        elif marker.exists():
            raise ValueError("completion marker exists without its registry")
        _check_identity(record, artifacts, inventory)
        if final.exists():
            checked, copied = _bundle(final)
            _check_identity(record, checked, copied)
        else:
            incomplete = destination(drive, f"incomplete/m4-synthetic/{digest}")
            incomplete.mkdir(parents=True, exist_ok=True)
            for item in inventory:
                _copy(destination(stage, item["filename"]), destination(incomplete, item["filename"]), item)
            if {child.name for child in incomplete.iterdir()} != set(_filenames(selection)):
                raise ValueError("unexpected artifact in incomplete evidence namespace")
            checked, copied = _bundle(incomplete)
            _check_identity(record, checked, copied)
            final.parent.mkdir(parents=True, exist_ok=True)
            os.replace(incomplete, final)
        write_record(registry, record)
        # The only acceptance marker is written last, after the registry and all
        # independently rehashed destination artifacts have been validated.
        write_record(destination(final, "COMPLETED.json"), record)
        return record


def validate_publication(drive_root: str | Path, run_id: str, *, selection: str = "both") -> tuple[Path, dict[str, Any]]:
    """Reject incomplete or corrupted publications before recovery or inspection."""
    drive = _private_root(drive_root)
    _filenames(selection)
    validate_run_id(run_id)
    registry = destination(drive, f"registry/milestones/M4/synthetic/{run_id}/{selection}.json")
    record = _read_record(registry)
    _validate_record(record)
    if record["run_id"] != run_id or record["selection"] != selection:
        raise ValueError("publication registry run mismatch")
    final, _ = _locations(drive, run_id, record["bundle_sha256"], selection)
    marker = _read_record(destination(final, "COMPLETED.json"))
    if marker != record:
        raise ValueError("completion marker differs from its registry")
    artifacts, inventory = _bundle(final)
    _check_identity(record, artifacts, inventory)
    return final, record


def hydrate_bundle(drive_root: str | Path, run_id: str, staging: str | Path,
                    *, dry_run: bool = False, selection: str = "both") -> dict[str, Any]:
    """Recover a completed bundle after runtime loss without recovering work files."""
    drive, stage = _private_root(drive_root), _root(staging)
    if stage == drive or stage in drive.parents or drive in stage.parents:
        raise ValueError("recovery staging and private root must be separate")
    source, record = validate_publication(drive, run_id, selection=selection)
    if dry_run:
        return {"kind": "m4-synthetic-evidence-hydration-inventory", "dry_run": True,
                "run_id": run_id, "bytes": sum(item["bytes"] for item in record["artifacts"]),
                "bundle_sha256": record["bundle_sha256"], "canonical": False}
    stage.mkdir(parents=True, exist_ok=True)
    with lock(destination(stage, ".m4-hydration.lock")):
        for item in record["artifacts"]:
            _copy(destination(source, item["filename"]), destination(stage, item["filename"]), item)
        artifacts, inventory = _bundle(stage)
        _check_identity(record, artifacts, inventory)
        write_record(destination(stage, "M4_EVIDENCE_RECOVERED.json"), record)
    return record


def main() -> None:
    """Expose inventory, publication, verification, and recovery as package commands."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inventory")
    inspect.add_argument("--bundle", required=True)
    publish = commands.add_parser("publish")
    publish.add_argument("--bundle", required=True)
    publish.add_argument("--drive-root", required=True)
    publish.add_argument("--dry-run", action="store_true")
    for name in ("validate", "hydrate"):
        command = commands.add_parser(name)
        command.add_argument("--drive-root", required=True)
        command.add_argument("--run-id", required=True)
        command.add_argument("--selection", choices=tuple(SELECTIONS), default="both")
        if name == "hydrate":
            command.add_argument("--staging", required=True)
            command.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.command == "inventory":
        result = inventory_bundle(args.bundle)
    elif args.command == "publish":
        result = publish_bundle(args.bundle, args.drive_root, dry_run=args.dry_run)
    elif args.command == "validate":
        result = validate_publication(args.drive_root, args.run_id, selection=args.selection)[1]
    else:
        result = hydrate_bundle(args.drive_root, args.run_id, args.staging, dry_run=args.dry_run, selection=args.selection)
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
