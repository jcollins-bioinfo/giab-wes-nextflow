import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from publish_private_workspace import publish,safe_root
class PublisherTest(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory(); self.base=Path(self.t.name); self.root=self.base/'giab-wes-nextflow-private'; self.bundle=self.base/'bundle'; self.bundle.mkdir(); self.make()
 def tearDown(self): self.t.cleanup()
 def make(self,name='ledger.txt',content=b'synthetic foundation evidence\n'):
  p=self.bundle/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(content);h=hashlib.sha256(content).hexdigest()
  m={'schema_version':'1.0.0','milestone':'m1_foundation','run_id':'run1','files':[{'path':name,'sha256':h,'bytes':len(content),'media_type':'text/plain','schema_id':'https://example.org/text','schema_version':'1.0.0','semantic_role':'source_ledger'}]};(self.bundle/'manifest.json').write_text(json.dumps(m))
 def test_publish_marker_last_and_idempotent(self):
  p,changed=publish(self.root,self.bundle,'run1');self.assertTrue(changed);self.assertTrue((p/'COMPLETED.json').is_file());self.assertTrue((self.root/'m1_foundation/registry/runs/run1.json').is_file());self.assertFalse(publish(self.root,self.bundle,'run1')[1])
 def test_conflict(self):
  publish(self.root,self.bundle,'run1');(self.bundle/'ledger.txt').write_text('changed');self.make(content=b'changed');
  with self.assertRaises(FileExistsError): publish(self.root,self.bundle,'run1')
 def test_tampering_and_bad_hash(self):
  m=json.loads((self.bundle/'manifest.json').read_text());m['files'][0]['sha256']='0'*64;(self.bundle/'manifest.json').write_text(json.dumps(m))
  with self.assertRaises(ValueError): publish(self.root,self.bundle,'run1')
 def test_missing(self):
  (self.bundle/'ledger.txt').unlink()
  with self.assertRaises(ValueError): publish(self.root,self.bundle,'run1')
 def test_traversal(self):
  m=json.loads((self.bundle/'manifest.json').read_text());m['files'][0]['path']='../ledger.txt';(self.bundle/'manifest.json').write_text(json.dumps(m))
  with self.assertRaises(ValueError): publish(self.root,self.bundle,'run1')
 def test_forbidden_files(self):
  for name in ('sample.bam','token.txt','.git/config','work/x'):
   with self.subTest(name=name):
    with tempfile.TemporaryDirectory() as d:
     self.bundle=Path(d);self.bundle.mkdir(exist_ok=True);self.make(name)
     with self.assertRaises(ValueError): publish(self.root,self.bundle,'run1')
 def test_unsafe_roots(self):
  for p in ('','/',str(Path.home()),str(self.base/'wrong')):
   with self.subTest(p=p),self.assertRaises(ValueError): safe_root(p)
