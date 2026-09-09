"""Independent negative gates for canonical indexing and fixed confidence domains."""
from __future__ import annotations

import gzip
from pathlib import Path
import tempfile
import unittest

from giab_wes_nextflow.canonical_science import validate_confidence_subset, verify_vcf_index


class CanonicalAdditionalGatesTests(unittest.TestCase):
    """Exercise artifact semantics with invented short byte fixtures."""

    def test_confidence_subset_is_union_based_and_boundary_exact(self) -> None:
        """Confidence never changes an approved denominator silently."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); evaluation = root / 'evaluation.bed'; confidence = root / 'confidence.bed.gz'
            evaluation.write_text('chr20\t2\t6\n')
            with gzip.open(confidence, 'wt') as stream:
                stream.write('chr20\t4\t8\nchr20\t0\t4\n')
            result = validate_confidence_subset(evaluation, confidence, {'chr20': 'A' * 10})
            self.assertTrue(result['evaluation_is_confident_subset'])
            with gzip.open(confidence, 'wt') as stream:
                stream.write('chr20\t0\t5\n')
            with self.assertRaisesRegex(ValueError, 'extends beyond'):
                validate_confidence_subset(evaluation, confidence, {'chr20': 'A' * 10})

    def test_unknown_confidence_contig_and_out_of_bounds_rejected(self) -> None:
        """A confidence file cannot expand the compatible reference contract."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); evaluation = root / 'evaluation'; confidence = root / 'confidence'
            evaluation.write_text('chr20\t0\t4\n')
            for bad in ['chr99\t0\t4\n', 'chr20\t0\t11\n', 'chr20\t-1\t4\n']:
                confidence.write_text(bad)
                with self.assertRaises(ValueError):
                    validate_confidence_subset(evaluation, confidence, {'chr20': 'A' * 10})

    def test_raw_index_must_retrieve_exact_sequential_records(self) -> None:
        """A syntactically readable but stale index must fail before normalization."""
        with tempfile.TemporaryDirectory() as directory:
            class Commands:
                """Write controlled artificial outputs instead of launching bcftools."""
                task = Path(directory)
                stale = False
                def run(self, tool, args, *, stdout):
                    (self.task / stdout).write_text('variant\n' if '-r' not in args or not self.stale else '')
            commands = Commands()
            verify_vcf_index(commands, 'raw.vcf.gz', ('chr20',))
            self.assertFalse((commands.task / 'index-check-indexed.txt').exists())
            commands.stale = True
            with self.assertRaisesRegex(ValueError, 'index does not match'):
                verify_vcf_index(commands, 'raw.vcf.gz', ('chr20',))


if __name__ == '__main__':
    unittest.main()
