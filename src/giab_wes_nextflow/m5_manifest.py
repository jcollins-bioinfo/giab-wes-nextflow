"""Reject duplicate manifest keys before Nextflow resolves any scientific inputs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

FIELDS = {'synthetic', 'sample', 'domain_id', 'reference', 'fai', 'dictionary', 'truth', 'truth_index', 'confidence', 'domain', 'queries'}


def read_manifest(path: Path) -> dict[str, Any]:
    """Read one bounded JSON object, rejecting duplicate keys at every depth."""
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        """Preserve unambiguous values only, including inside query objects."""
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'duplicate manifest key: {key}')
            result[key] = value
        return result

    if path.stat().st_size > 1_000_000:
        raise ValueError('M5 manifest exceeds bounded metadata size')
    result = json.loads(path.read_text(), object_pairs_hook=unique,
                        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f'invalid JSON constant: {value}')))
    if not isinstance(result, dict):
        raise ValueError('M5 manifest must be an object')
    return result


def main(argv: list[str] | None = None) -> int:
    """Emit canonical JSON from the validated read, avoiding a second file read."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(read_manifest(args.manifest), sort_keys=True, allow_nan=False))
    except (ValueError, OSError) as error:
        parser.error(str(error))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
