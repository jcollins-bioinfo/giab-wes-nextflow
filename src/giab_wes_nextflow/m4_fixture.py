"""Generate a separate invented SNV-positive fixture without changing M3 bytes."""
from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
from typing import Any

from .acquisition import destination, safe_root
from .m3_fixture import _gzip, fixture_payloads as m3_payloads, reverse_complement, sha256_bytes

FIXTURE_ID = "m4-snv-positive"
RECIPE_VERSION = "1.0.0"
VARIANT_ORACLE = (
    ("chrSYN1", 3151, "T", "A", "0/1"),
    ("chrSYN2", 7101, "T", "A", "1/1"),
    ("chrSYN1", 5401, "G", "G", "0/0"),
)


def fixture_payloads() -> tuple[dict[str, bytes], dict[str, Any]]:
    """Append 240 unique pairs with frozen alleles to the original invented controls."""
    payloads, expected = m3_payloads()
    reference: dict[str, str] = {}
    contig = ""
    for line in payloads["reference.fa"].decode().splitlines():
        if line.startswith(">"):
            contig = line[1:]
            reference[contig] = ""
        else:
            reference[contig] += line
    texts = {name: gzip.decompress(data).decode() for name, data in payloads.items() if name.endswith(".fastq.gz")}
    lane_counts = {row["lane"]: 0 for row in expected["lanes"]}
    coordinates: set[tuple[str, int, int]] = set()
    for contig, position, ref, alt, genotype in VARIANT_ORACLE:
        if reference[contig][position - 1] != ref:
            raise ValueError("frozen M4 oracle reference allele disagrees with invented reference")
        for support_mate in (1, 2):
            for index in range(40):
                row = expected["lanes"][index % 2]
                start = position - 1 - (50 if support_mate == 1 else 250) - index
                fragment = (contig, start, start + 350)
                if fragment in coordinates:
                    raise ValueError("M4 positive support must come from unique fragments")
                coordinates.add(fragment)
                lane_counts[row["lane"]] += 1
                number = lane_counts[row["lane"]]
                qname = f"M4_SYN_{row['lane']}_{number:04d}"
                use_alt = genotype == "1/1" or (genotype == "0/1" and index < 20)
                for mate in (1, 2):
                    read_start = start if mate == 1 else start + 200
                    sequence = reference[contig][read_start:read_start + 150]
                    if use_alt and read_start <= position - 1 < read_start + 150:
                        offset = position - 1 - read_start
                        sequence = sequence[:offset] + alt + sequence[offset + 1:]
                    if mate == 2:
                        sequence = reverse_complement(sequence)
                    quality = "".join(chr(33 + 27 + ((cycle + number + mate) % 14)) for cycle in range(150))
                    texts[row[f"fastq_{mate}"]] += f"@{qname}/{mate}\n{sequence}\n+\n{quality}\n"
                    expected["read_expectations"][f"{qname}/{mate}"] = {
                        "qname": qname, "mate": mate, "read_group": row["read_group_id"],
                        "contig": contig, "position_1based": read_start + 1, "reverse": mate == 2,
                        "original_qualities": quality, "sequence_sha256": sha256_bytes(sequence.encode()),
                        "duplicate_group": None,
                    }
    for name, text in texts.items():
        payloads[name] = _gzip(text.encode())
    expected.update(kind="m4-variant-positive-nonhuman-fixture", fixture_id=FIXTURE_ID,
                    recipe_version=RECIPE_VERSION, pair_count=264, primary_read_count=528,
                    mapped_read_count=524, unmapped_read_count=4,
                    variant_sites=[{"contig": name, "position_1based": pos, "ref": ref, "alt": alt,
                                    "genotype": genotype, "expected_ref_fragment_count": 40 if genotype == "0/1" else 0,
                                    "expected_alt_fragment_count": 40 if genotype == "0/1" else 80}
                                   for name, pos, ref, alt, genotype in VARIANT_ORACLE if genotype != "0/0"],
                    reference_controls=[{"contig": name, "position_1based": pos, "ref": ref,
                                         "genotype": genotype, "expected_ref_fragment_count": 80,
                                         "expected_alt_fragment_count": 0}
                                        for name, pos, ref, _alt, genotype in VARIANT_ORACLE if genotype == "0/0"],
                    files={name: {"bytes": len(data), "sha256": sha256_bytes(data)} for name, data in payloads.items()})
    return payloads, expected


def generate_m4_fixture(output: str | Path) -> dict[str, Any]:
    """Write only this registered fixture and preserve any conflicting existing byte."""
    root = safe_root(output, allow_test_root=True)
    payloads, expected = fixture_payloads()
    payloads["fixture-expectations.json"] = (json.dumps(expected, sort_keys=True, indent=2) + "\n").encode()
    root.mkdir(parents=True, exist_ok=True)
    for name, content in payloads.items():
        path = destination(root, name)
        if path.is_symlink() or (path.exists() and path.read_bytes() != content):
            raise FileExistsError(f"conflicting M4 fixture artifact: {name}")
        if not path.exists():
            path.write_bytes(content)
    return expected


def main(argv: list[str] | None = None) -> int:
    """Materialize the invented fixture without running a biological tool."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    generate_m4_fixture(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
