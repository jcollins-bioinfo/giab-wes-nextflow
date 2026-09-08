"""Prevent build archives from silently including workflow scratch or link targets."""
from __future__ import annotations

import importlib.util
import io
from pathlib import Path
import tarfile
import stat
import tempfile
import unittest
import zipfile

SPEC = importlib.util.spec_from_file_location("check_distributions", Path(__file__).resolve().parents[2] / "scripts/check_distributions.py")
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class DistributionTest(unittest.TestCase):
    """Inspect deliberately unsafe synthetic archive metadata without extraction."""

    def test_nested_work_and_genomic_artifacts_are_rejected(self) -> None:
        """Broad include matches must not leak ignored test work or generated data."""
        names = ("package/.nf-test/tests/hash/work/input.json", "package/tests/data/m3-generated/reference-source.json",
                 "package/tests/tiny.bam", "package/__pycache__/code.pyc", "../escape.py", "/absolute.py")
        for name in names:
            with self.subTest(name=name), self.assertRaises(ValueError):
                CHECK.validate_member(name, 20, linked=False, regular=True)

    def test_tar_links_fail_without_extraction(self) -> None:
        """An absolute link cannot bypass output artifact path guards."""
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "unsafe.tar.gz"
            with tarfile.open(archive_path, "w:gz") as archive:
                item = tarfile.TarInfo("package/config.json")
                item.type = tarfile.SYMTYPE
                item.linkname = "/invented/external.json"
                archive.addfile(item)
            with self.assertRaisesRegex(ValueError, "regular file"):
                CHECK.validate_archive(archive_path)
            self.assertEqual([path.name for path in Path(directory).iterdir()], ["unsafe.tar.gz"])

    def test_m4_generated_metadata_is_rejected_in_both_archive_formats(self) -> None:
        """Generated M4 JSON must fail independently of genomic suffix or build exclusions."""
        member = "package/tests/data/m4-generated/reference-source.json"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "unsafe.tar.gz"
            with tarfile.open(source, "w:gz") as archive:
                item = tarfile.TarInfo(member)
                item.size = 2
                archive.addfile(item, io.BytesIO(b"{}"))
            wheel = root / "unsafe.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr(member, "{}")
            for path in (source, wheel):
                with self.subTest(format=path.suffix), self.assertRaisesRegex(ValueError, "generated or prohibited"):
                    CHECK.validate_archive(path)
            self.assertEqual({path.name for path in root.iterdir()}, {"unsafe.tar.gz", "unsafe.whl"})

    def test_source_code_and_schema_archive_is_accepted(self) -> None:
        """Small authored source files pass the independent distribution inventory."""
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "safe.tar.gz"
            with tarfile.open(archive_path, "w:gz") as archive:
                for name in ("package/src/example.py", "package/schemas/example.json"):
                    item = tarfile.TarInfo(name)
                    item.size = 2
                    archive.addfile(item, io.BytesIO(b"{}"))
            self.assertEqual(CHECK.validate_archive(archive_path), 2)

    def test_wheel_special_file_modes_are_rejected(self) -> None:
        """ZIP metadata must not encode FIFO or device entries in a wheel."""
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "unsafe.whl"
            with zipfile.ZipFile(archive_path, "w") as archive:
                item = zipfile.ZipInfo("package/config.json")
                item.create_system = 3
                item.external_attr = (stat.S_IFIFO | 0o600) << 16
                archive.writestr(item, "{}")
            with self.assertRaisesRegex(ValueError, "regular file"):
                CHECK.validate_archive(archive_path)


if __name__ == "__main__":
    unittest.main()
