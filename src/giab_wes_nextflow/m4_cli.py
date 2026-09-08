"""Command-line boundaries for isolated synthetic native caller evidence."""
from __future__ import annotations

import argparse
import json

from .m4_contracts import bundle_results, collect_caller, prepare_inputs, validate_m4_result_bundle


def main(argv: list[str] | None = None) -> int:
    """Dispatch validated input isolation, native acceptance and bundle verification."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    prepare = subparsers.add_parser("prepare-inputs")
    for name in ("bundle", "bam", "bai", "reference-bundle", "output-dir"):
        prepare.add_argument(f"--{name}", required=True)
    collect = subparsers.add_parser("collect-caller")
    collect.add_argument("--caller", required=True, choices=("gatk", "deepvariant"))
    for name in ("inputs", "vcf", "vcf-index", "version-file", "command-file", "resources", "output"):
        collect.add_argument(f"--{name}", required=True)
    for name in ("gvcf", "gvcf-index", "inference", "model-before"):
        collect.add_argument(f"--{name}")
    bundle = subparsers.add_parser("bundle")
    bundle.add_argument("--inputs", required=True)
    bundle.add_argument("--caller-result", action="append", required=True)
    bundle.add_argument("--output-dir", required=True)
    validate = subparsers.add_parser("validate-bundle")
    validate.add_argument("--bundle", required=True)
    args = parser.parse_args(argv)
    if args.action == "prepare-inputs":
        prepare_inputs(args.bundle, args.bam, args.bai, args.reference_bundle, args.output_dir)
    elif args.action == "collect-caller":
        collect_caller(args.caller, args.inputs, args.vcf, args.vcf_index, args.version_file,
                       args.command_file, args.resources, args.output, gvcf=args.gvcf,
                       gvcf_index=args.gvcf_index, inference=args.inference, model_before=args.model_before)
    elif args.action == "bundle":
        bundle_results(args.inputs, args.caller_result, args.output_dir)
    else:
        result = validate_m4_result_bundle(args.bundle)
        print(json.dumps({"valid": True, "run_id": result["bundle"]["run_id"],
                          "selected_callers": result["bundle"]["data"]["selected_callers"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
