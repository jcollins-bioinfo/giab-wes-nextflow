"""Invented metadata exercises acceptance contracts; these are never real results."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from giab_wes_nextflow import cloud_public as adapter
from giab_wes_nextflow.canonical_asset_reference import digest_json, load_assets
from giab_wes_nextflow.canonical_results import DOMAINS, load_canonical_bundle
from giab_wes_nextflow.cloud_contract import ASSETS, QUALIFICATIONS, tool_images
from giab_wes_nextflow.coding_domain import EXPECTED
from giab_wes_nextflow.m4_contracts import MODEL_FILES
from giab_wes_nextflow.m5 import metrics
from giab_wes_nextflow.resources import config_path


def h(text):
    return hashlib.sha256(text.encode()).hexdigest()


def file_id(text):
    return {'sha256': h(text), 'bytes': 100}


def fixture_receipts():
    """Artificial producer metadata, constructed only inside isolated unit tests."""
    run = 'private-test-run'
    domain = copy.deepcopy(DOMAINS['hg001_chr20_22_coding'])
    assets = {k: {'uri': 's3://example-private-bucket/' + v, **file_id(k)} for k, v in ASSETS.items()}
    assets['evaluation']['sha256'] = domain['sha256']
    assets['calling_full']['sha256'] = EXPECTED['R_call'][2]
    reference_id = digest_json(load_assets()['reference_dictionary'])
    def files(names):
        return [{'filename': ASSETS[k], **file_id(k)} for k in names]
    reference = {'kind': 'canonical_reference_asset', 'status': 'base_identity_verified', 'complete_base_identity': True,
                 'reference_id': reference_id, 'contigs': load_assets()['reference_dictionary'],
                 'files': files(('reference', 'reference_fai', 'reference_dict'))}
    index = {'kind': 'canonical_bwa_index_asset', 'status': 'index_qualified', 'complete_base_identity': True,
             'reference': reference, 'reference_id': reference_id, 'tool': load_assets()['aligner'],
             'observed_version_text': 'Version: 0.7.17-r1188\n',
             'construction': {'algorithm': 'bwtsw', 'complete_reference': True, 'command': ['bwa', 'index', '-a', 'bwtsw', 'reference.fa']},
             'functional_probes': {'method': 'fixed_context_exact_reads_v1', 'all_expected_loci_observed': True,
                                   'sampled_only': True, 'reads': list(range(36)), 'sam_sha256': h('probe')},
             'files': files(k for k in ASSETS if k.startswith('bwa_'))}
    contexts = [(chrom, context, reverse) for chrom in ('chr1', 'chr2', 'chr20', 'chr21', 'chr22', 'chrX')
                for context in ('ordinary', 'high_gc', 'homopolymer_flank') for reverse in (False, True)]
    index['functional_probes']['reads'] = [{'name': f'probe{i:03d}', 'contig': c, 'context': context, 'reverse': reverse,
                                          'position': 1, 'read_sha256': h(f'probe{i}')} for i, (c, context, reverse) in enumerate(contexts)]
    known = {'kind': 'canonical_bqsr_asset', 'reference_id': reference_id, 'benchmark_truth_used': False,
             'source_contract_sha256': digest_json(load_assets()['known_sites']), 'files': files(k for k in ASSETS if k.startswith('known_'))}
    known['audits'] = [{'source_id': source['id'], 'source': {'filename': source['filename'], 'bytes': source['bytes'], 'sha256': h(source['id'])},
                       'retained_ref_alleles_verified': True, 'retained_records': 1}
                      for source in load_assets()['known_sites'] if source['role'] == 'bqsr_known_sites']
    versions = {'bwa': '0.7.17-r1188', 'samtools': '1.24', 'gatk': '4.7.0.0', 'deepvariant': '1.10.0', 'bcftools': '1.24', 'rtg': '3.13'}
    observed = {name: {'upstream_image': image, 'version': versions[name], 'image_manifest_sha256': h(name + '-manifest'),
                       'image_config_sha256': h(name + '-config'), 'version_output_sha256': h(name + '-version')}
                for name, image in tool_images().items()}
    observed['support'] = {k: h(k) for k in ('image_manifest_sha256', 'image_config_sha256', 'version_output_sha256')}
    runtime = {'kind': 'cloud_runtime_qualification', 'status': 'passed', 'repository_sha': 'a' * 40, 'backend': 'healthomics',
               'images': tool_images(), 'observed_tools': observed, 'architecture': 'x86_64', 'nextflow': '26.04.0', 'parser': 'v2', 'package_version': '0.0.0-test',
               'representative_positive_callers': {'gatk': True, 'deepvariant': True},
               'full_cloud_workflow_qualified': True, 'normalization_benchmark_qualified': True}
    receipts = {'reference': reference, 'index': index, 'known_sites': known, 'runtime': runtime}
    qualification = {k: {'uri': 's3://example-private-bucket/' + k + '.json', 'sha256': hashlib.sha256(adapter.encoded(receipts[k])).hexdigest(),
                         'bytes': len(adapter.encoded(receipts[k]))} for k in QUALIFICATIONS}
    inputs = {'schema_version': '1.0.0', 'kind': 'cloud_canonical_inputs', 'repository_sha': 'a' * 40,
              'sample': 'HG001', 'scope': 'hg001_chr20_22_coding', 'assets': assets, 'qualifications': qualification}
    auth = {'kind': 'cloud_input_authentication', 'status': 'passed', 'manifest_sha256': hashlib.sha256(adapter.encoded(inputs)).hexdigest(),
            'repository_sha': 'a' * 40, 'backend': 'healthomics', 'domain': domain, 'fastq_pairs': 2,
            'reference_outputs': {ASSETS[k]: file_id(k) for k in ('reference', 'reference_fai', 'reference_dict')},
            'calling_regions': file_id('regions'), 'qualifications': {k: v['sha256'] for k, v in qualification.items()}}
    shared = {'kind': 'cloud_shared_bam', 'status': 'passed', 'bam_validation': {'primary_records': 4, 'sample': 'HG001',
              'dictionary_contigs': 195, 'mapped_records': 4, 'mapped_records_with_oq': 4},
              'quality_contract': {'gatk': 'recalibrated_QUAL', 'deepvariant': 'retained_OQ'},
              'outputs': {k: file_id(k) for k in ('shared.bam', 'shared.bam.bai')}}
    physical = {'bam_sha256': h('shared.bam'), 'bai_sha256': h('shared.bam.bai'), 'reference_sha256': h('reference'), 'calling_regions_sha256': h('regions')}
    tasks = []
    for process, (tool, group, count) in adapter.PROCESSES.items():
      for number in range(count):
        i = len(tasks)
        task_id = 'private-task-' + group if group in ('gatk', 'deepvariant') else process + str(number)
        tasks.append({'task_id': task_id, 'process': process, 'attempt': 1, 'group': group,
                      'status': 'succeeded', 'cache': 'miss', 'tool': tool, 'image_manifest_sha256': observed[tool]['image_manifest_sha256'],
                      'command_sha256': h(group + '-command'), 'submitted': 1 + i * 2, 'started': 2 + i * 2, 'completed': 3 + i * 2,
                      'requested_cpus': 2, 'requested_memory_bytes': 1000000, 'cpu_seconds': None, 'peak_rss_bytes': None,
                      'missing_reasons': {'cpu_seconds': 'native metric absent', 'peak_rss_bytes': 'native metric absent'},
                      'inputs': list(physical.values()), 'outputs': [h(group + '-raw')]})
    execution = {'kind': 'cloud_execution_receipt', 'status': 'passed', 'run_id': run, 'repository_sha': 'a' * 40,
                 'sample': 'HG001', 'synthetic': False, 'backend': 'healthomics', 'nextflow': '26.04.0', 'parser': 'v2', 'package_version': '0.0.0-test',
                 'architecture': 'x86_64', 'accelerators': 0, 'workflow_sha256': h('workflow'), 'started': 0, 'completed': 100, 'tasks': tasks}
    base = {'status': 'passed', 'run_id': run, 'execution_sha256': hashlib.sha256(adapter.encoded(execution)).hexdigest()}
    scientific_callers, callers, benchmark_callers, outputs = {}, {}, {}, list(shared['outputs'].values())
    for name, quality in (('gatk', 'QUAL'), ('deepvariant', 'OQ')):
        rows = {'SNP': metrics(2, 3, 1, 1), 'INDEL': metrics(0, 0, 0, 0), 'OTHER': metrics(0, 0, 0, 0)}
        partitions = {k: file_id(name + '-' + k) for k in adapter.COUNT_SEMANTICS.values()}
        scientific_callers[name] = {'metrics': rows, 'partitions': partitions}
        callers[name] = {'shared_inputs': physical, 'quality_source': quality, 'tool_image_manifest_sha256': observed[name]['image_manifest_sha256'],
                         'raw_vcf': file_id(name + '-raw'), 'normalized_vcf': file_id(name + '-normalized'),
                         'task_id': 'private-task-' + name, 'attempt': 1}
        benchmark_callers[name] = {'raw_vcf': callers[name]['raw_vcf'], 'normalized_vcf': callers[name]['normalized_vcf'],
                                  'partitions': partitions, 'counts': {kind: {k: row[k] for k in adapter.COUNT_SEMANTICS} for kind, row in rows.items()},
                                  'task_id': 'CLOUD_VCFEVAL' + str(int(name == 'deepvariant')), 'attempt': 1}
        bench_task = next(t for t in tasks if t['task_id'] == benchmark_callers[name]['task_id'])
        bench_task['inputs'] = [callers[name]['normalized_vcf']['sha256']]
        bench_task['outputs'] = [item['sha256'] for item in partitions.values()]
        outputs.extend([callers[name]['raw_vcf'], callers[name]['normalized_vcf'], *partitions.values()])
    pinned_model = json.loads(config_path('m4-tools.json').read_text())['tools']['deepvariant']['model']
    model = {'model_type': 'WES', 'model_files': [{'filename': k, **file_id(k)} for k in sorted(MODEL_FILES)]}
    for item in model['model_files']:
        if item['filename'] == 'model.example_info.json':
            item.update(sha256=pinned_model['example_info_sha256'], bytes=pinned_model['example_info_bytes'])
    callers['deepvariant'].update(execution_mode='cpu', model_type='WES', use_original_quality_scores=True,
                                  postprocess_cpus=0, model_before=copy.deepcopy(model), model_after=copy.deepcopy(model))
    base['execution_sha256'] = hashlib.sha256(adapter.encoded(execution)).hexdigest()
    cache_cases = {name: {'backend_run_id': 'private-' + name, 'task_identity': 'private-task-' + name,
                         'task_cache_key': 'cache-' + ('first' if name == 'unchanged' else name),
                         'input_identity_sha256': h('input-' + ('first' if name == 'unchanged' else name)),
                         'output_sha256': h('output-' + ('first' if name == 'unchanged' else name)),
                         'cache_hit': name == 'unchanged', 'backend_receipt_sha256': h('native-' + name)}
                   for name in ('first', 'unchanged', 'parameter', 'input_content', 'reference', 'domain', 'container', 'command')}
    receipts.update(inputs=inputs, execution=execution,
                    scientific={'kind': 'cloud_scientific_evidence', 'status': 'pending_canonical_bundle_qualification', 'canonical': False,
                                'authentication': auth, 'shared': shared, 'domain': domain, 'callers': scientific_callers},
                    preprocessing={'kind': 'cloud_preprocessing_receipt', **base, 'shared_inputs': physical, 'duplicates_retained': True,
                                   'coordinate_sorted': True, 'original_qualities_verified': True, 'known_sites_sha256': qualification['known_sites']['sha256'],
                                   'truth_access': 'downstream_only_dataflow_shared_work_storage'},
                    callers={'kind': 'cloud_callers_receipt', **base, 'callers': callers},
                    benchmark={'kind': 'cloud_benchmark_receipt', **base, 'count_semantics': adapter.COUNT_SEMANTICS, 'domain': domain,
                               'genotype_aware': True, 'normalization': 'bcftools_norm_split_refcheck_m5', 'truth_sha256': assets['truth']['sha256'], 'callers': benchmark_callers},
                    resume={'kind': 'cloud_resume_receipt', **base, 'backend': 'healthomics', 'nextflow': '26.04.0', 'parser': 'v2',
                            'workflow_sha256': h('workflow'), 'unchanged_reused': True, 'cases': cache_cases,
                            'invalidated': {k: True for k in ('parameter', 'input_content', 'reference', 'domain', 'container', 'command')}},
                    durable={'kind': 'cloud_durable_receipt', **base, 'verification': 'whole_object_sha256', 'completion_marker_written_last': True,
                             'objects': [{**item, 'version_id': 'private-version', 'destination_sha256': item['sha256']} for item in outputs]})
    return receipts


def write_inputs(root, receipts):
    root.mkdir(exist_ok=True)
    inventory = {'schema_version': '1.0.0', 'kind': 'cloud_public_inventory', 'package_version': '0.0.0-test', 'receipts': {}}
    for name, receipt in receipts.items():
        data = adapter.encoded(receipt)
        (root / (name + '.json')).write_bytes(data)
        inventory['receipts'][name] = {'file': name + '.json', 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    raw = adapter.encoded(inventory); (root / 'inventory.json').write_bytes(raw)
    return root / 'inventory.json', hashlib.sha256(raw).hexdigest()


def test_pinned_projection_and_unknown_resources(tmp_path):
    path, pin = write_inputs(tmp_path / 'private', fixture_receipts())
    output = tmp_path / 'public'
    result_pin = adapter.publish(path, pin, output)
    result = load_canonical_bundle(output, result_pin)
    assert result.record['callers']['gatk']['metrics']['SNP']['tp_query'] == 2
    assert result.record['callers']['gatk']['metrics']['SNP']['tp_truth'] == 3
    assert result.record['resources']['gatk']['cpu_seconds'] is None
    assert result.record['resources']['total']['wall_seconds'] == 100
    public_bytes = ''.join(p.read_text() for p in output.iterdir())
    assert 'private-test-run' not in public_bytes and 'private-task' not in public_bytes
    assert 'private-version' not in public_bytes and 's3://' not in public_bytes
    with pytest.raises(ValueError, match='fresh'):
        adapter.publish(path, pin, output)


@pytest.mark.parametrize('mutation', [
    lambda r: r['scientific'].update(canonical=True),
    lambda r: r['execution'].update(synthetic=True),
    lambda r: r['execution'].update(repository_sha='b' * 40),
    lambda r: r['runtime'].update(full_cloud_workflow_qualified=False),
    lambda r: r['runtime']['observed_tools']['gatk'].update(version='4.6.0.0'),
    lambda r: r['scientific']['domain'].update(bases=1),
    lambda r: r['scientific']['shared']['bam_validation'].update(mapped_records_with_oq=0),
    lambda r: r['callers']['callers']['deepvariant'].update(quality_source='QUAL'),
    lambda r: r['callers']['callers']['gatk']['shared_inputs'].update(bam_sha256=h('foreign')),
    lambda r: r['callers']['callers']['deepvariant']['model_after']['model_files'][0].update(sha256=h('changed')),
    lambda r: r['callers']['callers']['gatk']['normalized_vcf'].update(sha256=h('foreign')),
    lambda r: r['benchmark']['callers']['gatk']['counts']['SNP'].update(tp_truth=2),
    lambda r: r['scientific']['callers']['gatk']['metrics']['SNP'].update(precision=1.0),
    lambda r: r['resume']['invalidated'].update(domain=False),
    lambda r: r['durable']['objects'][0].update(destination_sha256=h('foreign')),
    lambda r: r['preprocessing'].update(truth_access='isolated_by_IAM'),
])
def test_negative_acceptance_never_creates_public_output(tmp_path, mutation):
    receipts = fixture_receipts(); mutation(receipts)
    path, pin = write_inputs(tmp_path / 'private', receipts)
    with pytest.raises((ValueError, KeyError)):
        adapter.publish(path, pin, tmp_path / 'public')
    assert not (tmp_path / 'public').exists()


def test_inventory_hash_missing_receipts_and_links(tmp_path):
    path, pin = write_inputs(tmp_path / 'private', fixture_receipts())
    with pytest.raises(ValueError, match='pin'):
        adapter.publish(path, h('wrong pin'), tmp_path / 'out')
    member = path.parent / 'execution.json'; raw = member.read_bytes(); member.write_bytes(raw + b' ')
    with pytest.raises(ValueError, match='byte count'):
        adapter.publish(path, pin, tmp_path / 'out')
    member.write_bytes(raw); moved = tmp_path / 'moved.json'; member.rename(moved); member.symlink_to(moved)
    with pytest.raises(ValueError, match='linked'):
        adapter.publish(path, pin, tmp_path / 'out')


def test_resources_reject_launcher_cpu_mixed_cache_and_duplicate_attempts():
    receipts = fixture_receipts(); execution, runtime = receipts['execution'], receipts['runtime']
    task = next(t for t in execution['tasks'] if t['group'] == 'gatk')
    task['cache'] = 'hit'; task['cpu_seconds'] = 3; task['missing_reasons'].pop('cpu_seconds')
    resources, _ = adapter.execution_summary(execution, runtime)
    assert resources['gatk']['wall_seconds'] is None and resources['gatk']['cpu_seconds'] is None
    task['group'] = 'launcher'
    with pytest.raises(ValueError, match='group'):
        adapter.execution_summary(execution, runtime)
    task['group'] = 'gatk'; execution['tasks'].append(copy.deepcopy(task))
    with pytest.raises(ValueError, match='duplicate task'):
        adapter.execution_summary(execution, runtime)


def test_schema_copies_agree():
    root = Path(__file__).resolve().parents[2]
    assert (root / 'schemas/cloud-public-inventory.schema.json').read_bytes() == (root / 'src/giab_wes_nextflow/data/schemas/cloud-public-inventory.schema.json').read_bytes()
