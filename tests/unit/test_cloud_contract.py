"""Scientific input/cache and native-container regression tests; no AWS required."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pytest
from giab_wes_nextflow.cloud_contract import ASSETS, QUALIFICATIONS, cache_identity, load_manifest, tool_images, validate_manifest
from giab_wes_nextflow.cloud_science import include_variants

ROOT = Path(__file__).resolve().parents[2]


def manifest():
    return {'schema_version': '1.0.0', 'kind': 'cloud_canonical_inputs', 'repository_sha': 'a' * 40,
            'sample': 'HG001', 'scope': 'hg001_chr20_22_coding',
            'assets': {role: {'uri': f's3://private-project/source/{role}', 'sha256': 'b' * 64, 'bytes': 1} for role in ASSETS},
            'qualifications': {role: {'uri': f's3://private-project/provenance/{role}.json', 'sha256': 'c' * 64, 'bytes': 1} for role in QUALIFICATIONS}}


def test_exact_inventory_and_identity():
    record = manifest()
    assert validate_manifest(record) is record
    for mutation in ('truth_in_preprocess', 'missing_source', 'etag', 'unsigned_size', 'wrong_scope'):
        changed = deepcopy(record)
        if mutation == 'truth_in_preprocess': changed['assets']['unexpected_truth'] = changed['assets']['truth']
        if mutation == 'missing_source': del changed['assets']['fastq1']
        if mutation == 'etag': changed['assets']['reference']['sha256'] = '0123456789-7'
        if mutation == 'unsigned_size': changed['assets']['reference']['bytes'] = True
        if mutation == 'wrong_scope': changed['scope'] = 'hg001_full_coding'
        with pytest.raises(ValueError): validate_manifest(changed)


@pytest.mark.parametrize('uri', ['https://example.com/a', 's3://bucket/../a', 's3://bucket/a?signature=secret', 's3://bucket/a#v1', 's3://bucket/a;echo', 's3://bucket/a//b', 's3://bucket/a%20b'])
def test_unsafe_or_ambiguous_s3_path_rejected(uri):
    record = manifest(); record['assets']['reference']['uri'] = uri
    with pytest.raises(ValueError): validate_manifest(record)


def test_duplicate_basename_rejected():
    record = manifest(); record['assets']['fastq2']['uri'] = record['assets']['fastq1']['uri']
    with pytest.raises(ValueError, match='basenames'): validate_manifest(record)


def test_manifest_requires_external_hash(tmp_path):
    path = tmp_path / 'manifest.json'; path.write_text(json.dumps(manifest()))
    assert load_manifest(path, hashlib.sha256(path.read_bytes()).hexdigest())['sample'] == 'HG001'
    with pytest.raises(ValueError, match='pin mismatch'): load_manifest(path, 'd' * 64)


def test_cache_binds_scientific_identity_code_and_execution():
    record = manifest(); images = {**tool_images(), 'support': 'example/support@sha256:' + 'e' * 64}
    key = cache_identity(record, images, {'cpus': 4})
    changed = deepcopy(record); changed['assets']['reference']['sha256'] = 'f' * 64
    assert cache_identity(changed, images, {'cpus': 4}) != key
    changed = deepcopy(record); changed['repository_sha'] = 'f' * 40
    assert cache_identity(changed, images, {'cpus': 4}) != key
    assert cache_identity(record, images, {'cpus': 8}) != key
    changed_images = {**images, 'support': 'example/support@sha256:' + 'f' * 64}
    assert cache_identity(record, changed_images, {'cpus': 4}) != key
    with pytest.raises(ValueError, match='immutable'): cache_identity(record, {**images, 'support': 'example/support:latest'}, {})


def test_cloud_dag_uses_direct_pins_and_truth_exclusion():
    tasks = (ROOT / 'modules/cloud/tasks.nf').read_text()
    for caller in ('GATK', 'DEEPVARIANT'):
        body = tasks.split(f'process CLOUD_{caller}_CALL {{')[1].split('\nprocess ')[0]
        inputs = body.split('input:')[1].split('output:')[0]
        assert 'truth' not in inputs and 'manifest' not in inputs
        assert all(f'path {key}' in inputs for key in ('shared', 'reference', 'domain'))
    assert '--emit-original-quals true' in tasks
    assert '--make_examples_extra_args=use_original_quality_scores=true' in tasks
    assert '--model_type=WES' in tasks
    assert '--REMOVE_DUPLICATES false' in tasks
    assert '--all-records --ref-overlap --output-mode split --no-roc --sample-ploidy 2' in tasks
    assert 'cache false' in tasks.split('process CLOUD_BWA_ALIGN')[0]
    assert all(tool not in tasks for tool in ('udocker', 'apptainer', 'podman', 'canonical_runtime'))
    config = (ROOT / 'conf/cloud.config').read_text()
    assert all(image in config for image in tool_images().values())
    assert 'canonical_colab' not in config and 'cloud_allow_spend = false' in config


def test_inclusion_reuses_genotype_aware_canonical_policy(tmp_path):
    reference = tmp_path / 'reference.fa'; reference.write_text('>chr20\nAAAA\n')
    reference.with_name('reference.fa.fai').write_text('chr20\t4\t7\t4\t5\n')
    source = tmp_path / 'sorted.vcf'
    source.write_text('##fileformat=VCFv4.2\n##contig=<ID=chr20,length=4>\n##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tHG001\nchr20\t2\t.\tA\tC\t30\tPASS\t.\tGT\t0/1\n')
    result = include_variants(source, reference, tmp_path / 'included.vcf')
    assert result['status'] == 'passed'
    assert '0/1' in (tmp_path / 'included.vcf').read_text()
    source.write_text(source.read_text().replace('length=4', 'length=5'))
    with pytest.raises(ValueError, match='dictionary incompatible'): include_variants(source, reference, tmp_path / 'rejected.vcf')


def test_bam_gate_reuses_strict_oq_and_pair_count_validation(tmp_path):
    from giab_wes_nextflow.cloud_science import bam_gate
    reference = tmp_path / 'reference.fa'; reference.write_text('>chr20\nAAAA\n')
    reference.with_name('reference.fa.fai').write_text('chr20\t4\t7\t4\t5\n')
    observations = tmp_path / 'observations'; observations.mkdir()
    for name, content in {'shared.bam': 'opaque-bytes', 'shared.bam.bai': 'opaque-index',
                          'quickcheck.txt': '', 'header.sam': '@SQ\tSN:chr20\tLN:4\n@RG\tID:lane\tSM:HG001\n',
                          'records.sam': 'read1\t0\tchr20\t1\t60\t4M\t*\t0\t0\tAAAA\tIIII\tRG:Z:lane\tOQ:Z:JJJJ\nread2\t0\tchr20\t1\t60\t4M\t*\t0\t0\tAAAA\tIIII\tRG:Z:lane\tOQ:Z:JJJJ\n',
                          'mapped.txt': '2\n', 'primary.txt': '2\n', 'idxstats.txt': 'chr20\t4\t2\t0\n'}.items():
        (observations / name).write_text(content)
    auth = tmp_path / 'auth.json'; auth.write_text('{"fastq_pairs":1}')
    result = bam_gate(observations, reference, auth, tmp_path / 'bam.json')
    assert result['bam_validation']['mapped_records_with_oq'] == 2
    assert result['quality_contract'] == {'gatk': 'recalibrated_QUAL', 'deepvariant': 'retained_OQ'}
    (observations / 'records.sam').write_text((observations / 'records.sam').read_text().replace('\tOQ:Z:JJJJ', ''))
    with pytest.raises(ValueError, match='missing retained OQ'): bam_gate(observations, reference, auth, tmp_path / 'bad.json')


def test_authentication_rejects_corrupt_bytes_before_science(tmp_path):
    from giab_wes_nextflow.cloud_science import authenticate
    record = manifest(); path = tmp_path / 'manifest.json'; path.write_text(json.dumps(record))
    inputs = tmp_path / 'inputs'; inputs.mkdir(); (inputs / 'fastq1').write_bytes(b'changed')
    with pytest.raises(ValueError, match='fastq1 input identity mismatch'):
        authenticate(path, hashlib.sha256(path.read_bytes()).hexdigest(), inputs, tmp_path / 'outputs', 'awsbatch')
    assert not (tmp_path / 'outputs/authentication.json').exists()


def test_cloud_cli_requires_explicit_verified_identity(tmp_path):
    import os
    import subprocess
    import sys
    source = ROOT / 'src'
    environment = {**os.environ, 'PYTHONPATH': str(source)}
    command = [sys.executable, '-m', 'giab_wes_nextflow.cloud_science', 'authenticate', '--manifest', str(tmp_path / 'missing.json'), '--inputs', str(tmp_path), '--output', str(tmp_path / 'out'), '--backend', 'awsbatch']
    result = subprocess.run(command, env=environment, capture_output=True, text=True)
    assert result.returncode == 2 and '--manifest-sha256' in result.stderr
    assert not (tmp_path / 'out').exists()


def test_collection_rejects_asymmetric_shared_bytes_before_metrics(tmp_path):
    from giab_wes_nextflow.cloud_science import collect
    reference = tmp_path / 'reference.fa'; reference.write_text('>chr20\nAAAA\n')
    reference.with_name('reference.fa.fai').write_text('chr20\t4\t7\t4\t5\n')
    reference_names = ('reference.fa', 'reference.fa.fai', 'reference.dict')
    auth = tmp_path / 'auth.json'
    auth.write_text(json.dumps({'reference_outputs': {name: {'sha256': 'a' * 64} for name in reference_names}, 'calling_regions': {'sha256': 'a' * 64}}))
    shared = tmp_path / 'shared.json'; shared.write_text(json.dumps({'outputs': {name: {'sha256': 'a' * 64} for name in ('shared.bam', 'shared.bam.bai')}}))
    identities = []
    for caller in ('gatk', 'deepvariant'):
        path = tmp_path / f'{caller}-inputs.sha256'
        path.write_text(''.join('a' * 64 + f'  shared/{name}\n' for name in (*reference_names, 'regions.bed', 'shared.bam', 'shared.bam.bai')))
        identities.append(path)
    identities[1].write_text(identities[1].read_text().replace('a' * 64, 'b' * 64, 1))
    with pytest.raises(ValueError, match='symmetry mismatch'):
        collect([], identities, reference, shared, auth, tmp_path / 'evidence.json')
    assert not (tmp_path / 'evidence.json').exists()
