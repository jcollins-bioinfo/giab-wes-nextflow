"""Backend-independent, fail-closed inputs for direct-container cloud execution.

S3 ETags are never identities. The operator supplies a reviewed manifest SHA;
all staged bytes are rehashed before scientific work. This contract does not
turn unexecuted runtime or index qualification into successful evidence.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from .resources import config_path
from .m5 import require

ASSETS = {
    'fastq1': 'reads_1.fastq.gz', 'fastq2': 'reads_2.fastq.gz',
    'reference': 'reference.fa', 'reference_fai': 'reference.fa.fai', 'reference_dict': 'reference.dict',
    **{f'bwa_{suffix}': f'reference.fa.{suffix}' for suffix in ('amb', 'ann', 'bwt', 'pac', 'sa')},
    **{f'known_{name}{suffix}': f'bqsr_{source}.no-alt.vcf.gz' + ('.tbi' if suffix else '')
       for name, source in [('dbsnp', 'dbsnp138'), ('indels', 'known_indels'), ('mills', 'mills')]
       for suffix in ('', '_tbi')},
    'calling_full': 'R_call.bed', 'evaluation': 'evaluation.bed',
    'truth': 'truth.vcf.gz', 'truth_tbi': 'truth.vcf.gz.tbi', 'confidence': 'confidence.bed',
}
QUALIFICATIONS = ('reference', 'index', 'known_sites', 'runtime')


def tool_images() -> dict[str, str]:
    """Use the authoritative reviewed images; never pick a convenience tag."""
    result = {}
    for name in ('m3-tools.json', 'm4-tools.json', 'm5-tools.json'):
        result.update({key: value['image'] for key, value in json.loads(config_path(name).read_text())['tools'].items()})
    result['bwa'] = json.loads(config_path('canonical-assets.json').read_text())['aligner']['image']
    return {key: result[key] for key in ('bwa', 'samtools', 'gatk', 'deepvariant', 'bcftools', 'rtg')}


def validate_object(item: dict) -> str:
    require(set(item) == {'uri', 'sha256', 'bytes'}, 'object requires URI, whole-object SHA-256 and byte count')
    require(re.fullmatch('[0-9a-f]{64}', item['sha256']) is not None, 'invalid SHA-256; ETag is not accepted')
    require(type(item['bytes']) is int and item['bytes'] > 0, 'object byte count must be positive')
    uri = urlsplit(item['uri'])
    require(uri.scheme == 's3' and re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', uri.netloc) is not None,
            'cloud inputs must use explicit S3 object URIs')
    require(not uri.query and not uri.fragment and not uri.username and not uri.password, 'signed/query S3 URI forbidden')
    require(uri.path.startswith('/') and not any(x in ('', '.', '..') for x in uri.path[1:].split('/')), 'unsafe S3 object key')
    require(re.fullmatch(r'[A-Za-z0-9_./-]+', uri.path) is not None, 'unsafe S3 object key characters')
    return uri.path.rsplit('/', 1)[-1]


def validate_manifest(record: dict) -> dict:
    require(set(record) == {'schema_version', 'kind', 'repository_sha', 'sample', 'scope', 'assets', 'qualifications'}, 'unexpected cloud manifest fields')
    require(record['schema_version'] == '1.0.0' and record['kind'] == 'cloud_canonical_inputs', 'invalid cloud manifest kind/version')
    require(record['sample'] == 'HG001' and record['scope'] == 'hg001_chr20_22_coding', 'first cloud scope must remain HG001 chr20-22 coding')
    require(re.fullmatch('[0-9a-f]{40}', record['repository_sha']) is not None, 'full reviewed repository SHA required')
    require(set(record['assets']) == set(ASSETS) and set(record['qualifications']) == set(QUALIFICATIONS), 'incomplete or unexpected scientific inventory')
    names = [validate_object(item) for group in ('assets', 'qualifications') for item in record[group].values()]
    require(len(names) == len(set(names)), 'input basenames must be unique for deterministic staging')
    return record


def cache_identity(record: dict, images: dict[str, str], parameters: dict) -> str:
    """Content key binds source, images, input/ref/domain identities and parameters."""
    validate_manifest(record)
    require(set(images) == set(tool_images()) | {'support'}, 'complete immutable image inventory required')
    require(all(re.fullmatch(r'[^\s]+@sha256:[0-9a-f]{64}', value) for value in images.values()), 'immutable image digests required')
    payload = {'manifest': record, 'images': images, 'parameters': parameters}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def load_manifest(path: Path, expected_sha256: str) -> dict:
    require(re.fullmatch('[0-9a-f]{64}', expected_sha256) is not None, 'reviewed manifest SHA-256 required')
    require(hashlib.sha256(path.read_bytes()).hexdigest() == expected_sha256, 'cloud manifest pin mismatch')
    from .m5_manifest import read_manifest
    return validate_manifest(read_manifest(path))
