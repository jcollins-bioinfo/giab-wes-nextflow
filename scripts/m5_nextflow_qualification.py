"""Qualify actual M5 independent selections and cache reuse without rerunning M4."""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
from typing import Any

from giab_wes_nextflow.m5 import identity, load_json, require, validate_record
from giab_wes_nextflow.m5_manifest import FIELDS, read_manifest
from giab_wes_nextflow.m5_resources import parse_trace, TRACE_UNITS

PHASES = ('gatk', 'deepvariant', 'both', 'resume')


def validate_modes(traces: dict[str, str]) -> dict[str, Any]:
    """Require exact task inventories and reuse of the same successful task hashes."""
    require(set(traces) == set(PHASES), 'missing Nextflow qualification phase')
    seen: dict[tuple[str, str], str] = {}
    result = {}
    for phase in PHASES:
        tasks = parse_trace(traces[phase], trace_units=TRACE_UNITS)
        callers = (phase,) if phase in ('gatk', 'deepvariant') else ('gatk', 'deepvariant')
        expected = {(process, caller) for process in ('M5_NORMALIZE', 'M5_BENCHMARK') for caller in callers}
        observed = set()
        for task in tasks:
            match = re.search(r' \((gatk|deepvariant)(?::[^)]*)?\)$', task['name'])
            require(match is not None, 'missing or ambiguous M5 caller display tag')
            key = (task['process'], match[1])
            require(key in expected and key not in observed, 'unexpected or duplicated M5 task')
            observed.add(key)
            require(task['status'] == ('CACHED' if key in seen else 'COMPLETED'), 'incorrect M5 cache status')
            require(task['task_hash'] is not None, 'M5 trace lacks a task hash')
            if key in seen:
                require(task['task_hash'] == seen[key], 'M5 cache hash changed')
            seen[key] = task['task_hash']
        require(observed == expected, 'missing M5 task')
        result[phase] = {'task_count': len(tasks), 'statuses': {status: sum(t['status'] == status for t in tasks) for status in ('COMPLETED', 'CACHED')}}
    return result


def _identities(items: dict[str, Any]) -> dict[str, Any]:
    """Compare scientific bytes independently of staging or publication filenames."""
    return {key: {field: value[field] for field in ('sha256', 'bytes')} for key, value in items.items()}


def snapshot(published: Path, caller: str) -> dict[str, Any]:
    """Validate output bytes and lineage, returning a portable scientific comparison."""
    base = published / 'm5' / caller
    normdir = base / 'normalization/normalized'
    norm = load_json(normdir / 'normalization.json')
    bench = load_json(base / 'benchmark/benchmark/benchmark.json')
    validate_record(norm, 'normalization'); validate_record(bench, 'benchmark')
    require(norm['caller'] == bench['caller'] == caller, 'M5 publication caller mismatch')
    require(bench['normalization_lineage'] == norm['payload_sha256'], 'M5 normalization lineage mismatch')
    require(bench['inputs']['normalization'] == identity(normdir / 'normalization.json'), 'M5 normalization input identity mismatch')
    for name, expected in norm['outputs'].items():
        require(identity(normdir / name) == expected, 'M5 normalized output bytes changed')
    for name, expected in bench['outputs'].items():
        require(identity(base / 'benchmark/benchmark' / name) == expected, 'M5 benchmark output bytes changed')
    return {'normalization': {'inputs': _identities(norm['inputs']), 'outputs': _identities(norm['outputs']),
                              'sample': norm['sample'], 'record_count': norm['record_count'], 'excluded_records': norm['excluded_records'], 'tools': norm['tools']},
            'benchmark': {**{key: bench[key] for key in ('sample', 'domain_id', 'status', 'metrics', 'evaluated_bases', 'interval_count', 'tools')},
                          'inputs': _identities({key: value for key, value in bench['inputs'].items() if key != 'normalization'})}}


def _closed_manifest(source: Path, target: Path) -> None:
    """Adapt versioned synthetic-fixture metadata to the closed Nextflow contract."""
    data = read_manifest(source)
    require(set(data) in (FIELDS, FIELDS | {'canonical', 'recipe_version'}), 'unexpected fixture manifest fields')
    require(data['synthetic'] is True and data.get('canonical', False) is False, 'synthetic manifest required')
    data = {key: data[key] for key in FIELDS}
    for key in ('reference', 'fai', 'dictionary', 'truth', 'truth_index', 'confidence', 'domain'):
        data[key] = str((source.parent / data[key]).resolve(strict=True))
    for row in data['queries']:
        for key in ('vcf', 'index'):
            row[key] = str((source.parent / row[key]).resolve(strict=True))
    target.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')


def qualify_nextflow(repository: Path, output_root: Path, manifest: Path, *, nextflow: str = 'nextflow') -> dict[str, Any]:
    """Run real M5 tasks in four modes; accept only matching outputs and cache reuse.

    The caller supplies an installed package environment and prepared small
    synthetic inputs. This helper does not run callers, construct fixtures or
    claim that host-launcher monitoring measures Docker-tool resources.
    """
    repository, output_root, manifest = repository.resolve(), output_root.resolve(), manifest.resolve()
    require(not output_root.exists(), 'fresh M5 Nextflow qualification root required')
    output_root.mkdir(parents=True)
    (output_root / 'evidence').mkdir()
    adapter = output_root / 'manifest.json'
    _closed_manifest(manifest, adapter)
    work, published = output_root / 'work', output_root / 'published'
    traces, comparisons, commands = {}, {}, {}
    for phase in PHASES:
        mode = 'both' if phase == 'resume' else phase
        trace = output_root / 'evidence' / f'{phase}.trace.tsv'
        command = [nextflow, '-log', str(output_root / f'{phase}.log'), 'run', str(repository / 'm5.nf'), '-profile', 'm5_test',
                   '--m5_manifest', str(adapter), '--callers', mode, '--outdir', str(published), '-work-dir', str(work),
                   '-with-trace', str(trace), '-with-report', str(output_root / f'{phase}.report.html'),
                   '-with-timeline', str(output_root / f'{phase}.timeline.html'), '-with-dag', str(output_root / f'{phase}.dag.dot')]
        if phase != 'gatk':
            command.append('-resume')
        commands[phase] = command
        with (output_root / 'evidence' / f'{phase}.log').open('w') as log:
            subprocess.run(command, cwd=output_root, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1800)
        traces[phase] = trace.read_text()
        comparisons[phase] = {caller: snapshot(published, caller) for caller in ((mode,) if mode != 'both' else ('gatk', 'deepvariant'))}
        # Inspect actual normalization task staging, not only module source text.
        for task in parse_trace(traces[phase], trace_units=TRACE_UNITS):
            if task['process'] != 'M5_NORMALIZE':
                continue
            task_hash = task['task_hash']
            require(task_hash is not None and re.fullmatch(r'[a-f0-9]{2}/[a-f0-9]+', task_hash) is not None, 'invalid Nextflow task hash')
            matches = list(work.glob(task_hash + '*'))
            require(len(matches) == 1, 'ambiguous normalization work directory')
            staged = {p.name for p in matches[0].iterdir() if not p.name.startswith('.')}
            require(staged <= {'query.vcf.gz', 'query.vcf.gz.tbi', 'reference.fa', 'reference.fa.fai', 'reference.dict', 'normalized'}, 'unexpected normalization input or truth leakage')
    modes = validate_modes(traces)
    for caller in ('gatk', 'deepvariant'):
        require(comparisons[caller][caller] == comparisons['both'][caller] == comparisons['resume'][caller], 'independent/both/resume M5 outputs differ')
    result = {'synthetic': True, 'canonical': False, 'nextflow_resume_qualified': True, 'modes': modes,
              'normalization_staging_isolated': True, 'comparisons': comparisons, 'commands': commands,
              'boundary': 'Actual synthetic M5 Nextflow task execution and reuse only; no canonical accuracy or container-cost estimate.'}
    (output_root / 'evidence/nextflow-proof.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    return result
