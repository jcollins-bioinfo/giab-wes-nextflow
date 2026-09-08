"""Invent deterministic M5 representation cases without modifying M3/M4 recipes."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any
from .m5 import Runtime, identity, require

SAMPLE = 'SYNM5'
EXPECTED = {'SNP': {'tp_query': 4, 'tp_truth': 4, 'fp': 2, 'fn': 2},
            'INDEL': {'tp_query': 1, 'tp_truth': 1, 'fp': 0, 'fn': 0},
            'OTHER': {'tp_query': 0, 'tp_truth': 0, 'fp': 0, 'fn': 0}}


def header(seqs: dict[str, str], sample: str) -> str:
    """Write explicit sequence dictionaries, GT and retained native FILTER metadata."""
    return ('##fileformat=VCFv4.2\n' + ''.join(f'##contig=<ID={c},length={len(s)}>\n' for c, s in seqs.items()) +
            '##FILTER=<ID=LowQual,Description="Invented native filter retained">\n' +
            '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n' +
            '#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t' + sample + '\n')


def write_reference(root: Path, seqs: dict[str, str]) -> None:
    """Write exact one-line invented FASTA and independently computable FAI/dictionary."""
    fasta = b''; fai = []; dictionary = ['@HD\tVN:1.6\tSO:unsorted']
    for name, bases in seqs.items():
        prefix = f'>{name}\n'.encode(); offset = len(fasta) + len(prefix); fasta += prefix + bases.encode() + b'\n'
        fai.append(f'{name}\t{len(bases)}\t{offset}\t{len(bases)}\t{len(bases)+1}')
        dictionary.append(f'@SQ\tSN:{name}\tLN:{len(bases)}\tM5:{hashlib.md5(bases.encode()).hexdigest()}')
    (root / 'reference.fa').write_bytes(fasta)
    (root / 'reference.fa.fai').write_text('\n'.join(fai) + '\n')
    (root / 'reference.dict').write_text('\n'.join(dictionary) + '\n')


def fixture(root: Path) -> dict[str, Any]:
    """Materialize the preregistered SNP/indel/domain oracle before engine execution."""
    require(not root.exists(), 'fixture directory must be new'); root.mkdir(parents=True)
    bases = ['ACGT'[b % 4] for i in range(16) for b in hashlib.sha256(f'M5-invented-1.0.0-{i}'.encode()).digest()][:500]
    for p in (20, 60, 100, 150, 200, 250, 400):
        bases[p-1] = 'A'
    bases[289:311] = list('C' + 'A' * 20 + 'C')
    seqs = {'chrM5': ''.join(bases)}; write_reference(root, seqs)
    truth = [(20, 'A', 'C', '0/1'), (60, 'A', 'G', '1/1'), (100, 'A', 'C,G', '1/2'), (150, 'A', 'C', '0/1'), (200, 'A', 'T', '0/1'), (291, 'A', 'AA', '0/1')]
    query = [(20, 'A', 'C', '0/1'), (60, 'A', 'G', '1/1'), (100, 'A', 'C', '0/1'), (100, 'A', 'G', '0/1'), (150, 'A', 'C', '1/1'), (250, 'A', 'T', '0/1'), (300, 'A', 'AA', '0/1'), (400, 'A', 'T', '0/1')]
    for name, rows in [('truth', truth), ('gatk', query), ('deepvariant', query)]:
        (root / f'{name}.vcf').write_text(header(seqs, SAMPLE) + ''.join(f'chrM5\t{p}\t.\t{ref}\t{alt}\t60\tLowQual\t.\tGT\t{gt}\n' for p, ref, alt, gt in rows))
    (root / 'confidence.bed').write_text('chrM5\t0\t350\n'); (root / 'evaluation.bed').write_text('chrM5\t0\t500\n')
    (root / 'empty.bed').write_text('')
    manifest = {'synthetic': True, 'canonical': False, 'recipe_version': '1.0.0', 'sample': SAMPLE, 'domain_id': 'full',
                'reference': 'reference.fa', 'fai': 'reference.fa.fai', 'dictionary': 'reference.dict',
                'truth': 'truth.vcf.gz', 'truth_index': 'truth.vcf.gz.tbi', 'confidence': 'confidence.bed', 'domain': 'evaluation.bed',
                'queries': [{'caller': c, 'vcf': f'{c}.vcf.gz', 'index': f'{c}.vcf.gz.tbi'} for c in ('gatk', 'deepvariant')]}
    (root / 'm5-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    expected = {'schema_version': '1.0.0', 'recipe_version': '1.0.0', 'synthetic': True, 'canonical': False,
                'expected_counts': EXPECTED, 'evaluated_bases': 350, 'interval_count': 1,
                'left_aligned_insertion': ['chrM5', 290, 'C', 'CA'],
                'source_files': {p.name: identity(p) for p in sorted(root.iterdir())}}
    (root / 'fixture-expectations.json').write_text(json.dumps(expected, indent=2, sort_keys=True) + '\n')
    return expected


def compress_inputs(root: Path) -> None:
    """Create real BGZF and tabix inputs using the pinned normalizer distribution."""
    runtime = Runtime(root); runtime.version('bcftools')
    for name in ('truth', 'gatk', 'deepvariant'):
        runtime.run('bcftools', ['view', '--no-version', '-Oz', '-o', f'{name}.vcf.gz', f'{name}.vcf'])
        runtime.run('bcftools', ['index', '-t', f'{name}.vcf.gz'])
