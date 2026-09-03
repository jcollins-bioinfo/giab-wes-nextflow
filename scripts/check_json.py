#!/usr/bin/env python3
"""Parse every tracked JSON document and schema-validate canonical configurations."""
import json, subprocess
from pathlib import Path
from giab_wes_nextflow.acquisition import load_manifest
for name in subprocess.check_output(['git','ls-files','*.json','*.ipynb'],text=True).splitlines(): json.loads(Path(name).read_text())
load_manifest()
print('committed JSON and canonical M2 manifest valid')
