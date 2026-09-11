"""Fail-closed projection of reviewed private cloud receipts into public metadata.

This is an offline acceptance boundary, not an execution attestation service.
An operator must independently review the private inventory pin. Missing native
receipts are errors, including when the private collector contains valid counts.
No genomic files or private receipt bodies are copied into the public bundle.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re

from jsonschema import Draft202012Validator

from .canonical_asset_reference import digest_json, load_assets
from .canonical_results import DOMAINS, REQUIRED_LIMITATIONS, _json, write_public_bundle
from .cloud_contract import ASSETS, tool_images, validate_manifest
from .coding_domain import EXPECTED
from .m4_contracts import _model_inventory
from .m5 import metrics, require
from .resources import config_path, schema_path

ROLES = ('inputs', 'scientific', 'reference', 'index', 'known_sites', 'runtime',
         'execution', 'preprocessing', 'callers', 'benchmark', 'resume', 'durable')
GROUPS = ('shared_preprocessing', 'gatk', 'deepvariant', 'common_downstream')
PROCESSES = {
    'CLOUD_AUTHENTICATE': ('support', 'shared_preprocessing', 1),
    'CLOUD_BWA_ALIGN': ('bwa', 'shared_preprocessing', 1),
    'CLOUD_SORT': ('samtools', 'shared_preprocessing', 1),
    'CLOUD_MARK_DUPLICATES': ('gatk', 'shared_preprocessing', 1),
    'CLOUD_BQSR': ('gatk', 'shared_preprocessing', 1),
    'CLOUD_BAM_OBSERVATIONS': ('samtools', 'shared_preprocessing', 1),
    'CLOUD_BAM_GATE': ('support', 'shared_preprocessing', 1),
    'CLOUD_GATK_CALL': ('gatk', 'gatk', 1),
    'CLOUD_DEEPVARIANT_CALL': ('deepvariant', 'deepvariant', 1),
    'CLOUD_PREPARE_TRUTH': ('bcftools', 'common_downstream', 1),
    'CLOUD_NORMALIZE': ('bcftools', 'common_downstream', 3),
    'CLOUD_INCLUDE': ('support', 'common_downstream', 3),
    'CLOUD_COMPRESS': ('bcftools', 'common_downstream', 3),
    'CLOUD_RTG_REFERENCE': ('rtg', 'common_downstream', 1),
    'CLOUD_VCFEVAL': ('rtg', 'common_downstream', 2),
    'CLOUD_COLLECT': ('support', 'common_downstream', 1),
}
COUNT_SEMANTICS = {'tp_query': 'tp.vcf.gz', 'tp_truth': 'tp-baseline.vcf.gz',
                   'fp': 'fp.vcf.gz', 'fn': 'fn.vcf.gz'}
HASH = r'[0-9a-f]{64}'


def sha(value: object) -> str:
    require(isinstance(value, str) and re.fullmatch(HASH, value) is not None, 'invalid evidence SHA-256')
    return value


def identity(value: dict) -> dict:
    require(set(value) == {'sha256', 'bytes'} and type(value['bytes']) is int and value['bytes'] > 0,
            'whole-file identity requires SHA-256 and positive bytes')
    sha(value['sha256'])
    return value


def encoded(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def read_private(path: Path, pin: str) -> dict:
    """Read bounded regular JSON without following links or ambiguous numbers."""
    sha(pin)
    path = path.absolute()
    require(not any(p.is_symlink() for p in (path, *path.parents)) and path.is_file(), 'linked or missing private receipt')
    require(path.stat().st_size <= 2_000_000, 'private receipt exceeds metadata bound')
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == pin, 'private receipt pin mismatch')
    return _json(raw)


def load_inventory(path: Path, pin: str) -> tuple[dict, dict]:
    inventory = read_private(path, pin)
    Draft202012Validator(_json(schema_path('cloud-public-inventory.schema.json').read_bytes())).validate(inventory)
    receipts = {}
    for role, item in inventory['receipts'].items():
        member = path.parent / item['file']
        require(member.stat().st_size == item['bytes'], 'private receipt byte count mismatch')
        receipts[role] = read_private(member, item['sha256'])
    return inventory, receipts


def passed(receipt: dict, kind: str, run_id: str | None = None) -> None:
    require(receipt.get('kind') == kind and receipt.get('status') == 'passed', f'{kind} gate not passed')
    if run_id is not None:
        require(receipt.get('run_id') == run_id, f'{kind} belongs to another run')


def number(value: object, *, nullable: bool = False) -> None:
    require((nullable and value is None) or (type(value) in (int, float) and math.isfinite(value) and value >= 0),
            'invalid observed resource value')


def execution_summary(execution: dict, runtime: dict) -> tuple[dict, dict]:
    """Separate elapsed intervals from summed task time; never invent CPU/RSS."""
    require(execution['backend'] in ('healthomics', 'awsbatch') and execution['nextflow'] == runtime['nextflow']
            and execution['parser'] == runtime['parser'], 'backend engine/parser qualification mismatch')
    require(execution['architecture'] == 'x86_64' and execution['accelerators'] == 0, 'CPU architecture contract differs')
    sha(execution['workflow_sha256']); number(execution['started']); number(execution['completed'])
    require(execution['completed'] >= execution['started'], 'reversed run timing')
    tasks = execution['tasks']
    require(isinstance(tasks, list) and 1 <= len(tasks) <= 128, 'bounded actual task inventory required')
    seen = set()
    for task in tasks:
        require(set(task) == {'task_id', 'process', 'attempt', 'group', 'status', 'cache', 'tool', 'image_manifest_sha256',
                             'command_sha256', 'submitted', 'started', 'completed', 'requested_cpus', 'requested_memory_bytes',
                             'cpu_seconds', 'peak_rss_bytes', 'missing_reasons', 'inputs', 'outputs'}, 'unexpected task observation fields')
        require(isinstance(task['task_id'], str) and task['task_id'] and type(task['attempt']) is int and task['attempt'] > 0,
                'task/attempt identity missing')
        key = (task['task_id'], task['attempt'])
        require(key not in seen, 'duplicate task attempt'); seen.add(key)
        require(task['process'] in PROCESSES and (task['tool'], task['group']) == PROCESSES[task['process']][:2],
                'unrecognized task process/group')
        require(task['status'] in ('succeeded', 'failed') and task['cache'] in ('hit', 'miss', 'unknown'), 'task state/cache unavailable without label')
        require(task['tool'] in runtime['observed_tools'] and task['image_manifest_sha256'] ==
                runtime['observed_tools'][task['tool']]['image_manifest_sha256'], 'task runtime image differs from qualified native image')
        sha(task['command_sha256'])
        for field in ('submitted', 'started', 'completed', 'requested_cpus', 'requested_memory_bytes'):
            number(task[field])
        require(execution['started'] <= task['submitted'] <= task['started'] <= task['completed'] <= execution['completed'], 'invalid task timeline')
        require(task['requested_cpus'] > 0 and task['requested_memory_bytes'] > 0, 'requested resources missing')
        for field in ('cpu_seconds', 'peak_rss_bytes'):
            number(task[field], nullable=True)
        require(task['peak_rss_bytes'] is None or type(task['peak_rss_bytes']) is int, 'RSS must be integral bytes')
        require(set(task['missing_reasons']) == {k for k in ('cpu_seconds', 'peak_rss_bytes') if task[k] is None}
                and all(isinstance(v, str) and v for v in task['missing_reasons'].values()), 'task resource missingness mismatch')
        for group in ('inputs', 'outputs'):
            require(isinstance(task[group], list) and len(set(task[group])) == len(task[group]), 'task artifact hash inventory differs')
            for value in task[group]:
                sha(value)
    require({t['group'] for t in tasks if t['status'] == 'succeeded'} == set(GROUPS), 'scientific stage coverage incomplete')
    for process, (_, _, count) in PROCESSES.items():
        require(sum(t['process'] == process and t['status'] == 'succeeded' for t in tasks) == count,
                'native scientific DAG receipt inventory incomplete or duplicated')
    summary = []
    for task in tasks:
        summary.append({k: task[k] for k in ('process', 'attempt', 'group', 'status', 'cache', 'tool', 'image_manifest_sha256',
                                           'command_sha256', 'requested_cpus', 'requested_memory_bytes', 'cpu_seconds', 'peak_rss_bytes', 'inputs', 'outputs')}
                       | {'task_identity_sha256': hashlib.sha256(task['task_id'].encode()).hexdigest(),
                          'submitted_offset_seconds': task['submitted'] - execution['started'],
                          'started_offset_seconds': task['started'] - execution['started'],
                          'completed_offset_seconds': task['completed'] - execution['started'],
                          'missing_reasons': {k: 'Native task observation unavailable.' for k in task['missing_reasons']}})
    resources = {}
    for group in GROUPS:
        selected = [t for t in tasks if t['group'] == group]
        comparable = all(t['cache'] == 'miss' for t in selected)
        row = {'wall_seconds': max(t['completed'] for t in selected) - min(t['started'] for t in selected) if comparable else None,
               'cpu_seconds': sum(t['cpu_seconds'] for t in selected) if comparable and all(t['cpu_seconds'] is not None for t in selected) else None,
               'peak_rss_bytes': selected[0]['peak_rss_bytes'] if comparable and len(selected) == 1 else None}
        row['missing_reasons'] = {k: ('Cached or unknown-cache tasks are not uncached resource measurements.' if not comparable
                                     else 'Unavailable native observation or no simultaneous aggregate measurement.') for k, v in row.items() if v is None}
        resources[group] = row
    resources['total'] = {'wall_seconds': execution['completed'] - execution['started'], 'cpu_seconds': None, 'peak_rss_bytes': None,
                          'missing_reasons': {'cpu_seconds': 'End-to-end CPU including orchestration was not measured.',
                                              'peak_rss_bytes': 'Concurrent end-to-end peak RSS was not measured.'}}
    return resources, {'backend': execution['backend'], 'nextflow': execution['nextflow'], 'parser': execution['parser'],
                       'workflow_sha256': execution['workflow_sha256'], 'architecture': 'x86_64', 'accelerators': 0,
                       'elapsed_wall_seconds': resources['total']['wall_seconds'],
                       'summed_task_wall_seconds': sum(t['completed'] - t['started'] for t in tasks if t['cache'] == 'miss'),
                       'summed_task_wall_scope': 'Observed cache misses only; includes failed attempts.', 'tasks': summary}


def derive(inventory: dict, receipts: dict) -> tuple[dict, dict]:
    """Validate actual receipt joins and derive the compatible public v1 record."""
    require(set(receipts) == set(ROLES), 'incomplete private acceptance inventory')
    manifest = validate_manifest(receipts['inputs'])
    scientific, runtime, execution = (receipts[k] for k in ('scientific', 'runtime', 'execution'))
    require(scientific.get('kind') == 'cloud_scientific_evidence' and scientific.get('canonical') is False
            and scientific.get('status') == 'pending_canonical_bundle_qualification', 'private collector state differs')
    auth, shared = scientific['authentication'], scientific['shared']
    passed(auth, 'cloud_input_authentication'); passed(shared, 'cloud_shared_bam')
    passed(runtime, 'cloud_runtime_qualification'); passed(execution, 'cloud_execution_receipt')
    private_run = execution['run_id']
    require(isinstance(private_run, str) and private_run and execution['sample'] == 'HG001' and execution['synthetic'] is False,
            'real HG001 execution receipt required')
    require(auth['repository_sha'] == manifest['repository_sha'] == execution['repository_sha'] == runtime['repository_sha'],
            'source revision lineage mismatch')
    require(execution['package_version'] == runtime['package_version'] == inventory['package_version'], 'package version lineage mismatch')
    require(auth['manifest_sha256'] == inventory['receipts']['inputs']['sha256'], 'authenticated input manifest differs')
    require(auth['backend'] == runtime['backend'] == execution['backend'], 'backend lineage mismatch')
    domain = DOMAINS['hg001_chr20_22_coding']
    require(auth['domain'] == scientific['domain'] == domain, 'fixed evaluation denominator differs')
    require(manifest['assets']['evaluation']['sha256'] == domain['sha256']
            and manifest['assets']['calling_full']['sha256'] == EXPECTED['R_call'][2], 'fixed domain artifact identities differ')
    require(runtime['images'] == tool_images() and runtime['architecture'] == 'x86_64'
            and runtime['representative_positive_callers'] == {'gatk': True, 'deepvariant': True}
            and runtime['full_cloud_workflow_qualified'] is True and runtime['normalization_benchmark_qualified'] is True,
            'full native managed runtime qualification missing')
    require((runtime['backend'], runtime['nextflow'], runtime['parser']) in
            (('healthomics', '26.04.0', 'v2'), ('awsbatch', '26.04.6', 'v2')), 'unqualified backend engine/parser')
    tools = {}
    for config in ('m3-tools.json', 'm4-tools.json', 'm5-tools.json'):
        tools.update(json.loads(config_path(config).read_text())['tools'])
    tools['bwa'] = load_assets()['aligner']
    require(set(runtime['observed_tools']) == set(tool_images()) | {'support'}, 'native tool observation inventory missing')
    for name, observed in runtime['observed_tools'].items():
        sha(observed['image_manifest_sha256']); sha(observed['image_config_sha256']); sha(observed['version_output_sha256'])
        if name != 'support':
            require(observed['upstream_image'] == tool_images()[name] and observed['version'] ==
                    tools[name].get('expected_reported_version', tools[name].get('version')), 'native tool version/image pin differs')
    for role in ('reference', 'index', 'known_sites', 'runtime'):
        require(auth['qualifications'][role] == inventory['receipts'][role]['sha256'] == manifest['qualifications'][role]['sha256'],
                'qualified input receipt lineage differs')
        require(inventory['receipts'][role]['bytes'] == manifest['qualifications'][role]['bytes'], 'qualified input receipt byte count differs')
    reference, index, known = (receipts[k] for k in ('reference', 'index', 'known_sites'))
    dictionary = load_assets()['reference_dictionary']; reference_id = digest_json(dictionary)
    require(reference['kind'] == 'canonical_reference_asset' and reference['status'] == 'base_identity_verified'
            and reference['complete_base_identity'] is True and reference['contigs'] == dictionary
            and reference['reference_id'] == reference_id, 'complete-reference base identity missing')
    require(index['kind'] == 'canonical_bwa_index_asset' and index['status'] == 'index_qualified'
            and index['reference'] == reference and index['reference_id'] == reference_id and index['complete_base_identity'] is True
            and index['tool'] == load_assets()['aligner'] and index['construction'] ==
            {'algorithm': 'bwtsw', 'complete_reference': True, 'command': ['bwa', 'index', '-a', 'bwtsw', 'reference.fa']}, 'classic full-reference BWA gate differs')
    probe = index['functional_probes']
    require(probe['method'] == 'fixed_context_exact_reads_v1' and probe['all_expected_loci_observed'] is True
            and probe['sampled_only'] is True and len(probe['reads']) == 36, 'fixed index probe receipt missing')
    sha(probe['sam_sha256'])
    contexts = [(chrom, context, reverse) for chrom in ('chr1', 'chr2', 'chr20', 'chr21', 'chr22', 'chrX')
                for context in ('ordinary', 'high_gc', 'homopolymer_flank') for reverse in (False, True)]
    lengths = {row['name']: row['length'] for row in dictionary}
    for number_, (read, context) in enumerate(zip(probe['reads'], contexts)):
        require(set(read) == {'name', 'contig', 'position', 'reverse', 'context', 'read_sha256'}
                and (read['contig'], read['context'], read['reverse']) == context and read['name'] == f'probe{number_:03d}'
                and type(read['reverse']) is bool and type(read['position']) is int
                and 1 <= read['position'] <= lengths[read['contig']] - 150, 'fixed index probe inventory differs')
        sha(read['read_sha256'])
    require(re.findall(r'(?m)^Version: (\S+)\s*$', index['observed_version_text']) == ['0.7.17-r1188'], 'index executable version differs')
    require(known['kind'] == 'canonical_bqsr_asset' and known['reference_id'] == reference_id and known['benchmark_truth_used'] is False
            and known['source_contract_sha256'] == digest_json(load_assets()['known_sites']), 'independent known-sites lineage missing')
    sources = [item for item in load_assets()['known_sites'] if item['role'] == 'bqsr_known_sites']
    require(len(known['audits']) == len(sources), 'known-sites audit inventory incomplete')
    for audit, source in zip(known['audits'], sources):
        require(audit['source_id'] == source['id'] and audit['source']['filename'] == source['filename']
                and audit['source']['bytes'] == source['bytes'] and audit['retained_ref_alleles_verified'] is True
                and type(audit['retained_records']) is int and audit['retained_records'] > 0, 'known-sites independent REF/source audit differs')
        sha(audit['source']['sha256'])
    for role, names in [('reference', ('reference', 'reference_fai', 'reference_dict')),
                        ('index', tuple(k for k in ASSETS if k.startswith('bwa_'))),
                        ('known_sites', tuple(k for k in ASSETS if k.startswith('known_')))]:
        files = {item['filename']: {k: item[k] for k in ('sha256', 'bytes')} for item in receipts[role]['files']}
        for name in names:
            require(files[ASSETS[name]] == {k: manifest['assets'][name][k] for k in ('sha256', 'bytes')}, 'asset/output receipt differs')
    for name in ('reference', 'reference_fai', 'reference_dict'):
        require(auth['reference_outputs'][ASSETS[name]] == {k: manifest['assets'][name][k] for k in ('sha256', 'bytes')}, 'reference authentication differs')
    bam = shared['bam_validation']
    require(type(auth['fastq_pairs']) is int and auth['fastq_pairs'] > 0 and bam['primary_records'] == 2 * auth['fastq_pairs']
            and bam['sample'] == 'HG001' and bam['dictionary_contigs'] == len(dictionary)
            and bam['mapped_records'] > 0 and bam['mapped_records_with_oq'] == bam['mapped_records'], 'shared BAM/OQ gate failed')
    require(shared['quality_contract'] == {'gatk': 'recalibrated_QUAL', 'deepvariant': 'retained_OQ'}, 'quality contract differs')
    physical = {'bam_sha256': identity(shared['outputs']['shared.bam'])['sha256'],
                'bai_sha256': identity(shared['outputs']['shared.bam.bai'])['sha256'],
                'reference_sha256': auth['reference_outputs']['reference.fa']['sha256'],
                'calling_regions_sha256': identity(auth['calling_regions'])['sha256']}
    for role in ('preprocessing', 'callers', 'benchmark', 'resume', 'durable'):
        passed(receipts[role], f'cloud_{role}_receipt', private_run)
        require(receipts[role]['execution_sha256'] == inventory['receipts']['execution']['sha256'], 'receipt execution lineage mismatch')
    pre = receipts['preprocessing']
    require(pre['shared_inputs'] == physical and pre['duplicates_retained'] is True and pre['coordinate_sorted'] is True
            and pre['original_qualities_verified'] is True and pre['known_sites_sha256'] == inventory['receipts']['known_sites']['sha256']
            and pre['truth_access'] == 'downstream_only_dataflow_shared_work_storage', 'preprocessing/truth isolation evidence differs')
    benchmark = receipts['benchmark']
    require(benchmark['count_semantics'] == COUNT_SEMANTICS and benchmark['domain'] == domain
            and benchmark['genotype_aware'] is True and benchmark['normalization'] == 'bcftools_norm_split_refcheck_m5'
            and benchmark['truth_sha256'] == manifest['assets']['truth']['sha256'], 'benchmark semantics/domain/truth differs')
    caller_records = receipts['callers']['callers']
    require(set(caller_records) == set(scientific['callers']) == set(benchmark['callers']) == {'gatk', 'deepvariant'}, 'caller comparison incomplete')
    resources, observed_execution = execution_summary(execution, runtime)
    truth_hashes = {manifest['assets'][name]['sha256'] for name in ('truth', 'truth_tbi', 'confidence', 'evaluation')}
    for task in execution['tasks']:
        if task['process'] != 'CLOUD_AUTHENTICATE' and task['group'] != 'common_downstream':
            require(not truth_hashes.intersection(task['inputs']), 'truth entered preprocessing or caller task dataflow')
    outputs = dict(shared['outputs'])
    callers = {}
    for name, quality in (('gatk', 'QUAL'), ('deepvariant', 'OQ')):
        caller = caller_records[name]; bench = benchmark['callers'][name]
        require(caller['shared_inputs'] == physical and caller['quality_source'] == quality, 'caller physical input/quality asymmetry')
        require(caller['tool_image_manifest_sha256'] == runtime['observed_tools'][name]['image_manifest_sha256'], 'caller image lineage differs')
        require(identity(caller['raw_vcf']) == bench['raw_vcf'] and identity(caller['normalized_vcf']) == bench['normalized_vcf'], 'raw/normalized lineage differs')
        require(bench['partitions'] == scientific['callers'][name]['partitions'], 'RTG partition lineage mismatch')
        rows = scientific['callers'][name]['metrics']
        require(set(rows) == {'SNP', 'INDEL', 'OTHER'}, 'metric variant classes differ')
        for kind, row in rows.items():
            require(row == metrics(*(row[k] for k in COUNT_SEMANTICS)) == metrics(*(bench['counts'][kind][k] for k in COUNT_SEMANTICS)),
                    'query/truth counts, arithmetic or missingness differ')
        task = [t for t in execution['tasks'] if t['task_id'] == caller['task_id'] and t['attempt'] == caller['attempt']]
        require(len(task) == 1 and task[0]['status'] == 'succeeded' and task[0]['group'] == name and task[0]['tool'] == name
                and set(physical.values()).issubset(task[0]['inputs']) and caller['raw_vcf']['sha256'] in task[0]['outputs'], 'caller native task/artifact lineage differs')
        bench_tasks = [t for t in execution['tasks'] if t['task_id'] == bench['task_id'] and t['attempt'] == bench['attempt']]
        require(len(bench_tasks) == 1 and bench_tasks[0]['process'] == 'CLOUD_VCFEVAL' and bench_tasks[0]['status'] == 'succeeded'
                and caller['normalized_vcf']['sha256'] in bench_tasks[0]['inputs']
                and {item['sha256'] for item in bench['partitions'].values()}.issubset(bench_tasks[0]['outputs']), 'benchmark native task/artifact lineage differs')
        outputs.update({name + '-raw': caller['raw_vcf'], name + '-normalized': caller['normalized_vcf']})
        outputs.update({name + '-' + key: identity(item) for key, item in bench['partitions'].items()})
        require(set(COUNT_SEMANTICS.values()).issubset(bench['partitions']), 'missing RTG split partitions')
        callers[name] = {'quality_source': quality, 'shared_inputs': physical, 'raw_vcf_sha256': caller['raw_vcf']['sha256'],
                         'normalized_vcf_sha256': caller['normalized_vcf']['sha256'], 'metrics': rows}
    dv = caller_records['deepvariant']
    require(dv['execution_mode'] == 'cpu' and dv['model_type'] == 'WES' and dv['use_original_quality_scores'] is True
            and dv['postprocess_cpus'] == 0, 'CPU WES/OQ invocation differs')
    model_before = _model_inventory(dv['model_before'], tools['deepvariant'])
    require(model_before == _model_inventory(dv['model_after'], tools['deepvariant']), 'DeepVariant model changed during execution')
    resume = receipts['resume']
    require(resume['backend'] == execution['backend'] and resume['nextflow'] == execution['nextflow'] and resume['parser'] == execution['parser']
            and resume['workflow_sha256'] == execution['workflow_sha256'] and resume['unchanged_reused'] is True
            and resume['invalidated'] == {k: True for k in ('parameter', 'input_content', 'reference', 'domain', 'container', 'command')}, 'managed resume/cache qualification incomplete')
    cases = resume['cases']
    require(set(cases) == {'first', 'unchanged', *resume['invalidated']}, 'managed cache observation cases incomplete')
    for name, case in cases.items():
        require(set(case) == {'backend_run_id', 'task_identity', 'task_cache_key', 'input_identity_sha256', 'output_sha256', 'cache_hit', 'backend_receipt_sha256'},
                'managed cache observation fields differ')
        require(all(isinstance(case[k], str) and case[k] for k in ('backend_run_id', 'task_identity', 'task_cache_key')), 'native cache identity absent')
        for key in ('input_identity_sha256', 'output_sha256', 'backend_receipt_sha256'):
            sha(case[key])
        require(case['cache_hit'] is (name == 'unchanged'), 'cache hit observation contradicts case')
        if name == 'unchanged':
            require(all(case[k] == cases['first'][k] for k in ('task_cache_key', 'input_identity_sha256', 'output_sha256')), 'unchanged task did not reuse the same evidence')
        elif name != 'first':
            require(case['task_cache_key'] != cases['first']['task_cache_key'] and case['input_identity_sha256'] != cases['first']['input_identity_sha256'],
                    'changed dependency reused a stale cache identity')
    durable = receipts['durable']
    require(durable['verification'] == 'whole_object_sha256' and durable['completion_marker_written_last'] is True,
            'durable destination rehash/marker ordering missing')
    observed = {item['sha256']: item for item in durable['objects']}
    require(len(observed) == len(durable['objects']), 'duplicate durable artifact identity')
    for item in outputs.values():
        found = observed.get(item['sha256'], {})
        require(found.get('bytes') == item['bytes'] and isinstance(found.get('version_id'), str) and found['version_id']
                and found.get('destination_sha256') == item['sha256'], 'durable output rehash/version receipt missing')
    run_id = 'cloud-' + hashlib.sha256(private_run.encode()).hexdigest()[:24]
    public = {}
    role_sources = {'sources': ('inputs', 'scientific'), 'reference': ('reference',), 'index': ('index',),
                    'domain': ('inputs', 'scientific', 'benchmark'), 'runtime': ('runtime', 'execution'),
                    'preprocessing': ('preprocessing', 'known_sites', 'scientific'), 'gatk': ('callers', 'execution'),
                    'deepvariant': ('callers', 'execution'), 'benchmark': ('benchmark', 'scientific', 'durable'), 'resume': ('resume',)}
    for role, sources in role_sources.items():
        public[role + '.json'] = {'kind': role, 'status': 'passed', 'run_id': run_id,
                                  'private_receipt_sha256': {key: inventory['receipts'][key]['sha256'] for key in sources}}
    public['reference.json']['dictionary_sha256'] = reference_id
    public['index.json']['functional_probe_sam_sha256'] = probe['sam_sha256']
    public['deepvariant.json']['model_files'] = model_before
    public['preprocessing.json']['shared_inputs'] = physical
    public['benchmark.json']['count_semantics'] = COUNT_SEMANTICS
    public['runtime.json']['execution'] = observed_execution
    public['runtime.json']['observed_tools'] = {name: {k: data[k] for k in ('image_manifest_sha256', 'image_config_sha256', 'version_output_sha256')}
                                                for name, data in runtime['observed_tools'].items()}
    public['resume.json']['cases'] = {name: {k: case[k] for k in ('input_identity_sha256', 'output_sha256', 'cache_hit', 'backend_receipt_sha256')}
                                     for name, case in cases.items()}
    qualification = {role: {'artifact': role + '.json', 'sha256': hashlib.sha256(encoded(value)).hexdigest()}
                     for filename, value in public.items() for role in (filename[:-5],)}
    record = {'schema_version': '1.0.0', 'kind': 'canonical_results', 'status': 'complete', 'synthetic': False, 'canonical': True,
              'run_id': run_id, 'repository_sha': execution['repository_sha'], 'package_version': inventory['package_version'],
              'scope': 'hg001_chr20_22_coding', 'sample': 'HG001', 'domain': domain, 'shared_inputs': physical,
              'alignment': {'aligner': 'bwa', 'version': '0.7.17-r1188', 'runtime_identity': 'sha256:' + runtime['observed_tools']['bwa']['image_manifest_sha256']},
              'callers': callers, 'resources': resources, 'coverage': None,
              'coverage_missing_reason': 'No accepted coverage observation over the fixed evaluation BED was supplied.',
              'qualification': qualification, 'environments': [{'name': execution['backend'], 'status': 'executed', 'evidence': 'runtime.json'}],
              'limitations': list(REQUIRED_LIMITATIONS) + ['Truth isolation is enforced by dataflow; workflow roles and work storage are shared.',
                                                          'Group wall times are elapsed intervals, CPU is summed only when observed, and cache states remain explicit.'],
              'uncertainty': 'One observed run; unavailable native resources and coverage remain unavailable. Task retries and cache states are retained.'}
    return record, public


def publish(inventory_path: Path, inventory_sha256: str, output: Path) -> str:
    """Publish only after every gate; fresh outputs and manifest-last are required."""
    require(not output.exists() and not any(p.is_symlink() for p in (output, *output.parents)), 'public output must be fresh and unlinked')
    inventory, receipts = load_inventory(inventory_path, inventory_sha256)
    record, public = derive(inventory, receipts)
    return write_public_bundle(output, record, public)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--inventory-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps({'manifest_sha256': publish(args.inventory, args.inventory_sha256, args.output)}))


if __name__ == '__main__':
    main()
