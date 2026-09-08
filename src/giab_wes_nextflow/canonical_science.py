"""Canonical full-reference preprocessing and symmetric chr20–22 comparison.

Tool execution belongs to the qualified runtime. Truth is admitted only by the
benchmark function. The M5 inclusion and metric algorithms are reused without
changing their synthetic evidence or claiming full-exome generalization.
"""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any

from .acquisition import checksum, destination
from .m3 import load_json
from .m5 import metrics, selected, require, vcf_rows, intersect

SAMPLE = "HG001"
CONTIGS = ("chr20", "chr21", "chr22")


def file_id(path: Path) -> dict[str, Any]:
    """Describe regular bytes without exposing a private source path."""
    require(path.is_file() and not path.is_symlink(), "missing or linked scientific artifact")
    return {"sha256": checksum(path), "bytes": path.stat().st_size}


def write_json(path: Path, value: Any) -> None:
    """Atomically finish local metadata after its described artifacts exist."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".incomplete")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    os.replace(temporary, path)


def stage_file(source: Path, target: Path) -> None:
    """Copy an input into the sole runtime mount and verify destination bytes."""
    expected = file_id(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        require(file_id(target) == expected, "staged input conflict")
        return
    # Independent copies prevent an executed caller from mutating another branch.
    shutil.copyfile(source, target)
    require(file_id(target) == expected, "staging copy mismatch")


class IndexedSequence:
    """Read exact FASTA slices through authenticated FAI without loading a genome."""
    def __init__(self, path: Path, length: int, offset: int, width: int, line_bytes: int):
        self.path, self.length, self.offset, self.width, self.line_bytes = path, length, offset, width, line_bytes

    def __len__(self) -> int:
        return self.length

    def __getitem__(self, key: slice) -> str:
        require(isinstance(key, slice) and key.step in (None, 1), "unsupported reference slice")
        start, stop, _ = key.indices(self.length)
        if stop <= start:
            return ""
        begin = self.offset + start // self.width * self.line_bytes + start % self.width
        end = self.offset + (stop - 1) // self.width * self.line_bytes + (stop - 1) % self.width + 1
        with self.path.open("rb") as stream:
            stream.seek(begin)
            sequence = stream.read(end - begin).replace(b"\n", b"").replace(b"\r", b"")
        require(len(sequence) == stop - start, "FAI slice length mismatch")
        return sequence.decode("ascii").upper()


def indexed_reference(reference: Path) -> dict[str, IndexedSequence]:
    """Open previously authenticated full-reference derivatives for bounded access."""
    result = {}
    for line in reference.with_name(reference.name + ".fai").read_text().splitlines():
        name, *numbers = line.split("\t")
        require(name not in result and len(numbers) == 4, "invalid FAI inventory")
        length, offset, width, line_bytes = map(int, numbers)
        require(length > 0 and width > 0 and line_bytes >= width, "invalid FAI values")
        result[name] = IndexedSequence(reference, length, offset, width, line_bytes)
    require(bool(result), "empty reference index")
    return result


class Commands:
    """Record actual commands; expose only a single task directory to each tool."""
    def __init__(self, runtime: Any, task: Path, stage: str):
        self.runtime, self.task, self.stage = runtime, task, stage
        self.records: list[dict[str, Any]] = []
        task.mkdir(parents=True, exist_ok=True)

    def run(self, tool: str, args: list[str], *, stdout: str | None = None) -> str:
        record = self.runtime.run(tool, args, task_dir=self.task, stage=self.stage,
                                  timeout_seconds=24 * 3600)
        self.records.append(record)
        require(record["returncode"] == 0, f"{tool} failed; inspect private task logs")
        source = Path(record["stdout_path"])
        if stdout:
            shutil.copyfile(source, self.task / stdout)
            return ""
        require(source.stat().st_size <= 64 * 1024 * 1024, "unexpectedly large command stdout")
        return source.read_text()


def validate_bam(commands: Commands, bam: str, reference: Path, *, oq: bool) -> dict[str, Any]:
    """Validate BAM/index, full dictionary, sample and every mapped record's OQ."""
    commands.run("samtools", ["quickcheck", "-v", bam])
    header = commands.run("samtools", ["view", "-H", bam])
    rows = [dict(f.split(":", 1) for f in line.split("\t")[1:]) for line in header.splitlines() if line.startswith("@SQ\t")]
    seqs = indexed_reference(reference)
    require([(r["SN"], int(r["LN"])) for r in rows] == [(c, len(s)) for c, s in seqs.items()], "BAM/reference dictionary mismatch")
    groups = [dict(f.split(":", 1) for f in line.split("\t")[1:]) for line in header.splitlines() if line.startswith("@RG\t")]
    require(bool(groups) and all(g.get("SM") == SAMPLE for g in groups), "BAM sample mismatch")
    allowed = {g["ID"] for g in groups}
    require(len(allowed) == len(groups), "duplicate BAM read-group ID")
    commands.run("samtools", ["view", bam], stdout="validate.sam")
    total, mapped, with_oq = 0, 0, 0
    with (commands.task / "validate.sam").open() as stream:
        for line in stream:
            fields = line.rstrip("\n").split("\t")
            require(len(fields) >= 11, "malformed SAM record")
            parts = [part.split(":", 2) for part in fields[11:]]
            require(all(len(part) == 3 for part in parts), "malformed SAM tag")
            require(len({part[0] for part in parts}) == len(parts), "duplicate SAM tag")
            tags = {part[0]: part[2] for part in parts}
            require(tags.get("RG") in allowed, "missing or foreign read group")
            total += 1
            if int(fields[1]) & 4 == 0:
                mapped += 1
                if "OQ" in tags:
                    require(len(tags["OQ"]) == len(fields[9]), "OQ/read length mismatch")
                    with_oq += 1
                require(not oq or "OQ" in tags, "mapped read missing retained OQ")
    (commands.task / "validate.sam").unlink()
    require(total > 0 and mapped > 0, "empty or unmapped BAM")
    # Index access must agree with a sequential count on the calling chromosomes.
    sequential = commands.run("samtools", ["view", "-c", "-F", "4", bam]).strip()
    indexed = sum(int(row.split("\t")[2]) for row in commands.run("samtools", ["idxstats", bam]).splitlines())
    require(indexed == int(sequential), "BAM index mapped-count mismatch")
    primary = int(commands.run("samtools", ["view", "-c", "-F", "2304", bam]).strip())
    return {"primary_records": primary, "records": total, "mapped_records": mapped, "mapped_records_with_oq": with_oq,
            "read_groups": sorted(allowed), "sample": SAMPLE, "dictionary_contigs": len(seqs)}


def preprocess(spec: dict[str, Any], runtime: Any, output: Path) -> dict[str, Any]:
    """Align all authenticated reads to full GRCh38, mark duplicates, apply BQSR."""
    require(set(spec) == {"fastq1", "fastq2", "index_dir", "known_sites_dir", "regions", "input_hashes"}, "unexpected preprocessing input (truth is forbidden)")
    output.mkdir(parents=True, exist_ok=True)
    task = output / "active"
    commands = Commands(runtime, task, "shared_preprocessing")
    for name, source in (("reads_1.fastq.gz", spec["fastq1"]), ("reads_2.fastq.gz", spec["fastq2"]), ("regions.bed", spec["regions"])):
        stage_file(Path(source), task / name)
    for source in Path(spec["index_dir"]).iterdir():
        if source.name.startswith("reference.") and source.suffix != ".json":
            stage_file(source, task / source.name)
    known = []
    for source in sorted(Path(spec["known_sites_dir"]).iterdir()):
        if source.name.endswith((".vcf.gz", ".vcf.gz.tbi")):
            stage_file(source, task / source.name)
            if source.name.endswith(".vcf.gz"):
                known += ["--known-sites", source.name]
    require(len(known) == 6, "three independent known-sites resources required")
    # The complete paired inputs are stream-validated before the aligner starts.
    from .m3 import read_pairs
    pairs = sum(1 for _ in read_pairs(task / "reads_1.fastq.gz", task / "reads_2.fastq.gz"))
    require(pairs > 0, "empty FASTQ pairs")
    cpus = str(runtime.cpus)
    commands.run("bwa", ["mem", "-t", cpus, "-R", "@RG\\tID:NIST7035.L001\\tSM:HG001\\tLB:NIST7035\\tPL:ILLUMINA\\tPU:NIST7035.L001", "reference.fa", "reads_1.fastq.gz", "reads_2.fastq.gz"], stdout="aligned.sam")
    commands.run("samtools", ["sort", "-@", cpus, "-m", "512M", "-T", "sorttmp", "-o", "sorted.bam", "aligned.sam"])
    (task / "aligned.sam").unlink()
    commands.run("gatk", ["--java-options", "-Xmx16g -Djava.io.tmpdir=.", "MarkDuplicates", "-I", "sorted.bam", "-O", "marked.bam", "-M", "duplicates.txt", "--REMOVE_DUPLICATES", "false", "--REMOVE_SEQUENCING_DUPLICATES", "false", "--READ_NAME_REGEX", "null", "--CREATE_INDEX", "true", "--VALIDATION_STRINGENCY", "STRICT"])
    commands.run("gatk", ["--java-options", "-Xmx16g -Djava.io.tmpdir=.", "BaseRecalibrator", "-R", "reference.fa", "-I", "marked.bam", *known, "-O", "recal.table"])
    commands.run("gatk", ["--java-options", "-Xmx16g -Djava.io.tmpdir=.", "ApplyBQSR", "-R", "reference.fa", "-I", "marked.bam", "--bqsr-recal-file", "recal.table", "--emit-original-quals", "true", "--create-output-bam-index", "false", "-O", "shared.bam"])
    commands.run("samtools", ["index", "-@", cpus, "shared.bam"])
    bam = validate_bam(commands, "shared.bam", task / "reference.fa", oq=True)
    require(bam["primary_records"] == pairs * 2, "preprocessing primary-read count differs from paired inputs")
    # Whole-reference coverage summary; this is not evaluation-domain coverage.
    commands.run("samtools", ["coverage", "shared.bam"], stdout="coverage.tsv")
    retained = ("shared.bam", "shared.bam.bai", "reference.fa", "reference.fa.fai", "reference.dict", "regions.bed", "duplicates.txt", "recal.table", "coverage.tsv")
    shared = output / "shared"; shared.mkdir(exist_ok=True)
    for name in retained:
        os.replace(task / name, shared / name)
    result = {"kind": "preprocessing", "status": "passed", "sample": SAMPLE, "aligner": "bwa-0.7.17", "fastq_pairs": pairs,
              "inputs": spec["input_hashes"], "bam_validation": bam, "quality_contract": {"gatk": "recalibrated_QUAL", "deepvariant": "retained_OQ"},
              "outputs": {name: file_id(shared / name) for name in retained}, "commands": commands.records}
    write_json(output / "receipt.json", result)
    shutil.rmtree(task)
    return result


def call(caller: str, shared: Path, runtime: Any, output: Path) -> dict[str, Any]:
    """Run one caller with only identical shared BAM/reference/calling regions."""
    require(caller in ("gatk", "deepvariant"), "unknown caller")
    output.mkdir(parents=True, exist_ok=True)
    task = output / "active"; commands = Commands(runtime, task, caller)
    inputs = {}
    for name in ("shared.bam", "shared.bam.bai", "reference.fa", "reference.fa.fai", "reference.dict", "regions.bed"):
        stage_file(shared / name, task / name); inputs[name] = file_id(task / name)
    if caller == "gatk":
        args = ["--java-options", "-Xmx16g -Djava.io.tmpdir=.", "HaplotypeCaller", "-R", "reference.fa", "-I", "shared.bam", "-L", "regions.bed", "-O", "raw.vcf.gz", "--sample-name", SAMPLE, "--native-pair-hmm-threads", str(runtime.cpus), "--standard-min-confidence-threshold-for-calling", "30.0", "--emit-ref-confidence", "NONE"]
    else:
        args = ["--model_type=WES", "--ref=reference.fa", "--reads=shared.bam", "--regions=regions.bed", f"--sample_name={SAMPLE}", f"--num_shards={runtime.cpus}", "--postprocess_cpus=0", "--make_examples_extra_args=use_original_quality_scores=true", "--output_vcf=raw.vcf.gz", "--intermediate_results_dir=intermediate", "--logging_dir=deepvariant.logs"]
    commands.run(caller, args)
    require(all(file_id(task / name) == expected for name, expected in inputs.items()), "caller mutated shared input bytes")
    commands.run("bcftools", ["index", "-f", "-t", "raw.vcf.gz"])
    require(commands.run("bcftools", ["query", "-l", "raw.vcf.gz"]).strip() == SAMPLE, "caller output sample mismatch")
    for name in ("raw.vcf.gz", "raw.vcf.gz.tbi"):
        os.replace(task / name, output / name)
    result = {"kind": caller, "status": "passed", "caller": caller, "sample": SAMPLE, "inputs": inputs,
              "outputs": {name: file_id(output / name) for name in ("raw.vcf.gz", "raw.vcf.gz.tbi")}, "commands": commands.records}
    write_json(output / "receipt.json", result)
    shutil.rmtree(task)
    return result


def verify_vcf_index(commands: Commands, filename: str, contigs: tuple[str, ...]) -> None:
    """Require indexed VCF retrieval to equal complete sequential records before use."""
    commands.run('bcftools', ['view', '-H', filename], stdout='index-check-sequential.txt')
    commands.run('bcftools', ['view', '-H', '-r', ','.join(contigs), filename], stdout='index-check-indexed.txt')
    sequential, indexed = commands.task / 'index-check-sequential.txt', commands.task / 'index-check-indexed.txt'
    require(file_id(sequential) == file_id(indexed), 'raw VCF index does not match sequential records')
    sequential.unlink(); indexed.unlink()


def validate_confidence_subset(evaluation: Path, confidence: Path, seqs: dict[str, Any]) -> dict[str, Any]:
    """Verify the fixed evaluation union is inside the actual supplied confidence BED."""
    order = {name: index for index, name in enumerate(seqs)}
    def read(path: Path) -> list[tuple[str, int, int]]:
        """Read and union plain/gzip BED3 without conditioning on variant calls."""
        with path.open('rb') as stream:
            compressed = stream.read(2) == b'\x1f\x8b'
        opener = gzip.open if compressed else open
        intervals = []
        with opener(path, 'rt') as stream:
            for line in stream:
                fields = line.rstrip('\n').split('\t')
                require(len(fields) == 3 and fields[0] in seqs, 'confidence/evaluation BED contig or shape mismatch')
                chrom, start, end = fields[0], int(fields[1]), int(fields[2])
                require(0 <= start < end <= len(seqs[chrom]), 'confidence/evaluation BED bounds mismatch')
                intervals.append((chrom, start, end))
        merged = []
        for chrom, start, end in sorted(intervals, key=lambda row: (order[row[0]], row[1], row[2])):
            if merged and merged[-1][0] == chrom and start <= merged[-1][2]:
                merged[-1] = (chrom, merged[-1][1], max(end, merged[-1][2]))
            else:
                merged.append((chrom, start, end))
        return merged
    selected_domain, confidence_domain = read(evaluation), read(confidence)
    require(bool(selected_domain) and intersect(selected_domain, confidence_domain, seqs) == selected_domain,
            'approved evaluation domain extends beyond supplied confidence regions')
    return {'confidence': file_id(confidence), 'evaluation': file_id(evaluation), 'evaluation_is_confident_subset': True}


def normalize(vcf: Path, reference: Path, runtime: Any, output: Path, *, sample: str = SAMPLE) -> dict[str, Any]:
    """Apply qualified M5 normalization with indexed full-reference validation."""
    output.mkdir(parents=True, exist_ok=True)
    commands = Commands(runtime, output, "common_downstream")
    for source, name in ((vcf, "raw.vcf.gz"), (Path(str(vcf) + ".tbi"), "raw.vcf.gz.tbi"), (reference, "reference.fa"), (Path(str(reference) + ".fai"), "reference.fa.fai")):
        stage_file(source, output / name)
    seqs = indexed_reference(output / "reference.fa")
    verify_vcf_index(commands, "raw.vcf.gz", tuple(seqs))
    commands.run("bcftools", ["norm", "-f", "reference.fa", "-c", "e", "-m", "-any", "--multi-overlaps", "0", "--old-rec-tag", "M5_ORIG", "--no-version", "-Ov", "-o", "split.vcf", "raw.vcf.gz"])
    commands.run("bcftools", ["sort", "-Ov", "-o", "sorted.vcf", "split.vcf"])
    # Upstream truth declares 22 autosomes; require a compatible ordered subset,
    # then canonicalize only the header to the authenticated full dictionary.
    lines = (output / "sorted.vcf").read_text().splitlines(keepends=True)
    declarations = []
    for line in lines:
        if line.startswith("##contig="):
            match = re.search(r"ID=([^,>]+),length=(\d+)", line)
            require(match is not None, "malformed source contig header")
            declarations.append((match[1], int(match[2])))
    require(bool(declarations) and len(dict(declarations)) == len(declarations), "missing or duplicate VCF contigs")
    require(declarations == [(c, len(seqs[c])) for c in seqs if c in dict(declarations)], "source VCF dictionary incompatible")
    header = [f"##contig=<ID={c},length={len(s)}>\n" for c, s in seqs.items()]
    canonical = []
    for line in lines:
        if line.startswith("##contig="):
            continue
        if line.startswith("#CHROM"):
            canonical.extend(header)
        canonical.append(line)
    (output / "dictionary.vcf").write_text("".join(canonical))
    headers, rows = vcf_rows(output / "dictionary.vcf", seqs, sample, split=True)
    rows, excluded = selected(rows)
    (output / "included.vcf").write_text("".join(headers) + "".join("\t".join(row) + "\n" for row in rows))
    commands.run("bcftools", ["view", "--no-version", "-Oz", "-o", "normalized.vcf.gz", "included.vcf"])
    commands.run("bcftools", ["index", "-t", "normalized.vcf.gz"])
    vcf_rows(output / "normalized.vcf.gz", seqs, sample, split=True)
    commands.run("bcftools", ["view", "-H", "normalized.vcf.gz"], stdout="sequential.txt")
    commands.run("bcftools", ["view", "-H", "-r", ",".join(seqs), "normalized.vcf.gz"], stdout="indexed.txt")
    require(checksum(output / "sequential.txt") == checksum(output / "indexed.txt"), "normalized index mismatch")
    result = {"kind": "normalization", "status": "passed", "input": file_id(vcf), "input_index": file_id(Path(str(vcf) + ".tbi")), "reference": file_id(reference), "records": len(rows), "excluded": excluded,
              "outputs": {name: file_id(output / name) for name in ("normalized.vcf.gz", "normalized.vcf.gz.tbi")}, "commands": commands.records}
    write_json(output / "receipt.json", result)
    for name in ("raw.vcf.gz", "raw.vcf.gz.tbi", "reference.fa", "reference.fa.fai", "split.vcf", "sorted.vcf", "dictionary.vcf", "included.vcf", "sequential.txt", "indexed.txt"):
        (output / name).unlink()
    return result


def benchmark(caller: str, raw: Path, shared: Path, spec: dict[str, Any], runtime: Any, output: Path) -> dict[str, Any]:
    """Normalize truth and query identically and count authoritative RTG partitions."""
    from .coding_domain import EXPECTED
    require(set(spec) == {"truth", "truth_index", "evaluation", "confidence"}, "unexpected benchmark specification")
    reference = shared / "reference.fa"
    require(checksum(Path(spec["evaluation"])) == EXPECTED["R_eval_holdout"][2], "unapproved evaluation denominator")
    confidence_evidence = validate_confidence_subset(Path(spec["evaluation"]), Path(spec["confidence"]), indexed_reference(reference))
    query = normalize(raw / "raw.vcf.gz", reference, runtime, output / "query")
    # Truth stays on benchmark side. Select only chr20–22 before normalization;
    # evaluation remains unpadded and includes uncovered/un-captured coding loci.
    task = output / "evaluation"; commands = Commands(runtime, task, "common_downstream")
    for source, name in ((Path(spec["truth"]), "source-truth.vcf.gz"), (Path(spec["truth_index"]), "source-truth.vcf.gz.tbi"), (reference, "reference.fa"), (Path(str(reference) + ".fai"), "reference.fa.fai"), (Path(spec["evaluation"]), "evaluation.bed")):
        stage_file(source, task / name)
    commands.run("bcftools", ["view", "--no-version", "-r", ",".join(CONTIGS), "-Oz", "-o", "truth.vcf.gz", "source-truth.vcf.gz"])
    # GIAB names the sample HG001; any discrepancy is an explicit failure.
    require(commands.run("bcftools", ["query", "-l", "truth.vcf.gz"]).strip() == SAMPLE, "truth sample mismatch")
    commands.run("bcftools", ["index", "-t", "truth.vcf.gz"])
    truth = normalize(task / "truth.vcf.gz", reference, runtime, output / "truth-normalized")
    for directory, stem in ((output / "query", "query"), (output / "truth-normalized", "baseline")):
        for suffix in (".vcf.gz", ".vcf.gz.tbi"):
            stage_file(directory / ("normalized" + suffix), task / (stem + suffix))
    commands.run("rtg", ["format", "-o", "reference.sdf", "reference.fa"])
    sdf = {p.relative_to(task / "reference.sdf").as_posix(): file_id(p) for p in sorted((task / "reference.sdf").rglob("*")) if p.is_file()}
    commands.run("rtg", ["vcfeval", "-b", "baseline.vcf.gz", "-c", "query.vcf.gz", "-t", "reference.sdf", "-o", "vcfeval", "--evaluation-regions", "evaluation.bed", "--sample", SAMPLE, "--all-records", "--ref-overlap", "--output-mode", "split", "--no-roc", "--sample-ploidy", "2", "--threads", str(runtime.cpus)])
    seqs = indexed_reference(task / "reference.fa")
    counts = {}
    for name in ("tp", "tp-baseline", "fp", "fn"):
        _, rows = vcf_rows(task / f"vcfeval/{name}.vcf.gz", seqs, SAMPLE, split=True)
        counts[name] = Counter("SNP" if len(f[3]) == len(f[4]) == 1 else "INDEL" if len(f[3]) != len(f[4]) else "OTHER" for f in rows)
    result = {"kind": "benchmark", "status": "passed", "confidence": confidence_evidence, "source_truth": file_id(Path(spec["truth"])), "source_truth_index": file_id(Path(spec["truth_index"])), "caller": caller, "domain_id": "R_eval_holdout", "domain_sha256": EXPECTED["R_eval_holdout"][2], "evaluated_bases": EXPECTED["R_eval_holdout"][1], "interval_count": EXPECTED["R_eval_holdout"][0], "query": query, "truth": truth, "reference_sdf": sdf,
              "metrics": {kind: metrics(counts["tp"][kind], counts["tp-baseline"][kind], counts["fp"][kind], counts["fn"][kind]) for kind in ("SNP", "INDEL", "OTHER")}, "commands": commands.records,
              "partitions": {p.name: file_id(p) for p in sorted((task / "vcfeval").iterdir()) if p.is_file()}}
    write_json(output / "receipt.json", result)
    # Keep authoritative private partitions, remove reproducible temporary inputs.
    for p in task.iterdir():
        if p.name not in {"vcfeval", "evaluation.bed"}:
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    return result


def main() -> None:
    """Expose isolated canonical stages for the dedicated Nextflow entrypoint."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preprocess", "call", "benchmark"))
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--shared", type=Path)
    parser.add_argument("--raw", type=Path)
    parser.add_argument("--caller", choices=("gatk", "deepvariant"))
    args = parser.parse_args()
    from .canonical_runtime import Runtime
    configuration = load_json(args.runtime)
    context = configuration.pop("checkpoint_context")
    runtime = Runtime(**configuration)
    from .canonical_checkpoint import hydrate, publish
    stage = args.action + ("-" + args.caller if args.caller else "")
    inputs = {"context": context, "action": stage}
    if args.spec:
        inputs["specification"] = file_id(args.spec)
    if args.shared:
        inputs["shared"] = {name: file_id(args.shared / name) for name in ("shared.bam", "shared.bam.bai", "reference.fa", "reference.fa.fai", "reference.dict", "regions.bed")}
    if args.raw:
        inputs["raw"] = file_id(args.raw / "raw.vcf.gz")
    key = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    checkpoint = destination(Path(context["drive_root"]), f"runs/{context['run_id']}/completed-stages/{stage}")
    if (checkpoint / "stage-complete.json").exists():
        hydrate(checkpoint, args.output, key)
        # Reuse observation is outside immutable scientific output. Its original
        # command timings remain historical and cannot become current free work.
        from datetime import datetime, timezone
        reuse = {"stage": stage, "cached": True, "kind": "durable_stage_reuse", "cache_key": key,
                 "origin_receipt_sha256": checksum(checkpoint / 'receipt.json'),
                 "observed_at": datetime.now(timezone.utc).isoformat()}
        write_json(runtime.root / 'audit' / ('durable-reuse-' + stage + '-' + str(__import__('time').time_ns()) + '.json'), reuse)
        print(json.dumps({"stage": stage, "status": "verified_durable_reuse", "checkpoint_key": key}))
        return
    if args.output.exists():
        # A failed local task has no marker and is never treated as completed.
        # Its diagnostics remain in the runtime audit; restart in a fresh output.
        incomplete = args.output.with_name(args.output.name + ".failed-" + str(__import__("time").time_ns()))
        args.output.rename(incomplete)
    if args.action == "preprocess":
        preprocess(load_json(args.spec), runtime, args.output)
    elif args.action == "call":
        call(args.caller, args.shared, runtime, args.output)
    else:
        benchmark(args.caller, args.raw, args.shared, load_json(args.spec), runtime, args.output)
    publish(args.output, Path(context["drive_root"]), context["run_id"], stage, key)


if __name__ == "__main__":
    main()
