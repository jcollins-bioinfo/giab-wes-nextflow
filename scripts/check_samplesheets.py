#!/usr/bin/env python3
import csv,gzip,re,sys
from pathlib import Path
REQ=['sample','library','lane','read_group_id','platform_unit','fastq_1','fastq_2']; ALLOWED=set(REQ+['sequencing_center','platform']); ID=re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
def validate(path):
 with open(path,newline='') as f:
  try: rows=list(csv.DictReader(f,strict=True))
  except csv.Error as e: raise ValueError('malformed CSV') from e
 if not rows or set(rows[0])-ALLOWED or any(x not in rows[0] for x in REQ): raise ValueError('columns')
 rg=set();pu=set();seen=set()
 for r in rows:
  if any(not r.get(x) for x in REQ) or any(not ID.fullmatch(r[x]) for x in REQ[:5]): raise ValueError('missing/identifier')
  if r.get('platform','ILLUMINA')!='ILLUMINA' or r['fastq_1']==r['fastq_2']: raise ValueError('metadata/mates')
  for x in ('fastq_1','fastq_2'):
   p=Path(x and r[x]);
   if not str(p).endswith('.fastq.gz') or not p.is_file(): raise ValueError('missing mate')
   try:
    with gzip.open(p,'rt') as g: next(g)
   except Exception as e: raise ValueError('unreadable gzip') from e
  key=tuple(r.get(x,'') for x in rows[0]);
  if key in seen or r['read_group_id'] in rg or r['platform_unit'] in pu: raise ValueError('duplicate')
  seen.add(key);rg.add(r['read_group_id']);pu.add(r['platform_unit'])
 return True
if __name__=='__main__':
 validate('tests/fixtures/samplesheets/valid.csv'); rejected=0
 for p in Path('tests/fixtures/samplesheets').glob('*.csv'):
  if p.name=='valid.csv': continue
  try: validate(p)
  except ValueError: rejected+=1
  else: raise SystemExit(f'negative accepted: {p}')
 print(f'samplesheet valid; negatives rejected={rejected}')
