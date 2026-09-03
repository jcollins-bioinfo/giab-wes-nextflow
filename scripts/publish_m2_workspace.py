#!/usr/bin/env python3
"""Publish verified M2 staging artifacts to the existing private Drive workspace."""
import argparse, json, os, re, shutil
from pathlib import Path
from acquire_m2 import checksum, destination, now, safe_root
ROOT=Path(__file__).parents[1]
def publish(drive_root,staging,run_id,source_manifest=ROOT/"config/m2-resources.json"):
 drive=safe_root(drive_root);stage=safe_root(staging);run_id=str(run_id)
 if not re.fullmatch(r"[A-Za-z0-9._-]+",run_id):raise ValueError("invalid run id")
 spec=json.loads(Path(source_manifest).read_text());acq=stage/"registry/runs"/run_id/"acquisition.json"
 if not acq.is_file():raise ValueError("missing acquisition evidence")
 transform=stage/"registry/runs"/run_id/"transformation.json"
 if not transform.is_file() or json.loads(transform.read_text()).get("status")!="domains_materialized":raise ValueError("Gate B blocked: canonical domains not materialized")
 observations=json.loads(acq.read_text())["observations"];verified={x["id"]:x for x in observations};files=[]
 for item in spec["resources"]:
  if item["id"] not in verified:continue
  src=destination(stage,item["destination"])
  if not src.is_file() or checksum(src)!=verified[item["id"]]["sha256"]:raise ValueError("unverified staging artifact")
  files.append((Path(item["destination"]),src,item["id"]))
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
