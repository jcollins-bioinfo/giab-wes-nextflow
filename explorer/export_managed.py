#!/usr/bin/env python3
"""Derive the public allowlisted managed snapshot from its pinned private receipts."""
import argparse
import json
from pathlib import Path
from pipeline_evidence_explorer.execution import project_managed_receipts

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--validation', required=True, type=Path)
parser.add_argument('--provider', required=True, type=Path)
parser.add_argument('--collector', required=True, type=Path)
parser.add_argument('--output', required=True, type=Path)
args = parser.parse_args()
record = project_managed_receipts(args.validation, args.provider, args.collector)
args.output.write_text(json.dumps(record, sort_keys=True, indent=2) + '\n')
