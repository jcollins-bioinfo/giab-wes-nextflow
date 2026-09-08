"""Check that the owner capability report cannot launch or claim genomic work."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from giab_wes_nextflow.canonical_host import INDEX_ESTIMATE_BYTES, probe


class HostProbeTests(unittest.TestCase):
    """Use temporary storage and mocked observations; never invoke real Docker."""

    def test_observation_is_safe_and_noncanonical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            drive = root / "giab-wes-nextflow-private"
            drive.mkdir()
            memory = {"physical_bytes": 16 * 2**30, "cgroup_limit_bytes": None,
                      "effective_ceiling_bytes": 16 * 2**30}
            with patch("giab_wes_nextflow.canonical_host.shutil.which", return_value=None), \
                 patch("giab_wes_nextflow.canonical_host.memory_limits", return_value=memory):
                report = probe(drive, root)
            self.assertFalse(report["canonical_ready"])
            self.assertFalse(report["index_estimate_fits_memory_before_headroom"])
            self.assertEqual(report["index_build_documentation_estimate_bytes"], INDEX_ESTIMATE_BYTES)
            self.assertFalse(report["drive_quota_verified"])
            self.assertNotIn(str(root), json.dumps(report))
            self.assertEqual(list(drive.iterdir()), [])

    def test_drive_scratch_and_prohibited_root_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            drive = root / "giab-wes-nextflow-private"
            drive.mkdir()
            with self.assertRaisesRegex(ValueError, "outside Drive"):
                probe(drive, drive)
            (drive / "DO NOT ACCESS WITH CHATGPT").touch()
            with self.assertRaises(PermissionError):
                probe(drive, root)


if __name__ == "__main__":
    unittest.main()
