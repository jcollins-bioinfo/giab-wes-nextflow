"""Exercise launcher identity gates in real temporary Git repositories."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


LAUNCHER = Path(__file__).resolve().parents[2] / "scripts/run_m2_readiness.sh"
ORIGIN = "https://github.com/jcollins-bioinfo/giab-wes-nextflow.git"


class ReadinessIdentityTest(unittest.TestCase):
    """An observed SHA must identify exactly the clean source being installed."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "--quiet")
        self.git("config", "user.name", "Synthetic test")
        self.git("config", "user.email", "synthetic@example.invalid")
        shutil.copyfile(LAUNCHER, self.root / "launcher.sh")
        self.git("add", "launcher.sh")
        self.git("commit", "--quiet", "-m", "synthetic fixture")
        self.sha = self.git("rev-parse", "HEAD")
        self.git("remote", "add", "origin", ORIGIN)

    def git(self, *args: str) -> str:
        """Run Git against only the disposable synthetic repository."""
        return subprocess.run(
            ["git", *args], cwd=self.root, check=True, text=True, capture_output=True
        ).stdout.strip()

    def launch(self, ref: str | None = None) -> subprocess.CompletedProcess[str]:
        """Identity mode checks provenance without installing or reading data."""
        env = {key: value for key, value in os.environ.items() if not key.startswith("BASH_FUNC_")}
        env["REPOSITORY_REF"] = ref or self.sha
        return subprocess.run(
            ["bash", "launcher.sh", "identity"], cwd=self.root,
            env=env, capture_output=True, text=True, check=False,
        )

    def test_exact_origin_and_clean_sha_pass(self) -> None:
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(self.sha, result.stdout)

    def test_missing_or_lookalike_origin_fails_without_url_disclosure(self) -> None:
        for origin in (ORIGIN + "/lookalike", "https://credential@example.invalid/" + ORIGIN):
            self.git("remote", "set-url", "origin", origin)
            result = self.launch()
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(origin, result.stdout + result.stderr)
        self.git("remote", "remove", "origin")
        self.assertNotEqual(self.launch().returncode, 0)

    def test_resolved_but_not_checked_out_sha_fails(self) -> None:
        self.git("commit", "--allow-empty", "--quiet", "-m", "another synthetic commit")
        result = self.launch(self.sha)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not the checked-out", result.stderr)

    def test_tracked_and_untracked_changes_fail(self) -> None:
        (self.root / "untracked.py").write_text("# synthetic\n")
        self.assertNotEqual(self.launch().returncode, 0)
        (self.root / "untracked.py").unlink()
        with (self.root / "launcher.sh").open("a") as stream:
            stream.write("\n# modified\n")
        self.assertNotEqual(self.launch().returncode, 0)


if __name__ == "__main__":
    unittest.main()
