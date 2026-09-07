"""Create byte-stable invented M3 data; no external biological sequence is used.

SHA-256 counter output supplies a deterministic alphabet, independently of the
read placement and BQSR known-site recipe. The fixture is a wiring/invariant test,
not a substitute for HG001 data or a benchmark of caller accuracy.
"""
from __future__ import annotations

import csv
import binascii
import struct
import hashlib
import io
import json
from pathlib import Path
from typing import Any

from .acquisition import destination, safe_root

RECIPE_VERSION = "1.0.0"
SAMPLE = "SYNTHETIC01"
LIBRARY = "SYN_LIB"
CONTIG_LENGTHS = {"chrSYN1": 12000, "chrSYN2": 8000}


def sha256_bytes(value: bytes) -> str:
    """Return a content identity for an in-memory fixture artifact."""
    return hashlib.sha256(value).hexdigest()


def reverse_complement(sequence: str) -> str:
    """Reverse complement the complete deterministic DNA alphabet."""
    return sequence.translate(str.maketrans("ACGTNacgtn", "TGCANtgcan"))[::-1]


def _sequence(contig: str, length: int) -> str:
    """Expand a versioned SHA-256 counter into independent invented bases."""
    result = ""
    counter = 0
    while len(result) < length:
        block = hashlib.sha256(f"giab-wes-m3-nonhuman/{RECIPE_VERSION}/{contig}/{counter}".encode()).digest()
        result += "".join("ACGT"[value % 4] for value in block)
        counter += 1
    return result[:length]


def _gzip(payload: bytes) -> bytes:
    """Encode fixed stored-DEFLATE gzip blocks independent of zlib versions.

    Synthetic files are tiny. Deliberately uncompressed DEFLATE blocks avoid
    compressor-version differences while retaining actual gzip integrity checks.
    """
    result = bytearray(b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xff")
    blocks = [payload[start:start + 65535] for start in range(0, len(payload), 65535)] or [b""]
    for index, block in enumerate(blocks):
        result.append(1 if index == len(blocks) - 1 else 0)
        result.extend(struct.pack("<HH", len(block), 65535 - len(block)))
        result.extend(block)
    result.extend(struct.pack("<II", binascii.crc32(payload) & 0xffffffff, len(payload) & 0xffffffff))
    return bytes(result)


def fixture_payloads() -> tuple[dict[str, bytes], dict[str, Any]]:
    """Return canonical file bytes and complete expected identities/alignments."""
    reference = {name: _sequence(name, length) for name, length in CONTIG_LENGTHS.items()}
    fasta = "".join(f">{name}\n" + "".join(sequence[start:start + 60] + "\n"
                    for start in range(0, len(sequence), 60)) for name, sequence in reference.items())
    known = ["##fileformat=VCFv4.2", "##source=invented-independent-M3-BQSR-sites"]
    known += [f"##contig=<ID={name},length={length}>" for name, length in CONTIG_LENGTHS.items()]
    known += ["#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO"]
    for name, sequence in reference.items():
        for position in (751, 1551, 2451, 3751, 5051, 6651):
            base = sequence[position - 1]
            alternate = "ACGT"[("ACGT".index(base) + 1) % 4]
            known.append(f"{name}\t{position}\tSYN_{name}_{position}\t{base}\t{alternate}\t100\tPASS\t.")
    payloads = {"reference.fa": fasta.encode(), "known-sites.vcf": ("\n".join(known) + "\n").encode()}
    read_expectations: dict[str, dict[str, Any]] = {}
    sample_rows = []
    # Three copies of the first fragment span both lanes. Other fragments are
    # unique; 220-base inserts exercise overlapping mates, and N pairs unmapped.
    designs = {
        "L001": [("chrSYN1", 500, 350), ("chrSYN1", 500, 350), ("chrSYN1", 1100, 220),
                 ("chrSYN1", 1900, 400), ("chrSYN1", 2600, 350), ("chrSYN1", 3400, 350),
                 ("chrSYN1", 4400, 350), ("chrSYN2", 500, 350), ("chrSYN2", 1400, 220),
                 ("chrSYN2", 2600, 350), ("chrSYN2", 4200, 350), (None, 0, 0)],
        "L002": [("chrSYN1", 500, 350), ("chrSYN1", 5700, 350), ("chrSYN1", 6500, 220),
                 ("chrSYN1", 7600, 350), ("chrSYN1", 8500, 350), ("chrSYN1", 9800, 350),
                 ("chrSYN2", 900, 350), ("chrSYN2", 1900, 350), ("chrSYN2", 3200, 220),
                 ("chrSYN2", 5100, 350), ("chrSYN2", 6200, 350), (None, 0, 0)],
    }
    for lane_number, (lane, fragments) in enumerate(designs.items(), 1):
        rg = f"SYN_{lane}"
        names = ("reads_1.fastq.gz", "reads_2.fastq.gz") if lane_number == 1 else ("reads_lane2_1.fastq.gz", "reads_lane2_2.fastq.gz")
        texts = [[], []]
        for number, (contig, start, insert) in enumerate(fragments, 1):
            qname = f"SYN_{lane}_{number:04d}"
            for mate in (1, 2):
                if contig is None:
                    sequence = "N" * 150
                    quality = "#" * 150
                    position = None
                else:
                    sequence = (reference[contig][start:start + 150] if mate == 1 else
                                reverse_complement(reference[contig][start + insert - 150:start + insert]))
                    quality = "".join(chr(33 + 27 + ((index + number + mate) % 14)) for index in range(150))
                    if number in (4, 8) and mate == 1:
                        base = sequence[57]
                        sequence = sequence[:57] + "ACGT"[("ACGT".index(base) + 1) % 4] + sequence[58:]
                    position = start + 1 if mate == 1 else start + insert - 150 + 1
                texts[mate - 1].append(f"@{qname}/{mate}\n{sequence}\n+\n{quality}\n")
                read_expectations[f"{qname}/{mate}"] = {
                    "qname": qname, "mate": mate, "read_group": rg, "contig": contig,
                    "position_1based": position, "reverse": bool(contig and mate == 2),
                    "original_qualities": quality, "sequence_sha256": sha256_bytes(sequence.encode()),
                    "duplicate_group": "three-copy-fragment" if contig == "chrSYN1" and start == 500 else None,
                }
        for name, text in zip(names, texts):
            payloads[name] = _gzip("".join(text).encode())
        sample_rows.append({"sample": SAMPLE, "library": LIBRARY, "lane": lane, "read_group_id": rg,
                            "platform_unit": f"SYN_PU_{lane}", "fastq_1": names[0], "fastq_2": names[1],
                            "sequencing_center": "SYNTHETIC", "platform": "ILLUMINA"})
    sheet = io.StringIO(newline="")
    writer = csv.DictWriter(sheet, fieldnames=list(sample_rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(sample_rows)
    payloads["samplesheet.csv"] = sheet.getvalue().encode()
    source = {"schema_version": "1.0.0", "kind": "invented-nonhuman-reference-and-known-sites",
              "recipe_version": RECIPE_VERSION, "reference_sha256": sha256_bytes(payloads["reference.fa"]),
              "known_sites_sha256": sha256_bytes(payloads["known-sites.vcf"]),
              "contigs": CONTIG_LENGTHS, "source": "SHA-256 counter recipe; no external sequence", "license": "CC0-1.0"}
    payloads["reference-source.json"] = (json.dumps(source, sort_keys=True, indent=2) + "\n").encode()
    expectations = {"schema_version": "1.0.0", "kind": "m3-deterministic-nonhuman-fixture", "recipe_version": RECIPE_VERSION,
                    "synthetic": True, "canonical": False, "sample": SAMPLE, "library": LIBRARY,
                    "contigs": CONTIG_LENGTHS, "lanes": sample_rows, "read_length": 150,
                    "pair_count": 24, "primary_read_count": 48, "mapped_read_count": 44, "unmapped_read_count": 4,
                    "minimum_duplicate_read_count": 4, "duplicate_read_count": 4, "read_expectations": read_expectations,
                    "files": {name: {"bytes": len(data), "sha256": sha256_bytes(data)} for name, data in payloads.items()}}
    return payloads, expectations


def generate_fixture(output: str | Path) -> dict[str, Any]:
    """Materialize the fixture, preserving conflicting existing files for audit."""
    root = safe_root(output, allow_test_root=True)
    payloads, expectations = fixture_payloads()
    payloads["fixture-expectations.json"] = (json.dumps(expectations, sort_keys=True, indent=2) + "\n").encode()
    root.mkdir(parents=True, exist_ok=True)
    for name, content in payloads.items():
        path = destination(root, name)
        if path.is_symlink() or (path.exists() and path.read_bytes() != content):
            raise FileExistsError(f"different existing synthetic artifact: {name}")
        if not path.exists():
            path.write_bytes(content)
    return expectations
