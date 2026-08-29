#!/usr/bin/env python3
import subprocess
from pathlib import Path
files=subprocess.check_output(['git','ls-files'],text=True).splitlines(); forbidden=[]; large=[]
for n in files:
 p=Path(n)
 if any(x in {'.nextflow','work'} for x in p.parts) or p.suffix.lower() in {'.bam','.cram','.vcf','.bcf'}: forbidden.append(n)
 if p.is_file() and p.stat().st_size>100_000: large.append(n)
# Generated FASTQs must never be tracked, including the synthetic gzip materialization.
for n in files:
 if n.endswith(('.fastq.gz','.fq.gz')): forbidden.append(n)
if forbidden or large: raise SystemExit(f'forbidden={forbidden}; large={large}')
print(f'tracked files={len(files)}; no forbidden scientific/work files; no files >100KB')
