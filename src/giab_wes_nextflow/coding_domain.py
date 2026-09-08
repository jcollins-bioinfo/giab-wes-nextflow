"""Reproduce the owner-approved fixed GENCODE coding domain; fail on pin drift."""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable
from .m5 import identity, require

AUTOSOMES = tuple(f"chr{i}" for i in range(1, 23))
CONTIGS = (*AUTOSOMES, "chrX")
ORDER = {contig: index for index, contig in enumerate(CONTIGS)}
Interval = tuple[str, int, int]
INPUT_PINS = {
    "gtf": "5b9ad9aa71f6ab5d55123c51f74723644a895bc0cbaa9cee8fbc11bb9dec0bf7",
    "fai": "502a1b8fb73ccd53285c28a0f12df90c818b4fe3de1e862ef47c593ef1a0a4b4",
    "confidence": "dc3485e60447a3e863c34dfc063c3710ea5ed5efae50855c5197ba62538263b9",
}
EXPECTED = {
    "R_call": (189747, 77896078, "521a5c1140953bb516f36d28486767f49284a071a851331ce8d14f320d7ff728"),
    "R_eval_full": (203986, 33567783, "9c270a2c46c2e83ae0d35e5ceaa75e4b77918924bf7443d4fffe467cd9b950d4"),
    "R_eval_holdout": (11715, 1905809, "7730c4303e03fef74d2c22193102845e369e04ac81fabb7f41fae1374be65d00"),
}

def load_reference_lengths(path: Path) -> dict[str, int]:
    """Require unique, positive FAI lengths without reading sequence bytes."""
    lengths: dict[str, int] = {}
    for line in path.read_text().splitlines():
        fields = line.split("\t")
        if len(fields) != 5 or fields[0] in lengths:
            raise ValueError("Malformed or duplicate FAI row")
        length = int(fields[1])
        if length <= 0:
            raise ValueError("Nonpositive reference length")
        lengths[fields[0]] = length
    if not set(CONTIGS).issubset(lengths):
        raise ValueError("Reference index lacks a selected chromosome")
    return lengths

def load_bed(path: Path, lengths: dict[str, int], allowed: tuple[str, ...]) -> list[Interval]:
    """Validate every BED row before filtering, sorting, or interval arithmetic."""
    intervals: list[Interval] = []
    with path.open() as stream:
        for number, line in enumerate(stream, 1):
            fields = line.rstrip("\n").split("\t")
            if len(fields) != 3:
                raise ValueError(f"Not exact BED3: {path.name}:{number}")
            contig, start_text, end_text = fields
            start, end = int(start_text), int(end_text)
            if contig not in allowed or not 0 <= start < end <= lengths[contig]:
                raise ValueError(f"Unknown contig or invalid bounds: {path.name}:{number}")
            intervals.append((contig, start, end))
    if not intervals:
        raise ValueError("Empty input domain")
    return intervals

def merge(intervals: list[Interval]) -> list[Interval]:
    """Return chromosome-ordered union, merging overlaps and touching endpoints."""
    result: list[Interval] = []
    for contig, start, end in sorted(intervals, key=lambda row: (ORDER[row[0]], row[1], row[2])):
        if result and result[-1][0] == contig and start <= result[-1][2]:
            old_contig, old_start, old_end = result[-1]
            result[-1] = old_contig, old_start, max(old_end, end)
        else:
            result.append((contig, start, end))
    return result

def intersection(left: list[Interval], right: list[Interval]) -> list[Interval]:
    """Intersect two normalized BEDs using a linear two-pointer scan."""
    result: list[Interval] = []
    i = j = 0
    while i < len(left) and j < len(right):
        lc, ls, le = left[i]
        rc, rs, re = right[j]
        if ORDER[lc] < ORDER[rc]:
            i += 1
        elif ORDER[rc] < ORDER[lc]:
            j += 1
        else:
            if max(ls, rs) < min(le, re):
                result.append((lc, max(ls, rs), min(le, re)))
            if le <= re:
                i += 1
            else:
                j += 1
    return merge(result)

def pad(intervals: list[Interval], lengths: dict[str, int], padding: int) -> list[Interval]:
    """Apply fixed symmetric padding and clip against pinned chromosome lengths."""
    if padding < 0:
        raise ValueError("Negative padding")
    return merge([(contig, max(0, start - padding), min(lengths[contig], end + padding))
                  for contig, start, end in intervals])

def assert_domain(intervals: list[Interval], lengths: dict[str, int]) -> None:
    """Reject output with invalid bounds, order, overlaps, or touching intervals."""
    if not intervals or intervals != merge(intervals):
        raise ValueError("Output is empty or not a normalized interval union")
    for contig, start, end in intervals:
        if not 0 <= start < end <= lengths[contig]:
            raise ValueError("Output is outside the pinned reference bounds")

def assert_subset(subset: list[Interval], superset: list[Interval]) -> None:
    """Require every base of a proposed subset to belong to its parent domain."""
    if intersection(subset, superset) != subset:
        raise ValueError("Domain containment failed")

def coding_intervals(lines: Iterable[str], lengths: dict[str, int]) -> list[Interval]:
    """Select CDS plus stop codons with unique protein-coding gene/transcript types."""
    selected = []
    for line in lines:
        if line.startswith('#'):
            continue
        fields = line.rstrip('\n').split('\t')
        require(len(fields) == 9, 'malformed GTF row')
        contig, _, feature, start, end, _, _, _, attributes = fields
        if contig not in CONTIGS or feature not in ('CDS', 'stop_codon'):
            continue
        types = {key: re.findall(r'(?:^|;)[ \t]*' + key + r' "([^"\n]+)"(?=;|$)', attributes)
                 for key in ('gene_type', 'transcript_type')}
        require(all(len(v) == 1 for v in types.values()), 'missing or ambiguous GTF biotype')
        if any(v != ['protein_coding'] for v in types.values()):
            continue
        begin, finish = int(start)-1, int(end)
        require(contig in lengths and 0 <= begin < finish <= lengths[contig], 'GTF coordinate/reference mismatch')
        selected.append((contig, begin, finish))
    require(bool(selected), 'empty selected coding domain')
    return merge(selected)


def derive(coding: list[Interval], confidence: list[Interval], lengths: dict[str, int]) -> dict[str, list[Interval]]:
    """Apply fixed padding and confidence intersection independently of calls/depth."""
    coding = merge(coding); confidence = merge(confidence)
    assert_domain(coding, lengths); assert_domain(confidence, lengths)
    full = intersection([r for r in coding if r[0] in AUTOSOMES], confidence)
    result = {'R_call': pad(coding, lengths, 100), 'R_eval_full': full,
              'R_eval_holdout': [r for r in full if r[0] in ('chr20','chr21','chr22')]}
    assert_subset(coding, result['R_call']); assert_subset(full, confidence)
    return result


def construct(gtf: Path, fai: Path, confidence: Path, output: Path | None = None) -> dict[str, Any]:
    """Verify exact source/output pins before writing any approved BED or completion record.

    With output=None, verify in memory only. No reference bases, caller outputs,
    reads or coverage are accepted. Input hashes and expected domain hashes are
    immutable; disagreement fails closed and requires review, not replacement pins.
    """
    require(output is None or (not output.exists() and not any(p.is_symlink() for p in (output.absolute(), *output.absolute().parents))), 'output directory must be new with unlinked ancestors')
    sources = {k: identity(p) for k,p in [('gtf',gtf),('fai',fai),('confidence',confidence)]}
    require(all(sources[k]['sha256'] == v for k,v in INPUT_PINS.items()), 'approved source hash mismatch')
    lengths = load_reference_lengths(fai)
    with gzip.open(gtf, 'rt', encoding='utf-8') as stream:
        coding = coding_intervals(stream, lengths)
    regions = derive(coding, load_bed(confidence,lengths,AUTOSOMES), lengths)
    outputs = {}; encoded = {}
    for name, intervals in regions.items():
        assert_domain(intervals,lengths)
        data = ''.join(f'{c}\t{s}\t{e}\n' for c,s,e in intervals).encode('ascii')
        observed = (len(intervals),sum(e-s for _,s,e in intervals),hashlib.sha256(data).hexdigest())
        require(observed == EXPECTED[name], f'approved {name} identity mismatch; do not revise approval')
        encoded[name] = data
        outputs[name] = dict(zip(('intervals','bases','sha256'),observed),bytes=len(data))
    result = {'schema_version':'1.0.0','status':'approved_domain_reproduced','canonical_execution_ready':False,
              'reference_base_identity_verified':False,'inputs':sources,'outputs':outputs,
              'method':'GENCODE v50 Basic; both protein_coding biotypes; CDS plus stop_codon; BED half-open; fixed pad100 calling; autosomal confidence evaluation'}
    if output is not None:
        output.mkdir(parents=True)
        for name,data in encoded.items():
            (output/(name+'.bed')).write_bytes(data)
            require(hashlib.sha256((output/(name+'.bed')).read_bytes()).hexdigest()==outputs[name]['sha256'], 'written domain corrupted')
        (output/'domain-complete.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main() -> None:
    """Verify approved source/domain identities; optionally emit validated BEDs."""
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('gtf','fai','confidence'):
        parser.add_argument('--'+name,required=True,type=Path)
    parser.add_argument('--output',type=Path)
    print(json.dumps(construct(**vars(parser.parse_args())),indent=2))


if __name__ == '__main__':
    main()
