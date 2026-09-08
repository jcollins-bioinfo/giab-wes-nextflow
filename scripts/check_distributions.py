#!/usr/bin/env python3
"""Reject generated data, caches, unsafe members, and links in built distributions.

This reads archive metadata only and never extracts files. Explicit source roots
in pyproject.toml prevent unanchored include patterns from selecting nested
nf-test work directories; this independent check verifies the resulting bytes.
"""
from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath
import stat
import tarfile
import zipfile

FORBIDDEN_PARTS = {".git", ".nf-test", ".nextflow", "__pycache__", ".pytest_cache",
                   "work", "results", "m3-generated", "m4-generated", "m5-generated", "m5-test-results", "m3-test-results", "cache",
                   ".venv", "dist", "inputs", "references", "private-workspace"}
FORBIDDEN_SUFFIXES = (".pyc", ".bam", ".bai", ".sam", ".cram", ".crai", ".vcf",
                      ".vcf.gz", ".bcf", ".fastq.gz", ".fq.gz", ".fa", ".fasta",
                      ".fai", ".dict", ".tbi", ".gzi", ".part", ".incomplete",
                      ".fastq", ".fq", ".fna", ".fna.gz", ".fa.gz", ".fasta.gz", ".bwt", ".pac", ".sa", ".ann", ".amb")


def validate_member(name: str, size: int, *, linked: bool, regular: bool) -> None:
    """Reject unsafe archive paths, generated genomic artifacts and oversized files."""
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name or not path.parts:
        raise ValueError("unsafe distribution member path")
    if linked or not regular:
        raise ValueError("distribution member must be a regular file or directory")
    if (any(part in FORBIDDEN_PARTS or "DO NOT ACCESS WITH CHATGPT" in part for part in path.parts)
            or path.name.startswith((".nextflow", ".nf-test"))
            or name.endswith(FORBIDDEN_SUFFIXES)):
        raise ValueError(f"generated or prohibited distribution member: {name}")
    if size > 100_000:
        raise ValueError(f"distribution member exceeds the repository 100 KB policy: {name}")


def validate_archive(path: Path) -> int:
    """Inspect tar/wheel members without following links or extracting payloads."""
    names: set[str] = set()
    if path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as archive:
            for item in archive.getmembers():
                validate_member(item.name, item.size, linked=item.issym() or item.islnk(),
                                regular=item.isfile() or item.isdir())
                if item.name in names:
                    raise ValueError("duplicate distribution member")
                names.add(item.name)
    elif path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            for item in archive.infolist():
                mode = item.external_attr >> 16
                validate_member(item.filename, item.file_size, linked=stat.S_ISLNK(mode),
                                regular=stat.S_IFMT(mode) == 0 or stat.S_ISREG(mode) or stat.S_ISDIR(mode))
                if item.filename in names:
                    raise ValueError("duplicate distribution member")
                names.add(item.filename)
    else:
        raise ValueError("expected a wheel or gzip source distribution")
    if not names:
        raise ValueError("empty distribution")
    return len(names)


def main() -> None:
    """Validate every explicitly selected current build artifact."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", nargs="+", type=Path)
    args = parser.parse_args()
    for path in args.archives:
        print(f"{path.name}: {validate_archive(path)} safe members")


if __name__ == "__main__":
    main()
