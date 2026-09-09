#!/usr/bin/env python3
"""Create a thin reviewed-SHA Colab launcher, without embedding scientific logic."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re


def build(sha: str, output: Path) -> None:
    """Pin implementation separately from the notebook commit to avoid self-reference."""
    if re.fullmatch('[0-9a-f]{40}', sha) is None:
        raise ValueError('reviewed full commit SHA required')
    cells = []
    def cell(kind: str, text: str) -> None:
        """Append an unexecuted notebook cell."""
        item = {'cell_type': kind, 'id': f'canonical-{len(cells)}', 'metadata': {}, 'source': text.splitlines(keepends=True)}
        if kind == 'code':
            item.update(execution_count=None, outputs=[])
        cells.append(item)
    cell('markdown', f'''# HG001 chr20–22 coding-domain benchmark

Run all cells in the owner's **High-RAM Linux x86_64 Colab session**. Normal Drive authorization is the only intended owner interaction. This launcher is pinned to reviewed implementation **{sha}**. Scientific and operational logic lives in the installed package and dedicated Nextflow entrypoint.

The authorized path aligns all original NIST7035 lane reads against the complete authenticated GRCh38 no-alt reference. Classic BWA0.7.17 constructs a reusable index in `/content`; GATK and DeepVariant receive one shared BAM. Calling is limited to approved chr20–22 coding intervals with100bp padding; evaluation uses the fixed unpadded 1,905,809-base domain. HG001 training overlap remains a limitation.

Public reference/tool downloads are authorized and enabled below. No paid service is launched. Active work stays in `/content`. Durable verified sources/assets and completed outputs use only `/content/drive/MyDrive/giab-wes-nextflow-private`. No BWA-MEM2 index construction occurs.

First use can take several hours; this is a planning allowance, not a measured canonical runtime. Allow at least100GiB active scratch and60GiB durable free space initially. A disconnected browser does not itself stop a running Colab kernel, but Colab session limits still apply. Restart with Run all; never delete the project cache to retry.
''')
    cell('code', f'''import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from google.colab import drive, files

ALLOW_LARGE_DOWNLOADS = True
REPOSITORY = "https://github.com/jcollins-bioinfo/giab-wes-nextflow.git"
REPOSITORY_SHA = "{sha}"
if sys.version_info < (3, 10) or not Path("/content").is_dir():
    raise RuntimeError("Use the owner Colab runtime with Python3.10 or newer.")
STAGE = Path("/content/giab-wes-canonical") / REPOSITORY_SHA[:12]
CHECKOUT = STAGE / "checkout"
if any(path.is_symlink() for path in [STAGE, CHECKOUT, *STAGE.parents]):
    raise RuntimeError("Linked bootstrap path rejected before access.")
STAGE.mkdir(parents=True, exist_ok=True)

def checked(argv: list[str], cwd: Path | None = None) -> str:
    """Run a checked non-scientific bootstrap command."""
    return subprocess.run(argv, cwd=cwd, check=True, text=True, capture_output=True).stdout.strip()

NEW_CHECKOUT = not CHECKOUT.exists()
if NEW_CHECKOUT:
    checked(["git", "clone", "--no-checkout", "--filter=blob:none", REPOSITORY, str(CHECKOUT)])
if checked(["git", "remote", "get-url", "origin"], CHECKOUT) != REPOSITORY:
    raise RuntimeError("Unexpected checkout origin; preserve it and return the error.")
if not NEW_CHECKOUT and checked(["git", "status", "--porcelain", "--untracked-files=normal"], CHECKOUT):
    raise RuntimeError("Checkout is dirty; preserve it and return the error.")
checked(["git", "fetch", "--depth=1", "origin", REPOSITORY_SHA], CHECKOUT)
checked(["git", "checkout", "--detach", REPOSITORY_SHA], CHECKOUT)
if checked(["git", "rev-parse", "HEAD"], CHECKOUT) != REPOSITORY_SHA:
    raise RuntimeError("Checkout SHA mismatch.")
subprocess.run([sys.executable, "-m", "pip", "install", "--force-reinstall", "jsonschema==4.25.1", str(CHECKOUT)], check=True)
print(checked([sys.executable, "-I", "-m", "giab_wes_nextflow.runtime_identity", "--source-root", str(CHECKOUT), "--expected-sha", REPOSITORY_SHA]))
# Ensure Nextflow's host Python resolves to this exact verified interpreter.
BIN = STAGE / "launcher-bin"
BIN.mkdir(exist_ok=True)
(BIN / "python").write_text("#!/bin/sh\\nexec " + shlex.quote(sys.executable) + ' "$@"\\n')
(BIN / "python").chmod(0o755)
os.environ["PATH"] = str(BIN) + os.pathsep + os.environ["PATH"]
''')
    cell('markdown', '''## Authorize Drive, then execute

The package first checks observed RAM, CPU flags, scratch, runtime and restart state. It qualifies representative GATK and DeepVariant execution before canonical processing. Every source and reusable asset is rehashed. Completion markers are written only after durable destination verification.

If a gate fails, the failure remains explicit. Do not change scientific parameters to make one caller look better. Return the small failure report for diagnosis.
''')
    cell('code', '''drive.mount("/content/drive")
DRIVE_ROOT = Path("/content/drive/MyDrive/giab-wes-nextflow-private")
command = [sys.executable, "-I", "-m", "giab_wes_nextflow.canonical_run",
           "--source-root", str(CHECKOUT), "--expected-sha", REPOSITORY_SHA,
           "--scratch", str(STAGE / "analysis"), "--drive-root", str(DRIVE_ROOT)]
if ALLOW_LARGE_DOWNLOADS:
    command.append("--allow-large-downloads")
result = subprocess.run(command, check=False)
if result.returncode:
    report = STAGE / "analysis/canonical-failure.json"
    if report.is_file():
        files.download(str(report))
    raise RuntimeError("Canonical execution stopped at a strict gate. Return canonical-failure.json; preserve Drive assets and retry only after diagnosis.")
''')
    cell('code', '''BUNDLE = STAGE / "analysis/canonical-hg001-evidence.zip"
COMPLETE = STAGE / "analysis/canonical-complete.json"
if not BUNDLE.is_file() or not COMPLETE.is_file():
    raise RuntimeError("No completed canonical evidence bundle exists.")
print(COMPLETE.read_text())
files.download(str(BUNDLE))
files.download(str(COMPLETE))
''')
    cell('markdown', '''## Return evidence and resume

Return **canonical-hg001-evidence.zip** and its small **canonical-complete.json** manifest pin. The bundle contains only public-safe metadata, counts, metrics, hashes and resource limitations. Native VCFs, BAMs, references, indexes and private logs remain in the authorized private project hierarchy.

On the same runtime, Nextflow resume requires cached tasks with unchanged scientific outputs. After a runtime reset, the package hydrates independently validated completed stages from Drive and rebuilds local execution state. A partial file is never a completed stage. The public bundle is accepted by the Explorer only after Codex validates its externally supplied manifest SHA.

This run cannot establish whole-exome performance, population generalization, clinical validity, production validation, training independence, or a universal caller winner. Full approved coding-domain evaluation remains a later extension.
''')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({'cells': cells, 'metadata': {'kernelspec': {'display_name': 'Python3', 'language': 'python', 'name': 'python3'}, 'language_info': {'name': 'python', 'version': '3.12'}}, 'nbformat': 4, 'nbformat_minor': 5}, indent=1) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sha', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); build(args.sha, args.output)
