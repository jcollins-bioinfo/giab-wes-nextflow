"""Verify isolated imports and installed byte identity using synthetic checkouts."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import giab_wes_nextflow


class RuntimeIdentityTest(unittest.TestCase):
    """Import shadowing and stale installs must fail before acquisition or mirroring."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "reviewed"
        shutil.copytree(
            Path(giab_wes_nextflow.__file__).parent, self.root / "src/giab_wes_nextflow",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        for args in (["init", "--quiet"], ["config", "user.name", "Synthetic test"],
                     ["config", "user.email", "synthetic@example.invalid"], ["add", "src"],
                     ["commit", "--quiet", "-m", "synthetic package checkout"]):
            subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)
        self.sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.root,
                                  check=True, text=True, capture_output=True).stdout.strip()

    def run_identity(self, expected_sha: str | None = None) -> subprocess.CompletedProcess[str]:
        """Use the launcher's isolated import boundary with a hostile PYTHONPATH."""
        shadow = Path(self.temp.name) / "shadow"
        shadow.mkdir(exist_ok=True)
        (shadow / "giab_wes_nextflow.py").write_text("raise RuntimeError('shadow package executed')\n")
        env = dict(os.environ, PYTHONPATH=str(shadow))
        return subprocess.run(
            [sys.executable, "-I", "-m", "giab_wes_nextflow.runtime_identity", "--source-root",
             str(self.root), "--expected-sha", expected_sha or self.sha], env=env,
            cwd=shadow, text=True, capture_output=True, check=False,
        )

    def test_shadow_path_cannot_override_installed_package(self) -> None:
        result = self.run_identity()
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads(result.stdout)
        self.assertEqual(record["repository_sha"], self.sha)
        self.assertGreater(record["files"], 5)

    def test_wrong_reviewed_commit_fails(self) -> None:
        result = self.run_identity("0" * 40)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("commit changed", result.stderr)

    def test_changed_source_or_installed_inventory_fails(self) -> None:
        path = self.root / "src/giab_wes_nextflow/__init__.py"
        path.write_text(path.read_text() + "\n# changed source\n")
        self.assertNotEqual(self.run_identity().returncode, 0)
        subprocess.run(["git", "add", "src"], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "--quiet", "-m", "changed synthetic source"],
                       cwd=self.root, check=True)
        result = self.run_identity()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("do not match", result.stderr)


if __name__ == "__main__":
    unittest.main()
