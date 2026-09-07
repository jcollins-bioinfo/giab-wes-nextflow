#!/usr/bin/env python3
"""Validate M2 source and preparation contracts without publishing any artifacts.

Validation checks remain active under Python optimization. Workspace operations
bind records to exact run IDs and the installed source manifest before hashing
contained source files. Canonical domains also require the reviewed Gate B.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .acquisition import checksum, destination, load_manifest, safe_root, validate_acquisition, validate_run_id
from .resources import config_path


def validate(schema: str | Path, data: dict[str, Any]) -> None:
    """Validate one JSON object against a Draft 2020-12 schema and formats."""
    Draft202012Validator(json.loads(Path(schema).read_text()), format_checker=FormatChecker()).validate(data)


def _validate_gate(gate: dict[str, Any]) -> None:
    """Reject internally contradictory target decisions before workspace reads."""
    if gate.get("classification") not in {"confirmed", "inferred", "unresolved", "contradicted"}:
        raise ValueError("invalid capture-design classification")
    if not isinstance(gate.get("canonical_domains_allowed"), bool):
        raise ValueError("canonical domain permission must be explicit")
    if gate["canonical_domains_allowed"] and gate["classification"] != "confirmed":
        raise ValueError("only confirmed capture-design evidence can authorize canonical domains")


def validate_workspace(workspace: str | Path, run_id: str) -> str:
    """Validate complete source evidence and any materialized preparation record.

    Returns a factual stage label. Source-only success does not establish target
    identity, biological execution, or permission to publish canonical results.
    """
    validate_run_id(run_id)
    root = safe_root(workspace)
    manifest_path = config_path("m2-resources.json")
    manifest = load_manifest()
    gate_path = config_path("m2-target-design.json")
    gate = json.loads(gate_path.read_text())
    _validate_gate(gate)
    acquisition_path = destination(root, f"registry/runs/{run_id}/acquisition.json")
    acquisition = json.loads(acquisition_path.read_text())
    validate_acquisition(acquisition, manifest, checksum(manifest_path), root, run_id=run_id)
    transformation_path = destination(root, f"registry/runs/{run_id}/transformation.json")
    if not transformation_path.exists():
        return "verified_sources_only"
    transformation = json.loads(transformation_path.read_text())
    if transformation.get("schema_version") != "1.0.0" or transformation.get("run_id") != run_id:
        raise ValueError("transformation schema or run identity mismatch")
    status = transformation.get("status")
    if status == "domains_materialized":
        # The canonical publisher owns the shared gate, interval and lineage
        # validation contract; this read-only call performs no Drive writes.
        from .publication import validate_prepared_workspace
        validate_prepared_workspace(root, run_id, manifest_path, gate_path)
        return "canonical_domains_validated"
    if status != "reference_prepared_domain_blocked" or transformation.get("domains") != []:
        raise ValueError("invalid or contradictory transformation status")
    references = transformation.get("reference", [])
    ids = [item.get("id") for item in references]
    if len(ids) != 3 or set(ids) != {"grch38_fasta", "grch38_fai", "grch38_dict"}:
        raise ValueError("incomplete reference artifact inventory")
    paths: set[str] = set()
    for item in references:
        relative, expected = item.get("path"), item.get("sha256")
        if not isinstance(relative, str) or relative in paths:
            raise ValueError("invalid reference artifact path")
        paths.add(relative)
        if not isinstance(expected, str) or not re.fullmatch("[0-9a-f]{64}", expected):
            raise ValueError("invalid reference artifact hash")
        path = destination(root, relative)
        if not path.is_file() or checksum(path) != expected:
            raise ValueError("reference artifact hash mismatch")
    return "reference_bytes_validated_domain_blocked"


def main(argv: list[str] | None = None) -> int:
    """Validate installed declarations or one complete, guarded local workspace."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace")
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    load_manifest()
    _validate_gate(json.loads(config_path("m2-target-design.json").read_text()))
    if args.workspace:
        if not args.run_id:
            parser.error("--run-id required with --workspace")
        status = validate_workspace(args.workspace, args.run_id)
    elif args.run_id:
        parser.error("--workspace required with --run-id")
    else:
        status = "installed_declarations_only"
    print(f"M2 contracts valid: {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
