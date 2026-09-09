#!/usr/bin/env python3
"""Reject tracked workflow scratch, genomic payloads and oversized repository files."""
from __future__ import annotations

from pathlib import Path
import subprocess

FORBIDDEN_SUFFIXES = ('.bam', '.bai', '.sam', '.cram', '.crai', '.vcf', '.vcf.gz', '.bcf',
                      '.fastq', '.fastq.gz', '.fq', '.fq.gz', '.fa', '.fa.gz', '.fasta',
                      '.fasta.gz', '.fna', '.fna.gz', '.fai', '.dict', '.tbi', '.gzi',
                      '.bwt', '.pac', '.sa', '.ann', '.amb')


def forbidden_path(name: str) -> bool:
    """Reject raw probe reads and reference/index files independently of Git ignore rules."""
    path = Path(name)
    return any(part in {'.nextflow', 'work'} for part in path.parts) or name.lower().endswith(FORBIDDEN_SUFFIXES)


def main() -> None:
    """Inspect tracked path metadata only, without opening genomic file contents."""
    files = subprocess.check_output(['git', 'ls-files'], text=True).splitlines()
    forbidden = [name for name in files if forbidden_path(name)]
    large = [name for name in files if Path(name).is_file() and Path(name).stat().st_size > 100_000]
    if forbidden or large:
        raise SystemExit(f'forbidden={forbidden}; large={large}')
    print(f'tracked files={len(files)}; no forbidden scientific/work files; no files >100KB')


if __name__ == '__main__':
    main()
