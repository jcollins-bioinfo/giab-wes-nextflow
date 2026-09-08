"""Execute invented positive caller probes to qualify a Colab runtime.

The fixture recipe is preserved. This is a new runtime smoke test with classic
BWA and OQ; it does not replace historical M4 accuracy or full BQSR evidence.
"""
from __future__ import annotations

import gzip
import re
import shutil
from pathlib import Path
from typing import Any

from .canonical_science import Commands, file_id, write_json
from .m4_fixture import generate_m4_fixture
from .m5 import require


def _qualify_once(runtime: Any, directory: Path) -> dict[str, Any]:
    """Require native GATK and DeepVariant calls at both preregistered SNV sites."""
    fixture_root = directory / 'fixture'
    fixture = generate_m4_fixture(fixture_root)
    task = directory / 'preparation'
    task.mkdir(parents=True)
    for name in ['reference.fa', *(lane[key] for lane in fixture['lanes'] for key in ('fastq_1', 'fastq_2'))]:
        shutil.copyfile(fixture_root / name, task / name)
    versions = check_versions(runtime, task)
    commands = Commands(runtime, task, "runtime-qualification")
    commands.run("bwa", ["index", "-a", "bwtsw", "reference.fa"])
    commands.run("samtools", ["faidx", "reference.fa"])
    commands.run("gatk", ["CreateSequenceDictionary", "-R", "reference.fa", "-O", "reference.dict"])
    bams = []
    for number, lane in enumerate(fixture["lanes"]):
        rg = f"@RG\\tID:{lane['read_group_id']}\\tSM:SYNTHETIC01\\tLB:SYN_LIB\\tPL:ILLUMINA"
        commands.run("bwa", ["mem", "-t", "2", "-R", rg, "reference.fa", lane["fastq_1"], lane["fastq_2"]], stdout=f"lane{number}.sam")
        with (task / f"lane{number}.sam").open() as source, (task / f"lane{number}.oq.sam").open("w") as target:
            for line in source:
                if line.startswith("@"):
                    target.write(line)
                else:
                    fields = line.rstrip("\n").split("\t")
                    target.write("\t".join([*fields, "OQ:Z:" + fields[10]]) + "\n")
        commands.run("samtools", ["sort", "-o", f"lane{number}.bam", f"lane{number}.oq.sam"])
        bams.append(f"lane{number}.bam")
    commands.run("samtools", ["merge", "-f", "shared.bam", *bams])
    commands.run("samtools", ["index", "shared.bam"])
    (task / "regions.bed").write_text("chrSYN1\t0\t12000\nchrSYN2\t0\t8000\n")
    gatk_args = ["--java-options", "-Xmx4g", "HaplotypeCaller", "-R", "reference.fa", "-I", "shared.bam", "-L", "regions.bed", "-O", "gatk.vcf.gz", "--sample-name", "SYNTHETIC01", "--native-pair-hmm-threads", "2"]
    dv_args = ["--model_type=WES", "--ref=reference.fa", "--reads=shared.bam", "--regions=regions.bed", "--sample_name=SYNTHETIC01", "--num_shards=1", "--postprocess_cpus=0", "--make_examples_extra_args=use_original_quality_scores=true", "--output_vcf=deepvariant.vcf.gz", "--intermediate_results_dir=intermediate"]
    # Frozen oracle, fixture metadata and FASTQs remain outside caller staging.
    preparation_records = commands.records
    caller_records = []
    accepted = {}
    for caller, args in (("gatk", gatk_args), ("deepvariant", dv_args)):
        caller_task = directory / ('caller-' + caller)
        caller_task.mkdir()
        for name in ('reference.fa', 'reference.fa.fai', 'reference.dict', 'shared.bam', 'shared.bam.bai', 'regions.bed'):
            shutil.copyfile(task / name, caller_task / name)
        commands = Commands(runtime, caller_task, "runtime-qualification")
        commands.run(caller, args)
        require(commands.run("bcftools", ["query", "-l", f"{caller}.vcf.gz"]).strip() == "SYNTHETIC01", "runtime smoke sample mismatch")
        observed = {}
        with gzip.open(caller_task / f"{caller}.vcf.gz", "rt") as stream:
            for line in stream:
                if line.startswith("#"):
                    continue
                fields = line.split("\t"); index = fields[8].split(":").index("GT")
                observed[(fields[0], int(fields[1]), fields[3], fields[4])] = fields[9].split(":")[index].strip().replace("|", "/")
        for site in fixture["variant_sites"]:
            key = (site["contig"], site["position_1based"], site["ref"], site["alt"])
            require(observed.get(key) == site["genotype"], f"{caller} runtime positive SNV gate failed")
        caller_records.extend(commands.records)
        accepted[caller] = {"native_vcf": file_id(caller_task / f"{caller}.vcf.gz"), "positive_sites_accepted": len(fixture["variant_sites"])}
    result = {"kind": "runtime", "status": "passed", "scope": "invented_positive_SNV_runtime_only", "canonical_data_executed": False,
              "fixture_recipe": fixture["recipe_version"], "caller_acceptance": accepted, "tool_versions": versions, "commands": preparation_records + caller_records}
    executions = {tool: next(r for r in reversed(caller_records) if r["tool"] == tool) for tool in ("gatk", "deepvariant")}
    runtime.qualify(executions, lambda: {"accepted": True, "caller_acceptance": accepted, "fixture_recipe": fixture["recipe_version"]})
    write_json(directory / "runtime-qualified.json", result)
    return result


def check_versions(runtime: Any, task: Path) -> dict[str, Any]:
    """Require observed versions from every downstream tool before positive probes."""
    specs = {'samtools': (['--version'], r'samtools (1\.24)(?:\s|$)'),
             'gatk': (['--version'], r'(?:GATK\)?\s+v?)(4\.7\.0\.0)(?:\s|$)'),
             'deepvariant': (['--version'], r'(?:DeepVariant version|DeepVariant|version)\s*:?\s*(1\.10\.0)(?:\s|$)'),
             'bcftools': (['--version'], r'bcftools (1\.24)(?:\s|$)'),
             'rtg': (['version'], r'RTG Tools (3\.13)(?:\s|$)')}
    records = {}
    for tool, (args, pattern) in specs.items():
        record = runtime.run(tool, args, task_dir=task, stage='runtime-probe', timeout_seconds=180)
        text = Path(record['stdout_path']).read_text() + '\n' + Path(record['stderr_path']).read_text()
        require(re.search(pattern, text, re.I) is not None, f'{tool} executable version differs from its immutable pin')
        records[tool] = record
    return records


def qualify(runtime: Any, directory: Path) -> dict[str, Any]:
    """Try PRoot P2 once after a P1 execution failure; never relax biological gates."""
    try:
        return _qualify_once(runtime, directory)
    except RuntimeError:
        if runtime.backend != 'udocker' or runtime.udocker_mode != 'P1':
            raise
        runtime.udocker_mode = 'P2'
        runtime.environment['UDOCKER_DEFAULT_EXECUTION_MODE'] = 'P2'
        runtime.state['udocker_mode'] = 'P2'
        runtime.state['status'] = 'configured_only'
        runtime.write_state()
        result = _qualify_once(runtime, directory.with_name(directory.name + '-proot-p2'))
        result['fallback'] = 'P1 execution failed; fresh P2 staging passed the same acceptance gate'
        return result
