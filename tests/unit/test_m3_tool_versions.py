"""Keep distribution releases distinct from exact executable self-reports."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
from typing import Any
import unittest
from unittest.mock import patch

from jsonschema import ValidationError

from giab_wes_nextflow.m3 import canonical_hash, identity, load_json, validate_envelope
from giab_wes_nextflow.m3_collect import _tool_inventory, validate_result_bundle
from giab_wes_nextflow.resources import config_path
from test_m3_support import make_unit_bundle


class ToolVersionContractTest(unittest.TestCase):
    """A pinned image must satisfy its one documented executable-version report."""

    def setUp(self) -> None:
        """Load the actual packaged lock rather than substituting a test policy."""
        self.lock = load_json(config_path("m3-tools.json"))
        self.versions = {name: value["expected_reported_version"] for name, value in self.lock["tools"].items()}

    def inventory(self, bwa_report: str, image: str | None = None) -> list[dict[str, Any]]:
        """Collect explicit synthetic version observations under the real image lock."""
        observations = {**self.versions, "bwa-mem2": bwa_report}
        return _tool_inventory([f"{name}={value}" for name, value in observations.items()], [],
                               [] if image is None else [f"bwa-mem2={image}"])

    def test_distribution_and_self_report_are_explicit(self) -> None:
        """The stale report remains visible with its source and failed-CI evidence."""
        inventory = self.inventory("Looking to launch avx2 executable\n2.2.1\n")
        bwa = next(item for item in inventory if item["name"] == "bwa-mem2")
        self.assertEqual(bwa["declared_version"], "2.3")
        self.assertEqual(bwa["expected_reported_version"], "2.2.1")
        self.assertEqual(bwa["container_image"], self.lock["tools"]["bwa-mem2"]["image"])
        self.assertEqual({item["kind"] for item in bwa["version_evidence_sources"]},
                         {"upstream_release_source", "historical_ci_artifact"})
        self.assertIn("stale self-report", bwa["version_note"])
        for item in inventory:
            if item["name"] != "bwa-mem2":
                self.assertEqual(item["declared_version"], item["expected_reported_version"])

    def test_distribution_substitution_and_wrong_reports_fail(self) -> None:
        """Neither the release label, near version nor two reports satisfy the pin."""
        for text in ("2.3", "2.2.10", "2.2.1-extra", "2.2.1\n2.3", "prefix2.2.1", "2.2.1 2.3"):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "observed tool version"):
                self.inventory(text)

    def test_wrong_image_fails_even_with_expected_report(self) -> None:
        """A matching self-report cannot authorize a different binary image."""
        with self.assertRaisesRegex(ValueError, "immutable lock"):
            self.inventory("2.2.1", "quay.io/biocontainers/bwa-mem2@sha256:" + "f" * 64)

    def test_missing_expected_report_has_no_distribution_fallback(self) -> None:
        """A lock omitting the executable identity fails before collection."""
        del self.lock["tools"]["bwa-mem2"]["expected_reported_version"]
        with patch("giab_wes_nextflow.m3_collect.load_json", return_value=self.lock):
            with self.assertRaisesRegex(ValueError, "missing release or executable-report"):
                self.inventory("2.3")


class BundleToolIdentityTest(unittest.TestCase):
    """Rehashed result files must still agree with the installed immutable lock."""

    def setUp(self) -> None:
        """Build a complete invented bundle, with no actual container-run claim."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.bundle = make_unit_bundle(Path(temporary.name))

    def rewrite_provenance(self, record: dict[str, Any]) -> None:
        """Rehash every affected layer so rejection tests semantic identity binding."""
        path = self.bundle / "m3-provenance.json"
        record["payload_sha256"] = canonical_hash({key: value for key, value in record.items() if key != "payload_sha256"})
        path.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n")
        manifest_path = self.bundle / "m3-manifest.json"
        manifest = load_json(manifest_path)
        item = next(item for item in manifest["data"]["artifacts"] if item["artifact_type"] == "provenance")
        item.update(sha256=identity(path, "provenance", "immutable_m3_result")["sha256"],
                    bytes=path.stat().st_size, payload_sha256=record["payload_sha256"])
        manifest["payload_sha256"] = canonical_hash({key: value for key, value in manifest.items() if key != "payload_sha256"})
        manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")

    def test_only_provenance_uses_schema_two(self) -> None:
        """Only the incompatible provenance contract advances its schema version."""
        records = validate_result_bundle(self.bundle)
        for kind, record in records.items():
            self.assertEqual(record["schema_version"], "2.0.0" if kind == "provenance" else "1.0.0")
            if kind != "provenance":
                record["schema_version"] = "2.0.0"
                with self.subTest(kind=kind), self.assertRaises(ValidationError):
                    validate_envelope(record)

    def test_historical_provenance_is_not_silently_upgraded(self) -> None:
        """Earlier prerelease diagnostics retain their version and fail current admission."""
        record = load_json(self.bundle / "m3-provenance.json")
        record["schema_version"] = "1.0.0"
        for tool in record["data"]["tools"]:
            for field in ("expected_reported_version", "version_note", "version_evidence_sources"):
                del tool[field]
        self.rewrite_provenance(record)
        before = (self.bundle / "m3-provenance.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "historical evidence is not upgraded"):
            validate_result_bundle(self.bundle)
        self.assertEqual(before, (self.bundle / "m3-provenance.json").read_bytes())

    def test_current_schema_requires_explicit_executable_report(self) -> None:
        """Schema v2 cannot carry the old ambiguous tool record with a new label."""
        record = load_json(self.bundle / "m3-provenance.json")
        del record["data"]["tools"][0]["expected_reported_version"]
        self.rewrite_provenance(record)
        with self.assertRaisesRegex(ValidationError, "expected_reported_version"):
            validate_result_bundle(self.bundle)

    def test_rehashed_tool_identity_forgery_fails(self) -> None:
        """Image, declared release, expected report and evidence notes bind to the lock."""
        original = load_json(self.bundle / "m3-provenance.json")
        changes = {"declared_version": "2.2.1", "expected_reported_version": "2.3",
                   "container_image": "quay.io/biocontainers/bwa-mem2@sha256:" + "f" * 64,
                   "version_note": "distribution and binary reports silently equated",
                   "version_evidence_sources": []}
        for field, value in changes.items():
            record = json.loads(json.dumps(original))
            next(tool for tool in record["data"]["tools"] if tool["name"] == "bwa-mem2")[field] = value
            self.rewrite_provenance(record)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "identity differs from immutable lock"):
                validate_result_bundle(self.bundle)

    def test_rehashed_distribution_report_substitution_fails(self) -> None:
        """A fully rehashed report cannot substitute advertised 2.3 for observed 2.2.1."""
        record = load_json(self.bundle / "m3-provenance.json")
        next(tool for tool in record["data"]["tools"] if tool["name"] == "bwa-mem2")["observed_version_text"] = "2.3"
        self.rewrite_provenance(record)
        with self.assertRaisesRegex(ValueError, "observed tool version"):
            validate_result_bundle(self.bundle)

    def test_rehashed_incomplete_tool_inventory_fails(self) -> None:
        """A valid-looking subset cannot omit any locked preprocessing tool."""
        record = load_json(self.bundle / "m3-provenance.json")
        record["data"]["tools"].pop()
        self.rewrite_provenance(record)
        with self.assertRaisesRegex(ValueError, "inventory differs from immutable lock"):
            validate_result_bundle(self.bundle)


if __name__ == "__main__":
    unittest.main()
