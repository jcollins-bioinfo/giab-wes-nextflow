#!/usr/bin/env python3
"""Prepare the reference and frozen interval domains without read processing."""
import argparse,gzip,hashlib,json,os,shutil,subprocess
from pathlib import Path
AUTOSOMES_X={f'chr{i}' for i in range(1,23)}|{'chrX'}
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def intervals(path,allowed=AUTOSOMES_X):
 result=[]
 for line in Path(path).read_text().splitlines():
  if not line or line.startswith(('#','track','browser')): continue
  c,s,e,*_=line.split('\t'); s,e=int(s),int(e)
  if c not in allowed: continue
  if not 0<=s<e: raise ValueError(f'invalid BED interval: {line}')
  result.append((c,s,e))
 return result
def merge(rows):
 order={f'chr{i}':i for i in range(1,23)};order['chrX']=23; rows=sorted(rows,key=lambda x:(order[x[0]],x[1],x[2])); out=[]
 for c,s,e in rows:
  if out and out[-1][0]==c and s<=out[-1][2]: out[-1]=(c,out[-1][1],max(e,out[-1][2]))
  else: out.append((c,s,e))
 return out
def intersect(a,b):
 by={};out=[]
 for x in b:by.setdefault(x[0],[]).append(x)
 for c,s,e in a:
  for _,u,v in by.get(c,[]):
   if u>=e:break
   if v>s and u<e:out.append((c,max(s,u),min(e,v)))
 return merge(out)
def write(rows,path): Path(path).write_text(''.join(f'{c}\t{s}\t{e}\n' for c,s,e in rows))
def domains(target,truth,out,padding=100):
 design=merge(intervals(target)); high=merge(intervals(truth,{f'chr{i}' for i in range(1,23)})); call=merge((c,max(0,s-padding),e+padding) for c,s,e in design); full=intersect(high,design); hold=[x for x in full if x[0] in {'chr20','chr21','chr22'}]
 out.mkdir(parents=True,exist_ok=True); paths={}
 for name,rows in [('T_design',design),('R_call',call),('R_eval_full',full),('R_eval_holdout',hold)]:
  p=out/f'{name}.bed';write(rows,p);paths[name]={'path':str(p),'sha256':sha(p),'intervals':len(rows),'bases':sum(e-s for _,s,e in rows)}
 return paths
def main():
 p=argparse.ArgumentParser();p.add_argument('--workspace',required=True);p.add_argument('--target-hg19');p.add_argument('--chain');p.add_argument('--lift-over',default='liftOver');p.add_argument('--padding',type=int,default=100);a=p.parse_args();root=Path(a.workspace)
 gz=root/'references/GRCh38/GCA_000001405.15_GRCh38_no_alt_analysis_set.fasta.gz'; fa=gz.with_suffix('')
 if gz.exists() and not fa.exists():
  tmp=fa.with_suffix('.tmp')
  with gzip.open(gz,'rb') as src,tmp.open('wb') as dst:shutil.copyfileobj(src,dst)
  os.replace(tmp,fa)
 generated=[]
 if fa.exists():
  subprocess.run(['samtools','faidx',str(fa)],check=True); subprocess.run(['samtools','dict','-o',str(fa.with_suffix('.dict')),str(fa)],check=True);generated += [fa,Path(str(fa)+'.fai'),fa.with_suffix('.dict')]
 lineage={'schema_version':'1.0.0','pipeline_version':'0.2.0-dev.1','generated':[{'path':str(x.relative_to(root)),'sha256':sha(x),'bytes':x.stat().st_size} for x in generated]}
 if a.target_hg19 and a.chain:
  t=Path(a.target_hg19); lifted=root/'references/targets/target.GRCh38.unmerged.bed';lifted.parent.mkdir(parents=True,exist_ok=True);unmapped=lifted.with_suffix('.unmapped.bed');subprocess.run([a.lift_over,str(t),a.chain,str(lifted),str(unmapped)],check=True)
  lineage['target_liftover']={'source_sha256':sha(t),'chain_sha256':sha(a.chain),'unmapped_sha256':sha(unmapped),'domains':domains(lifted,root/'references/truth/HG001_GRCh38_1_22_v4.2.1_benchmark.bed',root/'references/domains',a.padding)}
 out=root/'registry/m2-lineage.json';out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(lineage,sort_keys=True,indent=2)+'\n')
if __name__=='__main__':main()
