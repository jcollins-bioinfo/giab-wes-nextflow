#!/usr/bin/env python3
"""Generate deterministic nonhuman reads from an invented repeating alphabet; seed 1729."""
import gzip,hashlib,random
from pathlib import Path
random.seed(1729); root=Path(__file__).parent
expected = {
    line.split()[0]: line.split()[1]
    for line in (root / 'hashes.sha256').read_text().splitlines()
    if line.strip()
}
for mate in (1,2):
 p=root/f'synthetic_nonhuman_R{mate}.fastq.gz'
 with p.open('wb') as raw:
  with gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0) as out:
   for i in range(4):
    seq=''.join(random.choice('ACGT') for _ in range(32)); text=f'@SYNTHETIC_NONHUMAN:{i}/{mate}\n{seq}\n+\n{"I"*32}\n';out.write(text.encode())
 digest = hashlib.sha256(p.read_bytes()).hexdigest()
 if expected.get(p.name) != digest:
  raise SystemExit(f'fixture hash mismatch for {p.name}: {digest}')
 print(p.name,digest)
