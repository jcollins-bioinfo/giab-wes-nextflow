"""Verify that the installed package matches a reviewed checkout before data I/O.

Invoke with Python isolated mode so PYTHONPATH, user site packages and the current
working directory cannot shadow the installation. This verifies code/resource
bytes, not biological data or the capabilities of an execution environment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from . import __version__


def package_inventory(directory: Path) -> dict[str, str]:
    """Hash packaged code and resource files using relative, platform-neutral keys."""
    return {
        path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.suffix in {".py", ".json"}
    }


def verify_install(source_root: Path, expected_sha: str) -> dict[str, str | int]:
    """Reject an installation with missing, extra or changed code/resource bytes.

    The shell launcher independently verifies clean source and origin before pip.
    Recheck clean source here to detect a change during installation.
    """
    root = source_root.resolve(strict=True)
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=normal"], cwd=root,
        check=True, capture_output=True, text=True,
    ).stdout
    if status:
        raise ValueError("source changed during installation; use a clean reviewed checkout")
    expected = package_inventory(root / "src/giab_wes_nextflow")
    installed = package_inventory(Path(__file__).resolve().parent)
    if not expected or expected != installed:
        raise ValueError("installed package code/resources do not match the reviewed checkout")
    sha = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD^{commit}"], cwd=root,
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    if sha != expected_sha:
        raise ValueError("checkout commit changed during installation")
    digest = hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest()
    return {"repository_sha": sha, "version": __version__, "files": len(expected), "package_inventory_sha256": digest}


def main(argv: list[str] | None = None) -> int:
    """Print a non-sensitive installed-source identity record or fail before use."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(verify_install(args.source_root, args.expected_sha), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
