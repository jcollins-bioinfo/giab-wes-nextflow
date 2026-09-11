#!/usr/bin/env python3
"""Use the official public GIAB S3 mirror only when pinned source MD5 agrees."""
import argparse
from deployment_settings import ACCOUNT, REGISTRY, BUCKET, ROLE_PREFIX, EXECUTION_ROLE
import json
from pathlib import Path
import sys
from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from giab_wes_nextflow.acquisition import load_manifest, now
from giab_wes_nextflow.aws_support import make_session, client, require_role
from acquire_sources import BUCKET, remote_identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipts', type=Path, required=True)
    parser.add_argument('--only', action='append', help='Mirror only an exact declared source id')
    args = parser.parse_args()
    args.receipts.mkdir(parents=True, exist_ok=True)
    session = make_session('giab-operator')
    identity = require_role(client(session, 'sts').get_caller_identity())
    if not identity['Arn'].startswith(ROLE_PREFIX):
        raise ValueError('Exact project operator required')
    s3 = client(session, 's3')
    public = session.client('s3', region_name='us-east-1', config=Config(signature_version=UNSIGNED))
    resources = [r for r in load_manifest()['resources'] if '/ReferenceSamples/giab/' in r['url']]
    if args.only:
        if not set(args.only) <= {r['id'] for r in resources}:
            raise ValueError('Unknown mirror source selection')
        resources = [r for r in resources if r['id'] in args.only]
    resources.sort(key=lambda r: (not r['id'].startswith('grch38'), r.get('role','').startswith('raw_read'),r['id']))
    for resource in resources:
        path = args.receipts / (resource['id'] + '.json')
        if path.exists():
            receipt=json.loads(path.read_text())
            observed=remote_identity(s3,receipt['key'])
            if observed != receipt['destination'] or observed['md5'] != resource['checksum']['expected']:
                raise ValueError('Existing source receipt differs')
            continue
        source_key=resource['url'].split('/ReferenceSamples/giab/',1)[1]
        try:
            head=public.head_object(Bucket='giab',Key=source_key)
        except ClientError as error:
            if error.response['Error']['Code'] in ('404','NoSuchKey'):
                print(resource['id']+': not in mirror; original-source acquisition remains required',flush=True)
                continue
            raise
        if head['ContentLength'] > 3 * 1024**3:
            raise ValueError('Mirror object exceeds bounded source size')
        staging='source/mirror-staging/'+resource['checksum']['expected']+'/'+resource['filename']
        print(resource['id']+': server-side copy and complete byte authentication',flush=True)
        s3.copy_object(Bucket=BUCKET,Key=staging,CopySource={'Bucket':'giab','Key':source_key},
                       CopySourceIfMatch=head['ETag'],ExpectedBucketOwner=ACCOUNT)
        copied=remote_identity(s3,staging)
        if copied['md5'] != resource['checksum']['expected'] or copied['bytes'] != head['ContentLength']:
            raise ValueError('Official mirror does not match pinned NCBI bytes: '+resource['id'])
        key='source/sha256/'+copied['sha256']+'/'+resource['filename']
        s3.copy_object(Bucket=BUCKET,Key=key,
                       CopySource={'Bucket':BUCKET,'Key':staging,'VersionId':copied['version_id']},
                       ExpectedBucketOwner=ACCOUNT,MetadataDirective='REPLACE',
                       Metadata={'sha256':copied['sha256'],'source-id':resource['id']})
        observed=remote_identity(s3,key)
        if any(observed[k] != copied[k] for k in ('md5','sha256','bytes')):
            raise ValueError('Final destination bytes differ')
        source={'id':resource['id'],'status':'verified','source_url':resource['url'],
                'effective_url':'https://giab.s3.us-east-1.amazonaws.com/'+source_key,
                'destination':resource['destination'],'bytes':observed['bytes'],
                'checksum':{'algorithm':'md5','expected':resource['checksum']['expected'],'observed':observed['md5']},
                'sha256':observed['sha256'],'verified_utc':now(),
                'method':'official S3 mirror, full pinned-MD5 authentication and final destination rehash'}
        receipt={'status':'source_bytes_verified','observed_at':now(),'source':source,'bucket':BUCKET,
                 'key':key,'destination':observed,'canonical_result':False,
                 'mirror_staging':{'key':staging,'version_id':copied['version_id']}}
        payload=(json.dumps(receipt,sort_keys=True,indent=2)+'\n').encode()
        s3.put_object(Bucket=BUCKET,Key=key+'.complete.json',Body=payload,ContentType='application/json',ExpectedBucketOwner=ACCOUNT)
        pending=path.with_suffix('.pending');pending.write_bytes(payload);pending.replace(path)
        print(resource['id']+': authenticated and committed',flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
