#!/usr/bin/env python3
"""Acquire declared M2 sources and validate byte-bound, immutable observations.

Source-manifest MD5 values authenticate the declared public source bytes; SHA-256
identifies observed artifacts and their lineage. Existing records never replace
fresh byte validation. Paths are canonicalized before containment comparisons.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import http.client
import json
import os
from pathlib import Path
import random
import re
import shutil
import time
from typing import Any, Callable, Iterator
import urllib.error
import urllib.parse
import urllib.request

from jsonschema import Draft202012Validator, FormatChecker

from . import __version__
from .resources import config_path, schema_path

VERSION = __version__
USER_AGENT = f"giab-wes-nextflow-acquire/{VERSION}"
CANONICAL_IDS = {
    "giab_garvan_sequence_index", "hg001_nist7035_l001_r1", "hg001_nist7035_l001_r2",
    "grch38_no_alt_fasta_gz", "grch38_compressed_fai", "grch38_compressed_gzi",
    "hg001_v421_truth_vcf", "hg001_v421_truth_tbi", "hg001_v421_high_confidence_bed",
    "ucsc_hg19_to_hg38_chain",
}
FORBIDDEN_FOLDER = "DO NOT ACCESS WITH CHATGPT"


def now() -> str:
    """Return a UTC metadata timestamp, never a substitute for byte identity."""
    return dt.datetime.now(dt.timezone.utc).isoformat()


def checksum(path: str | Path, algorithm: str = "sha256") -> str:
    """Hash a file in bounded memory."""
    digest = hashlib.new(algorithm)
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def redact(url: str) -> str:
    """Remove query, fragment, and user-info credentials from durable URLs."""
    parsed = urllib.parse.urlsplit(url)
    host = parsed.netloc.rsplit("@", 1)[-1]
    return urllib.parse.urlunsplit((parsed.scheme, host, parsed.path, "", ""))


def validate_run_id(value: str) -> str:
    """Reject path syntax before a run identifier is joined to a registry root."""
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
        raise ValueError("unsafe run id")
    return value



def validate_timestamp(value: Any, label: str = "timestamp") -> None:
    """Validate RFC3339 timestamps without optional jsonschema format extras."""
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})", value
    ):
        raise ValueError(f"invalid {label}")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"invalid {label}") from error
    if parsed.utcoffset() is None:
        raise ValueError(f"timezone missing from {label}")

def _guard_path_parts(path: Path) -> None:
    """Reject prohibited folder names without inspecting their contents."""
    if any(FORBIDDEN_FOLDER in part for part in path.parts):
        raise PermissionError("prohibited folder name in path")


def safe_root(value: str | Path, allow_test_root: bool = False) -> Path:
    """Validate staging/private roots before access, including ancestor guards.

    macOS system aliases /tmp and /var are resolved normally. User-created
    symlinks in workspace ancestry are rejected rather than followed.
    """
    raw = Path(value).expanduser().absolute()
    _guard_path_parts(raw)
    for candidate in [raw, *raw.parents]:
        if candidate not in {Path("/tmp"), Path("/var")} and candidate.is_symlink():
            raise ValueError("symlink in workspace root")
    root = raw.resolve()
    _guard_path_parts(root)
    if root in {Path("/"), Path.home().resolve()} or (
        not allow_test_root and root.name not in {"giab-wes-nextflow-private", "m2-stage"}
    ):
        raise ValueError("unsafe acquisition root")
    for parent in [root, *root.parents]:
        if (parent / FORBIDDEN_FOLDER).exists():
            raise PermissionError("workspace safety marker present")
    return root


def destination(root: str | Path, relative: str | Path) -> Path:
    """Resolve a contained relative path and reject symlinks beneath its root.

    Both sides of the containment test must use the same canonical root; this
    matters on macOS where /tmp and /var are aliases under /private.
    """
    raw_root = Path(root).absolute()
    _guard_path_parts(raw_root)
    for parent in [raw_root, *raw_root.parents]:
        if parent not in {Path("/tmp"), Path("/var")} and parent.is_symlink():
            raise ValueError("symlink in destination root")
        if (parent / FORBIDDEN_FOLDER).exists():
            raise PermissionError("workspace safety marker present")
    root = raw_root.resolve()
    rel = Path(relative)
    _guard_path_parts(root)
    _guard_path_parts(rel)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise ValueError("unsafe destination")
    candidate = root
    for part in rel.parts:
        if (candidate / FORBIDDEN_FOLDER).exists():
            raise PermissionError("workspace safety marker present")
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError("symlink in destination")
    out = candidate.resolve()
    if root not in out.parents:
        raise ValueError("destination escapes root")
    return out


def load_manifest(path: str | Path | None = None, *, allow_historical_version: bool = False) -> dict[str, Any]:
    """Validate a complete canonical manifest before any acquisition side effect.

    The historical-version exception is only for explicit cache recovery. Its
    caller must also bind the old manifest hash and compare its resource
    contracts with the currently installed canonical manifest.
    """
    manifest_path = Path(path) if path else config_path("m2-resources.json")
    manifest_path = destination(manifest_path.parent, manifest_path.name)
    spec = json.loads(manifest_path.read_text())
    schema = json.loads(schema_path("m2-source-manifest.schema.json").read_text())
    if allow_historical_version:
        schema["properties"]["project_version"] = {"type": "string", "pattern": r"^0\.[0-9]+\.[0-9]+-dev\.[0-9]+$"}
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(spec)
    validate_timestamp(spec["accessed_utc"], "manifest accessed_utc")
    resources = spec["resources"]
    ids = [item["id"] for item in resources]
    destinations = [item["destination"] for item in resources]
    filenames = [item["filename"] for item in resources]
    if set(ids) != CANONICAL_IDS or len(ids) != len(set(ids)):
        raise ValueError("manifest must contain each canonical resource exactly once")
    if len(destinations) != len(set(destinations)) or len(filenames) != len(set(filenames)):
        raise ValueError("duplicate destination or filename")
    for item in resources:
        if {"md5", "path"} & set(item):
            raise ValueError("legacy manifest keys are forbidden")
        destination(Path("/tmp/manifest-root"), item["destination"])
        parsed = urllib.parse.urlsplit(item["url"])
        if parsed.scheme != "https" or parsed.username or parsed.password:
            raise ValueError(f"unsafe URL for {item['id']}")
        if item["checksum"]["algorithm"] != "md5" or not re.fullmatch(r"[0-9a-f]{32}", item["checksum"]["expected"]):
            raise ValueError(f"invalid checksum for {item['id']}")
    return spec


def validate_source_bytes(path: Path, resource: dict[str, Any], observed: dict[str, Any] | None = None) -> None:
    """Check a source against declared MD5/size and optional observed SHA-256."""
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"missing or unsafe source: {resource['id']}")
    size = path.stat().st_size
    if size <= 0 or (resource.get("bytes") is not None and size != resource["bytes"]):
        raise ValueError(f"source size mismatch: {resource['id']}")
    if checksum(path, "md5") != resource["checksum"]["expected"]:
        raise ValueError(f"source MD5 mismatch: {resource['id']}")
    if observed is not None and (size != observed["bytes"] or checksum(path) != observed["sha256"]):
        raise ValueError(f"source observation mismatch: {resource['id']}")


def validate_acquisition(record: dict[str, Any], manifest: dict[str, Any], manifest_sha256: str,
                         root: Path | None = None, *, require_complete: bool = True,
                         run_id: str | None = None) -> None:
    """Validate observation schema, source identity, inventory and optional bytes."""
    schema = json.loads(schema_path("m2-acquisition.schema.json").read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(record)
    validate_run_id(record["run_id"])
    validate_timestamp(record["created_utc"], "acquisition created_utc")
    if run_id is not None and record["run_id"] != run_id:
        raise ValueError("acquisition run identity mismatch")
    if record["source_manifest_sha256"] != manifest_sha256:
        raise ValueError("acquisition source manifest mismatch")
    resources = {item["id"]: item for item in manifest["resources"]}
    observations = record["observations"]
    ids = [item["id"] for item in observations]
    if not ids or len(ids) != len(set(ids)) or not set(ids) <= set(resources):
        raise ValueError("invalid acquisition inventory")
    if require_complete and set(ids) != set(resources):
        raise ValueError("incomplete acquisition inventory")
    for item in observations:
        validate_timestamp(item["verified_utc"], "observation verified_utc")
        effective = urllib.parse.urlsplit(item["effective_url"])
        if effective.scheme not in {"http", "https"} or effective.username or effective.password or effective.query or effective.fragment:
            raise ValueError("unsafe effective source URL")
        if any(not isinstance(item["tool"].get(key), str) or not item["tool"][key] for key in ("name", "version")):
            raise ValueError("observation producer identity missing")
        resource = resources[item["id"]]
        if item["destination"] != resource["destination"] or item["source_url"] != redact(resource["url"]):
            raise ValueError("acquisition resource identity mismatch")
        expected = {"algorithm": "md5", "expected": resource["checksum"]["expected"], "observed": resource["checksum"]["expected"]}
        if item["checksum"] != expected:
            raise ValueError("acquisition checksum declaration mismatch")
        if resource["bytes"] is not None and item["bytes"] != resource["bytes"]:
            raise ValueError("acquisition declared size mismatch")
        if root is not None:
            validate_source_bytes(destination(root, item["destination"]), resource, item)


def preflight(manifest: str | Path | None = None, workspace: str | Path | None = None,
              remote: bool = False, opener: Callable[..., Any] = urllib.request.urlopen) -> dict[str, Any]:
    """Return a zero-download readiness result; storage is a reported lower bound."""
    spec = load_manifest(manifest)
    result = {"ok": True, "resource_count": len(spec["resources"]),
              "resource_ids": [item["id"] for item in spec["resources"]],
              "declared_bytes": sum(item["bytes"] or 0 for item in spec["resources"]),
              "unknown_size_resources": sum(item["bytes"] is None for item in spec["resources"]),
              "remote_checked": remote}
    if workspace:
        root = safe_root(workspace)
        parent = next(path for path in [root, *root.parents] if path.exists())
        result.update(workspace=str(root), free_bytes=shutil.disk_usage(parent).free)
    if remote:
        for item in spec["resources"]:
            request = urllib.request.Request(item["url"], method="HEAD", headers={"User-Agent": USER_AGENT})
            with opener(request, timeout=20):
                pass
    return result


@contextlib.contextmanager
def lock(path: Path, timeout: float = 15) -> Iterator[None]:
    """Hold an exclusive operation lock; preserve conflicts rather than guessing."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(descriptor, str(os.getpid()).encode())
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"lock busy: {path.name}") from None
            time.sleep(.05)
    try:
        yield
    finally:
        os.close(descriptor)
        Path(path).unlink(missing_ok=True)


def write_record(path: Path, record: dict[str, Any]) -> None:
    """Atomically create an immutable JSON record, allowing only exact reuse."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(record, sort_keys=True, indent=2) + "\n"
    with lock(Path(str(path) + ".lock")):
        if path.exists():
            if path.read_text() != payload:
                raise FileExistsError("immutable record conflict")
            return
        tmp = Path(str(path) + ".incomplete")
        if tmp.is_symlink():
            raise ValueError("symlink in record staging")
        with tmp.open("w") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)


def acquire(resource: dict[str, Any], root: Path, retries: int = 3,
            opener: Callable[..., Any] = urllib.request.urlopen,
            sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Resume bounded transient failures and promote only declared source bytes."""
    root = Path(root).resolve()
    final = destination(root, resource["destination"])
    final.parent.mkdir(parents=True, exist_ok=True)
    part = destination(root, resource["destination"] + ".part")
    expected = resource["checksum"]["expected"]
    with lock(Path(str(final) + ".lock")):
        if final.exists() and checksum(final, "md5") == expected:
            validate_source_bytes(final, resource)
            return observation(resource, final, "verified", 0, {}, resource["url"])
        if final.exists():
            quarantine = Path(str(final) + f".corrupt-{time.time_ns()}")
            os.replace(final, quarantine)
        attempts = 0
        metadata: dict[str, Any] = {}
        effective = resource["url"]
        while True:
            # A process can stop after a complete transfer but before promotion.
            # Reuse those exact bytes before issuing an out-of-range request;
            # this also covers a completed transfer followed by a read error.
            if part.exists():
                try:
                    validate_source_bytes(part, resource)
                except ValueError:
                    pass
                else:
                    os.replace(part, final)
                    return observation(resource, final, "verified", attempts,
                                       {"recovered_complete_partial": True}, effective)
            offset = part.stat().st_size if part.exists() else 0
            headers = {"User-Agent": USER_AGENT}
            if offset:
                headers["Range"] = f"bytes={offset}-"
            try:
                request = urllib.request.Request(resource["url"], headers=headers)
                with opener(request, timeout=60) as response:
                    status = getattr(response, "status", 200)
                    effective = response.geturl()
                    append = bool(offset and status == 206)
                    if append:
                        content_range = response.headers.get("Content-Range", "")
                        if not re.fullmatch(rf"bytes {offset}-[0-9]+/[0-9]+", content_range):
                            raise ValueError("invalid resumed Content-Range")
                    written = 0
                    with part.open("ab" if append else "wb") as out:
                        while True:
                            block = response.read(1 << 20)
                            if not block:
                                break
                            out.write(block)
                            written += len(block)
                        out.flush()
                        os.fsync(out.fileno())
                    declared = response.headers.get("Content-Length")
                    if declared is not None and written != int(declared):
                        raise http.client.IncompleteRead(b"", int(declared) - written)
                    metadata = {"http_status": status, "etag": response.headers.get("ETag"),
                                "last_modified": response.headers.get("Last-Modified"),
                                "content_length": declared, "range_requested": append}
                break
            except urllib.error.HTTPError as error:
                error.close()
                attempts += 1
                if error.code not in {408, 425, 429, 500, 502, 503, 504} or attempts > retries:
                    raise
            except (urllib.error.URLError, http.client.IncompleteRead, TimeoutError, ConnectionError, OSError):
                attempts += 1
                if attempts > retries:
                    raise
            sleep(min(8, 2 ** (attempts - 1)) + random.random() / 10)
        try:
            validate_source_bytes(part, resource)
        except ValueError:
            part.unlink(missing_ok=True)
            raise
        os.replace(part, final)
        return observation(resource, final, "verified", attempts, metadata, effective)


def observation(resource: dict[str, Any], path: Path, status: str, retries: int,
                response: dict[str, Any], effective_url: str) -> dict[str, Any]:
    """Record current verified bytes, sanitized URLs, and the producing version."""
    return {"id": resource["id"], "status": status, "source_url": redact(resource["url"]),
            "effective_url": redact(effective_url), "destination": resource["destination"],
            "bytes": path.stat().st_size, "checksum": {"algorithm": "md5", "expected": resource["checksum"]["expected"],
            "observed": checksum(path, "md5")}, "sha256": checksum(path), "verified_utc": now(),
            "retry_count": retries, "response": response, "tool": {"name": "acquire_m2.py", "version": VERSION}}


def main(argv: list[str] | None = None) -> int:
    """Run preflight/acquisition; partial immutable runs require a fresh run ID."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace")
    parser.add_argument("--manifest")
    parser.add_argument("--only", action="append")
    parser.add_argument("--run-id")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--check-remote", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = preflight(args.manifest, args.workspace, args.check_remote)
    except Exception as error:
        parser.error(f"preflight failed ({type(error).__name__}): {str(error).split('?')[0]}")
    if args.preflight_only:
        print(json.dumps(result, sort_keys=True))
        return 0
    if not args.workspace or not args.run_id:
        parser.error("--workspace and --run-id are required for acquisition")
    try:
        validate_run_id(args.run_id)
    except ValueError as error:
        parser.error(str(error))
    root = safe_root(args.workspace)
    spec = load_manifest(args.manifest)
    if args.only and not set(args.only) <= CANONICAL_IDS:
        parser.error("unknown --only resource")
    selected = [item for item in spec["resources"] if not args.only or item["id"] in args.only]
    manifest_path = Path(args.manifest) if args.manifest else config_path("m2-resources.json")
    manifest_hash = checksum(manifest_path)
    out = destination(root, f"registry/runs/{args.run_id}/acquisition.json")
    if out.exists():
        existing = json.loads(out.read_text())
        validate_acquisition(existing, spec, manifest_hash, root, require_complete=False, run_id=args.run_id)
        if {item["id"] for item in selected} != {item["id"] for item in existing["observations"]}:
            raise ValueError("immutable acquisition selection differs; use a new run ID to reuse verified source bytes")
        print(out)
        return 0
    observations = []
    for resource in selected:
        final = destination(root, resource["destination"])
        state = "reused" if final.exists() else ("resumed" if Path(str(final) + ".part").exists() else "new")
        print(f"resource={resource['id']} destination={resource['destination']} state={state}", flush=True)
        try:
            observations.append(acquire(resource, root))
        except Exception as error:
            part = Path(str(final) + ".part")
            rerun = f"giab-wes-acquire-m2 --workspace {root} --run-id {args.run_id}"
            print(f"ERROR resource={resource['id']} class={type(error).__name__} message={str(error).split('?')[0]} partial={'retained' if part.exists() else 'absent'} rerun={rerun}", flush=True)
            return 1
    record = {"schema_version": "1.0.0", "run_id": args.run_id, "created_utc": now(),
              "source_manifest_sha256": manifest_hash, "observations": observations}
    validate_acquisition(record, spec, manifest_hash, root, require_complete=not args.only, run_id=args.run_id)
    write_record(out, record)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
