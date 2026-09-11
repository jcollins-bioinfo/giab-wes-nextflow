#!/usr/bin/env python3
"""Resume supervision or cancel one private-journal-bound HealthOmics run."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from giab_wes_nextflow.aws_support import client, make_session, require_role
from giab_wes_nextflow.run_watchdog import (
    cancel_bound, load_policy, read_ledger, run_guarded, validate_request,
)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--policy", type=Path, required=True)
    p.add_argument("--ledger", type=Path, required=True)
    p.add_argument("--request-id", required=True)
    p.add_argument("--cancel", action="store_true", help="Cancel only this exact journal-bound run")
    args = p.parse_args()
    try:
        policy = load_policy(args.policy, for_cancel=args.cancel)
        record = read_ledger(args.ledger, policy)["runs"][args.request_id]
        session = make_session("giab-operator", policy["region"])
        identity = require_role(client(session, "sts").get_caller_identity())
        validate_request(policy, record["request"], record["reservation_key"], identity)
        omics = client(session, "omics")
        if args.cancel:
            result = cancel_bound(omics, record["request"], args.ledger, policy)
        else:
            result = run_guarded(omics=omics, request=record["request"], policy_path=args.policy,
                                 ledger_path=args.ledger, reservation_key=record["reservation_key"], identity=identity)
        print(json.dumps({"status": result["status"], "terminal_verified": True}))
        return 0 if result["status"] == "COMPLETED" or args.cancel else 2
    except Exception as exc:
        # Detailed private provider errors can contain resource identifiers.
        print("Run watchdog blocked/failed: " + type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
