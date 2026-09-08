"""Collect raw Nextflow resource evidence after workflow exit, without cost claims.

Raw durations are milliseconds, memory is bytes and CPU utilization is percent
of one logical CPU. Cached rows describe prior work and are aggregated separately.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
import hashlib
import io
import json
import math
from pathlib import Path
import re
from typing import Any, TypedDict

from jsonschema import Draft202012Validator, ValidationError

from . import __version__
from .m4_contracts import load_json
from .resources import schema_path

TRACE_UNITS = "nextflow-raw-ms-bytes"
GROUPS = ("shared_preprocessing", "gatk_incremental", "deepvariant_incremental", "common_normalization_benchmark")
SHARED = {
    "M3_PREFLIGHT", "M3_REFERENCE_FAIDX", "M3_REFERENCE_METADATA", "M3_FASTQ_VALIDATE",
    "M3_FASTQC", "M3_BWA_INDEX", "M3_ALIGN", "M3_SORT", "M3_MERGE", "M3_MARKDUP",
    "M3_PRE_BQSR", "M3_RECALIBRATE", "M3_APPLY_BQSR", "M3_BAM_SUMMARY", "M3_MOSDEPTH",
    "M3_PICARD_QC", "M3_MULTIQC", "M3_COLLECT", "M4_PREPARE_INPUTS",
}
ATTRIBUTION = {name: GROUPS[0] for name in SHARED}
ATTRIBUTION.update({"M4_HAPLOTYPECALLER": GROUPS[1], "M4_COLLECT_GATK": GROUPS[1],
                    "M4_DEEPVARIANT": GROUPS[2], "M4_COLLECT_DEEPVARIANT": GROUPS[2],
                    "M4_BUNDLE": GROUPS[3], "M5_NORMALIZE": GROUPS[3], "M5_BENCHMARK": GROUPS[3]})
STATUSES = {"COMPLETED", "CACHED", "FAILED", "ABORTED"}
METRICS = {"duration_seconds": ("duration", "seconds", 0.001),
           "realtime_seconds": ("realtime", "seconds", 0.001),
           "cpu_percent": ("%cpu", "percent", 1),
           "requested_cpus": ("cpus", "logical_cpus", 1),
           "requested_memory_bytes": ("memory", "bytes", 1),
           "peak_rss_bytes": ("peak_rss", "bytes", 1),
           "peak_vmem_bytes": ("peak_vmem", "bytes", 1)}


class Observation(TypedDict):
    """One measured, estimated or unavailable quantity with an explicit unit."""

    value: float | int | None
    unit: str
    reason: str | None


class Task(TypedDict):
    """Trace identity and resource observations for one task attempt."""

    task_id: int
    attempt: Observation
    name: str
    process: str
    group: str
    status: str
    cached: bool
    task_hash: str | None
    exit_code: int | None
    metrics: dict[str, Observation]


def observation(value: float | int | None, unit: str, reason: str | None = None) -> Observation:
    """Construct a quantity; unknown values always require a reason."""
    if value is None and not reason:
        raise ValueError("missing observation requires a reason")
    if value is not None and (isinstance(value, bool) or not math.isfinite(value) or value < 0 or reason is not None):
        raise ValueError("invalid resource observation")
    return {"value": value, "unit": unit, "reason": reason}


def _number(raw: str | None, field: str, unit: str, scale: float = 1) -> Observation:
    """Parse raw decimal numbers only; human units, negatives and NaN fail closed."""
    if raw in (None, "", "-", "NA"):
        return observation(None, unit, f"trace field {field} unavailable")
    if not re.fullmatch(r"\d+(?:\.\d+)?", raw):
        raise ValueError(f"invalid raw numeric trace field {field}: {raw!r}")
    value = int(raw) if raw.isdecimal() else float(raw)
    return observation(value if scale == 1 else value * scale, unit)


def process_name(name: str) -> str:
    """Strip a complete display tag before resolving the workflow-scoped name."""
    match = re.fullmatch(r"((?:[A-Za-z_][A-Za-z_0-9]*:)*[A-Za-z_][A-Za-z_0-9]*)(?: \([^\r\n]*\))?", name)
    if not match:
        raise ValueError(f"ambiguous process name: {name!r}")
    process = match[1].rsplit(":", 1)[-1]
    if process not in ATTRIBUTION:
        raise ValueError(f"unattributed process: {process}")
    return process


def parse_trace(text: str, *, trace_units: str) -> list[Task]:
    """Parse a finished raw trace, rejecting malformed rows and duplicate attempts.

    Failed attempts remain in the accounting. Old traces lacking ``attempt``
    retain explicit missingness; a repeated task ID then cannot be disambiguated.
    """
    if trace_units != TRACE_UNITS:
        raise ValueError("only explicitly declared nextflow-raw-ms-bytes traces are supported")
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    fields = reader.fieldnames or []
    if len(fields) != len(set(fields)) or not {"task_id", "name", "status", "exit"} <= set(fields):
        raise ValueError("missing or duplicate trace headers")
    tasks: list[Task] = []
    seen: dict[int, set[int | None]] = {}
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError("malformed trace row")
        if row["status"] not in STATUSES:
            raise ValueError("unknown or unfinished task status")
        process = process_name(row["name"])
        if not re.fullmatch(r"[1-9]\d*", row["task_id"]):
            raise ValueError("task_id must be a positive integer")
        task_id = int(row["task_id"])
        attempt = _number(row.get("attempt"), "attempt", "attempt")
        attempt_value = attempt["value"]
        if attempt_value is not None and (attempt_value < 1 or not float(attempt_value).is_integer()):
            raise ValueError("attempt must be a positive integer")
        attempt_id = int(attempt_value) if attempt_value is not None else None
        previous = seen.setdefault(task_id, set())
        if previous and (attempt_id in previous or attempt_id is None or None in previous):
            raise ValueError("duplicate or ambiguous task attempt")
        previous.add(attempt_id)
        exit_raw = row["exit"]
        if exit_raw in ("", "-", "NA"):
            exit_code = None
        elif re.fullmatch(r"\d+", exit_raw):
            exit_code = int(exit_raw)
        else:
            raise ValueError("invalid task exit code")
        if row["status"] in {"COMPLETED", "CACHED"} and exit_code != 0:
            raise ValueError("successful or cached task requires exit code zero")
        metrics = {key: _number(row.get(field), field, unit, scale)
                   for key, (field, unit, scale) in METRICS.items()}
        for key in ("requested_cpus", "requested_memory_bytes", "peak_rss_bytes", "peak_vmem_bytes"):
            value = metrics[key]["value"]
            if value is not None and (not float(value).is_integer() or (key == "requested_cpus" and value < 1)):
                raise ValueError(f"invalid integral resource {key}")
        realtime, cpu = metrics["realtime_seconds"]["value"], metrics["cpu_percent"]["value"]
        # Nextflow %cpu already includes use across CPUs: never multiply by cpus.
        estimate = realtime * cpu / 100 / 3600 if realtime is not None and realtime > 0 and cpu is not None else None
        metrics["cpu_hours_estimated"] = observation(estimate, "cpu_hours", None if estimate is not None else "positive realtime and CPU utilization required; zero realtime may reflect trace resolution")
        metrics["cpu_hours_measured"] = observation(None, "cpu_hours", "raw Nextflow trace provides no measured CPU time")
        tasks.append({"task_id": task_id, "attempt": attempt, "name": row["name"], "process": process,
                      "group": ATTRIBUTION[process], "status": row["status"], "cached": row["status"] == "CACHED",
                      "task_hash": None if row.get("hash") in (None, "", "-") else row["hash"],
                      "exit_code": exit_code, "metrics": metrics})
    if not tasks:
        raise ValueError("empty trace")
    return sorted(tasks, key=lambda task: (task["task_id"], task["attempt"]["value"] or 0))


def _aggregate(tasks: list[Task], key: str, *, maximum: bool = False) -> Observation:
    """Aggregate only complete evidence; partial sums never represent total work."""
    unit = (tasks[0]["metrics"][key]["unit"] if tasks else
            ("cpu_hours" if key.startswith("cpu_hours") else "bytes" if key.endswith("bytes") else "seconds"))
    values = [task["metrics"][key]["value"] for task in tasks]
    if not values or any(value is None for value in values):
        return observation(None, unit, "no tasks" if not values else "one or more task observations unavailable")
    known = [value for value in values if value is not None]
    return observation(max(known) if maximum else math.fsum(known), unit)


def summarize(tasks: list[Task]) -> dict[str, Any]:
    """Report current and cached-prior observations without conflating their cost."""
    result: dict[str, Any] = {"task_attempt_count": len(tasks),
                              "status_counts": {status: sum(t["status"] == status for t in tasks) for status in sorted(STATUSES)}}
    for label, cached in (("executed_attempts", False), ("cached_prior_attempts", True)):
        selected = [task for task in tasks if task["cached"] == cached]
        result[label] = {"task_attempt_count": len(selected),
                         "summed_task_duration_seconds": _aggregate(selected, "duration_seconds"),
                         "summed_task_realtime_seconds": _aggregate(selected, "realtime_seconds"),
                         "summed_cpu_hours_estimated": _aggregate(selected, "cpu_hours_estimated"),
                         "summed_cpu_hours_measured": _aggregate(selected, "cpu_hours_measured"),
                         "max_task_peak_rss_bytes": _aggregate(selected, "peak_rss_bytes", maximum=True),
                         "max_task_peak_vmem_bytes": _aggregate(selected, "peak_vmem_bytes", maximum=True)}
    return result


def _wall(observed: float | None, start: str | None, end: str | None) -> tuple[Observation, str]:
    """Use external invocation timing, never task spans or summed task durations."""
    if observed is not None and (start is not None or end is not None):
        raise ValueError("choose observed wall time or invocation start/end")
    if (start is None) != (end is None):
        raise ValueError("both invocation start and end are required")
    if start is not None and end is not None:
        first, last = datetime.fromisoformat(start), datetime.fromisoformat(end)
        if first.utcoffset() is None or last.utcoffset() is None:
            raise ValueError("invocation timestamps require explicit timezones")
        return observation((last - first).total_seconds(), "seconds"), "provided_invocation_timestamps"
    return observation(observed, "seconds", "invocation timing not supplied" if observed is None else None), "provided_observation" if observed is not None else "unavailable"


def validate_report(report: dict[str, Any]) -> None:
    """Validate the installed schema, task attribution and all summary arithmetic."""
    schema = json.loads(schema_path("m5-resources.schema.json").read_text())
    Draft202012Validator(schema).validate(report)
    tasks = report["tasks"]
    seen: dict[int, set[float | int | None]] = {}
    for task in tasks:
        attempt = task["attempt"]["value"]
        previous = seen.setdefault(task["task_id"], set())
        if previous and (attempt in previous or attempt is None or None in previous):
            raise ValueError("duplicate or ambiguous task attempt")
        previous.add(attempt)
        if attempt is not None and attempt < 1:
            raise ValueError("attempt must be positive")
        if task["status"] in {"COMPLETED", "CACHED"} and task["exit_code"] != 0:
            raise ValueError("successful or cached task requires exit code zero")
        for metric in task["metrics"].values():
            observation(**metric)
        cpus = task["metrics"]["requested_cpus"]["value"]
        if cpus is not None and cpus < 1:
            raise ValueError("requested CPUs must be positive")
        if process_name(task["name"]) != task["process"] or ATTRIBUTION[task["process"]] != task["group"]:
            raise ValueError("resource task attribution mismatch")
        if task["cached"] != (task["status"] == "CACHED"):
            raise ValueError("resource cache status mismatch")
        realtime = task["metrics"]["realtime_seconds"]["value"]
        cpu = task["metrics"]["cpu_percent"]["value"]
        expected = realtime * cpu / 100 / 3600 if realtime is not None and realtime > 0 and cpu is not None else None
        if task["metrics"]["cpu_hours_estimated"]["value"] != expected or task["metrics"]["cpu_hours_measured"]["value"] is not None:
            raise ValueError("CPU-hour derivation mismatch")
    supplied_wall = report["elapsed_wall_seconds"]["value"] if report["timing_source"] == "provided_observation" else None
    expected_wall, expected_source = _wall(supplied_wall, report["started_at"], report["ended_at"])
    if report["elapsed_wall_seconds"] != expected_wall or report["timing_source"] != expected_source:
        raise ValueError("invocation timing evidence mismatch")
    expected_groups = {group: summarize([task for task in tasks if task["group"] == group]) for group in GROUPS}
    if report["groups"] != expected_groups or report["end_to_end"] != summarize(tasks):
        raise ValueError("resource summary arithmetic mismatch")


def build_report(trace_path: str | Path, *, runtime: dict[str, Any], trace_units: str,
                 observed_wall_seconds: float | None = None, started_at: str | None = None,
                 ended_at: str | None = None) -> dict[str, Any]:
    """Create schema-validated evidence from a completed invocation's trace.

    Runtime metadata is explicitly supplied by the collector; its provenance is
    an operator assertion, not remote-host attestation. No canonical cost claim
    follows from a synthetic trace.
    """
    raw = Path(trace_path).read_bytes()
    tasks = parse_trace(raw.decode("utf-8"), trace_units=trace_units)
    wall, timing_source = _wall(observed_wall_seconds, started_at, ended_at)
    report = {"schema_version": "1.0.0", "artifact_type": "m5-resources", "package_version": __version__,
              "trace_sha256": hashlib.sha256(raw).hexdigest(), "trace_units": trace_units,
              "runtime": runtime, "runtime_provenance": "operator_supplied_not_attested",
              "elapsed_wall_seconds": wall, "timing_source": timing_source,
              "started_at": started_at, "ended_at": ended_at,
              "tasks": tasks, "groups": {group: summarize([t for t in tasks if t["group"] == group]) for group in GROUPS},
              "end_to_end": summarize(tasks), "warnings": [
                  "Synthetic evidence qualifies parsing and attribution only; no canonical caller-cost estimate.",
                  "Cached rows describe prior work; missing cached evidence never means free work.",
                  "CPU-hours estimated from realtime times percent CPU are not measured CPU time.",
                  "Maxima of task RSS/virtual memory are not simultaneous end-to-end run peaks.",
                  "Summed task times include failed attempts and are not elapsed invocation wall time.",
                  "Runtime and input metadata are supplied observations; trace completeness requires external workflow evidence."]}
    validate_report(report)
    return report


def main(argv: list[str] | None = None) -> int:
    """Collect a final trace after Nextflow exit and write a deterministic report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--trace-units", required=True, choices=[TRACE_UNITS])
    parser.add_argument("--runtime-json", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--observed-wall-seconds", type=float)
    parser.add_argument("--started-at")
    parser.add_argument("--ended-at")
    args = parser.parse_args(argv)
    try:
        report = build_report(args.trace, runtime=load_json(args.runtime_json), trace_units=args.trace_units,
                              observed_wall_seconds=args.observed_wall_seconds, started_at=args.started_at, ended_at=args.ended_at)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    except (ValueError, OSError, ValidationError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
