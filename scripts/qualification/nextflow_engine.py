#!/usr/bin/env python3
"""Bounded local engine/cache probes. Never claims managed or native qualification."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

SCRIPT = '''params.input = 'input.txt'
params.domain = 'domain-A'
params.reference = 'reference-A'
params.setting = 'setting-A'
process PROBE {
    cache 'deep'
    input:
    path source
    val reference
    val domain
    val setting
    output:
    tuple val(domain), path('receipt.txt')
    script:
    """
    cat ${source} > receipt.txt
    echo '${reference} ${domain} ${setting}' >> receipt.txt
    """
}
workflow {
    main:
    result = PROBE(file(params.input), params.reference, params.domain, params.setting)
    publish:
    receipts = result
}
output {
    receipts { path { domain, receipt -> "probe/${domain}" } }
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nextflow', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--parser', choices=['v1','v2'], required=True)
    parser.add_argument('--container-image')
    parser.add_argument('--alternate-container-image')
    args = parser.parse_args()
    if bool(args.container_image) != bool(args.alternate_container_image):
        parser.error('Both immutable runtime images are required together')
    if args.container_image and any('@sha256:' not in x for x in (args.container_image,args.alternate_container_image)):
        parser.error('Use digest-pinned images')
    root = args.work.resolve(); root.mkdir(parents=True, exist_ok=True)
    env = {k:v for k,v in os.environ.items() if not k.startswith('BASH_FUNC_')}
    env.update(NXF_SYNTAX_PARSER=args.parser, NXF_OFFLINE='true', NXF_DISABLE_CHECK_LATEST='true')
    nf = str(args.nextflow.resolve())
    version = subprocess.check_output([nf,'-version'],env=env,text=True)
    if 'version 26.04.0 ' not in version:
        raise ValueError('This probe requires exact Nextflow 26.04.0')
    script = root/'probe.nf'; script.write_text(SCRIPT)
    source = root/'input.txt'; source.write_text('nonhuman-A\n')
    cases = [('first', [], 'COMPLETED'), ('unchanged', [], 'CACHED'),
             ('parameter', ['--setting','setting-B'], 'COMPLETED'),
             ('reference', ['--reference','reference-B'], 'COMPLETED'),
             ('domain', ['--domain','domain-B'], 'COMPLETED'),
             ('content', [], 'COMPLETED'), ('container', [], 'COMPLETED'),
             ('command', [], 'COMPLETED')]
    results=[]
    for name,options,expected in cases:
        if name=='content':
            stat=source.stat(); source.write_text('nonhuman-B\n'); os.utime(source,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        if name=='command': script.write_text(SCRIPT.replace('cat ${source}', "echo command-B > command.txt\n    cat ${source}"))
        digest = ('b' if name in ('container','command') else 'a')*64
        image = (args.alternate_container_image if name in ('container','command') else args.container_image) or ('qualification/probe@sha256:'+digest)
        (root/'nextflow.config').write_text("process.container='"+image+"'\nprocess.executor='local'\ndocker.enabled="+str(bool(args.container_image)).lower()+"\ntrace.fields='name,status,hash,container'\n")
        command=[nf,'run','probe.nf','-ansi-log','false','-with-trace',name+'.tsv','-output-dir','out',*options]
        if name!='first': command+=['-resume']
        proc=subprocess.run(command,cwd=root,env=env,capture_output=True,text=True,timeout=90)
        (root/(name+'.log')).write_text(proc.stdout+proc.stderr)
        trace=list(csv.DictReader((root/(name+'.tsv')).open(),delimiter='\t')) if (root/(name+'.tsv')).exists() else []
        passed=proc.returncode==0 and len(trace)==1 and trace[0]['status']==expected
        results.append({'case':name,'expected':expected,'passed':passed,'exit':proc.returncode,'trace':trace})
        if proc.returncode:
            print(proc.stdout + proc.stderr, file=sys.stderr)
            break
    report={'engine':'26.04.0','parser':args.parser,'scope':'local nonhuman explicit-input cache and tuple workflow-output probe',
            'native_containers_executed':bool(args.container_image),'managed_backend_qualified':False,
            'container_digest_cache_test':'executed with Docker; managed cache still unqualified' if args.container_image else 'unavailable: local executor without a container runtime excludes container identity from its task hash; must test on managed backend',
            'distribution_sha256':hashlib.sha256(args.nextflow.read_bytes()).hexdigest(),
            'cases':results,'passed':len(results)==len(cases) and all(x['passed'] for x in results)}
    (root/'qualification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))
    return 0 if report['passed'] else 1

if __name__=='__main__':
    sys.exit(main())
