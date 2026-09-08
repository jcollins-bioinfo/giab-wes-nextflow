"""Stream complete reference identity and audited no-alt BQSR derivatives.

Whole-reference base identity is distinct from sampled executable qualification.
No genomic bytes are returned in public metadata. Active files remain on /content.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any, Callable

from .acquisition import checksum, destination, safe_root, validate_source_bytes, write_record
from .resources import config_path

Runner = Callable[[str, list[str], Path], str]


def active(path: str | Path) -> Path:
    """Reject Drive and off-Colab active paths before opening or creating files."""
    root = safe_root(path, allow_test_root=True)
    if not root.is_relative_to('/content') or root.is_relative_to('/content/drive'):
        raise ValueError('canonical active assets must remain under /content outside Drive')
    return root


def regular(path: str | Path) -> Path:
    """Read only guarded regular files without following user symlinks."""
    path = Path(path)
    path = destination(path.parent, path.name)
    if not path.is_file():
        raise ValueError('missing regular asset input')
    return path


def identity(path: Path) -> dict[str, Any]:
    """Describe a complete file with a basename, byte length and SHA-256."""
    path = regular(path)
    return {'filename': path.name, 'bytes': path.stat().st_size, 'sha256': checksum(path)}


def digest_json(value: Any) -> str:
    """Hash canonical JSON, independent of presentation and filesystem paths."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def load_assets() -> dict[str, Any]:
    """Read the installed immutable source/tool contract."""
    return json.loads(config_path('canonical-assets.json').read_text())


def scan_reference(path: Path) -> list[dict[str, Any]]:
    """Compute every contig MD5 and physical FAI offset with constant sequence memory.

    Sequence lines must use a uniform width except the final line of a contig.
    MD5 follows SAM dictionary rules: uppercase sequence excluding whitespace.
    """
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    current: dict[str, Any] | None = None
    md5 = hashlib.md5()
    previous_width = 0
    with regular(path).open('rb') as stream:
        while line := stream.readline():
            if line.startswith(b'>'):
                if current is not None:
                    if current['length'] <= 0:
                        raise ValueError('empty reference contig')
                    current['md5'] = md5.hexdigest()
                    rows.append(current)
                name = line[1:].split()[0].decode('ascii')
                if not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or name in seen:
                    raise ValueError('invalid or repeated reference contig')
                seen.add(name)
                current = {'name': name, 'length': 0, 'offset': stream.tell(), 'line_bases': 0, 'line_bytes': 0}
                md5 = hashlib.md5()
                previous_width = 0
                continue
            bases = line.rstrip(b'\r\n')
            if current is None or not bases or re.fullmatch(b'[ACGTRYSWKMBDHVNacgtryswkmbdhvn]+', bases) is None:
                raise ValueError('malformed reference sequence line')
            if current['line_bases'] == 0:
                current['line_bases'], current['line_bytes'] = len(bases), len(line)
            elif previous_width != current['line_bases'] or len(bases) > current['line_bases']:
                raise ValueError('reference FASTA wrapping cannot be represented by FAI')
            elif len(bases) == current['line_bases'] and len(line) != current['line_bytes']:
                raise ValueError('inconsistent reference line endings')
            previous_width = len(bases)
            current['length'] += len(bases)
            md5.update(bases.upper())
    if current is None or current['length'] <= 0:
        raise ValueError('empty reference')
    current['md5'] = md5.hexdigest()
    rows.append(current)
    return rows


def prepare_reference(source_gz: Path, authenticated_fai: Path, output: Path) -> dict[str, Any]:
    """Authenticate compressed source, stream all bases, and write exact derivatives."""
    spec = load_assets()
    m2 = json.loads(config_path('m2-resources.json').read_text())['resources']
    pins = {item['id']: item for item in m2}
    validate_source_bytes(regular(source_gz), pins['grch38_no_alt_fasta_gz'])
    validate_source_bytes(regular(authenticated_fai), pins['grch38_compressed_fai'])
    output = active(output)
    output.mkdir(parents=True, exist_ok=True)
    final = destination(output, 'reference.fa')
    if not final.exists():
        partial = destination(output, 'reference.fa.incomplete')
        with gzip.open(source_gz, 'rb') as source, partial.open('wb') as target:
            shutil.copyfileobj(source, target, 8 << 20)
            target.flush()
            os.fsync(target.fileno())
        os.replace(partial, final)
    rows = scan_reference(final)
    full = [{'name': row['name'], 'length': row['length'], 'md5': row['md5']} for row in rows]
    if full != spec['reference_dictionary']:
        raise ValueError('complete reference per-contig base identity differs from pinned dictionary')
    upstream = [(parts[0], int(parts[1])) for line in regular(authenticated_fai).read_text().splitlines()
                if (parts := line.split('\t'))]
    if upstream != [(r['name'], r['length']) for r in rows]:
        raise ValueError('authenticated FAI order/length identity differs')
    fai = ''.join(f"{r['name']}\t{r['length']}\t{r['offset']}\t{r['line_bases']}\t{r['line_bytes']}\n" for r in rows)
    dictionary = '@HD\tVN:1.6\tSO:unsorted\n' + ''.join(f"@SQ\tSN:{r['name']}\tLN:{r['length']}\tM5:{r['md5']}\n" for r in rows)
    for name, text in [('reference.fa.fai', fai), ('reference.dict', dictionary)]:
        target = destination(output, name)
        if target.exists() and target.read_text() != text:
            raise ValueError('existing reference derivative conflicts')
        partial = destination(output, name + '.incomplete')
        with partial.open('w') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(partial, target)
    record = {'schema_version': '1.0.0', 'kind': 'canonical_reference_asset', 'status': 'base_identity_verified',
              'source': identity(source_gz), 'upstream_fai': identity(authenticated_fai), 'contigs': full,
              'reference_id': digest_json(full), 'files': [identity(output / n) for n in ('reference.fa', 'reference.fa.fai', 'reference.dict')],
              'complete_base_identity': True, 'functional_index_qualified': False}
    write_record(output / 'reference-manifest.json', record)
    return record


def validate_reference(directory: Path) -> dict[str, Any]:
    """Rehash every derivative and repeat complete base identity before reference reuse."""
    directory = active(directory)
    record = json.loads(regular(directory / 'reference-manifest.json').read_text())
    rows = scan_reference(directory / 'reference.fa')
    full = [{k: r[k] for k in ('name', 'length', 'md5')} for r in rows]
    if record.get('kind') != 'canonical_reference_asset' or full != load_assets()['reference_dictionary'] or record.get('contigs') != full:
        raise ValueError('reference manifest or full base identity mismatch')
    if record.get('reference_id') != digest_json(full) or record.get('files') != [identity(directory / n) for n in ('reference.fa', 'reference.fa.fai', 'reference.dict')]:
        raise ValueError('reference derivative bytes changed')
    wanted_fai = ''.join(f"{r['name']}\t{r['length']}\t{r['offset']}\t{r['line_bases']}\t{r['line_bytes']}\n" for r in rows)
    wanted_dict = '@HD\tVN:1.6\tSO:unsorted\n' + ''.join(f"@SQ\tSN:{r['name']}\tLN:{r['length']}\tM5:{r['md5']}\n" for r in rows)
    if (directory / 'reference.fa.fai').read_text() != wanted_fai or (directory / 'reference.dict').read_text() != wanted_dict:
        raise ValueError('reference FAI/dictionary do not describe actual FASTA')
    return record


def reference_slice(stream: Any, row: dict[str, Any], start: int, length: int) -> str:
    """Fetch a bounded zero-based reference slice across physical FASTA line breaks."""
    if not 0 <= start < start + length <= row['length']:
        raise ValueError('reference allele coordinates outside contig')
    offset = row['offset'] + start // row['line_bases'] * row['line_bytes'] + start % row['line_bases']
    stream.seek(offset)
    result = bytearray()
    while len(result) < length:
        block = stream.read(min(1 << 20, length - len(result)))
        if not block:
            raise ValueError('truncated reference')
        result.extend(block.replace(b'\n', b'').replace(b'\r', b''))
    return bytes(result).decode().upper()


def prepare_known_sites(sources: dict[str, Path], reference_dir: Path, output: Path, runner: Runner) -> dict[str, Any]:
    """Audit every retained BQSR REF allele and explicitly remove only absent no-alt contigs.

    Original Broad files/TBIs are authenticated and retained externally. All VCF
    records are parsed; absent-reference records are counted, never silently
    renamed. Newly compressed derivatives receive new indexes and byte hashes.
    """
    reference = validate_reference(reference_dir)
    rows = {r['name']: r for r in scan_reference(reference_dir / 'reference.fa')}
    spec = load_assets()['known_sites']
    if set(sources) != {r['id'] for r in spec}:
        raise ValueError('BQSR source inventory differs from independent pinned resources')
    for item in spec:
        validate_source_bytes(regular(sources[item['id']]), item)
    output = active(output)
    output.mkdir(parents=True, exist_ok=True)
    completed = output / 'known-sites-manifest.json'
    if completed.exists():
        from .canonical_assets import validate_asset
        prior = validate_asset(output, 'canonical_bqsr_asset')
        if prior['reference_id'] != reference['reference_id'] or any(a['source'] != identity(sources[a['source_id']]) for a in prior['audits']):
            raise ValueError('known-sites reuse lineage mismatch')
        return prior
    if shutil.disk_usage(output).free < 20 * 1024 ** 3:
        raise ValueError('BQSR derivative preparation requires >=20GiB free scratch')
    audits = []
    for item in spec:
        if item['role'] != 'bqsr_known_sites':
            continue
        target = destination(output, item['id'] + '.no-alt.vcf')
        kept = removed = 0
        declared: dict[str, int] = {}
        previous = (-1, -1)
        order = {name: i for i, name in enumerate(rows)}
        with gzip.open(sources[item['id']], 'rt') as source, target.open('w') as out, (reference_dir / 'reference.fa').open('rb') as fasta:
            header_seen = False
            for line in source:
                if line.startswith('##contig='):
                    match = re.search(r'ID=([^,>]+),length=([0-9]+)', line)
                    if not match or match[1] in declared:
                        raise ValueError('ambiguous known-sites contig dictionary')
                    name, length = match[1], int(match[2])
                    declared[name] = length
                    if name in rows and rows[name]['length'] != length:
                        raise ValueError('known-sites/reference contig length mismatch')
                    continue
                if line.startswith('#CHROM'):
                    for row in rows.values():
                        out.write(f"##contig=<ID={row['name']},length={row['length']}>\n")
                    header_seen = True
                    out.write(line)
                    continue
                if line.startswith('#'):
                    out.write(line)
                    continue
                fields = line.rstrip('\n').split('\t')
                if not header_seen or len(fields) < 8 or not fields[1].isdigit() or not re.fullmatch('[ACGTNacgtn]+', fields[3]):
                    raise ValueError('invalid known-sites VCF record')
                name, position, ref = fields[0], int(fields[1]), fields[3].upper()
                if name not in declared or not 0 < position <= declared[name] or position + len(ref) - 1 > declared[name]:
                    raise ValueError('known-sites record outside declared source dictionary')
                if name not in rows:
                    removed += 1
                    continue
                key = (order[name], position)
                if key < previous or reference_slice(fasta, rows[name], position - 1, len(ref)) != ref:
                    raise ValueError('known-sites retained REF/order mismatch')
                previous = key
                kept += 1
                out.write(line)
        if kept == 0:
            raise ValueError('known-sites derivative is empty')
        compressed = target.with_suffix(target.suffix + '.gz')
        runner('bcftools', ['view', '-Oz', '-o', compressed.name, target.name], output)
        runner('bcftools', ['index', '--tbi', '--force', compressed.name], output)
        count = runner('bcftools', ['index', '--nrecords', compressed.name], output).strip()
        if not count.isdigit() or int(count) != kept:
            raise ValueError('known-sites derivative index record count mismatch')
        audits.append({'source_id': item['id'], 'source': identity(sources[item['id']]), 'retained_records': kept,
                       'excluded_absent_reference_records': removed, 'retained_ref_alleles_verified': True,
                       'files': [identity(compressed), identity(Path(str(compressed) + '.tbi'))]})
        target.unlink()
    record = {'schema_version': '1.0.0', 'kind': 'canonical_bqsr_asset', 'reference_id': reference['reference_id'],
              'source_contract_sha256': digest_json(spec), 'benchmark_truth_used': False, 'audits': audits,
              'files': [f for a in audits for f in a['files']]}
    write_record(output / 'known-sites-manifest.json', record)
    return record
