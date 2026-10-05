"""Synthetic contract tests only; these do not establish managed cache support."""
import copy
from pathlib import Path
import zipfile

import pytest

from giab_wes_nextflow import cloud_cache as cache

REPO = Path(__file__).resolve().parents[2]
IMAGE = 'example.test/support@sha256:' + 'a' * 64
OTHER = 'example.test/support@sha256:' + 'b' * 64


def plan(tmp_path, name='plan'):
    return cache.prepare(tmp_path / name, repo=REPO, image=IMAGE, alternate_image=OTHER,
                         production_package_sha256='c' * 64, qualification_receipt_sha256='d' * 64,
                         source_sha='e' * 40)


def observations(p):
    result = {}
    for index, name in enumerate(cache.CASES):
        row = p['cases'][name]; dep = row['dependencies']
        request = {'engineSettings': dict(cache.ENGINE), 'cacheBehavior': 'CACHE_ALWAYS', 'cacheId': '100',
                   'workflowId': '102' if name == 'command' else '101',
                   'parameters': {'reference': dep['reference'], 'domain': dep['domain'], 'setting': dep['parameter'],
                                  'probe_image': dep['container'], 'input': 's3://example/nonhuman-probe.txt'}}
        output = ('nonhuman-B\n' if name == 'input_content' else 'nonhuman-A\n')
        output += ''.join(dep[k] + '\n' for k in ('reference', 'domain', 'parameter'))
        if name == 'command':
            output += 'command-B\n'
        result[name] = {
            'request': request,
            'run': {'id': str(index + 200), 'status': 'COMPLETED', 'engineVersion': '26.04.0',
                    'engineSettings': dict(cache.ENGINE),
                    'workflowId': request['workflowId'], 'cacheId': '100', 'cacheBehavior': 'CACHE_ALWAYS',
                    'digest': 'sha256:' + p['packages'][row['package']]['sha256'], 'parameters': copy.deepcopy(request['parameters'])},
            'task_request': {'id': str(index + 200), 'taskId': str(index + 300)},
            'task': {'taskId': str(index + 300), 'status': 'COMPLETED', 'name': 'CACHE_PROBE',
                     'cacheHit': name == 'unchanged', 'cpus': 1, 'memory': 2, 'gpus': 0,
                     'cacheS3Uri': 's3://example/cache/first' if name == 'unchanged' else None,
                     'imageDetails': {'image': dep['container'], 'imageDigest': dep['container'].split('@')[1]}},
            'trace': {'name': 'CACHE_PROBE', 'container': dep['container'],
                      'status': 'CACHED' if name == 'unchanged' else 'COMPLETED',
                      'hash': 'hash-first' if name == 'unchanged' else 'hash-' + name},
            'input': {'uri': request['parameters']['input'], 'version_id': 'version-' + row['input_file'],
                      'sha256': dep['input_content'], 'bytes': 11, 'whole_object_sha256_verified': True},
            'output_text': output,
        }
    return result


def test_packages_are_deterministic_and_only_one_dependency_changes(tmp_path):
    first = plan(tmp_path, 'one'); second = plan(tmp_path, 'two')
    assert first == second
    for variant in ('baseline', 'command'):
        raw = (tmp_path / 'one' / f'{variant}.zip').read_bytes()
        assert raw == (tmp_path / 'two' / f'{variant}.zip').read_bytes()
        assert cache.digest(raw) == first['packages'][variant]['sha256']
        with zipfile.ZipFile(tmp_path / 'one' / f'{variant}.zip') as archive:
            assert set(archive.namelist()) == {'main.nf', 'nextflow.config', 'PACKAGE_MANIFEST.json'}
            assert b"manifest.nextflowVersion = '==26.04.0'" in archive.read('nextflow.config')
            assert b'maxRetries = 0' in archive.read('nextflow.config')
    baseline = first['cases']['first']['dependencies']
    for name in cache.CASES:
        deps = first['cases'][name]['dependencies']
        assert {key for key in cache.DIMENSIONS if deps[key] != baseline[key]} == (
            {name} if name in cache.DIMENSIONS else set())
    assert first['cases']['first']['expected_output_sha256'] == first['cases']['container']['expected_output_sha256']
    assert first['cases']['first'] == first['cases']['unchanged'] | {'expected_cache_hit': False}
    assert first['managed_cache_qualified'] is False


def test_same_image_alias_and_overwrite_are_rejected(tmp_path):
    p = tmp_path / 'plan'
    with pytest.raises(ValueError, match='different platform'):
        cache.prepare(p, repo=REPO, image=IMAGE, alternate_image='another.test/repo@sha256:' + 'a' * 64,
                      production_package_sha256='c' * 64, qualification_receipt_sha256='d' * 64, source_sha='e' * 40)
    assert not p.exists()
    plan(tmp_path)
    with pytest.raises(ValueError, match='fresh'):
        plan(tmp_path)


def test_native_probe_replay_preserves_production_review_gate(tmp_path):
    p = plan(tmp_path); result = cache.validate_probe(p, observations(p))
    assert result['status'] == 'passed'
    assert result['production_binding_review_required'] is True
    assert result['canonical_hg001_comparison_complete'] is False
    assert sum(row['cache_hit'] for row in result['cases'].values()) == 1
    assert 'cloud_resume_receipt' != result['kind']


def test_requests_are_stable_unsubmitted_and_bind_native_workflows(tmp_path):
    p = plan(tmp_path)
    bindings = {'cache_id': '100', 'run_group_id': '101', 'role_arn': 'arn:aws:iam::123456789012:role/example',
                'output_uri': 's3://example/results',
                'workflows': {name: {'id': str(102 + index), 'digest': 'sha256:' + row['sha256']}
                              for index, (name, row) in enumerate(p['packages'].items())},
                'inputs': {f'input-{label}.txt': {'uri': 's3://example/nonhuman-probe.txt', 'version_id': 'version-' + label,
                            'sha256': cache.digest(f'nonhuman-{label}\n'.encode()), 'bytes': 11} for label in ('A', 'B')}}
    result = cache.requests(p, bindings)
    assert result == cache.requests(p, bindings)
    assert result['submitted'] is result['budget_reserved'] is False
    assert len({row['requestId'] for row in result['requests'].values()}) == 8
    assert all(row['cacheBehavior'] == 'CACHE_ALWAYS' for row in result['requests'].values())
    assert result['requests']['first']['parameters'] == result['requests']['unchanged']['parameters']
    assert result['requests']['command']['workflowId'] != result['requests']['first']['workflowId']
    bindings['workflows']['baseline']['digest'] = 'sha256:' + 'f' * 64
    with pytest.raises(ValueError, match='digest'):
        cache.requests(p, bindings)


@pytest.mark.parametrize('mutation', [
    lambda p, o: o.pop('domain'),
    lambda p, o: o['first']['task'].pop('cacheHit'),
    lambda p, o: o['unchanged']['task'].update(cacheHit=False),
    lambda p, o: o['first']['run'].update(status='CANCELLED'),
    lambda p, o: o['first']['run'].update(engineVersion='26.04'),
    lambda p, o: o['first']['request']['engineSettings'].update(syntaxVersion='v1'),
    lambda p, o: o['first']['run']['engineSettings'].update(syntaxVersion='v1'),
    lambda p, o: o['first']['task_request'].update(id='other-run'),
    lambda p, o: o['first']['run'].update(cacheId='different'),
    lambda p, o: o['domain']['run'].update(cacheId='different'),
    lambda p, o: o['first']['request'].update(cacheBehavior='CACHE_ON_FAILURE'),
    lambda p, o: o['first']['run'].update(digest='sha256:' + 'f' * 64),
    lambda p, o: o['parameter']['request']['parameters'].update(setting='setting-A'),
    lambda p, o: o['container']['task']['imageDetails'].update(imageDigest='sha256:' + 'a' * 64),
    lambda p, o: o['first']['task'].update(cpus=2),
    lambda p, o: o['input_content']['input'].update(whole_object_sha256_verified=False),
    lambda p, o: o['input_content']['input'].update(version_id=''),
    lambda p, o: o['input_content']['input'].update(version_id='null'),
    lambda p, o: o['input_content']['input'].update(uri='s3://example/another-key'),
    lambda p, o: o['unchanged'].update(output_text='tampered\n'),
    lambda p, o: o['unchanged']['task'].update(cacheS3Uri=None),
    lambda p, o: o['domain']['run'].update(id=o['reference']['run']['id']),
    lambda p, o: p['cases']['domain']['dependencies'].update(reference='reference-B'),
])
def test_probe_failures_cannot_be_accepted(tmp_path, mutation):
    p = plan(tmp_path); o = observations(p); mutation(p, o)
    with pytest.raises((ValueError, KeyError)):
        cache.validate_probe(p, o)
