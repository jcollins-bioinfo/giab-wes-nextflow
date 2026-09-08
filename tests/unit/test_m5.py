"""Verify M5 science boundaries, deterministic inputs and public missingness."""
import gzip
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from jsonschema import ValidationError
from giab_wes_nextflow import m5
from giab_wes_nextflow.m5_fixture import fixture, SAMPLE, EXPECTED


class M5Tests(unittest.TestCase):
    """Exercise real parsers and arithmetic independently of Docker availability."""
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / 'fixture'; self.expected = fixture(self.root)
        self.seqs = m5.reference(self.root/'reference.fa', self.root/'reference.fa.fai', self.root/'reference.dict')

    def test_fixture_determinism_and_oracle(self) -> None:
        other = Path(self.tmp.name).resolve() / 'repeat'
        self.assertEqual(self.expected, fixture(other)); self.assertEqual(EXPECTED['SNP']['fp'], 2)
        h, rows = m5.vcf_rows(self.root/'gatk.vcf', self.seqs, SAMPLE)
        self.assertEqual(len(rows), 8); self.assertTrue(all(r[6] == 'LowQual' for r in rows))
        self.assertEqual(len(m5.selected(rows)[0]), 8)

    def test_arithmetic_distinct_tp_and_missingness(self) -> None:
        for tq in range(4):
            for tt in range(4):
                r = m5.metrics(tq, tt, 2, 1)
                self.assertEqual(r['precision'], tq/(tq+2)); self.assertEqual(r['recall'], tt/(tt+1))
        self.assertEqual(m5.metrics(0,0,1,1)['f1'], 0)
        self.assertIsNone(m5.metrics(0,0,0,0)['f1'])
        self.assertEqual(m5.metrics(1,1,0,0,evaluated=False)['missing_reasons']['f1'], 'empty_domain')
        for x in (-1, True, 0.5):
            with self.assertRaises(ValueError): m5.metrics(x,1,1,1)

    def test_reference_sample_contig_genotype_and_truncation_rejected(self) -> None:
        original = (self.root/'gatk.vcf').read_text()
        for text in (original.replace('SYNM5', 'WRONG'), original.replace('chrM5\t20', 'unknown\t20'), original.replace('\t20\t.\tA\tC', '\t20\t.\tG\tC'), original.replace('\t0/1\n', '\t0/9\n'), original[:-1]):
            p = self.root/'bad.vcf'; p.write_text(text)
            with self.assertRaises(ValueError): m5.vcf_rows(p,self.seqs,SAMPLE)
        p = self.root/'reference.fa.fai'; p.write_text(p.read_text().replace('\t7\t', '\t8\t'))
        with self.assertRaises(ValueError): m5.reference(self.root/'reference.fa',p,self.root/'reference.dict')

    def test_bed_intersection_and_negative(self) -> None:
        a = m5.intervals(self.root/'evaluation.bed', self.seqs); b = m5.intervals(self.root/'confidence.bed',self.seqs)
        self.assertEqual(m5.intersect(a,b,self.seqs), [('chrM5',0,350)])
        self.assertEqual(m5.intersect(a,[],self.seqs), [])
        for text in ('chrM5\t-1\t5\n','chrM5\t5\t501\n','chrM5\t1\t20\nchrM5\t5\t30\n'):
            p=self.root/'bad.bed';p.write_text(text)
            with self.assertRaises(ValueError):m5.intervals(p,self.seqs)

    def test_exclusion_policy_and_duplicate_conflict(self) -> None:
        _, rows=m5.vcf_rows(self.root/'gatk.vcf',self.seqs,SAMPLE)
        for gt,reason in [('0/0','reference_genotype'),('./1','missing_genotype'),('1','non_diploid')]:
            row=rows[0].copy();row[9]=gt; kept,excluded=m5.selected([row]);self.assertFalse(kept);self.assertEqual(excluded,{reason:1})
        p=self.root/'bad.vcf';p.write_text((self.root/'gatk.vcf').read_text()+'\t'.join(rows[-1])+'\n')
        with self.assertRaisesRegex(ValueError,'duplicate'):m5.vcf_rows(p,self.seqs,SAMPLE)

    def test_index_disagreement_and_isolated_runtime(self) -> None:
        runtime=m5.Runtime(self.root)
        with patch.object(runtime,'run',side_effect=['row\n','']):
            with self.assertRaisesRegex(ValueError,'index'):m5.index_check(runtime,'query.vcf.gz',self.seqs)
        class Result:
            returncode=0;stdout='bcftools 1.24\n';stderr=''
        with patch('giab_wes_nextflow.m5.subprocess.run',return_value=Result()) as run:
            runtime.version('bcftools');args=run.call_args.args[0]
            self.assertEqual(args.count('-v'),1);self.assertIn('--network',args);self.assertIn('none',args)
            self.assertFalse(any('truth' in x or 'confidence' in x for x in args))

    def command(self, tool: str, argv: list[str]) -> dict:
        """Build explicit structural test metadata without invoking a tool."""
        lock = m5.load_json(m5.config_path('m5-tools.json'))['tools']
        return {'tool':tool,'image':lock[tool]['image'],'argv':argv,'exit_code':0,
                'stdout_sha256':'0'*64,'stderr_sha256':'0'*64,'network':'none','mounts':['task']}

    def normalization_data(self) -> dict:
        """Construct complete test metadata for validator negative tests."""
        lock = m5.load_json(m5.config_path('m5-tools.json'))['tools']; item = m5.identity(self.root/'reference.fa')
        argv = ['bcftools','norm','-f','reference.fa','-c','e','-m','-any','--multi-overlaps','0','--old-rec-tag','M5_ORIG','--no-version','-Ov','-o','split.vcf','raw.vcf.gz']
        return {'caller':'gatk','sample':SAMPLE,'inputs':{k:item for k in ['raw_vcf','raw_index','reference','fai','dictionary']},
            'outputs':{n:{**item,'filename':n} for n in ['normalized.vcf.gz','normalized.vcf.gz.tbi']},
            'native_contract':None,'record_count':0,'excluded_records':{},
            'commands':[self.command('bcftools',argv),self.command('bcftools',['bcftools','index','-t','normalized.vcf.gz'])],
            'tools':{'bcftools':{'declared':lock['bcftools'],'observed_version':'bcftools 1.24'}},'warnings':[]}

    def test_schema_and_hash_fail_closed(self) -> None:
        out=self.root/'output';out.mkdir()
        incomplete = self.normalization_data(); del incomplete['inputs']['raw_index']
        with self.assertRaises(ValidationError):
            m5.publish('normalization',out,incomplete)
        record=m5.publish('normalization',out,self.normalization_data())
        record['record_count']=1
        with self.assertRaisesRegex(ValueError,'identity'):m5.validate_record(record,'normalization')
        p=self.root/'link';p.symlink_to(self.root/'reference.fa')
        with self.assertRaises(ValueError):m5.identity(p)
        with gzip.open(self.root/'broken.vcf.gz','wb') as stream:stream.write(b'#CHROM\n')
        with self.assertRaises(ValueError):m5.vcf_rows(self.root/'broken.vcf.gz',self.seqs,SAMPLE)

    def test_rehashed_metric_tamper_rejected(self) -> None:
        """A valid payload hash cannot turn incorrect arithmetic into evidence."""
        out = self.root / 'benchmark'; out.mkdir()
        normdir = self.root/'norm'; normdir.mkdir()
        norm = m5.publish('normalization',normdir,self.normalization_data())
        lock = m5.load_json(m5.config_path('m5-tools.json'))['tools']; item=m5.identity(self.root/'reference.fa')
        command=self.command('rtg',['vcfeval','-b','truth.vcf.gz','-c','query.vcf.gz','-t','reference.sdf','-o','vcfeval','--evaluation-regions','evaluation.bed','--sample',SAMPLE,'--all-records','--output-mode','split','--no-roc','--sample-ploidy','2','--threads','2'])
        record = m5.publish('benchmark',out,{'caller':'gatk','sample':SAMPLE,'domain_id':'full','status':'evaluated','evaluated_bases':350,'interval_count':1,
            'metrics':{t:m5.metrics(**counts) for t,counts in EXPECTED.items()},
            'inputs':{k:item for k in ['truth','truth_index','confidence','domain','reference','normalization']},
            'outputs':{k:item for k in ['evaluation.bed','tp.vcf.gz','tp-baseline.vcf.gz','fp.vcf.gz','fn.vcf.gz']},
            'reference_sdf':{'index':item},'normalization_lineage':norm['payload_sha256'],'truth_normalization':norm,
            'commands':[command],'tools':{'rtg':{'declared':lock['rtg'],'observed_version':'RTG Tools 3.13'}},'warnings':[],
            'canonical_metrics':None,'comparative_cost':None})
        record['metrics']['SNP']['precision'] = 1.0
        record['payload_sha256'] = m5.payload_hash({k:v for k,v in record.items() if k != 'payload_sha256'})
        with self.assertRaisesRegex(ValueError, 'arithmetic'):
            m5.validate_record(record, 'benchmark')


if __name__ == '__main__':
    unittest.main()
