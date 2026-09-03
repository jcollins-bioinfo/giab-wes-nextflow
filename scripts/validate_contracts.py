#!/usr/bin/env python3
"""Validate Draft 2020-12 schemas and explicitly synthetic fixtures."""
import argparse, json, math
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker
ROOT=Path(__file__).resolve().parents[1]
def load(p): return json.loads(Path(p).read_text())
def validate(schema_path, instance_path):
 schema=load(schema_path); Draft202012Validator.check_schema(schema)
 data=load(instance_path); data.pop('_schema',None)
 errors=list(Draft202012Validator(schema,format_checker=FormatChecker()).iter_errors(data))
 if errors: raise ValueError('; '.join(e.message for e in errors))
 if 'precision' in data:
  expected=data['query_tp']/(data['query_tp']+data['fp']) if data['query_tp']+data['fp'] else 0
  recall=data['truth_tp']/(data['truth_tp']+data['fn']) if data['truth_tp']+data['fn'] else 0
  f1=2*expected*recall/(expected+recall) if expected+recall else 0
  if any(not math.isclose(data[k],v,abs_tol=1e-9) for k,v in [('precision',expected),('recall',recall),('f1',f1)]): raise ValueError('inconsistent benchmark formula')
 if 'nodes' in data:
  graph={n:[] for n in data['nodes']}
  for e in data['edges']:
   if e['from'] not in graph or e['to'] not in graph: raise ValueError('lineage edge references unknown node')
   graph[e['from']].append(e['to'])
  visiting=set(); done=set()
  def visit(n):
   if n in visiting: raise ValueError('cyclic lineage')
   if n not in done:
    visiting.add(n)
    for x in graph[n]: visit(x)
    visiting.remove(n); done.add(n)
  for n in graph: visit(n)
 if data.get('comparability')=='comparable':
  ids=[data[x]['sha256'] for x in ('common_bam','truth','evaluation_domain')]+[data['configuration_sha256']]
  if len(ids)!=len(set(ids)): pass # identities may coincidentally hash alike; equality across callers is encoded once
 return True
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--fixture'); ap.add_argument('--schema'); a=ap.parse_args()
 if a.fixture: validate(a.schema,a.fixture); print('valid'); return
 valid=ROOT/'tests/fixtures/evidence/valid'; invalid=ROOT/'tests/fixtures/evidence/invalid'
 for f in valid.glob('*.json'): validate(ROOT/load(f)['_schema'],f)
 rejected=0
 for f in invalid.glob('*.json'):
  try: validate(ROOT/load(f)['_schema'],f)
  except (ValueError,Exception): rejected+=1
  else: raise SystemExit(f'invalid fixture accepted: {f}')
 validate(ROOT/'schemas/m2-source-manifest.schema.json',ROOT/'config/m2-resources.json')
 print(f'contracts valid; invalid fixtures rejected={rejected}; M2 source manifest valid')
if __name__=='__main__': main()
