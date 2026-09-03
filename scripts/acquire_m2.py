#!/usr/bin/env python3
"""Safe, resumable acquisition of objects declared by the M2 source manifest."""
from __future__ import annotations
import argparse, contextlib, datetime as dt, hashlib, http.client, json, os, random, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path
VERSION="0.2.0-dev.1"; USER_AGENT=f"giab-wes-nextflow-acquire/{VERSION}"
def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def checksum(path,algorithm="sha256"):
 h=hashlib.new(algorithm)
 with Path(path).open("rb") as stream:
  for block in iter(lambda:stream.read(8<<20),b""): h.update(block)
 return h.hexdigest()
def redact(url):
 p=urllib.parse.urlsplit(url); return urllib.parse.urlunsplit((p.scheme,p.netloc,p.path,"",""))
def safe_root(value,allow_test_root=False):
 p=Path(value).expanduser().resolve()
 if p in {Path("/"),Path.home().resolve()} or (not allow_test_root and p.name not in {"giab-wes-nextflow-private","m2-stage"}): raise ValueError("unsafe acquisition root")
 if (p/"DO NOT ACCESS WITH CHATGPT").exists(): raise PermissionError("workspace safety marker present")
 return p
def destination(root,relative):
 rel=Path(relative)
 if rel.is_absolute() or ".." in rel.parts: raise ValueError("unsafe destination")
 out=(root/rel).resolve()
 if root!=out and root not in out.parents: raise ValueError("destination escapes root")
 return out
def lock(path,timeout=15):
 @contextlib.contextmanager
 def held():
  deadline=time.monotonic()+timeout
  while True:
   try: fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.write(fd,str(os.getpid()).encode());break
   except FileExistsError:
    if time.monotonic()>=deadline: raise TimeoutError(f"lock busy: {path.name}")
    time.sleep(.05)
  try: yield
  finally: os.close(fd);Path(path).unlink(missing_ok=True)
 return held()
def acquire(resource,root,retries=3,opener=urllib.request.urlopen,sleep=time.sleep):
 root=Path(root).resolve(); final=destination(root,resource["destination"]); final.parent.mkdir(parents=True,exist_ok=True); part=Path(str(final)+".part"); expected=resource["checksum"]["expected"]
 with lock(Path(str(final)+".lock")):
  if final.exists() and checksum(final,"md5")==expected: return observation(resource,final,"verified",0,{},resource["url"])
  # Never delete a corrupt completed object: quarantine it for audit.
  if final.exists(): os.replace(final,Path(str(final)+f".corrupt-{int(time.time())}"))
  attempts=0; metadata={}; effective=resource["url"]
  while True:
   offset=part.stat().st_size if part.exists() else 0; headers={"User-Agent":USER_AGENT}
   if offset: headers["Range"]=f"bytes={offset}-"
   try:
    request=urllib.request.Request(resource["url"],headers=headers)
    with opener(request,timeout=60) as response:
     status=getattr(response,"status",200); effective=response.geturl(); append=bool(offset and status==206)
     if offset and not append: offset=0
     mode="ab" if append else "wb"
     written=0
     with part.open(mode) as out:
      while True:
       block=response.read(1<<20)
       if not block: break
       out.write(block);written+=len(block)
      out.flush();os.fsync(out.fileno())
     declared=response.headers.get("Content-Length")
     if declared is not None and written!=int(declared):raise http.client.IncompleteRead(b"",int(declared)-written)
     metadata={"http_status":status,"etag":response.headers.get("ETag"),"last_modified":response.headers.get("Last-Modified"),"content_length":declared,"range_requested":append}
    break
   except urllib.error.HTTPError as error:
    error.close();attempts+=1
    if error.code not in {408,425,429,500,502,503,504} or attempts>retries: raise
   except (urllib.error.URLError,http.client.IncompleteRead,TimeoutError,ConnectionError,OSError):
    attempts+=1
    if attempts>retries: raise
   sleep(min(8,2**(attempts-1))+random.random()/10)
  if checksum(part,"md5")!=expected:
   part.unlink(missing_ok=True); raise ValueError(f"checksum mismatch for {resource['id']}")
  os.replace(part,final)
  return observation(resource,final,"verified",attempts,metadata,effective)
def observation(resource,path,status,retries,response,effective_url):
 return {"id":resource["id"],"status":status,"source_url":redact(resource["url"]),"effective_url":redact(effective_url),"destination":resource["destination"],"bytes":path.stat().st_size,"checksum":{"algorithm":"md5","expected":resource["checksum"]["expected"],"observed":checksum(path,"md5")},"sha256":checksum(path),"verified_utc":now(),"retry_count":retries,"response":response,"tool":{"name":"acquire_m2.py","version":VERSION}}
def main(argv=None):
 p=argparse.ArgumentParser();p.add_argument("--workspace",required=True);p.add_argument("--manifest",default=Path(__file__).parents[1]/"config/m2-resources.json");p.add_argument("--only",action="append");p.add_argument("--run-id",required=True);a=p.parse_args(argv)
 root=safe_root(a.workspace);spec=json.loads(Path(a.manifest).read_text()); out=destination(root,f"registry/runs/{a.run_id}/acquisition.json")
 if out.exists():
  existing=json.loads(out.read_text())
  for item in existing["observations"]:
   path=destination(root,item["destination"])
   if not path.is_file() or checksum(path)!=item["sha256"]:raise ValueError("immutable observation no longer matches workspace bytes")
  print(out);return 0
 selected=[x for x in spec["resources"] if not a.only or x["id"] in a.only]; observations=[acquire(x,root) for x in selected]
 record={"schema_version":"1.0.0","run_id":a.run_id,"created_utc":now(),"source_manifest_sha256":checksum(a.manifest),"observations":observations}
 out.parent.mkdir(parents=True,exist_ok=True)
 payload=json.dumps(record,sort_keys=True,indent=2)+"\n"
 if out.exists() and out.read_text()!=payload: raise FileExistsError("immutable acquisition observation already exists")
 if not out.exists(): tmp=Path(str(out)+".tmp");tmp.write_text(payload);os.replace(tmp,out)
 print(out);return 0
if __name__=="__main__": raise SystemExit(main())
