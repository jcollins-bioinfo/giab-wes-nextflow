import hashlib, json, tempfile, unittest
from pathlib import Path
from jsonschema import ValidationError
from giab_wes_nextflow import __version__
from giab_wes_nextflow.acquisition import CANONICAL_IDS, load_manifest, preflight
from giab_wes_nextflow.mirror import hydrate_sources, mirror_sources
from giab_wes_nextflow.resources import config_path, schema_path

class HotfixTest(unittest.TestCase):
 def test_package_resources_and_canonical_manifest(self):
  spec=load_manifest();self.assertEqual(__version__,'0.3.0-dev.1');self.assertEqual({x['id'] for x in spec['resources']},CANONICAL_IDS);self.assertEqual(len(spec['resources']),10);self.assertTrue(schema_path('m2-source-manifest.schema.json').is_file())
 def test_preflight_has_no_workspace_mutation(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td)/'m2-stage';before=list(Path(td).iterdir());result=preflight(workspace=root);self.assertEqual(before,list(Path(td).iterdir()));self.assertEqual(result['resource_count'],10)
 def test_manifest_rejects_malformed_duplicate_legacy_and_missing(self):
  spec=json.loads(config_path('m2-resources.json').read_text())
  cases=[]
  duplicate=json.loads(json.dumps(spec));duplicate['resources'].append(duplicate['resources'][0]);cases.append(duplicate)
  legacy=json.loads(json.dumps(spec));legacy['resources'][0]['md5']='0'*32;cases.append(legacy)
  missing=json.loads(json.dumps(spec));missing['resources'].pop();cases.append(missing)
  unsafe=json.loads(json.dumps(spec));unsafe['resources'][0]['destination']='../escape';cases.append(unsafe)
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/'manifest.json'
   path.write_text('{');
   with self.assertRaises(json.JSONDecodeError):load_manifest(path)
   for case in cases:
    path.write_text(json.dumps(case))
    with self.assertRaises((ValueError,ValidationError)):load_manifest(path)
 def test_notebook_is_clean_and_current(self):
  notebook=json.loads(Path('notebooks/m2_colab.ipynb').read_text());source='\n'.join(''.join(x['source']) for x in notebook['cells'])
  self.assertTrue(all(c.get('execution_count') is None and not c.get('outputs') for c in notebook['cells'] if c['cell_type']=='code'))
  for stale in ('--skip-prepare','--target-hg19','!python','!pip','sys.path.insert','runpy') : self.assertNotIn(stale,source)
  for expected in ('REPOSITORY_URL','REPOSITORY_REF','giab_wes_nextflow','subprocess.run','RESOLVED_SHA'):self.assertIn(expected,source)
if __name__=='__main__':unittest.main()
