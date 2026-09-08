"""Validate public canonical evidence and export observations outside UI callbacks.

Trust begins with an independently reviewed manifest SHA supplied by the caller.
A self-hashed bundle cannot attest to execution; receipts and schema validation
make the declared evidence inspectable without promoting synthetic observations.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
import re
from typing import Any

from jsonschema import Draft202012Validator
from .m4_contracts import load_json
from .m5 import metrics, require
from .resources import schema_path

REQUIRED_LIMITATIONS = (
    'One HG001 sample and one execution do not establish population generalization or universal caller superiority.',
    'DeepVariant WES training included HG001; chr20–22 is same-individual locus-held-out sensitivity.',
    'These research results do not establish clinical validity or production validation.',
)
DOMAINS = {
    'hg001_chr20_22_coding': {'id': 'R_eval_holdout', 'sha256': '7730c4303e03fef74d2c22193102845e369e04ac81fabb7f41fae1374be65d00',
        'bases': 1905809, 'interval_count': 11715, 'contigs': ['chr20', 'chr21', 'chr22']},
    'hg001_full_coding': {'id': 'R_eval_full', 'sha256': '9c270a2c46c2e83ae0d35e5ceaa75e4b77918924bf7443d4fffe467cd9b950d4',
        'bases': 33567783, 'interval_count': 203986, 'contigs': [f'chr{x}' for x in range(1, 23)]},
}
QUALIFICATION_ROLES = ('sources', 'reference', 'index', 'domain', 'runtime', 'preprocessing', 'gatk', 'deepvariant', 'benchmark', 'resume')
MAX_BYTES = 100_000


def safe_metadata(value: Any) -> None:
    """Reject private paths, credentials, signed URLs and long sequence strings."""
    if isinstance(value, dict):
        for key, item in value.items():
            require(re.fullmatch(r'(?:access_token|refresh_token|password|secret|authorization|api_key)', key, re.I) is None,
                    'credential-shaped public metadata key')
            safe_metadata(key); safe_metadata(item)
    elif isinstance(value, list):
        for item in value:
            safe_metadata(item)
    elif isinstance(value, str):
        require(not any(x in value for x in ('DO NOT ACCESS WITH CHATGPT', '/Users/', '/home/', '/content/drive/')),
                'private path in public metadata')
        require(re.search(r'[?&](?:sig|signature|token|X-Amz-Signature|X-Goog-Signature)=', value, re.I) is None,
                'signed URL in public metadata')
        require(re.search(r'(?<![A-Za-z])[ACGTNacgtn]{80,}(?![A-Za-z])', value) is None,
                'sequence bytes in public metadata')


def validate_result(record: dict[str, Any]) -> None:
    """Check the closed canonical result, exact domain, symmetry and arithmetic."""
    Draft202012Validator(load_json(schema_path('canonical-results.schema.json'))).validate(record)
    safe_metadata(record)
    require(record['domain'] == DOMAINS[record['scope']], 'canonical domain differs from approved identity')
    require(set(REQUIRED_LIMITATIONS).issubset(record['limitations']), 'mandatory interpretation limits missing')
    for caller, quality in [('gatk', 'QUAL'), ('deepvariant', 'OQ')]:
        data = record['callers'][caller]
        require(data['quality_source'] == quality and data['shared_inputs'] == record['shared_inputs'],
                'physical input or effective quality policy mismatch')
        for row in data['metrics'].values():
            require(row == metrics(row['tp_query'], row['tp_truth'], row['fp'], row['fn']),
                    'canonical benchmark arithmetic or missingness mismatch')
    for group in record['resources'].values():
        missing = {key for key in ('wall_seconds', 'cpu_seconds', 'peak_rss_bytes') if group[key] is None}
        require(set(group['missing_reasons']) == missing and all(group['missing_reasons'].values()),
                'resource missingness mismatch')
    coverage = record['coverage']
    require((coverage is None) == (record['coverage_missing_reason'] is not None), 'coverage missingness mismatch')
    if coverage is not None:
        require(coverage['evaluated_bases'] == record['domain']['bases'] and coverage['covered_bases'] <= coverage['evaluated_bases'],
                'coverage denominator mismatch')


def _name(name: str) -> None:
    """Allow one flat, bounded public metadata filename with no path syntax."""
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*\.(?:json|tsv)', name) is not None and '..' not in name,
            'unsafe or nonmetadata public filename')


def _read(root: Path, name: str) -> bytes:
    """Read a regular bounded member without following symlink ancestors."""
    _name(name); p = root.absolute() / name
    require(not any(q.is_symlink() for q in (p, *p.parents)) and p.is_file(), 'linked or missing public evidence')
    require(p.stat().st_size <= MAX_BYTES, 'public evidence exceeds 100 KB limit')
    return p.read_bytes()


def _json(raw: bytes) -> dict[str, Any]:
    """Reject ambiguous duplicate keys and non-finite JSON numbers."""
    def unique(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate public JSON key'); result[key] = value
        return result
    def invalid(value: str) -> Any:
        raise ValueError('non-finite public JSON number')
    record = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)
    require(isinstance(record, dict), 'public JSON must be an object')
    return record


@dataclass(frozen=True)
class CanonicalResults:
    """Trusted canonical metadata and precomputed download representations."""
    record: dict[str, Any]
    manifest_sha256: str
    public_json: str
    metrics_tsv: str
    resources_tsv: str
    artifact_inventory: tuple[tuple[str, str], ...]


def export_metrics(record: dict[str, Any]) -> str:
    """Serialize validated canonical metrics with explicit blank missing cells."""
    validate_result(record); stream = io.StringIO(); writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
    fields = ['tp_query', 'tp_truth', 'fp', 'fn', 'precision', 'recall', 'f1']
    writer.writerow(['run_id', 'scope', 'caller', 'variant_type', *fields, 'missing_reasons'])
    for caller, result in record['callers'].items():
        for kind, row in result['metrics'].items():
            writer.writerow([record['run_id'], record['scope'], caller, kind, *[row[f] for f in fields], json.dumps(row['missing_reasons'], sort_keys=True)])
    return stream.getvalue()


def export_resources(record: dict[str, Any]) -> str:
    """Export observed resource quantities without summing wall times or peaks."""
    validate_result(record); stream = io.StringIO(); writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
    fields = ['wall_seconds', 'cpu_seconds', 'peak_rss_bytes']
    writer.writerow(['run_id', 'group', *fields, 'missing_reasons'])
    for group, row in record['resources'].items():
        writer.writerow([record['run_id'], group, *[row[f] for f in fields], json.dumps(row['missing_reasons'], sort_keys=True)])
    return stream.getvalue()


def load_canonical_bundle(directory: Path, expected_manifest_sha256: str) -> CanonicalResults:
    """Load exact public inventory only under an independently supplied manifest pin."""
    require(re.fullmatch('[0-9a-f]{64}', expected_manifest_sha256) is not None, 'trusted manifest SHA-256 required')
    raw = _read(directory, 'manifest.json')
    require(hashlib.sha256(raw).hexdigest() == expected_manifest_sha256, 'canonical manifest identity mismatch')
    manifest = _json(raw)
    require(set(manifest) == {'schema_version', 'kind', 'files'} and manifest['schema_version'] == '1.0.0'
            and manifest['kind'] == 'canonical_public_manifest' and isinstance(manifest['files'], dict), 'invalid public manifest')
    files = manifest['files']; require('result.json' in files and 'manifest.json' not in files and len(files) <= 64, 'invalid public inventory')
    require(set(p.name for p in directory.iterdir()) == set(files) | {'manifest.json'}, 'public directory differs from exact manifest')
    payloads = {}
    for name, item in files.items():
        data = _read(directory, name)
        require(set(item) == {'bytes', 'sha256'} and type(item['bytes']) is int and item['bytes'] == len(data)
                and item['sha256'] == hashlib.sha256(data).hexdigest(), 'public member hash or size mismatch')
        if name.endswith('.json'):
            safe_metadata(_json(data))
        else:
            safe_metadata(data.decode('utf-8'))
        payloads[name] = data
    result = _json(payloads['result.json']); validate_result(result)
    for role, receipt in result['qualification'].items():
        name = receipt['artifact']; require(name in payloads and name.endswith('.json') and name != 'result.json', 'missing qualification receipt')
        require(receipt['sha256'] == files[name]['sha256'], 'qualification receipt identity mismatch')
        value = _json(payloads[name])
        require(value.get('status') == 'passed' and value.get('kind') == role and value.get('run_id') == result['run_id'],
                'qualification receipt is not a passed gate for this run')
    for environment in result['environments']:
        require(environment['status'] != 'executed' or environment['evidence'] in payloads,
                'executed environment has no retained evidence')
    if result['coverage'] is not None:
        require(result['coverage']['artifact'] in payloads, 'coverage evidence absent')
    return CanonicalResults(result, expected_manifest_sha256, json.dumps(result, sort_keys=True, indent=2, allow_nan=False),
                            export_metrics(result), export_resources(result), tuple(sorted((name, item['sha256']) for name, item in files.items())))


def write_public_bundle(directory: Path, record: dict[str, Any], receipts: dict[str, dict[str, Any]]) -> str:
    """Write complete public metadata last; return its pin for external review.

    This writer validates declarations and receipts, not remote execution. The
    caller must provide actual completed-run evidence, never invented gates.
    """
    validate_result(record); require(not directory.exists(), 'public output directory must be fresh')
    directory.mkdir(parents=True)
    data = {'result.json': record, **receipts}; require('result.json' not in receipts and 'manifest.json' not in receipts, 'reserved public filename')
    inventory = {}
    for name, value in data.items():
        _name(name); safe_metadata(value); require(name.endswith('.json'), 'writer accepts JSON receipts only')
        raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode(); require(len(raw) <= MAX_BYTES, 'public member oversized')
        (directory / name).write_bytes(raw); inventory[name] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    manifest = {'schema_version': '1.0.0', 'kind': 'canonical_public_manifest', 'files': inventory}
    raw = (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode(); pin = hashlib.sha256(raw).hexdigest()
    (directory / 'manifest.json').write_bytes(raw)
    try:
        load_canonical_bundle(directory, pin)
    except Exception:
        (directory / 'manifest.json').unlink()
        raise
    return pin
