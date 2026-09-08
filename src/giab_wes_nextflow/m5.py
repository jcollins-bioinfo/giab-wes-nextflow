"""Common isolated normalization and authoritative RTG diploid benchmarking."""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any

from jsonschema import Draft202012Validator
from . import __version__
from .m4_contracts import load_json, validate_envelope as validate_m4
from .resources import config_path, schema_path


def require(ok: bool, message: str) -> None:
    """Enforce evidence contracts even with Python optimization enabled."""
    if not ok:
        raise ValueError(message)


def identity(path: Path) -> dict[str, Any]:
    """Hash a regular input without following linked ancestors."""
    p = path.absolute()
    require(not any(x.is_symlink() for x in (p, *p.parents)) and p.is_file(), "input must be an unlinked regular file")
    h = hashlib.sha256()
    with p.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return {'filename': p.name, 'bytes': p.stat().st_size, 'sha256': h.hexdigest()}


def payload_hash(record: dict[str, Any]) -> str:
    """Identify JSON independent of serialization whitespace."""
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def publish(kind: str, output: Path, data: dict[str, Any]) -> dict[str, Any]:
    """Validate and publish the completion record after all output checks."""
    record = {'schema_version': '1.0.0', 'kind': kind, 'package_version': __version__,
              'synthetic': True, 'canonical': False, **data}
    record['payload_sha256'] = payload_hash(record)
    validate_record(record, kind)
    (output / f'{kind}.json').write_text(json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + '\n')
    return record


def validate_record(record: dict[str, Any], kind: str) -> None:
    """Validate schema and self-independent result digest."""
    Draft202012Validator(load_json(schema_path(f'm5-{kind}.schema.json'))).validate(record)
    require(record['payload_sha256'] == payload_hash({k: v for k, v in record.items() if k != 'payload_sha256'}), 'M5 payload identity mismatch')
    lock = load_json(config_path('m5-tools.json'))['tools']
    for command in record['commands']:
        require(command['image'] == lock[command['tool']]['image'], 'command image differs from lock')
    tool = 'bcftools' if kind == 'normalization' else 'rtg'
    observed = record['tools'][tool]['observed_version']
    require(re.search(r'bcftools 1\.24(?:\s|$)' if tool == 'bcftools' else r'RTG Tools 3\.13(?:\s|$)', observed) is not None,
            'result observed version differs from lock')
    if kind == 'normalization':
        argv = [c['argv'] for c in record['commands']]
        require(['bcftools', 'norm', '-f', 'reference.fa', '-c', 'e', '-m', '-any', '--multi-overlaps', '0',
                 '--old-rec-tag', 'M5_ORIG', '--no-version', '-Ov', '-o', 'split.vcf', 'raw.vcf.gz'] in argv,
                'normalization command policy missing')
        require(['bcftools', 'index', '-t', 'normalized.vcf.gz'] in argv, 'normalization index command missing')
        require(all(record['outputs'][n]['bytes'] > 0 and record['outputs'][n]['filename'] == n for n in
                    ('normalized.vcf.gz', 'normalized.vcf.gz.tbi')), 'normalized output identity missing')
    if kind == 'benchmark':
        validate_record(record['truth_normalization'], 'normalization')
        evaluated = record['evaluated_bases'] > 0
        if evaluated:
            require(bool(record['reference_sdf']), 'reference SDF identity missing')
            require(all(n + '.vcf.gz' in record['outputs'] for n in ('tp', 'tp-baseline', 'fp', 'fn')),
                    'authoritative benchmark partitions missing')
            require(['vcfeval', '-b', 'truth.vcf.gz', '-c', 'query.vcf.gz', '-t', 'reference.sdf', '-o', 'vcfeval',
                     '--evaluation-regions', 'evaluation.bed', '--sample', record['sample'], '--all-records', '--ref-overlap',
                     '--output-mode', 'split', '--no-roc', '--sample-ploidy', '2', '--threads', '2'] in
                    [c['argv'] for c in record['commands']], 'benchmark command policy missing')
        require((record['status'] == 'evaluated') == evaluated and (record['interval_count'] > 0) == evaluated,
                'benchmark domain/status mismatch')
        for values in record['metrics'].values():
            expected = metrics(values['tp_query'], values['tp_truth'], values['fp'], values['fn'], evaluated=evaluated)
            require(values == expected, 'benchmark arithmetic or missingness mismatch')
            require(evaluated or all(values[k] == 0 for k in ('tp_query', 'tp_truth', 'fp', 'fn')),
                    'unevaluated domain cannot carry counts')


def reference(reference: Path, fai: Path, dictionary: Path) -> dict[str, str]:
    """Validate bounded synthetic FASTA against actual FAI bytes and dictionary."""
    for p in (reference, fai, dictionary):
        identity(p)
    require(reference.stat().st_size <= 64 * 1024 * 1024, 'M5 current execution envelope is bounded synthetic reference only')
    seqs: dict[str, str] = {}
    expected = []
    with reference.open('rb') as stream:
        name = None
        chunks: list[str] = []
        start = width = linebytes = 0
        short = False
        while line := stream.readline():
            if line.startswith(b'>'):
                if name is not None:
                    seqs[name] = ''.join(chunks)
                    expected.append([name, str(len(seqs[name])), str(start), str(width), str(linebytes)])
                name = line[1:].decode('ascii').strip().split()[0]
                require(name not in seqs and re.fullmatch(r'[A-Za-z0-9_.-]+', name) is not None, 'duplicate or invalid FASTA contig')
                chunks = []; start = stream.tell(); width = linebytes = 0; short = False
            else:
                bases = line.decode('ascii').rstrip('\n')
                require(name is not None and re.fullmatch('[ACGTN]+', bases) is not None and line.endswith(b'\n') and not short, 'malformed or truncated FASTA')
                if not width:
                    width, linebytes = len(bases), len(line)
                require(len(bases) <= width, 'inconsistent FASTA wrapping')
                short = len(bases) < width
                chunks.append(bases)
        require(name is not None and bool(chunks), 'empty FASTA')
        seqs[name] = ''.join(chunks)
        expected.append([name, str(len(seqs[name])), str(start), str(width), str(linebytes)])
    require([x.split('\t') for x in fai.read_text().splitlines()] == expected, 'FAI offsets/order/length mismatch')
    rows = [dict(x.split(':', 1) for x in line.split('\t')[1:]) for line in dictionary.read_text().splitlines() if line.startswith('@SQ\t')]
    require([(x['SN'], int(x['LN'])) for x in rows] == [(k, len(v)) for k, v in seqs.items()], 'dictionary order/length mismatch')
    for row in rows:
        require('M5' not in row or row['M5'].lower() == hashlib.md5(seqs[row['SN']].encode()).hexdigest(), 'dictionary MD5 mismatch')
    return seqs


def vcf_rows(path: Path, seqs: dict[str, str], sample: str, *, split: bool = False) -> tuple[list[str], list[list[str]]]:
    """Validate exact reference, sample, genotype indexes and ordered unique alleles."""
    identity(path)
    opener = gzip.open if path.name.endswith('.gz') else open
    headers: list[str] = []; rows: list[list[str]] = []; contigs = []; seen = set(); prior = (-1, 0); columns = False
    with opener(path, 'rt', encoding='ascii') as stream:
        for line in stream:
            require(line.endswith('\n'), 'truncated VCF')
            if line.startswith('#'):
                require(not rows, 'VCF header after records')
                headers.append(line)
                if line.startswith('##contig='):
                    match = re.search(r'ID=([^,>]+),length=(\d+)', line)
                    require(match is not None, 'invalid contig header')
                    contigs.append((match[1], int(match[2])))
                if line.startswith('#CHROM\t'):
                    require(not columns and line.rstrip().split('\t')[9:] == [sample], 'sample mismatch')
                    columns = True
                continue
            f = line.rstrip('\n').split('\t')
            require(columns and len(f) == 10 and f[0] in seqs, 'malformed VCF or unknown contig')
            pos = int(f[1]); key = (list(seqs).index(f[0]), pos)
            require(key >= prior and pos >= 1, 'VCF order/coordinate mismatch'); prior = key
            require(re.fullmatch('[ACGT]+', f[3]) is not None and seqs[f[0]][pos-1:pos-1+len(f[3])] == f[3], 'VCF REF mismatch')
            alts = f[4].split(',')
            require(all(re.fullmatch('[ACGT]+', a) and a != f[3] for a in alts) and len(set(alts)) == len(alts), 'ambiguous or symbolic ALT')
            require(not split or len(alts) == 1, 'normalization did not split alleles')
            for alt in alts:
                allele = (f[0], pos, f[3], alt)
                require(allele not in seen, 'duplicate allele conflict'); seen.add(allele)
            fmt = f[8].split(':'); values = f[9].split(':')
            require(len(fmt) == len(set(fmt)) and 'GT' in fmt and len(values) <= len(fmt), 'invalid FORMAT/GT')
            gt = values[fmt.index('GT')] if fmt.index('GT') < len(values) else '.'
            require(re.fullmatch(r'(?:\d+|\.)(?:[/|](?:\d+|\.))*', gt) is not None, 'malformed genotype')
            require(all(a == '.' or int(a) <= len(alts) for a in re.split(r'[/|]', gt)), 'genotype allele index out of range')
            rows.append(f)
    require(columns and contigs == [(k, len(v)) for k, v in seqs.items()], 'VCF contig dictionary mismatch')
    return headers, rows


def selected(rows: list[list[str]]) -> tuple[list[list[str]], dict[str, int]]:
    """Apply the same fully called diploid nonreference policy to either caller."""
    result = []; excluded: Counter[str] = Counter()
    for f in rows:
        values = f[9].split(':'); index = f[8].split(':').index('GT'); gt = values[index] if index < len(values) else '.'
        alleles = re.split(r'[/|]', gt)
        reason = 'missing_genotype' if '.' in alleles else 'non_diploid' if len(alleles) != 2 else 'reference_genotype' if all(int(a) == 0 for a in alleles) else None
        if reason:
            excluded[reason] += 1
        else:
            result.append(f)
    return result, dict(excluded)


class Runtime:
    """Execute tools in a sole task mount with no network or ambient repository."""
    def __init__(self, root: Path) -> None:
        """Initialize the package-owned lock and a sole mount root."""
        self.root = root.resolve(); self.commands: list[dict[str, Any]] = []
        self.tools = load_json(config_path('m5-tools.json'))['tools']

    def run(self, tool: str, args: list[str]) -> str:
        """Run a pinned tool and retain portable command and output identities."""
        entry = self.tools[tool]
        cmd = ['docker', 'run', '--rm', '--network', 'none', '--platform', 'linux/amd64', '--user', f'{os.getuid()}:{os.getgid()}', '-e', 'RTG_MEM=2G', '-v', f'{self.root}:/task', '-w', '/task', entry['image']]
        actual = (['bcftools'] if tool == 'bcftools' else []) + args
        result = subprocess.run(cmd + actual, capture_output=True, text=True, timeout=900, check=False)
        self.commands.append({'tool': tool, 'image': entry['image'], 'argv': actual,
                              'exit_code': result.returncode, 'stdout_sha256': hashlib.sha256(result.stdout.encode()).hexdigest(),
                              'stderr_sha256': hashlib.sha256(result.stderr.encode()).hexdigest(), 'network': 'none', 'mounts': ['task']})
        require(result.returncode == 0, f'{tool} failed: exit {result.returncode}; {result.stderr[-1000:]}')
        return result.stdout

    def version(self, tool: str) -> str:
        """Require an actual executable version matching the declared distribution."""
        result = self.run(tool, ['--version'] if tool == 'bcftools' else ['version'])
        pattern = r'bcftools 1\.24(?:\s|$)' if tool == 'bcftools' else r'RTG Tools 3\.13(?:\s|$)'
        require(re.search(pattern, result) is not None, f'{tool} version mismatch')
        return result.strip()


def index_check(runtime: Runtime, filename: str, seqs: dict[str, str]) -> None:
    """Compare complete sequential VCF records to independent indexed retrieval."""
    sequential = runtime.run('bcftools', ['view', '-H', filename])
    indexed = runtime.run('bcftools', ['view', '-H', '-r', ','.join(f'{c}:1-{len(s)}' for c, s in seqs.items()), filename])
    require(sequential == indexed, 'VCF index differs from sequential records')


def normalize(vcf: Path, index: Path, reference_path: Path, fai: Path, dictionary: Path,
              sample: str, caller: str, output: Path, native_contract: Path | None = None) -> dict[str, Any]:
    """Normalize one copied query without truth, evaluation domains or oracle access."""
    require(caller in ('gatk', 'deepvariant', 'truth'), 'invalid caller')
    require(not output.exists(), 'output directory must be new')
    seqs = reference(reference_path, fai, dictionary)
    vcf_rows(vcf, seqs, sample)
    inputs = {k: identity(p) for k, p in [('raw_vcf', vcf), ('raw_index', index), ('reference', reference_path), ('fai', fai), ('dictionary', dictionary)]}
    native = None
    if native_contract:
        record = load_json(native_contract); validate_m4(record); d = record['data']
        require(d['caller'] == caller and d['sample'] == sample and d['outputs']['vcf']['sha256'] == inputs['raw_vcf']['sha256'] and d['outputs']['vcf_index']['sha256'] == inputs['raw_index']['sha256'], 'M4 native lineage mismatch')
        native = identity(native_contract)
    with tempfile.TemporaryDirectory(prefix='m5-normalize-') as tmp:
        task = Path(tmp).resolve()
        for src, name in [(vcf, 'raw.vcf.gz'), (index, 'raw.vcf.gz.tbi'), (reference_path, 'reference.fa'), (fai, 'reference.fa.fai'), (dictionary, 'reference.dict')]:
            shutil.copyfile(src, task / name)
        runtime = Runtime(task); version = runtime.version('bcftools'); index_check(runtime, 'raw.vcf.gz', seqs)
        runtime.run('bcftools', ['norm', '-f', 'reference.fa', '-c', 'e', '-m', '-any', '--multi-overlaps', '0', '--old-rec-tag', 'M5_ORIG', '--no-version', '-Ov', '-o', 'split.vcf', 'raw.vcf.gz'])
        runtime.run('bcftools', ['sort', '-Ov', '-o', 'sorted.vcf', 'split.vcf'])
        headers, rows = vcf_rows(task / 'sorted.vcf', seqs, sample, split=True)
        rows, excluded = selected(rows)
        (task / 'included.vcf').write_text(''.join(headers) + ''.join('\t'.join(f) + '\n' for f in rows))
        runtime.run('bcftools', ['view', '--no-version', '-Oz', '-o', 'normalized.vcf.gz', 'included.vcf'])
        runtime.run('bcftools', ['index', '-t', 'normalized.vcf.gz'])
        vcf_rows(task / 'normalized.vcf.gz', seqs, sample, split=True); index_check(runtime, 'normalized.vcf.gz', seqs)
        output.mkdir(parents=True)
        for name in ('normalized.vcf.gz', 'normalized.vcf.gz.tbi'):
            shutil.copyfile(task / name, output / name)
        return publish('normalization', output, {'caller': caller, 'sample': sample, 'inputs': inputs,
                       'native_contract': native, 'outputs': {n: identity(output / n) for n in ('normalized.vcf.gz', 'normalized.vcf.gz.tbi')},
                       'record_count': len(rows), 'excluded_records': excluded, 'commands': runtime.commands,
                       'tools': {'bcftools': {'declared': runtime.tools['bcftools'], 'observed_version': version}},
                       'warnings': ['Synthetic execution envelope only; native FILTER retained and not used for inclusion.']})


def intervals(path: Path, seqs: dict[str, str]) -> list[tuple[str, int, int]]:
    """Require exact sorted disjoint half-open BED without data-dependent selection."""
    identity(path); result = []; prior = (-1, -1)
    for line in path.read_text().splitlines():
        f = line.split('\t'); require(len(f) == 3 and f[0] in seqs, 'malformed BED')
        start, end = int(f[1]), int(f[2]); idx = list(seqs).index(f[0])
        require(0 <= start < end <= len(seqs[f[0]]) and (idx > prior[0] or idx == prior[0] and start >= prior[1]), 'BED overlap/order/bounds mismatch')
        result.append((f[0], start, end)); prior = (idx, end)
    return result


def intersect(a: list[tuple[str, int, int]], b: list[tuple[str, int, int]], seqs: dict[str, str]) -> list[tuple[str, int, int]]:
    """Intersect two validated domains deterministically, merging adjacent results."""
    result: list[tuple[str, int, int]] = []
    for c in seqs:
        left = [(s, e) for name, s, e in a if name == c]; right = [(s, e) for name, s, e in b if name == c]; j = 0
        for start, end in left:
            while j < len(right) and right[j][1] <= start:
                j += 1
            k = j
            while k < len(right) and right[k][0] < end:
                s, e = max(start, right[k][0]), min(end, right[k][1])
                if s < e:
                    if result and result[-1][0] == c and result[-1][2] == s:
                        result[-1] = (c, result[-1][1], e)
                    else:
                        result.append((c, s, e))
                k += 1
    return result


def metrics(tp_query: int, tp_truth: int, fp: int, fn: int, *, evaluated: bool = True) -> dict[str, Any]:
    """Derive nullable metrics with distinct query and truth TP denominators."""
    require(all(type(x) is int and x >= 0 for x in (tp_query, tp_truth, fp, fn)), 'invalid benchmark counts')
    precision = tp_query / (tp_query + fp) if evaluated and tp_query + fp else None
    recall = tp_truth / (tp_truth + fn) if evaluated and tp_truth + fn else None
    f1 = None if precision is None or recall is None else 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {'tp_query': tp_query, 'tp_truth': tp_truth, 'fp': fp, 'fn': fn, 'precision': precision, 'recall': recall, 'f1': f1,
            'missing_reasons': {k: 'empty_domain' if not evaluated else 'zero_query_denominator' if k == 'precision' else 'zero_truth_denominator' if k == 'recall' else 'undefined_precision_or_recall' for k, v in [('precision', precision), ('recall', recall), ('f1', f1)] if v is None}}


def partition_counts(path: Path, seqs: dict[str, str], sample: str) -> Counter[str]:
    """Count authoritative RTG-assigned records by representation, without matching."""
    _, rows = vcf_rows(path, seqs, sample, split=True)
    return Counter('SNP' if len(f[3]) == len(f[4]) == 1 else 'INDEL' if len(f[3]) != len(f[4]) else 'OTHER' for f in rows)


def benchmark(normalized: Path, truth: Path, truth_index: Path, confidence: Path, domain: Path,
              reference_path: Path, fai: Path, dictionary: Path, sample: str, caller: str,
              domain_id: str, output: Path) -> dict[str, Any]:
    """Benchmark common normalized calls against downstream-only preserved truth."""
    require(caller in ('gatk', 'deepvariant') and re.fullmatch('[A-Za-z0-9_.-]+', domain_id) is not None, 'invalid benchmark identity')
    require(not output.exists(), 'output directory must be new')
    seqs = reference(reference_path, fai, dictionary); norm = load_json(normalized / 'normalization.json'); validate_record(norm, 'normalization')
    require(norm['caller'] == caller and norm['sample'] == sample and norm['inputs']['reference']['sha256'] == identity(reference_path)['sha256'], 'normalization lineage mismatch')
    for name in ('normalized.vcf.gz', 'normalized.vcf.gz.tbi'):
        require(identity(normalized / name) == norm['outputs'][name], 'normalized output identity mismatch')
    vcf_rows(normalized / 'normalized.vcf.gz', seqs, sample, split=True)
    region = intersect(intervals(domain, seqs), intervals(confidence, seqs), seqs)
    inputs = {k: identity(p) for k, p in [('truth', truth), ('truth_index', truth_index), ('confidence', confidence), ('domain', domain), ('reference', reference_path), ('normalization', normalized / 'normalization.json')]}
    with tempfile.TemporaryDirectory(prefix='m5-benchmark-') as tmp:
        task = Path(tmp).resolve()
        truth_norm = normalize(truth, truth_index, reference_path, fai, dictionary, sample, 'truth', task / 'truth-normalized')
        for src, name in [(normalized / 'normalized.vcf.gz', 'query.vcf.gz'), (normalized / 'normalized.vcf.gz.tbi', 'query.vcf.gz.tbi'), (task / 'truth-normalized/normalized.vcf.gz', 'truth.vcf.gz'), (task / 'truth-normalized/normalized.vcf.gz.tbi', 'truth.vcf.gz.tbi'), (reference_path, 'reference.fa')]:
            shutil.copyfile(src, task / name)
        (task / 'evaluation.bed').write_text(''.join(f'{c}\t{s}\t{e}\n' for c, s, e in region))
        runtime = Runtime(task); version = runtime.version('rtg'); sdf = {}; counts = {k: Counter() for k in ('tp', 'tp-baseline', 'fp', 'fn')}
        if region:
            runtime.run('rtg', ['format', '-o', 'reference.sdf', 'reference.fa'])
            sdf = {p.relative_to(task / 'reference.sdf').as_posix(): identity(p) for p in sorted((task / 'reference.sdf').rglob('*')) if p.is_file()}
            runtime.run('rtg', ['vcfeval', '-b', 'truth.vcf.gz', '-c', 'query.vcf.gz', '-t', 'reference.sdf', '-o', 'vcfeval', '--evaluation-regions', 'evaluation.bed', '--sample', sample, '--all-records', '--ref-overlap', '--output-mode', 'split', '--no-roc', '--sample-ploidy', '2', '--threads', '2'])
            for kind in counts:
                counts[kind] = partition_counts(task / f'vcfeval/{kind}.vcf.gz', seqs, sample)
        output.mkdir(parents=True)
        shutil.copyfile(task / 'evaluation.bed', output / 'evaluation.bed')
        if region:
            for p in (task / 'vcfeval').iterdir():
                if p.is_file():
                    shutil.copyfile(p, output / p.name)
        return publish('benchmark', output, {'caller': caller, 'sample': sample, 'domain_id': domain_id,
                       'status': 'evaluated' if region else 'not_evaluated', 'evaluated_bases': sum(e-s for _, s, e in region), 'interval_count': len(region),
                       'metrics': {t: metrics(counts['tp'][t], counts['tp-baseline'][t], counts['fp'][t], counts['fn'][t], evaluated=bool(region)) for t in ('SNP', 'INDEL', 'OTHER')},
                       'inputs': inputs, 'reference_sdf': sdf, 'normalization_lineage': norm['payload_sha256'], 'truth_normalization': truth_norm,
                       'outputs': {p.name: identity(p) for p in output.iterdir()}, 'commands': runtime.commands,
                       'tools': {'rtg': {'declared': runtime.tools['rtg'], 'observed_version': version}},
                       'warnings': ['Synthetic integration only; no canonical accuracy or fair caller-cost estimate.', 'Counts use representation-based SNP/INDEL/OTHER stratification and distinct query/truth TP.'],
                       'canonical_metrics': None, 'comparative_cost': None})


def main() -> None:
    """Expose one installed-package CLI for both Nextflow caller branches."""
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='action', required=True)
    for action in ('normalize', 'benchmark'):
        p = sub.add_parser(action)
        for name in ('reference', 'fai', 'dictionary', 'output'):
            p.add_argument('--' + name, required=True, type=Path)
        p.add_argument('--sample', required=True); p.add_argument('--caller', required=True, choices=('gatk', 'deepvariant'))
        if action == 'normalize':
            p.add_argument('--vcf', required=True, type=Path); p.add_argument('--index', required=True, type=Path); p.add_argument('--native-contract', type=Path)
        else:
            for name in ('normalized', 'truth', 'truth-index', 'confidence', 'domain'):
                p.add_argument('--' + name, required=True, type=Path)
            p.add_argument('--domain-id', required=True)
    args = vars(parser.parse_args()); action = args.pop('action'); args['reference_path'] = args.pop('reference')
    result = normalize(**args) if action == 'normalize' else benchmark(**args)
    print(json.dumps({'kind': result['kind'], 'payload_sha256': result['payload_sha256']}))


if __name__ == '__main__':
    main()
