#!/usr/bin/env python3
"""Read-only inspection; root causes an immediate stop after GetCallerIdentity."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from giab_wes_nextflow.aws_support import REGION, make_session, preflight


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile")
    parser.add_argument("--backend", choices=("all", "awsbatch", "healthomics"), default="all")
    parser.add_argument("--region", default=REGION)
    parser.add_argument("--desired-vcpus", type=int, default=32)
    parser.add_argument("--project-prefix", default="giab-wes")
    parser.add_argument("--json", type=Path, help="Save machine-readable evidence (stdout also receives JSON)")
    args = parser.parse_args()
    if args.desired_vcpus < 1:
        parser.error("--desired-vcpus must be positive")
    try:
        report = preflight(make_session(args.profile, args.region), args.desired_vcpus, args.project_prefix, args.backend)
    except Exception as exc:  # CLI boundary: never convert denied calls into empty state.
        print(f"Preflight failed: {exc}", file=sys.stderr)
        return 1
    output = json.dumps(report, indent=2, default=str) + "\n"
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(output)
    print(output, end="")
    print(f"Region: {report['region']}; root: {report['is_root']}; safe_to_deploy: false", file=sys.stderr)
    for blocker in report["blockers"]:
        print(f"BLOCKED: {blocker}", file=sys.stderr)
    return 2 if report["blockers"] else 0


if __name__ == "__main__":
    sys.exit(main())
