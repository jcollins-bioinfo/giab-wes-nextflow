"""Scientific and restart-boundary tests without external genomic compute."""
from pathlib import Path
import tempfile
import unittest

from giab_wes_nextflow.canonical_checkpoint import completed, inventory, hydrate
from giab_wes_nextflow.canonical_run import resources
from giab_wes_nextflow.canonical_science import indexed_reference, preprocess, stage_file, write_json
from giab_wes_nextflow.m5 import vcf_rows


class CanonicalScienceTests(unittest.TestCase):
    def test_indexed_reference_reads_across_lines_and_boundaries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); reference = root / 'reference.fa'
            reference.write_bytes(b'>chr1\nACGT\nGCTA\nAC\n>chr2\nTTTT\n')
            (root / 'reference.fa.fai').write_text('chr1\t10\t6\t4\t5\nchr2\t4\t25\t4\t5\n')
            seqs = indexed_reference(reference)
            self.assertEqual(seqs['chr1'][2:9], 'GTGCTAA')
            self.assertEqual(seqs['chr1'][8:99], 'AC')
            self.assertEqual(seqs['chr1'][10:12], '')
            self.assertEqual(len(seqs['chr1']), 10)

    def test_reference_mismatch_still_rejected_by_common_vcf_validator(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); ref = root / 'reference.fa'
            ref.write_text('>chr1\nACGT\n'); (root / 'reference.fa.fai').write_text('chr1\t4\t6\t4\t5\n')
            vcf = root / 'test.vcf'
            header = '##fileformat=VCFv4.2\n##contig=<ID=chr1,length=4>\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tHG001\n'
            vcf.write_text(header + 'chr1\t2\t.\tA\tG\t30\tPASS\t.\tGT\t0/1\n')
            with self.assertRaisesRegex(ValueError, 'REF mismatch'):
                vcf_rows(vcf, indexed_reference(ref), 'HG001', split=True)
            vcf.write_text(header + 'chr1\t2\t.\tC\tG\t30\tPASS\t.\tGT\t0/1\n')
            self.assertEqual(len(vcf_rows(vcf, indexed_reference(ref), 'HG001', split=True)[1]), 1)

    def test_truth_cannot_enter_preprocessing_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary).resolve() / 'out'
            with self.assertRaisesRegex(ValueError, 'truth is forbidden'):
                preprocess({'truth': 'forbidden'}, None, output)
            self.assertFalse(output.exists())

    def test_staged_input_is_independent_and_conflicts_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); source = root / 'source'; target = root / 'target'
            source.write_bytes(b'original'); stage_file(source, target)
            target.write_bytes(b'changed')
            self.assertEqual(source.read_bytes(), b'original')
            with self.assertRaisesRegex(ValueError, 'conflict'):
                stage_file(source, target)

    def test_checkpoint_requires_exact_inventory_and_current_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / 'saved'; root.mkdir(); (root / 'receipt.json').write_text('{}')
            record = {'kind': 'canonical_completed_stage', 'key': 'binding', 'files': inventory(root)}
            write_json(root / 'stage-complete.json', record)
            target = root.parent / 'restored'
            self.assertEqual(hydrate(root, target, 'binding')['status'], 'reused')
            self.assertEqual(inventory(root), inventory(target))
            with self.assertRaisesRegex(ValueError, 'identity'):
                completed(root, 'other')
            (root / 'receipt.json').write_text('{"changed":true}')
            with self.assertRaisesRegex(ValueError, 'byte mismatch'):
                completed(root, 'binding')

    def test_checkpoint_rejects_partial_and_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); partial = root / 'partial.incomplete'; partial.write_bytes(b'x')
            with self.assertRaisesRegex(ValueError, 'partial'):
                inventory(root)
            partial.unlink(); (root / 'linked').symlink_to('/etc/hosts')
            with self.assertRaisesRegex(ValueError, 'linked'):
                inventory(root)

    def test_resource_summary_does_not_invent_peak_or_sum_wall(self):
        observations = [{'stage': 'gatk', 'wall_seconds': 10, 'resources': {'cpu_seconds': 20}},
                        {'stage': 'deepvariant', 'wall_seconds': 12, 'resources': {'cpu_seconds': None}}]
        result = resources(observations, 30)
        self.assertEqual(result['total']['wall_seconds'], 30)
        self.assertIsNone(result['total']['cpu_seconds'])
        self.assertIsNone(result['gatk']['peak_rss_bytes'])
        self.assertEqual(result['gatk']['cpu_seconds'], 20)


if __name__ == '__main__':
    unittest.main()
