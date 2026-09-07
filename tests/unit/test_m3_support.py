"""Complete nonhuman contract fixtures for unit validation and publication tests.

BAM/BAI identities in this unit helper are explicit small stand-ins; they do not
claim container execution. Real binary/index validation belongs to the separate
Docker integration runner. No mocks bypass schema or semantic bundle validation.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from giab_wes_nextflow.m3 import preflight, read_pairs, validate_fastq, write_envelope
from giab_wes_nextflow.m3_collect import collect
from giab_wes_nextflow.m3_fixture import generate_fixture, reverse_complement
from giab_wes_nextflow.resources import config_path


def make_unit_bundle(root: Path, repository_sha: str = "a" * 40,
                     run_id: str = "m3-unit-contract") -> Path:
    """Produce all six validated synthetic result objects in a temporary root."""
    fixture = root / "fixture"
    expected = generate_fixture(fixture)
    reference = fixture / "reference.fa"
    fai = fixture / "reference.fa.fai"
    dictionary = fixture / "reference.dict"
    offset = 0
    fai_rows = []
    dict_rows = ["@HD\tVN:1.6"]
    for name, length in expected["contigs"].items():
        offset += len(f">{name}\n".encode())
        fai_rows.append(f"{name}\t{length}\t{offset}\t60\t61")
        offset += length + (length + 59) // 60
        dict_rows.append(f"@SQ\tSN:{name}\tLN:{length}")
    fai.write_text("\n".join(fai_rows) + "\n")
    dictionary.write_text("\n".join(dict_rows) + "\n")
    preflight_path = root / "m3-preflight.json"
    write_envelope(preflight_path, preflight(fixture / "samplesheet.csv", reference, fixture / "known-sites.vcf",
                   fixture / "fixture-expectations.json", repository_sha, run_id))
    lane_files = []
    originals = {}
    for lane in expected["lanes"]:
        fastq1, fastq2 = (fixture / lane[key] for key in ("fastq_1", "fastq_2"))
        output = root / f"{lane['lane']}.fastq-validation.json"
        record = validate_fastq(fastq1, fastq2, lane["sample"], lane["library"], lane["lane"], lane["read_group_id"],
                                lane["platform_unit"], lane["platform"], reference, fixture / "fixture-expectations.json",
                                fai, dictionary, run_id)
        write_envelope(output, record)
        lane_files.append(str(output))
        for qname, seq1, qual1, seq2, qual2 in read_pairs(fastq1, fastq2):
            originals[f"{qname}/1"] = (seq1, qual1)
            originals[f"{qname}/2"] = (seq2, qual2)
    headers = ["@HD\tVN:1.6\tSO:coordinate"] + dict_rows[1:]
    headers += [f"@RG\tID:{lane['read_group_id']}\tSM:{lane['sample']}\tLB:{lane['library']}\tPU:{lane['platform_unit']}\tPL:ILLUMINA" for lane in expected["lanes"]]
    order = {name: number for number, name in enumerate(expected["contigs"])}
    keys = sorted(expected["read_expectations"], key=lambda key: (
        order.get(expected["read_expectations"][key]["contig"], len(order)),
        expected["read_expectations"][key]["position_1based"] or 0, key))
    before, after = list(headers), list(headers)
    for key in keys:
        item = expected["read_expectations"][key]
        mapped = item["contig"] is not None
        flag = (99 if item["mate"] == 1 else 147) if mapped else (77 if item["mate"] == 1 else 141)
        if item["duplicate_group"] and item["qname"] != "SYN_L001_0001":
            flag += 1024
        seq, qual = originals[key]
        if item["reverse"]:
            seq, qual = reverse_complement(seq), qual[::-1]
        mate_key = f"{item['qname']}/{3 - item['mate']}"
        mate = expected["read_expectations"][mate_key]
        fields = [item["qname"], str(flag), item["contig"] or "*", str(item["position_1based"] or 0),
                  "60" if mapped else "0", "150M" if mapped else "*", "=" if mapped else "*",
                  str(mate["position_1based"] or 0), "0", seq, qual, f"RG:Z:{item['read_group']}"]
        before.append("\t".join(fields))
        changed = chr(max(33, ord(qual[0]) - 1)) + qual[1:]
        fields[10] = changed
        fields.append(f"OQ:Z:{qual}")
        after.append("\t".join(fields))
    before_path, after_path = root / "pre-bqsr.sam", root / "final.sam"
    before_path.write_text("\n".join(before) + "\n")
    after_path.write_text("\n".join(after) + "\n")
    stage_names = ["aligned_SYN_L001", "aligned_SYN_L002", "sorted_SYN_L001", "sorted_SYN_L002",
                   "merged", "duplicate_marked", "recalibration_table", "analysis_ready"]
    stages = []
    for name in stage_names:
        path = root / f"{name}.unit-identity"
        path.write_text("#:GATKReport.unit-fixture\n" if name == "recalibration_table" else f"unit-contract-stand-in:{name}\n")
        stages.append(f"{name}={path}")
    bam = root / "analysis_ready.unit-identity"
    bai = root / "analysis_ready.unit-index"
    bai.write_text("unit-contract-index-identity\n")
    flagstat = root / "flagstat.json"
    flagstat.write_text(json.dumps({"QC-passed reads": {"total": 48, "primary": 48, "mapped": 44, "duplicates": 4}}))
    idxstats = root / "idxstats.tsv"
    mapped_counts = {name: sum(item["contig"] == name for item in expected["read_expectations"].values()) for name in expected["contigs"]}
    idxstats.write_text("".join(f"{name}\t{length}\t{mapped_counts[name]}\t0\n" for name, length in expected["contigs"].items()) + "*\t0\t0\t4\n")
    stats = root / "samtools.stats.txt"
    stats.write_text("SN\traw total sequences:\t48\n")
    duplicate_metrics = root / "duplicates.txt"
    duplicate_metrics.write_text("LIBRARY\tUNPAIRED_READ_DUPLICATES\tREAD_PAIR_DUPLICATES\nSYN_LIB\t0\t2\n\n")
    coverage = root / "mosdepth.summary.txt"
    coverage.write_text("chrom\tlength\tbases\tmean\tmin\tmax\ntotal\t20000\t6000\t0.30\t0\t2\n")
    tool_contracts = json.loads(config_path("m3-tools.json").read_text())["tools"]
    versions = []
    for name, data in tool_contracts.items():
        path = root / f"{name}.version.txt"
        path.write_text(f"{name} {data['version']}\n")
        versions.append(f"{name}={path}")
    resources = root / "resources.json"
    resources.write_text(json.dumps({"task_id": "unit-task", "process": "unit-contract-fixture",
                         "requested_cpus": 1, "requested_memory_bytes": 1024 ** 3, "requested_time_seconds": 3600,
                         "container": None, "architecture": "synthetic-unit-contract"}))
    output = root / "contracts"
    collect(preflight_path, after_path, before_path, bam, bai, flagstat, idxstats, stats, duplicate_metrics,
            coverage, fixture / "fixture-expectations.json", output, stages, lane_files, [], versions, [], [], [str(resources)])
    return output
