"""Materialize explicit non-biological placeholders for Nextflow stub wiring only.

These empty VCF/index files cannot pass scientific validators. Real M5 fixture
generation and tool acceptance are separate; never use this directory as evidence.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def generate(output: Path) -> None:
    """Create a closed synthetic manifest with deliberately unusable tool inputs."""
    output.mkdir(parents=True, exist_ok=True)
    fields = {"reference": "reference.fa", "fai": "reference.fa.fai", "dictionary": "reference.dict",
              "truth": "truth.vcf.gz", "truth_index": "truth.vcf.gz.tbi",
              "confidence": "confidence.bed", "domain": "evaluation.bed"}
    queries = [{"caller": caller, "vcf": caller + ".vcf.gz", "index": caller + ".vcf.gz.tbi"}
               for caller in ("gatk", "deepvariant")]
    for name in [*fields.values(), *(q[k] for q in queries for k in ("vcf", "index"))]:
        path = output / name
        if not path.exists():
            path.write_bytes(b"")
    manifest = {"synthetic": True, "sample": "SYNM5", "domain_id": "full", **fields, "queries": queries}
    (output / "manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n")


def main() -> None:
    """Write placeholders only to the selected test directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("tests/data/m5-generated"))
    generate(parser.parse_args().output)


if __name__ == "__main__":
    main()
