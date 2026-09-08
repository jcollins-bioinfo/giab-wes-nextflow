// Synthetic M3 stage. Immutable tool identity; no caller or benchmark inputs.
process M3_MERGE {
    tag "${meta.sample}"
    cache 'deep'
    label 'm3_small'
    container 'quay.io/biocontainers/samtools@sha256:a130447589651ed09252aa95a5e4f4132942cdb54d835d81a04a9a930d656561'

    input:
    tuple val(meta), path(bams)

    output:
    tuple val(meta), path("${meta.sample}.merged.bam"), emit: bam
    path "${meta.sample}.merge.versions.txt", emit: versions
    path "${meta.sample}.merge.resources.json", emit: resources
    path "${meta.sample}.merge.command.sh", emit: command

    script:
    def bam_args = bams.collect { bam -> "'${bam}'" }.join(' ')
    """
    set -euo pipefail
    samtools merge -@ ${task.cpus - 1} -o "${meta.sample}.merged.bam" ${bam_args}
    samtools quickcheck -v "${meta.sample}.merged.bam"
    samtools --version > ${meta.sample}.merge.versions.txt 2>&1

    printf '{"task_id":null,"logical_artifact_id":"${meta.sample}.merge","process":"M3_MERGE","requested_cpus":%s,"requested_memory_bytes":%s,"requested_time_seconds":%s,"container":"quay.io/biocontainers/samtools@sha256:a130447589651ed09252aa95a5e4f4132942cdb54d835d81a04a9a930d656561","architecture":"%s"}\n' ${task.cpus} ${task.memory.toBytes()} ${task.time.toSeconds()} "\$(uname -m)" > ${meta.sample}.merge.resources.json
    cp .command.sh ${meta.sample}.merge.command.sh
    """

    stub:
    """
    touch "${meta.sample}.merged.bam"
    printf 'STUB_ONLY\n' > ${meta.sample}.merge.versions.txt
    printf '{"status":"stub_only","process":"M3_MERGE"}\n' > ${meta.sample}.merge.resources.json
    cp .command.sh ${meta.sample}.merge.command.sh
    """
}
