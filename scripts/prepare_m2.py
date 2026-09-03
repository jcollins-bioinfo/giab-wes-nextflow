#!/usr/bin/env python3
"""Reference preparation, Picard liftover, and deterministic M2 domains."""
from __future__ import annotations
import argparse, datetime as dt, gzip, hashlib, json, os, shutil, subprocess
from collections import defaultdict
from pathlib import Path
PRIMARY=tuple([f"chr{i}" for i in range(1,23)]+["chrX"]); ORDER={c:i for i,c in enumerate(PRIMARY)}
def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def sha(path):
 h=hashlib.sha256()
 with Path(path).open("rb") as f:
  for b in iter(lambda:f.read(1<<20),b""):h.update(b)
 return h.hexdigest()
def materialize_reference(gz,fa):
 tmp=Path(str(fa)+".tmp");tmp.unlink(missing_ok=True)
 with gzip.open(gz,"rb") as src,tmp.open("wb") as dst:shutil.copyfileobj(src,dst)
 if fa.exists():
  if sha(tmp)!=sha(fa):tmp.unlink();raise ValueError("existing reference FASTA does not match the verified compressed source")
  tmp.unlink()
 else:os.replace(tmp,fa)
def verify_canonical_gate(gate,target_bed,source_dict,min_liftover_pct):
 if not gate.get("canonical_domains_allowed"):raise RuntimeError("capture-design gate blocks canonical liftover/domain publication")
 approved=gate.get("approved_artifacts")
 if not isinstance(approved,dict):raise ValueError("confirmed gate lacks approved artifact checksums")
 for key,path in (("target_bed_sha256",target_bed),("source_dict_sha256",source_dict)):
  expected=approved.get(key)
  if not isinstance(expected,str) or len(expected)!=64 or sha(path)!=expected:raise ValueError(f"{key} does not match confirmed gate")
 if gate.get("min_liftover_pct") is None or min_liftover_pct!=gate["min_liftover_pct"]:raise ValueError("liftover threshold does not match confirmed gate")
def read_dict(path):
 lengths={}
 for line in Path(path).read_text().splitlines():
  if line.startswith("@SQ"):
   fields=dict(x.split(":",1) for x in line.split("\t")[1:]);lengths[fields["SN"]]=int(fields["LN"])
 if not lengths: raise ValueError("empty sequence dictionary")
 return lengths
def read_bed(path,lengths,allowed=PRIMARY):
 rows=[]
 for number,line in enumerate(Path(path).read_text().splitlines(),1):
  if not line or line.startswith(("#","track","browser")):continue
  fields=line.split("\t");
  if len(fields)<3:raise ValueError(f"malformed BED line {number}")
  contig=fields[0]
  if contig not in lengths:raise ValueError(f"unknown contig {contig}")
  start,end=int(fields[1]),int(fields[2])
  if contig not in allowed:continue
  if start<0 or end<=start or end>lengths[contig]:raise ValueError(f"invalid BED coordinates line {number}")
  rows.append((contig,start,end,fields[3] if len(fields)>3 else f"interval_{number:08d}"))
 if not rows:raise ValueError("empty interval result")
 return rows
def merge(rows):
 out=[]
 for c,s,e,*_ in sorted(rows,key=lambda x:(ORDER[x[0]],x[1],x[2])):
  if out and out[-1][0]==c and s<=out[-1][2]:out[-1]=(c,out[-1][1],max(e,out[-1][2]))
  else:out.append((c,s,e))
 return out
def intersect(left,right):
 by=defaultdict(list);out=[]
 for c,s,e in right:by[c].append((s,e))
 for c,s,e in left:
  for u,v in by[c]:
   if u>=e:break
   if v>s:out.append((c,max(s,u),min(e,v)))
 return merge(out)
def bed_to_interval_list(bed,dictionary,out):
 lengths=read_dict(dictionary);rows=read_bed(bed,lengths)
 headers=[x for x in Path(dictionary).read_text().splitlines() if x.startswith("@")]
 Path(out).write_text("\n".join(headers)+"\n"+"".join(f"{c}\t{s+1}\t{e}\t+\t{name}\n" for c,s,e,name in rows));return rows
def interval_list_to_bed(interval_list,lengths,out):
 rows=[]
 for line in Path(interval_list).read_text().splitlines():
  if not line or line.startswith("@"):continue
  c,s,e,_,name=line.split("\t")[:5];rows.append((c,int(s)-1,int(e),name))
 validated=[]
 for c,s,e,name in rows:
  if c not in lengths or s<0 or e<=s or e>lengths[c]:raise ValueError("invalid lifted interval")
  validated.append((c,s,e,name))
 Path(out).write_text("".join(f"{c}\t{s}\t{e}\t{name}\n" for c,s,e,name in validated));return validated
def write_bed(rows,path):Path(path).write_text("".join(f"{c}\t{s}\t{e}\n" for c,s,e in rows))
def summary(identifier,rows,path,parents,dict_sha,run_id,definition):
 per={}
 for c in PRIMARY:
  subset=[x for x in rows if x[0]==c]
  if subset:per[c]={"interval_count":len(subset),"bases":sum(e-s for _,s,e in subset)}
 return {"artifact_id":identifier,"definition":definition,"path":Path(path).name,"parents":parents,"reference_build":"GCA_000001405.15/GRCh38","contig_convention":"chr1-chr22,chrX","dictionary_sha256":dict_sha,"generation":{"tool":"prepare_m2.py","version":"0.2.0-dev.1","run_id":run_id,"created_utc":now()},"interval_count":len(rows),"bases":sum(e-s for _,s,e in rows),"per_contig":per,"sha256":sha(path),"validation_status":"valid"}
def build_domains(target,truth,dictionary,out,run_id,padding=100):
 lengths=read_dict(dictionary);design=merge(read_bed(target,lengths));high=merge(read_bed(truth,lengths));call=merge((c,max(0,s-padding),min(lengths[c],e+padding)) for c,s,e in design);full=intersect(high,design);hold=[x for x in full if x[0] in {"chr20","chr21","chr22"}]
 if not set(hold)<=set(full) or any(not any(c==d and u<=s and e<=v for d,u,v in design) for c,s,e in full):raise AssertionError("domain containment failed")
 out.mkdir(parents=True,exist_ok=True);defs={"T_design":"lifted, validated, merged, unpadded capture targets","R_call":"merge(pad(T_design,100)) clipped to primary contigs","R_eval_full":"GIAB high-confidence intersect T_design on primary contigs","R_eval_holdout":"R_eval_full intersect chr20-chr22"};result=[];dsha=sha(dictionary)
 for name,rows,parents in [("T_design",design,["capture_targets_lifted"]),("R_call",call,["T_design"]),("R_eval_full",full,["T_design","hg001_v421_high_confidence_bed"]),("R_eval_holdout",hold,["R_eval_full"])]:
  path=out/f"{name}.bed";write_bed(rows,path);result.append(summary(name,rows,path,parents,dsha,run_id,defs[name]))
 return result
def main():
 p=argparse.ArgumentParser();p.add_argument("--workspace",required=True);p.add_argument("--run-id",required=True);p.add_argument("--target-bed");p.add_argument("--source-dict");p.add_argument("--picard",default="picard");p.add_argument("--min-liftover-pct",type=float,default=.95);a=p.parse_args();root=Path(a.workspace);gate=json.loads((Path(__file__).parents[1]/"config/m2-target-design.json").read_text())
 gz=root/"references/GRCh38/GCA_000001405.15_GRCh38_no_alt_analysis_set.fasta.gz";fa=gz.with_suffix("")
 materialize_reference(gz,fa)
 subprocess.run(["samtools","faidx",str(fa)],check=True);dictionary=fa.with_suffix(".dict");subprocess.run(["samtools","dict","-o",str(dictionary),str(fa)],check=True)
 evidence={"schema_version":"1.0.0","run_id":a.run_id,"reference":[{"id":"grch38_fasta","path":str(fa.relative_to(root)),"sha256":sha(fa)},{"id":"grch38_fai","path":str(Path(str(fa)+".fai").relative_to(root)),"sha256":sha(str(fa)+".fai")},{"id":"grch38_dict","path":str(dictionary.relative_to(root)),"sha256":sha(dictionary)}],"capture_design_classification":gate["classification"],"domains":[],"status":"reference_prepared_domain_blocked"}
 if a.target_bed:
  if not a.source_dict:raise ValueError("--source-dict required")
  verify_canonical_gate(gate,a.target_bed,a.source_dict,a.min_liftover_pct)
  work=root/"cache"/a.run_id;work.mkdir(parents=True,exist_ok=True);source_il=work/"targets.hg19.interval_list";bed_to_interval_list(a.target_bed,a.source_dict,source_il);lifted_il=work/"targets.GRCh38.interval_list";rejected=work/"targets.rejected.interval_list";chain=root/"references/chains/hg19ToHg38.over.chain.gz"
  version=subprocess.run([a.picard,"--version"],check=True,capture_output=True,text=True).stdout.strip()
  if "3.1.1" not in version:raise RuntimeError(f"Picard 3.1.1 required, observed {version}")
  subprocess.run([a.picard,"LiftOverIntervalList",f"I={source_il}",f"O={lifted_il}",f"SD={dictionary}",f"CHAIN={chain}",f"REJECT={rejected}",f"MIN_LIFTOVER_PCT={a.min_liftover_pct}"],check=True)
  source_rows=read_bed(a.target_bed,read_dict(a.source_dict));lifted_bed=work/"targets.GRCh38.bed";lifted=interval_list_to_bed(lifted_il,read_dict(dictionary),lifted_bed);rejected_rows=[x for x in rejected.read_text().splitlines() if x and not x.startswith("@")] ;merged_lifted=merge(lifted)
  source_by_id={x[3]:(x[2]-x[1]) for x in source_rows};altered=sum((e-s)!=source_by_id.get(name) for c,s,e,name in lifted)
  evidence["liftover"]={"tool":"Picard LiftOverIntervalList","observed_version":version,"required_version":"3.1.1","min_liftover_pct":a.min_liftover_pct,"source_sha256":sha(a.target_bed),"source_dict_sha256":sha(a.source_dict),"lifted_bed_path":str(lifted_bed.relative_to(root)),"lifted_bed_sha256":sha(lifted_bed),"chain_sha256":sha(chain),"input_intervals":len(source_rows),"input_bases":sum(e-s for _,s,e,_ in source_rows),"lifted_intervals":len(lifted),"lifted_bases":sum(e-s for _,s,e,_ in lifted),"rejected_intervals":len(rejected_rows),"rejected_sha256":sha(rejected),"split_intervals":max(0,len(lifted)+len(rejected_rows)-len(source_rows)),"merged_intervals":len(merged_lifted),"altered_length_intervals":altered};evidence["domains"]=build_domains(lifted_bed,root/"references/truth/HG001_GRCh38_1_22_v4.2.1_benchmark.bed",dictionary,root/"references/domains",a.run_id);evidence["status"]="domains_materialized"
 out=root/"registry/runs"/a.run_id/"transformation.json";out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(evidence,sort_keys=True,indent=2)+"\n");print(out)
if __name__=="__main__":main()
