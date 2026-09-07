"""Validate M3 synthetic inputs and emit immutable, typed evidence envelopes.

Only the installed package's deterministic invented fixture may enter M3's
synthetic execution mode. HG001/capture-dependent acceptance stays closed. These
interfaces own measurements; notebooks and presentation layers only load them.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
from pathlib import Path
import platform
import re
from typing import Any, Iterator

from jsonschema import Draft202012Validator

from . import __version__
from .acquisition import checksum, destination, safe_root, validate_run_id
from .synthetic_fixtures import fixture_contract
from .resources import schema_path

IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def canonical_hash(value: Any) -> str:
    """Hash canonical compact JSON, excluding filesystem location and timestamps."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def load_json(path: str | Path) -> dict[str, Any]:
    """Read a JSON object from an explicit file, rejecting prohibited paths."""
    source = checked_file(path)
    value = json.loads(source.read_text())
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def checked_file(path: str | Path) -> Path:
    """Resolve normal Nextflow staging links without entering prohibited folders."""
    source = Path(path).expanduser()
    if any("DO NOT ACCESS WITH CHATGPT" in part for part in source.parts):
        raise PermissionError("prohibited artifact path")
    for parent in source.absolute().parents:
        if (parent / "DO NOT ACCESS WITH CHATGPT").exists():
            raise PermissionError("artifact ancestor safety marker present")
    source = source.resolve()
    if any("DO NOT ACCESS WITH CHATGPT" in part for part in source.parts):
        raise PermissionError("prohibited artifact target")
    for parent in source.parents:
        if (parent / "DO NOT ACCESS WITH CHATGPT").exists():
            raise PermissionError("artifact ancestor safety marker present")
    if not source.is_file():
        raise ValueError(f"missing regular artifact: {Path(path).name}")
    return source


def identity(path: str | Path, logical_id: str, role: str) -> dict[str, Any]:
    """Return safe logical identity, filename, byte count and SHA-256 only."""
    source = checked_file(path)
    return {"artifact_id": logical_id, "filename": Path(path).name, "role": role,
            "sha256": checksum(source), "bytes": source.stat().st_size}


def require_fixture(path: str | Path, *, fixture_id: str = "m3-preprocessing") -> dict[str, Any]:
    """Require full equality and byte identity with one explicitly selected recipe."""
    contract = fixture_contract(fixture_id)
    expected = contract.expectations
    observed = load_json(path)
    if observed != expected or checksum(checked_file(path)) != contract.manifest_sha256:
        raise ValueError("synthetic manifest does not match the installed deterministic fixture recipe")
    return expected


def require_fixture_file(path: str | Path, name: str, expected: dict[str, Any]) -> dict[str, Any]:
    """Bind a declared source to recipe bytes before any biological tool starts."""
    source = checked_file(path)
    declaration = expected["files"][name]
    if source.stat().st_size != declaration["bytes"] or checksum(source) != declaration["sha256"]:
        raise ValueError(f"synthetic source identity mismatch: {name}")
    return identity(path, name, "deterministic_synthetic_source")


def reference_lengths(path: str | Path) -> dict[str, int]:
    """Parse FASTA contigs strictly and preserve their declared ordering."""
    lengths: dict[str, int] = {}
    current: str | None = None
    with checked_file(path).open() as stream:
        for line in stream:
            if line.startswith(">"):
                current = line[1:].split()[0]
                if not IDENTIFIER.fullmatch(current) or current in lengths:
                    raise ValueError("invalid or duplicate reference contig")
                lengths[current] = 0
            else:
                bases = line.rstrip("\r\n")
                if current is None or not bases or re.fullmatch(r"[ACGTNacgtn]+", bases) is None:
                    raise ValueError("invalid reference sequence or header")
                lengths[current] += len(bases)
    if not lengths or any(value <= 0 for value in lengths.values()):
        raise ValueError("empty reference contig")
    return lengths


def validate_reference(reference: str | Path, expected: dict[str, Any],
                       fai: str | Path | None = None, dictionary: str | Path | None = None) -> dict[str, Any]:
    """Bind synthetic reference bytes and optional independently produced indexes."""
    item = require_fixture_file(reference, "reference.fa", expected)
    lengths = reference_lengths(reference)
    if lengths != expected["contigs"]:
        raise ValueError("reference contig contract mismatch")
    result = {"fasta": item, "contigs": lengths, "fai": None, "dictionary": None,
              "coordinate_convention": "reference sequence positions are 1-based; interval summaries are 0-based half-open"}
    if fai:
        rows = [line.split("\t") for line in checked_file(fai).read_text().splitlines()]
        if any(len(row) != 5 for row in rows) or len(rows) != len(lengths):
            raise ValueError("malformed FASTA index")
        if {row[0]: int(row[1]) for row in rows} != lengths or [row[0] for row in rows] != list(lengths):
            raise ValueError("FASTA index contig order/length mismatch")
        result["fai"] = identity(fai, "reference_fai", "derived_reference_index")
    if dictionary:
        rows = [dict(field.split(":", 1) for field in line.split("\t")[1:])
                for line in checked_file(dictionary).read_text().splitlines() if line.startswith("@SQ\t")]
        if len(rows) != len(lengths) or {row["SN"]: int(row["LN"]) for row in rows} != lengths or [row["SN"] for row in rows] != list(lengths):
            raise ValueError("sequence dictionary contig order/length mismatch")
        result["dictionary"] = identity(dictionary, "reference_dictionary", "derived_reference_dictionary")
    return result


def validate_known_sites(path: str | Path, expected: dict[str, Any]) -> dict[str, Any]:
    """Check the exact independent invented known-sites fixture and coordinates."""
    result = require_fixture_file(path, "known-sites.vcf", expected)
    count = 0
    for line in checked_file(path).read_text().splitlines():
        if line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) < 8 or fields[0] not in expected["contigs"] or not 1 <= int(fields[1]) <= expected["contigs"][fields[0]]:
            raise ValueError("invalid known-site contig or coordinate")
        count += 1
    if count != 12:
        raise ValueError("known-sites fixture record count mismatch")
    result["record_count"] = count
    result["role"] = "independent_invented_bqsr_known_sites_not_benchmark_truth"
    return result


def read_pairs(fastq1: str | Path, fastq2: str | Path) -> Iterator[tuple[str, str, str, str, str]]:
    """Yield synchronized FASTQ pairs, failing on truncation, IDs, or invalid quality.

    Both gzip integrity and four-line FASTQ structure are checked while reading;
    checksums are a separate prerequisite to scientific execution.
    """
    sources = [checked_file(fastq1), checked_file(fastq2)]
    seen: set[str] = set()
    with gzip.open(sources[0], "rt", encoding="ascii") as first, gzip.open(sources[1], "rt", encoding="ascii") as second:
        while True:
            pair = []
            for mate, stream in enumerate((first, second), 1):
                lines = [stream.readline() for _ in range(4)]
                if not any(lines):
                    pair.append(None)
                    continue
                if any(not line for line in lines):
                    raise ValueError("truncated FASTQ record")
                header, sequence, separator, qualities = (line.rstrip("\r\n") for line in lines)
                if not header.startswith("@") or not separator.startswith("+"):
                    raise ValueError("invalid FASTQ header/separator")
                fields = header[1:].split()
                if not fields:
                    raise ValueError("empty FASTQ read identity")
                raw_id = fields[0]
                suffix = re.search(r"/([12])$", raw_id)
                if suffix and int(suffix.group(1)) != mate:
                    raise ValueError("FASTQ mate suffix mismatch")
                read_id = raw_id[:-2] if suffix else raw_id
                if len(fields) > 1 and fields[1][0] in "12" and int(fields[1][0]) != mate:
                    raise ValueError("FASTQ CASAVA mate mismatch")
                if not read_id or re.search(r"\s", read_id):
                    raise ValueError("invalid FASTQ read identity")
                if not sequence or re.fullmatch(r"[ACGTNacgtn]+", sequence) is None or len(sequence) != len(qualities):
                    raise ValueError("FASTQ sequence/quality length or alphabet mismatch")
                if any(not 33 <= ord(value) <= 126 for value in qualities):
                    raise ValueError("FASTQ quality is not valid Phred+33")
                pair.append((read_id, sequence, qualities))
            if pair == [None, None]:
                break
            if None in pair or pair[0][0] != pair[1][0]:
                raise ValueError("FASTQ paired read identities or counts differ")
            read_id = pair[0][0]
            if read_id in seen:
                raise ValueError("duplicate FASTQ read identity")
            seen.add(read_id)
            yield read_id, pair[0][1], pair[0][2], pair[1][1], pair[1][2]
    if not seen:
        raise ValueError("empty FASTQ input")


def envelope(kind: str, run_id: str, data: dict[str, Any], inputs: list[dict[str, Any]],
             units: dict[str, str] | None = None, missingness: dict[str, str] | None = None) -> dict[str, Any]:
    """Create current evidence without upgrading historical provenance contracts."""
    validate_run_id(run_id)
    record = {"schema_version": "2.0.0" if kind == "provenance" else "1.0.0", "artifact_type": kind, "run_id": run_id,
              "producer": {"package": "giab-wes-nextflow", "version": __version__, "module": "giab_wes_nextflow.m3"},
              "synthetic": True, "canonical": False, "validation_status": "validated_synthetic",
              "runtime_architecture": platform.machine(), "input_artifacts": inputs,
              "units": units or {}, "missingness": missingness or {}, "data": data}
    record["payload_sha256"] = canonical_hash(record)
    validate_envelope(record)
    return record


def validate_envelope(record: dict[str, Any]) -> None:
    """Reject obsolete provenance, schema or payload failures without upgrading bytes."""
    kind = record.get("artifact_type")
    if kind not in {"preflight", "fastq", "alignment", "qc", "coverage", "resources", "provenance", "bundle"}:
        raise ValueError("unknown M3 evidence artifact type")
    if kind == "provenance" and record.get("schema_version") != "2.0.0":
        raise ValueError("M3 provenance requires schema version 2.0.0; historical evidence is not upgraded")
    Draft202012Validator(load_json(schema_path(f"m3-{kind}.schema.json"))).validate(record)
    payload = {key: value for key, value in record.items() if key != "payload_sha256"}
    if canonical_hash(payload) != record["payload_sha256"]:
        raise ValueError("M3 evidence payload hash mismatch")


def write_envelope(path: str | Path, record: dict[str, Any]) -> None:
    """Write a checked evidence object; refuse conflicting existing artifacts."""
    validate_envelope(record)
    requested = Path(path)
    root = safe_root(requested.parent, allow_test_root=True)
    target = destination(root, requested.name)
    payload = json.dumps(record, sort_keys=True, indent=2, allow_nan=False) + "\n"
    root.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or (target.exists() and target.read_text() != payload):
        raise FileExistsError(f"conflicting immutable M3 artifact: {target.name}")
    if not target.exists():
        target.write_text(payload)


def preflight(samplesheet: str | Path, reference: str | Path, known_sites: str | Path,
              expectations: str | Path, repository_sha: str, run_id: str,
              reference_fai: str | Path | None = None, reference_dict: str | Path | None = None,
              known_sites_index: str | Path | None = None, *, fixture_id: str = "m3-preprocessing") -> dict[str, Any]:
    """Admit only exact invented sources before reference indexing or alignment."""
    if not re.fullmatch(r"[0-9a-f]{40}", repository_sha):
        raise ValueError("repository SHA must identify an exact commit")
    expected = require_fixture(expectations, fixture_id=fixture_id)
    sheet = checked_file(samplesheet)
    inputs = [require_fixture_file(sheet, "samplesheet.csv", expected), identity(expectations, "fixture_expectations", "recipe_identity")]
    with sheet.open(newline="") as stream:
        lanes = list(csv.DictReader(stream))
    if lanes != expected["lanes"]:
        raise ValueError("samplesheet lane/read-group metadata differs from fixture")
    for lane in lanes:
        for field in ("fastq_1", "fastq_2"):
            inputs.append(require_fixture_file(sheet.parent / lane[field], lane[field], expected))
    ref = validate_reference(reference, expected, reference_fai, reference_dict)
    sites = validate_known_sites(known_sites, expected)
    inputs.extend([ref["fasta"], sites])
    index = identity(known_sites_index, "known_sites_index", "derived_known_sites_index") if known_sites_index else None
    data = {"fixture_recipe_version": expected["recipe_version"], "repository_sha": repository_sha,
            "sample": expected["sample"], "library": expected["library"], "lanes": lanes,
            "reference": ref, "known_sites": sites, "known_sites_index": index,
            "source_bytes_verified": True, "canonical_gate_status": "blocked",
            "bqsr_policy": "required_with_independent_known_sites_and_emit_original_quals",
            "calling_policy": "no_callers_in_M3", "expected_primary_reads": expected["primary_read_count"]}
    return envelope("preflight", run_id, data, inputs, {"source_size": "bytes", "reference_length": "bases"})


def validate_fastq(fastq1: str | Path, fastq2: str | Path, sample: str, library: str, lane: str,
                   read_group: str, platform_unit: str, sequencing_platform: str, reference: str | Path,
                   expectations: str | Path, reference_fai: str | Path | None = None,
                   reference_dict: str | Path | None = None, run_id: str = "m3-synthetic", *,
                   fixture_id: str = "m3-preprocessing") -> dict[str, Any]:
    """Validate lane metadata, paired gzip FASTQ integrity, and reference identities."""
    values = [sample, library, lane, read_group, platform_unit]
    if any(IDENTIFIER.fullmatch(value) is None for value in values) or sequencing_platform != "ILLUMINA":
        raise ValueError("invalid read-group metadata or platform")
    expected = require_fixture(expectations, fixture_id=fixture_id)
    matches = [row for row in expected["lanes"] if row["lane"] == lane]
    if len(matches) != 1:
        raise ValueError("unknown fixture lane")
    row = matches[0]
    if [sample, library, read_group, platform_unit, sequencing_platform] != [row[key] for key in ("sample", "library", "read_group_id", "platform_unit", "platform")]:
        raise ValueError("read-group metadata differs from fixture lane")
    inputs = [require_fixture_file(fastq1, row["fastq_1"], expected), require_fixture_file(fastq2, row["fastq_2"], expected)]
    ref = validate_reference(reference, expected, reference_fai, reference_dict)
    pairs = list(read_pairs(fastq1, fastq2))
    bases = sum(len(sequence1) + len(sequence2) for _, sequence1, _, sequence2, _ in pairs)
    qualities = [ord(char) - 33 for _, _, qual1, _, qual2 in pairs for char in qual1 + qual2]
    data = {"sample": sample, "library": library, "lane": lane, "read_group_id": read_group,
            "platform_unit": platform_unit, "platform": sequencing_platform, "pair_count": len(pairs),
            "read_count": len(pairs) * 2, "base_count": bases, "quality_encoding": "Phred+33",
            "minimum_quality": min(qualities), "maximum_quality": max(qualities),
            "read_name_set_sha256": canonical_hash(sorted(pair[0] for pair in pairs)), "reference": ref,
            "gzip_integrity": "valid", "paired_identity_status": "valid"}
    return envelope("fastq", run_id, data, inputs, {"read_count": "reads", "pair_count": "pairs", "base_count": "bases", "quality": "Phred"})
