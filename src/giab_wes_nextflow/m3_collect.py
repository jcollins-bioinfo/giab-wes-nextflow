"""Collect actual M3 tool evidence into immutable, scientifically bounded outputs.

SAM acceptance checks operate on actual samtools exports; the integration runner
independently checks BAM/BAI access with the pinned samtools image. Measurements
are calculated here, never in notebooks or dashboards. No canonical HG001 claim
can be emitted by this synthetic-only result contract.
"""
from __future__ import annotations

from collections import Counter
import json
import math
from pathlib import Path
import re
from typing import Any

from .m3 import (canonical_hash, checked_file, envelope, identity, load_json,
                 require_fixture, validate_envelope, write_envelope)
from .m3_fixture import reverse_complement, sha256_bytes
from .resources import config_path
from .synthetic_fixtures import fixture_contract, fixture_contract_from_manifest_sha256

KINDS = ("alignment", "qc", "coverage", "resources", "provenance")


def _pairs(values: list[str]) -> dict[str, str]:
    """Parse explicit name=value boundaries without evaluating user strings."""
    result = {}
    for value in values:
        if "=" not in value:
            raise ValueError("expected NAME=VALUE")
        name, item = value.split("=", 1)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name) or not item or name in result:
            raise ValueError("invalid or duplicate named artifact")
        result[name] = item
    return result


def _sam(path: str | Path, expected: dict[str, Any], require_oq: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate every primary alignment, read group, sequence and quality lineage.

    SAM flag 16 requires reverse-complemented sequence and reversed original
    FASTQ quality order. Final-BAM acceptance requires the resulting original
    quality string in OQ for every primary read, including unmapped reads.
    """
    headers: dict[str, Any] = {"contigs": [], "read_groups": {}, "sort_order": None}
    records: dict[str, Any] = {}
    duplicate_reads = 0
    mapped_reads = 0
    quality_changed = 0
    last_sort = (-1, -1)
    contig_order = {name: index for index, name in enumerate(expected["contigs"])}
    with checked_file(path).open() as stream:
        for line in stream:
            if line.startswith("@"):
                fields = line.rstrip("\n").split("\t")
                tags = dict(field.split(":", 1) for field in fields[1:] if ":" in field)
                if fields[0] == "@HD":
                    headers["sort_order"] = tags.get("SO")
                elif fields[0] == "@SQ":
                    headers["contigs"].append((tags["SN"], int(tags["LN"])))
                elif fields[0] == "@RG":
                    if tags["ID"] in headers["read_groups"]:
                        raise ValueError("duplicate SAM read group")
                    headers["read_groups"][tags["ID"]] = tags
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 11:
                raise ValueError("malformed SAM record")
            qname, flag_text, contig, position_text, mapq, cigar = fields[:6]
            flag, position = int(flag_text), int(position_text)
            if flag & (256 | 2048):
                raise ValueError("unexpected secondary/supplementary alignment in deterministic fixture")
            if not flag & 1 or bool(flag & 64) == bool(flag & 128):
                raise ValueError("invalid paired SAM flags")
            mate = 1 if flag & 64 else 2
            key = f"{qname}/{mate}"
            if key in records or key not in expected["read_expectations"]:
                raise ValueError("duplicate or unexpected SAM read identity")
            exp = expected["read_expectations"][key]
            tags = {}
            for tag in fields[11:]:
                parts = tag.split(":", 2)
                if len(parts) != 3 or parts[0] in tags:
                    raise ValueError("malformed or duplicate SAM tag")
                tags[parts[0]] = parts[2]
            if tags.get("RG") != exp["read_group"]:
                raise ValueError("SAM read group identity mismatch")
            mapped = not flag & 4
            if mapped != (exp["contig"] is not None):
                raise ValueError("synthetic mapped/unmapped expectation mismatch")
            reverse = bool(flag & 16)
            if reverse != exp["reverse"]:
                raise ValueError("synthetic alignment strand mismatch")
            if mapped:
                if contig != exp["contig"] or position != exp["position_1based"] or cigar != "150M":
                    raise ValueError("synthetic alignment coordinate/CIGAR mismatch")
                sort_key = (contig_order[contig], position)
                mapped_reads += 1
            else:
                if contig != "*" or position != 0 or cigar != "*":
                    raise ValueError("unmapped fixture read has unexpected coordinates")
                sort_key = (len(contig_order), 0)
            if sort_key < last_sort:
                raise ValueError("SAM records are not coordinate sorted")
            last_sort = sort_key
            sequence = reverse_complement(fields[9]) if reverse else fields[9]
            if sha256_bytes(sequence.encode()) != exp["sequence_sha256"]:
                raise ValueError("read sequence changed across shared preprocessing")
            original = exp["original_qualities"][::-1] if reverse else exp["original_qualities"]
            if len(fields[10]) != 150 or any(not 33 <= ord(value) <= 126 for value in fields[10]):
                raise ValueError("invalid SAM QUAL field")
            if require_oq:
                if tags.get("OQ") != original:
                    raise ValueError("OQ must exactly preserve original FASTQ qualities for every read")
                quality_changed += fields[10] != original
            elif fields[10] != original:
                raise ValueError("pre-BQSR QUAL changed from original FASTQ")
            if flag & 1024:
                if exp["duplicate_group"] is None:
                    raise ValueError("unexpected duplicate outside the known synthetic fragment group")
                duplicate_reads += 1
            records[key] = {"flag": flag, "contig": contig, "position": position, "cigar": cigar,
                            "read_group": tags["RG"], "sequence_sha256": exp["sequence_sha256"]}
    if (headers["sort_order"] != "coordinate" or headers["contigs"] != list(expected["contigs"].items())
            or set(headers["read_groups"]) != {row["read_group_id"] for row in expected["lanes"]}):
        raise ValueError("SAM reference/header/read-group contract mismatch")
    for row in expected["lanes"]:
        observed = headers["read_groups"][row["read_group_id"]]
        if any(observed.get(tag) != row[field] for tag, field in (("SM", "sample"), ("LB", "library"), ("PU", "platform_unit"), ("PL", "platform"))):
            raise ValueError("SAM read-group sample/library/platform metadata mismatch")
    if set(records) != set(expected["read_expectations"]) or mapped_reads != expected["mapped_read_count"]:
        raise ValueError("shared BAM does not retain the complete expected read inventory")
    if duplicate_reads != expected["duplicate_read_count"]:
        raise ValueError("exactly two duplicate pairs must be marked and one original pair retained")
    for key, record in records.items():
        if key.endswith("/1"):
            mate_record = records[key[:-1] + "2"]
            if bool(record["flag"] & 1024) != bool(mate_record["flag"] & 1024):
                raise ValueError("duplicate flags must agree across each retained fragment pair")
    summary = {"primary_reads": len(records), "mapped_reads": mapped_reads,
               "unmapped_reads": len(records) - mapped_reads, "duplicate_reads": duplicate_reads,
               "read_group_count": len(headers["read_groups"]), "coordinate_sorted": True,
               "oq_complete": require_oq, "reads_with_recalibrated_quality_changes": quality_changed,
               "read_identity_digest": canonical_hash(records), "contigs": expected["contigs"]}
    return summary, records


def parse_duplicate_metrics(path: str | Path, expected_duplicates: int) -> dict[str, Any]:
    """Parse Picard duplicate counts and cross-check retained SAM flags."""
    lines = checked_file(path).read_text().splitlines()
    index = next((number for number, line in enumerate(lines) if line.startswith("LIBRARY\t")), None)
    if index is None:
        raise ValueError("missing Picard duplicate metrics table")
    header = lines[index].split("\t")
    rows = []
    for line in lines[index + 1:]:
        if not line.strip() or line.startswith("#"):
            break
        fields = line.split("\t")
        if len(fields) != len(header):
            raise ValueError("malformed Picard duplicate metrics row")
        rows.append(dict(zip(header, fields)))
    if not rows:
        raise ValueError("empty duplicate metrics")
    duplicates = sum(int(row["UNPAIRED_READ_DUPLICATES"]) + 2 * int(row["READ_PAIR_DUPLICATES"]) for row in rows)
    if duplicates != expected_duplicates:
        raise ValueError("Picard duplicate metrics disagree with retained BAM flags")
    return {"libraries": [row["LIBRARY"] for row in rows], "duplicate_reads_from_metrics": duplicates,
            "duplicate_pairs": sum(int(row["READ_PAIR_DUPLICATES"]) for row in rows), "raw_metrics": identity(path, "duplicate_metrics", "picard_metrics")}


def parse_coverage(path: str | Path, reference_bases: int) -> dict[str, Any]:
    """Derive mean depth from mosdepth integer counts with explicit domain meaning."""
    rows = [line.split("\t") for line in checked_file(path).read_text().splitlines() if line.strip()]
    if not rows or rows[0][:4] != ["chrom", "length", "bases", "mean"]:
        raise ValueError("malformed mosdepth summary")
    totals = [row for row in rows[1:] if row[0] == "total"]
    if len(totals) != 1 or len(totals[0]) < 6:
        raise ValueError("mosdepth whole-reference total missing")
    row = totals[0]
    length, depth_sum = int(row[1]), int(row[2])
    minimum, maximum = int(row[4]), int(row[5])
    if length != reference_bases or depth_sum < 0 or not 0 <= minimum <= maximum:
        raise ValueError("mosdepth reference or depth counts invalid")
    mean = depth_sum / length
    if not math.isfinite(float(row[3])) or abs(float(row[3]) - mean) > 0.011:
        raise ValueError("mosdepth reported mean disagrees with integer depth sum")
    return {"domain_kind": "whole_invented_reference_target_independent", "reference_bases": length,
            "summed_depth_bases": depth_sum, "mean_depth": mean, "minimum_depth": minimum,
            "maximum_depth": maximum, "primary_evaluation_bases": None,
            "target_aware_acceptance": "blocked", "benchmark_domain": False,
            "rounding_note": "mean_depth is depth-sum/reference-length; raw mosdepth mean is rounded"}


def _tool_declarations() -> dict[str, Any]:
    """Require the current lock's separate release and executable-report identities."""
    declarations = load_json(config_path("m3-tools.json"))
    if declarations.get("schema_version") != "2.0.0":
        raise ValueError("M3 tool lock requires explicit executable-report contract version 2.0.0")
    declared_tools = declarations["tools"]
    for declaration in declared_tools.values():
        if any(not declaration.get(key) for key in ("version", "expected_reported_version", "image", "version_note")):
            raise ValueError("M3 tool lock is missing release or executable-report identity")
        if not isinstance(declaration.get("version_evidence_sources"), list):
            raise ValueError("M3 tool lock is missing version evidence sources")
    return declared_tools


def _require_reported_version(name: str, observed: str, expected: str) -> None:
    """Check the exact BWA version line or another tool's bounded version token."""
    if name == "bwa-mem2":
        versions = re.findall(r"(?m)^\s*([0-9]+(?:\.[0-9]+)+(?:[-+][A-Za-z0-9.]+)?)\s*$", observed)
        matched = versions == [expected]
    else:
        matched = re.search(r"(?<![0-9.])" + re.escape(expected) + r"(?![0-9.])", observed) is not None
    if not matched:
        raise ValueError(f"observed tool version does not match lock: {name}")


def _validate_tool_inventory(inventory: list[dict[str, Any]]) -> None:
    """Rebind all tool reports, source notes and image pins to the installed lock."""
    declarations = _tool_declarations()
    names = [item["name"] for item in inventory]
    if len(names) != len(declarations) or set(names) != set(declarations):
        raise ValueError("M3 tool inventory differs from immutable lock")
    bindings = {"declared_version": "version", "expected_reported_version": "expected_reported_version",
                "version_note": "version_note", "version_evidence_sources": "version_evidence_sources",
                "container_image": "image"}
    for item in inventory:
        declaration = declarations[item["name"]]
        if any(item.get(field) != declaration[key] for field, key in bindings.items()):
            raise ValueError(f"M3 tool identity differs from immutable lock: {item['name']}")
        _require_reported_version(item["name"], item["observed_version_text"], declaration["expected_reported_version"])


def _tool_inventory(tools: list[str], tool_versions: list[str], containers: list[str]) -> list[dict[str, Any]]:
    """Bind actual stdout to the exact executable report separately from its release."""
    declared_tools = _tool_declarations()
    observed = _pairs(tools)
    files = _pairs(tool_versions)
    container_values = _pairs(containers)
    for name, path in files.items():
        if name in observed:
            raise ValueError("duplicate observed tool version")
        observed[name] = checked_file(path).read_text().strip()
    required = set(declared_tools)
    if set(observed) != required or set(container_values) - required:
        raise ValueError("missing or unexpected observed M3 tool versions or containers")
    result = []
    for name in sorted(required):
        declaration = declared_tools[name]
        _require_reported_version(name, observed[name], declaration["expected_reported_version"])
        image = container_values.get(name, declaration["image"])
        if image != declaration["image"]:
            raise ValueError(f"tool container differs from immutable lock: {name}")
        result.append({"name": name, "declared_version": declaration["version"],
                       "expected_reported_version": declaration["expected_reported_version"],
                       "version_note": declaration["version_note"], "version_evidence_sources": declaration["version_evidence_sources"],
                       "observed_version_text": observed[name],
                       "container_image": image, "container_identity_status": "workflow_declared_digest",
                       "version_evidence": identity(files[name], f"{name}_version", "tool_version_stdout") if name in files else None})
    _validate_tool_inventory(result)
    return result


def _resource_records(paths: list[str]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Normalize declared task resources without inventing absent trace measurements."""
    result = []
    seen = set()
    for path in paths:
        record = load_json(path)
        required = {"task_id", "process", "requested_cpus", "requested_memory_bytes", "requested_time_seconds", "container", "architecture"}
        if set(record) - {"logical_artifact_id"} != required:
            raise ValueError("invalid task resource declaration")
        if record["task_id"] is None and not record.get("logical_artifact_id"):
            raise ValueError("missing task identity requires a logical artifact identifier")
        key = record["task_id"] or f"{record['process']}:{record['logical_artifact_id']}"
        if key in seen:
            raise ValueError("duplicate task resource declaration")
        if any(type(record[key]) is not int or record[key] <= 0 for key in ("requested_cpus", "requested_memory_bytes", "requested_time_seconds")):
            raise ValueError("declared task resources must be positive integers")
        seen.add(key)
        result.append({**record, "elapsed_seconds": None, "cpu_seconds": None, "peak_rss_bytes": None,
                       "cache_status": None, "raw_declaration": identity(path, f"resource_{len(result)}", "nextflow_task_declaration")})
    missing = {"observed_task_resources": "Measured Nextflow trace is retained by the integration runner; M3 collector does not infer cost from requested resources."}
    if any(item["task_id"] is None for item in result):
        missing["task_identity"] = "Task identity was not available in the module; logical artifacts must be joined to the retained Nextflow trace."
    if not result:
        missing["task_declarations"] = "No task resource records were supplied; this field does not establish task resource verification."
    return result, missing


def collect(preflight_path: str | Path, sam: str | Path, pre_bqsr_sam: str | Path, bam: str | Path,
            bai: str | Path, flagstat: str | Path, idxstats: str | Path, samtools_stats: str | Path,
            duplicate_metrics: str | Path, coverage_summary: str | Path, expectations: str | Path,
            output_dir: str | Path, stages: list[str], lane_validations: list[str],
            tools: list[str], tool_versions: list[str], containers: list[str],
            artifacts: list[str], resource_records: list[str], *, fixture_id: str = "m3-preprocessing") -> dict[str, Any]:
    """Collect a complete synthetic shared-BAM result from actual tool evidence."""
    preflight = load_json(preflight_path)
    validate_envelope(preflight)
    if preflight["artifact_type"] != "preflight":
        raise ValueError("collector requires M3 source preflight evidence")
    expected = require_fixture(expectations, fixture_id=fixture_id)
    fixture_inputs = [item for item in preflight["input_artifacts"] if item["artifact_id"] == "fixture_expectations"]
    if len(fixture_inputs) != 1 or fixture_inputs[0]["sha256"] != fixture_contract(fixture_id).manifest_sha256:
        raise ValueError("preflight fixture manifest differs from selected recipe")
    run_id = preflight["run_id"]
    if (preflight["data"]["reference"]["fasta"]["sha256"] != expected["files"]["reference.fa"]["sha256"]
            or preflight["data"]["known_sites"]["sha256"] != expected["files"]["known-sites.vcf"]["sha256"]
            or preflight["data"]["lanes"] != expected["lanes"]):
        raise ValueError("preflight source identity no longer matches the deterministic fixture")
    lanes = [load_json(path) for path in lane_validations]
    for lane in lanes:
        validate_envelope(lane)
        if lane["artifact_type"] != "fastq" or lane["run_id"] != run_id:
            raise ValueError("lane validation run identity mismatch")
    if {lane["data"]["read_group_id"] for lane in lanes} != {row["read_group_id"] for row in expected["lanes"]} or len(lanes) != 2:
        raise ValueError("complete independent lane validation evidence is required")
    for lane in lanes:
        row = next(item for item in expected["lanes"] if item["read_group_id"] == lane["data"]["read_group_id"])
        if (lane["data"]["reference"]["fasta"]["sha256"] != expected["files"]["reference.fa"]["sha256"]
                or {item["sha256"] for item in lane["input_artifacts"]} != {expected["files"][row[field]]["sha256"] for field in ("fastq_1", "fastq_2")}):
            raise ValueError("lane source identities do not match the preflight fixture")
    before_summary, before_records = _sam(pre_bqsr_sam, expected, False)
    alignment, after_records = _sam(sam, expected, True)
    if before_records != after_records:
        raise ValueError("ApplyBQSR changed read identity, alignment, flags, or read group")
    passed = load_json(flagstat).get("QC-passed reads")
    if not isinstance(passed, dict) or any(passed.get(field) != count for field, count in (("total", alignment["primary_reads"]), ("primary", alignment["primary_reads"]), ("mapped", alignment["mapped_reads"]), ("duplicates", alignment["duplicate_reads"]))):
        raise ValueError("samtools flagstat disagrees with validated SAM counts")
    index_rows = [line.split("\t") for line in checked_file(idxstats).read_text().splitlines()]
    mapped_by_contig = Counter(record["contig"] for record in after_records.values() if record["contig"] != "*")
    if ([row[0] for row in index_rows] != list(expected["contigs"]) + ["*"]
            or any(len(row) != 4 for row in index_rows)
            or any(int(row[1]) != expected["contigs"].get(row[0], 0) or int(row[2]) != mapped_by_contig.get(row[0], 0) for row in index_rows)
            or sum(int(row[3]) for row in index_rows) != expected["unmapped_read_count"]):
        raise ValueError("samtools index counts/contigs disagree with actual SAM")
    if "SN\traw total sequences:" not in checked_file(samtools_stats).read_text():
        raise ValueError("missing samtools alignment summaries")
    dup = parse_duplicate_metrics(duplicate_metrics, alignment["duplicate_reads"])
    stage_paths = _pairs(stages)
    mandatory = {"merged", "duplicate_marked", "recalibration_table", "analysis_ready"}
    if not mandatory <= set(stage_paths) or len([name for name in stage_paths if name.startswith("aligned_")]) != 2 or len([name for name in stage_paths if name.startswith("sorted_")]) != 2:
        raise ValueError("incomplete ordered shared-preprocessing stage inventory")
    if "GATKReport" not in checked_file(stage_paths["recalibration_table"]).read_text():
        raise ValueError("missing actual GATK recalibration table")
    if fixture_id == "m4-snv-positive":
        validate_bqsr_observations(stage_paths["recalibration_table"])
    stage_artifacts = [identity(path, name, "preprocessing_transformation") for name, path in stage_paths.items()]
    aligned_suffixes = {name.removeprefix("aligned_") for name in stage_paths if name.startswith("aligned_")}
    sorted_suffixes = {name.removeprefix("sorted_") for name in stage_paths if name.startswith("sorted_")}
    if aligned_suffixes != sorted_suffixes or set(stage_paths) != mandatory | {f"aligned_{suffix}" for suffix in aligned_suffixes} | {f"sorted_{suffix}" for suffix in sorted_suffixes}:
        raise ValueError("preprocessing stage identities cannot be paired into an ordered graph")
    lineage = [{"artifact_id": f"aligned_{suffix}", "parents": ["validated_lane_fastq", "reference.fa"], "operation": "BWA-MEM2"} for suffix in sorted(aligned_suffixes)]
    lineage += [{"artifact_id": f"sorted_{suffix}", "parents": [f"aligned_{suffix}"], "operation": "coordinate_sort"} for suffix in sorted(sorted_suffixes)]
    lineage += [{"artifact_id": "merged", "parents": [f"sorted_{suffix}" for suffix in sorted(sorted_suffixes)], "operation": "lane_merge"},
                {"artifact_id": "duplicate_marked", "parents": ["merged"], "operation": "MarkDuplicates_retained"},
                {"artifact_id": "recalibration_table", "parents": ["duplicate_marked", "known-sites.vcf"], "operation": "BaseRecalibrator"},
                {"artifact_id": "analysis_ready", "parents": ["duplicate_marked", "recalibration_table"], "operation": "ApplyBQSR_emit_original_quals"}]
    bam_id = identity(bam, "shared_analysis_ready_bam", "shared_caller_input")
    bai_id = identity(bai, "shared_analysis_ready_bai", "shared_caller_input_index")
    if next(item for item in stage_artifacts if item["artifact_id"] == "analysis_ready")["sha256"] != bam_id["sha256"]:
        raise ValueError("final stage BAM differs from shared caller input")
    inventory = _tool_inventory(tools, tool_versions, containers)
    resources, missing_resources = _resource_records(resource_records)
    extra = [identity(path, name, "raw_qc_or_execution_evidence") for name, path in _pairs(artifacts).items()]
    common = [identity(preflight_path, "source_preflight", "validated_source_contract"), bam_id, bai_id]
    reference_hash = preflight["data"]["reference"]["fasta"]["sha256"]
    alignment.update({"sample": expected["sample"], "reference_sha256": reference_hash, "bam": bam_id, "bai": bai_id,
                      "sam_export": identity(sam, "final_sam_export", "samtools_alignment_acceptance"),
                      "pre_bqsr_sam_export": identity(pre_bqsr_sam, "pre_bqsr_sam_export", "original_quality_acceptance"),
                      "bai_acceptance": "idxstats_matches_sam; indexed_random_access_verified_separately_by_integration_runner",
                      "duplicates_retained": True, "bqsr_applied": True,
                      "effective_quality_policy": {"gatk": "recalibrated QUAL", "deepvariant": "original OQ", "quality_inputs_identical": False}})
    qc = {"sample": expected["sample"], "reference_sha256": reference_hash, "read_count": alignment["primary_reads"],
          "raw_read_count": sum(lane["data"]["read_count"] for lane in lanes), "lane_count": len(lanes),
          "adapter_trimming": "not_performed; deterministic adapter-free fixture", "duplicate_metrics": dup,
          "lane_validation_hashes": [lane["payload_sha256"] for lane in lanes], "additional_qc_artifacts": extra}
    coverage = parse_coverage(coverage_summary, sum(expected["contigs"].values()))
    coverage["reference_sha256"] = reference_hash
    provenance = {"sample": expected["sample"], "repository_sha": preflight["data"]["repository_sha"],
                  "reference_sha256": reference_hash, "shared_bam_sha256": bam_id["sha256"],
                  "fixture_recipe_version": expected["recipe_version"], "source_preflight_payload_sha256": preflight["payload_sha256"],
                  "fixture_expectations_sha256": identity(expectations, "fixture_expectations", "recipe_identity")["sha256"],
                  "known_sites_sha256": preflight["data"]["known_sites"]["sha256"], "stage_artifacts": stage_artifacts, "artifact_lineage": lineage,
                  "transform_order": ["BWA-MEM2_per_lane", "coordinate_sort_per_lane", "lane_merge", "MarkDuplicates_retained", "BaseRecalibrator", "ApplyBQSR_emit_OQ"],
                  "tools": inventory, "host_python_container": None,
                  "callers_executed": [], "canonical_hg001_executed": False, "capture_design_gate": "blocked",
                  "claim_boundary": "actual execution of deterministic invented preprocessing only; no human-data, caller, benchmark, or deployment claim"}
    objects = {
        "alignment": envelope("alignment", run_id, alignment, common, {"read_counts": "reads", "coordinates": "1-based SAM", "artifact_size": "bytes"}),
        "qc": envelope("qc", run_id, qc, common + [identity(flagstat, "flagstat", "samtools_counts"), identity(idxstats, "idxstats", "samtools_index_counts"), identity(samtools_stats, "samtools_stats", "samtools_alignment_summary")], {"read_count": "reads", "lane_count": "lanes"}),
        "coverage": envelope("coverage", run_id, coverage, common + [identity(coverage_summary, "mosdepth_summary", "target_independent_depth")], {"reference_bases": "bases", "summed_depth_bases": "base-depth", "mean_depth": "reads/base"}, {"primary_evaluation_bases": "Capture-design Gate B is unresolved; whole-reference synthetic coverage is not an evaluation denominator."}),
        "resources": envelope("resources", run_id, {"tasks": resources, "task_count": len(resources), "comparison_cost_available": False}, common, {"elapsed_seconds": "seconds", "cpu_seconds": "core-seconds", "peak_rss_bytes": "bytes", "requested_memory_bytes": "bytes", "requested_time_seconds": "seconds", "requested_cpus": "cores"}, missing_resources),
        "provenance": envelope("provenance", run_id, provenance, common + stage_artifacts, {"artifact_size": "bytes"}, {"host_python_container": "Contract collectors run from the installed host Python package; container image is not applicable."}),
    }
    output = Path(output_dir)
    for kind, record in objects.items():
        write_envelope(output / f"m3-{kind}.json", record)
    artifact_inventory = [{**identity(output / f"m3-{kind}.json", kind, "immutable_m3_result"), "artifact_type": kind,
                           "payload_sha256": record["payload_sha256"]} for kind, record in objects.items()]
    manifest = envelope("bundle", run_id, {"artifacts": artifact_inventory, "reference_sha256": reference_hash,
                        "shared_bam_sha256": bam_id["sha256"], "repository_sha": provenance["repository_sha"]}, common)
    write_envelope(output / "m3-manifest.json", manifest)
    validate_result_bundle(output)
    return manifest


def validate_result_bundle(path: str | Path) -> dict[str, dict[str, Any]]:
    """Validate schemas, file hashes and scientific cross-links before publication."""
    candidate = Path(path)
    manifest_path = candidate / "m3-manifest.json" if candidate.is_dir() else candidate
    manifest = load_json(manifest_path)
    validate_envelope(manifest)
    if manifest["artifact_type"] != "bundle":
        raise ValueError("expected M3 bundle manifest")
    result = {"bundle": manifest}
    artifacts = manifest["data"]["artifacts"]
    if len(artifacts) != len(KINDS) or {item["artifact_type"] for item in artifacts} != set(KINDS):
        raise ValueError("incomplete or duplicate M3 result inventory")
    for item in artifacts:
        kind = item["artifact_type"]
        if item["filename"] != f"m3-{kind}.json":
            raise ValueError("unsafe or noncanonical M3 artifact path")
        artifact_path = manifest_path.parent / item["filename"]
        observed = identity(artifact_path, kind, "immutable_m3_result")
        if observed["sha256"] != item["sha256"] or observed["bytes"] != item["bytes"]:
            raise ValueError("M3 bundle artifact byte hash mismatch")
        record = load_json(artifact_path)
        validate_envelope(record)
        if record["artifact_type"] != kind or record["run_id"] != manifest["run_id"] or record["payload_sha256"] != item["payload_sha256"]:
            raise ValueError("M3 artifact run/type/payload lineage mismatch")
        result[kind] = record
    if any(record["producer"] != manifest["producer"] for record in result.values()):
        raise ValueError("M3 producer identity/version differs across outputs")
    _validate_tool_inventory(result["provenance"]["data"]["tools"])
    common_ids = {"source_preflight", "shared_analysis_ready_bam", "shared_analysis_ready_bai"}
    manifest_common = {item["artifact_id"]: item for item in manifest["input_artifacts"] if item["artifact_id"] in common_ids}
    if set(manifest_common) != common_ids:
        raise ValueError("M3 bundle common input lineage is incomplete")
    for record in result.values():
        common = {item["artifact_id"]: item for item in record["input_artifacts"] if item["artifact_id"] in common_ids}
        if common != manifest_common:
            raise ValueError("M3 BAM/BAI/preflight input lineage differs across outputs")
    if (result["alignment"]["data"]["bam"] != manifest_common["shared_analysis_ready_bam"]
            or result["alignment"]["data"]["bai"] != manifest_common["shared_analysis_ready_bai"]):
        raise ValueError("M3 shared BAM/BAI data disagrees with common input identities")
    reference_hash = manifest["data"]["reference_sha256"]
    fixture = fixture_contract_from_manifest_sha256(result["provenance"]["data"]["fixture_expectations_sha256"])
    expected = fixture.expectations
    if (reference_hash != expected["files"]["reference.fa"]["sha256"]
            or result["provenance"]["data"]["fixture_recipe_version"] != expected["recipe_version"]
            or result["provenance"]["data"]["sample"] != expected["sample"]
            or result["provenance"]["data"]["known_sites_sha256"] != expected["files"]["known-sites.vcf"]["sha256"]
            or result["provenance"]["data"]["repository_sha"] != manifest["data"]["repository_sha"]
            or result["alignment"]["data"]["primary_reads"] != expected["primary_read_count"]
            or result["alignment"]["data"]["mapped_reads"] != expected["mapped_read_count"]
            or result["alignment"]["data"]["unmapped_reads"] != expected["unmapped_read_count"]
            or result["alignment"]["data"]["duplicate_reads"] != expected["duplicate_read_count"]):
        raise ValueError("M3 result does not match its deterministic fixture or repository identity")
    if any(result[kind]["data"]["reference_sha256"] != reference_hash for kind in ("alignment", "qc", "coverage", "provenance")):
        raise ValueError("M3 reference identity diverges across outputs")
    if (result["alignment"]["data"]["bam"]["sha256"] != manifest["data"]["shared_bam_sha256"]
            or result["provenance"]["data"]["shared_bam_sha256"] != manifest["data"]["shared_bam_sha256"]
            or result["qc"]["data"]["read_count"] != result["alignment"]["data"]["primary_reads"]
            or result["qc"]["data"]["raw_read_count"] != result["alignment"]["data"]["primary_reads"]):
        raise ValueError("M3 BAM/read-count lineage diverges across outputs")
    return result


def validate_bqsr_observations(path: str | Path) -> int:
    """Require a GATK recalibration table containing positive actual observations."""
    lines = checked_file(path).read_text().splitlines()
    if not any("GATKReport" in line for line in lines):
        raise ValueError("missing GATK recalibration report")
    observations = 0
    for index, line in enumerate(lines):
        fields = line.split()
        if "Observations" not in fields or "Errors" not in fields:
            continue
        column = fields.index("Observations")
        for row in lines[index + 1:]:
            values = row.split()
            if len(values) != len(fields) or row.startswith("#"):
                break
            try:
                count = int(values[column])
            except ValueError as error:
                raise ValueError("invalid BQSR observation count") from error
            if count < 0:
                raise ValueError("negative BQSR observation count")
            observations += count
    if observations <= 0:
        raise ValueError("BQSR requires nonempty recalibration tables with positive observations")
    return observations
