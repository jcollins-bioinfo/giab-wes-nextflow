"""Invented source and registry tests for canonical launcher asset recovery."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any
import unittest
from unittest.mock import patch

from giab_wes_nextflow import canonical_run as driver
from giab_wes_nextflow import canonical_assets as assets
from giab_wes_nextflow.acquisition import checksum


class CanonicalAssetIntegrationTest(unittest.TestCase):
    """Exercise launcher boundaries without network, Docker or human genomic inputs."""

    def setUp(self) -> None:
        """Make two independently pinned invented files and one isolated Drive stand-in."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.stage = self.root / 'stage'
        self.drive = self.root / 'drive'
        self.drive.mkdir()
        self.content = b'invented-source-content'
        self.source = self.resource('toy', 'reads/toy.data')
        self.annotation = self.resource('annotation', 'gencode/toy.data')
        for context in (patch.object(driver, 'load_manifest', return_value={'resources': [self.source]}),
                        patch.object(driver, 'GTF', self.annotation), patch.object(driver, 'progress')):
            context.start()
            self.addCleanup(context.stop)

    def resource(self, name: str, target: str) -> dict[str, Any]:
        """Declare only test bytes and an unreachable URL to expose unintended networking."""
        return {'id': name, 'destination': target, 'filename': Path(target).name,
                'bytes': len(self.content), 'checksum': {'algorithm': 'md5', 'expected': hashlib.md5(self.content).hexdigest()},
                'url': 'https://invalid.example/' + name}

    def cache(self, resource: dict[str, Any]) -> Path:
        """Populate the exact preexisting M2 durable layout with declared toy bytes."""
        path = self.drive / 'cache/verified-sources' / resource['destination']
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.content)
        return path

    def test_previous_m2_cache_reuses_bytes_without_old_manifest(self) -> None:
        """Current source pins suffice; no old acquisition/target-gate metadata is relabelled."""
        for resource in (self.source, self.annotation):
            self.cache(resource)
        with patch('urllib.request.urlopen', side_effect=AssertionError('unexpected network')):
            sources, proof = driver.source_cache(self.stage, self.drive, False)
        self.assertEqual(set(sources), {'toy', 'annotation'})
        self.assertTrue(all(path.read_bytes() == self.content for path in sources.values()))
        self.assertTrue(all(row['cache_destination_rehashed'] for row in proof['objects'].values()))

    def test_downloads_disabled_reject_corrupt_existing_local_before_acquire(self) -> None:
        """An existing corrupt local file cannot turn a cache-only request into networking."""
        path = self.stage / self.source['destination']
        path.parent.mkdir(parents=True)
        path.write_bytes(b'corrupt')
        with patch.object(driver, 'acquire') as acquire, self.assertRaises(PermissionError):
            driver.source_cache(self.stage, self.drive, False)
        acquire.assert_not_called()

    def test_corrupt_durable_source_is_not_replaced_or_redownloaded(self) -> None:
        """A declared cache mismatch remains explicit and leaves original bytes available."""
        cached = self.cache(self.source)
        cached.write_bytes(b'corrupt')
        with patch.object(driver, 'acquire') as acquire, self.assertRaises(ValueError):
            driver.source_cache(self.stage, self.drive, True)
        acquire.assert_not_called()
        self.assertEqual(cached.read_bytes(), b'corrupt')

    def test_registry_filters_old_contract_and_partial_records(self) -> None:
        """Only complete metadata matching current installed contracts can select hydration."""
        folder = self.drive / 'registry/assets/run'
        folder.mkdir(parents=True)
        base = {'kind': 'canonical_reference_asset', 'reference_id': 'a' * 64, 'asset_id': 'b' * 64}
        (folder / 'old.json').write_text(json.dumps({**base, 'asset_contract_sha256': 'old'}))
        (folder / 'partial.json.incomplete').write_text('interrupted json')
        with patch.object(assets, 'asset_contract_sha256', return_value='current'), patch.object(assets, 'hydrate_assets', return_value=base) as hydrate:
            self.assertIsNone(driver.asset_restore(self.drive, self.stage, base['kind']))
            hydrate.assert_not_called()
            (folder / 'new.json').write_text(json.dumps({**base, 'asset_contract_sha256': 'current'}))
            self.assertEqual(driver.asset_restore(self.drive, self.stage, base['kind']), base)
            hydrate.assert_called_once_with(self.drive, base['reference_id'], base['asset_id'], self.stage, kind=base['kind'])

    def test_registry_symlink_ancestor_rejected_before_records_are_read(self) -> None:
        """Discovery never follows a run-directory symlink to read unrelated metadata."""
        registry = self.drive / 'registry/assets'
        registry.mkdir(parents=True)
        elsewhere = self.root / 'other'
        elsewhere.mkdir()
        (elsewhere / 'record.json').write_text('{}')
        (registry / 'run').symlink_to(elsewhere, target_is_directory=True)
        with patch.object(driver, 'load_json') as read, self.assertRaises(ValueError):
            driver.asset_restore(self.drive, self.stage, 'canonical_reference_asset')
        read.assert_not_called()

    def test_partial_domain_recovers_before_marker_and_complete_bytes_are_checked(self) -> None:
        """Interrupted domain promotion resumes without redefining any approved intervals."""
        from giab_wes_nextflow import coding_domain
        directory = self.root / 'domains'
        directory.mkdir()
        data = b'chrToy\t0\t1\n'
        (directory / 'R_call.bed').write_bytes(data)
        (directory / 'R_eval_holdout.bed.incomplete').write_bytes(b'interrupted')
        expected = {name: (1, 1, hashlib.sha256(data).hexdigest()) for name in ('R_call', 'R_eval_full', 'R_eval_holdout')}
        record = {'outputs': expected, 'status': 'invented'}
        # JSON persistence normalizes tuples; the constructor's production records are JSON primitives.
        record = json.loads(json.dumps(record))
        def construct(gtf: Path, fai: Path, confidence: Path, output: Path | None = None) -> dict[str, Any]:
            """Simulate only fixed tiny BED serialization, never scientific qualification."""
            if output is not None:
                output.mkdir()
                for name in expected:
                    (output / (name + '.bed')).write_bytes(data)
                (output / 'domain-complete.json').write_text(json.dumps(record))
            return record
        sources = {name: self.root / 'unused' for name in ('gencode_v50_basic', 'grch38_compressed_fai', 'hg001_v421_high_confidence_bed')}
        with patch.object(coding_domain, 'construct', side_effect=construct), patch.object(coding_domain, 'EXPECTED', expected):
            self.assertEqual(driver.prepare_domains(sources, directory), record)
            self.assertTrue((directory / 'domain-complete.json').is_file())
            self.assertEqual(driver.prepare_domains(sources, directory), record)
            (directory / 'R_call.bed').write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError, 'drift'):
                driver.prepare_domains(sources, directory)


if __name__ == '__main__':
    unittest.main()
