"""Installed CLI boundary for M3 synthetic source, alignment and result contracts."""
from __future__ import annotations

import argparse
from pathlib import Path

from .m3 import preflight, validate_fastq, write_envelope
from .m3_collect import collect, validate_result_bundle
from .m3_fixture import generate_fixture


def main(argv: list[str] | None = None) -> int:
    """Invoke package-owned checks; never admit canonical execution by a flag."""
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    fixture = sub.add_parser("generate-fixture")
    fixture.add_argument("--output", required=True)
    before = sub.add_parser("preflight")
    for name in ("samplesheet", "reference", "known-sites", "repository-sha", "run-id", "output"):
        before.add_argument(f"--{name}", required=True)
    before.add_argument("--expectations", "--fixture-manifest", dest="expectations", required=True)
    for name in ("reference-fai", "reference-dict", "known-sites-index"):
        before.add_argument(f"--{name}")
    fastq = sub.add_parser("validate-fastq")
    for name in ("fastq1", "fastq2", "sample", "library", "lane", "read-group", "platform-unit", "platform", "reference", "output"):
        fastq.add_argument(f"--{name}", required=True)
    fastq.add_argument("--fixture-manifest", "--expectations", dest="expectations", required=True)
    fastq.add_argument("--reference-fai")
    fastq.add_argument("--reference-dict")
    fastq.add_argument("--run-id", default="m3-synthetic")
    collector = sub.add_parser("collect")
    for name in ("preflight", "sam", "pre-bqsr-sam", "bam", "bai", "flagstat", "idxstats", "samtools-stats", "duplicate-metrics", "coverage-summary", "expectations", "output-dir"):
        collector.add_argument(f"--{name}", required=True)
    for name in ("stage", "lane-validation", "tool", "tool-version", "container", "artifact", "resource-record"):
        collector.add_argument(f"--{name}", action="append", default=[])
    validate = sub.add_parser("validate-bundle")
    validate.add_argument("path", nargs="?")
    validate.add_argument("--bundle")
    args = parser.parse_args(argv)
    if args.command == "generate-fixture":
        generate_fixture(args.output)
    elif args.command == "preflight":
        result = preflight(args.samplesheet, args.reference, args.known_sites, args.expectations, args.repository_sha,
                           args.run_id, args.reference_fai, args.reference_dict, args.known_sites_index)
        write_envelope(args.output, result)
    elif args.command == "validate-fastq":
        result = validate_fastq(args.fastq1, args.fastq2, args.sample, args.library, args.lane, args.read_group,
                               args.platform_unit, args.platform, args.reference, args.expectations,
                               args.reference_fai, args.reference_dict, args.run_id)
        write_envelope(args.output, result)
    elif args.command == "collect":
        collect(args.preflight, args.sam, args.pre_bqsr_sam, args.bam, args.bai, args.flagstat, args.idxstats,
                args.samtools_stats, args.duplicate_metrics, args.coverage_summary, args.expectations, args.output_dir,
                args.stage, args.lane_validation, args.tool, args.tool_version, args.container, args.artifact, args.resource_record)
    elif args.command == "validate-bundle":
        if bool(args.path) == bool(args.bundle):
            parser.error("validate-bundle requires exactly one path or --bundle")
        validate_result_bundle(args.bundle or args.path)
    print(f"M3 {args.command}: validated synthetic evidence; canonical execution remains blocked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
