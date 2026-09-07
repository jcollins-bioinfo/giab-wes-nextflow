"""Test publication safety with invented bytes and the real M3 bundle validator.

The unit helper's binary identity stand-ins are not executable BAM qualification;
that acceptance belongs to the independent Docker integration driver.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from giab_wes_nextflow.acquisition import checksum
from giab_wes_nextflow import m3_publication as publication
from test_m3_support import make_unit_bundle


class PublicationTest(unittest.TestCase):
    """Assert append-only identity, completion ordering, and recovery invariants."""

    def setUp(self) -> None:
        """Prepare fresh invented input and a correctly named private test root."""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bundle = make_unit_bundle(self.root / "source")
        self.drive = self.root / "giab-wes-nextflow-private"
        self.run_id = "m3-unit-contract"

    def test_dry_run_and_inventory_do_not_create_destination(self) -> None:
        """Read-only estimates validate sources without starting a publication."""
        result = publication.publish_bundle(self.bundle, self.drive, dry_run=True)
        self.assertFalse(self.drive.exists())
        self.assertEqual(len(result["artifacts"]), 6)
        self.assertGreater(result["bytes"], 0)
        self.assertEqual(result["bytes"], result["additional_bundle_bytes"])
        self.assertNotIn(str(self.root), json.dumps(result))
        self.assertFalse(result["would_copy_genomic_bytes"])

    def test_publish_retry_and_hydration_preserve_exact_bytes(self) -> None:
        """Completed retries preserve metadata; recovered artifacts match each hash."""
        # Explicitly place an excluded artifact beside the result; the allowlist
        # must prevent it from entering the synthetic evidence namespace.
        (self.bundle / "excluded.bam").write_bytes(b"invented excluded bytes")
        first = publication.publish_bundle(self.bundle, self.drive)
        final, checked = publication.validate_publication(self.drive, self.run_id)
        self.assertEqual(first, checked)
        self.assertEqual(publication.publish_bundle(self.bundle, self.drive), first)
        self.assertEqual({path.name for path in final.iterdir()}, set(publication.FILENAMES) | {"COMPLETED.json"})
        recovered = self.root / "recovery"
        publication.hydrate_bundle(self.drive, self.run_id, recovered, dry_run=True)
        self.assertFalse(recovered.exists())
        self.assertEqual(publication.hydrate_bundle(self.drive, self.run_id, recovered), first)
        self.assertEqual(publication.hydrate_bundle(self.drive, self.run_id, recovered), first)
        for name in publication.FILENAMES:
            self.assertEqual(checksum(recovered / name), checksum(self.bundle / name))
        self.assertEqual(json.loads((recovered / "M3_EVIDENCE_RECOVERED.json").read_text()), first)

    def test_interruption_before_marker_is_recoverable_but_not_complete(self) -> None:
        """A missing final marker blocks consumers even after registry promotion."""
        writer = publication.write_record

        def interrupted(path: Path, record: dict) -> None:
            """Inject one storage interruption at the acceptance boundary only."""
            if path.name == "COMPLETED.json":
                raise OSError("injected interruption before completion marker")
            writer(path, record)

        with patch.object(publication, "write_record", side_effect=interrupted):
            with self.assertRaisesRegex(OSError, "injected interruption"):
                publication.publish_bundle(self.bundle, self.drive)
        with self.assertRaises(FileNotFoundError):
            publication.validate_publication(self.drive, self.run_id)
        registry = self.drive / "registry/milestones/M3/synthetic/m3-unit-contract.json"
        recorded = registry.read_bytes()
        publication.publish_bundle(self.bundle, self.drive)
        self.assertEqual(recorded, registry.read_bytes())
        publication.validate_publication(self.drive, self.run_id)

    def test_conflicting_run_identity_preserves_completed_publication(self) -> None:
        """A new code identity cannot overwrite the same published run identifier."""
        first = publication.publish_bundle(self.bundle, self.drive)
        other = make_unit_bundle(self.root / "other", repository_sha="b" * 40)
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            publication.publish_bundle(other, self.drive)
        self.assertEqual(publication.validate_publication(self.drive, self.run_id)[1], first)

    def test_corruption_and_missing_marker_block_hydration(self) -> None:
        """No stale registry or marker can replace a destination byte check."""
        publication.publish_bundle(self.bundle, self.drive)
        final, _ = publication.validate_publication(self.drive, self.run_id)
        original = (final / "m3-qc.json").read_bytes()
        (final / "m3-qc.json").write_bytes(original + b" ")
        with self.assertRaises(ValueError):
            publication.hydrate_bundle(self.drive, self.run_id, self.root / "corrupt-recovery")
        self.assertFalse((self.root / "corrupt-recovery").exists())
        with self.assertRaises(ValueError):
            publication.publish_bundle(self.bundle, self.drive)
        (final / "m3-qc.json").write_bytes(original)
        (final / "COMPLETED.json").unlink()
        with self.assertRaises(FileNotFoundError):
            publication.validate_publication(self.drive, self.run_id)

    def test_marker_and_registry_must_agree(self) -> None:
        """Completion metadata is immutable evidence rather than an existence flag."""
        publication.publish_bundle(self.bundle, self.drive)
        final, record = publication.validate_publication(self.drive, self.run_id)
        record["publisher_architecture"] = "invented-other-architecture"
        (final / "COMPLETED.json").write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, "differs from its registry"):
            publication.validate_publication(self.drive, self.run_id)

    def test_path_guards_apply_before_any_write(self) -> None:
        """Reject ancestor markers, prohibited names, symlinks and nested roots."""
        forbidden = self.root / "DO NOT ACCESS WITH CHATGPT examples" / "giab-wes-nextflow-private"
        with self.assertRaises(PermissionError):
            publication.publish_bundle(self.bundle, forbidden)
        self.assertFalse(forbidden.parent.exists())
        link = self.root / "linked-bundle"
        link.symlink_to(self.bundle, target_is_directory=True)
        with self.assertRaises(ValueError):
            publication.publish_bundle(link, self.drive)
        self.drive.mkdir()
        marker = self.drive / "DO NOT ACCESS WITH CHATGPT"
        marker.touch()
        with self.assertRaises(PermissionError):
            publication.publish_bundle(self.bundle, self.drive)
        marker.unlink()
        with self.assertRaises(ValueError):
            publication.hydrate_bundle(self.drive, self.run_id, self.drive / "recovery")
        with self.assertRaises(ValueError):
            publication.validate_publication(self.drive, "../escape")

    def test_oversized_and_symlinked_json_are_rejected(self) -> None:
        """The publication cap and link guard run before parsing untrusted JSON."""
        path = self.bundle / "m3-resources.json"
        original = path.read_bytes()
        path.write_bytes(b" " * (publication.MAX_FILE_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "oversized"):
            publication.publish_bundle(self.bundle, self.drive)
        path.unlink()
        target = self.root / "resources.json"
        target.write_bytes(original)
        path.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "symlink"):
            publication.publish_bundle(self.bundle, self.drive)
        self.assertFalse(self.drive.exists())


if __name__ == "__main__":
    unittest.main()
