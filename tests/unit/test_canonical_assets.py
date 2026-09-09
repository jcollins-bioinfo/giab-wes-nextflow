"""Invented-data regressions for full base identity and marker-last asset recovery."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
from typing import Any
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from giab_wes_nextflow import canonical_assets as assets
from giab_wes_nextflow import canonical_asset_reference as reference
from giab_wes_nextflow.acquisition import checksum, safe_root

ACTIVE_POLICY = reference.active


class CanonicalAssetTest(unittest.TestCase):
    """Exercise asset failure boundaries without human data, downloads or fake qualification."""

    def setUp(self) -> None:
        """Create a tiny invented reference and replace source pins only within tests."""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.stage = self.root / 'stage'
        self.drive = self.root / 'giab-wes-nextflow-private'
        self.drive.mkdir()
        self.fa = b'>chrToyA\nACGTAC\nGTAC\n>chrToyB\nTTTTGG\n'
        self.source = self.root / 'source.gz'
        self.source.write_bytes(gzip.compress(self.fa))
        self.fai = self.root / 'source.fai'
        self.fai.write_text('chrToyA\t10\t999\t6\t7\nchrToyB\t6\t777\t6\t7\n')
        self.spec: dict[str, Any] = {'reference_dictionary': [
            {'name': 'chrToyA', 'length': 10, 'md5': hashlib.md5(b'ACGTACGTAC').hexdigest()},
            {'name': 'chrToyB', 'length': 6, 'md5': hashlib.md5(b'TTTTGG').hexdigest()}], 'known_sites': [], 'aligner': {'name': 'bwa'}}
        resources = [{'id': name, 'bytes': path.stat().st_size, 'checksum': {'expected': checksum(path, 'md5')}}
                     for name, path in [('grch38_no_alt_fasta_gz', self.source), ('grch38_compressed_fai', self.fai)]]
        self.manifest = self.root / 'm2.json'
        self.manifest.write_text(json.dumps({'resources': resources}))
        for context in (patch.object(reference, 'config_path', return_value=self.manifest),
                        patch.object(reference, 'load_assets', return_value=self.spec),
                        patch.object(assets, 'load_assets', return_value=self.spec),
                        patch.object(reference, 'active', side_effect=lambda p: safe_root(p, allow_test_root=True)),
                        patch.object(assets, 'active', side_effect=lambda p: safe_root(p, allow_test_root=True)),
                        patch.object(assets, 'DRIVE_ROOT', str(self.drive)),
                        patch.object(reference.shutil, 'disk_usage', return_value=SimpleNamespace(free=100 * 1024 ** 3))):
            context.start()
            self.addCleanup(context.stop)

    def prepare(self) -> dict[str, Any]:
        """Authenticate the invented source and construct its complete reference metadata."""
        return reference.prepare_reference(self.source, self.fai, self.stage)

    def test_full_md5_and_physical_fai_not_upstream_offsets(self) -> None:
        """Actual reference offsets are reconstructed while source order/lengths stay binding."""
        record = self.prepare()
        self.assertEqual(record, reference.validate_reference(self.stage))
        self.assertEqual((self.stage / 'reference.fa').read_bytes(), self.fa)
        self.assertNotIn('999', (self.stage / 'reference.fa.fai').read_text())
        rows = reference.scan_reference(self.stage / 'reference.fa')
        with (self.stage / 'reference.fa').open('rb') as stream:
            self.assertEqual(reference.reference_slice(stream, rows[0], 4, 5), 'ACGTA')
        self.assertEqual(self.prepare(), record)

    def test_mutation_cannot_pass_rehashed_manifest(self) -> None:
        """Same lengths and a self-rehashed file manifest cannot replace pinned full bases."""
        self.prepare()
        path = self.stage / 'reference.fa'
        path.write_bytes(path.read_bytes().replace(b'ACGTAC', b'ACGTAT', 1))
        manifest = self.stage / 'reference-manifest.json'
        record = json.loads(manifest.read_text())
        record['files'][0] = reference.identity(path)
        manifest.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, 'base identity'):
            reference.validate_reference(self.stage)

    def test_corrupt_authenticated_source_fails(self) -> None:
        """Corrupt authenticated sources are rejected before successful derivatives exist."""
        self.source.write_bytes(b'not gzip')
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse((self.stage / 'reference-manifest.json').exists())

    def test_authenticated_source_fai_order_remains_binding(self) -> None:
        """Even authenticated FAI metadata must agree with every contig in source order."""
        lines = self.fai.read_text().splitlines(keepends=True)
        self.fai.write_text(''.join(reversed(lines)))
        source_manifest = json.loads(self.manifest.read_text())
        source_manifest['resources'][1]['checksum']['expected'] = checksum(self.fai, 'md5')
        self.manifest.write_text(json.dumps(source_manifest))
        with self.assertRaisesRegex(ValueError, 'FAI order/length'):
            self.prepare()
        self.assertFalse((self.stage / 'reference-manifest.json').exists())

    def test_reference_derivative_promotion_resumes_after_interruption(self) -> None:
        """A stopped FAI write cannot leave a partial final derivative that blocks retry."""
        original = reference.os.replace
        def interrupted(source: Path, target: Path) -> None:
            """Interrupt one atomic promotion after its complete temporary bytes exist."""
            if Path(target).name == 'reference.fa.fai':
                raise OSError('invented FAI interruption')
            original(source, target)
        with patch.object(reference.os, 'replace', side_effect=interrupted), self.assertRaises(OSError):
            self.prepare()
        self.assertFalse((self.stage / 'reference.fa.fai').exists())
        self.assertTrue((self.stage / 'reference.fa.fai.incomplete').exists())
        self.assertEqual(self.prepare(), reference.validate_reference(self.stage))

    def test_nonuniform_wrapping_and_duplicate_contigs_fail(self) -> None:
        """Malformed sequence structure cannot create a misleading random-access index."""
        for data in (b'>a\nAC\nA\nAA\n', b'>a\nA\n>a\nA\n', b'>a\nA X\n'):
            source = self.root / 'malformed.fa'
            source.write_bytes(data)
            with self.assertRaises(ValueError):
                reference.scan_reference(source)

    def test_publish_hydrate_rehash_and_registry_before_marker(self) -> None:
        """A complete durable asset is content-addressed and rehashed again on hydration."""
        record = self.prepare()
        target = assets.publish_assets(self.stage, self.drive, 'invented-run', 'a' * 40, kind=record['kind'])
        marker = json.loads((target / 'COMPLETED.json').read_text())
        self.assertEqual(target.name, reference.digest_json(record))
        self.assertTrue((self.drive / 'registry/assets/invented-run' / (target.name + '.json')).is_file())
        hydrated = assets.hydrate_assets(self.drive, record['reference_id'], target.name, self.root / 'hydrated', kind=record['kind'])
        self.assertEqual(record, hydrated)
        self.assertEqual(assets.publish_assets(self.stage, self.drive, 'other-run', 'b' * 40, kind=record['kind']), target)
        self.assertEqual(marker, json.loads((target / 'COMPLETED.json').read_text()))
        (target / 'reference.fa').write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            assets.hydrate_assets(self.drive, record['reference_id'], target.name, self.root / 'again', kind=record['kind'])

    def test_registry_failure_leaves_no_completion_marker(self) -> None:
        """An interrupted durable transaction cannot advertise a complete reusable asset."""
        record = self.prepare()
        original = assets.write_record
        def fail_registry(path: Path, value: dict[str, Any]) -> None:
            """Inject a registry failure after copies to test commit-marker ordering."""
            if 'registry' in path.parts:
                raise OSError('invented registry interruption')
            original(path, value)
        with patch.object(assets, 'write_record', side_effect=fail_registry), self.assertRaises(OSError):
            assets.publish_assets(self.stage, self.drive, 'fail', 'a' * 40, kind=record['kind'])
        self.assertFalse(list(self.drive.rglob('COMPLETED.json')))
        target = assets.publish_assets(self.stage, self.drive, 'fail', 'a' * 40, kind=record['kind'])
        self.assertTrue((target / 'COMPLETED.json').is_file())

    def test_safe_archive_rejects_links_traversal_and_inventory_drift(self) -> None:
        """Only exact declared regular members may be extracted from authenticated archives."""
        archive = self.root / 'small.tar'
        for index, name in enumerate(('../escape', '/absolute', 'unexpected', 'payload', 'extra-directory')):
            with tarfile.open(archive, 'w') as out:
                member = tarfile.TarInfo(name)
                if name == 'extra-directory':
                    member.type = tarfile.DIRTYPE
                    out.addfile(member)
                elif name == 'payload':
                    member.type = tarfile.SYMTYPE
                    member.linkname = '/invented'
                    out.addfile(member)
                else:
                    member.size = 1
                    out.addfile(member, io.BytesIO(b'x'))
            with self.assertRaises(ValueError):
                assets.extract_archive(archive, self.root / f'extract{index}', {'payload': {'bytes': 1, 'sha256': hashlib.sha256(b'x').hexdigest()}}, maximum_bytes=1)

    def test_independent_known_sites_restriction_and_resume_are_audited(self) -> None:
        """Absent no-alt contigs are counted; retained REF alleles and derivative indexes bind."""
        self.prepare()
        body = ('##fileformat=VCFv4.2\n##contig=<ID=chrToyA,length=10>\n'
                '##contig=<ID=chrToyB,length=6>\n##contig=<ID=chrALT,length=5>\n'
                '#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n'
                'chrToyA\t2\t.\tC\tT\t.\tPASS\t.\n'
                'chrALT\t1\t.\tA\tG\t.\tPASS\t.\n')
        sources = {}
        for name in ('dbsnp', 'known', 'mills'):
            for indexed in (False, True):
                resource_id = name + ('_tbi' if indexed else '')
                path = self.root / (resource_id + '.gz')
                path.write_bytes(b'invented-index' if indexed else gzip.compress(body.encode()))
                sources[resource_id] = path
                self.spec['known_sites'].append({'id': resource_id, 'role': 'bqsr_known_sites_index' if indexed else 'bqsr_known_sites',
                    'filename': path.name, 'bytes': path.stat().st_size, 'checksum': {'expected': checksum(path, 'md5')}})
        calls = []
        def runner(tool: str, args: list[str], directory: Path) -> str:
            """Provide only compression/index plumbing for invented transformation unit coverage."""
            calls.append((tool, args))
            if args[0] == 'view':
                (directory / args[3]).write_bytes(gzip.compress((directory / args[4]).read_bytes()))
            elif '--tbi' in args:
                (directory / (args[-1] + '.tbi')).write_bytes(b'invented-index')
            return '1\n' if '--nrecords' in args else ''
        output = self.root / 'known-sites'
        record = reference.prepare_known_sites(sources, self.stage, output, runner)
        self.assertFalse(record['benchmark_truth_used'])
        self.assertTrue(all(a['retained_records'] == 1 and a['excluded_absent_reference_records'] == 1 for a in record['audits']))
        self.assertEqual(len(calls), 9)
        self.assertEqual(reference.prepare_known_sites(sources, self.stage, output, runner), record)
        self.assertEqual(len(calls), 9)
        first = sources['dbsnp']
        first.write_bytes(gzip.compress(body.replace('chrToyA\t2\t.\tC', 'chrToyA\t2\t.\tA').encode()))
        self.spec['known_sites'][0]['bytes'] = first.stat().st_size
        self.spec['known_sites'][0]['checksum']['expected'] = checksum(first, 'md5')
        with self.assertRaisesRegex(ValueError, 'REF/order mismatch'):
            reference.prepare_known_sites(sources, self.stage, self.root / 'bad-known-sites', runner)

    def test_low_memory_stops_index_before_executable_invocation(self) -> None:
        """Configured algorithm choice never authorizes a build above measured capacity."""
        self.prepare()
        with patch.object(assets, 'memory_limits', return_value={'effective_ceiling_bytes': 8 * 1024 ** 3}):
            invoked = []
            def runner(tool: str, args: list[str], cwd: Path) -> str:
                """Record an unexpected execution attempt without launching any tool."""
                invoked.append(args)
                return ''
            with self.assertRaisesRegex(ValueError, '16GiB'):
                assets.build_index(self.stage, self.root / 'index', runner)
            self.assertEqual(invoked, [])

    def test_off_colab_and_prohibited_paths_fail_without_creation(self) -> None:
        """Canonical active policy never permits Mac or Drive compute paths."""
        for path in (self.root / 'not-colab', Path('/content/drive/private-assets')):
            with self.assertRaises(ValueError):
                ACTIVE_POLICY(path)
        with self.assertRaises(PermissionError):
            reference.regular(self.root / 'DO NOT ACCESS WITH CHATGPT' / 'file')
        with self.assertRaises(ValueError):
            assets.publish_assets(self.root, self.drive, '../unsafe', 'a' * 40, kind='unknown')

    def test_atomic_copy_recovers_interrupted_partial(self) -> None:
        """A failed copy leaves no final file; the same verified bytes finish on retry."""
        source = self.root / 'copy-source'
        source.write_bytes(b'invented-copy-content')
        target = self.root / 'copy-target'
        def interrupted(stream: Any, out: Any, length: int) -> None:
            """Write a short prefix, then simulate runtime loss before promotion."""
            out.write(stream.read(3))
            raise OSError('invented interruption')
        with patch.object(assets.shutil, 'copyfileobj', side_effect=interrupted), self.assertRaises(OSError):
            assets.copy_verified(source, target, reference.identity(source))
        self.assertFalse(target.exists())
        self.assertEqual(target.with_name(target.name + '.incomplete').read_bytes(), b'inv')
        assets.copy_verified(source, target, reference.identity(source))
        self.assertEqual(target.read_bytes(), source.read_bytes())

    def test_reference_registry_contract_changes_with_pinned_bases(self) -> None:
        """Discovery cannot select an asset whose source/method contract has changed."""
        before = assets.asset_contract_sha256('canonical_reference_asset')
        self.spec['reference_dictionary'][0]['md5'] = '0' * 32
        self.assertNotEqual(before, assets.asset_contract_sha256('canonical_reference_asset'))



if __name__ == '__main__':
    unittest.main()
