"""Synthetic regression tests for M2 identity, recovery, and filesystem boundaries."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch

from jsonschema import ValidationError

from giab_wes_nextflow import acquisition, mirror
from giab_wes_nextflow.resources import config_path


class SourceMirrorSafetyTest(unittest.TestCase):
    """Exercise complete declared synthetic objects, never public sequence bytes."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()
        self.stage = self.base / "m2-stage"
        self.drive = self.base / "giab-wes-nextflow-private"
        self.stage.mkdir()
        self.drive.mkdir()
        self.manifest = json.loads(config_path("m2-resources.json").read_text())
        for index, item in enumerate(self.manifest["resources"]):
            data = f"deterministic nonhuman source object {index}\n".encode()
            path = self.stage / item["destination"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            item["bytes"] = len(data)
            item["checksum"]["expected"] = hashlib.md5(data).hexdigest()
        self.manifest_path = self.base / "manifest.json"
        self.manifest_path.write_text(json.dumps(self.manifest))
        # Substitute only the packaged source declaration; real validation,
        # hashing, path checks, copying and registry operations remain active.
        self.patches = [patch("giab_wes_nextflow.acquisition.config_path", return_value=self.manifest_path),
                        patch("giab_wes_nextflow.mirror.config_path", return_value=self.manifest_path)]
        for context in self.patches:
            context.start()
        self.addCleanup(lambda: [context.stop() for context in reversed(self.patches)])
        self.addCleanup(self.temporary.cleanup)
        self.run_id = "synthetic-source-run"
        self.repository_sha = "a" * 40
        self.acquisition = {"schema_version": "1.0.0", "run_id": self.run_id,
                            "created_utc": acquisition.now(), "source_manifest_sha256": acquisition.checksum(self.manifest_path),
                            "observations": [acquisition.observation(item, self.stage / item["destination"], "verified", 0, {}, item["url"])
                                             for item in self.manifest["resources"]]}
        self.acquisition_path = self.stage / f"registry/runs/{self.run_id}/acquisition.json"
        self.acquisition_path.parent.mkdir(parents=True)
        self.acquisition_path.write_text(json.dumps(self.acquisition, sort_keys=True, indent=2) + "\n")

    def publish(self):
        return mirror.mirror_sources(self.stage, self.drive, self.run_id, self.repository_sha)

    def test_retry_preserves_record_bytes_and_hydration_restores_evidence(self):
        record = self.publish()
        before = record.read_bytes()
        self.assertEqual(self.publish(), record)
        self.assertEqual(record.read_bytes(), before)
        original = self.acquisition_path.read_bytes()
        shutil.rmtree(self.stage)
        self.assertEqual(mirror.hydrate_sources(self.drive, self.stage, self.run_id), 10)
        self.assertEqual(self.acquisition_path.read_bytes(), original)
        self.assertEqual(mirror.hydrate_sources(self.drive, self.stage, self.run_id), 10)
        self.assertEqual(acquisition.main(["--workspace", str(self.stage), "--run-id", self.run_id]), 0)
        self.assertFalse(any(self.drive.rglob("COMPLETED.json")))

    def test_legacy_recovery_retains_old_identity_and_revalidates_new_observations(self):
        record_path = self.publish()
        legacy = json.loads(record_path.read_text())
        legacy["schema_version"] = "1.0.0"
        del legacy["acquisition"]
        del legacy["publisher_version"]
        old_manifest = json.loads(json.dumps(self.manifest))
        old_manifest["project_version"] = "0.2.0-dev.2"
        source_manifest = self.base / "historical-manifest.json"
        source_manifest.write_text(json.dumps(old_manifest))
        legacy["source_manifest_sha256"] = acquisition.checksum(source_manifest)
        record_path.write_text(json.dumps(legacy))
        legacy_bytes = record_path.read_bytes()
        shutil.rmtree(self.stage)
        with self.assertRaises(ValueError):
            mirror.hydrate_sources(self.drive, self.stage, self.run_id)
        with self.assertRaisesRegex(ValueError, "distinct"):
            mirror.hydrate_sources(self.drive, self.stage, self.run_id, source_manifest)
        self.assertEqual(mirror.hydrate_sources(self.drive, self.stage, self.run_id, source_manifest, "recovered-run"), 10)
        recovered_path = self.stage / "registry/runs/recovered-run/acquisition.json"
        recovered = json.loads(recovered_path.read_text())
        self.assertEqual(recovered["source_manifest_sha256"], acquisition.checksum(self.manifest_path))
        self.assertEqual(recovered["observations"][0]["response"]["source_repository_sha"], self.repository_sha)
        self.assertEqual(recovered["observations"][0]["response"]["source_manifest_sha256"], legacy["source_manifest_sha256"])
        self.assertEqual(record_path.read_bytes(), legacy_bytes)
        self.assertEqual(mirror.hydrate_sources(self.drive, self.stage, self.run_id, source_manifest, "recovered-run"), 10)

    def test_hydration_current_sha_is_explicit_and_immutable(self):
        mirror_path = self.publish()
        original_mirror = mirror_path.read_bytes()
        current_sha = "b" * 40
        self.assertEqual(mirror.hydrate_sources(self.drive, self.stage, self.run_id, repository_sha=current_sha), 10)
        hydration_path = self.acquisition_path.with_name("hydration.json")
        before = hydration_path.read_bytes()
        original_acquisition = self.acquisition_path.read_bytes()
        hydration = json.loads(before)
        self.assertEqual(hydration["repository_sha"], current_sha)
        self.assertEqual(hydration["source"]["source_repository_sha"], self.repository_sha)
        self.assertEqual(hydration["acquisition_sha256"], acquisition.checksum(self.acquisition_path))
        self.assertEqual(mirror.hydrate_sources(self.drive, self.stage, self.run_id, repository_sha=current_sha), 10)
        self.assertEqual(hydration_path.read_bytes(), before)
        with self.assertRaisesRegex(FileExistsError, "immutable record conflict"):
            mirror.hydrate_sources(self.drive, self.stage, self.run_id, repository_sha="c" * 40)
        self.assertEqual(hydration_path.read_bytes(), before)
        self.assertEqual(self.acquisition_path.read_bytes(), original_acquisition)
        self.assertEqual(mirror_path.read_bytes(), original_mirror)
        with self.assertRaisesRegex(ValueError, "exact commit"):
            mirror.hydrate_sources(self.drive, self.stage, self.run_id, repository_sha="main")

    def test_hydration_retry_preserves_original_publisher_and_runtime(self):
        self.publish()
        mirror.hydrate_sources(self.drive, self.stage, self.run_id, repository_sha="b" * 40)
        hydration_path = self.acquisition_path.with_name("hydration.json")
        before = hydration_path.read_bytes()
        with patch("giab_wes_nextflow.mirror.__version__", "0.2.0-dev.999"), patch("giab_wes_nextflow.mirror.platform.machine", return_value="changed-test-runtime"):
            mirror.hydrate_sources(self.drive, self.stage, self.run_id, repository_sha="b" * 40)
        self.assertEqual(hydration_path.read_bytes(), before)

    def test_complete_partial_is_promoted_without_a_range_request(self):
        resource = self.manifest["resources"][0]
        final = self.stage / resource["destination"]
        expected = final.read_bytes()
        final.rename(Path(str(final) + ".part"))
        with patch("giab_wes_nextflow.acquisition.urllib.request.urlopen", side_effect=AssertionError("network must not be used")) as opener:
            result = acquisition.acquire(resource, self.stage, opener=opener)
        self.assertEqual(final.read_bytes(), expected)
        self.assertTrue(result["response"]["recovered_complete_partial"])
        opener.assert_not_called()

    def test_two_copies_cannot_mutate_a_validated_temporary_before_promotion(self):
        resource = self.manifest["resources"][0]
        observed = self.acquisition["observations"][0]
        source = self.stage / resource["destination"]
        target = self.drive / "cache/verified-sources" / resource["destination"]
        first_validated = threading.Event()
        release_first = threading.Event()
        second_lock_attempt = threading.Event()
        second_copy = threading.Event()
        original_validate = mirror.validate_source_bytes
        original_copy = mirror.shutil.copy2
        original_lock = mirror.lock
        failures = []

        def guarded_lock(path, timeout=15):
            if threading.current_thread().name == "second-copy":
                second_lock_attempt.set()
            return original_lock(path, timeout=timeout)

        def copy(source_path, target_path):
            if threading.current_thread().name == "second-copy":
                Path(target_path).write_bytes(b"x")
                second_copy.set()
                raise OSError("injected interruption after overlapping truncate")
            return original_copy(source_path, target_path)

        def validate(path, item, obs=None):
            original_validate(path, item, obs)
            if threading.current_thread().name == "first-copy" and str(path).endswith(".incomplete"):
                first_validated.set()
                if not release_first.wait(5):
                    raise TimeoutError("test promotion barrier timed out")

        def run():
            try:
                mirror._copy_verified(source, target, resource, observed)
            except Exception as error:
                failures.append(error)

        with patch("giab_wes_nextflow.mirror.lock", side_effect=guarded_lock), patch("giab_wes_nextflow.mirror.shutil.copy2", side_effect=copy), patch("giab_wes_nextflow.mirror.validate_source_bytes", side_effect=validate):
            first = threading.Thread(target=run, name="first-copy", daemon=True)
            second = threading.Thread(target=run, name="second-copy", daemon=True)
            first.start()
            try:
                self.assertTrue(first_validated.wait(2))
                second.start()
                self.assertTrue(second_lock_attempt.wait(2))
                self.assertFalse(second_copy.is_set())
            finally:
                release_first.set()
                first.join(3)
                if second.ident is not None:
                    second.join(3)
            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
        self.assertEqual(failures, [])
        self.assertFalse(second_copy.is_set())
        self.assertEqual(target.read_bytes(), source.read_bytes())

    def test_hydration_without_verified_current_sha_records_null(self):
        self.publish()
        mirror.hydrate_sources(self.drive, self.stage, self.run_id)
        hydration = json.loads(self.acquisition_path.with_name("hydration.json").read_text())
        self.assertIsNone(hydration["repository_sha"])

    def test_historical_manifest_resource_change_is_rejected(self):
        self.publish()
        bad = json.loads(json.dumps(self.manifest))
        bad["resources"][0]["checksum"]["expected"] = "0" * 32
        historical = self.base / "bad-history.json"
        historical.write_text(json.dumps(bad))
        with self.assertRaisesRegex(ValueError, "resource contracts"):
            mirror.hydrate_sources(self.drive, self.stage, self.run_id, historical, "recovery")

    def test_run_path_traversal_and_missing_repository_sha_fail_before_writes(self):
        for value in [".", "..", "../../../escaped", "/absolute", "a/b"]:
            with self.assertRaises(ValueError):
                mirror.mirror_sources(self.stage, self.drive, value, self.repository_sha)
            with self.assertRaises(ValueError):
                mirror.hydrate_sources(self.drive, self.stage, value)
        with self.assertRaises(ValueError):
            mirror.mirror_sources(self.stage, self.drive, self.run_id, "unknown")
        self.assertEqual(list(self.drive.iterdir()), [])

    def test_schema_forgery_md5_and_manifest_mismatches_are_rejected(self):
        for mutator in [lambda r: r.pop("schema_version"),
                        lambda r: r.update(source_manifest_sha256="0" * 64),
                        lambda r: r["observations"].append(r["observations"][0])]:
            record = json.loads(json.dumps(self.acquisition))
            mutator(record)
            self.acquisition_path.write_text(json.dumps(record))
            with self.assertRaises((ValueError, ValidationError)):
                self.publish()
        self.acquisition_path.write_text(json.dumps(self.acquisition))
        first = self.manifest["resources"][0]
        artifact = self.stage / first["destination"]
        artifact.write_bytes(b"x" * first["bytes"])
        self.acquisition["observations"][0]["sha256"] = acquisition.checksum(artifact)
        self.acquisition_path.write_text(json.dumps(self.acquisition))
        with self.assertRaisesRegex(ValueError, "MD5"):
            self.publish()
        self.assertEqual(list(self.drive.iterdir()), [])

    def test_corrupt_cache_rejected_on_both_mirror_retry_and_hydrate(self):
        self.publish()
        item = self.manifest["resources"][0]
        (self.drive / "cache/verified-sources" / item["destination"]).write_bytes(b"corrupt")
        with self.assertRaises(ValueError):
            self.publish()
        shutil.rmtree(self.stage)
        with self.assertRaises(ValueError):
            mirror.hydrate_sources(self.drive, self.stage, self.run_id)
        self.assertFalse(self.stage.exists())

    def test_duplicate_or_traversing_mirror_inventory_is_rejected(self):
        path = self.publish()
        original = json.loads(path.read_text())
        for mutate in [lambda r: r["objects"].append(r["objects"][0]),
                       lambda r: r["objects"][0].update(destination="../escape"),
                       lambda r: r.update(source_manifest_sha256="0" * 64)]:
            record = json.loads(json.dumps(original))
            mutate(record)
            path.write_text(json.dumps(record))
            with self.assertRaises(ValueError):
                mirror.hydrate_sources(self.drive, self.stage, self.run_id)

    def test_invalid_acquisition_and_mirror_timestamps_fail_without_format_extras(self):
        self.acquisition["created_utc"] = "not-a-date"
        self.acquisition_path.write_text(json.dumps(self.acquisition))
        with self.assertRaises((ValueError, ValidationError)):
            self.publish()
        self.acquisition["created_utc"] = acquisition.now()
        self.acquisition_path.write_text(json.dumps(self.acquisition))
        path = self.publish()
        record = json.loads(path.read_text())
        record["created_utc"] = "2026-09-07T01:00:00"
        path.write_text(json.dumps(record))
        with self.assertRaises((ValueError, ValidationError)):
            mirror.hydrate_sources(self.drive, self.stage, self.run_id)

    def test_source_and_cache_symlinks_fail_without_following_external_bytes(self):
        external = self.base / "external"
        external.write_bytes(b"do not copy")
        first = self.stage / self.manifest["resources"][0]["destination"]
        first.unlink()
        first.symlink_to(external)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.publish()
        first.unlink()
        first.write_bytes(f"deterministic nonhuman source object 0\n".encode())
        self.publish()
        cache = self.drive / "cache/verified-sources" / self.manifest["resources"][0]["destination"]
        cache.unlink()
        cache.symlink_to(external)
        with self.assertRaisesRegex(ValueError, "symlink"):
            mirror.hydrate_sources(self.drive, self.stage, self.run_id)
        self.assertEqual(external.read_bytes(), b"do not copy")

    def test_nested_cache_safety_marker_prevents_cache_access(self):
        cache = self.drive / "cache"
        cache.mkdir()
        (cache / "DO NOT ACCESS WITH CHATGPT").touch()
        with self.assertRaises(PermissionError):
            self.publish()
        self.assertEqual([path.name for path in cache.iterdir()], ["DO NOT ACCESS WITH CHATGPT"])

    def test_interrupted_copy_has_no_promoted_object_or_record(self):
        with patch("giab_wes_nextflow.mirror.shutil.copy2", side_effect=OSError("injected copy failure")):
            with self.assertRaises(OSError):
                self.publish()
        self.assertFalse((self.drive / f"registry/runs/{self.run_id}/verified-source-mirror.json").exists())
        self.publish()

    def test_unknown_and_changed_acquisition_selections_fail_closed(self):
        with self.assertRaises(SystemExit):
            acquisition.main(["--workspace", str(self.stage), "--run-id", "new-run", "--only", "typo"])
        with self.assertRaisesRegex(ValueError, "selection differs"):
            acquisition.main(["--workspace", str(self.stage), "--run-id", self.run_id,
                              "--only", self.manifest["resources"][0]["id"]])


class PathSafetyTest(unittest.TestCase):
    def test_mac_system_aliases_share_a_canonical_containment_root(self):
        self.assertEqual(acquisition.destination(Path("/tmp/m2-test"), "a/b"), Path("/tmp/m2-test/a/b").resolve())

    def test_explicit_manifest_path_is_guarded_before_reading(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch("pathlib.Path.read_text", side_effect=AssertionError("prohibited read")):
                with self.assertRaises(PermissionError):
                    acquisition.load_manifest(root / "DO NOT ACCESS WITH CHATGPT area" / "manifest.json")
            (root / "DO NOT ACCESS WITH CHATGPT").touch()
            with patch("pathlib.Path.read_text", side_effect=AssertionError("prohibited read")):
                with self.assertRaises(PermissionError):
                    acquisition.load_manifest(root / "child" / "manifest.json")

    def test_stdlib_timestamp_validation_requires_a_real_date_and_timezone(self):
        acquisition.validate_timestamp("2026-09-07T01:02:03Z")
        for value in ["nonsense", "2026-09-07", "2026-09-07T01:02:03", "2026-02-31T01:02:03Z", None]:
            with self.assertRaises(ValueError):
                acquisition.validate_timestamp(value)

    def test_forbidden_ancestor_name_and_marker_fail_before_access(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(PermissionError):
                acquisition.safe_root(root / "DO NOT ACCESS WITH CHATGPT private" / "m2-stage")
            (root / "DO NOT ACCESS WITH CHATGPT").touch()
            with self.assertRaises(PermissionError):
                acquisition.safe_root(root / "m2-stage")


if __name__ == "__main__":
    unittest.main()
