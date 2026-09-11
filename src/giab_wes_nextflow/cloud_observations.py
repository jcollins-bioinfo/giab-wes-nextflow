"""Read private observations produced inside native cloud scientific tasks.

Declared container references and Nextflow task IDs are not backend identities.
These records deliberately require a later join to provider task/image receipts.
"""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re

from .canonical_results import _json
from .canonical_science import file_id
from .cloud_public import PROCESSES
from .m4_contracts import _model_inventory
from .m5 import require
from .resources import config_path


def read_file_inventory(path: Path) -> dict:
    """Read native whole-file SHA-256/size observations; no genomic payloads."""
    result = {}
    for line in path.read_text().splitlines():
        parts = line.split('\t')
        require(len(parts) == 3, 'malformed native file observation')
        digest, size, name = parts
        require(re.fullmatch('[0-9a-f]{64}', digest) is not None and size.isdecimal() and int(size) >= 0,
                'invalid native whole-file identity')
        member = PurePosixPath(name)
        require(not member.is_absolute() and '..' not in member.parts and name not in result
                and re.fullmatch(r'[A-Za-z0-9_./-]+', name) is not None, 'unsafe or duplicate native artifact name')
        result[name] = {'sha256': digest, 'bytes': int(size)}
    require(bool(result), 'empty native file observation inventory')
    return result


def read_task_observation(directory: Path) -> dict:
    """Retain actual local observations without manufacturing cloud resource data."""
    require(directory.is_dir() and not any(p.is_symlink() for p in (directory, *directory.parents)), 'linked or missing task receipt')
    required = {'task.json', 'started.txt', 'completed.txt', 'command.sh', 'inputs.tsv', 'outputs.tsv', 'version.txt'}
    names = {p.name for p in directory.iterdir()}
    require(required.issubset(names) and names <= required | {'model-before.json', 'model-after.json'}, 'incomplete or unexpected native receipt members')
    for path in directory.iterdir():
        require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 2_000_000, 'unsafe native receipt member')
    meta = _json((directory / 'task.json').read_bytes())
    require(set(meta) == {'process', 'label', 'nextflow_task_id', 'attempt', 'declared_image', 'requested_cpus', 'requested_memory_bytes', 'architecture'},
            'native task metadata fields differ')
    require(meta['process'] in PROCESSES and re.fullmatch(r'[A-Za-z0-9_-]{1,40}', meta['label']) is not None,
            'unknown task process/label')
    require(type(meta['nextflow_task_id']) is int and meta['nextflow_task_id'] > 0 and type(meta['attempt']) is int and meta['attempt'] > 0,
            'Nextflow task identity missing')
    require(re.fullmatch(r'[^\s]+@sha256:[0-9a-f]{64}', meta['declared_image']) is not None, 'declared image must be immutable')
    require(meta['architecture'] == 'x86_64' and all(type(meta[k]) is int and meta[k] > 0 for k in ('requested_cpus', 'requested_memory_bytes')),
            'native architecture or requested resource observation invalid')
    times = [(directory / name).read_text().strip() for name in ('started.txt', 'completed.txt')]
    require(all(value.isdecimal() for value in times) and int(times[1]) >= int(times[0]), 'invalid native task timing')
    version = (directory / 'version.txt').read_text()
    require(bool(version.strip()), 'missing native tool version output')
    result = {'kind': 'cloud_task_observation', 'status': 'passed', 'backend_binding_required': True, **meta,
              'tool': PROCESSES[meta['process']][0], 'group': PROCESSES[meta['process']][1],
              'started_epoch_seconds': int(times[0]), 'completed_epoch_seconds': int(times[1]),
              'command': file_id(directory / 'command.sh'), 'version_output': {**file_id(directory / 'version.txt'), 'text': version},
              'inputs': read_file_inventory(directory / 'inputs.tsv'), 'outputs': read_file_inventory(directory / 'outputs.tsv'),
              'cpu_seconds': None, 'peak_rss_bytes': None,
              'missing_reasons': {'cpu_seconds': 'Not observed inside native task.', 'peak_rss_bytes': 'Not observed inside native task.'}}
    if meta['process'] == 'CLOUD_DEEPVARIANT_CALL':
        require({'model-before.json', 'model-after.json'}.issubset(names), 'native WES model observations missing')
        tool = json.loads(config_path('m4-tools.json').read_text())['tools']['deepvariant']
        before = _json((directory / 'model-before.json').read_bytes())
        after = _json((directory / 'model-after.json').read_bytes())
        require(_model_inventory(before, tool) == _model_inventory(after, tool), 'native WES model changed during calling')
        result.update(model_before=before, model_after=after)
    return result


def collect_task_observations(directories: list[Path], *, include_collector: bool = False) -> list[dict]:
    records = [read_task_observation(directory) for directory in directories]
    require(len({(r['nextflow_task_id'], r['attempt']) for r in records}) == len(records), 'duplicate native task attempt observation')
    require(len({(r['process'], r['label']) for r in records}) == len(records), 'duplicate native process/label observation')
    for process, (_, _, count) in PROCESSES.items():
        expected = count if include_collector or process != 'CLOUD_COLLECT' else 0
        require(sum(r['process'] == process for r in records) == expected, 'native task observation DAG incomplete')
    return records


def artifact(record: dict, group: str, filename: str) -> dict:
    found = [item for name, item in record[group].items() if PurePosixPath(name).name == filename]
    require(len(found) == 1, 'missing or ambiguous task artifact identity')
    return found[0]


def join_scientific_lineage(observations: list[dict], callers: dict, shared: dict) -> None:
    """Join actual native outputs through the complete common normalization chain."""
    by_task = {(r['process'], r['label']): r for r in observations}
    for caller in ('gatk', 'deepvariant'):
        call = by_task[('CLOUD_' + caller.upper() + '_CALL', caller)]
        normalize = by_task[('CLOUD_NORMALIZE', caller)]
        include = by_task[('CLOUD_INCLUDE', caller)]
        compress = by_task[('CLOUD_COMPRESS', caller)]
        benchmark = by_task[('CLOUD_VCFEVAL', caller)]
        for name, digest in shared.items():
            require(artifact(call, 'inputs', name)['sha256'] == digest, 'observed native caller shared-input lineage differs')
        require(artifact(call, 'outputs', 'raw.vcf.gz') == artifact(normalize, 'inputs', 'raw.vcf.gz'), 'caller to normalization lineage differs')
        require(artifact(normalize, 'outputs', 'sorted.vcf') == artifact(include, 'inputs', 'sorted.vcf'), 'normalization to inclusion lineage differs')
        require(artifact(include, 'outputs', 'included.vcf') == artifact(compress, 'inputs', 'included.vcf'), 'inclusion to compression lineage differs')
        require(artifact(compress, 'outputs', 'normalized.vcf.gz') == artifact(benchmark, 'inputs', 'query.vcf.gz'), 'normalized query to RTG lineage differs')
        require(artifact(compress, 'outputs', 'normalized.vcf.gz.tbi') == artifact(benchmark, 'inputs', 'query.vcf.gz.tbi'), 'normalized index to RTG lineage differs')
        for name, identity in callers[caller]['partitions'].items():
            require(artifact(benchmark, 'outputs', name) == identity, 'RTG to collector partition lineage differs')
        callers[caller].update(raw_vcf=artifact(call, 'outputs', 'raw.vcf.gz'), normalized_vcf=artifact(compress, 'outputs', 'normalized.vcf.gz'),
                               caller_nextflow_task_id=call['nextflow_task_id'], caller_attempt=call['attempt'],
                               benchmark_nextflow_task_id=benchmark['nextflow_task_id'], benchmark_attempt=benchmark['attempt'],
                               normalization_chain=[{'process': r['process'], 'nextflow_task_id': r['nextflow_task_id'], 'attempt': r['attempt'],
                                                     'command': r['command'], 'inputs': r['inputs'], 'outputs': r['outputs']} for r in (normalize, include, compress)])
        if caller == 'deepvariant':
            callers[caller].update(model_before=call['model_before'], model_after=call['model_after'])
    truth = by_task[('CLOUD_PREPARE_TRUTH', 'truth')]
    normalize = by_task[('CLOUD_NORMALIZE', 'truth')]
    include = by_task[('CLOUD_INCLUDE', 'truth')]
    compress = by_task[('CLOUD_COMPRESS', 'truth')]
    require(artifact(truth, 'outputs', 'raw.vcf.gz') == artifact(normalize, 'inputs', 'raw.vcf.gz')
            and artifact(normalize, 'outputs', 'sorted.vcf') == artifact(include, 'inputs', 'sorted.vcf')
            and artifact(include, 'outputs', 'included.vcf') == artifact(compress, 'inputs', 'included.vcf'), 'common truth normalization lineage differs')
    for caller in ('gatk', 'deepvariant'):
        benchmark = by_task[('CLOUD_VCFEVAL', caller)]
        require(artifact(compress, 'outputs', 'normalized.vcf.gz') == artifact(benchmark, 'inputs', 'baseline.vcf.gz')
                and artifact(compress, 'outputs', 'normalized.vcf.gz.tbi') == artifact(benchmark, 'inputs', 'baseline.vcf.gz.tbi'), 'shared normalized truth lineage differs')
