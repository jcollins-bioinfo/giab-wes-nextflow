"""Durable, verified source cache; deliberately never publishes Gate B."""
import argparse, json, os, platform, shutil
from pathlib import Path
from .acquisition import checksum, destination, load_manifest, now, safe_root

def mirror_sources(staging, drive_root, run_id, repository_sha):
    stage=safe_root(staging); drive=safe_root(drive_root)
    acquisition_path=stage/'registry/runs'/run_id/'acquisition.json'
    acquisition=json.loads(acquisition_path.read_text()); spec=load_manifest()
    observations={x['id']:x for x in acquisition['observations']}
    if set(observations)!={x['id'] for x in spec['resources']}: raise ValueError('source mirror requires complete acquisition inventory')
    base=drive/'cache/verified-sources'; base.mkdir(parents=True,exist_ok=True); inventory=[]
    for resource in spec['resources']:
        src=destination(stage,resource['destination']); obs=observations[resource['id']]
        if not src.is_file() or checksum(src)!=obs['sha256']: raise ValueError(f"unverified source: {resource['id']}")
        dst=destination(base,resource['destination']); dst.parent.mkdir(parents=True,exist_ok=True)
        if dst.exists():
            if checksum(dst)!=obs['sha256']: raise FileExistsError(f"different mirror object: {resource['id']}")
        else:
            tmp=Path(str(dst)+'.incomplete'); shutil.copy2(src,tmp)
            if checksum(tmp)!=obs['sha256']: tmp.unlink(missing_ok=True); raise IOError('Drive rehash failed')
            os.replace(tmp,dst)
        inventory.append({'id':resource['id'],'destination':resource['destination'],'sha256':obs['sha256'],'bytes':dst.stat().st_size})
    record={'schema_version':'1.0.0','kind':'verified-source-mirror-not-gate-b','run_id':run_id,'source_manifest_sha256':acquisition['source_manifest_sha256'],'repository_sha':repository_sha,'runtime_architecture':platform.machine(),'created_utc':now(),'objects':inventory}
    out=drive/'registry/runs'/run_id/'verified-source-mirror.json';out.parent.mkdir(parents=True,exist_ok=True);payload=json.dumps(record,sort_keys=True,indent=2)+'\n'
    if out.exists() and out.read_text()!=payload: raise FileExistsError('immutable mirror record conflict')
    if not out.exists(): out.write_text(payload)
    return out

def hydrate_sources(drive_root, staging, run_id):
    drive=safe_root(drive_root);stage=safe_root(staging);record=json.loads((drive/'registry/runs'/run_id/'verified-source-mirror.json').read_text())
    for item in record['objects']:
        src=destination(drive/'cache/verified-sources',item['destination'])
        if checksum(src)!=item['sha256']: raise ValueError(f"corrupt mirror object: {item['id']}")
        dst=destination(stage,item['destination']);dst.parent.mkdir(parents=True,exist_ok=True)
        if dst.exists() and checksum(dst)!=item['sha256']: raise FileExistsError(f"different staging object: {item['id']}")
        if not dst.exists():
            tmp=Path(str(dst)+'.part');shutil.copy2(src,tmp)
            if checksum(tmp)!=item['sha256']:raise IOError('hydration rehash failed')
            os.replace(tmp,dst)
    return len(record['objects'])

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--drive-root',required=True);p.add_argument('--staging',required=True);p.add_argument('--run-id',required=True);p.add_argument('--repository-sha');p.add_argument('--hydrate',action='store_true');a=p.parse_args(argv)
    print(hydrate_sources(a.drive_root,a.staging,a.run_id) if a.hydrate else mirror_sources(a.staging,a.drive_root,a.run_id,a.repository_sha or 'unknown'))
