#!/usr/bin/env python3
"""Qualify M3 from a clean clone using invented data and explicit execution modes.

The Docker mode installs the exact cloned package, executes preprocessing, checks
its real BAM and immutable result contracts, then repeats with the same work
cache. Stub mode only qualifies scaffolding. Small uploadable evidence is kept
separate from sequence artifacts, container outputs, and Nextflow work files.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any
import venv
import urllib.parse

EXPECTED_REPOSITORY = "jcollins-bioinfo/giab-wes-nextflow"
EXPECTED_NEXTFLOW = "26.04.6"
MINIMUM_FREE_BYTES = 10 * 1024 ** 3
MINIMUM_DOCKER_MEMORY_BYTES = 4 * 1024 ** 3
EXPECTED_PROCESSES = {
    "M3_PREFLIGHT", "M3_REFERENCE_FAIDX", "M3_REFERENCE_METADATA", "M3_FASTQ_VALIDATE",
    "M3_FASTQC", "M3_BWA_INDEX", "M3_ALIGN", "M3_SORT", "M3_MERGE", "M3_MARKDUP",
    "M3_PRE_BQSR", "M3_RECALIBRATE", "M3_APPLY_BQSR", "M3_BAM_SUMMARY", "M3_MOSDEPTH",
    "M3_PICARD_QC", "M3_MULTIQC", "M3_COLLECT",
}
FORBIDDEN_FOLDER = "DO NOT ACCESS WITH CHATGPT"


def require(condition: bool, message: str) -> None:
    """Keep acceptance checks active even when Python runs with optimization."""
    if not condition:
        raise ValueError(message)


def validate_samtools_version(observed: str, declaration: dict[str, Any]) -> None:
    """Compare executable stdout with its explicit report expectation."""
    expected = declaration.get("expected_reported_version")
    require(isinstance(expected, str) and bool(expected), "samtools reported-version expectation is missing")
    require(observed == "samtools " + expected, "observed samtools version differs from pinned tool contract")


def digest(path: Path) -> str:
    """Hash an artifact without loading large alignment files into memory."""
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 << 20), b""):
            value.update(chunk)
    return value.hexdigest()


def guarded_path(path: Path) -> Path:
    """Reject prohibited names, markers and user-created symlink ancestors."""
    raw = path.expanduser().absolute()
    require(not any(FORBIDDEN_FOLDER in part for part in raw.parts), "prohibited folder path")
    for candidate in [raw, *raw.parents]:
        require(candidate in {Path("/tmp"), Path("/var")} or not candidate.is_symlink(), "symlink in integration path")
        require(not (candidate / FORBIDDEN_FOLDER).exists(), "workspace safety marker present")
    return raw.resolve()


def redact_text(text: str, root: Path) -> str:
    """Replace personal execution paths and URL query credentials in evidence."""
    result = text.replace(str(root), "$INTEGRATION_ROOT").replace(str(Path.home()), "$USER_HOME")
    def clean_url(match: re.Match[str]) -> str:
        parsed = urllib.parse.urlsplit(match.group(0))
        host = parsed.netloc.rsplit("@", 1)[-1]
        return urllib.parse.urlunsplit((parsed.scheme, host, parsed.path, "", ""))
    return re.sub(r'https?://[^\s<>"\']+', clean_url, result)


def sanitize_json(value: Any, root: Path) -> Any:
    """Apply evidence redaction recursively without changing numeric observations."""
    if isinstance(value, dict):
        return {key: sanitize_json(item, root) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_json(item, root) for item in value]
    return redact_text(value, root) if isinstance(value, str) else value


def safe_evidence_text(value: str, root: Path) -> str:
    """Validate sanitized text before any byte enters the upload directory."""
    redacted = redact_text(value, root)
    require(not re.search(r"/Users/[^/\s]+|/home/[^/\s]+|/content/drive(?:/|\b)", redacted),
            "private path remains in execution evidence; raw diagnostics were quarantined")
    return redacted


def quarantine_evidence(root: Path) -> Path:
    """Atomically remove the entire upload candidate tree before inspecting it."""
    quarantine = Path(tempfile.mkdtemp(prefix="quarantined-evidence-", dir=root))
    evidence = root / "evidence"
    if evidence.exists():
        evidence.rename(quarantine / "candidates")
    else:
        (quarantine / "candidates").mkdir()
    evidence.mkdir()
    return quarantine / "candidates"


def finish_evidence(root: Path) -> dict[str, dict[str, str | bool]]:
    """Promote evidence only after every text candidate passes the privacy check."""
    evidence = root / "evidence"
    raw = root / "raw-execution"
    raw.mkdir(exist_ok=True)
    candidates = quarantine_evidence(root)
    for path in sorted(candidates.glob("*")):
        if path.is_file() and any(path.name.endswith(ending) for ending in
                                 (".nextflow.log", ".trace.tsv", ".report.html", ".timeline.html", ".dag.html")):
            require(not path.is_symlink(), "linked execution evidence is forbidden")
            shutil.copy2(path, raw / path.name)
    paths = {path.relative_to(candidates): path for path in candidates.rglob("*") if not path.is_dir()}
    paths.update({Path(path.name): path for path in raw.iterdir() if path.is_file()})
    reports = {}
    ready: dict[Path, str] = {}
    for relative, path in sorted(paths.items()):
        require(not path.is_symlink() and path.is_file(), "linked or non-file execution evidence is forbidden")
        original = path.read_text()
        redacted = safe_evidence_text(original, root)
        if relative.parts[0] == "contracts":
            require(original == redacted, "output contracts cannot require privacy redaction")
        ready[relative] = redacted
        if path.parent == raw:
            reports[path.name] = {"raw_sha256": digest(path),
                                  "uploaded_sha256": hashlib.sha256(redacted.encode()).hexdigest(),
                                  "redacted_copy": redacted != original}
    for relative, contents in ready.items():
        target = evidence / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents)
    return reports


def finalize_proof(root: Path, proof: dict[str, Any]) -> None:
    """Always leave a safe failed proof when evidence or proof validation fails."""
    try:
        proof["execution_reports"] = finish_evidence(root)
        proof["evidence_hashes"] = file_inventory(root / "evidence")
        contents = safe_evidence_text(json.dumps(sanitize_json(proof, root), sort_keys=True, indent=2), root)
    except Exception:
        quarantine_evidence(root)
        failed = {"schema_version": "1.0.0", "kind": "m3-synthetic-integration-proof", "status": "failed",
                  "synthetic": True, "canonical": False, "biological_processing_validated": False,
                  "failure": {"type": "EvidenceValidationError",
                              "message": "Upload evidence validation failed; candidate files are quarantined outside the upload directory."}}
        (root / "evidence/integration-proof.json").write_text(json.dumps(failed, sort_keys=True, indent=2) + "\n")
        raise
    (root / "evidence/integration-proof.json").write_text(contents + "\n")


def git_output(repository: Path, *arguments: str) -> str:
    """Read a Git identity without consulting user hooks."""
    return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", *arguments], cwd=repository,
                          check=True, text=True, capture_output=True).stdout.strip()


def repository_identity(repository: Path, expected_sha: str) -> dict[str, str]:
    """Bind a clean checkout to an exact commit and the permitted origin."""
    require(bool(re.fullmatch(r"[0-9a-f]{40}", expected_sha)), "expected SHA must be exactly 40 lowercase hexadecimal characters")
    root = guarded_path(repository)
    require(git_output(root, "rev-parse", "--show-toplevel") == str(root), "repository must be its checkout root")
    origin = git_output(root, "remote", "get-url", "origin")
    allowed = {f"https://github.com/{EXPECTED_REPOSITORY}", f"https://github.com/{EXPECTED_REPOSITORY}.git",
               f"git@github.com:{EXPECTED_REPOSITORY}.git", f"ssh://git@github.com/{EXPECTED_REPOSITORY}.git"}
    require(origin in allowed, "missing or unexpected repository origin")
    actual = git_output(root, "rev-parse", "--verify", "HEAD^{commit}")
    require(actual == expected_sha, "requested commit is not checked out")
    require(not git_output(root, "status", "--porcelain", "--untracked-files=normal"), "integration requires a clean committed checkout")
    return {"repository": EXPECTED_REPOSITORY, "sha": actual, "origin": origin}


def nextflow_command(executable: str, checkout: Path, work: Path, output: Path, evidence: Path,
                     sha: str, run_id: str, mode: str, phase: str) -> list[str]:
    """Build first/resume/stub invocations while keeping scientific parameters identical."""
    require(mode in {"docker", "stub"}, "unknown execution mode")
    require(phase in {"first", "resume", "stub"}, "unknown execution phase")
    require(mode == "docker" or phase == "stub", "stub work must use a separate phase")
    profile = "m3_test,docker" if mode == "docker" else "m3_test"
    command = [executable, "-log", str(evidence / f"{phase}.nextflow.log"), "run", str(checkout),
               "-profile", profile, "--m3_repository_sha", sha, "--m3_run_id", run_id,
               "--outdir", str(output), "-work-dir", str(work),
               "-with-trace", str(evidence / f"{phase}.trace.tsv"),
               "-with-report", str(evidence / f"{phase}.report.html"),
               "-with-timeline", str(evidence / f"{phase}.timeline.html"),
               "-with-dag", str(evidence / f"{phase}.dag.html")]
    if phase == "resume":
        command.append("-resume")
    if mode == "stub":
        command.append("-stub-run")
    return command


def parse_trace(text: str) -> list[dict[str, str]]:
    """Parse the raw Nextflow trace and require task-level acceptance fields."""
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    require(set(reader.fieldnames or []) >= {"task_id", "hash", "name", "status", "exit", "container"}, "trace lacks required task fields")
    rows = [dict(row) for row in reader]
    require(bool(rows), "empty Nextflow trace")
    require(all(all(value is not None for value in row.values()) for row in rows), "malformed trace row")
    return rows


def process_name(name: str) -> str:
    """Remove Nextflow workflow scope and display tag from a task name."""
    return name.rsplit(":", 1)[-1].split(" (", 1)[0]


def validate_resume(first: list[dict[str, str]], repeated: list[dict[str, str]],
                    expected_processes: set[str] = EXPECTED_PROCESSES) -> dict[str, Any]:
    """Require actual initial execution and cache reuse of every repeated task."""
    require(all(row["status"] == "COMPLETED" and row["exit"] == "0" for row in first),
            "clean first run must contain successful executed tasks only")
    require(all(row["status"] == "CACHED" and row["exit"] in {"0", "-"} for row in repeated),
            "resume must reuse every successful task")
    require({process_name(row["name"]) for row in first} == expected_processes, "unexpected or missing M3 task set")
    first_tasks = {row["name"]: row["hash"] for row in first}
    repeat_tasks = {row["name"]: row["hash"] for row in repeated}
    require(len(first_tasks) == len(first) and len(repeat_tasks) == len(repeated), "trace task names are not unique")
    require(first_tasks == repeat_tasks, "resume changed task identities or hashes")
    require(all(not any(word in row["name"].lower() for word in ("haplotypecaller", "deepvariant", "benchmark")) for row in first),
            "caller or benchmark task leaked into shared preprocessing")
    return {"first_executed_tasks": len(first), "resumed_cached_tasks": len(repeated),
            "task_hashes_identical": True, "all_expected_processes_present": True}


def validate_trace_containers(rows: list[dict[str, str]], tools: dict[str, Any]) -> None:
    """Require executed tools to use their declared immutable Docker identities."""
    assignments = {
        "M3_REFERENCE_FAIDX": "samtools", "M3_SORT": "samtools", "M3_MERGE": "samtools",
        "M3_PRE_BQSR": "samtools", "M3_BAM_SUMMARY": "samtools", "M3_BWA_INDEX": "bwa-mem2",
        "M3_ALIGN": "bwa-mem2", "M3_FASTQC": "fastqc", "M3_REFERENCE_METADATA": "gatk",
        "M3_MARKDUP": "gatk", "M3_RECALIBRATE": "gatk", "M3_APPLY_BQSR": "gatk",
        "M3_PICARD_QC": "gatk", "M3_MOSDEPTH": "mosdepth", "M3_MULTIQC": "multiqc",
    }
    for row in rows:
        process = process_name(row["name"])
        if process in assignments:
            expected = tools["tools"][assignments[process]]["image"]
            require(row["container"] == expected, "executed task container differs from the pinned tool contract")
        else:
            require(process in {"M3_PREFLIGHT", "M3_FASTQ_VALIDATE", "M3_COLLECT"} and row["container"] in {"", "-", "null"},
                    "unexpected host task or container identity")


def validate_multiqc_ownership(rows: list[dict[str, str]], work: Path,
                              published_report: Path) -> dict[str, int | bool | str]:
    """Verify ownership of the container-created report and its published byte copy."""
    matches = [row for row in rows if process_name(row["name"]) == "M3_MULTIQC"]
    require(len(matches) == 1, "exactly one MultiQC task is required for ownership verification")
    task_hash = matches[0]["hash"]
    require(re.fullmatch(r"[0-9a-f]{2}/[0-9a-f]{6,30}", task_hash) is not None,
            "invalid MultiQC trace hash")
    prefix, remainder = task_hash.split("/")
    directory = guarded_path(work / prefix)
    candidates = [path for path in directory.glob(remainder + "*") if path.is_dir()]
    require(len(candidates) == 1, "MultiQC trace hash does not identify exactly one task directory")
    report = guarded_path(candidates[0] / "multiqc_report.html")
    require(report.is_file(), "original MultiQC task report is missing")
    observed = report.stat()
    require(observed.st_uid == os.getuid() and observed.st_gid == os.getgid(),
            "original MultiQC report ownership differs from the executing host user/group")
    source_hash = digest(report)
    require(source_hash == digest(published_report), "published MultiQC report differs from the task output")
    return {"task_report_uid": observed.st_uid, "task_report_gid": observed.st_gid,
            "host_uid": os.getuid(), "host_gid": os.getgid(),
            "task_report_owned_by_host_user_and_group": True,
            "published_bytes_match_task_report": True, "report_sha256": source_hash}


def validate_contract_identity(contracts: dict[str, dict[str, Any]], fixture: dict[str, Any],
                               sha: str, run_id: str, package_version: str,
                               bam_sha256: str, bai_sha256: str) -> None:
    """Bind package-validated result records to this exact execution and BAM."""
    require(set(contracts) == {"m3-manifest.json", "m3-alignment.json", "m3-qc.json", "m3-coverage.json", "m3-resources.json", "m3-provenance.json"},
            "unexpected result contract inventory")
    for record in contracts.values():
        require(record["run_id"] == run_id and record["producer"]["version"] == package_version,
                "result run or producing package version changed")
        require(record["synthetic"] is True and record["canonical"] is False and record["validation_status"] == "validated_synthetic",
                "result has an unsupported execution claim")
    bundle = contracts["m3-manifest.json"]["data"]
    provenance = contracts["m3-provenance.json"]["data"]
    alignment = contracts["m3-alignment.json"]["data"]
    reference_sha = fixture["files"]["reference.fa"]["sha256"]
    require(bundle["repository_sha"] == provenance["repository_sha"] == sha, "result repository SHA changed")
    require(bundle["reference_sha256"] == reference_sha and provenance["known_sites_sha256"] == fixture["files"]["known-sites.vcf"]["sha256"],
            "result reference or known-site identity differs from fixture source")
    require(bundle["shared_bam_sha256"] == provenance["shared_bam_sha256"] == alignment["bam"]["sha256"] == bam_sha256,
            "result contract identifies a different shared BAM")
    require(alignment["bai"]["sha256"] == bai_sha256, "result contract identifies a different BAI")
    require(alignment["sample"] == provenance["sample"] == fixture["sample"], "result sample identity changed")
    require(alignment["duplicates_retained"] is True and alignment["bqsr_applied"] is True, "required shared preprocessing is missing")
    require(provenance["callers_executed"] == [] and provenance["canonical_hg001_executed"] is False and provenance["capture_design_gate"] == "blocked",
            "caller, human-data or capture-domain claim leaked into synthetic preprocessing")


def validate_sam(sam: str, fixture: dict[str, Any]) -> dict[str, int | bool]:
    """Assert known invented alignments, read groups, retained OQ and duplicate flags.

    This is an independent integration oracle, not a producer of scientific
    benchmark metrics. FASTQ qualities are reversed for reverse-strand SAM reads.
    """
    headers: dict[str, list[dict[str, str]]] = {}
    records = []
    for line in sam.splitlines():
        fields = line.split("\t")
        if line.startswith("@"):
            headers.setdefault(fields[0], []).append(dict(field.split(":", 1) for field in fields[1:] if ":" in field))
        elif line:
            require(len(fields) >= 11, "malformed SAM alignment record")
            if not int(fields[1]) & (256 | 2048):
                records.append(fields)
    require(any(row.get("SO") == "coordinate" for row in headers.get("@HD", [])), "BAM is not declared coordinate sorted")
    references = {row["SN"]: int(row["LN"]) for row in headers.get("@SQ", [])}
    require(references == fixture["contigs"], "BAM reference dictionary differs from invented source")
    groups = {row["ID"]: row for row in headers.get("@RG", [])}
    expected_groups = {lane["read_group_id"] for lane in fixture["lanes"]}
    require(set(groups) == expected_groups, "read-group inventory changed")
    require(all(row.get("SM") == fixture["sample"] and row.get("LB") == fixture["library"] and row.get("PL") == "ILLUMINA" for row in groups.values()), "read-group sample/library/platform mismatch")
    require(len(records) == fixture["primary_read_count"], "unexpected primary read count")
    seen: set[str] = set()
    pair_duplicate_flags: dict[str, set[bool]] = {}
    mapped = duplicates = 0
    order = {name: index for index, name in enumerate(fixture["contigs"])}
    previous = (-1, -1)
    unmapped_seen = False
    for fields in records:
        flag = int(fields[1])
        require(bool(flag & 1), "synthetic paired read lost paired flag")
        require(bool(flag & 64) != bool(flag & 128), "read must have exactly one mate ordinal")
        key = fields[0] + ("/1" if flag & 64 else "/2")
        require(key not in seen and key in fixture["read_expectations"], "unknown or duplicate primary read identity")
        seen.add(key)
        pair_duplicate_flags.setdefault(fields[0], set()).add(bool(flag & 1024))
        expected = fixture["read_expectations"][key]
        tags = {item.split(":", 2)[0]: item.split(":", 2)[2] for item in fields[11:] if len(item.split(":", 2)) == 3}
        require(tags.get("RG") == expected["read_group"], "read-group tag changed")
        original = expected["original_qualities"][::-1] if flag & 16 else expected["original_qualities"]
        require(tags.get("OQ") == original, "original quality tag missing or changed")
        require(len(fields[10]) == fixture["read_length"], "recalibrated quality length changed")
        sequence = fields[9].translate(str.maketrans("ACGTNacgtn", "TGCANtgcan"))[::-1] if flag & 16 else fields[9]
        require(hashlib.sha256(sequence.encode()).hexdigest() == expected["sequence_sha256"], "read sequence changed during preprocessing")
        is_mapped = not flag & 4
        require(is_mapped == (expected["contig"] is not None), "expected mapping status changed")
        if is_mapped:
            mapped += 1
            require(not unmapped_seen, "mapped record follows terminal unmapped records")
            require(fields[2] == expected["contig"] and int(fields[3]) == expected["position_1based"], "synthetic alignment position changed")
            require(bool(flag & 16) == expected["reverse"], "synthetic alignment strand changed")
            coordinate = (order[fields[2]], int(fields[3]))
            require(coordinate >= previous, "BAM records are not coordinate ordered")
            previous = coordinate
        else:
            unmapped_seen = True
        if flag & 1024:
            duplicates += 1
            require(expected["duplicate_group"] is not None, "unexpected fragment marked duplicate")
    require(seen == set(fixture["read_expectations"]), "lost or added primary read")
    require(all(len(flags) == 1 for flags in pair_duplicate_flags.values()), "duplicate flags split a read pair")
    require(mapped == fixture["mapped_read_count"] and len(records) - mapped == fixture["unmapped_read_count"], "mapping totals differ from recipe")
    require(duplicates == fixture["duplicate_read_count"], "duplicate count differs from the known three-copy fragment")
    return {"primary_reads": len(records), "mapped_reads": mapped, "unmapped_reads": len(records) - mapped,
            "duplicate_reads": duplicates, "read_groups": len(groups), "oq_on_all_primary_reads": True,
            "exact_synthetic_alignments": True, "coordinate_sorted": True, "reference_dictionary_identical": True}


def file_inventory(root: Path) -> dict[str, str]:
    """Hash all published outputs except separately preserved execution reports."""
    return {path.relative_to(root).as_posix(): digest(path) for path in sorted(root.rglob("*"))
            if path.is_file() and "pipeline_info" not in path.relative_to(root).parts}


@dataclass
class Runner:
    """Execute argv without a shell and retain small nonsequence diagnostics."""
    root: Path
    environment: dict[str, str]
    commands: list[dict[str, Any]]

    def run(self, name: str, argv: list[str], cwd: Path, *, sequence_output: bool = False) -> str:
        """Run one checked command; sequence output stays outside uploadable evidence."""
        result = subprocess.run(argv, cwd=cwd, env=self.environment, text=True, capture_output=True)
        directory = self.root / ("inspection" if sequence_output else "diagnostics")
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{name}.stdout.txt").write_text(result.stdout)
        (directory / f"{name}.stderr.txt").write_text(result.stderr)
        if not sequence_output:
            evidence = self.root / "evidence"
            evidence.mkdir(exist_ok=True)
            stdout = safe_evidence_text(result.stdout, self.root)
            stderr = safe_evidence_text(result.stderr, self.root)
            (evidence / f"{name}.stdout.txt").write_text(stdout)
            (evidence / f"{name}.stderr.txt").write_text(stderr)
        self.commands.append({"name": name, "argv": [redact_text(arg, self.root) for arg in argv],
                              "cwd": redact_text(str(cwd), self.root), "exit_code": result.returncode})
        require(result.returncode == 0, f"{name} failed with exit {result.returncode}; see retained command diagnostics")
        return result.stdout


def inspect_bam(runner: Runner, docker: str, image: str, bam: Path, fixture: dict[str, Any]) -> dict[str, Any]:
    """Inspect the produced BAM/index through the exact pinned samtools container."""
    require(bool(re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", image)), "samtools image must be digest pinned")
    require(bam.is_file() and Path(str(bam) + ".bai").is_file(), "final BAM or matching BAI is missing")
    base = [docker, "run", "--rm", "--network", "none", "--platform", "linux/amd64", "--read-only",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m", "--volume", f"{bam.parent}:/data:ro", "--entrypoint", "samtools", image]
    runner.run("samtools-quickcheck", base + ["quickcheck", "-v", f"/data/{bam.name}"], runner.root)
    sam = runner.run("samtools-view", base + ["view", "-h", f"/data/{bam.name}"], runner.root, sequence_output=True)
    result: dict[str, Any] = validate_sam(sam, fixture)
    for contig, length in fixture["contigs"].items():
        count = runner.run(f"indexed-query-{contig}", base + ["view", "-c", f"/data/{bam.name}", f"{contig}:1-{length}"], runner.root)
        expected = sum(item["contig"] == contig for item in fixture["read_expectations"].values())
        require(int(count.strip()) == expected, "indexed region query differs from expected mapped reads")
    result["indexed_region_queries_valid"] = True
    result["samtools_version"] = runner.run("samtools-version", base + ["--version"], runner.root).splitlines()[0]
    result["bam_sha256"] = digest(bam)
    result["bai_sha256"] = digest(Path(str(bam) + ".bai"))
    return result


def storage_observation(output_root: Path) -> dict[str, int | bool]:
    """Measure the intended output filesystem without creating its directories."""
    candidate = guarded_path(output_root)
    while not candidate.exists():
        candidate = candidate.parent
    require(candidate.is_dir(), "output root has a non-directory ancestor")
    capacity = shutil.disk_usage(candidate)
    return {"free_bytes": capacity.free, "total_bytes": capacity.total,
            "minimum_free_bytes": MINIMUM_FREE_BYTES,
            "meets_synthetic_minimum": capacity.free >= MINIMUM_FREE_BYTES}


def validate_docker_capability(info: dict[str, Any]) -> dict[str, Any]:
    """Bound runtime claims to the observed engine and tiny synthetic requirements."""
    require(info.get("OSType") == "linux" and info.get("Architecture") in {"x86_64", "amd64"},
            "M3 integration requires an observed Linux/x86_64 Docker engine")
    require(type(info.get("NCPU")) is int and info["NCPU"] >= 1,
            "Docker must report at least one available CPU for synthetic M3 execution")
    require(type(info.get("MemTotal")) is int and info["MemTotal"] >= MINIMUM_DOCKER_MEMORY_BYTES,
            "Docker requires at least 4 GiB of assigned memory for synthetic M3; increase engine memory before retrying")
    return {key: info.get(key) for key in ("OSType", "Architecture", "ServerVersion", "NCPU", "MemTotal")}


def docker_info_format() -> str:
    """Build Docker's Go format while keeping daemon output limited to five facts.

    Compose Go delimiters explicitly so nf-core's source-template guard does not
    mistake Docker expressions for unfinished pipeline template substitutions.
    """
    fields = ("OSType", "Architecture", "ServerVersion", "NCPU", "MemTotal")
    return "{" + ",".join('"' + field + '":' + "{" * 2 + "json ." + field + "}" * 2 for field in fields) + "}"


def preflight(repository: Path, expected_sha: str, nextflow: str, docker: str,
              output_root: Path) -> dict[str, Any]:
    """Observe source and local executables without cloning, installing or running tasks."""
    identity = repository_identity(repository, expected_sha)
    resolved_nextflow = shutil.which(nextflow)
    resolved_docker = shutil.which(docker)
    return {"schema_version": "1.0.0", "status": "preflight_complete_execution_unverified", "repository": identity,
            "host_system": platform.system(), "host_architecture": platform.machine(),
            "nextflow_executable": resolved_nextflow, "docker_executable": resolved_docker,
            "storage": storage_observation(output_root), "execution_verified": False,
            "docker_executable_available": resolved_docker is not None, "docker_engine_verified": False}


def main(argv: list[str] | None = None) -> int:
    """Prepare or execute a fresh synthetic qualification and save honest evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--mode", choices=("preflight", "stub", "docker"), default="docker")
    parser.add_argument("--nextflow", default="nextflow")
    parser.add_argument("--docker", default="docker")
    args = parser.parse_args(argv)
    info = preflight(args.repository, args.expected_sha, args.nextflow, args.docker, args.output_root)
    if args.mode == "preflight":
        print(json.dumps(info, sort_keys=True))
        return 0
    require(info["nextflow_executable"] is not None, "Nextflow executable is unavailable")
    if args.mode == "docker":
        require(info["docker_executable"] is not None, "Docker is unavailable; real synthetic execution remains unverified")
        require(info["storage"]["meets_synthetic_minimum"],
                "synthetic M3 requires at least 10 GiB free on the output filesystem; free space or choose another output root before retrying")
    output_root = guarded_path(args.output_root)
    require(output_root not in {Path("/"), Path.home().resolve()}, "unsafe output root")
    require(not output_root.exists(), "output root already exists; preserve it and choose a fresh qualification directory")
    output_root.mkdir(parents=True)
    (output_root / "evidence").mkdir()
    (output_root / "raw-execution").mkdir()
    environment = {key: value for key, value in os.environ.items() if not key.startswith("BASH_FUNC_")}
    environment["NXF_ANSI_LOG"] = "false"
    environment["NXF_DISABLE_CHECK_LATEST"] = "true"
    runner = Runner(output_root, environment, [])
    proof: dict[str, Any] = {"schema_version": "1.0.0", "kind": "m3-synthetic-integration-proof",
                             "status": "in_progress", "mode": args.mode, "repository": info["repository"],
                             "synthetic": True, "canonical": False, "biological_processing_validated": False,
                             "host": {"system": platform.system(), "architecture": platform.machine()},
                             "storage": info["storage"], "commands": runner.commands}
    try:
        nf_version = runner.run("nextflow-version", [args.nextflow, "-version"], output_root)
        require(re.search(r"version\s+26\.04\.6\b", nf_version) is not None, "Nextflow version is not the pinned 26.04.6")
        proof["nextflow_version"] = nf_version.strip()
        if args.mode == "docker":
            docker_info = json.loads(runner.run("docker-info", [args.docker, "info", "--format", docker_info_format()], output_root))
            proof["docker"] = validate_docker_capability(docker_info)
            # Retain only relevant engine facts; a full info document may contain
            # host/proxy details unrelated to scientific execution evidence.
            (output_root / "evidence/docker-info.stdout.txt").write_text(json.dumps(proof["docker"], sort_keys=True) + "\n")
        checkout = output_root / "checkout"
        runner.run("clean-clone", ["git", "-c", "core.hooksPath=/dev/null", "clone", "--no-local", "--no-hardlinks", str(args.repository.resolve()), str(checkout)], output_root)
        runner.run("checkout-exact-sha", ["git", "-c", "core.hooksPath=/dev/null", "checkout", "--detach", args.expected_sha], checkout)
        runner.run("clone-origin", ["git", "remote", "set-url", "origin", info["repository"]["origin"]], checkout)
        require(repository_identity(checkout, args.expected_sha)["sha"] == args.expected_sha, "clean clone identity mismatch")
        package_environment = output_root / "package-venv"
        venv.EnvBuilder(with_pip=True, system_site_packages=False).create(package_environment)
        python = str(package_environment / "bin/python")
        runner.run("install-pinned-dependencies", [python, "-I", "-m", "pip", "install", "--disable-pip-version-check", "-r", str(checkout / "requirements-dev.txt")], output_root)
        runner.run("install-cloned-package", [python, "-I", "-m", "pip", "install", "--disable-pip-version-check", "--no-deps", "--force-reinstall", str(checkout)], output_root)
        proof["installed_dependency_versions"] = runner.run("installed-dependency-versions", [python, "-I", "-m", "pip", "freeze", "--all", "--exclude-editable"], output_root).splitlines()
        installed = runner.run("installed-package-identity", [python, "-I", "-m", "giab_wes_nextflow.runtime_identity", "--source-root", str(checkout), "--expected-sha", args.expected_sha], output_root)
        proof["installed_package"] = json.loads(installed)
        module_path = runner.run("isolated-wheel-location", [python, "-I", "-c", "import giab_wes_nextflow; print(giab_wes_nextflow.__file__)"], output_root).strip()
        require(Path(module_path).resolve().is_relative_to(package_environment.resolve()), "package was not installed inside the clean-clone environment")
        runner.environment["PATH"] = str(package_environment / "bin") + os.pathsep + runner.environment["PATH"]
        fixture_root = checkout / "tests/data/m3-generated"
        runner.run("generate-invented-fixture", [python, "-I", str(checkout / "tests/data/generate_m3_fixture.py"), "--output", str(fixture_root)], checkout)
        fixture_path = fixture_root / "fixture-expectations.json"
        fixture = json.loads(fixture_path.read_text())
        proof["fixture"] = {"manifest_sha256": digest(fixture_path), "recipe_version": fixture["recipe_version"],
                            "sample": fixture["sample"], "canonical": fixture["canonical"]}
        require(fixture["synthetic"] is True and fixture["canonical"] is False, "fixture is not explicitly invented noncanonical data")
        output = output_root / "published"
        work = output_root / "nextflow-work"
        run_id = "m3-ci-" + args.expected_sha[:12]
        first_phase = "stub" if args.mode == "stub" else "first"
        runner.run(first_phase, nextflow_command(args.nextflow, checkout, work, output, output_root / "raw-execution", args.expected_sha, run_id, args.mode, first_phase), checkout)
        contracts = output / "m3/contracts"
        manifest_path = contracts / "m3-manifest.json"
        require(manifest_path.is_file(), "M3 output manifest is missing")
        manifest = json.loads(manifest_path.read_text())
        if args.mode == "stub":
            require(manifest.get("status") == "stub_only" and manifest.get("validation_status") == "not_validated" and
                    manifest.get("biological_processing") is False and manifest.get("canonical") is False,
                    "stub output falsely claims biological validation")
            proof.update(status="stub_only", assertions={"stub_manifest_fail_closed": True})
        else:
            tools = json.loads((checkout / "config/m3-tools.json").read_text())
            bam = output / f"m3/{fixture['sample']}.analysis-ready.bam"
            proof["bam_assertions"] = inspect_bam(runner, args.docker, tools["tools"]["samtools"]["image"], bam, fixture)
            validate_samtools_version(proof["bam_assertions"]["samtools_version"], tools["tools"]["samtools"])
            # Canonical package validation owns scientific output schemas and
            # cross-artifact lineage; the driver does not duplicate that model.
            runner.run("validate-result-bundle", [python, "-I", "-m", "giab_wes_nextflow.m3_cli", "validate-bundle", "--bundle", str(contracts)], output_root)
            first_files = file_inventory(output / "m3")
            first_contracts = {path.name: json.loads(path.read_text()) for path in contracts.glob("*.json")}
            validate_contract_identity(first_contracts, fixture, args.expected_sha, run_id,
                                       str(proof["installed_package"]["version"]),
                                       proof["bam_assertions"]["bam_sha256"], proof["bam_assertions"]["bai_sha256"])
            runner.run("resume", nextflow_command(args.nextflow, checkout, work, output, output_root / "raw-execution", args.expected_sha, run_id, args.mode, "resume"), checkout)
            first_trace = parse_trace((output_root / "raw-execution/first.trace.tsv").read_text())
            second_trace = parse_trace((output_root / "raw-execution/resume.trace.tsv").read_text())
            proof["resume_assertions"] = validate_resume(first_trace, second_trace)
            validate_trace_containers(first_trace, tools)
            validate_trace_containers(second_trace, tools)
            proof["multiqc_permission_assertions"] = validate_multiqc_ownership(first_trace, work, output / "m3/multiqc_report.html")
            proof["resume_assertions"]["pinned_containers_identical"] = True
            require(first_files == file_inventory(output / "m3"), "resume changed published artifact bytes")
            require(first_contracts == {path.name: json.loads(path.read_text()) for path in contracts.glob("*.json")}, "resume changed contract semantics")
            proof["resume_assertions"].update(published_hashes_identical=True, contract_semantics_identical=True)
            proof.update(status="passed", biological_processing_validated=True, published_artifact_hashes=first_files)
        small_contracts = output_root / "evidence/contracts"
        small_contracts.mkdir()
        for path in contracts.glob("*.json"):
            require(safe_evidence_text(path.read_text(), output_root) == path.read_text(), "private path or signed URL in an output contract")
            shutil.copy2(path, small_contracts / path.name)
    except Exception as error:
        proof.update(status="failed", failure={"type": type(error).__name__, "message": str(error)}, biological_processing_validated=False)
        raise
    finally:
        finalize_proof(output_root, proof)
    print(json.dumps({"status": proof["status"], "proof": str(output_root / "evidence/integration-proof.json"),
                      "biological_processing_validated": proof["biological_processing_validated"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
