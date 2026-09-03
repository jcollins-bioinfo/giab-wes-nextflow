import hashlib,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"scripts"))
from publish_m2_workspace import publish
class PublishM2Test(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();base=Path(self.tmp.name);self.drive=base/"giab-wes-nextflow-private";self.stage=base/"m2-stage";self.drive.mkdir();self.stage.mkdir();self.run="test-run";data=b"synthetic artifact";path=self.stage/"inputs/x";path.parent.mkdir(parents=True);path.write_bytes(data);sha=hashlib.sha256(data).hexdigest();md5=hashlib.md5(data).hexdigest();e=self.stage/"registry/runs"/self.run;e.mkdir(parents=True);(e/"acquisition.json").write_text(json.dumps({"observations":[{"id":"x","sha256":sha}]}));(e/"transformation.json").write_text(json.dumps({"status":"domains_materialized"}));self.manifest=base/"manifest.json";self.manifest.write_text(json.dumps({"resources":[{"id":"x","destination":"inputs/x"}]}))
 def tearDown(self):self.tmp.cleanup()
 def test_completed_last_and_idempotent(self):
  path,changed=publish(self.drive,self.stage,self.run,self.manifest);self.assertTrue(changed);self.assertTrue((path/"COMPLETED.json").is_file());self.assertTrue((self.drive/"m2_data_provenance/registry/runs/test-run.json").is_file());self.assertFalse(publish(self.drive,self.stage,self.run,self.manifest)[1])
 def test_incomplete_never_completed_and_gate_required(self):
  (self.stage/"registry/runs"/self.run/"transformation.json").unlink()
  with self.assertRaises(ValueError):publish(self.drive,self.stage,self.run,self.manifest)
  self.assertFalse((self.drive/"m2_data_provenance/runs/completed/test-run/COMPLETED.json").exists())
 def test_safety_marker(self):
  (self.drive/"DO NOT ACCESS WITH CHATGPT").touch()
  with self.assertRaises(PermissionError):publish(self.drive,self.stage,self.run,self.manifest)
if __name__=="__main__":unittest.main()
