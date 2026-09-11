"""Nonhuman gate regressions, separate from actual managed-container proof."""
import gzip
import json

import pytest

from giab_wes_nextflow import managed_qualification as managed
from giab_wes_nextflow.m5 import reference, vcf_rows
from giab_wes_nextflow.m5_fixture import fixture, header, write_reference


def test_include_preserves_header_and_symmetric_diploid_policy(tmp_path):
    source = tmp_path / 'normalized'
    source.mkdir()
    for kind in ('fixture', 'native'):
        root = source / kind
        root.mkdir()
        seqs = {'chrToy': 'ACGTACGT'}
        write_reference(root, seqs)
        (root / 'sample.txt').write_text('SYN\n')
        body = header(seqs, 'SYN') + ('chrToy\t2\t.\tC\tT\t60\tLowQual\t.\tGT\t0/1\n'
                                       'chrToy\t4\t.\tT\tA\t60\tPASS\t.\tGT\t0/0\n')
        for caller in ('gatk', 'deepvariant', 'truth'):
            (root / (caller + '.sorted.vcf')).write_text(body)
    target = tmp_path / 'included'
    managed.include(source, target)
    for kind in ('fixture', 'native'):
        for caller in ('gatk', 'deepvariant', 'truth'):
            _, rows = vcf_rows(target / kind / (caller + '.included.vcf'), seqs, 'SYN', split=True)
            assert len(rows) == 1 and rows[0][6] == 'LowQual' and rows[0][9] == '0/1'


@pytest.fixture
def partitions(tmp_path):
    """Invent frozen partitions for testing acceptance logic; no RTG run is claimed."""
    root = tmp_path / 'benchmarked'
    root.mkdir()
    fixture(root / 'fixture')
    native = root / 'native'
    native.mkdir()
    write_reference(native, {'chrToy': 'ACGTACGT'})
    (native / 'sample.txt').write_text('SYNTHETIC01\n')
    (native / 'evaluated.bed').write_text('chrToy\t0\t8\n')
    (root / 'fixture/sample.txt').write_text('SYNM5\n')
    (root / 'fixture/evaluated.bed').write_text('chrM5\t0\t350\n')
    (root / 'native-qualification.json').write_text(json.dumps({'kind': 'managed_nonhuman_native_qualification', 'canonical': False}))
    for kind in ('fixture', 'native'):
        base = root / kind
        sample = (base / 'sample.txt').read_text().strip()
        seqs = reference(base / 'reference.fa', base / 'reference.fa.fai', base / 'reference.dict')
        for name, text in [('normalize.version.txt', 'bcftools 1.24'), ('compress.version.txt', 'bcftools 1.24'), ('rtg.version.txt', 'RTG Tools 3.13')]:
            (base / name).write_text(text + '\n')
        for caller in ('gatk', 'deepvariant'):
            (base / caller).mkdir()
            norm = 'chrM5\t290\t.\tC\tCA\t60\tPASS\t.\tGT\t0/1\n' if kind == 'fixture' else ''
            (base / (caller + '.normalized.vcf.gz')).write_bytes(gzip.compress((header(seqs, sample) + norm).encode()))
            for part in ('tp', 'tp-baseline', 'fp', 'fn'):
                if kind == 'fixture':
                    loci = {'tp': [(20, 'C'), (60, 'G'), (100, 'C'), (100, 'G')],
                            'tp-baseline': [(20, 'C'), (60, 'G'), (100, 'C'), (100, 'G')],
                            'fp': [(150, 'C'), (250, 'T')], 'fn': [(150, 'C'), (200, 'T')]}[part]
                    body = ''.join(f'chrM5\t{p}\t.\tA\t{alt}\t60\tPASS\t.\tGT\t0/1\n' for p, alt in loci)
                    if part in ('tp', 'tp-baseline'):
                        body += norm
                else:
                    body = ('chrToy\t2\t.\tC\tT\t60\tPASS\t.\tGT\t0/1\n'
                            'chrToy\t4\t.\tT\tA\t60\tPASS\t.\tGT\t0/1\n') if part in ('tp', 'tp-baseline') else ''
                (base / caller / (part + '.vcf.gz')).write_bytes(gzip.compress((header(seqs, sample) + body).encode()))
    return root


def test_frozen_oracle_acceptance_keeps_backend_cache_gate_false(partitions, tmp_path):
    result = managed.accept(partitions, tmp_path / 'qualification.json')
    assert result['normalization_benchmark_qualified'] is True
    assert result['canonical'] is False
    assert result['full_cloud_workflow_qualified'] is False
    assert result['managed_cache_qualified'] is False
    assert result['backend_receipt_binding_required'] is True


def test_genotype_mismatch_partition_cannot_be_erased(partitions, tmp_path):
    path = partitions / 'fixture/gatk/fp.vcf.gz'
    lines = gzip.decompress(path.read_bytes()).decode().splitlines(keepends=True)
    path.write_bytes(gzip.compress(''.join(l for l in lines if not l.startswith('chrM5\t150\t')).encode()))
    with pytest.raises(ValueError, match='preregistered'):
        managed.accept(partitions, tmp_path / 'rejected.json')
    assert not (tmp_path / 'rejected.json').exists()


def test_changed_denominator_is_rejected(partitions, tmp_path):
    (partitions / 'fixture/evaluated.bed').write_text('chrM5\t0\t351\n')
    with pytest.raises(ValueError, match='denominator'):
        managed.accept(partitions, tmp_path / 'rejected.json')
