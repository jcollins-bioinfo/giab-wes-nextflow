#!/usr/bin/env python3
"""Read revision-pinned Batch job definitions and emit a hashable qualification receipt."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from giab_wes_nextflow.aws_support import REGION, client, make_session, require_role, sha256, verify_batch_definitions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile')
    parser.add_argument('--region', default=REGION)
    parser.add_argument('--definitions', type=Path, required=True)
    parser.add_argument('--job-role', required=True)
    parser.add_argument('--benchmark-role', required=True)
    parser.add_argument('--support-image', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.region != REGION:
            raise ValueError('Initial cloud implementation is scoped to us-west-2')
        definitions = json.loads(args.definitions.read_text())
        session = make_session(args.profile, args.region)
        identity = require_role(client(session, 'sts').get_caller_identity())
        for role in (args.job_role, args.benchmark_role):
            if not role.startswith(f"arn:aws:iam::{identity['Account']}:role/"):
                raise ValueError('Both job roles must belong to the authenticated account')
        report = verify_batch_definitions(client(session, 'batch'), definitions,
                                          args.job_role, args.benchmark_role, args.support_image)
        report['identity'] = {key: identity[key] for key in ('Account', 'Arn', 'UserId')}
        payload = (json.dumps(report, sort_keys=True, indent=2, default=str) + '\n').encode()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(payload)
        print(json.dumps({'receipt': str(args.output), 'sha256': sha256(payload), 'status': 'verified'}))
        return 0
    except Exception as exc:
        print(f'Batch qualification failed: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
