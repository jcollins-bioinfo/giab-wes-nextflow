"""Synthetic runtime safety and attribution checks without launching scientific tools."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from giab_wes_nextflow import canonical_runtime as runtime
from giab_wes_nextflow import canonical_runtime_install as install

ROOT = Path(__file__).resolve().parents[2]


class RuntimeContractsTests(unittest.TestCase):
    """Resource ceilings, image identities and task mounts are executable contracts."""

    def test_macos_and_non_amd64_execution_rejected(self) -> None:
        """Linux execution cannot be inferred from a configured container backend."""
        for system, architecture in [('Darwin', 'arm64'), ('Linux', 'arm64')]:
            with patch.object(runtime.platform, 'system', return_value=system), patch.object(runtime.platform, 'machine', return_value=architecture):
                with self.assertRaisesRegex(ValueError, 'actual Linux amd64'):
                    runtime.Runtime(Path('/content/task'))

    def test_memory_headroom_and_cpu_ceilings(self) -> None:
        """The known 50.99 GiB allocation accommodates 44 GiB but not arbitrary requests."""
        with patch.object(runtime, 'memory_limits', return_value={'effective_ceiling_bytes': 54_750_404_608}), patch.object(runtime.os, 'sched_getaffinity', return_value=set(range(8)), create=True):
            runtime.Limits().validate()
            for cpus, memory in [(9, 44 * runtime.GIB), (8, 51 * runtime.GIB), (True, runtime.GIB)]:
                with self.assertRaises(ValueError):
                    runtime.Limits(cpus, memory).validate()
        with patch.object(runtime, 'memory_limits', return_value={'effective_ceiling_bytes': 8 * runtime.GIB}), patch.object(runtime.os, 'sched_getaffinity', return_value=set(range(8)), create=True):
            with self.assertRaises(ValueError):
                runtime.Limits().validate()

    def test_scratch_never_points_to_drive_or_protected_folder(self) -> None:
        """Active execution paths cannot include durable Drive or a protected folder."""
        for path in ['/tmp/task', '/content/drive/cache', '/content/DO NOT ACCESS WITH CHATGPT/task']:
            with self.assertRaises(ValueError):
                runtime._scratch(Path(path))

    def instance(self, root: Path, backend: str) -> runtime.Runtime:
        """Construct an inert command builder; never discover or execute a runtime."""
        obj = runtime.Runtime.__new__(runtime.Runtime)
        obj.root = root / 'runtime'
        obj.backend = backend
        obj.limits = runtime.Limits()
        obj.executable = [backend]
        obj.prepare = lambda tool: {'source_image': 'registry/tool@sha256:' + 'a' * 64, 'sif': '/content/runtime/image.sif', 'executable': '/content/native/tool'}
        return obj

    def test_only_task_directory_is_bound_and_entrypoint_not_duplicated(self) -> None:
        """Docker/udocker RTG entrypoints are replaced while preserving image environment."""
        with tempfile.TemporaryDirectory() as directory, patch.object(runtime, '_scratch', side_effect=lambda value: Path(value)):
            root = Path(directory); task = root / 'task'; task.mkdir()
            for backend in ['apptainer', 'singularity', 'podman', 'docker', 'udocker']:
                command = self.instance(root, backend).command('rtg', ['vcfeval', '--help'], task_dir=task)
                with self.subTest(backend=backend):
                    self.assertIn(str(task), ' '.join(command))
                    self.assertNotIn(str(root / 'runtime') + ':/', ' '.join(command))
                    self.assertNotIn('--hostenv', command)
                    self.assertNotIn('--bindhome', command)
                    self.assertEqual(command.count('rtg') + command.count('--entrypoint=rtg'), 1)
                    if backend == 'udocker':
                        self.assertNotIn('--nometa', command)

    def test_symlink_staging_and_over_ceiling_request_fail(self) -> None:
        """Filesystem aliases cannot widen task input access beyond explicit staged bytes."""
        with tempfile.TemporaryDirectory() as directory, patch.object(runtime, '_scratch', side_effect=lambda value: Path(value)):
            root = Path(directory); task = root / 'task'; task.mkdir()
            obj = self.instance(root, 'udocker')
            with self.assertRaises(ValueError):
                obj.command('gatk', [], task_dir=task, cpus=9)
            (task / 'truth-link').symlink_to(root / 'elsewhere')
            with self.assertRaisesRegex(ValueError, 'symlinks'):
                obj.command('gatk', [], task_dir=task)

    def test_existing_image_pins_and_packaged_runtime_lock_match(self) -> None:
        """New runtime routing preserves accepted historical tool identities."""
        tools = runtime.tool_lock()
        self.assertIn('bwa', tools)
        for name in ('m3-tools.json', 'm4-tools.json', 'm5-tools.json'):
            for tool, entry in json.loads((ROOT / 'config' / name).read_text())['tools'].items():
                self.assertEqual(tools[tool]['image'], entry['image'])
        self.assertEqual((ROOT / 'config/canonical-runtime.json').read_bytes(), (ROOT / 'src/giab_wes_nextflow/data/config/canonical-runtime.json').read_bytes())

    def test_version_probe_and_forged_receipt_cannot_qualify(self) -> None:
        """Qualification requires two unchanged caller execution receipts and validation."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); obj = self.instance(root, 'udocker')
            obj.tools = runtime.tool_lock(); obj.state = {'status': 'configured_only'}
            receipt = {'tool': 'gatk', 'returncode': 0, 'image': obj.tools['gatk']['image'], 'backend': 'udocker', 'stage': 'runtime-qualification', 'argv': ['gatk', '--version'], 'audit_record_path': str(root / 'audit.json')}
            (root / 'audit.json').write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError, 'version/help'):
                obj.qualify({'gatk': receipt, 'deepvariant': receipt}, lambda: {'accepted': True})
            receipt['stage'] = 'forged'
            with self.assertRaisesRegex(ValueError, 'unchanged'):
                obj.qualify({'gatk': receipt, 'deepvariant': receipt}, lambda: {'accepted': True})
            self.assertEqual(obj.state['status'], 'configured_only')


class RuntimeInstallerTests(unittest.TestCase):
    """Small artificial bytes exercise resumability and content-addressed installation."""

    def test_sha256_git_blob_size_and_corruption_checks(self) -> None:
        """Publisher SHA-256 and immutable Git blob hashes are distinct identities."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'asset'; raw = b'synthetic tool bytes'; path.write_bytes(raw)
            spec = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'git_blob_sha1': hashlib.sha1(f'blob {len(raw)}\0'.encode() + raw).hexdigest()}
            self.assertEqual(install.verify_asset(path, spec)['sha256'], spec['sha256'])
            path.write_bytes(raw[:-1] + b'!')
            with self.assertRaises(ValueError):
                install.verify_asset(path, spec)

    def test_completed_partial_recovers_without_network(self) -> None:
        """Interruption after download but before promotion does not redownload assets."""
        with tempfile.TemporaryDirectory() as directory, patch.object(install.urllib.request, 'urlopen') as network:
            path = Path(directory) / 'asset'; raw = b'complete'; path.with_suffix('.part').write_bytes(raw)
            spec = {'url': 'https://example.invalid/tool', 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
            install.download_asset(spec, path)
            self.assertEqual(path.read_bytes(), raw); network.assert_not_called()

    def test_tar_traversal_and_escaping_links_rejected_before_extraction(self) -> None:
        """Archive contents cannot escape installation scratch or create device nodes."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, target in [('../escape', None), ('/absolute', None), ('link', '../../escape')]:
                archive = root / 'bad.tar.gz'
                with tarfile.open(archive, 'w:gz') as output:
                    item = tarfile.TarInfo(name)
                    if target:
                        item.type = tarfile.SYMTYPE; item.linkname = target; output.addfile(item)
                    else:
                        item.size = 1; output.addfile(item, io.BytesIO(b'x'))
                with self.assertRaises(ValueError):
                    install.extract_safe(archive, root / 'unpacked')

class RuntimeSmokeTests(unittest.TestCase):
    """Check observed-version parsing and bounded fallback without tool execution."""

    def test_version_probes_accept_exact_reports_and_reject_drift(self) -> None:
        """Different component versions cannot be smuggled through a configured image."""
        from giab_wes_nextflow.canonical_smoke import check_versions
        reports = {'samtools': 'samtools 1.24\n', 'gatk': 'The Genome Analysis Toolkit (GATK) v4.7.0.0\n',
                   'deepvariant': 'DeepVariant version 1.10.0\n', 'bcftools': 'bcftools 1.24\n', 'rtg': 'RTG Tools 3.13\n'}
        with tempfile.TemporaryDirectory() as directory:
            task = Path(directory)
            class FakeRuntime:
                """Return fabricated version strings solely for parser tests."""
                def run(self, tool, args, **kwargs):
                    out, err = task / (tool + '.stdout'), task / (tool + '.stderr')
                    out.write_text(reports[tool]); err.write_text('')
                    return {'stdout_path': str(out), 'stderr_path': str(err)}
            self.assertEqual(set(check_versions(FakeRuntime(), task)), set(reports))
            reports['deepvariant'] = 'DeepVariant version 1.10.1\n'
            with self.assertRaisesRegex(ValueError, 'deepvariant executable version'):
                check_versions(FakeRuntime(), task)

    def test_only_execution_failure_triggers_one_fresh_proot_p2_attempt(self) -> None:
        """A failed biological oracle must never be relaxed through runtime fallback."""
        from giab_wes_nextflow import canonical_smoke
        from types import SimpleNamespace
        obj = SimpleNamespace(backend='udocker', udocker_mode='P1', environment={}, state={}, write_state=lambda: None)
        with patch.object(canonical_smoke, '_qualify_once', side_effect=[RuntimeError('seccomp'), {'status': 'passed'}]) as attempt:
            result = canonical_smoke.qualify(obj, Path('/content/smoke'))
            self.assertEqual(attempt.call_count, 2)
            self.assertEqual(attempt.call_args.args[1], Path('/content/smoke-proot-p2'))
            self.assertIn('same acceptance gate', result['fallback'])
        obj.udocker_mode = 'P1'
        with patch.object(canonical_smoke, '_qualify_once', side_effect=ValueError('positive SNV gate failed')) as attempt:
            with self.assertRaises(ValueError):
                canonical_smoke.qualify(obj, Path('/content/smoke'))
            self.assertEqual(attempt.call_count, 1)


if __name__ == '__main__':
    unittest.main()
