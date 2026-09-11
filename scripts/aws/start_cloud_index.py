#!/usr/bin/env python3
"""Start the bounded complete-reference index only after authenticated staging."""
import argparse
from deployment_settings import ACCOUNT, REGISTRY, BUCKET, ROLE_PREFIX, EXECUTION_ROLE
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from giab_wes_nextflow.acquisition import load_manifest
from giab_wes_nextflow.aws_support import make_session, client, require_role


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--receipts',type=Path,required=True)
    args=parser.parse_args();root=args.work.resolve()
    session=make_session('giab-operator')
    identity=require_role(client(session,'sts').get_caller_identity())
    if not identity['Arn'].startswith(ROLE_PREFIX):
        raise ValueError('Exact project operator required')
    omics,s3,ecr=(client(session,name) for name in ('omics','s3','ecr'))
    spec={r['id']:r for r in load_manifest()['resources']}
    required={'reference_source':'grch38_no_alt_fasta_gz','reference_fai':'grch38_compressed_fai'}
    deadline=time.monotonic()+3600
    while not all((args.receipts/(r+'.json')).exists() for r in required.values()):
        if time.monotonic()>=deadline: raise TimeoutError('Reference not ready; no index run started')
        time.sleep(30)
    parameters={}
    for parameter,resource_id in required.items():
        receipt=json.loads((args.receipts/(resource_id+'.json')).read_text())
        observed=receipt['destination']; source=receipt['source']
        if (receipt['status']!='source_bytes_verified' or observed['md5']!=spec[resource_id]['checksum']['expected']
                or observed['sha256']!=source['sha256'] or observed['bytes']!=source['bytes']
                or receipt['bucket']!=BUCKET
                or not receipt['key'].startswith('source/sha256/'+observed['sha256']+'/')):
            raise ValueError('Reference source receipt identity differs')
        # The support task independently authenticates the whole staged gzip by its pinned MD5.
        head=s3.head_object(Bucket=receipt['bucket'],Key=receipt['key'],ExpectedBucketOwner=ACCOUNT)
        if head['VersionId']!=observed['version_id'] or head['ContentLength']!=observed['bytes']:
            raise ValueError('Source object changed after destination rehash')
        parameters[parameter]='s3://'+receipt['bucket']+'/'+receipt['key']
    support=(root/'support-amd64-image.txt').read_text().strip()
    for image in [support,f'{REGISTRY}/bwa@sha256:c3a708bea7947a44288e675fd9791c7aaf0c97dba0710addba336ed193821f8a']:
        name,digest=image.split('.amazonaws.com/')[1].split('@')
        ecr.describe_images(repositoryName=name,imageIds=[{'imageDigest':digest}])
    parameters['support_image']=support
    parameters['ecr_prefix']=REGISTRY
    workflow_id=json.loads((root/'cloud-index-workflow.json').read_text())['id']
    group_id=json.loads((root/'live-omics-qualification/group-assets.json').read_text())['id']
    workflow=omics.get_workflow(id=workflow_id,type='PRIVATE')
    digest=hashlib.sha256((root/'cloud-index.zip').read_bytes()).hexdigest()
    if workflow['status']!='ACTIVE' or workflow['tags']['PackageSHA256']!=digest:
        raise ValueError('Active index workflow identity differs')
    group=omics.get_run_group(id=group_id)
    if (group['maxCpus'],group['maxRuns'],group['maxDuration'])!=(4,1,480):
        raise ValueError('Index scheduling bounds differ')
    request={'workflowId':workflow_id,'workflowType':'PRIVATE',
             'roleArn':EXECUTION_ROLE,
             'name':'giab-full-index-'+digest[:12],'runGroupId':group_id,'parameters':parameters,
             'outputUri':'s3://'+BUCKET+'/results/assets/'+digest+'/',
             'storageType':'DYNAMIC','retentionMode':'RETAIN','logLevel':'ALL',
             'engineSettings':{'engineVersion':'26.04.0','syntaxVersion':'v2'},
             'tags':{'Project':'giab-wes-nextflow','Environment':'demo','ExecutionKind':'full-reference-index'},
             'requestId':hashlib.sha256((digest+json.dumps(parameters,sort_keys=True)).encode()).hexdigest()}
    (root/'index-start-request.json').write_text(json.dumps(request,indent=2)+'\n')
    response=omics.start_run(**request)
    (root/'index-run.json').write_text(json.dumps(response,default=str,indent=2)+'\n')
    print(json.dumps(response,default=str),flush=True)
    return 0


if __name__=='__main__':
    sys.exit(main())
