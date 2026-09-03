#!/usr/bin/env python3
import argparse,hashlib,json
from pathlib import Path
from jsonschema import Draft202012Validator,FormatChecker
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--workspace',required=True);a=p.parse_args();root=Path(a.workspace);prov=json.loads((root/'registry/m2-acquisition.json').read_text());schema=json.loads((ROOT/'schemas/m2-provenance.schema.json').read_text());Draft202012Validator(schema,format_checker=FormatChecker()).validate(prov)
 for x in prov['artifacts']:
  f=root/x['path'];assert f.stat().st_size==x['bytes'] and sha(f)==x['sha256'] and x['expected_md5']==x['observed_md5']
 line=root/'registry/m2-lineage.json';assert line.is_file();print('M2 acquisition and lineage valid')
if __name__=='__main__':main()
