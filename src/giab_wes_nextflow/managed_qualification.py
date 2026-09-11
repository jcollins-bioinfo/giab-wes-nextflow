"""Frozen nonhuman qualification gates around native BCFtools and RTG stages."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil

from .m5 import (identity, intersect, intervals, metrics, partition_counts, reference,
                 require, selected, vcf_rows)
from .m5_fixture import EXPECTED, SAMPLE, fixture, header


def prepare(evaluated: Path, accepted: Path, output: Path) -> None:
    """Stage benchmark truth only after native caller/OQ acceptance has completed."""
    native = json.loads(accepted.read_text())
    require(native['kind'] == 'managed_nonhuman_native_qualification' and native['canonical'] is False
            and set(native['callers']) == {'gatk', 'deepvariant'}, 'native caller qualification missing')
    output.mkdir(parents=True, exist_ok=False)
    fixture(output / 'fixture')
    target = output / 'native'
    target.mkdir()
    frozen = json.loads((evaluated / 'fixture-expectations.json').read_text())
    for name in ('reference.fa', 'reference.fa.fai', 'reference.dict', 'gatk.vcf.gz', 'deepvariant.vcf.gz'):
        shutil.copyfile(evaluated / name, target / name)
    for caller in ('gatk', 'deepvariant'):
        require(identity(target / (caller + '.vcf.gz'))['sha256'] == native['callers'][caller]['vcf_sha256'],
                'accepted native caller output changed')
    seqs = reference(target / 'reference.fa', target / 'reference.fa.fai', target / 'reference.dict')
    sites = frozen['variant_sites']
    require(len(sites) == 2 and native['original_quality_records_verified'] == frozen['primary_read_count'],
            'native frozen site/quality inventory differs')
    sample = 'SYNTHETIC01'
    (target / 'truth.vcf').write_text(header(seqs, sample) + ''.join(
        f"{s['contig']}\t{s['position_1based']}\t.\t{s['ref']}\t{s['alt']}\t60\tPASS\t.\tGT\t{s['genotype']}\n" for s in sites))
    region = ''.join(f'{c}\t0\t{len(bases)}\n' for c, bases in seqs.items())
    (target / 'evaluation.bed').write_text(region)
    (target / 'confidence.bed').write_text(region)
    shutil.copyfile(accepted, output / 'native-qualification.json')
    for kind in ('fixture', 'native'):
        root = output / kind
        seqs = reference(root / 'reference.fa', root / 'reference.fa.fai', root / 'reference.dict')
        domain = intersect(intervals(root / 'evaluation.bed', seqs), intervals(root / 'confidence.bed', seqs), seqs)
        (root / 'evaluated.bed').write_text(''.join(f'{c}\t{s}\t{e}\n' for c, s, e in domain))
        (root / 'sample.txt').write_text((SAMPLE if kind == 'fixture' else sample) + '\n')


def include(source: Path, output: Path) -> None:
    """Apply the existing symmetric diploid/nonreference inclusion policy."""
    shutil.copytree(source, output)
    for kind in ('fixture', 'native'):
        root = output / kind
        sample = (root / 'sample.txt').read_text().strip()
        seqs = reference(root / 'reference.fa', root / 'reference.fa.fai', root / 'reference.dict')
        for caller in ('gatk', 'deepvariant', 'truth'):
            headers, rows = vcf_rows(root / (caller + '.sorted.vcf'), seqs, sample, split=True)
            retained, excluded = selected(rows)
            (root / (caller + '.included.vcf')).write_text(''.join(headers) + ''.join('\t'.join(r) + '\n' for r in retained))
            (root / (caller + '.inclusion.json')).write_text(json.dumps({'excluded': excluded, 'retained': len(retained)}) + '\n')


def accept(source: Path, output: Path) -> dict:
    """Require frozen locus/count/representation oracles, never derive them from calls."""
    observed = {}
    for kind in ('fixture', 'native'):
        root = source / kind
        sample = (root / 'sample.txt').read_text().strip()
        seqs = reference(root / 'reference.fa', root / 'reference.fa.fai', root / 'reference.dict')
        for name, pattern in [('normalize.version.txt', r'(?m)^bcftools 1\.24(?:\s|$)'),
                              ('compress.version.txt', r'(?m)^bcftools 1\.24(?:\s|$)'),
                              ('rtg.version.txt', r'RTG Tools 3\.13(?:\s|$)')]:
            require(re.search(pattern, (root / name).read_text()) is not None, 'native benchmark version differs')
        region = intervals(root / 'evaluated.bed', seqs)
        if kind == 'fixture':
            require(sum(e-s for _, s, e in region) == 350 and len(region) == 1, 'frozen M5 denominator differs')
        callers = {}
        expected = EXPECTED if kind == 'fixture' else {
            'SNP': {'tp_query': 2, 'tp_truth': 2, 'fp': 0, 'fn': 0},
            'INDEL': {'tp_query': 0, 'tp_truth': 0, 'fp': 0, 'fn': 0},
            'OTHER': {'tp_query': 0, 'tp_truth': 0, 'fp': 0, 'fn': 0}}
        for caller in ('gatk', 'deepvariant'):
            counts = {name: partition_counts(root / caller / (name + '.vcf.gz'), seqs, sample)
                      for name in ('tp', 'tp-baseline', 'fp', 'fn')}
            values = {variant: metrics(counts['tp'][variant], counts['tp-baseline'][variant], counts['fp'][variant], counts['fn'][variant])
                      for variant in ('SNP', 'INDEL', 'OTHER')}
            require(all({key: values[variant][key] for key in wanted} == wanted for variant, wanted in expected.items()),
                    f'{kind}/{caller} preregistered benchmark counts differ')
            if kind == 'fixture':
                _, rows = vcf_rows(root / (caller + '.normalized.vcf.gz'), seqs, sample, split=True)
                require(any([r[0], int(r[1]), r[3], r[4]] == ['chrM5', 290, 'C', 'CA'] for r in rows),
                        'frozen insertion was not left aligned')
                for name, loci in {'tp': [20, 60, 100, 100], 'tp-baseline': [20, 60, 100, 100],
                                   'fp': [150, 250], 'fn': [150, 200]}.items():
                    _, rows = vcf_rows(root / caller / (name + '.vcf.gz'), seqs, sample, split=True)
                    require(sorted(int(r[1]) for r in rows if len(r[3]) == len(r[4]) == 1) == loci,
                            'frozen genotype/representation partition loci differ')
            callers[caller] = {'metrics': values, 'normalized': identity(root / (caller + '.normalized.vcf.gz')),
                               'partitions': {p.name: identity(p) for p in sorted((root / caller).iterdir()) if p.is_file()}}
        observed[kind] = {'callers': callers, 'evaluated_bases': sum(e-s for _, s, e in region), 'interval_count': len(region)}
    native = json.loads((source / 'native-qualification.json').read_text())
    require(native.get('kind') == 'managed_nonhuman_native_qualification' and native.get('canonical') is False,
            'native qualification identity differs')
    result = {**native, 'normalization_benchmark_qualified': True, 'benchmarks': observed,
              'full_cloud_workflow_qualified': False, 'managed_cache_qualified': False,
              'backend_receipt_binding_required': True}
    output.write_text(json.dumps(result, indent=2) + '\n')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'include', 'accept'))
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--accepted', type=Path)
    args = parser.parse_args()
    if args.command == 'prepare':
        require(args.accepted is not None, 'native acceptance receipt required')
        prepare(args.input, args.accepted, args.output)
    elif args.command == 'include':
        include(args.input, args.output)
    else:
        accept(args.input, args.output)


if __name__ == '__main__':
    main()
