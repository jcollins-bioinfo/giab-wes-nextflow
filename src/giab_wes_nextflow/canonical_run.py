"""Colab Run-all driver: authenticate assets, qualify runtime, execute and resume.

Scientific logic is package-owned. The notebook supplies only the reviewed SHA,
normal Drive authorization and the owner's already-approved download setting.
No local-Mac genomic compute, paid cloud launch, or partial publication is allowed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any
import zipfile

from . import __version__
from .acquisition import acquire, checksum, destination, load_manifest, safe_root, validate_source_bytes
from .canonical_science import file_id, stage_file, write_json
from .coding_domain import EXPECTED
from .m5_manifest import read_manifest as load_json
from .m5 import require
from .runtime_identity import verify_install

DRIVE = Path('/content/drive/MyDrive/giab-wes-nextflow-private')
NEXTFLOW = {'url': 'https://github.com/nextflow-io/nextflow/releases/download/v26.04.6/nextflow-26.04.6-dist',
            'sha256': '182a63c74074e2dc7956ffa3c8cd59de952ed2c44394e21faf5e1736b945444c', 'bytes': 42355106}
GTF = {'id': 'gencode_v50_basic', 'url': 'https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/release_50/gencode.v50.basic.annotation.gtf.gz',
       'destination': 'gencode/gencode.v50.basic.annotation.gtf.gz', 'filename': 'gencode.v50.basic.annotation.gtf.gz',
       'bytes': 79970394, 'checksum': {'algorithm': 'md5', 'expected': '11e77cf1d4b78b43f57d608e3f7f2202'},
       'license_note': 'GENCODE/Ensembl annotation terms; preserve GENCODE attribution.'}


def progress(stage: str, status: str) -> None:
    """Emit concise actionable progress without exposing genomic contents."""
    print(f'[{datetime.now(timezone.utc).isoformat()}] {stage}: {status}', flush=True)


def source_cache(stage: Path, drive: Path, allow_downloads: bool) -> tuple[dict[str, Path], dict[str, Any]]:
    """Rehash current declared source-cache objects before downloading duplicates."""
    from .canonical_assets import copy_verified, identity
    sources, observations = {}, {}
    required = [r for r in load_manifest()['resources'] if r['id'] != 'ucsc_hg19_to_hg38_chain'] + [GTF]
    for resource in required:
        progress(resource['id'], 'authenticate cache or resume public source transfer')
        local = destination(stage, resource['destination'])
        cached = destination(drive, 'cache/verified-sources/' + resource['destination'])
        if cached.exists():
            validate_source_bytes(cached, resource)
            copy_verified(cached, local, identity(cached))
        if not allow_downloads:
            try:
                validate_source_bytes(local, resource)
            except (ValueError, OSError):
                raise PermissionError(f"{resource['id']}: verified cache absent and public downloads disabled") from None
        observed = acquire(resource, stage)
        validate_source_bytes(local, resource, observed)
        copy_verified(local, cached, identity(local))
        observations[resource['id']] = {'source': resource, 'file': file_id(local), 'cache_destination_rehashed': True}
        sources[resource['id']] = local
    return sources, {'kind': 'sources', 'status': 'passed', 'objects': observations}


def ensure_nextflow(stage: Path, allow_downloads: bool) -> Path:
    """Install the exact platform-independent Nextflow release, requiring Java17+."""
    from .canonical_runtime_install import download_asset
    target = stage / 'tools/nextflow'
    if not target.exists():
        require(allow_downloads, 'Nextflow absent and tool downloads disabled')
        target.parent.mkdir(parents=True, exist_ok=True)
        # The installer helper verifies SHA-256/size and resumes interrupted bytes.
        download_asset(NEXTFLOW, target)
    require(file_id(target) == {'sha256': NEXTFLOW['sha256'], 'bytes': NEXTFLOW['bytes']}, 'Nextflow executable pin mismatch')
    target.chmod(0o755)
    java = subprocess.run(['java', '-version'], capture_output=True, text=True, check=True)
    match = re.search(r'version "(\d+)', java.stderr + java.stdout)
    require(match is not None and int(match[1]) >= 17, 'Colab requires Java17+ before Nextflow')
    return target


def asset_restore(drive: Path, stage: Path, kind: str, reference_id: str | None = None) -> dict[str, Any] | None:
    """Discover only project registry metadata; hydrate an exact validated asset."""
    from .canonical_assets import asset_contract_sha256, hydrate_assets, regular
    registry = destination(drive, 'registry/assets')
    if not registry.exists():
        return None
    candidates = []
    for child in sorted(registry.iterdir()):
        folder = destination(registry, child.name)
        require(folder.is_dir(), 'unexpected asset registry entry')
        for entry in sorted(folder.iterdir()):
            path = destination(folder, entry.name)
            if path.suffix != '.json':
                continue  # Interrupted .incomplete/.lock records never select an asset.
            path = regular(path)
            require(path.stat().st_size <= 100000, 'unsafe asset registry')
            record = load_json(path)
            if record.get('kind') == kind and record.get('asset_contract_sha256') == asset_contract_sha256(kind) and (reference_id is None or record.get('reference_id') == reference_id):
                candidates.append(record)
    for record in reversed(candidates):
        # Current-contract records must hydrate successfully; corrupt bytes fail explicitly.
        return hydrate_assets(drive, record['reference_id'], record['asset_id'], stage, kind=kind)
    return None


def prepare_domains(sources: dict[str, Path], directory: Path) -> dict[str, Any]:
    """Reproduce approved domain pins and promote complete BEDs before their marker.

    Interrupted copies remain .incomplete files. A later run can finish missing
    final files without changing fixed interval definitions or admitting drift.
    """
    from .canonical_assets import copy_verified, identity
    from .coding_domain import construct, EXPECTED
    directory = destination(directory.parent, directory.name)
    marker = destination(directory, 'domain-complete.json')
    arguments = (sources['gencode_v50_basic'], sources['grch38_compressed_fai'], sources['hg001_v421_high_confidence_bed'])
    if marker.exists():
        record = construct(*arguments)
        require(load_json(marker) == record, 'persisted coding-domain manifest drift')
        for name, (_, _, sha) in EXPECTED.items():
            require(checksum(destination(directory, name + '.bed')) == sha, 'persisted coding-domain drift')
        return record
    candidate = destination(directory.parent, 'domain-build-' + str(time.time_ns()))
    record = construct(*arguments, candidate)
    for name in EXPECTED:
        source = destination(candidate, name + '.bed')
        copy_verified(source, destination(directory, source.name), identity(source))
    source = destination(candidate, 'domain-complete.json')
    copy_verified(source, marker, identity(source))
    return record


def public_command(record: dict[str, Any]) -> dict[str, Any]:
    """Keep measured resources/tool/input identities, omit private argv and paths."""
    return {key: record[key] for key in ('tool', 'stage', 'image', 'backend', 'returncode', 'attempt', 'cached', 'stdout_sha256', 'stderr_sha256', 'wall_seconds', 'resources', 'isolation')}


def resources(records: list[dict[str, Any]], total_wall: float | None = None) -> dict[str, Any]:
    """Aggregate serial CPU/work duration without inventing aggregate peak memory."""
    groups = {}
    for group in ('gatk', 'deepvariant', 'shared_preprocessing', 'common_downstream', 'total'):
        selected = [r for r in records if group == 'total' or r['stage'] == group]
        cpu = sum(r['resources']['cpu_seconds'] for r in selected) if selected and all(r['resources']['cpu_seconds'] is not None for r in selected) else None
        wall = total_wall if group == 'total' else sum(r['wall_seconds'] for r in selected) if selected else None
        missing = {'peak_rss_bytes': 'No reliable exact aggregate peak RSS; sampled process-tree sums retained in task receipts.'}
        if cpu is None:
            missing['cpu_seconds'] = 'Unavailable or daemon-mediated accounting.'
        if wall is None:
            missing['wall_seconds'] = 'No uncached wall observation for this group.'
        groups[group] = {'wall_seconds': wall, 'cpu_seconds': cpu, 'peak_rss_bytes': None, 'missing_reasons': missing}
    return groups


def locate(directory: Path, filename: str) -> Path:
    """Require one unambiguous workflow output rather than guess its layout."""
    found = list(directory.rglob(filename))
    require(len(found) == 1, f'expected one {filename} in completed workflow output')
    return found[0]


def verify_outputs(directory: Path, declared: dict[str, Any]) -> None:
    """Require receipt output hashes to describe the currently published bytes."""
    for name, expected in declared.items():
        require(file_id(destination(directory, name)) == expected, 'published scientific output differs from receipt')


def collect(stage: Path, published: Path, run_id: str, identity: dict[str, Any], gates: dict[str, Any], resume: dict[str, Any], wall: float | None) -> tuple[Path, str]:
    """Produce public canonical evidence only after exact output and resume gates."""
    from .canonical_results import DOMAINS, REQUIRED_LIMITATIONS, write_public_bundle
    from .canonical_asset_reference import load_assets
    preprocessing_path = locate(published / 'canonical/shared', 'receipt.json')
    preprocessing = load_json(preprocessing_path)
    verify_outputs(preprocessing_path.parent / 'shared', preprocessing['outputs'])
    shared = {key: preprocessing['outputs'][name]['sha256'] for key, name in [('bam_sha256', 'shared.bam'), ('bai_sha256', 'shared.bam.bai'), ('reference_sha256', 'reference.fa'), ('calling_regions_sha256', 'regions.bed')]}
    callers, records, receipts = {}, list(preprocessing['commands']), {}
    expected_domain = DOMAINS['hg001_chr20_22_coding']
    common_truth_outputs = None
    for caller in ('gatk', 'deepvariant'):
        native_path = locate(published / f'canonical/{caller}/native', 'receipt.json')
        native = load_json(native_path)
        verify_outputs(native_path.parent, native['outputs'])
        candidates = [(p, load_json(p)) for p in (published / f'canonical/{caller}/benchmark').rglob('receipt.json')]
        matches = [(path, record) for path, record in candidates if record['kind'] == 'benchmark']
        require(len(matches) == 1, 'expected one unambiguous benchmark receipt per caller')
        benchmark_path, benchmark = matches[0]
        require(benchmark['caller'] == caller and benchmark['domain_id'] == expected_domain['id']
                and benchmark['domain_sha256'] == expected_domain['sha256']
                and benchmark['evaluated_bases'] == expected_domain['bases']
                and benchmark['interval_count'] == expected_domain['interval_count'], 'benchmark caller/domain contract mismatch')
        verify_outputs(benchmark_path.parent / 'query', benchmark['query']['outputs'])
        verify_outputs(benchmark_path.parent / 'truth-normalized', benchmark['truth']['outputs'])
        if common_truth_outputs is None:
            common_truth_outputs = benchmark['truth']['outputs']
        require(benchmark['truth']['outputs'] == common_truth_outputs, 'normalized truth differs between callers')
        verify_outputs(benchmark_path.parent / 'evaluation/vcfeval', benchmark['partitions'])
        actual = {key: native['inputs'][name]['sha256'] for key, name in [('bam_sha256', 'shared.bam'), ('bai_sha256', 'shared.bam.bai'), ('reference_sha256', 'reference.fa'), ('calling_regions_sha256', 'regions.bed')]}
        require(actual == shared, 'canonical caller physical-input asymmetry')
        callers[caller] = {'quality_source': 'QUAL' if caller == 'gatk' else 'OQ', 'shared_inputs': actual,
            'raw_vcf_sha256': native['outputs']['raw.vcf.gz']['sha256'], 'normalized_vcf_sha256': benchmark['query']['outputs']['normalized.vcf.gz']['sha256'], 'metrics': benchmark['metrics']}
        require(benchmark['query']['input'] == native['outputs']['raw.vcf.gz'], 'raw-to-normalized lineage mismatch')
        records.extend(native['commands']); records.extend(benchmark['commands'])
        records.extend(benchmark['query']['commands']); records.extend(benchmark['truth']['commands'])
        receipts[caller] = {'kind': caller, 'status': 'passed', 'run_id': run_id, 'inputs': actual, 'outputs': native['outputs'], 'commands': [public_command(r) for r in native['commands']]}
        receipts.setdefault('benchmark', {'kind': 'benchmark', 'status': 'passed', 'run_id': run_id, 'callers': {}})['callers'][caller] = {k: benchmark[k] for k in ('metrics', 'partitions', 'domain_sha256', 'evaluated_bases', 'interval_count')}
    receipts['preprocessing'] = {'kind': 'preprocessing', 'status': 'passed', 'run_id': run_id, 'inputs': preprocessing['inputs'], 'outputs': preprocessing['outputs'], 'bam_validation': preprocessing['bam_validation'], 'commands': [public_command(r) for r in preprocessing['commands']]}
    coverage_record = load_json(stage / 'coverage/receipt.json')
    require(file_id(stage / 'coverage/depth.tsv') == coverage_record['artifact'], 'private coverage output mismatch')
    require(coverage_record['shared_bam_sha256'] == shared['bam_sha256'], 'coverage/shared BAM identity mismatch')
    records.extend(coverage_record['commands'])
    receipts['coverage'] = load_json(stage / 'coverage/public-coverage.json')
    require(receipts['coverage'] == {key: value for key, value in coverage_record.items() if key != 'commands'},
            'public coverage differs from validated private receipt')
    receipts['coverage']['run_id'] = run_id
    receipts['resume'] = {'kind': 'resume', 'status': 'passed', 'run_id': run_id, **resume}
    for role in ('sources', 'reference', 'index', 'domain', 'runtime'):
        # Whole private receipts remain durable; public selection binds their hash
        # and concrete checked assertions without sequence/private-path disclosure.
        receipts[role] = {'kind': role, 'status': 'passed', 'run_id': run_id, **gates[role]}
    result = {'schema_version': '1.0.0', 'kind': 'canonical_results', 'status': 'complete', 'synthetic': False, 'canonical': True,
              'run_id': run_id, 'repository_sha': identity['repository_sha'], 'package_version': __version__, 'scope': 'hg001_chr20_22_coding', 'sample': 'HG001',
              'domain': DOMAINS['hg001_chr20_22_coding'], 'shared_inputs': shared, 'alignment': {'aligner': 'bwa', 'version': '0.7.17', 'runtime_identity': load_assets()['aligner']['image']},
              'callers': callers, 'resources': resources(records, wall), 'coverage': {'evaluated_bases': coverage_record['evaluated_bases'], 'covered_bases': coverage_record['covered_bases'], 'definition': coverage_record['definition'], 'artifact': 'coverage.json'},
              'coverage_missing_reason': None,
              'qualification': {role: {'artifact': role + '.json', 'sha256': hashlib.sha256((json.dumps(receipt, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()).hexdigest()} for role, receipt in receipts.items() if role != 'coverage'}, 'environments': [{'name': 'Colab', 'status': 'executed', 'evidence': 'runtime.json'}, *[{'name': x, 'status': 'configured_only', 'evidence': None} for x in ('SLURM', 'AWS Batch', 'Seqera/Wave')]],
              'limitations': [*REQUIRED_LIMITATIONS, 'This is the HG001 chr20–22 coding-domain benchmark, not a whole-exome result.', 'Uncovered and uncaptured coding loci remain in the approved recall denominator.', 'One execution does not establish stable comparative cost.'],
              'uncertainty': 'One sample, one platform and one execution; no population uncertainty interval, causal claim, or scalar winner is supported.'}
    from .canonical_results import load_canonical_bundle
    output = destination(stage, 'public-evidence')
    proof_path = destination(stage, 'public-evidence-proof.json')
    payloads = {role + '.json': receipt for role, receipt in receipts.items()}
    # A retry can observe cache reuse and a different wall interval. Preserve the
    # first complete observation, requiring every scientific/code/gate binding
    # and every other resource value to remain identical.
    stable = json.loads(json.dumps(result))
    stable['qualification'].pop('resume')
    stable['resources']['total'].pop('wall_seconds')
    stable['resources']['total']['missing_reasons'].pop('wall_seconds', None)
    scientific_pin = hashlib.sha256(json.dumps(
        {'result': stable, 'receipts': {k: v for k, v in payloads.items() if k != 'resume.json'}},
        sort_keys=True, allow_nan=False).encode()).hexdigest()
    proof = {'kind': 'canonical_collection_proof', 'run_id': run_id,
             'repository_sha': identity['repository_sha'], 'scientific_sha256': scientific_pin}
    if output.exists() and (output / 'manifest.json').exists():
        require(proof_path.is_file(), 'completed public evidence has no independent collection proof')
        saved = load_json(proof_path)
        require({k: v for k, v in saved.items() if k != 'manifest_sha256'} == proof,
                'completed public evidence run/code/scientific proof differs')
        pin = saved['manifest_sha256']
        load_canonical_bundle(output, pin)
        return output, pin
    if output.exists():
        # Retain interrupted legacy output for inspection, never overwrite it.
        os.rename(output, destination(stage, 'public-evidence.incomplete-' + str(time.time_ns())))
    candidate = destination(stage, 'public-evidence.build-' + str(time.time_ns()))
    pin = write_public_bundle(candidate, result, payloads)
    partial_proof = destination(stage, 'public-evidence-proof.json.incomplete')
    write_json(partial_proof, {**proof, 'manifest_sha256': pin})
    os.replace(partial_proof, proof_path)
    os.rename(candidate, output)
    return output, pin


def finish_evidence(stage: Path, public: Path, pin: str, run_id: str, repository_sha: str) -> Path:
    """Validate and atomically write the small return bundle; completion is last."""
    from .canonical_results import load_canonical_bundle
    model = load_canonical_bundle(public, pin)
    require(model.record['repository_sha'] == repository_sha and model.record['run_id'] == run_id,
            'completed public evidence code/run identity differs')
    bundle = destination(stage, 'canonical-hg001-evidence.zip')
    partial = destination(stage, 'canonical-hg001-evidence.zip.incomplete')
    with zipfile.ZipFile(partial, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(public.iterdir()):
            archive.write(path, path.name)
    os.replace(partial, bundle)
    marker = destination(stage, 'canonical-complete.json.incomplete')
    write_json(marker, {'run_id': run_id, 'repository_sha': repository_sha, 'manifest_sha256': pin,
                        'bundle': file_id(bundle), 'canonical': True})
    os.replace(marker, destination(stage, 'canonical-complete.json'))
    return bundle


def restore_completed_run(stage: Path, drive: Path, run_id: str, repository_sha: str) -> Path | None:
    """Recover a completed durable result before repeating runtime qualification."""
    from .canonical_checkpoint import completed, hydrate, publish
    from .canonical_asset_reference import digest_json
    public = destination(drive, f'runs/{run_id}/completed-stages/public-evidence')
    marker = destination(public, 'stage-complete.json')
    # Private provenance must have completed before the final public checkpoint.
    private = destination(drive, f'runs/{run_id}/completed-stages/private-provenance')
    private_marker = destination(private, 'stage-complete.json')
    if not marker.exists() and not private_marker.exists():
        return None
    private_record = load_json(private_marker)
    completed(private, digest_json(private_record['files']))
    proof = load_json(destination(private, 'public-evidence-proof.json'))
    require(proof['repository_sha'] == repository_sha and proof['run_id'] == run_id,
            'completed private evidence code/run identity differs')
    pin = proof['manifest_sha256']
    local = destination(stage, 'public-evidence')
    if marker.exists():
        hydrate(public, local, pin)
    else:
        # Private completion includes the exact small public inventory, so an
        # interruption between the two durable markers needs no recomputation.
        for path in destination(private, 'public-evidence').iterdir():
            stage_file(path, destination(local, path.name))
        from .canonical_results import load_canonical_bundle
        load_canonical_bundle(local, pin)
        publish(local, drive, run_id, 'public-evidence', pin)
    return finish_evidence(stage, local, pin, run_id, repository_sha)


def run(source_root: Path, expected_sha: str, stage: Path, drive: Path, *, allow_large_downloads: bool, preflight_only: bool = False) -> Path:
    """Execute the complete gated Colab path, with rehashed durable restart state."""
    from .canonical_host import probe
    from .canonical_assets import prepare_reference, build_index, prepare_known_sites, publish_assets, acquire_known_sites
    from .canonical_asset_reference import digest_json
    from .canonical_runtime import Runtime
    from .canonical_smoke import qualify
    from .canonical_checkpoint import publish
    require(re.fullmatch('[0-9a-f]{40}', expected_sha) is not None, 'full reviewed commit SHA required')
    identity = verify_install(source_root, expected_sha)
    from importlib.metadata import version
    import sys
    identity['python_version'] = sys.version
    identity['validation_dependencies'] = {name: version(name) for name in ('jsonschema', 'attrs', 'jsonschema-specifications', 'referencing', 'rpds-py')}
    require(identity['validation_dependencies']['jsonschema'] == '4.25.1', 'canonical validator requires tested jsonschema4.25.1')
    origin = subprocess.run(['git', 'remote', 'get-url', 'origin'], cwd=source_root, check=True, text=True, capture_output=True).stdout.strip()
    require(origin == 'https://github.com/jcollins-bioinfo/giab-wes-nextflow.git', 'unapproved repository origin')
    require(drive == DRIVE and safe_root(drive) == DRIVE and drive.is_dir(), 'mount the authorized project Drive root')
    stage = safe_root(stage, allow_test_root=True)
    require(stage.is_relative_to(Path('/content')) and not stage.is_relative_to(Path('/content/drive')), 'active work must be under /content, outside Drive')
    stage.mkdir(parents=True, exist_ok=True)
    host = probe(drive, stage)
    require(host['system'] == 'Linux' and host['architecture'] == 'x86_64', 'qualified architecture requires Linux/x86_64')
    require(all(host['cpu_features'].values()), 'required CPU flags absent')
    require(host['memory']['effective_ceiling_bytes'] is not None and host['memory']['effective_ceiling_bytes'] >= 24 * 1024**3, 'canonical path needs >=24GiB observed RAM')
    # Existing owned scratch assets reduce the incremental restart requirement.
    retained_bytes = sum(p.stat().st_size for p in stage.rglob('*') if p.is_file() and not p.is_symlink())
    require(host['scratch_free_bytes'] >= 16 * 1024**3 and host['scratch_free_bytes'] + retained_bytes >= 100 * 1024**3, 'need100GiB total active capacity with >=16GiB free restart reserve')
    require(host['drive_filesystem_reported_free_bytes'] >= 16 * 1024**3, 'need >=16GiB reported durable free space; each publication also checks its incremental bytes')
    write_json(stage / 'host.json', host)
    completed_run = stage / 'canonical-complete.json'
    if completed_run.exists() and not preflight_only:
        from .canonical_results import load_canonical_bundle
        complete = load_json(completed_run)
        require(complete['repository_sha'] == expected_sha, 'completed run code identity differs')
        load_canonical_bundle(stage / 'public-evidence', complete['manifest_sha256'])
        bundle = stage / 'canonical-hg001-evidence.zip'
        require(file_id(bundle) == complete['bundle'], 'completed public ZIP identity changed')
        progress('completed', 'existing result revalidated; return its evidence bundle')
        return bundle
    if preflight_only:
        progress('preflight', 'passed host gate; assets and runtime remain unqualified')
        return stage / 'host.json'
    run_id = 'hg001-chr20-22-' + expected_sha[:12]
    recovered = restore_completed_run(stage, drive, run_id, expected_sha)
    if recovered is not None:
        progress('completed', 'durable public evidence and private provenance revalidated; return evidence bundle')
        return recovered
    config = {'scratch': str(stage / 'runtime'), 'backend': 'auto', 'cpus': min(8, host['logical_cpus']),
              'memory_bytes': min(44 * 1024**3, int(host['memory']['effective_ceiling_bytes'] * 0.85)), 'allow_install': allow_large_downloads}
    runtime = Runtime(**config)
    progress('runtime', 'discover reproducible execution backend')
    runtime.discover()
    if runtime.state['status'] != 'qualified_representative_callers':
        progress('runtime', 'execute independent invented GATK and DeepVariant positive probes')
        smoke_dir = stage / ('runtime-smoke-' + str(time.time_ns()))
        qualify(runtime, smoke_dir)
    require(runtime.state['status'] == 'qualified_representative_callers', 'canonical execution blocked: representative callers unqualified')
    runtime_receipt = runtime.write_state()
    progress('sources', 'hydrate verified private source cache')
    sources, source_proof = source_cache(stage / 'sources', drive, allow_large_downloads)
    write_json(stage / 'sources.json', source_proof)
    reference_dir = stage / 'reference'
    reference = asset_restore(drive, reference_dir, 'canonical_reference_asset')
    if reference is None:
        reference = prepare_reference(sources['grch38_no_alt_fasta_gz'], sources['grch38_compressed_fai'], reference_dir)
        publish_assets(reference_dir, drive, run_id, expected_sha, kind='canonical_reference_asset')
    def runner(tool: str, args: list[str], cwd: Path) -> str:
        translated = []
        for arg in args:
            if arg.startswith('/'):
                require(Path(arg).is_relative_to(cwd), 'asset command accesses outside its task mount')
                translated.append(str(Path(arg).relative_to(cwd)))
            else:
                translated.append(arg)
        record = runtime.run(tool, translated, task_dir=cwd, stage='asset-qualification', expected_exit_codes=(0, 1) if tool == 'bwa' and not args else (0,))
        text = Path(record['stdout_path']).read_text()
        return text + Path(record['stderr_path']).read_text() if tool == 'bwa' and not args else text
    progress('reference/index', 'qualify or hydrate full GRCh38 classic BWA index')
    index_dir = stage / 'index'
    index = asset_restore(drive, index_dir, 'canonical_bwa_index_asset', reference['reference_id'])
    if index is None:
        index = build_index(reference_dir, index_dir, runner)
        publish_assets(index_dir, drive, run_id, expected_sha, kind='canonical_bwa_index_asset')
    progress('BQSR', 'authenticate independent Broad known-sites and reference compatibility')
    known_dir = stage / 'known-sites'
    known = asset_restore(drive, known_dir, 'canonical_bqsr_asset', reference['reference_id'])
    if known is None:
        known_sources = acquire_known_sites(stage / 'known-source', drive, allow_large_downloads=allow_large_downloads)
        known = prepare_known_sites(known_sources, reference_dir, known_dir, runner)
        publish_assets(known_dir, drive, run_id, expected_sha, kind='canonical_bqsr_asset')
    domains = stage / 'domains'
    prepare_domains(sources, domains)
    regions = domains / 'R_call_chr20_22.bed'
    text = ''.join(line for line in (domains / 'R_call.bed').read_text().splitlines(keepends=True) if line.split('\t')[0] in ('chr20', 'chr21', 'chr22'))
    require(bool(text), 'empty preregistered calling regions')
    regions.write_text(text)
    specification = {'fastq1': str(sources['hg001_nist7035_l001_r1']), 'fastq2': str(sources['hg001_nist7035_l001_r2']), 'index_dir': str(index_dir), 'known_sites_dir': str(known_dir), 'regions': str(regions),
                     'input_hashes': {'sources': digest_json(source_proof), 'reference': digest_json(reference), 'index': digest_json(index), 'known_sites': digest_json(known), 'calling_regions': checksum(regions)}}
    write_json(stage / 'preprocessing.json', specification)
    write_json(stage / 'benchmarking.json', {'truth': str(sources['hg001_v421_truth_vcf']), 'truth_index': str(sources['hg001_v421_truth_tbi']), 'confidence': str(sources['hg001_v421_high_confidence_bed']), 'evaluation': str(domains / 'R_eval_holdout.bed')})
    config['backend'] = runtime.backend
    config['checkpoint_context'] = {'drive_root': str(drive), 'run_id': run_id, 'repository_sha': expected_sha, 'package_inventory_sha256': identity['package_inventory_sha256'], 'runtime_backend': runtime.backend, 'validation_dependencies': identity['validation_dependencies']}
    write_json(stage / 'runtime-config.json', config)
    nextflow = ensure_nextflow(stage, allow_large_downloads)
    env = dict(os.environ, NXF_HOME=str(stage / 'nextflow-home'), NXF_TEMP=str(stage / 'tmp'), NXF_VER='26.04.6', NXF_DISABLE_CHECK_LATEST='true', NXF_ANSI_LOG='false', TMPDIR=str(stage / 'tmp'))
    (stage / 'tmp').mkdir(exist_ok=True)
    published = stage / 'published'
    command = [str(nextflow), 'run', str(source_root / 'canonical.nf'), '-profile', 'canonical_colab', '-work-dir', str(stage / 'nextflow-work'), '--outdir', str(published), '--canonical_ready', 'true', '--preprocess_spec', str(stage / 'preprocessing.json'), '--benchmark_spec', str(stage / 'benchmarking.json'), '--runtime_spec', str(stage / 'runtime-config.json'), '--canonical_max_cpus', str(config['cpus']), '--canonical_max_memory', str(config['memory_bytes']) + ' B', '-resume']
    progress('canonical', 'run full-reference shared preprocessing and chr20–22 caller comparison')
    start = time.monotonic()
    with (stage / 'nextflow-first.log').open('w') as log:
        subprocess.run(command, cwd=stage, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    from .canonical_coverage import coverage
    from .canonical_checkpoint import inventory, hydrate
    coverage_output = stage / 'coverage'
    shared = locate(published / 'canonical/shared', 'shared.bam').parent
    coverage_key = digest_json({'bam': checksum(shared / 'shared.bam'), 'domain': EXPECTED['R_eval_holdout'][2], 'code': expected_sha})
    saved_coverage = destination(drive, f'runs/{run_id}/completed-stages/coverage')
    coverage_reused = (saved_coverage / 'stage-complete.json').exists()
    if coverage_reused:
        hydrate(saved_coverage, coverage_output, coverage_key)
    else:
        if coverage_output.exists():
            coverage_output.rename(stage / ('coverage-failed-' + str(time.time_ns())))
        progress('coverage', 'measure all fixed evaluation bases including zero depth')
        coverage(runtime, shared, domains / 'R_eval_holdout.bed', coverage_output)
        publish(coverage_output, drive, run_id, 'coverage', coverage_key)
    wall = time.monotonic() - start
    before = inventory(published)
    trace = published / 'pipeline_info/execution_trace.tsv'
    first_trace = trace.read_text(); write_json(stage / 'first-run.json', {'trace_sha256': checksum(trace), 'wall_seconds': wall})
    progress('resume', 'require all five canonical tasks cached and all scientific output hashes unchanged')
    with (stage / 'nextflow-resume.log').open('w') as log:
        subprocess.run(command, cwd=stage, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    import csv
    rows = list(csv.DictReader(trace.read_text().splitlines(), delimiter='\t'))
    require(len(rows) == 5 and all(row['status'] == 'CACHED' for row in rows), 'canonical Nextflow resume did not cache all five tasks')
    after = inventory(published)
    scientific = {k: v for k, v in before.items() if k.startswith('canonical/')}
    require(scientific == {k: v for k, v in after.items() if k.startswith('canonical/')}, 'resumed canonical scientific bytes changed')
    first_rows = list(csv.DictReader(first_trace.splitlines(), delimiter='\t'))
    require({r['hash'] for r in first_rows} == {r['hash'] for r in rows}, 'resume task hash mismatch')
    resume = {'nextflow_version': '26.04.6', 'cached_tasks': 5, 'task_hashes': sorted(r['hash'] for r in rows), 'scientific_inventory_sha256': digest_json(scientific), 'first_statuses': [r['status'] for r in first_rows]}
    gates = {'sources': {'receipt_sha256': checksum(stage / 'sources.json'), 'objects': {k: v['file'] for k, v in source_proof['objects'].items()}, 'authenticated_source_bytes': True},
             'reference': {'manifest_sha256': checksum(reference_dir / 'reference-manifest.json'), 'reference_id': reference['reference_id'], 'complete_base_identity': True},
             'index': {'manifest_sha256': checksum(index_dir / 'index-manifest.json'), 'aligner': 'bwa-0.7.17', 'complete_reference': True, 'sampled_functional_probes': 36, 'qualified': True},
             'domain': {'approved_domain_hashes': {k: v[2] for k, v in EXPECTED.items()}, 'reproduced': True},
             'runtime': {'receipt_sha256': checksum(runtime_receipt), 'backend': runtime.backend, 'representative_callers_accepted': True, 'runtime_identity_sha256': digest_json(runtime.state['runtime_identity']), 'architecture': host['architecture'], 'accelerator': 'none_used'}}
    reused = list((stage / 'runtime/audit').glob('durable-reuse-*.json'))
    resume['durable_stage_reuse_observations'] = len(reused)
    complete_wall = wall if not reused and not coverage_reused and all(r['status'] == 'COMPLETED' for r in first_rows) else None
    public, pin = collect(stage, published, run_id, identity, gates, resume, complete_wall)
    # Retain private machine-readable execution provenance and bounded logs.
    private = stage / 'private-provenance'; private.mkdir(exist_ok=True)
    for path in (stage / 'host.json', stage / 'sources.json', runtime_receipt):
        stage_file(path, private / path.name)
    stage_file(stage / 'public-evidence-proof.json', private / 'public-evidence-proof.json')
    for path in public.iterdir():
        stage_file(path, private / 'public-evidence' / path.name)
    audit = private / 'audit'; audit.mkdir(exist_ok=True)
    for path in sorted((stage / 'runtime/audit').iterdir()):
        if path.is_file() and path.stat().st_size <= 1_000_000:
            stage_file(path, audit / path.name)
    publish(private, drive, run_id, 'private-provenance', digest_json(inventory(private)))
    publish(public, drive, run_id, 'public-evidence', pin)
    bundle = finish_evidence(stage, public, pin, run_id, expected_sha)
    progress('completed', f'public manifest SHA256={pin}; return canonical-hg001-evidence.zip')
    return bundle


def main() -> None:
    """Run or dry-run a reviewed canonical Colab implementation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--expected-sha', required=True)
    parser.add_argument('--scratch', required=True, type=Path)
    parser.add_argument('--drive-root', type=Path, default=DRIVE)
    parser.add_argument('--allow-large-downloads', action='store_true')
    parser.add_argument('--preflight-only', action='store_true')
    args = parser.parse_args()
    try:
        result = run(args.source_root, args.expected_sha, args.scratch, args.drive_root, allow_large_downloads=args.allow_large_downloads, preflight_only=args.preflight_only)
        print(result)
    except Exception as error:
        # The small failure report exposes a class/stage, not human sequence or
        # private command arguments. Detailed logs remain in the private runtime.
        safe = args.scratch.absolute().is_relative_to('/content') and not args.scratch.absolute().is_relative_to('/content/drive') and not any('DO NOT ACCESS WITH CHATGPT' in p for p in args.scratch.parts) and not any(p.is_symlink() for p in [args.scratch, *args.scratch.parents])
        if not safe:
            raise
        args.scratch.mkdir(parents=True, exist_ok=True)
        write_json(args.scratch / 'canonical-failure.json', {'kind': 'canonical_failure', 'canonical': False, 'repository_sha': args.expected_sha,
                   'error_class': type(error).__name__, 'message': str(error).split('?')[0][:1000]})
        raise


if __name__ == '__main__':
    main()
