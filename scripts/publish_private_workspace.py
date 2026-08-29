#!/usr/bin/env python3
"""Idempotently publish a declared, non-sensitive M1 evidence inventory."""
import argparse, hashlib, json, os, re, shutil, sys
from pathlib import Path
FORBIDDEN_NAMES={'.git','.nextflow','work'}
FORBIDDEN_EXT={'.bam','.cram','.vcf','.bcf','.fastq','.fq'}
SECRET=re.compile(r'(secret|token|credential|private[_-]?key)',re.I)
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''): h.update(b)
 return h.hexdigest()
def safe_root(value):
 if not value: raise ValueError('private root is required')
 p=Path(value).expanduser().resolve(); home=Path.home().resolve()
 if p in (Path('/'),home) or p.name!='giab-wes-nextflow-private': raise ValueError('unsafe private root')
 return p
def safe_rel(s):
 p=Path(s)
 if p.is_absolute() or '..' in p.parts or any(x in FORBIDDEN_NAMES for x in p.parts): raise ValueError(f'unsafe path: {s}')
 if p.suffix.lower() in FORBIDDEN_EXT or SECRET.search(s): raise ValueError(f'forbidden artifact: {s}')
 return p
def publish(root,bundle,run_id):
 root=safe_root(root); bundle=Path(bundle).resolve()
 if not re.fullmatch(r'[A-Za-z0-9._-]+',run_id): raise ValueError('invalid run id')
 manifest_path=bundle/'manifest.json'; manifest=json.loads(manifest_path.read_text())
 if manifest.get('schema_version')!='1.0.0' or manifest.get('milestone')!='m1_foundation' or manifest.get('run_id')!=run_id: raise ValueError('invalid manifest identity')
 inventory=manifest.get('files');
 if not isinstance(inventory,list) or not inventory: raise ValueError('empty inventory')
 declared=[]
 for item in inventory:
  if set(item)!={'path','sha256','bytes','media_type','schema_id','schema_version','semantic_role'}: raise ValueError('invalid inventory fields')
  rel=safe_rel(item['path']); src=(bundle/rel).resolve()
  if bundle not in src.parents or not src.is_file(): raise ValueError(f'missing/traversal file: {rel}')
  if src.stat().st_size!=item['bytes'] or sha(src)!=item['sha256']: raise ValueError(f'inventory mismatch: {rel}')
  declared.append((rel,src))
 allowed={str(x[0]) for x in declared}|{'manifest.json'}
 for f in bundle.rglob('*'):
  if f.is_file() and str(f.relative_to(bundle)) not in allowed: raise ValueError(f'undeclared file: {f.name}')
 base=root/'m1_foundation'; incomplete=base/'runs'/'_incomplete'/run_id; completed=base/'runs'/'completed'/run_id
 registry=base/'registry'/'runs'; reports=base/'reports'; exports=base/'exports'; logs=base/'logs'
 for d in (registry,reports,exports,logs,incomplete.parent,completed.parent): d.mkdir(parents=True,exist_ok=True)
 manifest_hash=sha(manifest_path)
 marker={'schema_version':'1.0.0','milestone':'m1_foundation','run_id':run_id,'manifest_sha256':manifest_hash,'completed_path':f'm1_foundation/runs/completed/{run_id}','inventory_count':len(declared),'status':'completed'}
 if completed.exists():
  old=json.loads((completed/'COMPLETED.json').read_text()) if (completed/'COMPLETED.json').exists() else None
  if old==marker and sha(completed/'manifest.json')==manifest_hash: return completed,False
  raise FileExistsError('conflicting completed run')
 if incomplete.exists(): shutil.rmtree(incomplete)
 incomplete.mkdir(parents=True)
 for rel,src in declared:
  dst=incomplete/rel; dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
 shutil.copy2(manifest_path,incomplete/'manifest.json')
 for rel,_ in declared:
  item=next(x for x in inventory if x['path']==str(rel))
  if sha(incomplete/rel)!=item['sha256']: raise ValueError('copy tampering detected')
 incomplete.rename(completed)
 registry_record=registry/f'{run_id}.json'; registry_record.write_text(json.dumps({'run_id':run_id,'manifest_sha256':manifest_hash,'path':str(completed.relative_to(root))},sort_keys=True,indent=2)+'\n')
 # Completion is deliberately written last, after atomic directory rename and registry.
 (completed/'COMPLETED.json').write_text(json.dumps(marker,sort_keys=True,indent=2)+'\n')
 return completed,True
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--root',default=os.getenv('GIAB_WES_PRIVATE_ROOT')); ap.add_argument('--bundle',required=True); ap.add_argument('--run-id',required=True); a=ap.parse_args()
 try:
  path,changed=publish(a.root,a.bundle,a.run_id); print(('published: ' if changed else 'no-op: ')+str(path))
 except Exception as e: print(f'error: {e}',file=sys.stderr); return 2
 return 0
if __name__=='__main__': raise SystemExit(main())
