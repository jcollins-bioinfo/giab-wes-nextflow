"""Qualifiable Linux runtimes with narrow task mounts and auditable resource guards.

Discovery and successful version probes are configured evidence. Representative
GATK and DeepVariant execution plus independent output validation is required
before the runtime can be marked qualified. PRoot is filesystem translation,
not an adversarial security boundary; canonical truth isolation uses staging.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import resource
import shutil
import signal
import subprocess
import sys
import time
from typing import Any, Callable

from .acquisition import checksum
from .canonical_host import memory_limits
from .canonical_runtime_install import install_udocker, inventory
from .m4_contracts import load_json
from .resources import config_path

GIB = 1024 ** 3
EXECUTABLES = {'deepvariant': '/opt/deepvariant/bin/run_deepvariant', 'bwa-mem2': 'bwa-mem2'}


def tool_lock() -> dict[str, Any]:
    """Merge accepted historical OCI pins without rewriting M3-M5 contracts."""
    tools: dict[str, Any] = {}
    for name in ('m3-tools.json', 'm4-tools.json', 'm5-tools.json', 'canonical-runtime.json'):
        for tool, entry in load_json(config_path(name))['tools'].items():
            if tool in tools and tools[tool]['image'] != entry['image']:
                raise ValueError('conflicting immutable tool images')
            if not re.fullmatch(r'[^\s]+@sha256:[0-9a-f]{64}', entry['image']):
                raise ValueError('mutable or malformed tool image')
            tools[tool] = entry
    return tools


def _scratch(path: Path) -> Path:
    """Reject Drive, protected paths and symlink escape for active runtime state."""
    absolute = path.absolute()
    if any(part == 'DO NOT ACCESS WITH CHATGPT' for part in absolute.parts):
        raise ValueError('protected folder cannot be accessed')
    if any(parent.is_symlink() for parent in (absolute, *absolute.parents)):
        raise ValueError('active runtime paths cannot use symlinks')
    if not absolute.is_relative_to('/content') or absolute.is_relative_to('/content/drive'):
        raise ValueError('canonical Colab active work must remain on /content outside Drive')
    return absolute


@dataclass(frozen=True)
class Limits:
    """Explicit operator ceilings, independently constrained by observed host limits."""

    cpus: int = 8
    memory_bytes: int = 44 * GIB
    scratch_reserve_bytes: int = 16 * GIB

    def validate(self) -> None:
        """Reject invalid ceilings and requests exceeding available host resources."""
        if isinstance(self.cpus, bool) or not isinstance(self.cpus, int) or not 1 <= self.cpus <= 8:
            raise ValueError('CPU ceiling must be an integer from 1 to 8')
        if not isinstance(self.memory_bytes, int) or not GIB <= self.memory_bytes <= 44 * GIB:
            raise ValueError('memory ceiling must be between 1 and 44 GiB')
        allowed = os.sched_getaffinity(0) if hasattr(os, 'sched_getaffinity') else range(os.cpu_count() or 1)
        if self.cpus > len(allowed):
            raise ValueError('CPU ceiling exceeds available logical CPUs')
        effective = memory_limits()['effective_ceiling_bytes']
        if effective is None or self.memory_bytes > int(effective * 0.90):
            raise ValueError('memory ceiling exceeds 90% of effective host RAM or RAM is unknown')


def _tree_rss(root_pid: int) -> int:
    """Sample summed descendant RSS; shared pages can be counted more than once."""
    rows = {}
    for path in Path('/proc').glob('[0-9]*/stat'):
        try:
            fields = path.read_text().rsplit(')', 1)[1].split()
            rows[int(path.parent.name)] = (int(fields[1]), int(fields[21]) * os.sysconf('SC_PAGE_SIZE'))
        except (OSError, ValueError, IndexError):
            continue
    selected = {root_pid}
    while True:
        found = {pid for pid, (parent, _) in rows.items() if parent in selected}
        if found <= selected:
            break
        selected |= found
    return sum(rows.get(pid, (0, 0))[1] for pid in selected)


class Runtime:
    """Execute reviewed tools through functional local container or native routes."""

    def __init__(self, scratch: Path, *, backend: str = 'auto', cpus: int = 8,
                 memory_bytes: int = 44 * GIB, allow_install: bool = False,
                 native_manifest: Path | None = None, udocker_mode: str = 'P1') -> None:
        """Configure scratch and limits; scientific tools are not executed here."""
        if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'amd64'):
            raise ValueError('canonical runtime requires actual Linux amd64; Mac execution is forbidden')
        if backend not in ('auto', 'apptainer', 'singularity', 'podman', 'docker', 'udocker', 'native'):
            raise ValueError('unsupported runtime backend')
        self.root = _scratch(Path(scratch))
        self.root.mkdir(parents=True, exist_ok=True)
        self.limits = Limits(cpus, memory_bytes); self.limits.validate()
        self.cpus = cpus
        self.memory_bytes = memory_bytes
        if udocker_mode not in ('P1', 'P2'):
            raise ValueError('only reviewed PRoot modes P1/P2 are supported')
        self.udocker_mode = udocker_mode
        self.backend = backend
        self.allow_install = allow_install
        self.tools = tool_lock()
        self.native = load_json(native_manifest) if native_manifest else None
        self.executable: list[str] = []
        self.environment = {key: value for key, value in os.environ.items() if key in ('PATH', 'LANG', 'LC_ALL', 'SSL_CERT_FILE', 'SSL_CERT_DIR')}
        self.environment.update(HOME=str(self.root / 'home'), TMPDIR=str(self.root / 'tmp'), PYTHONDONTWRITEBYTECODE='1')
        for name in ('home', 'tmp', 'audit', 'images'):
            (self.root / name).mkdir(exist_ok=True)
        self.environment.update(APPTAINER_CACHEDIR=str(self.root / 'images'), APPTAINER_TMPDIR=str(self.root / 'tmp'),
                                SINGULARITY_CACHEDIR=str(self.root / 'images'), SINGULARITY_TMPDIR=str(self.root / 'tmp'))
        self.state: dict[str, Any] = {'status': 'configured_only', 'architecture': platform.machine(), 'backend': None,
                                      'discovery_failures': [], 'images': {}, 'qualification': None}

    def _control(self, argv: list[str], *, timeout: int = 1800) -> str:
        """Capture bounded preparation diagnostics without inheriting credentials."""
        result = subprocess.run(argv, cwd=self.root, env=self.environment, capture_output=True, text=True, timeout=timeout)
        name = hashlib.sha256(json.dumps(argv).encode()).hexdigest()[:20]
        (self.root / 'audit' / f'control-{name}.json').write_text(json.dumps({'argv': argv, 'returncode': result.returncode,
                       'stdout': result.stdout[-10000:], 'stderr': result.stderr[-10000:]}, indent=2) + '\n')
        if result.returncode:
            raise RuntimeError(f'runtime preparation failed ({result.returncode}); see control-{name}.json')
        return result.stdout

    def _select(self, backend: str) -> None:
        """Select one installed runtime and bind it to observed executable identity."""
        if backend == 'udocker':
            install = self.root / 'vendor/udocker'
            if not (install / 'installed.json').exists() and not self.allow_install:
                raise ValueError('udocker installation requires allow_install=True')
            record = install_udocker(install)
            # Keep mutable OCI layers separate from the immutable engine inventory.
            repo = self.root / 'udocker-repository'; repo.mkdir(exist_ok=True)
            self.environment.update(UDOCKER_DIR=str(repo), UDOCKER_BIN=str(Path(record['engine_root']) / 'bin'),
                                    UDOCKER_LIB=str(Path(record['engine_root']) / 'lib'), UDOCKER_DOC=str(Path(record['engine_root']) / 'doc'),
                                    UDOCKER_TARBALL=str(install / 'downloads/engine.tar.gz'), UDOCKER_TMP=str(self.root / 'tmp'),
                                    UDOCKER_DEFAULT_EXECUTION_MODE=self.udocker_mode, UDOCKER_LOGLEVEL='0')
            self.executable = [sys.executable, record['executable'], '--allow-root']
            self.state['installer'] = record
        elif backend == 'native':
            if not self.native or self.native.get('isolation') != 'reduced_native' or not self.native.get('adr'):
                raise ValueError('native fallback requires an explicit reviewed manifest and reduced-isolation ADR')
            self.executable = []
        else:
            path = shutil.which(backend)
            if not path:
                raise ValueError(f'{backend} executable unavailable')
            self.executable = [path]
        self.state['images'] = {}
        self.backend = backend
        self.state['backend'] = backend
        self.state['udocker_mode'] = self.udocker_mode if backend == 'udocker' else None
        if self.executable:
            version = self._control([*self.executable, '--version'], timeout=30)
            self.state['runtime_identity'] = {'argv_prefix': self.executable, 'version_stdout': version.strip(),
                'executable_sha256': checksum(self.executable[0]), 'launcher_sha256': checksum(self.executable[1]) if backend == 'udocker' else None}

    def discover(self) -> dict[str, Any]:
        """Try priority runtimes with a real container probe; retain configured status."""
        if self.state['backend']:
            return self.state
        prior = self.root / 'runtime-state.json'
        if prior.is_file():
            saved = load_json(prior)
            if saved.get('status') == 'qualified_representative_callers' and (self.backend == 'auto' or self.backend == saved['backend']):
                self.udocker_mode = saved.get('udocker_mode') or self.udocker_mode
                self._select(saved['backend'])
                if self.state.get('runtime_identity') != saved.get('runtime_identity'):
                    raise ValueError('qualified runtime executable identity changed')
                for tool, entry in saved['images'].items():
                    if saved['backend'] != 'native' and entry.get('source_image') != self.tools[tool]['image']:
                        raise ValueError('qualified runtime tool image changed')
                self.state = saved
                for record in saved['qualification']['executions'].values():
                    if load_json(Path(record['audit_record_path'])) != record:
                        raise ValueError('qualified execution receipt changed')
                    if checksum(record['stdout_path']) != record['stdout_sha256'] or checksum(record['stderr_path']) != record['stderr_sha256']:
                        raise ValueError('qualified execution logs changed')
                return self.state
        requested = self.backend
        candidates = ['apptainer', 'singularity', 'podman', 'udocker'] if requested == 'auto' else [requested]
        if requested == 'auto' and self.native:
            candidates.append('native')
        for candidate in candidates:
            try:
                self._select(candidate)
                self.prepare('samtools')
                probe = self.root / 'probe'; probe.mkdir(exist_ok=True)
                self.run('samtools', ['--version'], task_dir=probe, timeout_seconds=120, stage='runtime-probe')
                self.state['functional_probe'] = True
                self._save()
                return self.state
            except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
                self.state['discovery_failures'].append({'backend': candidate, 'error': str(error)})
                if candidate == 'udocker' and self.udocker_mode == 'P1' and self.state['backend'] == 'udocker':
                    try:
                        self.udocker_mode = 'P2'
                        self.environment['UDOCKER_DEFAULT_EXECUTION_MODE'] = 'P2'
                        self.state['udocker_mode'] = 'P2'
                        probe = self.root / 'probe-p2'; probe.mkdir(exist_ok=True)
                        self.run('samtools', ['--version'], task_dir=probe, timeout_seconds=120, stage='runtime-probe')
                        self.state['functional_probe'] = True
                        self._save()
                        return self.state
                    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as fallback_error:
                        self.state['discovery_failures'].append({'backend': 'udocker-P2', 'error': str(fallback_error)})
                self.state['backend'] = None
        self.backend = requested
        self._save()
        raise RuntimeError('No runtime passed functional discovery; inspect runtime-state.json. Representative GATK/DeepVariant qualification has not occurred.')

    def _save(self) -> None:
        """Persist state atomically; configured evidence never implies qualification."""
        part = self.root / 'runtime-state.json.part'
        part.write_text(json.dumps(self.state, indent=2, sort_keys=True) + '\n')
        os.replace(part, self.root / 'runtime-state.json')

    def write_state(self) -> Path:
        """Write the current receipt and return its explicit evidence path."""
        self._save()
        return self.root / 'runtime-state.json'

    def prepare(self, tool: str) -> dict[str, Any]:
        """Acquire the existing digest-pinned image or validate an exact native inventory."""
        if not self.state['backend']:
            self.discover()
        if tool not in self.tools:
            raise ValueError('tool lacks a reviewed immutable identity')
        if shutil.disk_usage(self.root).free < self.limits.scratch_reserve_bytes:
            raise ValueError('runtime scratch reserve is exhausted')
        image = self.tools[tool]['image']
        if self.backend == 'native':
            entry = self.native['tools'].get(tool)
            if not entry or entry['version'] != self.tools[tool]['version']:
                raise ValueError('native tool version missing or differs from reviewed tool')
            prefix = _scratch(Path(entry['prefix']))
            if inventory(prefix) != entry['inventory']:
                raise ValueError('native installation inventory changed')
            executable = prefix / entry['executable']
            if executable.resolve() != executable.absolute() or not executable.is_file():
                raise ValueError('unsafe native executable')
            result = {'source_image': None, 'native_manifest': entry, 'executable': str(executable)}
        elif self.backend in ('apptainer', 'singularity'):
            path = self.root / 'images' / (image.rsplit(':', 1)[1] + '.sif')
            marker = path.with_suffix('.json')
            if marker.exists():
                saved = load_json(marker)
                if saved['sha256'] != checksum(path):
                    raise ValueError('cached SIF changed')
            else:
                part = path.with_suffix('.part.sif')
                self._control([*self.executable, 'pull', '--force', str(part), 'docker://' + image])
                saved = {'source_image': image, 'sha256': checksum(part)}
                os.replace(part, path)
                marker.write_text(json.dumps(saved) + '\n')
            result = {**saved, 'sif': str(path)}
        else:
            if tool not in self.state['images']:
                command = [*self.executable, 'pull']
                if self.backend != 'udocker':
                    command += ['--platform', 'linux/amd64']
                self._control([*command, image])
            result = {'source_image': image}
        self.state['images'][tool] = result
        return result

    def command(self, tool: str, args: list[str], *, task_dir: Path, cpus: int | None = None,
                memory_bytes: int | None = None) -> list[str]:
        """Build argv binding only the task root; never bind /content, Drive or HOME."""
        task = _scratch(task_dir)
        if not task.is_dir() or task == self.root or task == Path('/content'):
            raise ValueError('a distinct existing task directory is required')
        if any(path.is_symlink() for path in task.rglob('*')):
            raise ValueError('task staging cannot contain symlinks; copy or hardlink explicit inputs')
        cpus = self.limits.cpus if cpus is None else cpus
        memory = self.limits.memory_bytes if memory_bytes is None else memory_bytes
        if not isinstance(cpus, int) or not 1 <= cpus <= self.limits.cpus or not isinstance(memory, int) or not GIB <= memory <= self.limits.memory_bytes:
            raise ValueError('task request exceeds resource ceilings')
        if not all(isinstance(arg, str) and '\0' not in arg for arg in args):
            raise ValueError('tool arguments must be a list of strings without NUL')
        prepared = self.prepare(tool)
        tool_environment = [f'OMP_NUM_THREADS={cpus}', f'TF_NUM_INTRAOP_THREADS={cpus}', 'TF_NUM_INTEROP_THREADS=1', 'RTG_MEM=8G']
        executable = EXECUTABLES.get(tool, tool)
        if self.backend in ('apptainer', 'singularity'):
            return [*self.executable, 'exec', '--containall', '--cleanenv', '--no-home', '--bind', f'{task}:/work', '--pwd', '/work',
                    '--env', ','.join(tool_environment), prepared['sif'], executable, *args]
        if self.backend == 'udocker':
            return [*self.executable, 'run', '--rm', '--pull=never', '--nobanner', '--containerauth', f'--entrypoint={executable}',
                    '--workdir=/work', f'--volume={task}:/work', *[f'--env={value}' for value in tool_environment], prepared['source_image'], *args]
        if self.backend in ('podman', 'docker'):
            return [*self.executable, 'run', '--rm', '--network=none', '--platform=linux/amd64', '--cpus', str(cpus),
                    '--memory', str(memory), '--memory-swap', str(memory), '--mount', f'type=bind,src={task},dst=/work',
                    '--workdir', '/work', *[part for value in tool_environment for part in ('--env', value)], '--entrypoint', executable, prepared['source_image'], *args]
        self.environment.update(dict(value.split('=', 1) for value in tool_environment))
        return [prepared['executable'], *args]

    def run(self, tool: str, args: list[str], *, task_dir: Path, timeout_seconds: int = 86400,
            cpus: int | None = None, memory_bytes: int | None = None, stage: str = 'scientific-task',
            expected_exit_codes: tuple[int, ...] = (0,)) -> dict[str, Any]:
        """Execute once, recording command, logs and reliable versus limited resources.

        Scientific failures are not retried automatically. CPU affinity and a
        sampled process-tree RSS guard constrain no-daemon execution; Docker
        metrics remain unavailable because its daemon is outside the process tree.
        """
        cpus = self.limits.cpus if cpus is None else cpus
        memory = self.limits.memory_bytes if memory_bytes is None else memory_bytes
        argv = self.command(tool, args, task_dir=task_dir, cpus=cpus, memory_bytes=memory)
        if stage in {'shared_preprocessing', 'gatk', 'deepvariant', 'common_downstream'} and self.state['status'] != 'qualified_representative_callers':
            raise ValueError('canonical scientific execution requires qualified representative callers')
        stamp = f'{time.time_ns()}-{tool}'
        stdout, stderr = self.root / 'audit' / (stamp + '.stdout'), self.root / 'audit' / (stamp + '.stderr')
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        observed_start_utc = datetime.now(timezone.utc).isoformat()
        started = time.monotonic(); peak = 0; termination = None
        with stdout.open('wb') as out, stderr.open('wb') as err:
            proc = subprocess.Popen(argv, cwd=task_dir, env=self.environment, stdout=out, stderr=err, start_new_session=True)
            if hasattr(os, 'sched_setaffinity'):
                try:
                    os.sched_setaffinity(proc.pid, sorted(os.sched_getaffinity(0))[:cpus])
                except ProcessLookupError:
                    pass
            try:
                while proc.poll() is None:
                    observed = _tree_rss(proc.pid); peak = max(peak, observed)
                    if observed > memory:
                        termination = 'sampled_process_tree_rss_ceiling_exceeded'
                    elif time.monotonic() - started > timeout_seconds:
                        termination = 'wall_timeout'
                    if termination:
                        os.killpg(proc.pid, signal.SIGTERM)
                        try:
                            proc.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            os.killpg(proc.pid, signal.SIGKILL)
                        break
                    time.sleep(0.2)
            except BaseException:
                if proc.poll() is None:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
                raise
            code = proc.wait()
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        daemon = self.backend in ('docker', 'podman')
        cpu_seconds = None if daemon else (after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime)
        record = {'audit_record_path': str(self.root / 'audit' / (stamp + '.json')), 'tool': tool, 'stage': stage, 'argv': argv, 'image': self.tools[tool]['image'] if self.backend != 'native' else None,
                  'runtime': self.state['runtime_identity'] if self.backend != 'native' else {'backend': 'native'},
                  'backend': self.backend, 'runtime_mode': self.udocker_mode if self.backend == 'udocker' else None, 'returncode': code, 'termination': termination, 'attempt': 1, 'cached': False, 'uncached': True, 'observed_start_utc': observed_start_utc,
                  'stdout_path': str(stdout), 'stderr_path': str(stderr), 'stdout_sha256': checksum(stdout), 'stderr_sha256': checksum(stderr),
                  'wall_seconds': time.monotonic() - started, 'resources': {'requested_cpus': cpus, 'requested_memory_bytes': memory,
                  'cpu_seconds': cpu_seconds, 'cpu_hours': None if cpu_seconds is None else cpu_seconds / 3600,
                  'cpu_basis': 'unavailable_daemon_accounting' if daemon else 'waited_children_rusage_delta_serial_launcher',
                  'sampled_tree_rss_upper_bound_bytes': None if daemon else peak, 'rss_sampling_seconds': 0.2,
                  'peak_rss_bytes': None, 'peak_rss_missing_reason': 'no exact aggregate RSS maximum; sampled tree sums may double-count shared pages',
                  'architecture': platform.machine(), 'accelerator': 'none_used'},
                  'isolation': 'narrow_task_mount' if self.backend != 'native' else 'reduced_native_no_filesystem_boundary'}
        (self.root / 'audit' / (stamp + '.json')).write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
        if termination or code not in expected_exit_codes:
            raise RuntimeError(f'{tool} failed ({code}, {termination}); audit record {stamp}.json')
        return record

    def qualify(self, executions: dict[str, dict[str, Any]], validator: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        """Mark qualified only after real caller records and independent outputs pass."""
        if set(executions) != {'gatk', 'deepvariant'}:
            raise ValueError('both representative GATK and DeepVariant executions are required')
        for tool, record in executions.items():
            if load_json(Path(record['audit_record_path'])) != record:
                raise ValueError('qualification requires an unchanged actual execution receipt')
            if record['tool'] != tool or record['returncode'] != 0 or record['image'] != (None if self.backend == 'native' else self.tools[tool]['image']) or record['backend'] != self.backend:
                raise ValueError('qualification caller execution identity mismatch')
            if record['stage'] != 'runtime-qualification' or any(arg in ('--version', '--help') for arg in record['argv']):
                raise ValueError('version/help probes cannot qualify a runtime')
            if checksum(record['stdout_path']) != record['stdout_sha256'] or checksum(record['stderr_path']) != record['stderr_sha256']:
                raise ValueError('qualification log identity changed')
        evidence = validator()
        if not isinstance(evidence, dict) or evidence.get('accepted') is not True:
            raise ValueError('independent representative-output validator did not accept')
        self.state['qualification'] = {'executions': executions, 'output_validation': evidence}
        self.state['status'] = 'qualified_representative_callers'
        self._save()
        return self.state
