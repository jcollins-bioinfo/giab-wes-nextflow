"""Negative tests proving M2 validation is byte-bound and active under -O."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from jsonschema import ValidationError

from giab_wes_nextflow import validation
from giab_wes_nextflow.resources import config_path
import test_m2_mirror_safety as mirror_fixture


class WorkspaceValidationSafetyTest(unittest.TestCase):
    def setUp(self):
        self.fixture = mirror_fixture.SourceMirrorSafetyTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.gate_path = config_path("m2-target-design.json")
        self.context = patch("giab_wes_nextflow.validation.config_path", side_effect=lambda name:
                             self.fixture.manifest_path if name == "m2-resources.json" else self.gate_path)
        self.context.start()
        self.addCleanup(self.context.stop)

    def check(self):
        return validation.validate_workspace(self.fixture.stage, self.fixture.run_id)

    def test_complete_source_contract_is_explicitly_sources_only(self):
        self.assertEqual(self.check(), "verified_sources_only")

    def test_wrong_run_manifest_and_partial_inventory_fail(self):
        for mutate in [lambda r: r.update(run_id="different-run"),
                       lambda r: r.update(source_manifest_sha256="0" * 64),
                       lambda r: r["observations"].pop()]:
            record = json.loads(json.dumps(self.fixture.acquisition))
            mutate(record)
            self.fixture.acquisition_path.write_text(json.dumps(record))
            with self.assertRaises((ValueError, ValidationError)):
                self.check()

    def test_run_or_observation_path_traversal_and_symlinks_fail(self):
        with self.assertRaises(ValueError):
            validation.validate_workspace(self.fixture.stage, "../../../escape")
        record = json.loads(json.dumps(self.fixture.acquisition))
        record["observations"][0]["destination"] = "../../../escape"
        self.fixture.acquisition_path.write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            self.check()
        self.fixture.acquisition_path.write_text(json.dumps(self.fixture.acquisition))
        source = self.fixture.stage / self.fixture.manifest["resources"][0]["destination"]
        external = self.fixture.base / "external"
        source.rename(external)
        source.symlink_to(external)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.check()

    def test_optimized_python_rejects_corrupt_source_bytes(self):
        source = self.fixture.stage / self.fixture.manifest["resources"][0]["destination"]
        source.write_bytes(b"corrupt")
        code = "\n".join([
            "from pathlib import Path",
            "from unittest.mock import patch",
            "from giab_wes_nextflow.validation import validate_workspace",
            f"manifest = Path({str(self.fixture.manifest_path)!r})",
            f"gate = Path({str(self.gate_path)!r})",
            "with patch('giab_wes_nextflow.acquisition.config_path', return_value=manifest), patch('giab_wes_nextflow.validation.config_path', side_effect=lambda name: manifest if name == 'm2-resources.json' else gate):",
            f"    validate_workspace({str(self.fixture.stage)!r}, {self.fixture.run_id!r})",
        ])
        result = subprocess.run([sys.executable, "-O", "-c", code], cwd=self.fixture.base,
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("source size mismatch", result.stderr)

    def test_fabricated_domains_cannot_bypass_unresolved_gate(self):
        path = self.fixture.acquisition_path.with_name("transformation.json")
        path.write_text(json.dumps({"schema_version": "1.0.0", "run_id": self.fixture.run_id,
                                    "status": "domains_materialized", "domains": []}))
        with self.assertRaises(ValueError):
            self.check()

    def test_contradictory_reference_only_transformation_fails(self):
        path = self.fixture.acquisition_path.with_name("transformation.json")
        for record in [{"schema_version": "1.0.0", "run_id": self.fixture.run_id,
                        "status": "reference_prepared_domain_blocked", "domains": [{}]},
                       {"schema_version": "1.0.0", "run_id": self.fixture.run_id,
                        "status": "reference_prepared_domain_blocked", "domains": [], "reference": []}]:
            path.write_text(json.dumps(record))
            with self.assertRaises(ValueError):
                self.check()


if __name__ == "__main__":
    unittest.main()
