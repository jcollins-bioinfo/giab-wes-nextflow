#!/usr/bin/env python3
"""Checksum-gated, resumable acquisition for the private M2 workspace."""
import argparse, datetime, hashlib, json, os, shutil, subprocess, sys, urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def digest(path, algorithm):
 h=hashlib.new(algorithm)
 with Path(path).open('rb') as f:
  for block in iter(lambda:f.read(8*1024*1024),b''): h.update(block)
 return h.hexdigest()
def download(resource, root):
 dst=root/resource['path']; dst.parent.mkdir(parents=True,exist_ok=True)
 if dst.exists() and digest(dst,'md5')==resource['md5']: return dst,'verified-existing'
 if dst.exists(): dst.unlink()
 part=dst.with_suffix(dst.suffix+'.part')
 start=part.stat().st_size if part.exists() else 0
 request=urllib.request.Request(resource['url'],headers={'Range':f'bytes={start}-'} if start else {})
 try:
  with urllib.request.urlopen(request) as response, part.open('ab' if start and response.status==206 else 'wb') as out: shutil.copyfileobj(response,out,8*1024*1024)
 except Exception: raise
 if digest(part,'md5')!=resource['md5']:
  part.unlink(missing_ok=True); raise ValueError(f"MD5 mismatch: {resource['id']}")
 os.replace(part,dst); return dst,'downloaded'
def record(path,resource,status):
 return {'id':resource['id'],'role':resource['role'],'path':resource['path'],'source_url':resource['url'],'expected_md5':resource['md5'],'observed_md5':digest(path,'md5'),'sha256':digest(path,'sha256'),'bytes':path.stat().st_size,'status':status}
def main(argv=None):
 p=argparse.ArgumentParser(); p.add_argument('--workspace',required=True); p.add_argument('--manifest',default=ROOT/'config/m2-resources.json'); p.add_argument('--only',action='append'); p.add_argument('--skip-prepare',action='store_true'); a=p.parse_args(argv)
 root=Path(a.workspace).resolve(); root.mkdir(parents=True,exist_ok=True); spec=json.loads(Path(a.manifest).read_text()); selected=[r for r in spec['resources'] if not a.only or r['id'] in a.only]
 records=[]
 for r in selected:
  path,status=download(r,root); records.append(record(path,r,status)); print(f"{status}: {r['id']}")
 stamp=datetime.datetime.now(datetime.timezone.utc).isoformat(); provenance={'schema_version':'1.0.0','pipeline_version':'0.2.0-dev.1','created_utc':stamp,'manifest_sha256':digest(a.manifest,'sha256'),'dataset':spec['dataset'],'artifacts':records}
 out=root/'registry/m2-acquisition.json'; out.parent.mkdir(parents=True,exist_ok=True)
 if out.exists():
  previous=json.loads(out.read_text())
  if previous['manifest_sha256']!=provenance['manifest_sha256']: raise FileExistsError('immutable acquisition record conflicts with this manifest')
 else:
  tmp=out.with_suffix('.tmp'); tmp.write_text(json.dumps(provenance,sort_keys=True,indent=2)+'\n'); os.replace(tmp,out)
 if not a.skip_prepare and any(x['id']=='reference_gz' for x in selected): subprocess.run([sys.executable,str(ROOT/'scripts/prepare_m2.py'),'--workspace',str(root)],check=True)
 return 0
if __name__=='__main__': raise SystemExit(main())
