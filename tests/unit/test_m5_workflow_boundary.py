"""Protect the downstream truth boundary and explicit stub-only evidence labels."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class WorkflowBoundaryTests(unittest.TestCase):
    """Inspect input signatures rather than relying on a successful synthetic score."""

    def test_truth_is_absent_from_normalization_inputs(self) -> None:
        source = (ROOT / "modules/local/m5_normalize/main.nf").read_text()
        inputs = source.split("input:", 1)[1].split("output:", 1)[0]
        for forbidden in ("truth", "confidence", "domain", "expected"):
            self.assertNotIn(forbidden, inputs)
        workflow = (ROOT / "subworkflows/local/m5_common_benchmark/main.nf").read_text()
        self.assertIn("M5_NORMALIZE(queries, reference)", workflow)
        self.assertIn("M5_BENCHMARK(M5_NORMALIZE.out.normalized, reference, benchmark_inputs)", workflow)

    def test_stubs_cannot_claim_metrics_or_validation(self) -> None:
        for name in ("m5_normalize", "m5_benchmark"):
            source = (ROOT / f"modules/local/{name}/main.nf").read_text().split("stub:", 1)[1]
            self.assertIn('"status":"stub_only"', source)
            self.assertIn('"canonical":false', source)
        entry = (ROOT / "m5.nf").read_text()
        self.assertIn("manifest.synthetic != true", entry)
        self.assertNotIn("M4_DUAL_CALLERS", entry)


if __name__ == "__main__":
    unittest.main()
