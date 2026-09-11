"""Explicit account binding supplied privately by the deployment operator."""
import os
import re

ACCOUNT = os.environ.get('GIAB_AWS_ACCOUNT_ID', '')
if not re.fullmatch(r'[0-9]{12}', ACCOUNT):
    raise ValueError('Set GIAB_AWS_ACCOUNT_ID from the reviewed private deployment configuration')
REGISTRY = f'{ACCOUNT}.dkr.ecr.us-west-2.amazonaws.com/giab-wes-demo'
BUCKET = f'giab-wes-demo-{ACCOUNT}-us-west-2-data'
ROLE_PREFIX = f'arn:aws:sts::{ACCOUNT}:assumed-role/giab-operator/'
EXECUTION_ROLE = f'arn:aws:iam::{ACCOUNT}:role/giab-wes-demo-healthomics-execution'
