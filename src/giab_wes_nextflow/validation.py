#!/usr/bin/env python3
import argparse,json
from pathlib import Path
from jsonschema import Draft202012Validator,FormatChecker
from .acquisition import checksum, load_manifest
from .resources import config_path, schema_path
def validate(schema,data):Draft202012Validator(json.loads(Path(schema).read_text()),format_checker=FormatChecker()).validate(data)
def main():
 p=argparse.ArgumentParser();p.add_argument("--workspace");p.add_argument("--run-id");a=p.parse_args();manifest=load_manifest()
 gate=json.loads(config_path("m2-target-design.json").read_text());assert gate["classification"] in {"confirmed","inferred","unresolved","contradicted"}
 if a.workspace:
  if not a.run_id:raise ValueError("--run-id required with --workspace")
  root=Path(a.workspace);acq=json.loads((root/"registry/runs"/a.run_id/"acquisition.json").read_text());validate(schema_path("m2-acquisition.schema.json"),acq)
  for item in acq["observations"]:
   path=root/item["destination"];assert checksum(path)==item["sha256"]
  transform=root/"registry/runs"/a.run_id/"transformation.json"
  if transform.exists():
   for domain in json.loads(transform.read_text()).get("domains",[]):validate(schema_path("m2-domain.schema.json"),domain)
 print("M2 contracts valid")
if __name__=="__main__":main()
