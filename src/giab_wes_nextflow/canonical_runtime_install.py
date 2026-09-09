"""Content-pinned, resumable user-space runtime installation on Linux scratch."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tarfile
import urllib.request
import urllib.error
import time
from typing import Any

from .acquisition import checksum
from .m4_contracts import load_json
from .resources import config_path


def verify_asset(path: Path, spec: dict[str, Any]) -> dict[str, Any]:
    """Require the declared size and SHA-256 or immutable Git blob identity."""
    if path.stat().st_size != spec['bytes']:
        raise ValueError('runtime asset size mismatch')
    digest = checksum(path)
    if spec.get('sha256') and digest != spec['sha256']:
        raise ValueError('runtime asset SHA-256 mismatch')
    if spec.get('git_blob_sha1'):
        h = hashlib.sha1(f"blob {spec['bytes']}\0".encode())
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1 << 20), b''):
                h.update(block)
        if h.hexdigest() != spec['git_blob_sha1']:
            raise ValueError('runtime asset immutable Git blob mismatch')
    if not spec.get('sha256') and not spec.get('git_blob_sha1'):
        raise ValueError('runtime asset lacks a preregistered content hash')
    return {'bytes': path.stat().st_size, 'sha256': digest, 'source': spec}


def _download_asset_once(spec: dict[str, Any], destination: Path) -> dict[str, Any]:
    """Resume verified HTTP ranges; promote only authenticated complete bytes."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return verify_asset(destination, spec)
    part = destination.with_name(destination.name + '.part')
    if part.exists() and part.stat().st_size == spec['bytes']:
        record = verify_asset(part, spec); os.replace(part, destination); return record
    offset = part.stat().st_size if part.exists() else 0
    request = urllib.request.Request(spec['url'], headers={'Range': f'bytes={offset}-'} if offset else {})
    with urllib.request.urlopen(request, timeout=60) as response:
        append = offset > 0 and response.status == 206
        if append and not response.headers.get('Content-Range', '').startswith(f'bytes {offset}-'):
            raise ValueError('invalid resumed runtime download range')
        with part.open('ab' if append else 'wb') as output:
            for block in iter(lambda: response.read(1 << 20), b''):
                output.write(block)
                if output.tell() > spec['bytes']:
                    raise ValueError('runtime download exceeds declared bytes')
            output.flush(); os.fsync(output.fileno())
    record = verify_asset(part, spec)
    os.replace(part, destination)
    return record


def download_asset(spec: dict[str, Any], destination: Path) -> dict[str, Any]:
    """Retry at most three transient transport attempts; preserve resumable bytes."""
    for attempt in range(3):
        try:
            return _download_asset_once(spec, destination)
        except urllib.error.HTTPError as error:
            if error.code not in {408, 425, 429, 500, 502, 503, 504} or attempt == 2:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == 2:
                raise
        time.sleep(2 ** attempt)
    raise RuntimeError('unreachable transport retry state')


def extract_safe(archive: Path, destination: Path) -> None:
    """Reject traversal, special nodes and escaping links before extracting tools."""
    with tarfile.open(archive) as source:
        names = set()
        for item in source.getmembers():
            path = PurePosixPath(item.name)
            if path.is_absolute() or '..' in path.parts or item.name in names:
                raise ValueError('unsafe or duplicate runtime archive path')
            names.add(item.name)
            if not (item.isfile() or item.isdir() or item.issym() or item.islnk()):
                raise ValueError('special file in runtime archive')
            if item.issym() or item.islnk():
                target = PurePosixPath(item.linkname)
                combined = (path.parent / target) if item.issym() else target
                depth = 0
                for component in combined.parts:
                    depth += -1 if component == '..' else 0 if component == '.' else 1
                    if depth < 0:
                        raise ValueError('escaping runtime archive link')
                if target.is_absolute():
                    raise ValueError('absolute runtime archive link')
        destination.mkdir(parents=True, exist_ok=True)
        source.extractall(destination, filter='data')


def inventory(root: Path) -> dict[str, str]:
    """Hash runtime files and preserve link targets independently of source URLs."""
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            result[str(path.relative_to(root))] = 'symlink:' + os.readlink(path)
        elif path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
            result[str(path.relative_to(root))] = checksum(path)
    return result


def install_udocker(root: Path) -> dict[str, Any]:
    """Install pinned source and PRoot engines without pip, sudo or Docker.

    Runtime installation completion is independent of actual tool qualification.
    Engine binaries are verified against the immutable upstream Git blob; their
    SHA-256 is observed after download, never misrepresented as publisher SHA-256.
    """
    lock = load_json(config_path('canonical-runtime.json'))['udocker']
    marker = root / 'installed.json'
    source, engine = root / 'source', root / 'engine'
    if marker.is_file():
        record = load_json(marker)
        if record['source_inventory'] != inventory(source) or record['engine_inventory'] != inventory(engine):
            raise ValueError('installed runtime inventory changed; use a fresh runtime directory')
        return record
    records = {}
    for kind, target in (('source', source), ('engine', engine)):
        archive = root / 'downloads' / f'{kind}.tar.gz'
        records[kind] = download_asset(lock[kind], archive)
        extract_safe(archive, target)
    record = {'backend': 'udocker', 'status': 'installed_not_qualified', 'version': lock['version'],
              'executable': str(source / 'udocker-1.3.17/udocker/maincmd.py'),
              'engine_root': str(engine / 'udocker_dir'), 'assets': records,
              'source_inventory': inventory(source), 'engine_inventory': inventory(engine)}
    marker.write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    return record
