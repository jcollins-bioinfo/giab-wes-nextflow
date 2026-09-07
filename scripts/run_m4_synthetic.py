#!/usr/bin/env python3
"""Qualify actual dual callers on one accepted invented BQSR BAM and its cache.

The allele oracle is fixed in this driver before calling. Caller tasks receive
isolated regular input files, no oracle or repository mounts, and no network.
Only sanitized execution diagnostics and JSON contracts enter the upload tree.
"""
from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import sys
from typing import Any, Sequence
import venv

import run_m3_synthetic as shared

require = shared.require
MINIMUM_FREE_BYTES = 30 * 1024 ** 3
MINIMUM_MEMORY_BYTES = 12 * 1024 ** 3
CALLER_PROCESSES = {"gatk": "M4_HAPLOTYPECALLER", "deepvariant": "M4_DEEPVARIANT"}
ORACLE = (
    {"contig": "chrSYN1", "position_1based": 3151, "ref": "T", "alt": "A", "genotype": "0/1", "ref_fragments": 40, "alt_fragments": 40},
    {"contig": "chrSYN2", "position_1based": 7101, "ref": "T", "alt": "A", "genotype": "1/1", "ref_fragments": 0, "alt_fragments": 80},
    {"contig": "chrSYN1", "position_1based": 5401, "ref": "G", "alt": None, "genotype": "0/0", "ref_fragments": 80, "alt_fragments": 0},
)


class Runner(shared.Runner):
    """Reuse safe command capture while exposing bounded failure diagnostics to CI."""

    def run(self, name: str, argv: list[str], cwd: Path, *, sequence_output: bool = False) -> str:
        """Print a failure tail only after both nonsequence streams pass redaction."""
        try:
            return super().run(name, argv, cwd, sequence_output=sequence_output)
        except ValueError:
            if not sequence_output:
                directory = self.root / "diagnostics"
                streams = [shared.safe_evidence_text((directory / f"{name}.{channel}.txt").read_text(), self.root)
                           for channel in ("stdout", "stderr")]
                tail = "\n".join(streams)[-12000:]
                if tail:
                    print(tail, file=sys.stderr)
            raise


def storage_observation(output: Path) -> dict[str, Any]:
    """Measure local disk before image preparation without creating output files."""
    result = shared.storage_observation(output)
    result.update(minimum_free_bytes=MINIMUM_FREE_BYTES,
                  meets_synthetic_minimum=result["free_bytes"] >= MINIMUM_FREE_BYTES)
    return result


def validate_capability(info: dict[str, Any], cpu: dict[str, Any], flags: Sequence[str]) -> dict[str, Any]:
    """Require measured Linux x86 AVX and sufficient standard-runner capacity."""
    engine = shared.validate_docker_capability(info)
    require(engine["NCPU"] >= 2 and engine["MemTotal"] >= MINIMUM_MEMORY_BYTES,
            "M4 requires at least two CPUs and 12 GiB Docker memory for the declared synthetic allocation")
    require(cpu.get("system") == "Linux" and cpu.get("architecture") in {"amd64", "x86_64"}, "M4 requires actual Linux x86_64 execution")
    require(set(flags) <= set(cpu.get("flags", [])), "M4 requires observed SSE4.1, SSE4.2 and AVX CPU support")
    return {"docker": engine, "cpu": cpu}


def nextflow_command(executable: str, checkout: Path, work: Path, output: Path,
                     reports: Path, sha: str, run_id: str, callers: str, phase: str) -> list[str]:
    """Keep scientific parameters stable while selecting callers and separate reports."""
    require(callers in {"gatk", "deepvariant", "both"}, "unsupported caller mode")
    require(phase in {"gatk", "deepvariant", "both", "resume"}, "unsupported integration phase")
    command = [executable, "-log", str(reports / f"{phase}.nextflow.log"), "run", str(checkout),
               "-profile", "m4_test,docker", "--m3_repository_sha", sha, "--m3_run_id", run_id,
               "--callers", callers, "--outdir", str(output), "-work-dir", str(work)]
    for flag, suffix in (("-with-trace", "trace.tsv"), ("-with-report", "report.html"),
                         ("-with-timeline", "timeline.html"), ("-with-dag", "dag.html")):
        command.extend((flag, str(reports / f"{phase}.{suffix}")))
    if phase != "gatk":
        command.append("-resume")
    return command


def validate_mode_traces(traces: dict[str, list[dict[str, str]]], m3_tools: dict[str, Any],
                         m4_tools: dict[str, Any]) -> dict[str, Any]:
    """Prove real independent callers, upstream reuse, both-mode reuse and full resume."""
    require(set(traces) == {"gatk", "deepvariant", "both", "resume"}, "missing caller-mode trace")
    prior: dict[str, str] = {}
    summary: dict[str, Any] = {}
    for mode in ("gatk", "deepvariant", "both", "resume"):
        rows = traces[mode]
        names = [row["name"] for row in rows]
        require(len(set(names)) == len(names), "duplicate task identity in trace")
        upstream = [row for row in rows if shared.process_name(row["name"]).startswith("M3_")]
        require(len(upstream) == 22 and {shared.process_name(row["name"]) for row in upstream} == shared.EXPECTED_PROCESSES,
                "M4 did not retain the complete accepted shared preprocessing topology")
        shared.validate_trace_containers(upstream, m3_tools)
        selected = {"gatk", "deepvariant"} if mode in {"both", "resume"} else {mode}
        expected_processes = shared.EXPECTED_PROCESSES | {"M4_PREPARE_INPUTS", "M4_BUNDLE"}
        expected_processes |= {CALLER_PROCESSES[caller] for caller in selected}
        expected_processes |= {"M4_COLLECT_" + caller.upper() for caller in selected}
        require({shared.process_name(row["name"]) for row in rows} == expected_processes, "unexpected or missing M4 task inventory")
        seen_callers: set[str] = set()
        for row in rows:
            process = shared.process_name(row["name"])
            selection = "both" if mode == "resume" else mode
            identity_key = row["name"] + "|selection:" + selection if process == "M4_BUNDLE" else row["name"]
            require(row["status"] in {"COMPLETED", "CACHED"} and row["exit"] in {"0", "-"}, "task failed or lacks success evidence")
            if identity_key in prior:
                require(prior[identity_key] == row["hash"] and row["status"] == "CACHED", "previous work was not reused with the identical task hash")
            else:
                require(row["status"] == "COMPLETED", "unseen task was cached before actual qualification")
            prior[identity_key] = row["hash"]
            for caller, expected in CALLER_PROCESSES.items():
                if process == expected:
                    seen_callers.add(caller)
                    require(row["container"] == m4_tools["tools"][caller]["image"], "caller container differs from immutable pin")
            if not process.startswith("M3_") and process not in CALLER_PROCESSES.values():
                require(process in {"M4_PREPARE_INPUTS", "M4_COLLECT_GATK", "M4_COLLECT_DEEPVARIANT", "M4_BUNDLE"}
                        and row["container"] in {"", "-", "null"}, "unexpected M4 task or container")
        require(seen_callers == selected, "caller selection differs from requested mode")
        if mode == "resume":
            require({row["name"]: row["hash"] for row in rows} == {row["name"]: row["hash"] for row in traces["both"]},
                    "both-mode resume changed task inventory or hashes")
        summary[mode] = dict(collections.Counter(row["status"] for row in rows))
        expected_counts = {"gatk": {"COMPLETED": 26}, "deepvariant": {"CACHED": 23, "COMPLETED": 3},
                           "both": {"CACHED": 27, "COMPLETED": 1}, "resume": {"CACHED": 28}}
        require(summary[mode] == expected_counts[mode], "unexpected executed or cached task counts for caller selection")
    return {"modes": summary, "upstream_tasks_per_mode": 22, "prior_task_hashes_reused": True,
            "both_callers_executed": True, "both_mode_resume_all_cached": True}


def task_directory(work: Path, row: dict[str, str]) -> Path:
    """Resolve an observed trace hash to exactly one guarded task directory."""
    value = row["hash"]
    require(re.fullmatch(r"[0-9a-f]{2}/[0-9a-f]{6,62}", value) is not None, "unsafe trace task hash")
    prefix, suffix = value.split("/")
    candidates = [path for path in (work / prefix).glob(suffix + "*") if path.is_dir()]
    require(len(candidates) == 1, "trace does not identify exactly one task directory")
    return shared.guarded_path(candidates[0])


def validate_caller_mounts(command: str, task: Path) -> dict[str, Any]:
    """Reject actual Docker mounts that expose anything outside the isolated task."""
    lines = command.replace("\\\n", " ").splitlines()
    launches = [line for line in lines if re.search(r"\bdocker\s+run\b", line)]
    require(len(launches) == 1, "caller wrapper must identify one Docker launch")
    launch = launches[0]
    require(re.search(r"--network(?:=|\s+)none(?:\s|$)", launch) is not None, "caller network is not disabled")
    require("--privileged" not in launch and "--volumes-from" not in launch and "--mount" not in launch,
            "unsupported caller container mount or privilege option")
    tokens = shlex.split(launch)
    volumes: list[str] = []
    for index, token in enumerate(tokens):
        if token in {"-v", "--volume"}:
            require(index + 1 < len(tokens), "missing container volume")
            volumes.append(tokens[index + 1])
        elif token.startswith("--volume="):
            volumes.append(token.split("=", 1)[1])
    require(bool(volumes), "caller Docker launch has no auditable task mount")
    logical_mounts = []
    for volume in volumes:
        source = volume.split(":", 1)[0]
        for variable in ("${NXF_TASK_WORKDIR}", "$NXF_TASK_WORKDIR", "${PWD}", "$PWD"):
            source = source.replace(variable, str(task))
        require("$" not in source and Path(source).is_absolute(), "unresolved or nonabsolute container mount")
        mounted = shared.guarded_path(Path(source))
        require(mounted == task or mounted.is_relative_to(task), "caller container exposes a parent, fixture, oracle or repository mount")
        logical_mounts.append("task" if mounted == task else "task/" + str(mounted.relative_to(task)))
    return {"network": "none", "mounts_within_task_only": True, "mounts": sorted(logical_mounts)}


def validate_staged_inputs(directory: Path, accepted_metadata: Path) -> dict[str, Any]:
    """Hash the exact regular files visible to the caller against accepted inputs."""
    root = shared.guarded_path(directory)
    require(root.is_dir(), "actual caller input directory is missing")
    record = json.loads(accepted_metadata.read_text())
    expected = {item["filename"]: item for item in record["data"]["files"]}
    require(set(expected) == {"shared.bam", "shared.bam.bai", "reference.fa", "reference.fa.fai", "reference.dict", "regions.bed"},
            "accepted caller input inventory is incomplete")
    paths = list(root.rglob("*"))
    require(len(paths) == 7 and {path.name for path in paths} == set(expected) | {"m4-inputs.json"}, "actual caller has missing or unexpected input files")
    require(all(path.parent == root and path.is_file() and not path.is_symlink() for path in paths), "actual caller inputs are nested or linked")
    observed = []
    for name, identity in expected.items():
        path = root / name
        current = {"filename": name, "bytes": path.stat().st_size, "sha256": shared.digest(path)}
        require(current == identity, "actual caller input bytes differ from the accepted shared input")
        observed.append(current)
    metadata_hash = shared.digest(root / "m4-inputs.json")
    require(metadata_hash == shared.digest(accepted_metadata), "actual caller metadata differs from accepted input contract")
    return {"exact_seven_regular_inputs": True, "actual_bytes_match_accepted_contract": True,
            "metadata_sha256": metadata_hash, "files": sorted(observed, key=lambda item: item["filename"])}


def validate_alleles(sam: str) -> dict[str, Any]:
    """Count predeclared allele-bearing fragments independently of any caller output."""
    support: dict[tuple[str, int], dict[str, str]] = {(site["contig"], site["position_1based"]): {} for site in ORACLE}
    for line in sam.splitlines():
        if not line or line.startswith("@"):
            continue
        fields = line.split("\t")
        require(len(fields) >= 11, "malformed actual BAM record")
        flag = int(fields[1])
        if flag & (4 | 256 | 2048):
            continue
        require(fields[5] == "150M", "M4 SNV oracle requires exact 150M alignments")
        start = int(fields[3])
        for site in ORACLE:
            if fields[2] != site["contig"] or not start <= site["position_1based"] < start + 150:
                continue
            base = fields[9][site["position_1based"] - start]
            fragments = support[(site["contig"], site["position_1based"])]
            require(fields[0] not in fragments or fragments[fields[0]] == base, "paired allele observations disagree")
            fragments[fields[0]] = base
    results = []
    for site in ORACLE:
        observed = collections.Counter(support[(site["contig"], site["position_1based"])].values())
        expected = {site["ref"]: site["ref_fragments"]}
        if site["alt"] is not None:
            expected[site["alt"]] = site["alt_fragments"]
        expected = {key: value for key, value in expected.items() if value}
        require(dict(observed) == expected, "actual shared BAM allele support differs from the frozen oracle")
        results.append({"contig": site["contig"], "position_1based": site["position_1based"], "fragment_counts": dict(observed)})
    return {"all_mapped_cigars_150M": True, "sites": results}


def validate_native_vcf(path: Path, sample: str) -> dict[str, Any]:
    """Check native SNV genotypes and the reference control without normalization."""
    observed: dict[tuple[str, int], tuple[str, list[str], str]] = {}
    header_seen = False
    with gzip.open(shared.guarded_path(path), "rt") as stream:
        for line in stream:
            if line.startswith("#CHROM"):
                require(line.rstrip().split("\t")[9:] == [sample], "native VCF sample differs from the shared BAM")
                header_seen = True
            elif not line.startswith("#"):
                fields = line.rstrip().split("\t")
                require(header_seen and len(fields) == 10, "malformed native single-sample VCF")
                key = (fields[0], int(fields[1]))
                format_fields = dict(zip(fields[8].split(":"), fields[9].split(":")))
                require("GT" in format_fields and key not in observed, "missing genotype or duplicate native VCF locus")
                observed[key] = (fields[3], fields[4].split(","), format_fields["GT"])
    require(header_seen, "native VCF has no sample header")
    for site in ORACLE:
        record = observed.get((site["contig"], site["position_1based"]))
        if site["alt"] is None:
            require(record is None or set(re.split(r"[/|]", record[2])) == {"0"}, "reference control has a nonreference call")
            continue
        require(record is not None and record[0] == site["ref"] and site["alt"] in record[1], "expected native SNV allele is absent")
        allele = str(record[1].index(site["alt"]) + 1)
        expected = ["0", allele] if site["genotype"] == "0/1" else [allele, allele]
        require(sorted(re.split(r"[/|]", record[2])) == sorted(expected), "native SNV genotype differs from frozen oracle")
    return {"expected_native_snvs_valid": True, "reference_control_nonvariant": True, "sample": sample}


def vcf_query_semantics(text: str) -> list[tuple[Any, ...]]:
    """Compare indexed native record identity without relying on numeric text formatting."""
    result = []
    for line in text.splitlines():
        if line.startswith("#") or not line:
            continue
        fields = line.split("\t")
        require(len(fields) == 10, "indexed VCF record is not single-sample")
        info = dict(item.split("=", 1) for item in fields[7].split(";") if "=" in item)
        sample = dict(zip(fields[8].split(":"), fields[9].split(":")))
        result.append((fields[0], int(fields[1]), fields[3], fields[4], sample.get("GT"), info.get("END")))
    require(bool(result), "indexed native output contains no records")
    return result


def inspect_native_indexes(runner: shared.Runner, docker: str, image: str,
                           paths: Sequence[Path], contigs: dict[str, int], caller: str) -> dict[str, Any]:
    """Exercise actual native VCF/gVCF random access using the pinned image's reader."""
    regions = ",".join(f"{name}:1-{length}" for name, length in contigs.items())
    observations = []
    for index, path in enumerate(paths):
        command = [docker, "run", "--rm", "--network", "none", "--platform", "linux/amd64", "--read-only",
                   "--user", f"{os.getuid()}:{os.getgid()}", "--volume", f"{path.parent}:/data:ro",
                   "--entrypoint", "/opt/conda/envs/bio/bin/bcftools", image,
                   "view", "-H", "-r", regions, "/data/" + path.name]
        indexed = runner.run(f"indexed-native-{caller}-{index}", command, runner.root, sequence_output=True)
        with gzip.open(path, "rt") as stream:
            unindexed = stream.read()
        rows = vcf_query_semantics(indexed)
        require(rows == vcf_query_semantics(unindexed), "native index queries differ from the sequential native records")
        observations.append({"filename": path.name, "records": len(rows), "index_query_matches_sequential_records": True})
    return {"reader_image": image, "fixed_full_reference_domain": regions, "files": observations}


def validate_inference(before: dict[str, Any], after: dict[str, Any], metadata_sha256: str,
                       contigs: set[str]) -> dict[str, Any]:
    """Bind positive actual inference to the WES files frozen before model execution."""
    require(before.get("kind") == "m4_deepvariant_model_inventory" and after.get("kind") == "m4_deepvariant_inference",
            "missing actual DeepVariant model or inference evidence")
    require(before.get("schema_version") == after.get("schema_version") == "1.0.0" and
            before.get("model_type") == after.get("model_type") == "WES", "unexpected inference contract")
    files = before.get("model_files", [])
    expected = {"fingerprint.pb", "saved_model.pb", "model.example_info.json",
                "variables/variables.data-00000-of-00001", "variables/variables.index"}
    require(len(files) == len(expected) and {item["filename"] for item in files} == expected, "incomplete WES model inventory")
    require(all(type(item["bytes"]) is int and item["bytes"] > 0 and re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) for item in files),
            "invalid model file identity")
    require(next(item["sha256"] for item in files if item["filename"] == "model.example_info.json") == metadata_sha256,
            "model metadata differs from pinned identity")
    require(files == after.get("model_files"), "model bytes changed after the pre-inference freeze")
    require(all(type(after.get(key)) is int and after[key] > 0 for key in ("example_record_count", "call_variants_record_count")),
            "DeepVariant did not produce nonzero candidates and predictions")
    require(after.get("all_probabilities_valid") is True and after.get("probability_tolerance") == 1e-5,
            "DeepVariant predictions lack strict probability validation")
    require(bool(after.get("variant_contigs")) and set(after["variant_contigs"]) <= contigs, "inference variants use unknown contigs")
    for key in ("example_files", "call_variants_files"):
        identities = after.get(key, [])
        require(bool(identities) and len({item["filename"] for item in identities}) == len(identities), "missing or duplicate inference artifact identity")
        require(all(Path(item["filename"]).name == item["filename"] and type(item["bytes"]) is int and item["bytes"] > 0
                    and re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) for item in identities), "invalid inference artifact identity")
    return {**after, "pre_inference_model_hashes_identical": True}


def validate_execution_identity(contracts: Path, sha: str, run_id: str, version: str,
                                fixture: dict[str, Any], fixture_sha256: str,
                                bam_sha256: str, bai_sha256: str, preprocessing: Path) -> None:
    """Bind package-validated caller records to this actual checkout and shared BAM."""
    records = [json.loads(path.read_text()) for path in contracts.glob("*.json")]
    require(all(record["run_id"] == run_id and record["producer"]["version"] == version and
                record["data"]["repository_sha"] == sha for record in records), "caller contract differs from this exact run or installed package")
    inputs = json.loads((contracts / "m4-inputs.json").read_text())["data"]
    files = {item["filename"]: item for item in inputs["files"]}
    require(inputs["fixture_id"] == "m4-snv-positive" and inputs["fixture_manifest_sha256"] == fixture_sha256,
            "caller input fixture differs from the frozen source")
    require(files["shared.bam"]["sha256"] == bam_sha256 and files["shared.bam.bai"]["sha256"] == bai_sha256,
            "caller contracts do not identify the actual shared BAM and BAI")
    require(inputs["preprocessing_manifest_sha256"] == shared.digest(preprocessing), "caller preprocessing lineage differs from accepted M3 manifest")
    require(files["reference.fa"]["sha256"] == fixture["files"]["reference.fa"]["sha256"] and
            inputs["known_sites_sha256"] == fixture["files"]["known-sites.vcf"]["sha256"], "caller reference or known-sites identity changed")
    expected_regions = [{"contig": name, "start": 0, "end": length} for name, length in fixture["contigs"].items()]
    require(inputs["calling_regions"] == expected_regions and inputs["quality_policy"] == {"gatk": "QUAL", "deepvariant": "OQ"},
            "caller domain or effective-quality policy differs from the frozen contract")


def finalize_proof(root: Path, proof: dict[str, Any]) -> None:
    """Use the shared privacy boundary while retaining an honest M4 failure identity."""
    try:
        proof["execution_reports"] = shared.finish_evidence(root)
        proof["evidence_hashes"] = shared.file_inventory(root / "evidence")
        text = shared.safe_evidence_text(json.dumps(shared.sanitize_json(proof, root), sort_keys=True, indent=2), root)
    except Exception:
        shared.quarantine_evidence(root)
        failed = {"schema_version": "1.0.0", "kind": "m4-synthetic-integration-proof", "status": "failed",
                  "synthetic": True, "canonical": False, "biological_processing_validated": False,
                  "failure": {"type": "EvidenceValidationError", "message": "Unsafe evidence was quarantined outside the upload directory."}}
        (root / "evidence/integration-proof.json").write_text(json.dumps(failed, sort_keys=True, indent=2) + "\n")
        raise
    (root / "evidence/integration-proof.json").write_text(text + "\n")


def prepare_checkout(runner: shared.Runner, repository: Path, sha: str,
                     origin: str, proof: dict[str, Any]) -> tuple[Path, str]:
    """Install and verify exactly the clean cloned package before creating fixtures."""
    root = runner.root
    checkout = root / "checkout"
    runner.run("clean-clone", ["git", "-c", "core.hooksPath=/dev/null", "clone", "--no-local", "--no-hardlinks", str(repository.resolve()), str(checkout)], root)
    runner.run("checkout-exact-sha", ["git", "-c", "core.hooksPath=/dev/null", "checkout", "--detach", sha], checkout)
    runner.run("clone-origin", ["git", "remote", "set-url", "origin", origin], checkout)
    shared.repository_identity(checkout, sha)
    environment = root / "package-venv"
    venv.EnvBuilder(with_pip=True, system_site_packages=False).create(environment)
    python = str(environment / "bin/python")
    runner.run("install-pinned-dependencies", [python, "-I", "-m", "pip", "install", "--disable-pip-version-check", "-r", str(checkout / "requirements-dev.txt")], root)
    runner.run("install-cloned-package", [python, "-I", "-m", "pip", "install", "--disable-pip-version-check", "--no-deps", "--force-reinstall", str(checkout)], root)
    proof["installed_dependency_versions"] = runner.run("installed-dependency-versions", [python, "-I", "-m", "pip", "freeze", "--all", "--exclude-editable"], root).splitlines()
    proof["installed_package"] = json.loads(runner.run("installed-package-identity", [python, "-I", "-m", "giab_wes_nextflow.runtime_identity", "--source-root", str(checkout), "--expected-sha", sha], root))
    location = runner.run("isolated-wheel-location", [python, "-I", "-c", "import giab_wes_nextflow; print(giab_wes_nextflow.__file__)"], root).strip()
    require(Path(location).resolve().is_relative_to(environment.resolve()), "package did not import from the isolated installation")
    runner.environment["PATH"] = str(environment / "bin") + os.pathsep + runner.environment["PATH"]
    return checkout, python


def main(argv: Sequence[str] | None = None) -> int:
    """Execute all required caller modes and publish only sanitized verified evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--mode", choices=("preflight", "docker"), default="docker")
    parser.add_argument("--nextflow", default="nextflow")
    parser.add_argument("--docker", default="docker")
    args = parser.parse_args(argv)
    info = shared.preflight(args.repository, args.expected_sha, args.nextflow, args.docker, args.output_root)
    info["storage"] = storage_observation(args.output_root)
    if args.mode == "preflight":
        print(json.dumps(info, sort_keys=True))
        return 0
    require(info["nextflow_executable"] is not None and info["docker_executable"] is not None, "M4 requires Nextflow and a real Docker runtime")
    require(platform.system() == "Linux" and platform.machine() in {"x86_64", "amd64"}, "M4 actual qualification requires Linux x86_64")
    require(info["storage"]["meets_synthetic_minimum"], "M4 requires at least 30 GiB free before preparing immutable images")
    root = shared.guarded_path(args.output_root)
    require(root not in {Path("/"), Path.home().resolve()} and not root.exists(), "choose a fresh safe M4 output root")
    root.mkdir(parents=True)
    (root / "evidence").mkdir()
    (root / "raw-execution").mkdir()
    environment = {key: value for key, value in os.environ.items() if not key.startswith("BASH_FUNC_")}
    environment.update(NXF_ANSI_LOG="false", NXF_DISABLE_CHECK_LATEST="true")
    runner = Runner(root, environment, [])
    proof: dict[str, Any] = {"schema_version": "1.0.0", "kind": "m4-synthetic-integration-proof", "status": "in_progress",
                             "mode": "docker", "repository": info["repository"], "synthetic": True, "canonical": False,
                             "biological_processing_validated": False, "storage_before": info["storage"], "commands": runner.commands}
    try:
        nf = runner.run("nextflow-version", [args.nextflow, "-version"], root)
        require(re.search(r"version\s+26\.04\.6\b", nf) is not None, "Nextflow does not match pinned 26.04.6")
        proof["nextflow_version"] = nf.strip()
        engine = json.loads(runner.run("docker-info", [args.docker, "info", "--format", shared.docker_info_format()], root))
        cpu_text = Path("/proc/cpuinfo").read_text()
        cpu = {"system": platform.system(), "architecture": platform.machine(),
               "flags": sorted(set(re.search(r"(?m)^flags\s*:\s*(.+)$", cpu_text).group(1).split()))}
        lock = json.loads((args.repository / "config/m4-tools.json").read_text())
        proof["capability"] = validate_capability(engine, cpu, lock["tools"]["deepvariant"]["cpu_required_flags"])
        checkout, python = prepare_checkout(runner, args.repository, args.expected_sha, info["repository"]["origin"], proof)
        lock = json.loads((checkout / "config/m4-tools.json").read_text())
        m3_tools = json.loads((checkout / "config/m3-tools.json").read_text())
        dv_image = lock["tools"]["deepvariant"]["image"]
        runner.run("prepare-deepvariant-image", [args.docker, "pull", dv_image], root)
        fields = ("Id", "RepoDigests", "Os", "Architecture", "Size")
        image_format = "{" + ",".join('"' + field + '":' + "{" * 2 + "json ." + field + "}" * 2 for field in fields) + "}"
        proof["deepvariant_image"] = json.loads(runner.run("inspect-deepvariant-image", [args.docker, "image", "inspect", dv_image, "--format", image_format], root))
        require(proof["deepvariant_image"]["Os"] == "linux" and proof["deepvariant_image"]["Architecture"] == "amd64", "pulled image has unexpected architecture")
        require(any(value.endswith(dv_image.split("@", 1)[1]) for value in proof["deepvariant_image"]["RepoDigests"]), "pulled image lacks the pinned manifest digest")
        cpu_program = ("import json,platform,re; from pathlib import Path; "
                       "flags=re.search(r'(?m)^flags\\s*:\\s*(.+)$',Path('/proc/cpuinfo').read_text()).group(1).split(); "
                       "print(json.dumps({'system':platform.system(),'architecture':platform.machine(),'flags':sorted(set(flags))}))")
        in_image = json.loads(runner.run("deepvariant-runtime-capability", [args.docker, "run", "--rm", "--network", "none",
                                   "--platform", "linux/amd64", "--user", f"{os.getuid()}:{os.getgid()}",
                                   "--entrypoint", "/usr/bin/python3", dv_image, "-c", cpu_program], root))
        proof["in_container_capability"] = validate_capability(engine, in_image, lock["tools"]["deepvariant"]["cpu_required_flags"])
        reader_version = runner.run("native-index-reader-version", [args.docker, "run", "--rm", "--network", "none", "--platform", "linux/amd64",
                      "--user", f"{os.getuid()}:{os.getgid()}", "--entrypoint", "/opt/conda/envs/bio/bin/bcftools", dv_image, "--version"], root).splitlines()[0]
        require(reader_version == "bcftools 1.15", "native index reader differs from the pinned image's declared build")
        proof["native_index_reader"] = {"version": reader_version, "image": dv_image}
        proof["storage_after_image"] = storage_observation(root)
        require(proof["storage_after_image"]["free_bytes"] >= 10 * 1024 ** 3, "insufficient work space remains after image preparation")
        fixture_root = checkout / "tests/data/m4-generated"
        runner.run("generate-invented-fixture", [python, "-I", "-m", "giab_wes_nextflow.m4_fixture", "--output", str(fixture_root)], root)
        fixture_path = fixture_root / "fixture-expectations.json"
        fixture = json.loads(fixture_path.read_text())
        require(fixture["synthetic"] is True and fixture["canonical"] is False, "fixture is not invented noncanonical data")
        frozen = {"schema_version": "1.0.0", "kind": "m4_predeclared_acceptance_oracle", "sites": ORACLE,
                  "fixture_manifest_sha256": shared.digest(fixture_path), "tool_lock_sha256": shared.digest(checkout / "config/m4-tools.json")}
        oracle_bytes = (json.dumps(frozen, sort_keys=True, indent=2) + "\n").encode()
        (root / "evidence/frozen-oracle.json").write_bytes(oracle_bytes)
        proof["oracle_sha256"] = hashlib.sha256(oracle_bytes).hexdigest()
        proof["fixture"] = {"manifest_sha256": frozen["fixture_manifest_sha256"], "sample": fixture["sample"], "recipe_version": fixture["recipe_version"]}
        output, work = root / "published", root / "nextflow-work"
        run_id = "m4-ci-" + args.expected_sha[:12]
        traces: dict[str, list[dict[str, str]]] = {}
        native_snapshots: dict[str, dict[str, str]] = {}
        contract_snapshots: dict[str, dict[str, Any]] = {}
        proof["native_assertions"] = {}
        proof["native_index_assertions"] = {}
        proof["caller_isolation"] = {}
        for phase, mode in (("gatk", "gatk"), ("deepvariant", "deepvariant"), ("both", "both"), ("resume", "both")):
            runner.run(phase, nextflow_command(args.nextflow, checkout, work, output, root / "raw-execution", args.expected_sha, run_id, mode, phase), checkout)
            traces[phase] = shared.parse_trace((root / f"raw-execution/{phase}.trace.tsv").read_text())
            contracts = output / f"m4/{mode}/contracts"
            runner.run(f"validate-bundle-{phase}", [python, "-I", "-m", "giab_wes_nextflow.m4_cli", "validate-bundle", "--bundle", str(contracts)], root)
            bam = output / f"m3/{fixture['sample']}.analysis-ready.bam"
            identity = {"bam": shared.digest(bam), "bai": shared.digest(Path(str(bam) + ".bai"))}
            if "shared_bam_identity" in proof:
                require(proof["shared_bam_identity"] == identity, "shared BAM or BAI bytes changed across modes")
            proof["shared_bam_identity"] = identity
            validate_execution_identity(contracts, args.expected_sha, run_id, proof["installed_package"]["version"], fixture,
                frozen["fixture_manifest_sha256"], identity["bam"], identity["bai"], output / "m3/contracts/m3-manifest.json")
            selected = ("gatk", "deepvariant") if mode == "both" else (mode,)
            for caller in selected:
                native = output / f"m4/{mode}/{fixture['sample']}.{caller}.native.vcf.gz"
                require(Path(str(native) + ".tbi").is_file(), "native VCF index is absent")
                proof["native_assertions"][f"{phase}:{caller}"] = validate_native_vcf(native, fixture["sample"])
                current = {name: shared.digest(path) for name, path in (("vcf", native), ("index", Path(str(native) + ".tbi")))}
                if caller == "deepvariant":
                    gvcf = native.with_name(native.name.replace(".native.vcf.gz", ".native.g.vcf.gz"))
                    for label, path in (("gvcf", gvcf), ("gvcf_index", Path(str(gvcf) + ".tbi"))):
                        require(path.is_file(), "DeepVariant native gVCF or index is absent")
                        current[label] = shared.digest(path)
                record = json.loads((contracts / f"m4-{caller}.json").read_text())
                output_keys = {"vcf": "vcf", "index": "vcf_index", "gvcf": "gvcf", "gvcf_index": "gvcf_index"}
                require(all(record["data"]["outputs"][output_keys[key]]["sha256"] == value for key, value in current.items()),
                        "caller contract identifies native output bytes different from actual published files")
                if caller in native_snapshots:
                    require(native_snapshots[caller] == current and contract_snapshots[caller] == record,
                            "caller outputs or contract semantics changed across selection/resume modes")
                else:
                    native_snapshots[caller], contract_snapshots[caller] = current, record
                    paths = [native] if caller == "gatk" else [native, gvcf]
                    proof["native_index_assertions"][caller] = inspect_native_indexes(runner, args.docker, dv_image, paths, fixture["contigs"], caller)
                    row = next(row for row in traces[phase] if shared.process_name(row["name"]) == CALLER_PROCESSES[caller])
                    task = task_directory(work, row)
                    command = (task / ".command.run").read_text()
                    proof["caller_isolation"][caller] = validate_caller_mounts(command, task)
                    proof["caller_isolation"][caller]["staged_input_identity"] = validate_staged_inputs(task / "caller-inputs", contracts / "m4-inputs.json")
                    (root / f"raw-execution/{caller}.command.run.txt").write_text(command)
                    if caller == "deepvariant":
                        before_path = task / "m4-deepvariant-model-before.json"
                        after_path = task / "m4-deepvariant-inference.json"
                        proof["deepvariant_inference"] = validate_inference(json.loads(before_path.read_text()), json.loads(after_path.read_text()),
                            lock["tools"]["deepvariant"]["model"]["example_info_sha256"], set(fixture["contigs"]))
                        for path in (before_path, after_path):
                            shutil.copy2(path, root / "evidence" / path.name)
            if phase == "gatk":
                proof["bam_assertions"] = shared.inspect_bam(runner, args.docker, m3_tools["tools"]["samtools"]["image"], bam, fixture)
                shared.validate_samtools_version(proof["bam_assertions"]["samtools_version"], m3_tools["tools"]["samtools"])
                sam = (root / "inspection/samtools-view.stdout.txt").read_text()
                proof["allele_assertions"] = validate_alleles(sam)
            target = root / f"evidence/contracts/{phase}"
            target.mkdir(parents=True)
            for path in contracts.glob("*.json"):
                require(shared.safe_evidence_text(path.read_text(), root) == path.read_text(), "caller contract requires forbidden redaction")
                shutil.copy2(path, target / path.name)
        proof["mode_and_resume_assertions"] = validate_mode_traces(traces, m3_tools, lock)
        proof["multiqc_permission_assertions"] = shared.validate_multiqc_ownership(traces["gatk"], work, output / "m3/multiqc_report.html")
        require((root / "evidence/frozen-oracle.json").read_bytes() == oracle_bytes and shared.digest(fixture_path) == frozen["fixture_manifest_sha256"], "acceptance oracle or fixture changed after calling")
        proof.update(status="passed", biological_processing_validated=True, native_hashes=native_snapshots,
                     per_caller_contracts_identical_across_modes=True, storage_after=storage_observation(root))
    except Exception as error:
        proof.update(status="failed", biological_processing_validated=False, failure={"type": type(error).__name__, "message": str(error)})
        raise
    finally:
        finalize_proof(root, proof)
    print(json.dumps({"status": proof["status"], "biological_processing_validated": True, "proof": str(root / "evidence/integration-proof.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
