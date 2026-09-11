"""Authenticate full reference and validate native classic-BWA task outputs.

Runs inside support tasks. BWA itself runs only in its separate pinned image.
The operator must bind the returned native task to HealthOmics image receipts
before publishing a reusable asset completion marker.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

from giab_wes_nextflow.canonical_asset_reference import prepare_reference, validate_reference, identity
from giab_wes_nextflow.canonical_assets import _probes, load_assets, validate_asset, INDEX_SUFFIXES
from giab_wes_nextflow.acquisition import write_record


class ProbePrepared(Exception):
    pass


def prepare(args):
    root = Path('/content/reference')
    prepare_reference(args.source, args.fai, root)
    def stage_probe(tool, command, directory):
        if tool != 'bwa':
            raise ValueError('Unexpected scientific tool')
        (root/'probe-command.json').write_text(json.dumps(command)+'\n')
        raise ProbePrepared()
    try:
        _probes(root, stage_probe)
    except ProbePrepared:
        pass
    if not (root/'_probe_work/index-probes.fastq').is_file():
        raise ValueError('Predeclared functional probes not prepared')
    shutil.copytree(root, args.output)


def accept(args):
    root = Path('/content/index')
    shutil.copytree(args.input, root)
    reference = validate_reference(root)
    version = (root/'bwa.version.txt').read_text()
    if 'Version: 0.7.17-r1188\n' not in version:
        raise ValueError('Native classic BWA version differs')
    annotation = (root/'reference.fa.ann').read_text().splitlines()[0].split()
    if list(map(int, annotation[:2])) != [sum(r['length'] for r in reference['contigs']),len(reference['contigs'])]:
        raise ValueError('Native BWA annotation differs from complete reference')
    probe_path=root/'_probe_work/index-probes.fastq'
    staged_probe_hash=hashlib.sha256(probe_path.read_bytes()).hexdigest()
    expected_command=json.loads((root/'probe-command.json').read_text())
    def native_output(tool, command, directory):
        if tool != 'bwa' or command != expected_command:
            raise ValueError('Native functional-probe command differs')
        if hashlib.sha256(probe_path.read_bytes()).hexdigest() != staged_probe_hash:
            raise ValueError('Native task used different functional probe input')
        return (root/'probe.sam').read_text()
    functional = _probes(root,native_output)
    files=[identity(root/('reference.fa.'+suffix)) for suffix in INDEX_SUFFIXES]
    if any(row['bytes'] <= 0 for row in files):
        raise ValueError('Native index payload missing')
    record={'schema_version':'1.0.0','kind':'canonical_bwa_index_asset',
            'reference_id':reference['reference_id'],'reference':reference,'tool':load_assets()['aligner'],
            'observed_version_text':version,'construction':{'algorithm':'bwtsw','complete_reference':True,
            'command':['bwa','index','-a','bwtsw','reference.fa']},'functional_probes':functional,
            'complete_base_identity':True,'status':'index_qualified',
            'files':reference['files']+[identity(root/'reference-manifest.json')]+files}
    write_record(root/'index-manifest.json',record)
    validate_asset(root,'canonical_bwa_index_asset')
    args.output.mkdir()
    for name in [row['filename'] for row in record['files']]+['index-manifest.json']:
        shutil.copy2(root/name,args.output/name)
    # Native task/runtime evidence remains separate from reusable sequence assets.
    evidence={'status':'index_bytes_and_functional_probes_verified','backend_receipts_required':True,
              'native_task_environment':(root/'native-task.txt').read_text().splitlines(),
              'index_manifest_sha256':identity(root/'index-manifest.json')['sha256'],
              'native_probe_sam_sha256':identity(root/'probe.sam')['sha256'],
              'canonical_hg001_comparison_complete':False}
    Path('index-validation.json').write_text(json.dumps(evidence,indent=2)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    prep=commands.add_parser('prepare')
    prep.add_argument('--source',type=Path,required=True);prep.add_argument('--fai',type=Path,required=True)
    prep.add_argument('--output',type=Path,required=True)
    check=commands.add_parser('accept')
    check.add_argument('--input',type=Path,required=True);check.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    (prepare if args.command=='prepare' else accept)(args)


if __name__ == '__main__':
    main()
