"""Collect invented metadata-only fixtures; no test data represent real execution."""
from __future__ import annotations

import copy
import json
import shutil
import zipfile
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import patch

from giab_wes_nextflow.canonical_results import DOMAINS, load_canonical_bundle
from giab_wes_nextflow.canonical_run import collect, restore_completed_run
from giab_wes_nextflow.canonical_checkpoint import inventory
from giab_wes_nextflow.canonical_asset_reference import digest_json
from giab_wes_nextflow.canonical_science import file_id, write_json
from giab_wes_nextflow.m5 import metrics


class CanonicalCollectionTests(unittest.TestCase):
    """Exercise producer-to-consumer binding with deliberately non-genomic bytes."""

    def setUp(self) -> None:
        """Create tiny fake artifacts and clearly marked artificial gate assertions."""
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.stage = Path(self.temp.name).resolve() / 'stage'; self.stage.mkdir()
        self.published = self.stage / 'published'
        self.run_id = 'collection-test-only-not-execution'
        self.identity = {'repository_sha': 'b' * 40}
        self.gates = {role: {'test_only': True, 'execution_observed': False} for role in ('sources', 'reference', 'index', 'domain', 'runtime')}
        self.resume = {'test_only': True, 'cached_tasks': 5}
        self.domain = DOMAINS['hg001_chr20_22_coding']
        shared = self.published / 'canonical/shared/result'
        names = ('shared.bam', 'shared.bam.bai', 'reference.fa', 'reference.fa.fai', 'reference.dict', 'regions.bed')
        self.shared = {name: self.artifact(shared / 'shared' / name) for name in names}
        write_json(shared / 'receipt.json', {'kind': 'preprocessing', 'status': 'passed', 'test_only': True,
                  'outputs': self.shared, 'inputs': {'test_only': True}, 'commands': [], 'bam_validation': {'test_only': True}})
        for caller in ('gatk', 'deepvariant'):
            native = self.published / f'canonical/{caller}/native/result'
            outputs = {name: self.artifact(native / name) for name in ('raw.vcf.gz', 'raw.vcf.gz.tbi')}
            write_json(native / 'receipt.json', {'kind': caller, 'status': 'passed', 'test_only': True,
                      'inputs': copy.deepcopy(self.shared), 'outputs': outputs, 'commands': []})
            benchmark = self.published / f'canonical/{caller}/benchmark/result'
            norms = {}
            for role, subdir in [('query', 'query'), ('truth', 'truth-normalized')]:
                declared = {name: self.artifact(benchmark / subdir / name) for name in ('normalized.vcf.gz', 'normalized.vcf.gz.tbi')}
                norms[role] = {'kind': 'normalization', 'status': 'passed', 'test_only': True,
                               'outputs': declared, 'input': outputs['raw.vcf.gz'] if role == 'query' else {'sha256': 'c' * 64, 'bytes': 1}, 'commands': []}
                write_json(benchmark / subdir / 'receipt.json', norms[role])
            partitions = {name: self.artifact(benchmark / 'evaluation/vcfeval' / name) for name in ('tp.vcf.gz', 'fp.vcf.gz', 'fn.vcf.gz', 'tp-baseline.vcf.gz')}
            write_json(benchmark / 'receipt.json', {'kind': 'benchmark', 'status': 'passed', 'test_only': True, **norms,
                      'caller': caller, 'domain_id': self.domain['id'], 'metrics': {kind: metrics(2, 3, 1, 1) for kind in ('SNP', 'INDEL', 'OTHER')}, 'commands': [], 'partitions': partitions,
                      'domain_sha256': self.domain['sha256'], 'evaluated_bases': self.domain['bases'], 'interval_count': self.domain['interval_count']})
        coverage_dir = self.stage / 'coverage'
        artifact = self.artifact(coverage_dir / 'depth.tsv')
        coverage = {'kind': 'coverage', 'status': 'passed', 'test_only': True,
                    'evaluated_bases': self.domain['bases'], 'covered_bases': 100,
                    'definition': 'Invented test metadata; no biological coverage observation.', 'artifact': artifact,
                    'domain_id': 'R_eval_holdout', 'domain_sha256': self.domain['sha256'], 'shared_bam_sha256': self.shared['shared.bam']['sha256'], 'commands': []}
        write_json(coverage_dir / 'receipt.json', coverage)
        write_json(coverage_dir / 'public-coverage.json', {key: value for key, value in coverage.items() if key != 'commands'})

    def artifact(self, path: Path) -> dict:
        """Write obvious fake payloads only under the test temporary directory."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(('INVENTED TEST BYTES: ' + path.name + '\n').encode())
        return file_id(path)

    def execute(self):
        """Run the real collector against artificial receipts without launching tools."""
        return collect(self.stage, self.published, self.run_id, self.identity, self.gates, self.resume, 100.0)

    def receipt(self, caller: str, role: str) -> Path:
        """Locate an unambiguous fake native or benchmark producer receipt."""
        return self.published / f'canonical/{caller}/{role}/result/receipt.json'

    def test_collector_emits_model_valid_bundle_and_coverage(self) -> None:
        """The real writer's output can be consumed under its exact returned pin."""
        directory, pin = self.execute()
        model = load_canonical_bundle(directory, pin)
        self.assertEqual(model.record['run_id'], self.run_id)
        self.assertEqual(model.record['callers']['gatk']['metrics']['SNP'], metrics(2, 3, 1, 1))
        self.assertEqual(model.record['coverage']['covered_bases'], 100)
        self.assertIsNone(model.record['coverage_missing_reason'])
        self.assertTrue((directory / 'coverage.json').is_file())
        self.assertTrue(json.loads((directory / 'sources.json').read_text())['test_only'])

    def test_completed_collection_reused_after_resume_without_rewriting(self) -> None:
        """A retry retains the first observation while rechecking scientific proof."""
        directory, pin = self.execute()
        before = {path.name: path.read_bytes() for path in directory.iterdir()}
        resumed = {**self.resume, 'cached_tasks': 6}
        self.assertEqual(collect(self.stage, self.published, self.run_id, self.identity, self.gates, resumed, None), (directory, pin))
        self.assertEqual(before, {path.name: path.read_bytes() for path in directory.iterdir()})

    def test_completed_collection_rejects_changed_evidence_and_code(self) -> None:
        """An existing completion cannot authorize a different code or gate proof."""
        self.execute()
        for identity, gates in [({'repository_sha': 'a' * 40}, self.gates),
                                (self.identity, {**self.gates, 'runtime': {'test_only': True, 'changed': True}})]:
            with self.subTest(identity=identity, gates=gates), self.assertRaisesRegex(ValueError, 'proof differs'):
                collect(self.stage, self.published, self.run_id, identity, gates, self.resume, None)
        output = self.stage / 'public-evidence/result.json'
        output.write_bytes(output.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'hash or size mismatch'):
            self.execute()

    def test_interrupted_collection_leaves_only_preserved_candidate(self) -> None:
        """A partial writer never publishes its directory as completed evidence."""
        def interrupted(directory, result, receipts):
            directory.mkdir(); (directory / 'result.json').write_text('interrupted test-only bytes')
            raise OSError('invented interruption')
        with patch('giab_wes_nextflow.canonical_results.write_public_bundle', side_effect=interrupted):
            with self.assertRaisesRegex(OSError, 'invented interruption'):
                self.execute()
        self.assertFalse((self.stage / 'public-evidence').exists())
        candidates = list(self.stage.glob('public-evidence.build-*'))
        self.assertEqual(len(candidates), 1)
        self.execute()
        self.assertTrue((candidates[0] / 'result.json').exists())

    def test_legacy_incomplete_collection_is_preserved_on_retry(self) -> None:
        """Interrupted older output without a completion manifest is recoverable."""
        output = self.stage / 'public-evidence'; output.mkdir()
        (output / 'partial.json').write_text('invented partial metadata')
        directory, pin = self.execute()
        load_canonical_bundle(directory, pin)
        preserved = list(self.stage.glob('public-evidence.incomplete-*'))
        self.assertEqual((preserved[0] / 'partial.json').read_text(), 'invented partial metadata')

    def test_complete_collection_requires_separate_trusted_pin(self) -> None:
        """Never treat a manifest's self-derived hash as independent evidence."""
        directory, _ = self.execute()
        original = (directory / 'manifest.json').read_bytes()
        (self.stage / 'public-evidence-proof.json').unlink()
        with self.assertRaisesRegex(ValueError, 'no independent collection proof'):
            self.execute()
        self.assertEqual((directory / 'manifest.json').read_bytes(), original)

    def test_changed_published_bytes_rejected(self) -> None:
        """Declared output hashes cannot survive mutation of the actual artifact."""
        path = self.receipt('gatk', 'native').parent / 'raw.vcf.gz'
        path.write_bytes(b'TAMPERED TEST BYTES')
        with self.assertRaisesRegex(ValueError, 'differs from receipt'):
            self.execute()
        self.assertFalse((self.stage / 'public-evidence/manifest.json').exists())

    def test_completed_durable_bundle_restores_without_runtime_or_tools(self) -> None:
        """A reset recovers verified public bytes only after private provenance exists."""
        public, pin = self.execute()
        drive = self.stage / 'fake-drive'
        root = drive / f'runs/{self.run_id}/completed-stages'
        durable = root / 'public-evidence'; shutil.copytree(public, durable)
        write_json(durable / 'stage-complete.json', {'kind': 'canonical_completed_stage', 'key': pin, 'files': inventory(durable)})
        fresh = self.stage / 'fresh'; fresh.mkdir()
        with self.assertRaises(FileNotFoundError):
            restore_completed_run(fresh, drive, self.run_id, self.identity['repository_sha'])
        private = root / 'private-provenance'; private.mkdir()
        (private / 'receipt.json').write_text('{"test_only":true}')
        shutil.copytree(public, private / 'public-evidence')
        shutil.copyfile(self.stage / 'public-evidence-proof.json', private / 'public-evidence-proof.json')
        files = inventory(private)
        write_json(private / 'stage-complete.json', {'kind': 'canonical_completed_stage', 'key': digest_json(files), 'files': files})
        bundle = restore_completed_run(fresh, drive, self.run_id, self.identity['repository_sha'])
        record = json.loads((fresh / 'canonical-complete.json').read_text())
        self.assertEqual(record['manifest_sha256'], pin)
        self.assertEqual(record['bundle'], file_id(bundle))
        with zipfile.ZipFile(bundle) as archive:
            self.assertEqual(sorted(archive.namelist()), sorted(p.name for p in public.iterdir()))
        with self.assertRaisesRegex(ValueError, 'code/run identity'):
            restore_completed_run(fresh, drive, self.run_id, 'd' * 40)
        (durable / 'stage-complete.json').unlink()
        resumed = self.stage / 'private-only-recovery'; resumed.mkdir()
        with patch('giab_wes_nextflow.canonical_checkpoint.publish') as publish:
            restored = restore_completed_run(resumed, drive, self.run_id, self.identity['repository_sha'])
            self.assertTrue(restored.is_file())
            publish.assert_called_once_with(resumed / 'public-evidence', drive, self.run_id, 'public-evidence', pin)
        (private / 'receipt.json').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'checkpoint inventory'):
            restore_completed_run(fresh, drive, self.run_id, self.identity['repository_sha'])

    def test_caller_input_asymmetry_rejected(self) -> None:
        """Per-caller physical identities must match the shared preprocessing output."""
        path = self.receipt('deepvariant', 'native'); value = json.loads(path.read_text())
        value['inputs']['shared.bam']['sha256'] = 'd' * 64; write_json(path, value)
        with self.assertRaisesRegex(ValueError, 'asymmetry'):
            self.execute()

    def test_raw_to_normalized_lineage_rejected(self) -> None:
        """Matching normalized outputs cannot conceal a different raw-call parent."""
        path = self.receipt('gatk', 'benchmark'); value = json.loads(path.read_text())
        value['query']['input']['sha256'] = 'e' * 64; write_json(path, value)
        with self.assertRaisesRegex(ValueError, 'lineage'):
            self.execute()

    def test_public_coverage_must_equal_private_validated_receipt(self) -> None:
        """A public copy cannot contradict coverage already bound to private depth bytes."""
        path = self.stage / 'coverage/public-coverage.json'
        value = json.loads(path.read_text()); value['covered_bases'] += 1; write_json(path, value)
        with self.assertRaisesRegex(ValueError, 'public coverage differs'):
            self.execute()

    def test_duplicate_benchmark_receipts_are_ambiguous(self) -> None:
        """Collection must not silently choose a result from competing output branches."""
        source = self.receipt('gatk', 'benchmark')
        write_json(source.parent.parent / 'competing/receipt.json', json.loads(source.read_text()))
        with self.assertRaisesRegex(ValueError, 'unambiguous benchmark'):
            self.execute()

    def test_benchmark_domain_caller_and_shared_truth_identity_are_enforced(self) -> None:
        """Schema-looking metadata cannot substitute a different denominator or truth."""
        path = self.receipt('gatk', 'benchmark'); original = json.loads(path.read_text())
        for key, changed in [('caller', 'deepvariant'), ('domain_id', 'R_eval_full'), ('domain_sha256', 'f' * 64), ('evaluated_bases', 1), ('interval_count', 1)]:
            value = copy.deepcopy(original); value[key] = changed; write_json(path, value)
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'caller/domain contract'):
                self.execute()
        write_json(path, original)
        path = self.receipt('deepvariant', 'benchmark'); value = json.loads(path.read_text())
        truth = path.parent / 'truth-normalized/normalized.vcf.gz'
        truth.write_bytes(b'DIFFERENT INVENTED TRUTH BYTES')
        value['truth']['outputs']['normalized.vcf.gz'] = file_id(truth); write_json(path, value)
        with self.assertRaisesRegex(ValueError, 'normalized truth differs'):
            self.execute()


if __name__ == '__main__':
    unittest.main()
