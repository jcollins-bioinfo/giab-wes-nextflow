#!/usr/bin/env python3
"""Publish M2 evidence only after gate, lineage, and destination verification.

The packaged capture decision is authoritative for the CLI. A preparation status
string is never authorization to publish a domain. Existing completed runs are
immutable: retries revalidate their inventory, bytes, registry, and marker.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from .acquisition import checksum, load_manifest, lock, now, safe_root, validate_acquisition
from .preparation import PRIMARY, intersect, merge, read_bed, read_dict
from .resources import config_path, schema_path

SHA256 = re.compile(r"^[0-9a-f]{64}$")
DOMAIN_PARENTS = {
    "T_design": ["capture_targets_lifted"],
    "R_call": ["T_design"],
    "R_eval_full": ["T_design", "hg001_v421_high_confidence_bed"],
    "R_eval_holdout": ["R_eval_full"],
}
REFERENCE_IDS = {"grch38_fasta", "grch38_fai", "grch38_dict"}
_HASH_SCHEMA = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_LIFTOVER_COUNT_FIELDS = (
    "input_intervals", "input_bases", "lifted_intervals", "lifted_bases",
    "rejected_intervals", "split_intervals", "merged_intervals", "altered_length_intervals",
)
_LIFTOVER_PROPERTIES = {
    "tool": {"const": "Picard LiftOverIntervalList"}, "required_version": {"const": "3.1.1"},
    "observed_version": {"type": "string", "minLength": 1},
    "min_liftover_pct": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
    "lifted_bed_path": {"type": "string", "minLength": 1},
    **{field: _HASH_SCHEMA for field in ("source_sha256", "source_dict_sha256", "chain_sha256",
                                        "lifted_bed_sha256", "rejected_sha256")},
    **{field: {"type": "integer", "minimum": 0} for field in _LIFTOVER_COUNT_FIELDS},
}
_TRANSFORMATION_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["schema_version", "run_id", "status", "capture_design_classification", "reference", "liftover", "domains"],
    "properties": {
        "schema_version": {"const": "1.0.0"}, "run_id": {"type": "string", "minLength": 1},
        "status": {"const": "domains_materialized"}, "capture_design_classification": {"const": "confirmed"},
        "reference": {"type": "array", "minItems": 3, "maxItems": 3, "items": {
            "type": "object", "additionalProperties": False, "required": ["id", "path", "sha256"],
            "properties": {"id": {"enum": sorted(REFERENCE_IDS)}, "path": {"type": "string", "minLength": 1},
                           "sha256": _HASH_SCHEMA}}},
        "liftover": {"type": "object", "additionalProperties": False,
                     "required": list(_LIFTOVER_PROPERTIES), "properties": _LIFTOVER_PROPERTIES},
        "domains": {"type": "array", "minItems": 4, "maxItems": 4, "items": {"type": "object"}},
    },
}
_TARGET_DECISION_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["schema_version", "classification", "canonical_domains_allowed", "approved_artifacts",
                 "candidate", "min_liftover_pct", "primary_evidence", "block_reason"],
    "properties": {
        "schema_version": {"const": "1.0.0"}, "classification": {"const": "confirmed"},
        "canonical_domains_allowed": {"const": True}, "candidate": {"type": "string", "minLength": 1},
        "block_reason": {"type": ["string", "null"]},
        "min_liftover_pct": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
        "approved_artifacts": {"type": "object", "additionalProperties": False,
                               "required": ["target_bed_sha256", "source_dict_sha256"],
                               "properties": {key: _HASH_SCHEMA for key in ("target_bed_sha256", "source_dict_sha256")}},
        "primary_evidence": {"type": "array", "minItems": 1, "items": {
            "type": "object", "additionalProperties": False, "required": ["finding", "url"],
            "properties": {"finding": {"type": "string", "minLength": 1},
                           "url": {"type": "string", "format": "uri", "pattern": "^https://"}}}},
    },
}


@dataclass(frozen=True)
class Artifact:
    """One validated source and its immutable publication identity."""

    artifact_id: str
    relative: str
    source: Path
    sha256: str
    bytes: int


def _safe_path(root: Path, relative: str = "") -> Path:
    """Reject traversal, forbidden names, and symlinks before dereferencing."""
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("unsafe publication path")
    path = root / rel
    for component in (path, *path.parents):
        if "DO NOT ACCESS WITH CHATGPT" in component.name:
            raise PermissionError("workspace safety marker or forbidden path")
        if component.is_symlink():
            raise ValueError("symlink in publication path")
    return path


def _root(value: str | Path) -> Path:
    """Apply acquisition root policy without losing evidence of symlinks."""
    path = _safe_path(Path(value).expanduser().absolute())
    return safe_root(path)


def _read_json(path: Path) -> dict[str, Any]:
    """Load a JSON object from a regular, non-symlink control file."""
    _safe_path(path)
    if not path.is_file():
        raise ValueError(f"missing evidence file: {path.name}")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"evidence must be an object: {path.name}")
    return value


def _validate_schema(schema: dict[str, Any], value: dict[str, Any], name: str) -> None:
    """Validate a contract schema and give callers one consistent error type."""
    try:
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    except ValidationError as exc:
        raise ValueError(f"{name} validation failed: {exc.message}") from exc


def _schema(name: str, value: dict[str, Any]) -> None:
    """Validate a packaged schema, reporting contract failures as ValueError."""
    _validate_schema(_read_json(schema_path(name)), value, name)


def _digest(value: Any, label: str) -> str:
    """Require a complete lowercase SHA-256 identity."""
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise ValueError(f"invalid {label} SHA-256")
    return value


def _artifact(stage: Path, relative: str, artifact_id: str, expected: str,
              publication_prefix: str = "") -> Artifact:
    """Bind an artifact record to existing bytes before publication."""
    if not isinstance(relative, str) or not relative or relative == ".":
        raise ValueError("prepared artifact path missing")
    source = _safe_path(stage, relative)
    if not source.is_file() or checksum(source) != _digest(expected, artifact_id):
        raise ValueError(f"unverified prepared artifact: {artifact_id}")
    return Artifact(artifact_id, str(Path(publication_prefix) / relative), source,
                    expected, source.stat().st_size)


def _gate(path: Path, transformation: dict[str, Any]) -> dict[str, Any]:
    """Bind liftover provenance to the authoritative confirmed target decision."""
    gate = _read_json(path)
    if (gate.get("schema_version") != "1.0.0"
            or gate.get("classification") != "confirmed"
            or gate.get("canonical_domains_allowed") is not True):
        raise ValueError("Gate B blocked: capture decision is not confirmed")
    _validate_schema(_TARGET_DECISION_SCHEMA, gate, "confirmed target decision")
    approved = gate.get("approved_artifacts")
    if not isinstance(approved, dict):
        raise ValueError("Gate B confirmed decision lacks approved artifacts")
    liftover = transformation.get("liftover", {})
    for key, field in (("target_bed_sha256", "source_sha256"),
                       ("source_dict_sha256", "source_dict_sha256")):
        expected = _digest(approved.get(key), key)
        if liftover.get(field) != expected:
            raise ValueError("Gate B approved source identity does not match liftover")
    threshold = gate.get("min_liftover_pct")
    if (isinstance(threshold, bool) or not isinstance(threshold, (float, int))
            or not 0 < threshold <= 1 or liftover.get("min_liftover_pct") != threshold):
        raise ValueError("Gate B liftover threshold mismatch")
    if (transformation.get("capture_design_classification") != "confirmed"
            or not isinstance(gate.get("primary_evidence"), list)
            or not gate["primary_evidence"]):
        raise ValueError("Gate B decision lacks confirmed source evidence")
    return gate


def _reference_lineage(reference: dict[str, Artifact], sources: dict[str, Artifact]) -> None:
    """Verify decompressed reference identity and matching dictionary/index lengths."""
    digest = hashlib.sha256()
    with gzip.open(sources["grch38_no_alt_fasta_gz"].source, "rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    if digest.hexdigest() != reference["grch38_fasta"].sha256:
        raise ValueError("prepared reference is not derived from acquired reference")
    lengths: dict[str, int] = {}
    index_expected: dict[str, list[int]] = {}
    current: str | None = None
    short_line = False
    with reference["grch38_fasta"].source.open("rb") as stream:
        while line := stream.readline():
            if line.startswith(b">"):
                current = line[1:].split()[0].decode("ascii")
                if current in lengths:
                    raise ValueError("duplicate reference contig")
                lengths[current] = 0
                index_expected[current] = [0, stream.tell(), 0, 0]
                short_line = False
            elif current is None or not line.strip():
                raise ValueError("reference sequence lacks a header or contains blank lines")
            else:
                bases = len(line.rstrip(b"\r\n"))
                if short_line:
                    raise ValueError("short reference line before end of contig")
                if index_expected[current][2] == 0:
                    index_expected[current][2:] = [bases, len(line)]
                else:
                    width = index_expected[current][2]
                    if bases > width:
                        raise ValueError("inconsistent reference line width")
                    short_line = bases < width
                lengths[current] += bases
                index_expected[current][0] += bases
    dictionary = read_dict(reference["grch38_dict"].source)
    dictionary_lines = [line for line in reference["grch38_dict"].source.read_text().splitlines()
                        if line.startswith("@SQ\t")]
    index: dict[str, list[int]] = {}
    for line in reference["grch38_fai"].source.read_text().splitlines():
        fields = line.split("\t")
        if len(fields) != 5 or fields[0] in index:
            raise ValueError("invalid prepared FASTA index")
        index[fields[0]] = [int(field) for field in fields[1:]]
    if (not lengths or lengths != dictionary or len(dictionary_lines) != len(lengths)
            or index_expected != index):
        raise ValueError("reference, dictionary, and index coordinates disagree")


def _domains(stage: Path, run_id: str, transformation: dict[str, Any],
             reference: dict[str, Artifact], sources: dict[str, Artifact]) -> list[Artifact]:
    """Recompute fixed domain relations and summaries from verified input bytes."""
    liftover = transformation["liftover"]
    if (liftover.get("tool") != "Picard LiftOverIntervalList"
            or liftover.get("required_version") != "3.1.1"
            or re.search(r"(?<![0-9.])3\.1\.1(?![0-9.])", str(liftover.get("observed_version"))) is None
            or liftover.get("chain_sha256") != sources["ucsc_hg19_to_hg38_chain"].sha256):
        raise ValueError("invalid liftover tool or chain lineage")
    lifted = _artifact(stage, liftover.get("lifted_bed_path"), "capture_targets_lifted",
                       liftover.get("lifted_bed_sha256"), "prepared")
    rejected = _artifact(stage, f"cache/{run_id}/targets.rejected.interval_list",
                         "capture_targets_rejected", liftover.get("rejected_sha256"), "prepared")
    lengths = read_dict(reference["grch38_dict"].source)
    rows = read_bed(lifted.source, lengths)
    rejects = [line for line in rejected.source.read_text().splitlines()
               if line and not line.startswith("@")]
    count_fields = _LIFTOVER_COUNT_FIELDS
    if any(type(liftover.get(key)) is not int or liftover[key] < 0 for key in count_fields):
        raise ValueError("invalid liftover audit counts")
    if (liftover["input_intervals"] == 0 or liftover["input_bases"] == 0
            or liftover["lifted_intervals"] != len(rows)
            or liftover["lifted_bases"] != sum(end - start for _, start, end, _ in rows)
            or liftover["rejected_intervals"] != len(rejects)
            or liftover["merged_intervals"] != len(merge(rows))
            or liftover["split_intervals"] != max(0, len(rows) + len(rejects) - liftover["input_intervals"])
            or liftover["altered_length_intervals"] > len(rows)):
        raise ValueError("liftover audit does not match artifact bytes")
    design = merge(rows)
    full = intersect(merge(read_bed(sources["hg001_v421_high_confidence_bed"].source, lengths)), design)
    expected = {
        "T_design": design,
        "R_call": merge((c, max(0, start - 100), min(lengths[c], end + 100)) for c, start, end in design),
        "R_eval_full": full,
        "R_eval_holdout": [row for row in full if row[0] in {"chr20", "chr21", "chr22"}],
    }
    domains = transformation.get("domains")
    if (not isinstance(domains, list) or len(domains) != 4
            or {item.get("artifact_id") for item in domains} != set(DOMAIN_PARENTS)):
        raise ValueError("incomplete prepared domain inventory")
    artifacts = [lifted, rejected]
    for domain in domains:
        _schema("m2-domain.schema.json", domain)
        identity = domain["artifact_id"]
        if domain["path"] != f"{identity}.bed":
            raise ValueError("noncanonical domain path")
        artifact = _artifact(stage, f"references/domains/{domain['path']}", identity,
                             domain["sha256"], "prepared")
        observed = [row[:3] for row in read_bed(artifact.source, lengths, allowed=tuple(lengths))]
        rows = expected[identity]
        per_contig = {c: {"interval_count": len([r for r in rows if r[0] == c]),
                          "bases": sum(end - start for chrom, start, end in rows if chrom == c)}
                      for c in PRIMARY if any(row[0] == c for row in rows)}
        if (observed != rows or domain["parents"] != DOMAIN_PARENTS[identity]
                or domain["dictionary_sha256"] != reference["grch38_dict"].sha256
                or domain["generation"].get("run_id") != run_id
                or domain["interval_count"] != len(rows)
                or domain["bases"] != sum(end - start for _, start, end in rows)
                or domain["per_contig"] != per_contig):
            raise ValueError("domain lineage or measured interval summary mismatch")
        artifacts.append(artifact)
    return artifacts


def _validated_files(stage: Path, run_id: str, manifest: Path, target_decision: Path) -> list[Artifact]:
    """Validate schemas, source checksums, gate binding, and prepared lineage."""
    spec = load_manifest(manifest)
    acquisition_path = _safe_path(stage, f"registry/runs/{run_id}/acquisition.json")
    transformation_path = _safe_path(stage, f"registry/runs/{run_id}/transformation.json")
    acquisition = _read_json(acquisition_path)
    transformation = _read_json(transformation_path)
    _gate(target_decision, transformation)
    _validate_schema(_TRANSFORMATION_SCHEMA, transformation, "publication transformation")
    _schema("m2-acquisition.schema.json", acquisition)
    validate_acquisition(acquisition, spec, checksum(manifest), stage, run_id=run_id)
    if (acquisition["run_id"] != run_id or transformation.get("run_id") != run_id
            or transformation.get("schema_version") != "1.0.0"
            or transformation.get("status") != "domains_materialized"):
        raise ValueError("Gate B blocked: run identity or transformation contract mismatch")
    if acquisition["source_manifest_sha256"] != checksum(manifest):
        raise ValueError("acquisition manifest does not match publication manifest")
    observations = acquisition["observations"]
    verified = {item["id"]: item for item in observations}
    if len(verified) != len(observations) or set(verified) != {item["id"] for item in spec["resources"]}:
        raise ValueError("incomplete or unexpected acquisition inventory")
    sources: dict[str, Artifact] = {}
    for item in spec["resources"]:
        record = verified[item["id"]]
        artifact = _artifact(stage, item["destination"], item["id"], record["sha256"])
        sources[item["id"]] = artifact
    reference_records = transformation.get("reference")
    if (not isinstance(reference_records, list) or len(reference_records) != 3
            or {item.get("id") for item in reference_records} != REFERENCE_IDS):
        raise ValueError("incomplete prepared reference inventory")
    reference = {item["id"]: _artifact(stage, item["path"], item["id"], item["sha256"], "prepared")
                 for item in reference_records}
    _reference_lineage(reference, sources)
    files = list(sources.values()) + list(reference.values())
    files += _domains(stage, run_id, transformation, reference, sources)
    for identity, source in (("acquisition", acquisition_path), ("transformation", transformation_path),
                             ("source_manifest", manifest), ("target_decision", target_decision)):
        files.append(Artifact(identity, f"evidence/{identity}.json", source, checksum(source), source.stat().st_size))
    if len({item.relative for item in files}) != len(files) or len({item.artifact_id for item in files}) != len(files):
        raise ValueError("duplicate publication artifact identity or path")
    return files


def validate_prepared_workspace(staging: str | Path, run_id: str,
                                source_manifest: str | Path | None = None,
                                target_decision: str | Path | None = None) -> list[Artifact]:
    """Validate a publishable prepared workspace without writing any artifact.

    This is the shared publication and validation CLI boundary. A confirmed
    target decision, complete acquisition inventory, and byte-validated fixed
    domain relations are mandatory. Explicit decisions support synthetic tests.
    """
    run_id = str(run_id)
    if run_id in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9._-]+", run_id):
        raise ValueError("invalid run id")
    stage = _root(staging)
    manifest = _safe_path(Path(source_manifest or config_path("m2-resources.json")).absolute())
    decision = _safe_path(Path(target_decision or config_path("m2-target-design.json")).absolute())
    return _validated_files(stage, run_id, manifest, decision)


def _inventory(files: list[Artifact]) -> list[dict[str, Any]]:
    """Create the one canonical expected inventory from validated artifacts."""
    return [{"artifact_id": item.artifact_id, "path": item.relative,
             "source_sha256": item.sha256, "destination_sha256": item.sha256, "bytes": item.bytes}
            for item in files]


def _tree_files(root: Path) -> set[str]:
    """Enumerate a publication tree while rejecting links and unsafe subfolders."""
    paths: set[str] = set()
    for directory, names, files in os.walk(root, followlinks=False):
        for name in names + files:
            path = _safe_path(Path(directory), name)
            if name in files:
                if not path.is_file():
                    raise ValueError("nonregular publication object")
                paths.add(str(path.relative_to(root)))
    return paths


def _verify_publication(path: Path, files: list[Artifact], run_id: str) -> dict[str, Any]:
    """Rehash every durable object and reject inventory drift on every retry."""
    manifest = _read_json(_safe_path(path, "manifest.json"))
    if (set(manifest) != {"schema_version", "milestone", "run_id", "created_utc", "files"}
            or manifest["schema_version"] != "1.0.0" or manifest["milestone"] != "m2_data_provenance"
            or manifest["run_id"] != run_id or manifest["files"] != _inventory(files)):
        raise ValueError("immutable publication manifest conflict")
    expected = {item.relative for item in files} | {"manifest.json"}
    if _safe_path(path, "COMPLETED.json").exists():
        expected.add("COMPLETED.json")
    if _tree_files(path) != expected:
        raise ValueError("unexpected or missing durable publication artifacts")
    for item in files:
        destination = _safe_path(path, item.relative)
        if destination.stat().st_size != item.bytes or checksum(destination) != item.sha256:
            raise ValueError("durable artifact rehash failed")
    return manifest


def _write_exclusive(path: Path, value: dict[str, Any]) -> None:
    """Write an append-only control object; never truncate an existing record."""
    _safe_path(path)
    with path.open("x") as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def publish(drive_root: str | Path, staging: str | Path, run_id: str,
            source_manifest: str | Path | None = None,
            target_decision: str | Path | None = None) -> tuple[Path, bool]:
    """Publish a fully validated M2 run, or reverify an immutable completed run.

    ``target_decision`` permits complete decision fixtures in synthetic tests;
    it is not a gate bypass. The CLI always uses the packaged decision. The
    completion marker is written only after destination and registry validation.
    """
    run_id = str(run_id)
    if run_id in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9._-]+", run_id):
        raise ValueError("invalid run id")
    drive = _root(drive_root)
    files = validate_prepared_workspace(staging, run_id, source_manifest, target_decision)
    base = _safe_path(drive, "m2_data_provenance")
    incomplete = _safe_path(base, f"runs/_incomplete/{run_id}")
    completed = _safe_path(base, f"runs/completed/{run_id}")
    registry = _safe_path(base, f"registry/runs/{run_id}.json")
    base.mkdir(parents=True, exist_ok=True)
    with lock(_safe_path(base, f".{run_id}.publish.lock")):
        if not completed.exists():
            if registry.exists():
                raise FileExistsError("append-only registry conflict before publication")
            incomplete.mkdir(parents=True, exist_ok=True)
            existing = _tree_files(incomplete)
            if existing - {item.relative for item in files} - {"manifest.json"}:
                raise ValueError("unexpected incomplete publication artifacts")
            for item in files:
                destination = _safe_path(incomplete, item.relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                if not destination.exists():
                    with item.source.open("rb") as source, destination.open("xb") as output:
                        shutil.copyfileobj(source, output)
                        output.flush()
                        os.fsync(output.fileno())
                if destination.stat().st_size != item.bytes or checksum(destination) != item.sha256:
                    raise ValueError("destination rehash failed; incomplete bytes preserved")
            if not (incomplete / "manifest.json").exists():
                _write_exclusive(incomplete / "manifest.json", {
                    "schema_version": "1.0.0", "milestone": "m2_data_provenance", "run_id": run_id,
                    "created_utc": now(), "files": _inventory(files),
                })
            _verify_publication(incomplete, files, run_id)
            completed.parent.mkdir(parents=True, exist_ok=True)
            os.rename(incomplete, completed)
        _verify_publication(completed, files, run_id)
        manifest_sha = checksum(completed / "manifest.json")
        expected_registry = {"run_id": run_id, "manifest_sha256": manifest_sha,
                             "path": str(completed.relative_to(drive))}
        marker_path = _safe_path(completed, "COMPLETED.json")
        if marker_path.exists():
            if not registry.is_file() or _read_json(registry) != expected_registry:
                raise ValueError("immutable registry conflict")
            marker = _read_json(marker_path)
            _schema("m2-completion.schema.json", marker)
            if (marker["run_id"] != run_id or marker["manifest_sha256"] != manifest_sha
                    or marker["registry_sha256"] != checksum(registry)):
                raise ValueError("completion marker lineage mismatch")
            return completed, False
        registry.parent.mkdir(parents=True, exist_ok=True)
        if registry.exists():
            if _read_json(registry) != expected_registry:
                raise FileExistsError("append-only registry conflict")
        else:
            _write_exclusive(registry, expected_registry)
        if _read_json(registry) != expected_registry:
            raise ValueError("registry readback mismatch")
        marker = {"schema_version": "1.0.0", "run_id": run_id, "status": "completed",
                  "manifest_sha256": manifest_sha, "registry_sha256": checksum(registry), "completed_utc": now()}
        _schema("m2-completion.schema.json", marker)
        _write_exclusive(marker_path, marker)
        if _read_json(marker_path) != marker:
            raise ValueError("completion marker readback mismatch")
        return completed, True


def main() -> None:
    """Publish using packaged source and authoritative capture-design contracts."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--drive-root", required=True)
    parser.add_argument("--staging", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    path, changed = publish(args.drive_root, args.staging, args.run_id)
    print(("published" if changed else "no-op"), path)


if __name__ == "__main__":
    main()
