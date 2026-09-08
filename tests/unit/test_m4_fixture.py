"""Preserve the original recipe while admitting only the strong invented SNV fixture."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from giab_wes_nextflow.m3 import require_fixture
from giab_wes_nextflow.m3_collect import validate_bqsr_observations, validate_result_bundle
from giab_wes_nextflow.m4_fixture import _uses_alternate_allele, generate_m4_fixture
from giab_wes_nextflow.m3_fixture import sha256_bytes
from giab_wes_nextflow.synthetic_fixtures import fixture_contract, fixture_contract_from_manifest_sha256
from test_m3_support import make_unit_bundle


class M4FixtureTest(unittest.TestCase):
    """Explicit recipe identity precedes any alignment or caller execution."""

    def test_original_hash_and_reference_sources_are_unchanged(self) -> None:
        """The new read recipe preserves all three existing reference-source artifacts."""
        original, positive = fixture_contract("m3-preprocessing"), fixture_contract("m4-snv-positive")
        self.assertEqual(original.manifest_sha256, "d8f87a4eddd93eebd1cee5c9d77bfa1b8093714a8b3c2edc434742a3f3e16c1d")
        for name in ("reference.fa", "reference-source.json", "known-sites.vcf"):
            self.assertEqual(original.payloads[name], positive.payloads[name])
        self.assertEqual(positive.expectations["primary_read_count"], 528)
        self.assertEqual(len(positive.expectations["read_expectations"]), 528)

    def test_heterozygous_alleles_are_not_confounded_with_fixture_structure(self) -> None:
        """Each lane and supporting mate independently receives 10 ALT and 10 REF fragments."""
        patterns = []
        for support_mate in (1, 2):
            pattern = [_uses_alternate_allele("0/1", index, support_mate) for index in range(40)]
            patterns.append(pattern)
            self.assertEqual(sum(pattern), 20)
            self.assertEqual(sum(pattern[0::2]), 10)
            self.assertEqual(sum(pattern[1::2]), 10)
            self.assertFalse(all(pattern[index] == pattern[index + 1] for index in range(19)))
        self.assertNotEqual(patterns[0], patterns[1])
        self.assertTrue(all(_uses_alternate_allele("1/1", index, 1) for index in range(40)))
        self.assertFalse(any(_uses_alternate_allele("0/0", index, 1) for index in range(40)))

    def test_explicit_selection_and_immutable_repeat(self) -> None:
        """The default remains M3 and an explicit M4 selection repeats identical bytes."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = generate_m4_fixture(root)
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            generate_m4_fixture(root)
            self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})
            path = root / "fixture-expectations.json"
            with self.assertRaisesRegex(ValueError, "deterministic fixture"):
                require_fixture(path)
            self.assertEqual(require_fixture(path, fixture_id="m4-snv-positive"), expected)
            expected["primary_read_count"] = 48
            path.write_text(json.dumps(expected))
            with self.assertRaisesRegex(ValueError, "deterministic fixture"):
                require_fixture(path, fixture_id="m4-snv-positive")

    def test_unknown_recipe_and_manifest_hash_fail(self) -> None:
        """Neither a user-selected factory name nor arbitrary manifest bytes are trusted."""
        with self.assertRaisesRegex(ValueError, "unapproved"):
            fixture_contract("any-synthetic")
        with self.assertRaisesRegex(ValueError, "unregistered"):
            fixture_contract_from_manifest_sha256("f" * 64)

    def test_published_hashes_and_unique_positive_fragments_are_frozen(self) -> None:
        """The public recipe inventory and exact fragment support cannot drift silently."""
        contract = fixture_contract("m4-snv-positive")
        table = json.loads((Path(__file__).parents[1] / "data/m4/expected-hashes.json").read_text())
        for name, content in contract.payloads.items():
            self.assertEqual(table["files"][name], {"bytes": len(content), "sha256": sha256_bytes(content)})
        self.assertEqual(table["files"]["fixture-expectations.json"]["sha256"], contract.manifest_sha256)
        expected = contract.expectations
        for site in expected["variant_sites"] + expected["reference_controls"]:
            observations = [item for item in expected["read_expectations"].values()
                if item["contig"] == site["contig"] and item["position_1based"] <= site["position_1based"] < item["position_1based"] + 150]
            self.assertEqual(len({item["qname"] for item in observations}), 80)
            self.assertEqual(sum(item["reverse"] for item in observations), 40)
            self.assertTrue(all(item["duplicate_group"] is None for item in observations))

    def test_selected_fixture_passes_full_shared_bam_contract(self) -> None:
        """The enlarged exact read/quality/duplicate inventory passes existing invariants."""
        with tempfile.TemporaryDirectory() as directory:
            bundle = make_unit_bundle(Path(directory), fixture_id="m4-snv-positive")
            result = validate_result_bundle(bundle)
            self.assertEqual(result["alignment"]["data"]["primary_reads"], 528)
            self.assertEqual(result["alignment"]["data"]["duplicate_reads"], 4)
            self.assertTrue(result["alignment"]["data"]["oq_complete"])

    def test_header_only_bqsr_does_not_prove_recalibration(self) -> None:
        """Positive observations, not a familiar report header, gate M4 admission."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "table.txt"
            for content in ("#:GATKReport\n", "#:GATKReport\nReadGroup Observations Errors\nRG 0 0\n"):
                path.write_text(content)
                with self.assertRaisesRegex(ValueError, "positive observations"):
                    validate_bqsr_observations(path)


if __name__ == "__main__":
    unittest.main()
