"""Invented-byte failure boundaries; these tests do not execute native tools."""
import gzip
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from giab_wes_nextflow import canonical_asset_reference as reference
from giab_wes_nextflow import cloud_known_sites as known


@pytest.fixture
def staged(tmp_path, monkeypatch):
    ref = tmp_path / 'reference'
    ref.mkdir()
    (ref / 'reference.fa').write_text('>chrToy\nACGTACGT\n')
    rows = [{'name': 'chrToy', 'length': 8, 'md5': hashlib.md5(b'ACGTACGT').hexdigest()}]
    spec = {'reference_dictionary': rows, 'known_sites': []}
    sources = []
    body = ('##fileformat=VCFv4.2\n##contig=<ID=chrToy,length=8>\n##contig=<ID=chrAlt,length=8>\n'
            '#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n'
            'chrToy\t2\t.\tC\tT\t.\tPASS\t.\nchrAlt\t2\t.\tC\tT\t.\tPASS\t.\n')
    for name in ('dbsnp', 'indels', 'mills'):
        for index in (False, True):
            path = tmp_path / (name + '.vcf.gz' + ('.tbi' if index else ''))
            path.write_bytes(b'invented-source-index' if index else gzip.compress(body.encode()))
            sources.append(path)
            spec['known_sites'].append({'id': name + ('_tbi' if index else ''), 'filename': path.name,
                                       'role': 'bqsr_known_sites_index' if index else 'bqsr_known_sites',
                                       'bytes': path.stat().st_size, 'checksum': {'expected': hashlib.md5(path.read_bytes()).hexdigest()}})
    manifest = {'reference_id': reference.digest_json(rows), 'contigs': rows}
    for module in (known, reference):
        monkeypatch.setattr(module, 'load_assets', lambda: spec)
        monkeypatch.setattr(module, 'validate_reference', lambda _: manifest)
    monkeypatch.setattr(known.shutil, 'disk_usage', lambda _: SimpleNamespace(free=30 * 1024 ** 3))
    return tmp_path, ref, sources, spec


def native_plumbing(staged):
    """Simulate transport only with gzip and explicit readback receipts for unit gates."""
    tmp, ref, sources, spec = staged
    filtered = tmp / 'filtered'
    prepared = known.prepare(sources, ref, filtered)
    for name in ('compress', 'index'):
        (filtered / (name + '.version.txt')).write_text('bcftools 1.24\n')
    for audit in prepared['audits']:
        name = audit['source_id'] + '.no-alt.vcf'
        gz = filtered / (name + '.gz')
        gz.write_bytes(gzip.compress((filtered / name).read_bytes()))
        Path(str(gz) + '.tbi').write_bytes(b'invented-native-index')
        count, sha = known.records(gz)
        (filtered / (name + '.count')).write_text(str(count) + '\n')
        for suffix in ('.source-records.sha256', '.sequential.sha256', '.indexed.sha256'):
            (filtered / (name + suffix)).write_text(sha + '  -\n')
    return filtered


def test_sources_are_all_authenticated_before_transform(staged):
    tmp, ref, sources, _ = staged
    sources[-1].write_bytes(b'changed')
    with pytest.raises(ValueError):
        known.prepare(sources, ref, tmp / 'filtered')
    assert not (tmp / 'filtered').exists()


def test_benchmark_truth_cannot_replace_source(staged):
    tmp, ref, sources, _ = staged
    truth = tmp / 'truth.vcf.gz'
    truth.write_bytes(sources[0].read_bytes())
    with pytest.raises(ValueError, match='filenames'):
        known.prepare([truth, *sources[1:]], ref, tmp / 'filtered')


def test_native_readback_bound_and_completion_withheld(staged):
    tmp, _, _, _ = staged
    filtered = native_plumbing(staged)
    record = known.accept(filtered, tmp / 'accepted')
    assert record['kind'] == 'canonical_bqsr_asset'
    assert all(a['retained_records'] == a['excluded_absent_reference_records'] == 1 for a in record['audits'])
    assert len(record['files']) == 6
    receipt = json.loads((tmp / 'known-sites-validation.json').read_text())
    assert receipt['task_output_copies_rehashed'] is True
    assert receipt['durable_destination_rehashed'] is False
    assert not list(tmp.rglob('COMPLETED.json'))


@pytest.mark.parametrize('suffix,value', [('.indexed.sha256', '0' * 64), ('.count', '2'), ('.source-records.sha256', '1' * 64)])
def test_bad_native_count_or_readback_blocks_asset(staged, suffix, value):
    tmp, _, _, _ = staged
    filtered = native_plumbing(staged)
    (filtered / ('dbsnp.no-alt.vcf' + suffix)).write_text(value + '\n')
    with pytest.raises(ValueError):
        known.accept(filtered, tmp / 'rejected')
    assert not (tmp / 'rejected/known-sites-manifest.json').exists()


def test_native_wrong_version_blocks_asset(staged):
    tmp, _, _, _ = staged
    filtered = native_plumbing(staged)
    (filtered / 'index.version.txt').write_text('bcftools 1.23\n')
    with pytest.raises(ValueError, match='version'):
        known.accept(filtered, tmp / 'rejected')


def test_retained_ref_mismatch_blocks_transform(staged):
    tmp, ref, sources, spec = staged
    source = sources[0]
    source.write_bytes(gzip.compress(gzip.decompress(source.read_bytes()).replace(b'chrToy\t2\t.\tC', b'chrToy\t2\t.\tG')))
    spec['known_sites'][0]['bytes'] = source.stat().st_size
    spec['known_sites'][0]['checksum']['expected'] = hashlib.md5(source.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='REF/order'):
        known.prepare(sources, ref, tmp / 'rejected')
    assert not (tmp / 'rejected/known-sites-preparation.json').exists()
