// Actual full-reference preparation. Calling remains a separate gated run.
params.reference_source = null
params.reference_fai = null
params.support_image = null
params.ecr_prefix = null

process REFERENCE {
    container params.support_image
    cpus 2
    memory '8 GB'
    time '60m'
    input:
    path source
    path fai
    output:
    path 'reference'
    script:
    """
    python -I /mnt/workflow/cloud_index.py prepare --source ${source} --fai ${fai} --output reference
    """
}

process CLASSIC_INDEX {
    container "${params.ecr_prefix}/bwa@sha256:c3a708bea7947a44288e675fd9791c7aaf0c97dba0710addba336ed193821f8a"
    cpus 4
    memory '24 GB'
    time '6h'
    input:
    path reference
    output:
    path 'indexed'
    script:
    """
    test "\$(uname -m)" = x86_64
    cp -r ${reference} indexed
    cd indexed
    test "\$(df -Pk . | awk 'NR==2 {print \$4}')" -ge 36700160
    memory_limit=\$(cat /sys/fs/cgroup/memory.max 2>/dev/null || cat /sys/fs/cgroup/memory/memory.limit_in_bytes)
    test "\$memory_limit" != max
    test "\$memory_limit" -ge 17179869184
    printf '%s\\n' "\$memory_limit" > memory-limit.bytes
    (bwa 2>&1 || test \$? = 1) > bwa.version.txt
    grep -q '^Version: 0.7.17-r1188' bwa.version.txt
    sha256sum reference.fa reference.fa.fai reference.dict reference-manifest.json > before.sha256
    env | grep '^AWS_WORKFLOW_' | sort > native-task.txt
    bwa index -a bwtsw reference.fa
    bwa mem -a -T 0 -t 1 reference.fa _probe_work/index-probes.fastq > probe.sam
    sha256sum -c before.sha256
    """
}

process ACCEPT_INDEX {
    container params.support_image
    cpus 2
    memory '8 GB'
    time '60m'
    input:
    path indexed
    output:
    path 'index', emit: index
    path 'index-validation.json', emit: receipt
    script:
    """
    python -I /mnt/workflow/cloud_index.py accept --input ${indexed} --output index
    """
}

workflow {
    main:
    reference = REFERENCE(file(params.reference_source),file(params.reference_fai))
    indexed = CLASSIC_INDEX(reference)
    validated = ACCEPT_INDEX(indexed)
    publish:
    index = validated.index
    qualification = validated.receipt
}

output {
    index { path 'private-index' }
    qualification { path 'qualification' }
}
