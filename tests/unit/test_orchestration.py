"""Exercise fail-closed state transitions and canonical version ownership."""

from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("validate_orchestration", ROOT / "scripts/validate_orchestration.py")
assert SPEC is not None and SPEC.loader is not None
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)
SCHEMA = VALIDATOR.read_json(ROOT / VALIDATOR.SCHEMA_PATH)
SHA = "a" * 40
REPOSITORY = "jcollins-bioinfo/giab-wes-nextflow"


def record() -> dict[str, Any]:
    """Return an unfinished synthetic recovery record with no execution claim."""
    return {
        "schema_version": "1.0.0", "record_type": "project_state",
        "milestone": "M2.1.1", "phase": "provenance_recovery", "state": "implemented",
        "version": "0.2.0-dev.4",
        "repositories": {"pipeline": {"full_name": REPOSITORY, "branch": "codex/recovery",
                                      "evidence_sha": SHA, "evidence_scope": "observed_prior_commit"},
                         "website": None},
        "required_inputs": [{"id": "capture_design", "status": "blocked", "sha256": None,
                             "reason": "Exact vendor byte identity remains unresolved."}],
        "local_tests": [{"name": "synthetic", "status": "passed", "evidence_sha": None,
                         "command": "python -m unittest", "detail": "Uncommitted synthetic worktree tests."}],
        "ci": [], "execution_environments": [],
        "publication": {"drive": "not_published", "public_evidence": "not_published",
                        "deployment": "not_deployed", "release": "not_released",
                        "authorization_reference": None, "evidence_artifacts": []},
        "external_blockers": [{"id": "capture_identity", "gate": "Gate B",
                               "reason": "Exact source bytes unresolved.",
                               "owner_action": "Provide capture-design evidence."}],
        "next_safe_action": "Observe recovery CI before starting M3.",
        "observed_at": "2026-09-07T12:00:00Z",
    }


def verified_record() -> dict[str, Any]:
    """Add commit-specific synthetic validation, retaining the independent gate."""
    data = record()
    data["state"] = "verified"
    data["ci"] = [{"name": "required synthetic CI", "required": True, "status": "success",
                   "repository": REPOSITORY, "evidence_sha": SHA,
                   "run_url": f"https://github.com/{REPOSITORY}/actions/runs/123", "job_urls": []}]
    return data


def canonical_record() -> dict[str, Any]:
    """Construct a synthetic model of the evidence required for canonical state."""
    data = verified_record()
    data.update(milestone="M7", state="canonically_executed", external_blockers=[])
    data["required_inputs"][0].update(status="verified", sha256="b" * 64)
    data["execution_environments"] = [{"id": "canonical", "status": "executed", "os": "Linux",
                                       "architecture": "x86_64", "canonical": True,
                                       "run_id": "synthetic-test-run", "evidence_artifacts": ["evidence/run.json"]}]
    return data


def version_repository(root: Path, version: str = "0.2.0-dev.4") -> None:
    """Write minimal version declarations independently of the real checkout."""
    files = {
        "src/giab_wes_nextflow/__init__.py": f'__version__ = "{version}"\n',
        "pyproject.toml": '[tool.hatch.version]\npath = "src/giab_wes_nextflow/__init__.py"\n',
        "nextflow.config": f"manifest {{\n    version = '{version}'\n}}\n",
        "CITATION.cff": f"version: {version}\n",
        "modules/local/emit_foundation_contract/main.nf": json.dumps({"pipeline_version": version}, separators=(",", ":")),
        "tests/snapshots/foundation.semantic.json": json.dumps({"pipeline_version": version}),
        "schemas/run-contract.schema.json": json.dumps({"properties": {"pipeline_version": {"const": version}}}),
        "config/m2-resources.json": json.dumps({"project_version": version}),
        "schemas/m2-source-manifest.schema.json": json.dumps({"properties": {"project_version": {"const": version}}}),
        "src/giab_wes_nextflow/data/config/m2-resources.json": json.dumps({"project_version": version}),
        "src/giab_wes_nextflow/data/schemas/m2-source-manifest.schema.json": json.dumps({"properties": {"project_version": {"const": version}}}),
    }
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


class OrchestrationTests(unittest.TestCase):
    """State labels cannot stand in for observed CI, input or execution evidence."""

    def test_implemented_does_not_claim_execution(self) -> None:
        VALIDATOR.validate_document(record(), SCHEMA)

    def test_verified_retains_independent_capture_gate(self) -> None:
        VALIDATOR.validate_document(verified_record(), SCHEMA)

    def test_m4_verified_cannot_retain_failed_required_ci(self) -> None:
        """An M4 label cannot override a failed or stale required-run identity."""
        data = verified_record()
        data["milestone"] = "M4"
        VALIDATOR.validate_document(data, SCHEMA)
        for status in ("failure", "pending", "not_run"):
            data["ci"][0]["status"] = status
            with self.subTest(status=status), self.assertRaisesRegex(ValueError, "required CI"):
                VALIDATOR.validate_document(data, SCHEMA)

    def test_m5_synthetic_verified_requires_current_green_ci(self) -> None:
        """The explicit synthetic state inherits all current required-CI gates."""
        data = verified_record(); data.update(milestone='M5', state='synthetically_verified')
        VALIDATOR.validate_document(data, SCHEMA)
        data['ci'][0]['status'] = 'failure'
        with self.assertRaisesRegex(ValueError, 'required CI'):
            VALIDATOR.validate_document(data, SCHEMA)

    def test_canonical_and_authorized_release(self) -> None:
        data = canonical_record()
        VALIDATOR.validate_document(data, SCHEMA)
        data["state"] = "released"
        data["publication"].update(release="released", public_evidence="verified",
                                   authorization_reference="owner-approval-reference",
                                   evidence_artifacts=["evidence/release-inventory.json"])
        VALIDATOR.validate_document(data, SCHEMA)

    def test_verified_requires_ci_on_recorded_commit(self) -> None:
        for defect in ("missing", "failed", "different_sha", "other_repo", "wrong_url", "no_tests", "failed_test"):
            with self.subTest(defect=defect):
                data = verified_record()
                if defect == "missing":
                    data["ci"] = []
                elif defect == "failed":
                    data["ci"][0]["status"] = "failure"
                elif defect == "different_sha":
                    data["ci"][0]["evidence_sha"] = "c" * 40
                elif defect == "other_repo":
                    data["ci"][0]["repository"] = "other/repo"
                elif defect == "wrong_url":
                    data["ci"][0]["run_url"] = "https://github.com/other/repo/actions/runs/123"
                elif defect == "no_tests":
                    data["local_tests"] = []
                else:
                    data["local_tests"][0]["status"] = "failed"
                with self.assertRaises(ValueError):
                    VALIDATOR.validate_document(data, SCHEMA)

    def test_canonical_requires_input_hashes_run_and_no_blockers(self) -> None:
        for defect in ("input", "hash", "environment", "run", "artifacts", "configured", "blocker"):
            with self.subTest(defect=defect):
                data = canonical_record()
                if defect == "input":
                    data["required_inputs"][0]["status"] = "declared"
                elif defect == "hash":
                    data["required_inputs"][0]["sha256"] = None
                elif defect == "environment":
                    data["execution_environments"] = []
                elif defect == "run":
                    data["execution_environments"][0]["run_id"] = None
                elif defect == "artifacts":
                    data["execution_environments"][0]["evidence_artifacts"] = []
                elif defect == "configured":
                    data["execution_environments"][0]["status"] = "configured_only"
                else:
                    data["external_blockers"] = record()["external_blockers"]
                with self.assertRaises(ValueError):
                    VALIDATOR.validate_document(data, SCHEMA)

    def test_unapproved_release_and_unverified_deployment_rejected(self) -> None:
        data = canonical_record()
        data["state"] = "released"
        with self.assertRaises(ValueError):
            VALIDATOR.validate_document(data, SCHEMA)
        data["publication"].update(release="released", public_evidence="verified",
                                   evidence_artifacts=["evidence/release.json"])
        with self.assertRaises(ValueError):
            VALIDATOR.validate_document(data, SCHEMA)
        data["publication"]["authorization_reference"] = "owner-approval-reference"
        data["milestone"] = "M8"
        with self.assertRaisesRegex(ValueError, "public deployment"):
            VALIDATOR.validate_document(data, SCHEMA)

    def test_strict_structure_and_blocker_semantics(self) -> None:
        for defect in ("unknown", "missing", "timestamp", "hash", "duplicate", "blocked"):
            with self.subTest(defect=defect):
                data = record()
                if defect == "unknown":
                    data["optimistic_completion"] = True
                elif defect == "missing":
                    del data["repositories"]
                elif defect == "timestamp":
                    data["observed_at"] = "yesterday"
                elif defect == "hash":
                    data["repositories"]["pipeline"]["evidence_sha"] = "main"
                elif defect == "duplicate":
                    data["required_inputs"].append(copy.deepcopy(data["required_inputs"][0]))
                else:
                    data.update(state="blocked", external_blockers=[])
                with self.assertRaises(ValueError):
                    VALIDATOR.validate_document(data, SCHEMA)

    def test_duplicate_json_keys_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "record.json"
            path.write_text('{"state":"blocked","state":"verified"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                VALIDATOR.read_json(path)

    def test_version_scope_excludes_historical_fixture_producers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            version_repository(root)
            fixtures = root / "tests/fixtures"
            fixtures.mkdir(parents=True)
            (fixtures / "history.json").write_text('{"producer_version":"0.1.0","project_version":"0.1.0"}', encoding="utf-8")
            self.assertEqual(VALIDATOR.validate_version_consistency(root), "0.2.0-dev.4")

    def test_root_packaged_and_nextflow_version_drift_rejected(self) -> None:
        paths = ("nextflow.config", "config/m2-resources.json", "schemas/m2-source-manifest.schema.json",
                 "CITATION.cff", "modules/local/emit_foundation_contract/main.nf",
                 "tests/snapshots/foundation.semantic.json", "schemas/run-contract.schema.json",
                 "src/giab_wes_nextflow/data/config/m2-resources.json",
                 "src/giab_wes_nextflow/data/schemas/m2-source-manifest.schema.json")
        for relative in paths:
            with self.subTest(path=relative), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                version_repository(root)
                path = root / relative
                path.write_text(path.read_text(encoding="utf-8").replace("0.2.0-dev.4", "0.1.0"), encoding="utf-8")
                with self.assertRaises(ValueError):
                    VALIDATOR.validate_version_consistency(root)

    def test_packaged_resource_nonversion_drift_is_rejected(self) -> None:
        """A schema/tool declaration must retain all authoritative bytes in wheels."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            version_repository(root)
            path = root / "src/giab_wes_nextflow/data/config/m2-resources.json"
            value = json.loads(path.read_text())
            value["unexpected_tool_digest"] = "a" * 64
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "packaged resource differs"):
                VALIDATOR.validate_version_consistency(root)

    def test_required_checkpoint_identity_and_future_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            version_repository(root)
            orchestration = root / "docs/orchestration"
            (orchestration / "checkpoints").mkdir(parents=True)
            (root / VALIDATOR.SCHEMA_PATH).write_text(json.dumps(SCHEMA), encoding="utf-8")
            (orchestration / "project-state.json").write_text(json.dumps(record()), encoding="utf-8")
            for number in range(3, 10):
                checkpoint = record()
                checkpoint.update(record_type="checkpoint", milestone=f"M{number}", state="not_started")
                (orchestration / f"checkpoints/M{number}.json").write_text(json.dumps(checkpoint), encoding="utf-8")
            self.assertEqual(VALIDATOR.validate_repository(root), 8)
            path = orchestration / "checkpoints/M3.json"
            checkpoint = VALIDATOR.read_json(path)
            checkpoint["state"] = "implemented"
            path.write_text(json.dumps(checkpoint), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "optimistically"):
                VALIDATOR.validate_repository(root)
            checkpoint.update(state="not_started", milestone="M4")
            path.write_text(json.dumps(checkpoint), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "identity"):
                VALIDATOR.validate_repository(root)
            path.unlink()
            with self.assertRaises(FileNotFoundError):
                VALIDATOR.validate_repository(root)


if __name__ == "__main__":
    unittest.main()
