"""Test approved coordinate semantics without genomic files or caller evidence."""
from pathlib import Path
import tempfile
import unittest
from giab_wes_nextflow import coding_domain as d


class CodingDomainTests(unittest.TestCase):
    """Protect fixed domains, coordinate conversion, and source-pin rejection."""

    def test_selection_and_half_open_coordinates(self) -> None:
        """Require both biotypes and include stop codons while excluding UTRs."""
        row='chr1\tsource\tCDS\t2\t5\t.\t+\t0\tgene_type "protein_coding"; transcript_type "protein_coding";\n'
        lines=[row,row.replace('CDS','stop_codon').replace('\t2\t5\t','\t6\t8\t'),row.replace('CDS','UTR'),row.replace('transcript_type "protein_coding"','transcript_type "lncRNA"')]
        self.assertEqual(d.coding_intervals(lines,{'chr1':10}),[('chr1',1,8)])
        for bad in (row.replace('\t2\t5\t','\t0\t5\t'),row.replace('transcript_type "protein_coding";','transcript_type "protein_coding"; transcript_type "protein_coding";')):
            with self.assertRaises(ValueError):d.coding_intervals([bad],{'chr1':10})

    def test_padding_clipping_touching_and_intersection(self) -> None:
        """Pad only calling; keep evaluation unpadded and autosomal."""
        coding=[('chr1',1,5),('chr20',150,160),('chrX',1,8)]
        confidence=[('chr1',3,10),('chr20',155,200)]
        result=d.derive(coding,confidence,{'chr1':30,'chr20':300,'chrX':20})
        self.assertEqual(result['R_call'],[('chr1',0,30),('chr20',50,260),('chrX',0,20)])
        self.assertEqual(result['R_eval_full'],[('chr1',3,5),('chr20',155,160)])
        self.assertEqual(result['R_eval_holdout'],[('chr20',155,160)])
        self.assertEqual(d.merge([('chr1',1,4),('chr1',4,7)]),[('chr1',1,7)])
        self.assertEqual(d.intersection([('chr1',0,5)],[('chr1',5,8)]),[])

    def test_sources_fail_before_outputs(self) -> None:
        """Unapproved synthetic bytes cannot create an approved-domain marker."""
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();p=root/'fake';p.write_bytes(b'invented')
            with self.assertRaisesRegex(ValueError,'source hash'):
                d.construct(p,p,p,root/'out')
            self.assertFalse((root/'out').exists())

    def test_bed_unknown_contig_rejected(self) -> None:
        """Reject unexpected evaluation contigs before set arithmetic."""
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'domain.bed';p.write_text('chrUnknown\t0\t1\n')
            with self.assertRaises(ValueError):d.load_bed(p,{'chr1':10},d.AUTOSOMES)


if __name__ == '__main__':
    unittest.main()
