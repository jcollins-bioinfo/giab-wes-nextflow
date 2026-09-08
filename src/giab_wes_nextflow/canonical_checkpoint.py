"""Restart-safe private completed-stage publication; never persist Nextflow work."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
from typing import Any

from .acquisition import checksum, destination, safe_root, validate_run_id
from .canonical_science import file_id, write_json
from .m5 import require


def inventory(root: Path) -> dict[str, Any]:
    """Hash exact regular-file inventory, rejecting linked or partial artifacts."""
    files = {}
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink(), "linked completed-stage artifact")
        if path.is_file():
            require(not path.name.endswith((".part", ".incomplete")), "partial completed-stage artifact")
            if path.name != "stage-complete.json":
                files[path.relative_to(root).as_posix()] = file_id(path)
    require(bool(files), "empty completed stage")
    return files


def completed(root: Path, key: str) -> dict[str, Any]:
    """Rehash every byte before considering a completed stage reusable."""
    marker = destination(root, "stage-complete.json")
    record = json.loads(marker.read_text())
    require(record.get("kind") == "canonical_completed_stage" and record.get("key") == key, "checkpoint identity mismatch")
    require(record["files"] == inventory(root), "checkpoint inventory or byte mismatch")
    return record


def publish(source: Path, drive: Path, run_id: str, stage: str, key: str) -> Path:
    """Copy and rehash selected completed output; write marker last on Drive."""
    drive = safe_root(drive); validate_run_id(run_id); validate_run_id(stage)
    require(str(drive) == "/content/drive/MyDrive/giab-wes-nextflow-private", "canonical Drive root mismatch")
    target = destination(drive, f"runs/{run_id}/completed-stages/{stage}")
    files = inventory(source)
    if (target / "stage-complete.json").exists():
        require(completed(target, key)["files"] == files, "immutable completed-stage conflict")
        return target
    target.mkdir(parents=True, exist_ok=True)
    require(shutil.disk_usage(drive).free > sum(x["bytes"] for x in files.values()) + 1024**3, "insufficient durable free space")
    for name, expected in files.items():
        final = destination(target, name); final.parent.mkdir(parents=True, exist_ok=True)
        if final.exists() and file_id(final) == expected:
            continue
        partial = final.with_name(final.name + ".incomplete")
        shutil.copyfile(source / name, partial)
        require(file_id(partial) == expected, "durable copy verification failed")
        os.replace(partial, final)
    require(inventory(target) == files, "durable inventory mismatch")
    write_json(target / "stage-complete.json", {"kind": "canonical_completed_stage", "key": key, "files": files})
    completed(target, key)
    return target


def hydrate(source: Path, target: Path, key: str) -> dict[str, Any]:
    """Restore only complete outputs, verifying both durable and scratch bytes."""
    record = completed(source, key)
    target.mkdir(parents=True, exist_ok=True)
    for name, expected in record["files"].items():
        final = destination(target, name); final.parent.mkdir(parents=True, exist_ok=True)
        if final.exists():
            require(file_id(final) == expected, "scratch restart conflict")
        else:
            shutil.copyfile(source / name, final)
            require(file_id(final) == expected, "scratch hydration mismatch")
    require(inventory(target) == record["files"], "hydrated inventory mismatch")
    return {"status": "reused", "marker_sha256": checksum(source / "stage-complete.json"), "files": len(record["files"])}
