#!/usr/bin/env python3
"""Validate observed milestone state, evidence gates, and project versions.

Repository evidence identifies an already observed commit, never this record's
own future commit. A synthetically implemented milestone does not establish
canonical execution, public deployment, or release authorization.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = Path("docs/orchestration/project-state.schema.json")
COMPLETE_STATES = {"verified", "synthetically_verified", "canonically_executed", "released"}


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate keys instead of silently accepting the last value."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path: Path) -> dict[str, Any]:
    """Read one JSON object with duplicate-key detection."""
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_pairs)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _require_unique(items: Sequence[Mapping[str, Any]], field: str, label: str) -> None:
    """Reject ambiguous identities within one evidence collection."""
    values = [item[field] for item in items]
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {label} {field}")


def validate_document(
    document: Mapping[str, Any],
    schema: Mapping[str, Any],
    *,
    expected_version: str | None = None,
) -> None:
    """Validate structure and fail-closed scientific/execution state invariants.

    Required CI must apply to a recorded repository SHA. Successful baseline CI
    may be retained in an unfinished checkpoint, but cannot stand in for a
    future commit. Unknown input hashes remain null until verified.
    """
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(document), key=lambda error: str(error.path))
    if errors:
        raise ValueError("; ".join(f"{'/'.join(map(str, e.path)) or '/'}: {e.message}" for e in errors))
    # jsonschema's RFC3339 checker is an optional dependency. Validate timestamps
    # explicitly so minimal package installations retain the same safety gate.
    observed_at = document["observed_at"]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", observed_at) is None:
        raise ValueError("observed_at requires an ISO8601 timestamp with timezone")
    datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    if expected_version is not None and document["version"] != expected_version:
        raise ValueError("orchestration version differs from the package version")

    repositories = {
        value["full_name"]: value
        for value in document["repositories"].values()
        if value is not None
    }
    if len(repositories) != sum(value is not None for value in document["repositories"].values()):
        raise ValueError("pipeline and website repository identities must differ")
    for label, items, field in (
        ("input", document["required_inputs"], "id"),
        ("test", document["local_tests"], "name"),
        ("CI", document["ci"], "name"),
        ("environment", document["execution_environments"], "id"),
        ("blocker", document["external_blockers"], "id"),
    ):
        _require_unique(items, field, label)

    for item in document["required_inputs"]:
        if item["status"] == "verified" and item["sha256"] is None:
            raise ValueError("verified input requires a SHA-256 content identity")
    for check in document["ci"]:
        if check["repository"] not in repositories:
            raise ValueError("CI references an unrecorded repository")
        if check["status"] in {"success", "failure", "pending"}:
            if check["evidence_sha"] is None or check["run_url"] is None:
                raise ValueError("observed CI requires a commit SHA and run URL")
        if check["run_url"] is not None:
            pattern = rf"https://github.com/{re.escape(check['repository'])}/(?:actions/runs|runs)/[0-9]+(?:/attempts/[0-9]+)?"
            if re.fullmatch(pattern, check["run_url"]) is None:
                raise ValueError("CI run URL does not belong to its repository")
        if any(not url.startswith(f"https://github.com/{check['repository']}/") for url in check["job_urls"]):
            raise ValueError("CI job URL does not belong to its repository")

    for environment in document["execution_environments"]:
        if environment["status"] == "executed":
            if not environment["run_id"] or not environment["evidence_artifacts"]:
                raise ValueError("executed environment requires run identity and artifact evidence")
        if environment["canonical"] and environment["status"] != "executed":
            raise ValueError("canonical environment must have executed")
    publication = document["publication"]
    if publication["drive"] == "verified" or publication["public_evidence"] == "verified":
        if not publication["evidence_artifacts"]:
            raise ValueError("verified publication requires artifact evidence")
    if publication["deployment"] == "deployed" or publication["release"] == "released":
        if not publication["authorization_reference"] or not publication["evidence_artifacts"]:
            raise ValueError("deployment or release requires authorization and artifact evidence")

    state = document["state"]
    if state == "blocked" and not document["external_blockers"]:
        raise ValueError("blocked state requires an explicit blocker and owner action")
    if state in COMPLETE_STATES:
        required_checks = [check for check in document["ci"] if check["required"]]
        if not required_checks:
            raise ValueError("verified state requires observed required CI")
        for check in required_checks:
            if check["status"] != "success":
                raise ValueError("verified state requires all required CI to succeed")
            if check["evidence_sha"] != repositories[check["repository"]]["evidence_sha"]:
                raise ValueError("required CI SHA differs from the recorded repository evidence SHA")
        if not document["local_tests"] or any(test["status"] != "passed" for test in document["local_tests"]):
            raise ValueError("verified state requires passing local tests")
    if state in {"canonically_executed", "released"}:
        if not any(env["canonical"] and env["status"] == "executed" for env in document["execution_environments"]):
            raise ValueError("canonical completion requires immutable execution evidence")
        if not document["required_inputs"] or any(item["status"] != "verified" for item in document["required_inputs"]):
            raise ValueError("canonical completion requires verified input content identities")
        if document["external_blockers"]:
            raise ValueError("canonical completion cannot retain unresolved external blockers")
    if state == "released":
        if publication["release"] != "released" or publication["public_evidence"] != "verified":
            raise ValueError("released state requires published release and verified public evidence")
        if document["milestone"] in {"M8", "M9"} and publication["deployment"] != "deployed":
            raise ValueError("released website or Explorer requires verified public deployment")


def _package_version(root: Path) -> str:
    """Read the literal package version without importing mutable source code."""
    source = root / "src/giab_wes_nextflow/__init__.py"
    assignments = ast.parse(source.read_text(encoding="utf-8"), filename=str(source)).body
    values = [node.value.value for node in assignments if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets)
              and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)]
    if len(values) != 1:
        raise ValueError("package must have exactly one literal __version__")
    return values[0]


def _project_versions(value: Any) -> list[str]:
    """Find project_version literals/constants, excluding other producer versions."""
    versions: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"project_version", "pipeline_version"}:
                if isinstance(child, str):
                    versions.append(child)
                elif isinstance(child, dict) and isinstance(child.get("const"), str):
                    versions.append(child["const"])
            else:
                versions.extend(_project_versions(child))
    elif isinstance(value, list):
        for child in value:
            versions.extend(_project_versions(child))
    return versions


def validate_version_consistency(root: Path) -> str:
    """Check authoritative source/config/schema versions without rewriting history.

    Fixture producer versions are intentionally outside this scope: historical
    producers are provenance, not the current package version. Root and packaged
    config/schema project_version declarations must agree with __version__.
    """
    version = _package_version(root)
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    hatch = re.search(r'(?ms)^\[tool\.hatch\.version\]\s*(.*?)(?=^\[|\Z)', pyproject)
    if hatch is None or not re.search(r'(?m)^path\s*=\s*[\x22\x27]src/giab_wes_nextflow/__init__\.py[\x22\x27]\s*$', hatch.group(1)):
        raise ValueError("build metadata must read the canonical package version")
    nextflow = (root / "nextflow.config").read_text(encoding="utf-8")
    manifest = re.search(r"(?s)\bmanifest\s*\{(.*?)\}", nextflow)
    matches = re.findall(r"(?m)^\s*version\s*=\s*['\x22]([^'\x22]+)['\x22]", manifest.group(1) if manifest else "")
    if matches != [version]:
        raise ValueError("Nextflow manifest version differs from the package version")
    citation = (root / "CITATION.cff").read_text(encoding="utf-8")
    if re.findall(r"(?m)^version: ([^\n]+)$", citation) != [version]:
        raise ValueError("CITATION version differs from the package version")
    # These are active runtime producers/current golden expectations, not archived
    # evidence. Verify them explicitly so an old literal cannot pass new CI.
    producer = (root / "modules/local/emit_foundation_contract/main.nf").read_text()
    if f'"pipeline_version":"{version}"' not in producer:
        raise ValueError("foundation producer version differs from the package version")
    for relative in ("tests/snapshots/foundation.semantic.json", "schemas/run-contract.schema.json"):
        if _project_versions(read_json(root / relative)) != [version]:
            raise ValueError(f"{relative} current foundation version differs from the package version")
    for relative in ("config", "schemas", "src/giab_wes_nextflow/data/config", "src/giab_wes_nextflow/data/schemas"):
        declarations = 0
        for path in sorted((root / relative).rglob("*.json")):
            for declared in _project_versions(read_json(path)):
                declarations += 1
                if declared != version:
                    raise ValueError(f"{path.relative_to(root)} project_version differs from {version}")
        if not declarations:
            raise ValueError(f"missing {relative} project_version declarations")
    for kind in ("config", "schemas"):
        packaged_root = root / "src/giab_wes_nextflow/data" / kind
        for packaged in sorted(packaged_root.rglob("*.json")):
            authoritative = root / kind / packaged.relative_to(packaged_root)
            if not authoritative.is_file() or authoritative.read_bytes() != packaged.read_bytes():
                raise ValueError(f"packaged resource differs from authoritative {authoritative.relative_to(root)}")
    return version


def validate_repository(root: Path) -> int:
    """Validate state and all required M3-M9 checkpoint identities and gates."""
    version = validate_version_consistency(root)
    schema = read_json(root / SCHEMA_PATH)
    paths = [root / "docs/orchestration/project-state.json"]
    paths.extend(root / f"docs/orchestration/checkpoints/M{number}.json" for number in range(3, 10))
    current_major = 0
    for path in paths:
        document = read_json(path)
        # Historical checkpoints retain the producer version observed at their
        # evidence commit. Only the live project-state follows current source.
        validate_document(document, schema, expected_version=version if path == paths[0] else None)
        if path.name == "project-state.json":
            if document["record_type"] != "project_state":
                raise ValueError("project-state.json has the wrong record_type")
            current_major = int(document["milestone"].split(".")[0][1:])
        elif document["record_type"] != "checkpoint" or document["milestone"] != path.stem:
            raise ValueError(f"{path.name} checkpoint identity disagrees with its filename")
        elif int(document["milestone"][1:]) > current_major and document["state"] != "not_started":
            raise ValueError(f"{path.name} optimistically advances beyond the current milestone")
    return len(paths)


def main(argv: Sequence[str] | None = None) -> int:
    """Run repository validation; return a nonzero CLI status on invalid evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        count = validate_repository(args.root.resolve())
    except (ValueError, OSError) as error:
        parser.exit(1, f"orchestration invalid: {error}\n")
    print(f"orchestration valid: {count} records; project versions consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
