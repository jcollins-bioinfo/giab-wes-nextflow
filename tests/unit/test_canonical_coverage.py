"""Exact positional coverage arithmetic and negative gates without genomic execution."""
from pathlib import Path
import tempfile
import unittest

from giab_wes_nextflow.canonical_coverage import coverage, summarize_depth


class CanonicalCoverageTests(unittest.TestCase):
    """Uncovered bases belong in the same approved denominator as covered bases."""

    def test_gaps_zero_depth_thresholds_and_mean(self):
        intervals = [('chr20', 0, 3), ('chr20', 5, 7), ('chr21', 1, 2)]
        rows = ['chr20\t1\t0\n', 'chr20\t2\t1\n', 'chr20\t3\t10\n', 'chr20\t6\t20\n', 'chr20\t7\t30\n', 'chr21\t2\t39\n']
        summary = summarize_depth(iter(rows), intervals)
        self.assertEqual(summary['evaluated_bases'], 6)
        self.assertEqual(summary['covered_bases'], 5)
        self.assertEqual(summary['bases_at_least'], {'1': 5, '10': 4, '20': 3, '30': 2})
        self.assertEqual(summary['depth_sum'], 100)
        self.assertEqual(summary['mean_depth'], 100 / 6)

    def test_missing_extra_duplicate_wrong_order_and_negative_depth_fail(self):
        valid = ['chr20\t1\t0\n', 'chr20\t2\t1\n']
        for rows in [valid[:-1], valid + ['chr20\t3\t0\n'], [valid[0], valid[0]], list(reversed(valid)), ['chr20\t1\t-1\n', valid[1]], ['chr21\t1\t0\n', valid[1]]]:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                summarize_depth(iter(rows), [('chr20', 0, 2)])

    def test_unapproved_domain_fails_before_runtime_or_output_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); bed = root / 'changed.bed'; bed.write_text('chr20\t0\t1\n')
            with self.assertRaisesRegex(ValueError, 'unapproved'):
                coverage(None, root / 'shared', bed, root / 'output')
            self.assertFalse((root / 'output').exists())


if __name__ == '__main__':
    unittest.main()
