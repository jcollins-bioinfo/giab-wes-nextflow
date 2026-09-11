"""Frozen invented full-DAG input gates, without claiming native/backend execution."""
import gzip
import json

import pytest

from giab_wes_nextflow import cloud_qualification as q
from giab_wes_nextflow.canonical_science import file_id
from giab_wes_nextflow.cloud_contract import validate_manifest


@pytest.fixture
def prepared(tmp_path):
    source = tmp_path / 'prepared'
    q.generate(source)
    for suffix in ('amb', 'bwt', 'pac', 'sa'):
        (source / ('reference.fa.' + suffix)).write_bytes(b'invented-index-placeholder')
    (source / 'reference.fa.ann').write_text('20000 2 11\n')
    for name in ('truth.vcf.gz', 'bqsr_dbsnp138.no-alt.vcf.gz', 'bqsr_known_indels.no-alt.vcf.gz', 'bqsr_mills.no-alt.vcf.gz'):
        raw = source / ('truth.vcf' if name == 'truth.vcf.gz' else 'known-sites.vcf')
        (source / name).write_bytes(gzip.compress(raw.read_bytes()))
        (source / (name + '.tbi')).write_bytes(b'invented-tabix-placeholder')
    target = tmp_path / 'manifested'
    q.make_manifest(source,target,'a'*40)
    return target


def test_frozen_manifest_cannot_pass_canonical_contract(prepared):
    manifest = json.loads((prepared / 'manifest.json').read_text())
    with pytest.raises(ValueError):
        validate_manifest(manifest)
    assert manifest['synthetic'] is True and manifest['canonical'] is False


def test_regenerated_nonhuman_inputs_preserve_denominator(prepared,tmp_path):
    receipt = q.authenticate(prepared/'manifest.json',(prepared/'manifest.sha256').read_text().strip(),
                             prepared/'inputs',tmp_path/'authenticated','healthomics')
    assert receipt['kind'] == q.AUTH_KIND
    assert receipt['fastq_pairs'] == 264
    assert receipt['domain']['evaluated_bases'] == 20000
    assert receipt['domain']['interval_count'] == 2
    assert receipt['canonical'] is False


def test_modified_input_fails_even_with_self_rehashed_manifest(prepared,tmp_path):
    path = prepared/'inputs/reads_1.fastq.gz'
    path.write_bytes(gzip.compress(gzip.decompress(path.read_bytes()).replace(b'A',b'C',1)))
    manifest = prepared/'manifest.json'
    record = json.loads(manifest.read_text())
    record['files'][path.name] = file_id(path)
    manifest.write_text(json.dumps(record))
    with pytest.raises(ValueError,match='frozen nonhuman'):
        q.authenticate(manifest,file_id(manifest)['sha256'],prepared/'inputs',tmp_path/'rejected','healthomics')


def test_original_oq_identity_includes_unmapped_reads(prepared,tmp_path):
    receipt = q.authenticate(prepared/'manifest.json',(prepared/'manifest.sha256').read_text().strip(),
                             prepared/'inputs',tmp_path/'authenticated','healthomics')
    records = tmp_path/'records'
    records.mkdir()
    sam = []
    for name, row in receipt['fixture_expectations']['read_expectations'].items():
        flag = (64 if name.endswith('/1') else 128) | 4
        quality = row['original_qualities']
        sam.append(f"{row['qname']}\t{flag}\t*\t0\t0\t*\t*\t0\t0\t{'N'*len(quality)}\t{quality}\tOQ:Z:{quality}\n")
    path = records/'records.sam'
    path.write_text(''.join(sam))
    assert q.validate_original_qualities(records,receipt) == 528
    path.write_text(''.join(sam).replace('OQ:Z:','XX:Z:',1))
    with pytest.raises(ValueError,match='OQ identity'):
        q.validate_original_qualities(records,receipt)


def test_dag_acceptance_does_not_qualify_backend_or_cache(tmp_path):
    frozen = q.generate(tmp_path/'fixture')
    row = lambda n: dict(zip(('tp_query','tp_truth','fp','fn'),(n,n,0,0)))
    data = {'canonical':False,'synthetic':True,'authentication':{'kind':q.AUTH_KIND,'recipe':q.RECIPE,
             'canonical':False,'domain':frozen['domain'],'repository_sha':'a'*40},'domain':frozen['domain'],
             'shared':{'original_quality_records_verified':528},
             'callers':{c:{'metrics':{'SNP':row(2),'INDEL':row(0),'OTHER':row(0)}} for c in ('gatk','deepvariant')}}
    source = tmp_path/'cloud-evidence.json'
    source.write_text(json.dumps(data))
    result = q.accept(source,tmp_path/'acceptance.json')
    assert result['scientific_dag_acceptance'] is True
    assert result['full_cloud_workflow_qualified'] is False
    assert result['managed_cache_qualified'] is False
    data['callers']['gatk']['metrics']['SNP']['fn'] = 1
    source.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='counts'):
        q.accept(source,tmp_path/'rejected.json')
