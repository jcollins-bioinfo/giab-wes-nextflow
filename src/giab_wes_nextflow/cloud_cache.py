"""Offline preparation and validation for bounded managed cache probes.

No AWS client, credential read, reservation, registration or submission occurs.
Probe evidence does not by itself authorize or qualify the production package.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

from .m5 import require

DIMENSIONS = ('parameter', 'input_content', 'reference', 'domain', 'container', 'command')
CASES = ('first', 'unchanged', *DIMENSIONS)
ENGINE = {'engineVersion': '26.04.0', 'syntaxVersion': 'v2'}


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encoded(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def check_hash(value: object) -> None:
    require(isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None,
            'Exact SHA-256 required')


def _image(value: str) -> str:
    require(re.fullmatch(r'[^\s]+@sha256:[0-9a-f]{64}', value) is not None,
            'Digest-pinned probe image required')
    return value.rsplit('@sha256:', 1)[1]


def prepare(root: Path, *, repo: Path, image: str, alternate_image: str,
            production_package_sha256: str, qualification_receipt_sha256: str,
            source_sha: str) -> dict:
    """Build two deterministic ZIPs and eight isolated cases; never overwrite."""
    check_hash(production_package_sha256); check_hash(qualification_receipt_sha256)
    require(re.fullmatch(r'[0-9a-f]{40}', source_sha) is not None, 'Exact source revision required')
    require(_image(image) != _image(alternate_image), 'Container negative requires different platform manifests')
    require(not root.exists() and not any(p.is_symlink() for p in (root, *root.parents)),
            'Preparation output must be fresh and unlinked')
    template = (repo / 'scripts/qualification/cloud-cache.nf').read_bytes()
    config = (repo / 'scripts/qualification/cloud-cache.config').read_bytes()
    require(template.count(b'# COMMAND_VARIANT') == 1, 'Missing unique command variant marker')
    root.mkdir(parents=True)
    inputs = {'A': b'nonhuman-A\n', 'B': b'nonhuman-B\n'}
    for label, raw in inputs.items():
        (root / f'input-{label}.txt').write_bytes(raw)
    packages = {}
    for variant in ('baseline', 'command'):
        script = template if variant == 'baseline' else template.replace(
            b'# COMMAND_VARIANT', b"printf '%s\\n' 'command-B' >> receipt.txt")
        files = {'main.nf': script, 'nextflow.config': config}
        manifest = {'source_sha': source_sha, 'scope': 'nonhuman_managed_cache_probe',
                    'production_package_sha256': production_package_sha256,
                    'files': {name: {'sha256': digest(raw), 'bytes': len(raw)} for name, raw in files.items()}}
        files['PACKAGE_MANIFEST.json'] = encoded(manifest)
        target = root / f'{variant}.zip'
        with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, raw in sorted(files.items()):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3; info.external_attr = 0o100644 << 16
                archive.writestr(info, raw)
        packages[variant] = {'file': target.name, 'sha256': digest(target.read_bytes()),
                             'main_sha256': digest(script), 'manifest': manifest}
    base = {'parameter': 'setting-A', 'input_content': digest(inputs['A']), 'reference': 'reference-A',
            'domain': 'domain-A', 'container': image, 'command': packages['baseline']['main_sha256']}
    replacements = {'parameter': 'setting-B', 'input_content': digest(inputs['B']), 'reference': 'reference-B',
                    'domain': 'domain-B', 'container': alternate_image, 'command': packages['command']['main_sha256']}
    cases = {}
    for name in CASES:
        dependencies = dict(base)
        if name in DIMENSIONS:
            dependencies[name] = replacements[name]
        label = 'B' if name == 'input_content' else 'A'
        raw_output = inputs[label] + ''.join(dependencies[k] + '\n' for k in ('reference', 'domain', 'parameter')).encode()
        if name == 'command':
            raw_output += b'command-B\n'
        cases[name] = {'dependencies': dependencies, 'input_file': f'input-{label}.txt',
                       'package': 'command' if name == 'command' else 'baseline',
                       'input_identity_sha256': digest(encoded(dependencies)),
                       'expected_output_sha256': digest(raw_output), 'expected_output_bytes': len(raw_output),
                       'expected_cache_hit': name == 'unchanged'}
    plan = {'schema_version': '1.0.0', 'kind': 'managed_cache_probe_plan', 'backend': 'healthomics',
            'engine_settings': ENGINE, 'source_sha': source_sha,
            'production_package_sha256': production_package_sha256,
            'qualification_receipt_sha256': qualification_receipt_sha256,
            'packages': packages, 'cases': cases, 'case_order': list(CASES),
            'task_bounds': {'cpus': 1, 'memory_gib': 2, 'minutes': 5, 'retries': 0, 'tasks_per_run': 1},
            'required_cache_behavior': 'CACHE_ALWAYS', 'mutation_performed': False,
            'managed_cache_qualified': False, 'canonical_hg001_comparison_complete': False,
            'launch_gates': ['Fresh non-root identity and inventory; adopt existing matching requests.',
                             'Private budget admission and deterministic requests; no reservation created by this plan.',
                             'Independent supervisor, server run bounds, cancellation and durable receipts.',
                             'One ACTIVE run cache and two registered workflows matching these package digests.',
                             'Both input fixtures must use the SAME S3 key/URI with distinct retained VersionIds and equal byte lengths.',
                             'Before EACH case, make its declared fixture the current version at that key, and reverify bytes; never replace human data.',
                             'Run first, then unchanged, then each negative against the same cache.',
                             'Review exact production package binding before accepting a runtime qualification.']}
    (root / 'plan.json').write_bytes(encoded(plan))
    return plan


def validate_resume(resume: dict, execution: dict) -> dict:
    """Validate the existing reviewed private resume contract independently."""
    require(resume.get('kind') == 'cloud_resume_receipt' and resume.get('status') == 'passed'
            and resume.get('run_id') == execution['run_id'], 'managed resume receipt not passed for this run')
    require(all(resume[k] == execution[k] for k in ('backend', 'nextflow', 'parser', 'workflow_sha256')),
            'managed resume engine/package binding differs')
    invalidated = resume.get('invalidated')
    require(resume.get('unchanged_reused') is True and isinstance(invalidated, dict)
            and set(invalidated) == set(DIMENSIONS) and all(value is True for value in invalidated.values()),
            'managed resume/cache qualification incomplete')
    cases = resume['cases']
    require(set(cases) == set(CASES), 'managed cache observation cases incomplete')
    seen = set(); receipt_pins = set()
    for name, case in cases.items():
        require(set(case) == {'backend_run_id', 'task_identity', 'task_cache_key', 'input_identity_sha256',
                             'output_sha256', 'cache_hit', 'backend_receipt_sha256'}, 'managed cache observation fields differ')
        require(all(isinstance(case[k], str) and case[k] for k in ('backend_run_id', 'task_identity', 'task_cache_key')),
                'native cache identity absent')
        pair = (case['backend_run_id'], case['task_identity'])
        require(pair not in seen, 'managed cache cases reuse one native task observation'); seen.add(pair)
        for key in ('input_identity_sha256', 'output_sha256', 'backend_receipt_sha256'):
            check_hash(case[key])
        require(case['backend_receipt_sha256'] not in receipt_pins, 'managed cache cases duplicate a provider receipt')
        receipt_pins.add(case['backend_receipt_sha256'])
        require(case['cache_hit'] is (name == 'unchanged'), 'cache hit observation contradicts case')
        if name == 'unchanged':
            require(all(case[k] == cases['first'][k] for k in ('task_cache_key', 'input_identity_sha256', 'output_sha256')),
                    'unchanged task did not reuse the same evidence')
        elif name != 'first':
            require(case['task_cache_key'] != cases['first']['task_cache_key'] and
                    case['input_identity_sha256'] != cases['first']['input_identity_sha256'],
                    'changed dependency reused a stale cache identity')
    return cases


def requests(plan: dict, bindings: dict) -> dict:
    """Construct private, unsubmitted requests from actual registered identities.

    A request file is not admission: the existing watchdog must reserve and
    supervise every case, and live group/cache/input versions must be reread.
    """
    from .aws_support import parse_s3_uri
    require(plan['kind'] == 'managed_cache_probe_plan' and plan['engine_settings'] == ENGINE,
            'Unexpected managed probe plan')
    for key in ('cache_id', 'run_group_id'):
        require(re.fullmatch(r'[0-9]{1,18}', bindings[key]) is not None, 'Native numeric provider identity required')
    require(re.fullmatch(r'arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]+', bindings['role_arn']) is not None,
            'Execution role ARN required')
    parse_s3_uri(bindings['output_uri'])
    first_input, changed_input = (bindings['inputs'][f'input-{label}.txt'] for label in ('A', 'B'))
    require(first_input['uri'] == changed_input['uri'] and first_input['version_id'] != changed_input['version_id'],
            'Input-content negative requires the same URI and distinct retained versions')
    result = {}; suite = digest(encoded(plan))
    for name in CASES:
        case = plan['cases'][name]; dep = case['dependencies']
        workflow = bindings['workflows'][case['package']]
        require(re.fullmatch(r'[0-9]{1,18}', workflow['id']) is not None and
                workflow['digest'] == 'sha256:' + plan['packages'][case['package']]['sha256'],
                'Registered workflow digest differs')
        source = bindings['inputs'][case['input_file']]
        parse_s3_uri(source['uri'])
        require(source['sha256'] == dep['input_content'] and source['bytes'] == 11
                and isinstance(source['version_id'], str) and source['version_id'] not in ('', 'null'),
                'Pinned staged input identity required')
        request = {'workflowId': workflow['id'], 'workflowType': 'PRIVATE', 'roleArn': bindings['role_arn'],
                   'name': 'cache-' + name.replace('_', '-') + '-' + suite[:12],
                   'outputUri': bindings['output_uri'].rstrip('/') + '/' + suite + '/' + name + '/',
                   'parameters': {'input': source['uri'], 'reference': dep['reference'], 'domain': dep['domain'],
                                  'setting': dep['parameter'], 'probe_image': dep['container']},
                   'engineSettings': dict(ENGINE), 'runGroupId': bindings['run_group_id'], 'storageType': 'DYNAMIC',
                   'logLevel': 'ALL', 'cacheId': bindings['cache_id'], 'cacheBehavior': 'CACHE_ALWAYS',
                   'tags': {'Project': 'giab-wes-nextflow', 'CacheProbeSuiteSHA256': suite, 'CacheProbeCase': name}}
        request['requestId'] = digest(encoded(request))
        result[name] = request
    return {'kind': 'unsubmitted_managed_cache_requests', 'plan_sha256': suite, 'case_order': list(CASES),
            'requests': result, 'submitted': False, 'budget_reserved': False,
            'admission_and_independent_supervision_required': True}


def validate_probe(plan: dict, observations: dict) -> dict:
    """Validate independently pinned provider/trace/output captures, offline.

    The caller must authenticate the input capture and its externally reviewed
    pin. This function validates joins; it is not a provider attestation service.
    """
    require(plan['kind'] == 'managed_cache_probe_plan' and plan['engine_settings'] == ENGINE,
            'unexpected managed probe engine')
    check_hash(plan['production_package_sha256']); check_hash(plan['qualification_receipt_sha256'])
    require(set(plan['cases']) == set(CASES) and set(plan['packages']) == {'baseline', 'command'},
            'Unexpected probe plan inventory')
    require(set(observations) == set(CASES), 'All eight native cases are required')
    cases = {}; cache_ids = set(); run_ids = set()
    first_dependencies = plan['cases']['first']['dependencies']
    input_uri = observations['first']['input']['uri']
    require(observations['first']['input']['version_id'] != observations['input_content']['input']['version_id'],
            'Input-content negative requires a distinct retained version')
    for name in CASES:
        expected = plan['cases'][name]; capture = observations[name]
        run, task, trace, request = (capture[k] for k in ('run', 'task', 'trace', 'request'))
        changed = {k for k in DIMENSIONS if expected['dependencies'][k] != first_dependencies[k]}
        require(changed == ({name} if name in DIMENSIONS else set()), 'Probe changed more than the intended dependency')
        require(expected['input_identity_sha256'] == digest(encoded(expected['dependencies']))
                and expected['expected_cache_hit'] is (name == 'unchanged'), 'Probe case identity differs')
        require(expected['package'] == ('command' if name == 'command' else 'baseline'), 'Probe package variant differs')
        require(run['status'] == 'COMPLETED' and run['engineVersion'] == ENGINE['engineVersion']
                and run['engineSettings'] == ENGINE
                and run['id'] not in run_ids, 'Native completed distinct probe run required')
        run_ids.add(run['id'])
        require(request['engineSettings'] == ENGINE and request['cacheBehavior'] == 'CACHE_ALWAYS'
                and run['cacheBehavior'] == 'CACHE_ALWAYS' and request['cacheId'] == run['cacheId'],
                'Explicit managed cache/parser binding missing')
        cache_ids.add(run['cacheId'])
        package = plan['packages'][expected['package']]
        require(run['digest'] == 'sha256:' + package['sha256'] and run['workflowId'] == request['workflowId']
                and run['parameters'] == request['parameters'], 'Provider package/request mismatch')
        parameters = request['parameters']; dep = expected['dependencies']
        require({k: parameters[k] for k in ('reference', 'domain', 'setting', 'probe_image')} ==
                {'reference': dep['reference'], 'domain': dep['domain'], 'setting': dep['parameter'], 'probe_image': dep['container']},
                'Probe dependency parameters differ')
        require(capture['input']['sha256'] == dep['input_content']
                and capture['input']['uri'] == parameters['input'] == input_uri and capture['input']['bytes'] == 11
                and isinstance(capture['input']['version_id'], str) and capture['input']['version_id'] not in ('', 'null')
                and capture['input']['whole_object_sha256_verified'] is True, 'Versioned input byte proof missing')
        require(capture['task_request'] == {'id': run['id'], 'taskId': task['taskId']},
                'Task receipt collection context belongs to another run')
        require(task['status'] == 'COMPLETED' and task['name'] == 'CACHE_PROBE' and task['taskId']
                and task.get('cacheHit') is expected['expected_cache_hit'], 'Native task/cache observation differs')
        image = task['imageDetails']
        require(image['imageDigest'] == 'sha256:' + _image(dep['container']) and image['image'] == dep['container'],
                'Provider platform image differs')
        require(trace['name'] == 'CACHE_PROBE' and trace['container'] == dep['container']
                and trace['status'] in ('CACHED', 'COMPLETED')
                and isinstance(trace['hash'], str) and trace['hash'], 'Native trace binding differs')
        if name == 'unchanged':
            require(isinstance(task.get('cacheS3Uri'), str) and task['cacheS3Uri'].startswith('s3://'),
                    'Provider cache-hit location missing')
        require(task['cpus'] == 1 and task['memory'] == 2 and task.get('gpus', 0) == 0,
                'Probe task resource bounds differ')
        output = capture['output_text'].encode()
        wanted = (b'nonhuman-B\n' if name == 'input_content' else b'nonhuman-A\n')
        require(dep['input_content'] == digest(wanted), 'Nonhuman input identity differs')
        wanted += ''.join(dep[k] + '\n' for k in ('reference', 'domain', 'parameter')).encode()
        if name == 'command':
            wanted += b'command-B\n'
        require(output == wanted and digest(output) == expected['expected_output_sha256']
                and len(output) == expected['expected_output_bytes'],
                'Probe output byte identity differs')
        cases[name] = {'backend_run_id': run['id'], 'task_identity': task['taskId'], 'nextflow_task_hash': trace['hash'],
                       'provider_cache_location': task.get('cacheS3Uri'),
                       'input_identity_sha256': expected['input_identity_sha256'], 'output_sha256': digest(output),
                       'cache_hit': task['cacheHit'], 'backend_receipt_sha256': digest(encoded(capture))}
    require(len(cache_ids) == 1 and all(isinstance(v, str) and v for v in cache_ids), 'Cases must use one nonempty native cache')
    return {'kind': 'managed_cache_probe_validation', 'status': 'passed', 'backend': 'healthomics',
            'nextflow': '26.04.0', 'parser': 'v2', 'plan_sha256': digest(encoded(plan)),
            'production_package_sha256': plan['production_package_sha256'],
            'qualification_receipt_sha256': plan['qualification_receipt_sha256'], 'cases': cases,
            'canonical_hg001_comparison_complete': False, 'production_binding_review_required': True,
            'managed_cache_qualified': False,
            'resume_adapter_review_required': 'Bind actual provider cache-entry keys and production package; '
                                              'Nextflow task hashes are not asserted to be provider cache keys.'}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare_parser = commands.add_parser('prepare')
    prepare_parser.add_argument('--repo', type=Path, required=True)
    prepare_parser.add_argument('--output', type=Path, required=True)
    for field in ('image', 'alternate-image', 'production-package-sha256', 'qualification-receipt-sha256', 'source-sha'):
        prepare_parser.add_argument('--' + field, required=True)
    validate_parser = commands.add_parser('validate')
    for field in ('plan', 'observations', 'output'):
        validate_parser.add_argument('--' + field, type=Path, required=True)
    validate_parser.add_argument('--observations-sha256', required=True)
    request_parser = commands.add_parser('requests')
    for field in ('plan', 'bindings', 'output'):
        request_parser.add_argument('--' + field, type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        kwargs = vars(args).copy(); kwargs.pop('command'); root = kwargs.pop('output')
        result = prepare(root, **kwargs)
    elif args.command == 'requests':
        require(not args.output.exists(), 'Request output must be fresh')
        result = requests(json.loads(args.plan.read_text()), json.loads(args.bindings.read_text()))
        args.output.write_bytes(encoded(result))
    else:
        raw = args.observations.read_bytes(); check_hash(args.observations_sha256)
        require(len(raw) <= 2_000_000 and digest(raw) == args.observations_sha256, 'Observation pin/size mismatch')
        require(not args.output.exists(), 'Validation output must be fresh')
        result = validate_probe(json.loads(args.plan.read_text()), json.loads(raw))
        args.output.write_bytes(encoded(result))
    print(json.dumps({'kind': result['kind'], 'mutation_performed': False}))


if __name__ == '__main__':
    main()
