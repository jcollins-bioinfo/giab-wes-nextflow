"""Small invented metadata fixtures; binary identities are explicit unit stand-ins.

This helper does not qualify BAM, VCF indexes or inference execution. The Docker
integration driver independently proves these properties using actual tools.
No mocks bypass the production schema or semantic bundle validator here.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

from giab_wes_nextflow.m4_contracts import MODEL_FILES, bundle_results, collect_caller, prepare_inputs
from giab_wes_nextflow.resources import config_path
from test_m3_support import make_unit_bundle as preprocessing_bundle


def make_unit_bundle(root: Path, repository_sha: str = "a" * 40,
                     run_id: str = "m4-unit-contract", *, callers: tuple[str, ...] = ("gatk", "deepvariant")) -> Path:
    """Collect valid synthetic metadata using explicit non-executable unit evidence."""
    upstream = root / "preprocessing"
    accepted = preprocessing_bundle(upstream, repository_sha, run_id, fixture_id="m4-snv-positive")
    inputs = root / "caller-inputs"
    prepare_inputs(accepted, upstream / "analysis_ready.unit-identity", upstream / "analysis_ready.unit-index",
                   upstream / "fixture", inputs)
    tools = json.loads(config_path("m4-tools.json").read_text())["tools"]
    paths = []
    for caller in callers:
        directory = root / caller
        directory.mkdir()
        tool = tools[caller]
        text = ("##fileformat=VCFv4.2\n##contig=<ID=chrSYN1,length=12000>\n"
                "##contig=<ID=chrSYN2,length=8000>\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSYNTHETIC01\n"
                "chrSYN1\t3151\t.\tT\tA\t99\tPASS\t.\tGT\t0/1\n"
                "chrSYN2\t7101\t.\tT\tA\t99\tPASS\t.\tGT\t1/1\n")
        vcf = directory / f"SYNTHETIC01.{caller}.native.vcf.gz"
        vcf.write_bytes(gzip.compress(text.encode(), mtime=0))
        index = Path(str(vcf) + ".tbi")
        index.write_bytes(b"unit-only-index-identity")
        version = directory / "version.txt"
        version.write_text(f"{caller} {tool['expected_reported_version']}\n")
        command = directory / "command.sh"
        command.write_text("gatk HaplotypeCaller --reference caller-inputs/reference.fa --input caller-inputs/shared.bam --intervals caller-inputs/regions.bed --interval-padding 0 --create-output-variant-index true --output SYNTHETIC01.gatk.native.vcf.gz --native-pair-hmm-threads 2 --standard-min-confidence-threshold-for-calling 30.0 --emit-ref-confidence NONE\n" if caller == "gatk" else
                           "/opt/deepvariant/bin/run_deepvariant --ref=caller-inputs/reference.fa --reads=caller-inputs/shared.bam --regions=caller-inputs/regions.bed --sample_name=SYNTHETIC01 --output_vcf=SYNTHETIC01.deepvariant.native.vcf.gz --output_gvcf=SYNTHETIC01.deepvariant.native.g.vcf.gz --intermediate_results_dir=deepvariant.intermediate --logging_dir=deepvariant.logs --model_type=WES --num_shards=1 --postprocess_cpus=0 --make_examples_extra_args=use_original_quality_scores=true\n")
        resources = directory / "resources.json"
        resources.write_text(json.dumps({"task_id": None, "logical_artifact_id": f"m4_{caller}",
            "process": "M4_HAPLOTYPECALLER" if caller == "gatk" else "M4_DEEPVARIANT",
            "requested_cpus": 2, "requested_memory_bytes": 8 * 1024 ** 3,
            "requested_time_seconds": 3600, "container": tool["image"], "architecture": "x86_64"}))
        extras: dict[str, Any] = {}
        if caller == "deepvariant":
            gvcf = directory / "SYNTHETIC01.deepvariant.native.g.vcf.gz"
            gvcf.write_bytes(vcf.read_bytes())
            gindex = Path(str(gvcf) + ".tbi")
            gindex.write_bytes(index.read_bytes())
            model_files = [{"filename": name, "bytes": 1, "sha256": hashlib.sha256(name.encode()).hexdigest()} for name in sorted(MODEL_FILES)]
            metadata = next(item for item in model_files if item["filename"] == "model.example_info.json")
            metadata.update(bytes=tool["model"]["example_info_bytes"], sha256=tool["model"]["example_info_sha256"])
            before = directory / "model-before.json"
            model = {"schema_version": "1.0.0", "kind": "m4_deepvariant_model_inventory", "model_type": "WES", "model_files": model_files}
            before.write_text(json.dumps(model))
            inference = directory / "inference.json"
            observed = {**model, "kind": "m4_deepvariant_inference", "example_record_count": 2,
                "call_variants_record_count": 2, "all_probabilities_valid": True, "probability_tolerance": 1e-5,
                "variant_contigs": ["chrSYN1", "chrSYN2"],
                "example_files": [{"filename": "unit.examples.gz", "bytes": 1, "sha256": "1" * 64}],
                "call_variants_files": [{"filename": "unit.inference.gz", "bytes": 1, "sha256": "2" * 64}]}
            inference.write_text(json.dumps(observed))
            extras = {"gvcf": gvcf, "gvcf_index": gindex, "inference": inference, "model_before": before}
        output = directory / f"m4-{caller}.json"
        collect_caller(caller, inputs, vcf, index, version, command, resources, output, **extras)
        paths.append(output)
    output_dir = root / "contracts"
    bundle_results(inputs, paths, output_dir)
    return output_dir
