"""Load one immutable evidence snapshot; no benchmark science lives in the UI.

This initial model admits only the bundled, hash-pinned synthetic observations.
Missing HG001 metrics remain absent. A future canonical result model requires
its own validated contract rather than changing a label on this snapshot.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
from typing import Any

MANIFEST_SHA256 = "16562b8a15532af0658cca562897a28ea0e2f575c50e97598b03ea5b41750daf"
FILES = {"m3-proof.json", "m3-first.trace.tsv", "m4-attempt.json", "domain-approval.json",
         "m4-verified-main-34237377774.json"}
REPO = "https://github.com/jcollins-bioinfo/giab-wes-nextflow"


def require(condition: bool, message: str) -> None:
    """Raise on invalid evidence even when Python optimization is enabled."""
    if not condition:
        raise ValueError(message)


def read_regular(root: Path, name: str) -> bytes:
    """Read a bounded fixed member without following any linked path ancestor."""
    require(name in FILES | {"manifest.json"}, "unknown evidence member")
    path = root.absolute() / name
    require(not any(part.is_symlink() for part in (path, *path.parents)), "linked evidence is forbidden")
    require(path.is_file() and path.stat().st_size <= 100_000, "missing or oversized evidence")
    return path.read_bytes()


@dataclass(frozen=True)
class TaskObservation:
    """Original Nextflow trace observations; reported units are retained verbatim."""
    name: str
    status: str
    elapsed: str
    cpu: str
    peak_rss: str
    task_hash: str


@dataclass(frozen=True)
class Snapshot:
    """Validated immutable measurements and identities for rendering only."""
    primary_reads: int
    mapped_reads: int
    unmapped_reads: int
    duplicate_reads: int
    read_groups: int
    completed_tasks: int
    cached_tasks: int
    pipeline_sha: str
    bam_sha256: str
    bai_sha256: str
    m4_run_id: int
    m4_sha: str
    tasks: tuple[TaskObservation, ...]
    sources: tuple[tuple[str, str], ...]
    public_json: str
    caller_observation: str


def load_snapshot(directory: Path | None = None) -> Snapshot:
    """Verify every byte and semantic boundary before exposing any observation."""
    root = directory or Path(__file__).parent / "data"
    manifest_bytes = read_regular(root, "manifest.json")
    require(hashlib.sha256(manifest_bytes).hexdigest() == MANIFEST_SHA256, "evidence manifest identity mismatch")
    manifest = json.loads(manifest_bytes)
    require(set(manifest) == FILES, "evidence inventory mismatch")
    payloads = {name: read_regular(root, name) for name in sorted(FILES)}
    for name, raw in payloads.items():
        require(hashlib.sha256(raw).hexdigest() == manifest[name], "evidence member hash mismatch")
    m3 = json.loads(payloads["m3-proof.json"])
    m4 = json.loads(payloads["m4-verified-main-34237377774.json"])
    historical_m4 = json.loads(payloads["m4-attempt.json"])
    domain = json.loads(payloads["domain-approval.json"])
    require(m3["synthetic"] is True and m3["canonical"] is False and m3["status"] == "passed"
            and m3["biological_processing_validated"] is True, "M3 is not accepted synthetic evidence")
    require(m4["synthetic"] is True and m4["canonical"] is False and m4["status"] == "passed"
            and m4["execution_scope"]["biological_processing_validated"] is True
            and m4["execution_scope"]["both_and_resume_accepted"] is True
            and m4["deepvariant_inference"]["example_record_count"] > 0
            and m4["deepvariant_inference"]["call_variants_record_count"] > 0
            and m4["deepvariant_inference"]["all_probabilities_valid"] is True,
            "M4 is not accepted synthetic SNV evidence")
    require(all(item["expected_native_snvs_valid"] is True and item["reference_control_nonvariant"] is True
                for item in m4["native_assertions"].values()), "M4 native acceptance is incomplete")
    require(historical_m4["status"] == "failed" and historical_m4["canonical"] is False,
            "historical M4 attempt must preserve its failed acceptance state")
    require(domain["decision"] == "approve_fixed_coding_domain_alternative"
            and domain["canonical_execution"] is False, "domain decision cannot claim execution")
    bam = m3["bam_assertions"]
    for key in ("primary_reads", "mapped_reads", "unmapped_reads", "duplicate_reads", "read_groups"):
        require(type(bam[key]) is int and bam[key] >= 0, "invalid read count")
    require(bam["mapped_reads"] + bam["unmapped_reads"] == bam["primary_reads"], "read totals disagree")
    require(bam["coordinate_sorted"] is True and bam["indexed_region_queries_valid"] is True
            and bam["oq_on_all_primary_reads"] is True, "BAM acceptance is incomplete")
    resume = m3["resume_assertions"]
    rows = list(csv.DictReader(io.StringIO(payloads["m3-first.trace.tsv"].decode()), delimiter="\t"))
    require(len(rows) == resume["first_executed_tasks"] and all(r["status"] == "COMPLETED" for r in rows),
            "trace differs from accepted execution")
    tasks = tuple(TaskObservation(r["name"], r["status"], r.get("realtime", "-"), r.get("%cpu", "-"),
                                  r.get("peak_rss", "-"), r["hash"]) for r in rows)
    public = {"schema_version": "1.0.0", "scope": "synthetic_prototype", "canonical": False,
              "manifest_sha256": MANIFEST_SHA256, "source_hashes": manifest,
              "m3": {"repository": m3["repository"], "bam_assertions": bam, "resume_assertions": resume},
              "m4": m4, "m4_historical_attempt": historical_m4, "domain_decision": domain,
              "benchmark_metrics": None, "comparative_cost": None,
              "missing_reason": "No canonical HG001 benchmark or fair caller-cost experiment exists."}
    observations = [f"{site['contig']}:{site['position_1based']} — native {site['genotype']} accepted by both callers."
                    for site in m4["frozen_oracle_sites"] if site["alt"] is not None]
    observations.append("The reference control passed. DeepVariant produced two candidate examples and two inference records with valid probabilities.")
    return Snapshot(*(bam[k] for k in ("primary_reads", "mapped_reads", "unmapped_reads", "duplicate_reads", "read_groups")),
                    resume["first_executed_tasks"], resume["resumed_cached_tasks"], m3["repository"]["sha"],
                    bam["bam_sha256"], bam["bai_sha256"], m4["run_id"], m4["head_sha"], tasks,
                    tuple(sorted(manifest.items())), json.dumps(public, sort_keys=True, indent=2), " ".join(observations))


def select_tasks(snapshot: Snapshot, name: str) -> tuple[TaskObservation, ...]:
    """Select already validated observations without recomputing scientific values."""
    require(name == "all" or name in {task.name for task in snapshot.tasks}, "unknown process selection")
    return snapshot.tasks if name == "all" else tuple(task for task in snapshot.tasks if task.name == name)
