"""Prepare, qualify, hydrate and publish immutable canonical reference assets.

Execution remains unqualified until the supplied pinned runtime actually builds
and probes the full index. Publication copies only validated payloads, rehashes
Drive bytes, appends a registry record, and writes the completion marker last.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tarfile
from typing import Any

from .acquisition import acquire, checksum, destination, lock, safe_root, validate_run_id, validate_source_bytes, write_record
from .canonical_host import memory_limits
from .canonical_asset_reference import (Runner, active, digest_json, identity, load_assets, prepare_known_sites,
                                        prepare_reference, reference_slice, regular, scan_reference, validate_reference)

__all__ = ['prepare_reference', 'prepare_known_sites', 'build_index', 'acquire_known_sites',
           'publish_assets', 'hydrate_assets', 'validate_asset', 'copy_verified', 'identity',
           'asset_contract_sha256', 'extract_archive']

INDEX_SUFFIXES = ('amb', 'ann', 'bwt', 'pac', 'sa')
DRIVE_ROOT = '/content/drive/MyDrive/giab-wes-nextflow-private'
MANIFESTS = {'canonical_reference_asset': 'reference-manifest.json', 'canonical_bwa_index_asset': 'index-manifest.json',
             'canonical_bqsr_asset': 'known-sites-manifest.json'}


def copy_verified(source: Path, target: Path, expected: dict[str, Any]) -> None:
    """Serialize copies and rehash destination bytes before atomic promotion."""
    source = regular(source)
    target = destination(target.parent, target.name)
    target.parent.mkdir(parents=True, exist_ok=True)
    with lock(Path(str(target) + '.lock')):
        if target.exists():
            if identity(target) != {**expected, 'filename': target.name}:
                raise ValueError('existing asset destination is corrupt or different')
            return
        partial = destination(target.parent, target.name + '.incomplete')
        with source.open('rb') as stream, partial.open('wb') as out:
            shutil.copyfileobj(stream, out, 8 << 20)
            out.flush()
            os.fsync(out.fileno())
        if identity(partial) != {**expected, 'filename': partial.name}:
            raise ValueError('asset copy rehash failed')
        os.replace(partial, target)


def asset_contract_sha256(kind: str) -> str:
    """Bind registry discovery to current reference, method and source/tool contracts."""
    spec = load_assets()
    if kind not in MANIFESTS:
        raise ValueError('unknown asset kind')
    contract = {'kind': kind, 'asset_schema_version': '1.0.0', 'reference_dictionary': spec['reference_dictionary']}
    if kind == 'canonical_bwa_index_asset':
        contract['aligner'] = spec['aligner']
        contract['probe_method'] = 'fixed_context_exact_reads_v1'
    elif kind == 'canonical_bqsr_asset':
        contract['known_sites'] = spec['known_sites']
        contract['method'] = 'exclude_absent_contigs_verify_all_retained_ref_v1'
    return digest_json(contract)


def acquire_known_sites(scratch: Path, drive_root: Path, *, allow_large_downloads: bool) -> dict[str, Path]:
    """Hydrate verified independent BQSR sources first; resume only declared missing bytes."""
    scratch, drive = active(scratch), safe_root(drive_root)
    scratch.mkdir(parents=True, exist_ok=True)
    if str(drive) != DRIVE_ROOT:
        raise ValueError('canonical Drive root must be the authorized project folder')
    selected = load_assets()['known_sites']
    required = sum(r['bytes'] for r in selected)
    if shutil.disk_usage(scratch).free < required * 3 or shutil.disk_usage(drive).free < required:
        raise ValueError('insufficient source/derivative scratch or reported Drive space')
    result: dict[str, Path] = {}
    for resource in selected:
        local = destination(scratch, resource['destination'])
        cached = destination(drive, f"cache/verified-sources/canonical-bqsr/{resource['checksum']['expected']}/{resource['filename']}")
        if cached.exists():
            validate_source_bytes(regular(cached), resource)
            copy_verified(cached, local, identity(cached))
        elif not allow_large_downloads:
            try:
                validate_source_bytes(regular(local), resource)
            except (ValueError, OSError):
                raise PermissionError('large source downloads are disabled; verified cache absent') from None
        observed = acquire(resource, scratch)
        validate_source_bytes(local, resource, observed)
        copy_verified(local, cached, identity(local))
        write_record(destination(drive, f"registry/assets/sources/{resource['id']}-{observed['sha256']}.json"),
                     {'schema_version': '1.0.0', 'source_contract': resource, 'file': identity(local)})
        result[resource['id']] = local
    return result


def extract_archive(archive: Path, output: Path, expected: dict[str, dict[str, Any]], *, maximum_bytes: int) -> list[dict[str, Any]]:
    """Extract an exact declared inventory; reject links, sparse files and unsafe names.

    This is a utility for separately authenticated archives. A successful safe
    extraction does not qualify the optional Hartwig index or its producer.
    """
    output = active(output)
    output.mkdir(parents=True, exist_ok=True)
    names: set[str] = set()
    directories: set[str] = set()
    parents = {str(parent) for name in expected for parent in Path(name).parents if str(parent) != '.'}
    total = 0
    with tarfile.open(regular(archive), 'r:*') as source:
        for member in source:
            target = destination(output, member.name)
            if member.isdir():
                name = member.name.rstrip('/')
                if name not in parents or name in directories:
                    raise ValueError('archive has unexpected or repeated directory')
                directories.add(name)
                continue
            if not member.isfile() or member.issparse() or member.name not in expected or member.name in names:
                raise ValueError('archive has unexpected, repeated or nonregular member')
            total += member.size
            if total > maximum_bytes or member.size != expected[member.name]['bytes']:
                raise ValueError('archive expanded-size contract differs')
            names.add(member.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            stream = source.extractfile(member)
            if stream is None:
                raise ValueError('archive member cannot be read')
            with stream, target.open('xb') as out:
                shutil.copyfileobj(stream, out, 1 << 20)
            if checksum(target) != expected[member.name]['sha256']:
                raise ValueError('archive member SHA-256 differs')
    if names != set(expected):
        raise ValueError('archive inventory incomplete')
    return [identity(output / name) for name in sorted(names)]


def _probes(directory: Path, runner: Runner) -> dict[str, Any]:
    """Align frozen exact reads in both orientations across chromosomes and contexts.

    Probe presence at the known generating locus is required even when repeats
    also align elsewhere. This sampled test never substitutes for full MD5s.
    """
    rows = {r['name']: r for r in scan_reference(directory / 'reference.fa')}
    wanted = ('chr1', 'chr2', 'chr20', 'chr21', 'chr22', 'chrX')
    if not set(wanted) <= set(rows):
        raise ValueError('full canonical reference lacks probe chromosomes')
    probes = []
    private = active(directory / '_probe_work')
    private.mkdir(parents=True, exist_ok=True)
    fq = private / 'index-probes.fastq'
    with (directory / 'reference.fa').open('rb') as fasta, fq.open('w') as out:
        for name in wanted:
            row = rows[name]
            for category in ('ordinary', 'high_gc', 'homopolymer_flank'):
                found = None
                start = row['length'] // 3
                window = reference_slice(fasta, row, start, min(2_000_000, row['length'] - start))
                for offset in range(0, len(window) - 151, 31):
                    sequence = window[offset:offset + 151]
                    if re.fullmatch('[ACGT]+', sequence) is None:
                        continue
                    gc = (sequence.count('G') + sequence.count('C')) / 151
                    if category == 'high_gc' and gc < .65:
                        continue
                    if category == 'homopolymer_flank' and not re.search(r'(A{6}|C{6}|G{6}|T{6})', sequence):
                        continue
                    if len(set(sequence[i:i + 15] for i in range(137))) < 110:
                        continue
                    found = (start + offset + 1, sequence)
                    break
                if found is None:
                    raise ValueError('predeclared index probe context unavailable')
                pos, sequence = found
                for reverse in (False, True):
                    query = sequence.translate(str.maketrans('ACGT', 'TGCA'))[::-1] if reverse else sequence
                    qname = f'probe{len(probes):03d}'
                    out.write(f'@{qname}\n{query}\n+\n' + 'I' * 151 + '\n')
                    probes.append({'name': qname, 'contig': name, 'position': pos, 'reverse': reverse, 'context': category,
                                   'read_sha256': hashlib.sha256(query.encode()).hexdigest()})
    sam = runner('bwa', ['mem', '-a', '-T', '0', '-t', '1', 'reference.fa', str(fq.relative_to(directory))], directory)
    matched = set()
    by_name = {p['name']: p for p in probes}
    for line in sam.splitlines():
        if not line or line.startswith('@'):
            continue
        f = line.split('\t')
        if len(f) < 11 or f[0] not in by_name:
            raise ValueError('malformed or unexpected functional probe alignment')
        p = by_name[f[0]]
        if f[2] == p['contig'] and int(f[3]) == p['position'] and f[5] == '151M' and bool(int(f[1]) & 16) == p['reverse'] and not int(f[1]) & 4:
            matched.add(f[0])
    if matched != set(by_name):
        raise ValueError('full-reference index failed predeclared functional probe loci')
    return {'method': 'fixed_context_exact_reads_v1', 'sampled_only': True, 'reads': probes,
            'all_expected_loci_observed': True, 'sam_sha256': hashlib.sha256(sam.encode()).hexdigest()}


def build_index(reference_dir: Path, output: Path, runner: Runner) -> dict[str, Any]:
    """Build classic BWA bwtsw on the full reference, preserving historical M3 MEM2 evidence."""
    reference = validate_reference(reference_dir)
    output = active(output)
    output.mkdir(parents=True, exist_ok=True)
    manifest = output / 'index-manifest.json'
    if manifest.exists():
        return validate_asset(output, 'canonical_bwa_index_asset')
    ceiling = memory_limits()['effective_ceiling_bytes']
    if ceiling is None or ceiling < 16 * 1024 ** 3 or shutil.disk_usage(output).free < 35 * 1024 ** 3:
        raise ValueError('classic full-reference index requires measured >=16GiB RAM and >=35GiB free scratch')
    for name in ('reference.fa', 'reference.fa.fai', 'reference.dict', 'reference-manifest.json'):
        copy_verified(reference_dir / name, output / name, identity(reference_dir / name))
    version = runner('bwa', [], output)
    if re.findall(r'(?m)^Version: (\S+)\s*$', version) != ['0.7.17-r1188']:
        raise ValueError('classic BWA executable identity differs from pinned release')
    runner('bwa', ['index', '-a', 'bwtsw', 'reference.fa'], output)
    names = ['reference.fa.' + suffix for suffix in INDEX_SUFFIXES]
    files = [identity(output / name) for name in names]
    if any(item['bytes'] <= 0 for item in files):
        raise ValueError('incomplete classic BWA index')
    annotation = (output / 'reference.fa.ann').read_text().splitlines()[0].split()
    if list(map(int, annotation[:2])) != [sum(r['length'] for r in reference['contigs']), len(reference['contigs'])]:
        raise ValueError('BWA annotation reference size/contig identity differs')
    probes = _probes(output, runner)
    if validate_reference(output) != reference:
        raise ValueError('reference changed during index construction')
    record = {'schema_version': '1.0.0', 'kind': 'canonical_bwa_index_asset', 'reference_id': reference['reference_id'],
              'reference': reference, 'tool': load_assets()['aligner'], 'observed_version_text': version,
              'construction': {'algorithm': 'bwtsw', 'complete_reference': True, 'command': ['bwa', 'index', '-a', 'bwtsw', 'reference.fa']},
              'functional_probes': probes, 'complete_base_identity': True, 'status': 'index_qualified',
              'files': reference['files'] + [identity(output / 'reference-manifest.json')] + files}
    write_record(manifest, record)
    return validate_asset(output, record['kind'])


def validate_asset(directory: Path, kind: str) -> dict[str, Any]:
    """Rehash the complete fixed payload inventory before reuse or publication."""
    directory = active(directory)
    if kind not in MANIFESTS:
        raise ValueError('unknown asset kind')
    record = json.loads(regular(directory / MANIFESTS[kind]).read_text())
    if record.get('kind') != kind or record.get('schema_version') != '1.0.0':
        raise ValueError('asset manifest identity mismatch')
    if kind == 'canonical_reference_asset':
        return validate_reference(directory)
    expected = ({'reference.fa', 'reference.fa.fai', 'reference.dict', 'reference-manifest.json'} | {'reference.fa.' + s for s in INDEX_SUFFIXES}
                if kind == 'canonical_bwa_index_asset' else {r['id'] + '.no-alt.vcf.gz' + suffix for r in load_assets()['known_sites'] if r['role'] == 'bqsr_known_sites' for suffix in ('', '.tbi')})
    files = record.get('files', [])
    if len(files) != len(expected) or {f['filename'] for f in files} != expected or files != [identity(destination(directory, f['filename'])) for f in files]:
        raise ValueError('asset payload inventory/bytes differ')
    if kind == 'canonical_bwa_index_asset':
        reference = validate_reference(directory)
        if record.get('reference') != reference or record.get('reference_id') != reference['reference_id'] or record.get('tool') != load_assets()['aligner'] or record.get('status') != 'index_qualified':
            raise ValueError('index reference/tool qualification differs')
        probes = record.get('functional_probes', {})
        reads = probes.get('reads', [])
        contexts = [(chrom, context, reverse) for chrom in ('chr1', 'chr2', 'chr20', 'chr21', 'chr22', 'chrX')
                    for context in ('ordinary', 'high_gc', 'homopolymer_flank') for reverse in (False, True)]
        if probes.get('method') != 'fixed_context_exact_reads_v1' or probes.get('all_expected_loci_observed') is not True or len(reads) != 36 or probes.get('sampled_only') is not True or re.fullmatch('[0-9a-f]{64}', probes.get('sam_sha256', '')) is None:
            raise ValueError('index lacks complete declared sampled probe evidence')
        lengths = {row['name']: row['length'] for row in reference['contigs']}
        for number, (read, context) in enumerate(zip(reads, contexts)):
            if (read.get('contig'), read.get('context'), read.get('reverse')) != context or read.get('name') != f'probe{number:03d}' or type(read.get('reverse')) is not bool or type(read.get('position')) is not int or not 1 <= read['position'] <= lengths[read['contig']] - 150 or re.fullmatch('[0-9a-f]{64}', read.get('read_sha256', '')) is None or set(read) != {'name', 'contig', 'position', 'reverse', 'context', 'read_sha256'}:
                raise ValueError('index sampled probe inventory differs')
        if record.get('complete_base_identity') is not True or re.findall(r'(?m)^Version: (\S+)\s*$', record.get('observed_version_text', '')) != [load_assets()['aligner']['expected_reported_version']] or record.get('construction') != {'algorithm': 'bwtsw', 'complete_reference': True, 'command': ['bwa', 'index', '-a', 'bwtsw', 'reference.fa']}:
            raise ValueError('index executable/construction identity differs')
    else:
        spec = load_assets()['known_sites']
        source_ids = [r['id'] for r in spec if r['role'] == 'bqsr_known_sites']
        audits = record.get('audits', [])
        if record.get('reference_id') != digest_json(load_assets()['reference_dictionary']) or record.get('source_contract_sha256') != digest_json(spec) or record.get('benchmark_truth_used') is not False or [a.get('source_id') for a in audits] != source_ids:
            raise ValueError('BQSR resource contract differs')
        for audit in audits:
            source = next(r for r in spec if r['id'] == audit['source_id'])
            source_file = audit.get('source', {})
            if source_file.get('filename') != source['filename'] or source_file.get('bytes') != source['bytes'] or re.fullmatch('[0-9a-f]{64}', source_file.get('sha256', '')) is None or audit.get('retained_ref_alleles_verified') is not True or type(audit.get('retained_records')) is not int or audit['retained_records'] <= 0 or type(audit.get('excluded_absent_reference_records')) is not int or audit['excluded_absent_reference_records'] < 0:
                raise ValueError('BQSR source/audit evidence differs')
        if [f for a in audits for f in a.get('files', [])] != files:
            raise ValueError('BQSR audit output identities differ')
    return record


def publish_assets(stage: Path, drive_root: Path, run_id: str, repository_sha: str, *, kind: str) -> Path:
    """Publish fixed payloads by content identity; registry precedes completion marker."""
    record = validate_asset(stage, kind)
    drive = safe_root(drive_root)
    validate_run_id(run_id)
    if str(drive) != DRIVE_ROOT or re.fullmatch('[0-9a-f]{40}', repository_sha) is None:
        raise ValueError('unapproved durable root or repository identity')
    asset_id = digest_json(record)
    target = destination(drive, f"cache/reference-assets/sha256/{record['reference_id']}/{asset_id}")
    target.mkdir(parents=True, exist_ok=True)
    with lock(destination(target, '.publication.lock')):
        files = record['files'] + [identity(stage / MANIFESTS[kind])]
        for item in files:
            copy_verified(stage / item['filename'], destination(target, item['filename']), item)
        expected = {f['filename'] for f in files}
        present = {p.name for p in target.iterdir()} - {'.publication.lock', 'COMPLETED.json'}
        if present != expected or any(identity(target / f['filename']) != f for f in files):
            raise ValueError('durable asset complete inventory/rehash failed')
        observation = {'schema_version': '1.0.0', 'kind': kind, 'reference_id': record['reference_id'], 'asset_id': asset_id,
                       'repository_sha': repository_sha, 'run_id': run_id, 'files': files, 'destination_rehashed': True,
                       'asset_contract_sha256': asset_contract_sha256(kind)}
        registry = destination(drive, f'registry/assets/{run_id}/{asset_id}.json')
        write_record(registry, observation)
        marker = {'schema_version': '1.0.0', 'asset_id': asset_id, 'manifest_sha256': checksum(stage / MANIFESTS[kind]), 'files': files}
        write_record(destination(target, 'COMPLETED.json'), marker)
    return target


def hydrate_assets(drive_root: Path, reference_id: str, asset_id: str, output: Path, *, kind: str) -> dict[str, Any]:
    """Require marker/hash identities, rehash durable bytes, then qualify the local copy."""
    drive = safe_root(drive_root)
    if str(drive) != DRIVE_ROOT or any(re.fullmatch('[0-9a-f]{64}', x) is None for x in (reference_id, asset_id)) or kind not in MANIFESTS:
        raise ValueError('invalid durable asset identity')
    source = destination(drive, f'cache/reference-assets/sha256/{reference_id}/{asset_id}')
    marker = json.loads(regular(source / 'COMPLETED.json').read_text())
    manifest = regular(source / MANIFESTS[kind])
    record = json.loads(manifest.read_text())
    if marker.get('asset_id') != asset_id or record.get('reference_id') != reference_id or digest_json(record) != asset_id or marker.get('manifest_sha256') != checksum(manifest):
        raise ValueError('durable asset completion marker mismatch')
    files = record['files'] + [identity(manifest)]
    if marker.get('files') != files or {p.name for p in source.iterdir()} != {f['filename'] for f in files} | {'COMPLETED.json'}:
        raise ValueError('durable asset inventory differs')
    output = active(output)
    output.mkdir(parents=True, exist_ok=True)
    for item in files:
        copy_verified(source / item['filename'], destination(output, item['filename']), item)
    return validate_asset(output, kind)


def main() -> None:
    """Expose reference and read-only asset validation to the thin Colab launcher."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    reference = commands.add_parser('reference')
    reference.add_argument('--source-gz', type=Path, required=True)
    reference.add_argument('--source-fai', type=Path, required=True)
    reference.add_argument('--output', type=Path, required=True)
    validate = commands.add_parser('validate')
    validate.add_argument('--directory', type=Path, required=True)
    validate.add_argument('--kind', choices=MANIFESTS, required=True)
    args = parser.parse_args()
    result = prepare_reference(args.source_gz, args.source_fai, args.output) if args.command == 'reference' else validate_asset(args.directory, args.kind)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
