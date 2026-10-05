"""Public, immutable execution metadata derived from accepted nonhuman receipts.

Provider identifiers, account bindings, locations, commands and genomic payloads
never enter the public projection. Missing observations remain null.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

from .model import require

VALIDATION_SHA256 = "88d91777bc34367114e73f0e5c3f5f202dfae10526433deacb83e476396c51bf"
MANAGED_SHA256 = "b06836b606a3a1f86b62e10aa28465543cf147a403afa940bc3f4e24e34253e0"
SHA = re.compile(r"[a-f0-9]{64}")
DIGEST = re.compile(r"sha256:[a-f0-9]{64}")
TASK_FIELDS = {"key", "process", "label", "index", "attempt", "status", "created_seconds", "start_seconds", "stop_seconds", "requested_cpus", "requested_memory_bytes", "cpu_seconds", "peak_rss_bytes", "native_seconds", "image_digest", "command_sha256", "inputs", "outputs"}


def _read_pinned(path: Path, digest: str) -> dict[str, Any]:
    require(path.is_file() and path.stat().st_size <= 5_000_000, "missing or oversized execution evidence")
    require(not any(p.is_symlink() for p in (path, *path.parents)), "linked execution evidence is forbidden")
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == digest, "execution evidence identity mismatch")
    return json.loads(raw)


def _epoch(value: str) -> float:
    parsed = datetime.fromisoformat(value)
    require(parsed.tzinfo is not None, "timestamp needs a timezone")
    return parsed.timestamp()


def _artifacts(value: dict[str, Any]) -> list[dict[str, Any]]:
    # Deliberately discard even relative file names; only byte identities cross
    # the private-to-public boundary. Preserve duplicate physical inputs.
    return sorted(({"sha256": item["sha256"], "bytes": item["bytes"]} for item in value.values()),
                  key=lambda item: (item["sha256"], item["bytes"]))


def project_managed_receipts(validation_path: Path, provider_path: Path, collector_path: Path) -> dict[str, Any]:
    """Project only the accepted receipt chain, deterministically and offline."""
    validation = _read_pinned(validation_path, VALIDATION_SHA256)
    provider = _read_pinned(provider_path, validation["provider_receipt_sha256"])
    collector = _read_pinned(collector_path, validation["source_evidence"]["sha256"])
    require(validation["status"] == "PASSED" and validation["provider_binding_passed"] is True
            and validation["full_nonhuman_dag_qualified"] is True and validation["canonical"] is False,
            "accepted nonhuman qualification required")
    run = provider["run"]
    require(run["status"] == "COMPLETED" and run["id"] == validation["run_id"], "provider run mismatch")
    require(run["digest"] == "sha256:" + validation["archive_sha256"], "workflow package mismatch")
    origin = _epoch(run["startTime"])
    joins = {item["provider_task_id"]: item for item in validation["native_scientific_observation_joins"]}
    native = {(item["process"], item["nextflow_process_index"], item["attempt"]): item
              for item in collector["task_observations"]}
    tasks = []
    for task in provider["task_details"]:
        process = task["name"].split(" (")[0]
        joined = joins.get(task["taskId"])
        observation = native.get((joined["process"], joined["nextflow_process_index"], joined["attempt"])) if joined else None
        if joined:
            require(process == joined["process"] and task["imageDetails"]["imageDigest"] == joined["image_digest"], "provider image binding mismatch")
            if observation:
                require(observation["command"] == joined["command"], "native command binding mismatch")
                require(task["cpus"] == observation["requested_cpus"] and task["memory"] * 2**30 == observation["requested_memory_bytes"], "requested resource binding mismatch")
        index = joined["nextflow_process_index"] if joined else None
        attempt = joined["attempt"] if joined else None
        tasks.append({
            "key": f"{process}:{index}:{attempt}", "process": process,
            "label": joined["label"] if joined else "fixture", "index": index, "attempt": attempt,
            "status": task["status"],
            "created_seconds": round(_epoch(task["creationTime"]) - origin, 6),
            "start_seconds": round(_epoch(task["startTime"]) - origin, 6),
            "stop_seconds": round(_epoch(task["stopTime"]) - origin, 6),
            "requested_cpus": task["cpus"], "requested_memory_bytes": task["memory"] * 2**30,
            "cpu_seconds": observation["cpu_seconds"] if observation else None,
            "peak_rss_bytes": observation["peak_rss_bytes"] if observation else None,
            "native_seconds": observation["completed_epoch_seconds"] - observation["started_epoch_seconds"] if observation else None,
            "image_digest": task["imageDetails"]["imageDigest"],
            "command_sha256": joined["command"]["sha256"] if joined else None,
            "inputs": _artifacts(observation["inputs"]) if observation else [],
            "outputs": _artifacts(observation["outputs"]) if observation else [],
        })
    record = {
        "schema_version": "1.0.0", "scope": "accepted_managed_nonhuman", "canonical": False,
        "observed_date": run["startTime"][:10], "repository_sha": validation["repository_sha"],
        "workflow_package_sha256": validation["archive_sha256"], "validation_sha256": VALIDATION_SHA256,
        "provider_receipt_sha256": validation["provider_receipt_sha256"],
        "collector_sha256": validation["source_evidence"]["sha256"],
        "engine": validation["engine"], "parser": validation["parser"],
        "elapsed_seconds": round(_epoch(run["stopTime"]) - origin, 6),
        "submission_to_start_seconds": round(origin - _epoch(run["creationTime"]), 6),
        "managed_cache_qualified": validation["managed_cache_qualified"],
        "native_observation_count": len(joins), "original_quality_records": validation["original_quality_records_verified"],
        "returned_objects_rehashed": validation["returned_objects_rehashed"],
        "tasks": sorted(tasks, key=lambda task: (task["start_seconds"], task["key"])),
    }
    validate_managed(record)
    return record


def _finite_nonnegative(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def validate_managed(record: dict[str, Any]) -> None:
    """Reject unsupported claims and extra/private fields before rendering."""
    require(set(record) == {"schema_version", "scope", "canonical", "observed_date", "repository_sha", "workflow_package_sha256", "validation_sha256", "provider_receipt_sha256", "collector_sha256", "engine", "parser", "elapsed_seconds", "submission_to_start_seconds", "managed_cache_qualified", "native_observation_count", "original_quality_records", "returned_objects_rehashed", "tasks"}, "unexpected execution fields")
    require(record["scope"] == "accepted_managed_nonhuman" and record["canonical"] is False and record["managed_cache_qualified"] is False, "nonhuman execution boundary violated")
    require(record["schema_version"] == "1.0.0" and record["validation_sha256"] == VALIDATION_SHA256, "qualification receipt mismatch")
    require(re.fullmatch(r"[a-f0-9]{40}", record["repository_sha"]) is not None, "invalid source identity")
    for field in ("workflow_package_sha256", "provider_receipt_sha256", "collector_sha256"):
        require(SHA.fullmatch(record[field]) is not None, "invalid evidence identity")
    require(record["engine"] == "26.04.0" and record["parser"] == "v2", "unqualified engine or parser")
    require(type(record["observed_date"]) is str and re.fullmatch(r"\d{4}-\d{2}-\d{2}", record["observed_date"]) is not None, "invalid observation date")
    date.fromisoformat(record["observed_date"])
    require(_finite_nonnegative(record["elapsed_seconds"]) and record["elapsed_seconds"] > 0 and _finite_nonnegative(record["submission_to_start_seconds"]), "invalid provider elapsed time")
    require(type(record["original_quality_records"]) is int and record["original_quality_records"] == 528 and type(record["returned_objects_rehashed"]) is int and record["returned_objects_rehashed"] == 198, "accepted observation count mismatch")
    tasks = record["tasks"]
    require(len(tasks) == 28 and len({task["key"] for task in tasks}) == 28, "managed task inventory mismatch")
    require(len({task["process"] for task in tasks}) == 21, "managed process inventory mismatch")
    require(record["native_observation_count"] == 23 and sum(task["index"] is not None for task in tasks) == 23, "native observation inventory mismatch")
    for task in tasks:
        require(set(task) == TASK_FIELDS, "unexpected task fields")
        require(re.fullmatch(r"[A-Z_]+", task["process"]) is not None and task["label"] in {"shared", "truth", "gatk", "deepvariant", "fixture"}, "unsafe process identity")
        require(task["status"] == "COMPLETED" and DIGEST.fullmatch(task["image_digest"]) is not None, "task lacks accepted image or status")
        require(all(_finite_nonnegative(task[field]) for field in ("created_seconds", "start_seconds", "stop_seconds")), "invalid provider task time")
        require(0 <= task["created_seconds"] <= task["start_seconds"] <= task["stop_seconds"] <= record["elapsed_seconds"], "task timestamps outside execution")
        for field in ("requested_cpus", "requested_memory_bytes"):
            require(type(task[field]) is int and task[field] > 0, "invalid requested resource")
        for field in ("index", "attempt"):
            require(task[field] is None or type(task[field]) is int and task[field] > 0, "invalid native identity")
        require(task["key"] == f"{task['process']}:{task['index']}:{task['attempt']}", "task key mismatch")
        for field in ("cpu_seconds", "peak_rss_bytes", "native_seconds"):
            require(task[field] is None or _finite_nonnegative(task[field]), "invalid observed resource")
        require(task["command_sha256"] is None or SHA.fullmatch(task["command_sha256"]) is not None, "unsafe command identity")
        for field in ("inputs", "outputs"):
            for artifact in task[field]:
                require(set(artifact) == {"sha256", "bytes"} and SHA.fullmatch(artifact["sha256"]) is not None and type(artifact["bytes"]) is int and artifact["bytes"] >= 0, "unsafe artifact identity")


@dataclass(frozen=True)
class TimelineRow:
    """Calculated chart values; callbacks only select and render these values."""
    key: str
    label: str
    created: float
    start: float
    staging_seconds: float
    provider_seconds: float


@dataclass(frozen=True)
class ExecutionSnapshot:
    record: dict[str, Any]
    timeline: tuple[TimelineRow, ...]
    public_json: str


def load_managed(path: Path | None = None) -> ExecutionSnapshot:
    record = _read_pinned(path or Path(__file__).parent / "data/managed-execution.json", MANAGED_SHA256)
    validate_managed(record)
    timeline = tuple(TimelineRow(task["key"], task["process"] + (f" [{task['label']} #{task['index']}]" if task["index"] else " [fixture]"),
                    task["created_seconds"], task["start_seconds"], task["start_seconds"] - task["created_seconds"],
                    task["stop_seconds"] - task["start_seconds"]) for task in record["tasks"])
    return ExecutionSnapshot(record, timeline, json.dumps(record, sort_keys=True, indent=2) + "\n")
