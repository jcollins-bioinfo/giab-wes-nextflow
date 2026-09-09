"""Restart boundary tests using invented metadata, never genomic execution."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from giab_wes_nextflow.canonical_checkpoint import completed, hydrate, inventory
from giab_wes_nextflow.canonical_science import stage_file, write_json


class CanonicalRestartTests(unittest.TestCase):
    """Interrupted copies remain partial; completion markers are unambiguous."""

    def setUp(self):
        """Make one tiny authenticated fake completed stage."""
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.source = Path(temp.name).resolve() / 'source'; self.source.mkdir()
        self.target = self.source.parent / 'target'
        (self.source / 'receipt.json').write_text('{"test_only":true}')
        write_json(self.source / 'stage-complete.json', {
            'kind': 'canonical_completed_stage', 'key': 'test-binding', 'files': inventory(self.source)})

    def test_interrupted_copy_never_creates_final_and_retry_recovers(self):
        """A killed copy can leave truncated temporary bytes, never final bytes."""
        def interrupted(source, partial):
            Path(partial).write_bytes(b'{'); raise OSError('invented interruption')
        with patch('giab_wes_nextflow.canonical_checkpoint.shutil.copyfile', side_effect=interrupted):
            with self.assertRaisesRegex(OSError, 'invented interruption'):
                hydrate(self.source, self.target, 'test-binding')
        self.assertFalse((self.target / 'receipt.json').exists())
        self.assertTrue((self.target / 'receipt.json.incomplete').exists())
        hydrate(self.source, self.target, 'test-binding')
        self.assertEqual(inventory(self.source), inventory(self.target))

    def test_verified_partial_can_promote_without_copying_again(self):
        """An interruption before rename does not force another complete copy."""
        self.target.mkdir()
        (self.target / 'receipt.json.incomplete').write_bytes((self.source / 'receipt.json').read_bytes())
        with patch('giab_wes_nextflow.canonical_checkpoint.shutil.copyfile', side_effect=AssertionError('unexpected copy')):
            hydrate(self.source, self.target, 'test-binding')
        self.assertEqual(inventory(self.source), inventory(self.target))

    def test_existing_changed_final_is_not_overwritten(self):
        """Atomic restart does not authorize replacing conflicting completed data."""
        self.target.mkdir(); (self.target / 'receipt.json').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'scratch restart conflict'):
            hydrate(self.source, self.target, 'test-binding')

    def test_duplicate_marker_keys_are_rejected(self):
        """A duplicate identity key cannot silently replace the original value."""
        marker = self.source / 'stage-complete.json'
        value = json.loads(marker.read_text())
        marker.write_text('{"key":"other",' + json.dumps(value)[1:])
        with self.assertRaisesRegex(ValueError, 'duplicate JSON'):
            completed(self.source, 'test-binding')

    def test_independent_staging_copy_recovers_from_interruption(self):
        """Caller/private staging never promotes a truncated final file."""
        source = self.source / 'receipt.json'; target = self.target / 'receipt.json'
        def interrupted(source, partial):
            Path(partial).write_bytes(b'{'); raise OSError('invented interruption')
        with patch('giab_wes_nextflow.canonical_science.shutil.copyfile', side_effect=interrupted):
            with self.assertRaisesRegex(OSError, 'invented interruption'):
                stage_file(source, target)
        self.assertFalse(target.exists())
        stage_file(source, target)
        self.assertEqual(source.read_bytes(), target.read_bytes())
