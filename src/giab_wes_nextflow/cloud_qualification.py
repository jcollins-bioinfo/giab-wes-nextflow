"""Strictly invented inputs for executing the actual cloud scientific DAG.

HG001 and chr20/chr21 are interface labels only in this separately typed recipe.
All bases and qualities derive from the frozen nonhuman M4 fixture. Its manifest
cannot pass the canonical cloud entrypoint's sample/scope/kind contract.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

from .canonical_science import file_id, write_json
from .cloud_contract import ASSETS
from .m3 import read_pairs
from .m3_fixture import _gzip
from .m4_fixture import fixture_payloads
from .m5 import require
from .m5_fixture import header, write_reference

RECIPE = 'cloud-m4-v1'
KIND = 'cloud_nonhuman_qualification_inputs'
AUTH_KIND = 'cloud_nonhuman_qualification_authentication'
RENAME = {'chrSYN1': 'chr20', 'chrSYN2': 'chr21'}


def generate(output: Path) -> dict:
    """Relabel fixed invented reference and concatenate original fixture lanes."""
    output.mkdir(parents=True, exist_ok=False)
    payloads, expected = fixture_payloads()
    seqs = {}
    name = None
    for line in payloads['reference.fa'].decode().splitlines():
        if line.startswith('>'):
            name = RENAME[line[1:]]
            seqs[name] = ''
        else:
            seqs[name] += line
    write_reference(output, seqs)
    for mate in (1, 2):
        data = b''.join(gzip.decompress(payloads[name]) for name in
                        (f'reads_{mate}.fastq.gz', f'reads_lane2_{mate}.fastq.gz'))
        (output / f'reads_{mate}.fastq.gz').write_bytes(_gzip(data))
    known = payloads['known-sites.vcf'].decode()
    for old, new in RENAME.items():
        known = known.replace(old, new)
    (output / 'known-sites.vcf').write_text(known)
    sites = [{**site, 'contig': RENAME[site['contig']]} for site in expected['variant_sites']]
    (output / 'truth.vcf').write_text(header(seqs, 'HG001') + ''.join(
        f"{s['contig']}\t{s['position_1based']}\t.\t{s['ref']}\t{s['alt']}\t60\tPASS\t.\tGT\t{s['genotype']}\n" for s in sites))
    domain = ''.join(f'{name}\t0\t{len(sequence)}\n' for name, sequence in seqs.items())
    for name in ('R_call.bed', 'evaluation.bed', 'confidence.bed'):
        (output / name).write_text(domain)
    frozen = {'recipe': RECIPE, 'synthetic': True, 'canonical': False,
              'human_interface_sample_label': 'HG001', 'primary_read_count': expected['primary_read_count'],
              'variant_sites': sites, 'read_expectations': expected['read_expectations'],
              'domain': {'id': 'nonhuman_cloud_dag', 'evaluated_bases': 20000, 'interval_count': 2,
                         'sha256': hashlib.sha256(domain.encode()).hexdigest()}}
    write_json(output / 'fixture-expectations.json', frozen)
    return frozen


def make_manifest(prepared: Path, output: Path, repository_sha: str) -> dict:
    """Inventory actual native miniature indexes; never accept external fixture bytes."""
    require(re.fullmatch('[0-9a-f]{40}', repository_sha) is not None, 'exact repository SHA required')
    output.mkdir(parents=True, exist_ok=False)
    inputs = output / 'inputs'
    inputs.mkdir()
    # Canonical S3 names are irrelevant here: this separately typed manifest is
    # consumed through explicitly staged files by the qualification entrypoint.
    selected = set(ASSETS.values()) | {'fixture-expectations.json', 'known-sites.vcf', 'truth.vcf'}
    for name in sorted(selected):
        shutil.copyfile(prepared / name, inputs / name)
    manifest = {'schema_version': '1.0.0', 'kind': KIND, 'recipe': RECIPE,
                'synthetic': True, 'canonical': False, 'scope': 'nonhuman',
                'repository_sha': repository_sha, 'sample': 'HG001',
                'files': {p.name: file_id(p) for p in sorted(inputs.iterdir())}}
    write_json(output / 'manifest.json', manifest)
    (output / 'manifest.sha256').write_text(file_id(output / 'manifest.json')['sha256'] + '\n')
    return manifest


def _records(path: Path) -> list[str]:
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt') as stream:
        return [line for line in stream if not line.startswith('#')]


def authenticate(manifest: Path, expected: str, inputs: Path, output: Path, backend: str) -> dict:
    """Regenerate every non-index input; a self-rehashed manifest is insufficient."""
    require(file_id(manifest)['sha256'] == expected, 'qualification manifest SHA differs')
    record = json.loads(manifest.read_text())
    require(set(record) == {'schema_version', 'kind', 'recipe', 'synthetic', 'canonical', 'scope', 'repository_sha', 'sample', 'files'}
            and record['kind'] == KIND and record['recipe'] == RECIPE and record['schema_version'] == '1.0.0'
            and record['synthetic'] is True and record['canonical'] is False
            and record['scope'] == 'nonhuman' and record['sample'] == 'HG001'
            and re.fullmatch('[0-9a-f]{40}', record['repository_sha']) is not None, 'unregistered nonhuman qualification recipe')
    inventory = set(ASSETS.values()) | {'fixture-expectations.json', 'known-sites.vcf', 'truth.vcf'}
    require(set(record['files']) == inventory and {p.name for p in inputs.iterdir()} == inventory,
            'qualification file inventory differs')
    require(sum(item['bytes'] for item in record['files'].values()) < 5_000_000, 'qualification exceeds nonhuman byte ceiling')
    for name, identity in record['files'].items():
        require(file_id(inputs / name) == identity, 'qualification staged file identity differs')
    with tempfile.TemporaryDirectory(prefix='cloud-fixture-') as scratch:
        frozen_root = Path(scratch) / 'fixture'
        frozen = generate(frozen_root)
        for path in frozen_root.iterdir():
            require(file_id(path) == file_id(inputs / path.name), 'qualification bytes differ from frozen nonhuman recipe')
        for name in ('truth.vcf.gz', 'bqsr_dbsnp138.no-alt.vcf.gz', 'bqsr_known_indels.no-alt.vcf.gz', 'bqsr_mills.no-alt.vcf.gz'):
            original = frozen_root / ('truth.vcf' if name == 'truth.vcf.gz' else 'known-sites.vcf')
            require(_records(inputs / name) == _records(original), 'qualification native compression changed records')
    # Actual native index/record access is exercised by the downstream BWA/GATK/
    # BCFtools processes. These tiny indexes never qualify complete GRCh38 assets.
    annotation = (inputs / 'reference.fa.ann').read_text().splitlines()[0].split()
    require(list(map(int, annotation[:2])) == [20000, 2], 'qualification BWA dictionary differs')
    roots = {key: output / key for key in ('reads', 'reference', 'index', 'known', 'domain', 'truth')}
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=False)
    for role, name in ASSETS.items():
        category = ('reads' if role.startswith('fastq') else 'known' if role.startswith('known_')
                    else 'domain' if role == 'calling_full' else 'truth' if role in ('evaluation', 'truth', 'truth_tbi', 'confidence') else 'index')
        shutil.copyfile(inputs / name, roots[category] / name)
    for name in ('reference.fa', 'reference.fa.fai', 'reference.dict'):
        shutil.copyfile(inputs / name, roots['reference'] / name)
    shutil.copyfile(inputs / 'R_call.bed', roots['domain'] / 'regions.bed')
    pairs = sum(1 for _ in read_pairs(roots['reads'] / 'reads_1.fastq.gz', roots['reads'] / 'reads_2.fastq.gz'))
    require(pairs * 2 == frozen['primary_read_count'], 'qualification FASTQ read count differs')
    receipt = {'kind': AUTH_KIND, 'status': 'passed', 'synthetic': True, 'canonical': False,
               'recipe': RECIPE, 'repository_sha': record['repository_sha'], 'backend': backend,
               'manifest_sha256': expected, 'domain': frozen['domain'], 'fastq_pairs': pairs,
               'reference_outputs': {name: file_id(roots['reference'] / name) for name in ('reference.fa', 'reference.fa.fai', 'reference.dict')},
               'calling_regions': file_id(roots['domain'] / 'regions.bed'), 'fixture_expectations': frozen}
    write_json(output / 'authentication.json', receipt)
    return receipt


def validate_original_qualities(directory: Path, receipt: dict) -> int:
    """Require exact original qualities on every primary invented read, including unmapped."""
    require(receipt.get('kind') == AUTH_KIND and receipt.get('recipe') == RECIPE, 'qualification OQ context differs')
    expected = receipt['fixture_expectations']['read_expectations']
    seen = set()
    for line in (directory / 'records.sam').read_text().splitlines():
        fields = line.split('\t')
        flag = int(fields[1])
        if flag & 2304:
            continue
        name = fields[0] + ('/1' if flag & 64 else '/2')
        require(name in expected and name not in seen, 'unknown or duplicate qualification primary read')
        original = expected[name]['original_qualities']
        if flag & 16:
            original = original[::-1]
        tags = {f.split(':', 2)[0]: f.split(':', 2)[2] for f in fields[11:]}
        require(tags.get('OQ') == original, 'qualification original OQ identity differs')
        seen.add(name)
    require(seen == set(expected), 'qualification original read inventory incomplete')
    return len(seen)


def accept(source: Path, output: Path) -> dict:
    """Validate actual shared lineage and frozen counts after the entire cloud DAG."""
    data = json.loads(source.read_text())
    auth = data['authentication']
    require(data.get('canonical') is False and data.get('synthetic') is True and auth.get('kind') == AUTH_KIND
            and auth.get('recipe') == RECIPE and auth.get('canonical') is False, 'full DAG nonhuman context differs')
    with tempfile.TemporaryDirectory(prefix='cloud-oracle-') as tmp:
        frozen = generate(Path(tmp) / 'fixture')
    require(data['domain'] == auth['domain'] == frozen['domain'], 'qualification denominator differs')
    require(data['shared']['original_quality_records_verified'] == frozen['primary_read_count'], 'qualification original OQ gate missing')
    require(set(data['callers']) == {'gatk', 'deepvariant'}, 'qualification caller inventory incomplete')
    for caller in data['callers'].values():
        for variant, expected in [('SNP', (2, 2, 0, 0)), ('INDEL', (0, 0, 0, 0)), ('OTHER', (0, 0, 0, 0))]:
            row = caller['metrics'][variant]
            require(tuple(row[key] for key in ('tp_query', 'tp_truth', 'fp', 'fn')) == expected,
                    'full DAG frozen genotype-aware counts differ')
    receipt = {'kind': 'managed_cloud_dag_qualification', 'status': 'passed', 'synthetic': True, 'canonical': False,
               'recipe': RECIPE, 'scientific_dag_acceptance': True, 'backend_receipt_binding_required': True,
               'full_cloud_workflow_qualified': False, 'managed_cache_qualified': False,
               'source_evidence': file_id(source), 'domain': frozen['domain'], 'repository_sha': auth['repository_sha']}
    write_json(output, receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('generate', 'manifest', 'accept'))
    parser.add_argument('--input', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--repository-sha')
    args = parser.parse_args()
    if args.command == 'generate':
        generate(args.output)
    elif args.command == 'manifest':
        make_manifest(args.input, args.output, args.repository_sha)
    else:
        accept(args.input, args.output)


if __name__ == '__main__':
    main()
