"""Explicitly admit two installed invented recipes, never user-defined factories."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from .m3_fixture import fixture_payloads as m3_payloads
from .m4_fixture import fixture_payloads as m4_payloads

FIXTURE_IDS = ("m3-preprocessing", "m4-snv-positive")


@dataclass(frozen=True)
class FixtureContract:
    """Bind a named package recipe to its complete sources and serialized manifest."""

    fixture_id: str
    payloads: dict[str, bytes]
    expectations: dict[str, Any]
    manifest_sha256: str


def fixture_contract(fixture_id: str) -> FixtureContract:
    """Resolve only literal installed factories with deterministic manifest hashes."""
    factories = {"m3-preprocessing": m3_payloads, "m4-snv-positive": m4_payloads}
    if fixture_id not in factories:
        raise ValueError("unknown or unapproved synthetic fixture ID")
    payloads, expected = factories[fixture_id]()
    manifest = (json.dumps(expected, sort_keys=True, indent=2) + "\n").encode()
    return FixtureContract(fixture_id, payloads, expected, hashlib.sha256(manifest).hexdigest())


def fixture_contract_from_manifest_sha256(value: str) -> FixtureContract:
    """Select a fixture from a persisted exact hash, never a shared reference hash."""
    for fixture_id in FIXTURE_IDS:
        contract = fixture_contract(fixture_id)
        if contract.manifest_sha256 == value:
            return contract
    raise ValueError("unregistered synthetic fixture manifest identity")
