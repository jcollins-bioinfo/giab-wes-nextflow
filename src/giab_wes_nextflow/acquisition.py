#!/usr/bin/env python3
"""Safe, resumable acquisition of objects declared by the M2 source manifest."""
from __future__ import annotations
import argparse, contextlib, datetime as dt, hashlib, http.client, json, os, random, re, shutil, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker
from . import __version__
from .resources import config_path, schema_path
VERSION=__version__; USER_AGENT=f"giab-wes-nextflow-acquire/{VERSION}"
CANONICAL_IDS={"giab_garvan_sequence_index","hg001_nist7035_l001_r1","hg001_nist7035_l001_r2","grch38_no_alt_fasta_gz","grch38_compressed_fai","grch38_compressed_gzi","hg001_v421_truth_vcf","hg001_v421_truth_tbi","hg001_v421_high_confidence_bed","ucsc_hg19_to_hg38_chain"}
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
def load_manifest(path=None):
 """Parse and validate the complete canonical manifest before side effects."""
 path=Path(path) if path else config_path("m2-resources.json")
 spec=json.loads(path.read_text())
 schema=json.loads(schema_path("m2-source-manifest.schema.json").read_text())
 Draft202012Validator(schema,format_checker=FormatChecker()).validate(spec)
 resources=spec["resources"]; ids=[x["id"] for x in resources]; dests=[x["destination"] for x in resources]; names=[x["filename"] for x in resources]
 if set(ids)!=CANONICAL_IDS or len(ids)!=len(set(ids)):raise ValueError("manifest must contain each canonical resource exactly once")
 if len(dests)!=len(set(dests)) or len(names)!=len(set(names)):raise ValueError("duplicate destination or filename")
 for item in resources:
  if {"md5","path"}&set(item):raise ValueError("legacy manifest keys are forbidden")
  destination(Path("/tmp/manifest-root"),item["destination"])
  parsed=urllib.parse.urlsplit(item["url"])
  if parsed.scheme!="https" or parsed.username or parsed.password:raise ValueError(f"unsafe URL for {item['id']}")
  algo=item["checksum"]["algorithm"]; digest=item["checksum"]["expected"]
  if algo not in hashlib.algorithms_available or not re.fullmatch(r"[0-9a-f]{32}",digest):raise ValueError(f"invalid checksum for {item['id']}")
 return spec
def preflight(manifest=None,workspace=None,remote=False,opener=urllib.request.urlopen):
 """Return a machine-readable, zero-download readiness result."""
 spec=load_manifest(manifest); result={"ok":True,"resource_count":len(spec["resources"]),"resource_ids":[x["id"] for x in spec["resources"]],"declared_bytes":sum(x["bytes"] or 0 for x in spec["resources"]),"remote_checked":remote}
 if workspace:
  root=safe_root(workspace); parent=next((p for p in [root,*root.parents] if p.exists()),None); result["workspace"]=str(root);result["free_bytes"]=shutil.disk_usage(parent).free
 if remote:
  for item in spec["resources"]:
   request=urllib.request.Request(item["url"],method="HEAD",headers={"User-Agent":USER_AGENT})
   with opener(request,timeout=20):pass
 return result
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
 p=argparse.ArgumentParser();p.add_argument("--workspace");p.add_argument("--manifest");p.add_argument("--only",action="append");p.add_argument("--run-id");p.add_argument("--preflight-only",action="store_true");p.add_argument("--check-remote",action="store_true");a=p.parse_args(argv)
 try: result=preflight(a.manifest,a.workspace,a.check_remote)
 except Exception as error: p.error(f"preflight failed ({type(error).__name__}): {error}")
 if a.preflight_only:print(json.dumps(result,sort_keys=True));return 0
 if not a.workspace or not a.run_id:p.error("--workspace and --run-id are required for acquisition")
 if a.run_id in {".",".."} or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*",a.run_id):p.error("unsafe --run-id")
 root=safe_root(a.workspace);spec=load_manifest(a.manifest); out=destination(root,f"registry/runs/{a.run_id}/acquisition.json")
 if out.exists():
  existing=json.loads(out.read_text())
  for item in existing["observations"]:
   path=destination(root,item["destination"])
   if not path.is_file() or checksum(path)!=item["sha256"]:raise ValueError("immutable observation no longer matches workspace bytes")
  print(out);return 0
 selected=[x for x in spec["resources"] if not a.only or x["id"] in a.only]; observations=[]
 for resource in selected:
  final=destination(root,resource["destination"]);state="reused" if final.exists() else ("resumed" if Path(str(final)+".part").exists() else "new")
  print(f"resource={resource['id']} destination={resource['destination']} state={state}",flush=True)
  try: observations.append(acquire(resource,root))
  except Exception as error:
   part=Path(str(final)+".part");rerun=f"giab-wes-acquire-m2 --workspace {root} --run-id {a.run_id} --only {resource['id']}"
   print(f"ERROR resource={resource['id']} class={type(error).__name__} message={str(error).split('?')[0]} partial={'retained' if part.exists() else 'absent'} rerun={rerun}",flush=True);return 1
 manifest_path=Path(a.manifest) if a.manifest else config_path("m2-resources.json")
 record={"schema_version":"1.0.0","run_id":a.run_id,"created_utc":now(),"source_manifest_sha256":checksum(manifest_path),"observations":observations}
 out.parent.mkdir(parents=True,exist_ok=True)
 payload=json.dumps(record,sort_keys=True,indent=2)+"\n"
 if out.exists() and out.read_text()!=payload: raise FileExistsError("immutable acquisition observation already exists")
 if not out.exists(): tmp=Path(str(out)+".tmp");tmp.write_text(payload);os.replace(tmp,out)
 print(out);return 0
if __name__=="__main__": raise SystemExit(main())
