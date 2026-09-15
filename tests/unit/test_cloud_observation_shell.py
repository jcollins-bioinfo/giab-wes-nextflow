"""Execute the native inventory producer, including failed measurement commands."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import textwrap

import pytest

from giab_wes_nextflow.cloud_observations import read_file_inventory


def helper():
    source = (Path(__file__).resolve().parents[2] / 'modules/local/cloud/tasks.nf').read_text()
    block = re.search(r'(?ms)^    observe_files\(\) \{\n.*?^    \}\n', source)
    assert block is not None
    # Decode the two escapes used in this static Groovy string fragment.
    return textwrap.dedent(block[0]).replace(r'\$', '$').replace('\\\\', '\\')


def executable(path, body):
    path.write_text(body)
    path.chmod(0o755)


def environment(tmp_path):
    tools = tmp_path / 'tools'; tools.mkdir()
    executable(tools / 'sha256sum', f'#!{sys.executable}\nimport hashlib,sys\nfrom pathlib import Path\nprint(hashlib.sha256(Path(sys.argv[-1]).read_bytes()).hexdigest()+"  "+sys.argv[-1])\n')
    # A command that is absent in the BWA image must never be needed here.
    executable(tools / 'stat', '#!/bin/sh\necho unexpected-stat >&2\nexit 127\n')
    return tools, {**os.environ, 'PATH': str(tools) + os.pathsep + os.environ['PATH']}


def run_inventory(tmp_path, env, targets='data'):
    return subprocess.run(['bash', '-c', 'set -euo pipefail\n' + helper() +
                           '\nobserve_files ' + targets + ' > inventory.tsv\necho reached > after.txt\n'],
                          cwd=tmp_path, env=env, capture_output=True, text=True)


def test_inventory_without_stat_hashes_actual_bytes_and_empty_files(tmp_path):
    _, env = environment(tmp_path)
    data = tmp_path / 'data'; data.mkdir()
    contents = {'binary.bin': bytes(range(256)), 'empty': b'', 'lines.txt': b'one\ntwo\n'}
    for name, value in contents.items(): (data / name).write_bytes(value)
    result = run_inventory(tmp_path, env)
    assert result.returncode == 0, result.stderr
    assert 'unexpected-stat' not in result.stderr
    assert read_file_inventory(tmp_path / 'inventory.tsv') == {
        'data/' + name: {'bytes': len(value), 'sha256': hashlib.sha256(value).hexdigest()}
        for name, value in contents.items()}


@pytest.mark.parametrize('command,body', [
    ('wc', 'exit 127'),
    ('wc', 'printf "17\\n"; exit 2'),
    ('wc', 'printf "invalid\\n"'),
    ('sha256sum', 'exit 2'),
])
def test_failed_or_invalid_measurement_stops_before_completion(tmp_path, command, body):
    tools, env = environment(tmp_path)
    (tmp_path / 'data').write_bytes(b'actual bytes')
    executable(tools / command, '#!/bin/sh\n' + body + '\n')
    result = run_inventory(tmp_path, env)
    assert result.returncode != 0
    assert not (tmp_path / 'after.txt').exists()
    assert (tmp_path / 'inventory.tsv').read_text() == ''


def test_byte_count_padding_is_removed(tmp_path):
    tools, env = environment(tmp_path)
    (tmp_path / 'data').write_bytes(b'abc')
    executable(tools / 'wc', '#!/bin/sh\ncat >/dev/null\nprintf "       3\\n"\n')
    result = run_inventory(tmp_path, env)
    assert result.returncode == 0, result.stderr
    assert read_file_inventory(tmp_path / 'inventory.tsv')['data']['bytes'] == 3


def test_missing_artifact_stops_before_completion(tmp_path):
    _, env = environment(tmp_path)
    result = run_inventory(tmp_path, env, 'missing')
    assert result.returncode != 0
    assert not (tmp_path / 'after.txt').exists()


def test_historical_empty_byte_count_remains_invalid(tmp_path):
    path = tmp_path / 'inputs.tsv'
    path.write_text('a' * 64 + '\t\taligned.sam\n')
    with pytest.raises(ValueError, match='invalid native whole-file identity'):
        read_file_inventory(path)
