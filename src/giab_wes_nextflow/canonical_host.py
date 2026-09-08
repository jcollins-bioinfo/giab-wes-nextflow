"""Observe a Colab/Linux host without claiming canonical execution readiness.

No package installation, image pull, index build, genomic acquisition, Drive
publication, or system change is performed. Storage locations describe durable
intent; active work stays on Colab /content scratch, not on the owner's Mac. Filesystem free space is not Drive
account quota. The owner must return this report before an execution plan is set.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
from typing import Any

from .acquisition import safe_root
from .m4_contracts import _write
from .runtime_identity import verify_install

INDEX_ESTIMATE_BYTES = 86_797_831_148


def memory_limits() -> dict[str, int | None]:
    """Report physical and cgroup ceilings separately; unknown values remain null."""
    physical = None
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        for line in meminfo.read_text().splitlines():
            if line.startswith("MemTotal:"):
                physical = int(line.split()[1]) * 1024
    limits = []
    for name in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        path = Path(name)
        if path.is_file():
            value = path.read_text().strip()
            if value.isdigit() and 0 < int(value) < 2 ** 60:
                limits.append(int(value))
    cgroup = min(limits) if limits else None
    known = [value for value in (physical, cgroup) if value is not None]
    return {"physical_bytes": physical, "cgroup_limit_bytes": cgroup,
            "effective_ceiling_bytes": min(known) if known else None}


def probe(drive_root: Path, scratch: Path) -> dict[str, Any]:
    """Inspect only the named project root and bounded runtime capability metadata."""
    drive = safe_root(drive_root)
    local = safe_root(scratch, allow_test_root=True)
    if not drive.is_dir() or not local.is_dir():
        raise ValueError("mount the existing project Drive folder and choose existing local scratch")
    if local == drive or local.is_relative_to(drive):
        raise ValueError("active scratch must be outside Drive")
    docker = {"executable_available": shutil.which("docker") is not None,
              "daemon_reachable": False, "architecture": None, "total_memory_bytes": None}
    if docker["executable_available"]:
        try:
            result = subprocess.run(["docker", "info", "--format", "{" * 2 + "json ." + "}" * 2], capture_output=True,
                                    text=True, timeout=15, check=True)
            info = json.loads(result.stdout)
            docker.update(daemon_reachable=True, architecture=info.get("Architecture"),
                          total_memory_bytes=info.get("MemTotal"))
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    cpuinfo = Path("/proc/cpuinfo")
    flags = set()
    if cpuinfo.is_file():
        for line in cpuinfo.read_text().splitlines():
            if line.startswith("flags") and ":" in line:
                flags.update(line.split(":", 1)[1].split())
                break
    memory = memory_limits()
    return {"schema_version": "1.0.0", "kind": "canonical_host_capability_observation",
            "observed_at": datetime.now(timezone.utc).isoformat(), "canonical_ready": False,
            "system": platform.system(), "architecture": platform.machine(), "logical_cpus": os.cpu_count(),
            "memory": memory, "cpu_features": {name: name in flags for name in ("sse4_1", "sse4_2", "avx")},
            "docker": docker, "scratch_free_bytes": shutil.disk_usage(local).free,
            "drive_filesystem_reported_free_bytes": shutil.disk_usage(drive).free,
            "drive_quota_verified": False, "index_build_documentation_estimate_bytes": INDEX_ESTIMATE_BYTES,
            "index_estimate_is_measured_rss": False,
            "index_estimate_fits_memory_before_headroom": (memory["effective_ceiling_bytes"] > INDEX_ESTIMATE_BYTES
                if memory["effective_ceiling_bytes"] is not None else None),
            "durable_layout": {"source_cache": "cache/verified-sources/",
                "reference_indexes": "cache/reference-assets/sha256/<reference-id>/<index-manifest-id>/",
                "validated_results": "runs/<run-id>/", "registries": "registry/runs/<run-id>/"},
            "required_before_execution": ["qualify actual pinned containers and isolation", "validate approved domain implementation",
                "verify independent BQSR resources", "rehash hydrated sources", "verify reusable index or qualify index build",
                "resolve M4 native synthetic acceptance failure"],
            "publication_rule": "Stage locally; rehash durable destination; validate inventory and registry; completion marker last. Never publish Nextflow work."}


def main() -> None:
    """Write one immutable local observation and print only safe host metadata."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drive-root", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, default=Path("/content"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()
    identity = verify_install(args.source_root, args.expected_sha)
    result = probe(args.drive_root, args.scratch)
    result["runtime_identity"] = identity
    _write(args.output, (json.dumps(result, indent=2, sort_keys=True) + "\n").encode())
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
