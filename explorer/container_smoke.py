#!/usr/bin/env python3
"""Check a running default Explorer image using its public HTTP contract."""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request


def check(base: str) -> None:
    """Default synthetic service must not imply a canonical run occurred."""
    prefix = base.rstrip('/') + '/research/giab-wes-nextflow/explorer/'
    for endpoint in ('healthz', 'readyz', 'evidence.json'):
        with urllib.request.urlopen(prefix + endpoint, timeout=5) as response:
            assert response.status == 200, endpoint
            payload = json.load(response)
            if endpoint == 'readyz':
                assert payload['canonical'] is False
                assert payload['status'] == 'synthetic_prototype_ready'
    try:
        urllib.request.urlopen(prefix + 'canonical/readyz', timeout=5)
    except urllib.error.HTTPError as error:
        assert error.code == 503
        assert json.load(error)['canonical'] is False
    else:
        raise AssertionError('default image unexpectedly claims canonical readiness')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8050')
    args = parser.parse_args()
    for attempt in range(30):
        try:
            check(args.base_url)
            print('Explorer health/evidence passed; canonical correctly unavailable')
            return
        except (urllib.error.URLError, TimeoutError):
            if attempt == 29:
                raise
            time.sleep(1)


if __name__ == '__main__':
    main()
