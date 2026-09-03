import hashlib,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"scripts"))
from publish_m2_workspace import publish
from acquire_m2 import checksum
from giab_wes_nextflow.publication import publish
from giab_wes_nextflow.acquisition import checksum
class PublishM2Test(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();base=Path(self.tmp.name);self.drive=base/"giab-wes-nextflow-private";self.stage=base/"m2-stage";self.drive.mkdir();self.stage.mkdir();self.run="test-run"
  data=b"synthetic artifact";path=self.stage/"inputs/x";path.parent.mkdir(parents=True);path.write_bytes(data);sha=hashlib.sha256(data).hexdigest()
  self.manifest=base/"manifest.json";self.manifest.write_text(json.dumps({"resources":[{"id":"x","destination":"inputs/x"}]}))
  reference=[]
  for artifact_id,relative in (("grch38_fasta","references/ref.fa"),("grch38_fai","references/ref.fa.fai"),("grch38_dict","references/ref.dict")):
   artifact=self.stage/relative;artifact.parent.mkdir(parents=True,exist_ok=True);artifact.write_bytes(artifact_id.encode());reference.append({"id":artifact_id,"path":relative,"sha256":checksum(artifact)})
  lifted=self.stage/f"cache/{self.run}/targets.GRCh38.bed";lifted.parent.mkdir(parents=True);lifted.write_bytes(b"lifted")
  domains=[]
  for artifact_id in ("T_design","R_call","R_eval_full","R_eval_holdout"):
   artifact=self.stage/f"references/domains/{artifact_id}.bed";artifact.parent.mkdir(parents=True,exist_ok=True);artifact.write_bytes(artifact_id.encode());domains.append({"artifact_id":artifact_id,"path":artifact.name,"sha256":checksum(artifact)})
  e=self.stage/"registry/runs"/self.run;e.mkdir(parents=True)
  (e/"acquisition.json").write_text(json.dumps({"source_manifest_sha256":checksum(self.manifest),"observations":[{"id":"x","sha256":sha}]}))
  (e/"transformation.json").write_text(json.dumps({"status":"domains_materialized","reference":reference,"liftover":{"lifted_bed_path":str(lifted.relative_to(self.stage)),"lifted_bed_sha256":checksum(lifted)},"domains":domains}))
 def tearDown(self):self.tmp.cleanup()
 def test_completed_last_and_idempotent(self):
  path,changed=publish(self.drive,self.stage,self.run,self.manifest);self.assertTrue(changed);self.assertTrue((path/"COMPLETED.json").is_file());self.assertTrue((self.drive/"m2_data_provenance/registry/runs/test-run.json").is_file());self.assertFalse(publish(self.drive,self.stage,self.run,self.manifest)[1])
 def test_incomplete_never_completed_and_gate_required(self):
  (self.stage/"registry/runs"/self.run/"transformation.json").unlink()
  with self.assertRaises(ValueError):publish(self.drive,self.stage,self.run,self.manifest)
  self.assertFalse((self.drive/"m2_data_provenance/runs/completed/test-run/COMPLETED.json").exists())
 def test_rejects_partial_or_wrong_manifest_acquisition(self):
  evidence=self.stage/"registry/runs"/self.run/"acquisition.json";record=json.loads(evidence.read_text());record["observations"]=[];evidence.write_text(json.dumps(record))
  with self.assertRaisesRegex(ValueError,"inventory"):publish(self.drive,self.stage,self.run,self.manifest)
 def test_rejects_dot_path_run_ids(self):
  for run_id in (".",".."):
   with self.assertRaisesRegex(ValueError,"invalid run id"):publish(self.drive,self.stage,run_id,self.manifest)
 def test_rejects_missing_prepared_artifact(self):
  (self.stage/"references/domains/T_design.bed").unlink()
  with self.assertRaisesRegex(ValueError,"prepared artifact"):publish(self.drive,self.stage,self.run,self.manifest)
 def test_safety_marker(self):
  (self.drive/"DO NOT ACCESS WITH CHATGPT").touch()
  with self.assertRaises(PermissionError):publish(self.drive,self.stage,self.run,self.manifest)
if __name__=="__main__":unittest.main()
