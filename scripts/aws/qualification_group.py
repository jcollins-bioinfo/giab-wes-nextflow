#!/usr/bin/env python3
"""Terraform provisioner for the run group absent from hashicorp/aws 6.64.0."""
import json
import argparse
from deployment_settings import ACCOUNT, REGISTRY, BUCKET, ROLE_PREFIX, EXECUTION_ROLE
from pathlib import Path
import sys
import boto3


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('receipt', type=Path)
    parser.add_argument('--purpose', choices=['native', 'assets'], default='native')
    args = parser.parse_args()
    session = boto3.Session(profile_name='giab-operator', region_name='us-west-2')
    identity = session.client('sts').get_caller_identity()
    if not identity['Arn'].startswith(ROLE_PREFIX):
        raise ValueError('Exact project operator required')
    omics = session.client('omics')
    duration = 60 if args.purpose == 'native' else 480
    request = {'name': 'giab-wes-demo-' + args.purpose + '-qualification', 'maxCpus': 4,
               'maxRuns': 1, 'maxDuration': duration,
               'tags': {'Project': 'giab-wes-nextflow', 'Environment': 'demo', 'ManagedBy': 'Terraform'},
               'requestId': 'giab-' + args.purpose + '-qualification-4-1-' + str(duration) + '-v1'}
    groups = [g for page in omics.get_paginator('list_run_groups').paginate()
              for g in page['items'] if g['name'] == request['name']]
    if len(groups) > 1:
        raise ValueError('Ambiguous existing run groups')
    response = groups[0] if groups else omics.create_run_group(**request)
    group = omics.get_run_group(id=response['id'])
    if any(group[k] != request[k] for k in ['name', 'maxCpus', 'maxRuns', 'maxDuration', 'tags']):
        raise ValueError('Run group readback differs from reviewed configuration')
    args.receipt.write_text(json.dumps(group, default=str, indent=2) + '\n')
    print('Verified bounded qualification run group: ' + group['id'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
