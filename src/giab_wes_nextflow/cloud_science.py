"""Small native Python scientific gates between independently containerized tools.

There is no subordinate OCI runtime here. Pure reference, FASTQ, normalization,
BAM-validation and RTG metric routines are reused from the canonical code.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import shutil
from .acquisition import checksum, load_manifest as source_manifest, validate_source_bytes
from .canonical_asset_reference import digest_json, load_assets, scan_reference
from .canonical_results import DOMAINS
from .canonical_science import file_id, indexed_reference, validate_bam, validate_confidence_subset, write_json
from .cloud_contract import ASSETS, QUALIFICATIONS, load_manifest, tool_images
from .coding_domain import EXPECTED
from .m3 import read_pairs
from .m5 import metrics, require, selected, vcf_rows


def authenticate(manifest: Path, expected: str, inputs: Path, output: Path, backend: str) -> dict:
    """Authenticate original sources and qualified derivatives before alignment."""
    record = load_manifest(manifest, expected)
    roots = {key: output / key for key in ('reads', 'reference', 'known', 'domain', 'truth')}
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
    qualifications = {}
    staged = {}
    for group in ('assets', 'qualifications'):
        for role, item in record[group].items():
            source = inputs / item['uri'].rsplit('/', 1)[-1]
            require(file_id(source) == {key: item[key] for key in ('sha256', 'bytes')}, f'{role} input identity mismatch')
            if group == 'qualifications':
                qualifications[role] = json.loads(source.read_text())
                continue
            category = ('reads' if role.startswith('fastq') else 'known' if role.startswith('known_')
                        else 'domain' if role == 'calling_full' else 'truth' if role in ('evaluation', 'truth', 'truth_tbi', 'confidence') else 'reference')
            target = roots[category] / ASSETS[role]
            shutil.copyfile(source, target)
            staged[role] = target
    # Original authenticated source identity, independently of supplied SHA-256.
    source_ids = {'fastq1': 'hg001_nist7035_l001_r1', 'fastq2': 'hg001_nist7035_l001_r2',
                  'truth': 'hg001_v421_truth_vcf', 'truth_tbi': 'hg001_v421_truth_tbi', 'confidence': 'hg001_v421_high_confidence_bed'}
    contracts = {item['id']: item for item in source_manifest()['resources']}
    for role, source_id in source_ids.items():
        validate_source_bytes(staged[role], contracts[source_id])
    rows = scan_reference(staged['reference'])
    require([{'name': r['name'], 'length': r['length'], 'md5': r['md5']} for r in rows] == load_assets()['reference_dictionary'], 'complete GRCh38 base dictionary mismatch')
    expected_fai = ''.join(f"{r['name']}\t{r['length']}\t{r['offset']}\t{r['line_bases']}\t{r['line_bytes']}\n" for r in rows)
    require(staged['reference_fai'].read_text() == expected_fai, 'physical reference FAI differs')
    expected_dict = '@HD\tVN:1.6\tSO:unsorted\n' + ''.join(f"@SQ\tSN:{r['name']}\tLN:{r['length']}\tM5:{r['md5']}\n" for r in rows)
    require(staged['reference_dict'].read_text() == expected_dict, 'reference dictionary differs')
    reference_id = digest_json(load_assets()['reference_dictionary'])
    reference = qualifications['reference']
    require(reference.get('kind') == 'canonical_reference_asset' and reference.get('reference_id') == reference_id
            and reference.get('status') == 'base_identity_verified' and reference.get('complete_base_identity') is True
            and reference.get('contigs') == load_assets()['reference_dictionary']
            and {i['filename'] for i in reference.get('files', [])} == {'reference.fa', 'reference.fa.fai', 'reference.dict'}, 'reference qualification identity differs')
    index = qualifications['index']
    require(index.get('kind') == 'canonical_bwa_index_asset' and index.get('status') == 'index_qualified'
            and index.get('reference_id') == reference_id and index.get('tool') == load_assets()['aligner']
            and index.get('reference') == reference and index.get('complete_base_identity') is True, 'BWA index lacks canonical qualification')
    probes = index.get('functional_probes', {})
    require(probes.get('method') == 'fixed_context_exact_reads_v1' and probes.get('all_expected_loci_observed') is True
            and probes.get('sampled_only') is True and len(probes.get('reads', [])) == 36, 'BWA functional qualification missing')
    require(index.get('construction') == {'algorithm': 'bwtsw', 'complete_reference': True, 'command': ['bwa', 'index', '-a', 'bwtsw', 'reference.fa']}, 'BWA construction differs')
    require(re.findall(r'(?m)^Version: (\S+)\s*$', index.get('observed_version_text', '')) == ['0.7.17-r1188'], 'BWA observed version differs')
    require(re.fullmatch('[0-9a-f]{64}', probes.get('sam_sha256', '')) is not None, 'index probe output identity missing')
    contexts = [(chrom, context, reverse) for chrom in ('chr1', 'chr2', 'chr20', 'chr21', 'chr22', 'chrX')
                for context in ('ordinary', 'high_gc', 'homopolymer_flank') for reverse in (False, True)]
    lengths = {row['name']: row['length'] for row in rows}
    for number, (read, context) in enumerate(zip(probes['reads'], contexts)):
        require(set(read) == {'name', 'contig', 'position', 'reverse', 'context', 'read_sha256'}
                and (read['contig'], read['context'], read['reverse']) == context and read['name'] == f'probe{number:03d}'
                and type(read['reverse']) is bool and type(read['position']) is int
                and 1 <= read['position'] <= lengths[read['contig']] - 150
                and re.fullmatch('[0-9a-f]{64}', read['read_sha256']) is not None, 'index sampled probe inventory differs')
    annotation = staged['bwa_ann'].read_text().splitlines()[0].split()
    require(list(map(int, annotation[:2])) == [sum(row['length'] for row in rows), len(rows)], 'BWA annotation dictionary identity differs')
    known = qualifications['known_sites']
    require(known.get('kind') == 'canonical_bqsr_asset' and known.get('reference_id') == reference_id
            and known.get('source_contract_sha256') == digest_json(load_assets()['known_sites'])
            and known.get('benchmark_truth_used') is False, 'independent known-sites provenance missing')
    for qualification, directory in ((reference, roots['reference']), (index, roots['reference']), (known, roots['known'])):
        files = qualification.get('files', [])
        require(bool(files), 'qualified asset has no payload identities')
        for item in files:
            if item['filename'] == 'reference-manifest.json':
                expected_reference = record['qualifications']['reference']
                require({k: item[k] for k in ('sha256', 'bytes')} == {k: expected_reference[k] for k in ('sha256', 'bytes')}, 'index reference receipt differs')
            else:
                require('/' not in item['filename'] and file_id(directory / item['filename']) == {k: item[k] for k in ('sha256', 'bytes')}, 'qualified derivative payload differs')
    require({i['filename'] for i in index['files']} == {'reference.fa', 'reference.fa.fai', 'reference.dict', 'reference-manifest.json'} | {f'reference.fa.{s}' for s in ('amb','ann','bwt','pac','sa')}, 'index inventory differs')
    require({i['filename'] for i in known['files']} == {ASSETS[k] for k in ASSETS if k.startswith('known_')}, 'known-sites inventory differs')
    require(len(known.get('audits', [])) == 3 and all(a.get('retained_ref_alleles_verified') is True and a.get('retained_records', 0) > 0 for a in known['audits']), 'known-sites REF qualification missing')
    sources = [r for r in load_assets()['known_sites'] if r['role'] == 'bqsr_known_sites']
    require([a.get('source_id') for a in known['audits']] == [r['id'] for r in sources], 'known-sites independent source inventory differs')
    for audit, contract in zip(known['audits'], sources):
        source = audit.get('source', {})
        require(source.get('filename') == contract['filename'] and source.get('bytes') == contract['bytes']
                and re.fullmatch('[0-9a-f]{64}', source.get('sha256', '')) is not None
                and type(audit.get('excluded_absent_reference_records')) is int and audit['excluded_absent_reference_records'] >= 0,
                'known-sites source audit identity differs')
    require([item for audit in known['audits'] for item in audit.get('files', [])] == known['files'], 'known-sites audit output identities differ')
    # Only alignment needs BWA sidecars. Keep later reference staging bounded.
    index_root = output / 'index'
    roots['reference'].rename(index_root)
    roots['reference'].mkdir()
    for role in ('reference', 'reference_fai', 'reference_dict'):
        shutil.copyfile(index_root / ASSETS[role], roots['reference'] / ASSETS[role])
        staged[role] = roots['reference'] / ASSETS[role]
    runtime = qualifications['runtime']
    require(runtime.get('kind') == 'cloud_runtime_qualification' and runtime.get('status') == 'passed'
            and runtime.get('backend') == backend and runtime.get('repository_sha') == record['repository_sha']
            and runtime.get('images') == tool_images() and runtime.get('architecture') == 'x86_64'
            and runtime.get('representative_positive_callers') == {'gatk': True, 'deepvariant': True}, 'cloud representative runtime qualification missing')
    require(checksum(staged['calling_full']) == EXPECTED['R_call'][2], 'fixed calling design differs')
    require(checksum(staged['evaluation']) == EXPECTED['R_eval_holdout'][2], 'fixed evaluation denominator differs')
    (roots['domain'] / 'regions.bed').write_text(''.join(line for line in staged['calling_full'].read_text().splitlines(keepends=True) if line.split('\t')[0] in ('chr20', 'chr21', 'chr22')))
    validate_confidence_subset(staged['evaluation'], staged['confidence'], indexed_reference(staged['reference']))
    pairs = sum(1 for _ in read_pairs(staged['fastq1'], staged['fastq2']))
    require(pairs > 0, 'empty FASTQ pairs')
    receipt = {'kind': 'cloud_input_authentication', 'status': 'passed', 'manifest_sha256': expected,
               'repository_sha': record['repository_sha'], 'fastq_pairs': pairs, 'backend': backend,
               'domain': DOMAINS['hg001_chr20_22_coding'], 'reference_outputs': {ASSETS[k]: file_id(staged[k]) for k in ('reference', 'reference_fai', 'reference_dict')}, 'calling_regions': file_id(roots['domain'] / 'regions.bed'),
               'qualifications': {key: record['qualifications'][key]['sha256'] for key in QUALIFICATIONS}}
    write_json(output / 'authentication.json', receipt)
    return receipt


class SamtoolsEvidence:
    """Replay exact samtools observations through the existing strict BAM gate."""
    def __init__(self, task: Path):
        self.task = task
    def run(self, tool: str, args: list[str], *, stdout: str | None = None) -> str:
        require(tool == 'samtools', 'unexpected evidence tool')
        names = {('quickcheck', '-v', 'shared.bam'): 'quickcheck.txt', ('view', '-H', 'shared.bam'): 'header.sam',
                 ('view', 'shared.bam'): 'records.sam', ('view', '-c', '-F', '4', 'shared.bam'): 'mapped.txt',
                 ('idxstats', 'shared.bam'): 'idxstats.txt', ('view', '-c', '-F', '2304', 'shared.bam'): 'primary.txt'}
        require(tuple(args) in names, 'unexpected evidence command')
        source = self.task / names[tuple(args)]
        if stdout:
            shutil.copyfile(source, self.task / stdout)
            return ''
        return source.read_text()


def bam_gate(directory: Path, reference: Path, authentication: Path, output: Path) -> dict:
    validation = validate_bam(SamtoolsEvidence(directory), 'shared.bam', reference, oq=True)
    receipt = json.loads(authentication.read_text())
    require(validation['primary_records'] == receipt['fastq_pairs'] * 2, 'primary-read count differs from original paired reads')
    result = {'kind': 'cloud_shared_bam', 'status': 'passed', 'bam_validation': validation,
              'outputs': {name: file_id(directory / name) for name in ('shared.bam', 'shared.bam.bai')},
              'quality_contract': {'gatk': 'recalibrated_QUAL', 'deepvariant': 'retained_OQ'}}
    write_json(output, result)
    return result


def include_variants(source: Path, reference: Path, output: Path) -> dict:
    """Use canonical M5 inclusion and full-dictionary validation after bcftools norm."""
    seqs = indexed_reference(reference)
    lines = source.read_text().splitlines(keepends=True)
    declarations = []
    for line in lines:
        if line.startswith('##contig='):
            match = re.search(r'ID=([^,>]+),length=(\d+)', line)
            require(match is not None, 'malformed source contig header')
            declarations.append((match[1], int(match[2])))
    require(bool(declarations) and len(dict(declarations)) == len(declarations), 'missing or duplicate VCF contigs')
    require(declarations == [(c, len(seqs[c])) for c in seqs if c in dict(declarations)], 'source VCF dictionary incompatible')
    canonical = []
    for line in lines:
        if line.startswith('##contig='):
            continue
        if line.startswith('#CHROM'):
            canonical.extend(f'##contig=<ID={c},length={len(s)}>\n' for c, s in seqs.items())
        canonical.append(line)
    dictionary = output.with_name('dictionary.vcf'); dictionary.write_text(''.join(canonical))
    headers, rows = vcf_rows(dictionary, seqs, 'HG001', split=True)
    rows, excluded = selected(rows)
    output.write_text(''.join(headers) + ''.join('\t'.join(row) + '\n' for row in rows))
    result = {'kind': 'normalization_inclusion', 'status': 'passed', 'input': file_id(source), 'output': file_id(output), 'excluded': excluded}
    write_json(output.with_suffix('.json'), result)
    return result


def collect(partitions: list[Path], caller_identities: list[Path], reference: Path, shared_receipt: Path, authentication: Path, output: Path) -> dict:
    """Collect real RTG counts; withhold a canonical result until adapter qualification."""
    seqs = indexed_reference(reference)
    auth = json.loads(authentication.read_text())
    shared = json.loads(shared_receipt.read_text())
    expected_inputs = {name: item['sha256'] for name, item in {**shared['outputs'], **auth['reference_outputs'], 'regions.bed': auth['calling_regions']}.items()}
    require({p.name for p in caller_identities} == {'gatk-inputs.sha256', 'deepvariant-inputs.sha256'}, 'both caller input observations required')
    for observation in caller_identities:
        lines = [line.split() for line in observation.read_text().splitlines()]
        observed = {Path(name).name: sha for sha, name in lines}
        require(len(lines) == len(observed) and observed == expected_inputs, 'caller input identity or symmetry mismatch')
    callers = {}
    for directory in partitions:
        caller = directory.name
        require(caller in ('gatk', 'deepvariant') and caller not in callers, 'duplicate/unknown caller partitions')
        counts = {}
        for name in ('tp', 'tp-baseline', 'fp', 'fn'):
            _, rows = vcf_rows(directory / f'{name}.vcf.gz', seqs, 'HG001', split=True)
            counts[name] = Counter('SNP' if len(f[3]) == len(f[4]) == 1 else 'INDEL' if len(f[3]) != len(f[4]) else 'OTHER' for f in rows)
        callers[caller] = {'metrics': {kind: metrics(counts['tp'][kind], counts['tp-baseline'][kind], counts['fp'][kind], counts['fn'][kind]) for kind in ('SNP', 'INDEL', 'OTHER')},
                           'partitions': {p.name: file_id(p) for p in sorted(directory.iterdir()) if p.is_file()}}
    require(set(callers) == {'gatk', 'deepvariant'}, 'both callers required')
    result = {'kind': 'cloud_scientific_evidence', 'status': 'pending_canonical_bundle_qualification', 'canonical': False,
              'authentication': json.loads(authentication.read_text()), 'shared': json.loads(shared_receipt.read_text()),
              'callers': callers, 'domain': DOMAINS['hg001_chr20_22_coding'],
              'blockers': ['Backend-native runtime, task/resource/cache and resume receipts require independent qualification before canonical bundle publication.'],
              'claim': 'Private execution evidence only; not a validated canonical public result.'}
    write_json(output, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    auth = sub.add_parser('authenticate')
    for name in ('manifest', 'inputs', 'output'): auth.add_argument('--' + name, type=Path, required=True)
    auth.add_argument('--manifest-sha256', required=True); auth.add_argument('--backend', choices=('awsbatch', 'healthomics'), required=True)
    bam = sub.add_parser('bam-gate')
    for name in ('directory', 'reference', 'authentication', 'output'): bam.add_argument('--' + name, type=Path, required=True)
    inclusion = sub.add_parser('include')
    for name in ('source', 'reference', 'output'): inclusion.add_argument('--' + name, type=Path, required=True)
    evidence = sub.add_parser('collect')
    evidence.add_argument('--partitions', nargs=2, type=Path, required=True)
    evidence.add_argument('--caller-identities', nargs=2, type=Path, required=True)
    for name in ('reference', 'shared-receipt', 'authentication', 'output'): evidence.add_argument('--' + name, type=Path, required=True)
    args = vars(parser.parse_args()); command = args.pop('command')
    if command == 'authenticate': args['expected'] = args.pop('manifest_sha256')
    {'authenticate': authenticate, 'bam-gate': bam_gate, 'include': include_variants, 'collect': collect}[command](**args)

if __name__ == '__main__':
    main()
