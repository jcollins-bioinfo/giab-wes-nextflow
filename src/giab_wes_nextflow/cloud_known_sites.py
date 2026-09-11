"""Audited BQSR preparation around separate native BCFtools task stages.

These are private task receipts. Durable S3 rehash and backend task/image binding
must precede an operator-published completion marker; this module creates none.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil

from .acquisition import validate_source_bytes, write_record
from .canonical_asset_reference import (digest_json, filter_known_site, identity,
                                        load_assets, validate_reference)
from .canonical_assets import copy_verified
from .m5 import require


def prepare(sources: list[Path], reference: Path, output: Path) -> dict:
    """Authenticate all six independent source objects before filtering any VCF."""
    spec = load_assets()['known_sites']
    require(len(sources) == len(spec) == len({p.name for p in sources}), 'known-sites source inventory differs')
    by_name = {p.name: p for p in sources}
    require(set(by_name) == {r['filename'] for r in spec}, 'known-sites source filenames differ')
    for item in spec:
        validate_source_bytes(by_name[item['filename']], item)
    ref = validate_reference(reference)
    output.mkdir(parents=True, exist_ok=False)
    require(shutil.disk_usage(output).free >= 20 * 1024 ** 3, 'known-sites preparation requires >=20GiB scratch')
    audits = []
    for item in spec:
        if item['role'] != 'bqsr_known_sites':
            continue
        target = output / (item['id'] + '.no-alt.vcf')
        kept, removed = filter_known_site(by_name[item['filename']], item, reference, target)
        audits.append({'source_id': item['id'], 'source': identity(by_name[item['filename']]),
                       'retained_records': kept, 'excluded_absent_reference_records': removed,
                       'retained_ref_alleles_verified': True, 'uncompressed': identity(target)})
    record = {'kind': 'cloud_bqsr_preparation', 'reference_id': ref['reference_id'],
              'source_contract_sha256': digest_json(spec), 'benchmark_truth_used': False,
              'sources': [identity(by_name[r['filename']]) for r in spec], 'audits': audits}
    (output / 'contigs.txt').write_text(','.join(r['name'] for r in ref['contigs']) + '\n')
    (output / 'filtered-inputs.sha256').write_text(''.join(
        f"{a['uncompressed']['sha256']}  {a['uncompressed']['filename']}\n" for a in audits))
    write_record(output / 'known-sites-preparation.json', record)
    return record


def records(path: Path) -> tuple[int, str]:
    """Independently recount/hash the complete BGZF record stream, excluding headers."""
    count = 0
    digest = hashlib.sha256()
    with gzip.open(path, 'rb') as stream:
        for line in stream:
            require(line.endswith(b'\n'), 'truncated known-sites derivative')
            if not line.startswith(b'#'):
                require(len(line.rstrip(b'\n').split(b'\t')) >= 8, 'malformed known-sites derivative')
                count += 1
                digest.update(line)
    return count, digest.hexdigest()


def accept(source: Path, output: Path) -> dict:
    """Bind validated native index/readback to audited input, then rehash output copies."""
    preparation = json.loads((source / 'known-sites-preparation.json').read_text())
    spec = load_assets()['known_sites']
    require(preparation['kind'] == 'cloud_bqsr_preparation'
            and preparation['reference_id'] == digest_json(load_assets()['reference_dictionary'])
            and preparation['source_contract_sha256'] == digest_json(spec)
            and preparation['benchmark_truth_used'] is False, 'known-sites preparation contract differs')
    selected = [r for r in spec if r['role'] == 'bqsr_known_sites']
    require([a['source_id'] for a in preparation['audits']] == [r['id'] for r in selected], 'known-sites audit inventory differs')
    require((source / 'filtered-inputs.sha256').read_text() == ''.join(
        f"{a['uncompressed']['sha256']}  {a['uncompressed']['filename']}\n" for a in preparation['audits']),
        'known-sites native filter input binding differs')
    require([p['filename'] for p in preparation['sources']] == [r['filename'] for r in spec]
            and all(p['bytes'] == r['bytes'] and re.fullmatch('[0-9a-f]{64}', p['sha256'])
                    for p, r in zip(preparation['sources'], spec)), 'known-sites source receipt differs')
    for name in ('compress', 'index'):
        require(re.search(r'(?m)^bcftools 1\.24(?:\s|$)', (source / (name + '.version.txt')).read_text()) is not None,
                'native BCFtools version differs')
    output.mkdir(parents=True, exist_ok=False)
    audits = []
    for audit, item in zip(preparation['audits'], selected):
        stem = item['id'] + '.no-alt.vcf'
        gz = source / (stem + '.gz')
        count, sha = records(gz)
        expected_source = next(p for p in preparation['sources'] if p['filename'] == item['filename'])
        require(audit['source'] == expected_source and audit['retained_ref_alleles_verified'] is True
                and type(audit['excluded_absent_reference_records']) is int
                and audit['excluded_absent_reference_records'] >= 0, 'known-sites source audit differs')
        require(type(audit['retained_records']) is int and count == audit['retained_records'] > 0
                and (source / (stem + '.count')).read_text().strip() == str(count), 'known-sites native record count differs')
        require(all((source / (stem + suffix)).read_text().split()[0] == sha
                    for suffix in ('.source-records.sha256', '.sequential.sha256', '.indexed.sha256')),
                'known-sites native record or index readback differs')
        files = [identity(gz), identity(Path(str(gz) + '.tbi'))]
        require(all(p['bytes'] > 0 for p in files), 'known-sites payload empty')
        for entry in files:
            copy_verified(source / entry['filename'], output / entry['filename'], entry)
        audits.append({k: v for k, v in audit.items() if k != 'uncompressed'} | {'files': files})
    record = {'schema_version': '1.0.0', 'kind': 'canonical_bqsr_asset',
              'reference_id': preparation['reference_id'], 'source_contract_sha256': digest_json(spec),
              'benchmark_truth_used': False, 'audits': audits, 'files': [f for a in audits for f in a['files']]}
    write_record(output / 'known-sites-manifest.json', record)
    write_record(output.parent / 'known-sites-validation.json', {
        'kind': 'native_known_sites_validation', 'canonical_result': False,
        'asset_manifest': identity(output / 'known-sites-manifest.json'),
        'task_output_copies_rehashed': True, 'durable_destination_rehashed': False,
        'native_record_index_readback_verified': True,
        'backend_task_image_binding_required': True,
        'preparation': identity(source / 'known-sites-preparation.json')})
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prep = sub.add_parser('prepare')
    prep.add_argument('--sources', nargs='+', type=Path, required=True)
    prep.add_argument('--reference', type=Path, required=True)
    prep.add_argument('--output', type=Path, required=True)
    done = sub.add_parser('accept')
    done.add_argument('--input', type=Path, required=True)
    done.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        # Existing canonical reference helpers deliberately require active /content.
        ref = Path('/content/known-sites-reference')
        shutil.copytree(args.reference, ref)
        prepare(args.sources, ref, args.output)
    else:
        accept(args.input, args.output)


if __name__ == '__main__':
    main()
