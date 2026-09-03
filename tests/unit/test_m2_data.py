import hashlib,json,tempfile,unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from acquire_m2 import download
from prepare_m2 import domains,intervals,merge
class M2Test(unittest.TestCase):
 def test_existing_verified_is_idempotent(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);p=root/'inputs/x';p.parent.mkdir();p.write_bytes(b'canonical');r={'id':'x','url':'https://invalid.example/x','path':'inputs/x','md5':hashlib.md5(b'canonical').hexdigest()}
   self.assertEqual(download(r,root)[1],'verified-existing')
 def test_bad_existing_is_not_accepted(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);p=root/'x';p.write_bytes(b'wrong');r={'id':'x','url':'file:///definitely/missing','path':'x','md5':'0'*32}
   with self.assertRaises(Exception):download(r,root)
   self.assertFalse(p.exists())
 def test_domains_are_sorted_merged_padded_and_truth_bounded(self):
  with tempfile.TemporaryDirectory() as d:
   d=Path(d);(d/'target').write_text('chr20\t20\t30\nchr1\t10\t20\nchr1\t18\t25\nchrY\t1\t9\n');(d/'truth').write_text('chr1\t12\t30\nchr20\t25\t40\n');x=domains(d/'target',d/'truth',d/'out',10)
   self.assertEqual((d/'out/T_design.bed').read_text(),'chr1\t10\t25\nchr20\t20\t30\n');self.assertEqual((d/'out/R_call.bed').read_text(),'chr1\t0\t35\nchr20\t10\t40\n');self.assertEqual((d/'out/R_eval_full.bed').read_text(),'chr1\t12\t25\nchr20\t25\t30\n');self.assertEqual((d/'out/R_eval_holdout.bed').read_text(),'chr20\t25\t30\n')
 def test_live_version_metadata_is_consistent(self):
  root=Path(__file__).resolve().parents[2]
  self.assertIn("version = '0.2.0-dev.1'",(root/'nextflow.config').read_text())
  self.assertIn('version: 0.2.0-dev.1',(root/'CITATION.cff').read_text())
  self.assertEqual(json.loads((root/'schemas/run-contract.schema.json').read_text())['properties']['pipeline_version']['const'],'0.2.0-dev.1')
 def test_invalid_coordinates_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'x';p.write_text('chr1\t9\t2\n');
   with self.assertRaises(ValueError):intervals(p)
if __name__=='__main__':unittest.main()
