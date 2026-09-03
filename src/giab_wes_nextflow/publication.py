#!/usr/bin/env python3
"""Publish verified M2 staging artifacts to the existing private Drive workspace."""
import argparse, json, os, re, shutil
from pathlib import Path
from .acquisition import checksum, destination, now, safe_root
from .resources import config_path
def publish(drive_root,staging,run_id,source_manifest=None):
 source_manifest=source_manifest or config_path("m2-resources.json")
 drive=safe_root(drive_root);stage=safe_root(staging);run_id=str(run_id)
 if run_id in {".",".."} or not re.fullmatch(r"[A-Za-z0-9._-]+",run_id):raise ValueError("invalid run id")
 spec=json.loads(Path(source_manifest).read_text());acq=stage/"registry/runs"/run_id/"acquisition.json"
 if not acq.is_file():raise ValueError("missing acquisition evidence")
 transform=stage/"registry/runs"/run_id/"transformation.json"
 transformation=json.loads(transform.read_text()) if transform.is_file() else {}
 if transformation.get("status")!="domains_materialized":raise ValueError("Gate B blocked: canonical domains not materialized")
 acquisition=json.loads(acq.read_text())
 if acquisition.get("source_manifest_sha256")!=checksum(source_manifest):raise ValueError("acquisition manifest does not match publication manifest")
 observations=acquisition.get("observations",[]);verified={x["id"]:x for x in observations};required={x["id"] for x in spec["resources"]}
 if len(verified)!=len(observations) or set(verified)!=required:raise ValueError("incomplete or unexpected acquisition inventory")
 files=[]
 for item in spec["resources"]:
  src=destination(stage,item["destination"])
  if not src.is_file() or checksum(src)!=verified[item["id"]]["sha256"]:raise ValueError("unverified staging artifact")
  files.append((Path(item["destination"]),src,item["id"]))
 prepared=[]
 prepared.extend((x["id"],x["path"],x["sha256"]) for x in transformation.get("reference",[]))
 liftover=transformation.get("liftover",{})
 prepared.append(("capture_targets_lifted",liftover.get("lifted_bed_path"),liftover.get("lifted_bed_sha256")))
 domains=transformation.get("domains",[])
 if len(domains)!=4 or {x.get("artifact_id") for x in domains}!={"T_design","R_call","R_eval_full","R_eval_holdout"}:raise ValueError("incomplete prepared domain inventory")
 prepared.extend((x["artifact_id"],f"references/domains/{x['path']}",x["sha256"]) for x in domains)
 if len(prepared)!=8 or {x[0] for x in prepared}!={"grch38_fasta","grch38_fai","grch38_dict","capture_targets_lifted","T_design","R_call","R_eval_full","R_eval_holdout"}:raise ValueError("incomplete prepared artifact inventory")
 for artifact_id,relative,expected in prepared:
  if not relative:raise ValueError("prepared artifact path missing")
  src=destination(stage,relative)
  if not src.is_file() or checksum(src)!=expected:raise ValueError("prepared artifact does not match transformation evidence")
  files.append((Path("prepared")/relative,src,artifact_id))
 for name in ("acquisition.json","transformation.json"):
  src=stage/"registry/runs"/run_id/name
  if src.is_file():files.append((Path("evidence")/name,src,name.removesuffix(".json")))
 base=drive/"m2_data_provenance";incomplete=base/"runs/_incomplete"/run_id;completed=base/"runs/completed"/run_id;registry=base/"registry/runs";registry.mkdir(parents=True,exist_ok=True);completed.parent.mkdir(parents=True,exist_ok=True);incomplete.parent.mkdir(parents=True,exist_ok=True)
 if completed.exists():
  marker=completed/"COMPLETED.json"
  if marker.is_file():return completed,False
  raise FileExistsError("completed path lacks marker")
 if incomplete.exists():shutil.rmtree(incomplete)
 incomplete.mkdir(parents=True);inventory=[]
 for rel,src,artifact_id in files:
  dst=destination(incomplete,str(rel));dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
  if checksum(dst)!=checksum(src):raise IOError("destination rehash failed")
  inventory.append({"artifact_id":artifact_id,"path":str(rel),"source_sha256":checksum(src),"destination_sha256":checksum(dst),"bytes":dst.stat().st_size})
 manifest={"schema_version":"1.0.0","milestone":"m2_data_provenance","run_id":run_id,"created_utc":now(),"files":inventory};mp=incomplete/"manifest.json";mp.write_text(json.dumps(manifest,sort_keys=True,indent=2)+"\n");manifest_sha=checksum(mp);os.replace(incomplete,completed)
 reg=registry/f"{run_id}.json"
 if reg.exists():raise FileExistsError("append-only registry conflict")
 reg.write_text(json.dumps({"run_id":run_id,"manifest_sha256":manifest_sha,"path":str(completed.relative_to(drive))},sort_keys=True,indent=2)+"\n")
 marker={"schema_version":"1.0.0","run_id":run_id,"status":"completed","manifest_sha256":manifest_sha,"registry_sha256":checksum(reg),"completed_utc":now()}
 (completed/"COMPLETED.json").write_text(json.dumps(marker,sort_keys=True,indent=2)+"\n");return completed,True
def main():
 p=argparse.ArgumentParser();p.add_argument("--drive-root",required=True);p.add_argument("--staging",required=True);p.add_argument("--run-id",required=True);a=p.parse_args();path,changed=publish(a.drive_root,a.staging,a.run_id);print(("published" if changed else "no-op"),path)
if __name__=="__main__":main()
