#!/usr/bin/env python3
"""Run bounded actual M5 tools and optional previously accepted M4 output integration."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import platform
import shutil
import sys
from typing import Any
from giab_wes_nextflow.m5 import benchmark, identity, load_json, normalize, require, Runtime, vcf_rows
from giab_wes_nextflow.runtime_identity import verify_install
from giab_wes_nextflow.m5_fixture import compress_inputs, EXPECTED, fixture, header, SAMPLE


def evaluate(root: Path, sample: str, callers: dict[str, Path], contracts: dict[str, Path] | None = None) -> dict[str, Any]:
    """Run identical interfaces independently and require repeat output-byte identity."""
    ref, fai, dictionary = (root / n for n in ('reference.fa', 'reference.fa.fai', 'reference.dict'))
    outputs = {}
    for caller, vcf in callers.items():
        out = root / f'normalized-{caller}'
        record = normalize(vcf, Path(str(vcf) + '.tbi'), ref, fai, dictionary, sample, caller, out, (contracts or {}).get(caller))
        again = normalize(vcf, Path(str(vcf) + '.tbi'), ref, fai, dictionary, sample, caller, root / f'repeat-{caller}', (contracts or {}).get(caller))
        require(record['outputs'] == again['outputs'], 'normalization bytes differ on repeat')
        result = benchmark(out, root / 'truth.vcf.gz', root / 'truth.vcf.gz.tbi', root / 'confidence.bed', root / 'evaluation.bed', ref, fai, dictionary, sample, caller, 'full', root / f'benchmark-{caller}')
        outputs[caller] = result
    require(outputs['gatk']['metrics'] == outputs['deepvariant']['metrics'], 'equivalent fixture caller views differ')
    return outputs


def m4_inputs(source: Path, root: Path) -> tuple[str, dict[str, Path], dict[str, Path]]:
    """Adapt actual accepted M4 files without rerunning preprocessing or callers."""
    proof = load_json(source / 'evidence/integration-proof.json')
    require(proof['status'] == 'passed' and proof['biological_processing_validated'] and not proof['canonical'], 'M4 source is not accepted synthetic execution')
    published = source / 'published/m4/both'; contracts = {c: published / f'contracts/m4-{c}.json' for c in ('gatk', 'deepvariant')}
    sample = proof['fixture']['sample']; inputs = load_json(published / 'contracts/m4-inputs.json')['data']
    expected_reference = next(x['sha256'] for x in inputs['files'] if x['filename'] == 'reference.fa')
    candidates = sorted((source / 'nextflow-work').glob('*/*/caller-inputs/reference.fa'))
    candidate = next((p for p in candidates if not p.is_symlink() and identity(p)['sha256'] == expected_reference), None)
    require(candidate is not None, 'accepted regular M4 caller reference not found')
    root.mkdir(parents=True)
    for n in ('reference.fa', 'reference.fa.fai', 'reference.dict'):
        shutil.copyfile(candidate.parent / n, root / n)
    seqs = {}; name = None
    for line in (root / 'reference.fa').read_text().splitlines():
        if line.startswith('>'):
            name = line[1:].split()[0]; seqs[name] = ''
        else:
            seqs[name] += line
    oracle = load_json(source / 'evidence/frozen-oracle.json')
    rows = [s for s in oracle['sites'] if s['alt'] is not None]
    (root / 'truth.vcf').write_text(header(seqs, sample) + ''.join(f"{s['contig']}\t{s['position_1based']}\t.\t{s['ref']}\t{s['alt']}\t60\tPASS\t.\tGT\t{s['genotype']}\n" for s in rows))
    region = ''.join(f'{c}\t0\t{len(s)}\n' for c, s in seqs.items())
    (root / 'confidence.bed').write_text(region); (root / 'evaluation.bed').write_text(region)
    runtime = Runtime(root); runtime.version('bcftools')
    runtime.run('bcftools', ['view', '--no-version', '-Oz', '-o', 'truth.vcf.gz', 'truth.vcf']); runtime.run('bcftools', ['index', '-t', 'truth.vcf.gz'])
    callers = {c: published / f'{sample}.{c}.native.vcf.gz' for c in contracts}
    return sample, callers, contracts


def retain_evidence(root: Path) -> None:
    """Retain bounded invented inputs, normalized bytes and authoritative partitions."""
    total = 0
    for name in ('fixture', 'm4-interface'):
        directory = root / name
        if not directory.is_dir():
            continue
        for source in sorted(directory.rglob('*')):
            if source.is_file():
                item = identity(source)
                total += item['bytes']
                require(item['bytes'] <= 100_000 and total <= 10_000_000, 'synthetic evidence exceeds bounded publication envelope')
                target = root / 'evidence' / source.relative_to(root)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)


def main() -> None:
    """Emit small proof/JSON evidence only after independently frozen counts pass."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root', required=True, type=Path); parser.add_argument('--m4-output-root', type=Path)
    parser.add_argument('--expected-sha', required=True)
    args = parser.parse_args(); require(platform.system() == 'Linux' and platform.machine() in ('x86_64', 'amd64'), 'actual M5 tools require Linux x86_64')
    installed = verify_install(Path(__file__).resolve().parents[1], args.expected_sha)
    root = args.output_root.resolve(); require(not root.exists(), 'fresh output root required'); root.mkdir(parents=True)
    (root / 'evidence').mkdir()
    expected = fixture(root / 'fixture'); compress_inputs(root / 'fixture')
    outputs = evaluate(root / 'fixture', SAMPLE, {c: root / f'fixture/{c}.vcf.gz' for c in ('gatk', 'deepvariant')})
    for result in outputs.values():
        for kind, counts in EXPECTED.items():
            require({k: result['metrics'][kind][k] for k in counts} == counts, f'preregistered {kind} counts failed')
        require(result['evaluated_bases'] == 350 and result['interval_count'] == 1, 'domain denominator changed')
    seqs = {'chrM5': (root / 'fixture/reference.fa').read_text().splitlines()[1]}
    _, rows = vcf_rows(root / 'fixture/normalized-gatk/normalized.vcf.gz', seqs, SAMPLE, split=True)
    require(any([r[0], int(r[1]), r[3], r[4]] == expected['left_aligned_insertion'] for r in rows), 'indel was not left aligned')
    base = root / 'fixture'
    empty = benchmark(base / 'normalized-gatk', base / 'truth.vcf.gz', base / 'truth.vcf.gz.tbi', base / 'confidence.bed', base / 'empty.bed', base / 'reference.fa', base / 'reference.fa.fai', base / 'reference.dict', SAMPLE, 'gatk', 'empty', base / 'benchmark-empty')
    require(empty['status'] == 'not_evaluated' and empty['metrics']['SNP']['f1'] is None, 'empty domain missingness failed')
    m4 = None
    if args.m4_output_root:
        sample, callers, contracts = m4_inputs(args.m4_output_root.resolve(), root / 'm4-interface')
        m4 = evaluate(root / 'm4-interface', sample, callers, contracts)
        for result in m4.values():
            require(result['metrics']['SNP']['tp_query'] == 2 and result['metrics']['SNP']['tp_truth'] == 2 and result['metrics']['SNP']['fp'] == result['metrics']['SNP']['fn'] == 0, 'accepted M4 SNV interface changed')
    evidence = root / 'evidence'
    retain_evidence(root)
    for caller, result in outputs.items():
        (evidence / f'{caller}-benchmark.json').write_text(json.dumps(result, indent=2) + '\n')
    proof = {'schema_version': '1.0.0', 'status': 'passed', 'synthetic': True, 'canonical': False,
             'installed_package': installed, 'repository_sha': args.expected_sha, 'fixture_oracle': expected, 'normalization_repeat_bytes_identical': True, 'expected_counts': EXPECTED,
             'empty_domain_missingness': True, 'm4_interface_accepted': m4 is not None,
             'm4_benchmarks': m4, 'nextflow_resume_qualified': False,
             'retained_file_hashes': {p.relative_to(evidence).as_posix(): identity(p) for p in sorted(evidence.rglob('*')) if p.is_file()},
             'execution_scope': 'Direct real-tool synthetic qualification; separate Nextflow evidence required for cache claims.'}
    (evidence / 'integration-proof.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps({'status': 'passed', 'evidence': str(evidence), 'manifest': str(root / 'fixture/m5-manifest.json')}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        if '--output-root' in sys.argv:
            root = Path(sys.argv[sys.argv.index('--output-root') + 1]).resolve()
            if (root / 'evidence').is_dir():
                failure = {'schema_version': '1.0.0', 'status': 'failed', 'synthetic': True,
                           'canonical': False, 'error_type': type(error).__name__, 'message': str(error)[-1500:]}
                (root / 'evidence/integration-proof.json').write_text(json.dumps(failure, indent=2) + '\n')
                for p in sorted(root.glob('*/*/benchmark.json')):
                    if p.stat().st_size <= 100_000:
                        shutil.copyfile(p, root / 'evidence' / (p.parent.name + '.json'))
        raise
