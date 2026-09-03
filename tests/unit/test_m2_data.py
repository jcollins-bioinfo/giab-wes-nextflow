import hashlib,json,sys,tempfile,threading,unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"scripts"))
from acquire_m2 import acquire,destination,lock,redact
from prepare_m2 import bed_to_interval_list,build_domains,interval_list_to_bed,read_dict
class Handler(BaseHTTPRequestHandler):
 data=b"synthetic-public-fixture"*100; ignore_range=False; failures=0; truncate_once=False
 def do_GET(self):
  if type(self).failures:type(self).failures-=1;self.send_error(503);return
  start=0
  if self.headers.get("Range") and not type(self).ignore_range:start=int(self.headers["Range"].split("=")[1].split("-")[0]);self.send_response(206);self.send_header("Content-Range",f"bytes {start}-{len(self.data)-1}/{len(self.data)}")
  else:self.send_response(200)
  body=self.data[start:];self.send_header("Content-Length",str(len(body)));self.end_headers()
  if type(self).truncate_once:type(self).truncate_once=False;self.wfile.write(body[:17]);self.close_connection=True
  else:self.wfile.write(body)
 def log_message(self,*args):pass
class M2DataTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.server=ThreadingHTTPServer(("127.0.0.1",0),Handler);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.url=f"http://127.0.0.1:{self.server.server_port}/file?token=SECRET";Handler.ignore_range=False;Handler.failures=0;Handler.truncate_once=False
 def tearDown(self):self.server.shutdown();self.server.server_close();self.tmp.cleanup()
 def resource(self,checksum=None):return {"id":"fixture","destination":"inputs/file.bin","url":self.url,"checksum":{"expected":checksum or hashlib.md5(Handler.data).hexdigest()}}
 def test_fresh_atomic_idempotent_and_redacted(self):
  obs=acquire(self.resource(),self.root);self.assertEqual(obs["status"],"verified");self.assertNotIn("?",obs["source_url"]);self.assertFalse((self.root/"inputs/file.bin.part").exists());self.assertEqual(acquire(self.resource(),self.root)["sha256"],obs["sha256"])
 def test_resume_and_server_without_range(self):
  part=self.root/"inputs/file.bin.part";part.parent.mkdir(parents=True);part.write_bytes(Handler.data[:31]);self.assertTrue(acquire(self.resource(),self.root)["response"]["range_requested"])
  (self.root/"inputs/file.bin").unlink();part.write_bytes(Handler.data[:31]);Handler.ignore_range=True;self.assertFalse(acquire(self.resource(),self.root)["response"]["range_requested"])
 def test_checksum_failure_removes_partial_and_quarantines_corrupt_final(self):
  final=self.root/"inputs/file.bin";final.parent.mkdir(parents=True);final.write_bytes(b"corrupt")
  with self.assertRaises(ValueError):acquire(self.resource("0"*32),self.root)
  self.assertFalse(Path(str(final)+".part").exists());self.assertTrue(list(final.parent.glob("file.bin.corrupt-*")))
 def test_retry(self):Handler.failures=1;self.assertEqual(acquire(self.resource(),self.root,sleep=lambda _:None)["retry_count"],1)
 def test_truncated_response_resumes(self):Handler.truncate_once=True;self.assertEqual(acquire(self.resource(),self.root,sleep=lambda _:None)["retry_count"],1)
 def test_nonretryable_http_failure(self):
  resource=self.resource();resource["url"]="http://127.0.0.1:1/missing"
  with self.assertRaises(Exception):acquire(resource,self.root,retries=0,sleep=lambda _:None)
 def test_concurrent_lock_times_out_without_corruption(self):
  path=self.root/"held.lock"
  with lock(path):
   with self.assertRaises(TimeoutError):
    with lock(path,timeout=.01):pass
  self.assertFalse(path.exists())
 def test_safe_destination_and_redaction(self):
  with self.assertRaises(ValueError):destination(self.root,"../escape")
  self.assertEqual(redact("https://x/y?token=secret"),"https://x/y")
 def test_bed_interval_list_round_trip_and_domain_boundaries(self):
  dictionary=self.root/"ref.dict";dictionary.write_text("@HD\tVN:1.6\n@SQ\tSN:chr1\tLN:20\n@SQ\tSN:chr20\tLN:20\n@SQ\tSN:chr21\tLN:20\n@SQ\tSN:chr22\tLN:20\n@SQ\tSN:chrX\tLN:20\n")
  target=self.root/"target.bed";target.write_text("chr1\t0\t1\ta\nchr1\t18\t20\tb\nchr20\t5\t6\tc\n");il=self.root/"x.interval_list";rows=bed_to_interval_list(target,dictionary,il);self.assertIn("chr1\t1\t1\t+\ta",il.read_text());back=self.root/"back.bed";self.assertEqual(interval_list_to_bed(il,read_dict(dictionary),back),rows)
  truth=self.root/"truth.bed";truth.write_text("chr1\t0\t20\nchr20\t0\t20\n");out=self.root/"domains";first=build_domains(target,truth,dictionary,out,"run",100);hashes=[x["sha256"] for x in first];second=build_domains(target,truth,dictionary,out,"run",100);self.assertEqual(hashes,[x["sha256"] for x in second]);self.assertEqual((out/"R_call.bed").read_text(),"chr1\t0\t20\nchr20\t0\t20\n");self.assertEqual([x["bases"] for x in first],[4,40,4,1])
 def test_unknown_contig_rejected(self):
  d=self.root/"d";d.write_text("@SQ\tSN:chr1\tLN:10\n");b=self.root/"b";b.write_text("1\t0\t1\n")
  with self.assertRaises(ValueError):bed_to_interval_list(b,d,self.root/"o")
if __name__=="__main__":unittest.main()
