"""Test public canonical consumer contracts with invented metadata, never real runs."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from giab_wes_nextflow import canonical_results as model
from giab_wes_nextflow.m5 import metrics


def example_result() -> tuple[dict, dict]:
    """Build artificial metadata solely for schema and negative tests."""
    run_id = 'model-test-not-execution'
    receipts = {role + '.json': {'status':'passed','kind':role,'run_id':run_id,'test_only':True} for role in model.QUALIFICATION_ROLES}
    qualification = {role: {'artifact':role+'.json','sha256':hashlib.sha256((json.dumps(receipts[role+'.json'],sort_keys=True,indent=2)+'\n').encode()).hexdigest()} for role in model.QUALIFICATION_ROLES}
    shared = {k:'a'*64 for k in ('bam_sha256','bai_sha256','reference_sha256','calling_regions_sha256')}
    resources = {k:{'wall_seconds':None,'cpu_seconds':None,'peak_rss_bytes':None,
        'missing_reasons':{m:'unmeasured test metadata' for m in ('wall_seconds','cpu_seconds','peak_rss_bytes')}} for k in ('gatk','deepvariant','shared_preprocessing','common_downstream','total')}
    result = {'schema_version':'1.0.0','kind':'canonical_results','status':'complete','synthetic':False,'canonical':True,
        'run_id':run_id,'repository_sha':'b'*40,'package_version':'0.0.0-test','scope':'hg001_chr20_22_coding','sample':'HG001',
        'domain':copy.deepcopy(model.DOMAINS['hg001_chr20_22_coding']),'shared_inputs':shared,
        'alignment':{'aligner':'bwa-mem2','version':'test-only','runtime_identity':'sha256:'+'c'*64},
        'callers':{c:{'quality_source':q,'shared_inputs':copy.deepcopy(shared),'raw_vcf_sha256':'d'*64,'normalized_vcf_sha256':'e'*64,
            'metrics':{'SNP':metrics(2,3,1,1),'INDEL':metrics(0,0,0,0),'OTHER':metrics(0,0,0,0)}} for c,q in [('gatk','QUAL'),('deepvariant','OQ')]},
        'resources':resources,'coverage':None,'coverage_missing_reason':'unmeasured test metadata','qualification':qualification,
        'environments':[{'name':'test-only','status':'configured_only','evidence':None}],
        'limitations':list(model.REQUIRED_LIMITATIONS),'uncertainty':'Artificial test metadata; no actual HG001 execution.'}
    return result,receipts


class CanonicalResultsTests(unittest.TestCase):
    """Exercise trust pins, metric invariants, privacy and typed exports."""
    def setUp(self) -> None:
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()/'bundle';self.record,self.receipts=example_result()

    def test_complete_metadata_and_exports(self) -> None:
        pin=model.write_public_bundle(self.root,self.record,self.receipts)
        data=model.load_canonical_bundle(self.root,pin)
        self.assertEqual(data.record['scope'],'hg001_chr20_22_coding')
        self.assertIn('tp_query\ttp_truth',data.metrics_tsv)
        self.assertIn('zero_query_denominator',data.metrics_tsv)
        self.assertIn('unmeasured test metadata',data.resources_tsv)
        self.assertEqual(len(data.artifact_inventory),11)

    def test_domain_sample_quality_and_metrics_fail_closed(self) -> None:
        for change in ('synthetic','domain','quality','bam','precision','missing','coverage'):
            with self.subTest(change=change):
                r=copy.deepcopy(self.record)
                if change=='synthetic':r['synthetic']=True
                if change=='domain':r['domain']['bases']-=1
                if change=='quality':r['callers']['deepvariant']['quality_source']='QUAL'
                if change=='bam':r['callers']['gatk']['shared_inputs']['bam_sha256']='f'*64
                if change=='precision':r['callers']['gatk']['metrics']['SNP']['precision']=1
                if change=='missing':r['resources']['gatk']['missing_reasons']={}
                if change=='coverage':r['coverage_missing_reason']=None
                with self.assertRaises(Exception):model.validate_result(r)

    def test_hash_replacement_and_extra_members_rejected(self) -> None:
        pin=model.write_public_bundle(self.root,self.record,self.receipts)
        with self.assertRaisesRegex(ValueError,'identity'):model.load_canonical_bundle(self.root,'f'*64)
        (self.root/'extra.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'inventory|manifest'):model.load_canonical_bundle(self.root,pin)
        (self.root/'extra.json').unlink();p=self.root/'result.json';p.write_bytes(p.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'hash|size'):model.load_canonical_bundle(self.root,pin)

    def test_failed_receipt_and_privacy_never_publish_marker(self) -> None:
        self.receipts['runtime.json']['status']='failed'
        self.record['qualification']['runtime']['sha256']=hashlib.sha256((json.dumps(self.receipts['runtime.json'],sort_keys=True,indent=2)+'\n').encode()).hexdigest()
        with self.assertRaisesRegex(ValueError,'passed gate'):model.write_public_bundle(self.root,self.record,self.receipts)
        self.assertFalse((self.root/'manifest.json').exists())
        for unsafe in ('/Users/person/private/file','https://example.test/x?sig=secret','A'*100,'DO NOT ACCESS WITH CHATGPT'):
            with self.assertRaises(ValueError):model.safe_metadata({'value':unsafe})

    def test_links_traversal_duplicate_keys_and_nan(self) -> None:
        pin=model.write_public_bundle(self.root,self.record,self.receipts);p=self.root/'runtime.json';raw=p.read_bytes();p.unlink()
        target=self.root.parent/'target.json';target.write_bytes(raw);p.symlink_to(target)
        with self.assertRaisesRegex(ValueError,'linked'):model.load_canonical_bundle(self.root,pin)
        for n in ('../secret.json','raw.vcf','/tmp/a.json','a/b.json'):
            with self.assertRaises(ValueError):model._name(n)
        for raw in (b'{"x":1,"x":2}',b'{"x":NaN}'):
            with self.assertRaises(ValueError):model._json(raw)


if __name__=='__main__':unittest.main()
