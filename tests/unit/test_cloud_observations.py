"""Private native observation and lineage tests with nonhuman temporary bytes."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from giab_wes_nextflow.cloud_observations import read_file_inventory, read_task_observation, join_scientific_lineage
from giab_wes_nextflow.cloud_science import authenticate


def ident(value):
    return {'sha256': hashlib.sha256(value.encode()).hexdigest(), 'bytes': len(value)}


def task_receipt(tmp_path):
    root = tmp_path / 'receipt'; root.mkdir()
    (root / 'task.json').write_text(json.dumps({'process': 'CLOUD_GATK_CALL', 'label': 'gatk', 'nextflow_task_id': 8, 'attempt': 1,
        'declared_image': 'example/gatk@sha256:' + 'a' * 64, 'requested_cpus': 2, 'requested_memory_bytes': 1000000, 'architecture': 'x86_64'}))
    for name, text in {'started.txt': '100', 'completed.txt': '120', 'command.sh': '#!/bin/bash\ngatk --version\n',
                       'version.txt': 'GATK 4.7.0.0\n', 'inputs.tsv': 'b' * 64 + '\t3\tshared/shared.bam\n',
                       'outputs.tsv': 'c' * 64 + '\t4\traw.vcf.gz\n'}.items():
        (root / name).write_text(text)
    return root


def test_native_observations_retain_measured_and_unknown_fields(tmp_path):
    result = read_task_observation(task_receipt(tmp_path))
    assert result['backend_binding_required'] is True
    assert result['started_epoch_seconds'] == 100
    assert result['cpu_seconds'] is None and result['peak_rss_bytes'] is None
    assert result['outputs']['raw.vcf.gz'] == {'sha256': 'c' * 64, 'bytes': 4}
    assert result['command']['sha256'] == ident('#!/bin/bash\ngatk --version\n')['sha256']


@pytest.mark.parametrize('change', ['missing_version', 'symlink', 'bad_timing', 'missing_model', 'mutable_image'])
def test_invalid_native_observations_rejected(tmp_path, change):
    root = task_receipt(tmp_path)
    if change == 'missing_version': (root / 'version.txt').write_text('')
    if change == 'symlink':
        source = root / 'command.sh'; source.rename(tmp_path / 'command.sh'); source.symlink_to(tmp_path / 'command.sh')
    if change == 'bad_timing': (root / 'completed.txt').write_text('99')
    if change in ('missing_model', 'mutable_image'):
        path = root / 'task.json'; meta = json.loads(path.read_text())
        if change == 'missing_model': meta.update(process='CLOUD_DEEPVARIANT_CALL', label='deepvariant')
        else: meta['declared_image'] = 'example/gatk:latest'
        path.write_text(json.dumps(meta))
    with pytest.raises(ValueError): read_task_observation(root)


@pytest.mark.parametrize('line', ['a\t3\tx', 'a' * 64 + '\t3\t../outside', 'a' * 64 + '\t3\t/absolute',
                                 ('a' * 64 + '\t3\tx\n') * 2, 'a' * 64 + '\t-1\tx'])
def test_native_inventory_path_and_digest_boundaries(tmp_path, line):
    path = tmp_path / 'inputs.tsv'; path.write_text(line)
    with pytest.raises(ValueError): read_file_inventory(path)


def lineage():
    records, callers = [], {}
    shared = {'shared.bam': ident('shared')['sha256'], 'reference.fa': ident('reference')['sha256']}
    def task(process, label, inputs, outputs):
        item = {'process': process, 'label': label, 'inputs': inputs, 'outputs': outputs,
                'nextflow_task_id': len(records) + 1, 'attempt': 1, 'command': ident(process)}
        records.append(item); return item
    for label in ('gatk', 'deepvariant', 'truth'):
        if label == 'truth':
            task('CLOUD_PREPARE_TRUTH', label, {'truth.vcf.gz': ident('original_truth')}, {'raw.vcf.gz': ident(label + '-raw')})
        else:
            call = task('CLOUD_' + label.upper() + '_CALL', label,
                        {'shared.bam': ident('shared'), 'reference.fa': ident('reference')}, {'raw.vcf.gz': ident(label + '-raw')})
            if label == 'deepvariant': call.update(model_before={'model_files': []}, model_after={'model_files': []})
        task('CLOUD_NORMALIZE', label, {'raw.vcf.gz': ident(label + '-raw')}, {'sorted.vcf': ident(label + '-sorted')})
        task('CLOUD_INCLUDE', label, {'sorted.vcf': ident(label + '-sorted')}, {'included.vcf': ident(label + '-included')})
        task('CLOUD_COMPRESS', label, {'included.vcf': ident(label + '-included')},
             {'normalized.vcf.gz': ident(label + '-normalized'), 'normalized.vcf.gz.tbi': ident(label + '-index')})
    for label in ('gatk', 'deepvariant'):
        parts = {name: ident(label + name) for name in ('tp.vcf.gz', 'tp-baseline.vcf.gz', 'fp.vcf.gz', 'fn.vcf.gz')}
        task('CLOUD_VCFEVAL', label, {'query.vcf.gz': ident(label + '-normalized'), 'query.vcf.gz.tbi': ident(label + '-index'),
                                    'baseline.vcf.gz': ident('truth-normalized'), 'baseline.vcf.gz.tbi': ident('truth-index')}, parts)
        callers[label] = {'partitions': copy.deepcopy(parts)}
    return records, callers, shared


def test_common_normalization_and_partition_lineage():
    records, callers, shared = lineage(); join_scientific_lineage(records, callers, shared)
    assert callers['gatk']['raw_vcf'] == ident('gatk-raw')
    assert callers['gatk']['normalized_vcf'] == ident('gatk-normalized')
    assert len(callers['deepvariant']['normalization_chain']) == 3


@pytest.mark.parametrize('process,label,group,name', [
    ('CLOUD_GATK_CALL', 'gatk', 'inputs', 'shared.bam'),
    ('CLOUD_NORMALIZE', 'gatk', 'inputs', 'raw.vcf.gz'),
    ('CLOUD_INCLUDE', 'deepvariant', 'inputs', 'sorted.vcf'),
    ('CLOUD_COMPRESS', 'gatk', 'inputs', 'included.vcf'),
    ('CLOUD_VCFEVAL', 'deepvariant', 'inputs', 'query.vcf.gz'),
    ('CLOUD_VCFEVAL', 'gatk', 'outputs', 'tp-baseline.vcf.gz'),
    ('CLOUD_VCFEVAL', 'gatk', 'inputs', 'baseline.vcf.gz'),
])
def test_changed_intermediate_or_truth_is_rejected(process, label, group, name):
    records, callers, shared = lineage()
    next(r for r in records if r['process'] == process and r['label'] == label)[group][name] = ident('changed')
    with pytest.raises(ValueError, match='lineage'): join_scientific_lineage(records, callers, shared)


def test_fixture_dispatch_never_precedes_manifest_hash_gate(tmp_path):
    path = tmp_path / 'manifest.json'; path.write_text('{"kind":"cloud_nonhuman_qualification_inputs"}')
    with pytest.raises(ValueError, match='pin mismatch'):
        authenticate(path, 'a' * 64, tmp_path, tmp_path / 'out', 'healthomics')
    assert not (tmp_path / 'out').exists()
