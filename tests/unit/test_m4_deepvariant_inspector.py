"""Negative checks for the isolated DeepVariant evidence inspector."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("m4_deepvariant_inspector", ROOT / "scripts/m4_inspect_deepvariant.py")
INSPECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSPECTOR)


class PredictionBoundaryTest(unittest.TestCase):
    """A record count alone must not admit invalid model predictions."""

    def test_probabilities_require_finite_normalized_three_classes(self) -> None:
        """Zero records, NaN, infinities and invalid probabilities cannot qualify inference."""
        INSPECTOR.validate_probabilities([0.01, 0.98, 0.01])
        for values in ([], [0.5, 0.5], [0.1, 0.1, 0.1], [float("nan"), 0, 1],
                       [float("inf"), 0, 0], [-0.1, 1, 0.1], [1.1, 0, -0.1]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                INSPECTOR.validate_probabilities(values)

    def test_candidate_must_fit_reference_and_have_alternative(self) -> None:
        """Only dictionary coordinates and real alternative alleles enter the proof."""
        lengths = {"invented": 100}
        self.assertEqual(INSPECTOR.validate_variant("invented", 10, 11, "A", ["T"], lengths), "invented")
        for name, start, end, reference, alternatives in (
            ("other", 10, 11, "A", ["T"]), ("invented", -1, 0, "A", ["T"]),
            ("invented", 99, 101, "AA", ["T"]), ("invented", 10, 10, "A", ["T"]),
            ("invented", 10, 12, "A", ["T"]), ("invented", 10, 11, "A", []),
            ("invented", 10, 11, "A", ["A"]),
        ):
            with self.subTest(name=name, start=start, alternatives=alternatives), self.assertRaises(ValueError):
                INSPECTOR.validate_variant(name, start, end, reference, alternatives, lengths)

    def test_predictions_must_match_generated_candidate_and_alt_indices(self) -> None:
        """Positive unrelated predictions cannot qualify the generated example inventory."""
        lengths = {"invented": 100}
        candidate = INSPECTOR.candidate_identity("invented", 10, 11, "A", ["T", "C"], [0], lengths)
        INSPECTOR.require_candidate_lineage(candidate, {candidate})
        for prediction in (INSPECTOR.candidate_identity("invented", 20, 21, "A", ["T", "C"], [0], lengths),
                           INSPECTOR.candidate_identity("invented", 10, 11, "A", ["T", "C"], [1], lengths)):
            with self.assertRaisesRegex(ValueError, "generated candidate"):
                INSPECTOR.require_candidate_lineage(prediction, {candidate})
        with self.assertRaisesRegex(ValueError, "allele indices"):
            INSPECTOR.candidate_identity("invented", 10, 11, "A", ["T"], [1], lengths)


class ModelBoundaryTest(unittest.TestCase):
    """Every expected model byte identity must exist before caller inference."""

    def setUp(self) -> None:
        """Build invented model-file bytes solely for metadata boundary tests."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        for name in INSPECTOR.MODEL_FILES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(name.encode())
        self.metadata_hash = hashlib.sha256(b"model.example_info.json").hexdigest()

    def test_model_freeze_records_five_files_and_rejects_metadata_drift(self) -> None:
        """An observed model inventory cannot substitute another WES metadata identity."""
        record = INSPECTOR.model_inventory(self.root, self.metadata_hash)
        self.assertEqual(record["kind"], "m4_deepvariant_model_inventory")
        self.assertEqual({entry["filename"] for entry in record["model_files"]}, set(INSPECTOR.MODEL_FILES))
        self.assertNotIn(str(self.root), json.dumps(record))
        with self.assertRaisesRegex(ValueError, "metadata differs"):
            INSPECTOR.model_inventory(self.root, "f" * 64)

    def test_missing_empty_and_linked_weights_fail(self) -> None:
        """Incomplete or linked weights cannot stand in for the pinned in-image model."""
        path = self.root / "saved_model.pb"
        path.write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "empty"):
            INSPECTOR.model_inventory(self.root, self.metadata_hash)
        path.unlink()
        with self.assertRaisesRegex(ValueError, "regular"):
            INSPECTOR.model_inventory(self.root, self.metadata_hash)
        path.symlink_to(self.root / "fingerprint.pb")
        with self.assertRaisesRegex(ValueError, "linked"):
            INSPECTOR.model_inventory(self.root, self.metadata_hash)

    def test_missing_duplicate_and_ambiguous_inference_inputs_fail(self) -> None:
        """Counting cannot double-count the same file or hide colliding logical names."""
        first = self.root / "records.gz"
        first.write_bytes(b"invented")
        second = self.root / "other/records.gz"
        second.parent.mkdir()
        second.write_bytes(b"invented")
        for paths in ([], [first, first], [first, second]):
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                INSPECTOR.unique_files(paths)

    def test_forbidden_output_is_rejected_before_access(self) -> None:
        """The absolute safety-name boundary also applies to newly requested output."""
        with self.assertRaisesRegex(ValueError, "prohibited"):
            INSPECTOR.guarded_path(self.root / ("prefix " + INSPECTOR.FORBIDDEN_FOLDER) / "new.json")


if __name__ == "__main__":
    unittest.main()
