#!/usr/bin/env python3
"""Submit one bounded nonhuman run only after exact image and run-group checks."""
import argparse
from deployment_settings import ACCOUNT, REGISTRY, BUCKET, ROLE_PREFIX, EXECUTION_ROLE
import hashlib
import json
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from giab_wes_nextflow.aws_support import make_session, client, require_role


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work',type=Path,required=True)
    args=parser.parse_args()
    root=args.work.resolve()
    session=make_session('giab-operator')
    identity=require_role(client(session,'sts').get_caller_identity())
    if not identity['Arn'].startswith(ROLE_PREFIX):
        raise ValueError('Exact project operator required')
    omics,ecr,s3=(client(session,name) for name in ('omics','ecr','s3'))
    registration=json.loads((root/'managed-native-registration.json').read_text())
    workflow_id=json.loads((root/'managed-native-workflow.json').read_text())['id']
    group_id=json.loads((root/'live-omics-qualification/group.json').read_text())['id']
    package_hash=hashlib.sha256((root/'managed-native.zip').read_bytes()).hexdigest()
    if package_hash != registration['tags']['PackageSHA256']:
        raise ValueError('Qualification package changed')
    group=omics.get_run_group(id=group_id)
    if (group['maxCpus'],group['maxRuns'],group['maxDuration']) != (4,1,60):
        raise ValueError('Qualification scheduling bounds differ')
    workflow=omics.get_workflow(id=workflow_id,type='PRIVATE')
    if workflow['status']!='ACTIVE' or workflow['tags']['PackageSHA256']!=package_hash:
        raise ValueError('Active workflow identity differs')
    support=(root/'support-amd64-image.txt').read_text().strip()
    workflow_source=(Path(__file__).resolve().parents[1]/'qualification/managed-native.nf').read_text()
    images=sorted(set(REGISTRY+'/'+name+'@sha256:'+digest for name,digest in re.findall(r'/([a-z]+)@sha256:([0-9a-f]{64})',workflow_source))|{support})
    remaining=images[:]
    deadline=time.monotonic()+1800
    while remaining:
        for image in remaining[:]:
            name,digest=image.split('.amazonaws.com/')[1].split('@')
            try:
                ecr.describe_images(repositoryName=name,imageIds=[{'imageDigest':digest}])
            except ecr.exceptions.ImageNotFoundException:
                continue
            remaining.remove(image)
            print('Verified runtime image: '+name,flush=True)
        if remaining:
            if time.monotonic()>=deadline:
                raise TimeoutError('Image transfer not ready; no paid run submitted')
            time.sleep(30)
    bucket=BUCKET
    seed=b'giab-managed-nonhuman-qualification-v1\n'
    key='source/qualification/nonhuman-v1.txt'
    s3.put_object(Bucket=bucket,Key=key,Body=seed,ExpectedBucketOwner=ACCOUNT)
    with s3.get_object(Bucket=bucket,Key=key,ExpectedBucketOwner=ACCOUNT)['Body'] as stream:
        if stream.read()!=seed: raise ValueError('S3 seed staging differs')
    request={'workflowId':workflow_id,'workflowType':'PRIVATE',
             'roleArn':EXECUTION_ROLE,
             'name':'giab-native-'+package_hash[:12],'runGroupId':group_id,
             'parameters':{'support_image':support,'ecr_prefix':REGISTRY,'seed':'s3://'+bucket+'/'+key},
             'outputUri':'s3://'+bucket+'/results/qualification/'+package_hash+'/',
             'storageType':'DYNAMIC','retentionMode':'RETAIN','logLevel':'ALL',
             'engineSettings':{'engineVersion':'26.04.0','syntaxVersion':'v2'},
             'tags':{'Project':'giab-wes-nextflow','Environment':'demo','ExecutionKind':'nonhuman-qualification'},
             'requestId':hashlib.sha256((package_hash+support+group_id).encode()).hexdigest()}
    (root/'native-start-request.json').write_text(json.dumps(request,indent=2)+'\n')
    response=omics.start_run(**request)
    (root/'native-run.json').write_text(json.dumps(response,default=str,indent=2)+'\n')
    print(json.dumps(response,default=str),flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
