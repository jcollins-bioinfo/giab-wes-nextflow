"""Negative manifest and independent/cache qualification gates without Docker."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from giab_wes_nextflow.m5_manifest import read_manifest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('m5_nextflow_qualification', ROOT / 'scripts/m5_nextflow_qualification.py')
HELPER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HELPER)


def traces() -> dict[str, str]:
    """Produce only synthetic task-state observations for the four-mode oracle."""
    result = {}
    for phase in HELPER.PHASES:
        callers = (phase,) if phase in ('gatk', 'deepvariant') else ('gatk', 'deepvariant')
        rows = ['task_id\thash\tname\tstatus\texit\tattempt']
        for caller in callers:
            for process in ('M5_NORMALIZE', 'M5_BENCHMARK'):
                task_id = (1 if caller == 'gatk' else 3) + (process == 'M5_BENCHMARK')
                rows.append(f'{task_id}\taa/{task_id:06d}\tW:{process} ({caller}:full)\t' + ('COMPLETED' if phase in ('gatk', 'deepvariant') else 'CACHED') + '\t0\t1')
        result[phase] = '\n'.join(rows) + '\n'
    return result


class ManifestGateTests(unittest.TestCase):
    """Reject ambiguous values before any scientific path is resolved by Nextflow."""

    def test_duplicate_top_level_nested_and_nonstandard_json_rejected(self) -> None:
        """Duplicate values must fail even when they are identical or nested."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manifest.json'
            for text in ('{"sample":"a","sample":"b"}', '{"queries":[{"caller":"gatk","caller":"gatk"}]}', '{"x":NaN}', '[]'):
                path.write_text(text)
                with self.subTest(text=text), self.assertRaises(ValueError):
                    read_manifest(path)
            path.write_text('{"sample":"a","queries":[{"caller":"gatk"}]}')
            self.assertEqual(read_manifest(path)['sample'], 'a')

    def test_nf_negative_fixture_is_otherwise_a_valid_closed_manifest(self) -> None:
        """The nf-test must exercise duplicate rejection, not an unrelated missing field."""
        path = ROOT / 'tests/data/m5-duplicate-manifest.invalid-json.txt'
        data = json.loads(path.read_text())
        self.assertEqual(set(data), HELPER.FIELDS)
        self.assertEqual({row['caller'] for row in data['queries']}, {'gatk', 'deepvariant'})
        with self.assertRaisesRegex(ValueError, 'duplicate manifest key: sample'):
            read_manifest(path)

    def test_nextflow_consumes_validated_stdout_without_rereading_manifest(self) -> None:
        """The strict reader's bytes, rather than a second permissive read, enter DSL parsing."""
        source = (ROOT / 'm5.nf').read_text()
        self.assertIn('giab_wes_nextflow.m5_manifest', source)
        self.assertIn('parseText(manifest_text)', source)
        self.assertNotIn('parseText(manifest_file.text)', source)


class ModeQualificationTests(unittest.TestCase):
    """Do not accept cache claims from missing tasks, failures or changed identities."""

    def test_independent_runs_and_both_resume_exact_cache_oracle(self) -> None:
        """Both independent modes execute, then both-mode and repeat reuse all four tasks."""
        result = HELPER.validate_modes(traces())
        self.assertEqual(result['gatk']['statuses'], {'COMPLETED': 2, 'CACHED': 0})
        self.assertEqual(result['deepvariant']['statuses'], {'COMPLETED': 2, 'CACHED': 0})
        self.assertEqual(result['both']['statuses'], {'COMPLETED': 0, 'CACHED': 4})
        self.assertEqual(result['resume']['statuses'], {'COMPLETED': 0, 'CACHED': 4})

    def test_status_hash_inventory_caller_and_phase_tampering_fail(self) -> None:
        """Explicit expected identities prevent plausible-looking partial execution proofs."""
        mutations = [('gatk', 'COMPLETED', 'CACHED'), ('both', 'CACHED', 'COMPLETED'), ('resume', 'aa/000001', 'bb/000001'), ('both', 'gatk:full', 'other:full'), ('resume', 'M5_NORMALIZE', 'M4_HAPLOTYPECALLER')]
        for phase, before, after in mutations:
            data = traces(); data[phase] = data[phase].replace(before, after, 1)
            with self.subTest(phase=phase, before=before), self.assertRaises(ValueError):
                HELPER.validate_modes(data)
        data = traces(); del data['both']
        with self.assertRaises(ValueError):
            HELPER.validate_modes(data)
        data = traces(); data['resume'] = '\n'.join(data['resume'].splitlines()[:-1]) + '\n'
        with self.assertRaises(ValueError):
            HELPER.validate_modes(data)

    def test_portable_identity_ignores_filename_but_preserves_bytes(self) -> None:
        """Filename relocation does not erase byte identity from comparisons."""
        first = {'reference': {'filename': 'reference.fa', 'bytes': 12, 'sha256': 'a' * 64}}
        second = copy.deepcopy(first); second['reference']['filename'] = '/relocated/reference.fa'
        self.assertEqual(HELPER._identities(first), HELPER._identities(second))
        second['reference']['bytes'] = 13
        self.assertNotEqual(HELPER._identities(first), HELPER._identities(second))


if __name__ == '__main__':
    unittest.main()
