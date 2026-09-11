#!/usr/bin/env python3
"""Acquire approved sources one at a time; publish rehashed private S3 receipts."""
import argparse
from deployment_settings import ACCOUNT, REGISTRY, BUCKET, ROLE_PREFIX, EXECUTION_ROLE
import hashlib
import json
from pathlib import Path
import shutil
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from giab_wes_nextflow.acquisition import acquire, destination, load_manifest, now, safe_root
from giab_wes_nextflow.canonical_run import GTF
from giab_wes_nextflow.canonical_asset_reference import load_assets
from giab_wes_nextflow.aws_support import make_session, client, require_role
from boto3.s3.transfer import TransferConfig



def remote_identity(s3, key):
    md5, sha, size = hashlib.md5(), hashlib.sha256(), 0
    response = s3.get_object(Bucket=BUCKET, Key=key, ExpectedBucketOwner=ACCOUNT)
    with response['Body'] as stream:
        for block in iter(lambda: stream.read(8 << 20), b''):
            md5.update(block); sha.update(block); size += len(block)
    return {'md5': md5.hexdigest(), 'sha256': sha.hexdigest(), 'bytes': size,
            'version_id': response['VersionId']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scratch', type=Path, required=True)
    parser.add_argument('--receipts', type=Path, required=True)
    parser.add_argument('--profile', default='giab-operator')
    parser.add_argument('--only', action='append', help='Acquire only an exact declared source id')
    args = parser.parse_args()
    scratch = safe_root(args.scratch)
    scratch.mkdir(parents=True, exist_ok=True, mode=0o700)
    args.receipts.mkdir(parents=True, exist_ok=True)
    session = make_session(args.profile)
    identity = require_role(client(session, 'sts').get_caller_identity())
    if not identity['Arn'].startswith(ROLE_PREFIX):
        raise ValueError('Exact project operator required')
    s3 = client(session, 's3')
    resources = [r for r in load_manifest()['resources'] if r['id'] != 'ucsc_hg19_to_hg38_chain']
    resources += [GTF] + load_assets()['known_sites']
    if args.only:
        if not set(args.only) <= {r['id'] for r in resources}:
            raise ValueError('Unknown source selection')
        resources = [r for r in resources if r['id'] in args.only]
    resources.sort(key=lambda r: (r.get('role', '').startswith('raw_read'), r['id']))
    for resource in resources:
        receipt_path = args.receipts / (resource['id'] + '.json')
        if receipt_path.exists():
            receipt = json.loads(receipt_path.read_text())
            observed = remote_identity(s3, receipt['key'])
            if receipt['source']['checksum']['expected'] != resource['checksum']['expected'] or observed != receipt['destination']:
                raise ValueError('Existing immutable source receipt differs: ' + resource['id'])
            print(resource['id'] + ': verified existing S3 source', flush=True)
            continue
        with urllib.request.urlopen(urllib.request.Request(resource['url'], method='HEAD'), timeout=30) as response:
            size = int(response.headers['Content-Length'])
        if size > 3 * 1024**3 or shutil.disk_usage(scratch).free < size + 4 * 1024**3:
            raise ValueError('Source exceeds bounded single-file scratch admission: ' + resource['id'])
        print(resource['id'] + ': acquiring ' + str(size) + ' bytes', flush=True)
        source = acquire(resource, scratch)
        path = destination(scratch, resource['destination'])
        key = 'source/sha256/' + source['sha256'] + '/' + resource['filename']
        s3.upload_file(str(path), BUCKET, key, ExtraArgs={'ExpectedBucketOwner': ACCOUNT,
                       'Metadata': {'sha256': source['sha256'], 'source-id': resource['id']}},
                       Config=TransferConfig(max_concurrency=2, multipart_chunksize=16 << 20))
        observed = remote_identity(s3, key)
        if (observed['md5'], observed['sha256'], observed['bytes']) != (resource['checksum']['expected'], source['sha256'], source['bytes']):
            raise ValueError('Destination rehash differs: ' + resource['id'])
        receipt = {'status': 'source_bytes_verified', 'observed_at': now(), 'source': source,
                   'bucket': BUCKET, 'key': key, 'destination': observed, 'canonical_result': False}
        payload = (json.dumps(receipt, sort_keys=True, indent=2) + '\n').encode()
        # Commit completion markers only after origin authentication and destination rehash.
        s3.put_object(Bucket=BUCKET, Key=key + '.complete.json', Body=payload,
                      ExpectedBucketOwner=ACCOUNT, ContentType='application/json')
        pending = receipt_path.with_suffix('.pending')
        pending.write_bytes(payload); pending.replace(receipt_path)
        path.unlink()  # Only this task's scratch copy; authenticated durable version is retained.
        print(resource['id'] + ': private S3 destination rehashed and committed', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
