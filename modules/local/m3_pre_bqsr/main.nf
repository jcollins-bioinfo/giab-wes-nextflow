// Synthetic M3 stage. Immutable tool identity; no caller or benchmark inputs.
process M3_PRE_BQSR {
    tag "${meta.sample}"
    cache 'deep'
    label 'm3_small'
    container 'quay.io/biocontainers/samtools@sha256:a130447589651ed09252aa95a5e4f4132942cdb54d835d81a04a9a930d656561'

    input:
    tuple val(meta), path(bam), path(duplicate_metrics)

    output:
    tuple val(meta), path(bam), path("${bam}.bai"), path("${meta.sample}.pre-bqsr.sam"), path(duplicate_metrics), emit: bam
    path "${meta.sample}.pre_bqsr.versions.txt", emit: versions
    path "${meta.sample}.pre_bqsr.resources.json", emit: resources
    path "${meta.sample}.pre_bqsr.command.sh", emit: command

    script:
    """
    set -euo pipefail
    samtools quickcheck -v "${bam}"
    samtools index -@ ${task.cpus - 1} "${bam}" "${bam}.bai"
    samtools view -h "${bam}" > "${meta.sample}.pre-bqsr.sam"
    samtools --version > ${meta.sample}.pre_bqsr.versions.txt 2>&1

    printf '{"task_id":null,"logical_artifact_id":"${meta.sample}.pre_bqsr","process":"M3_PRE_BQSR","requested_cpus":%s,"requested_memory_bytes":%s,"requested_time_seconds":%s,"container":"quay.io/biocontainers/samtools@sha256:a130447589651ed09252aa95a5e4f4132942cdb54d835d81a04a9a930d656561","architecture":"%s"}\n' ${task.cpus} ${task.memory.toBytes()} ${task.time.toSeconds()} "\$(uname -m)" > ${meta.sample}.pre_bqsr.resources.json
    cp .command.sh ${meta.sample}.pre_bqsr.command.sh
    """

    stub:
    """
    touch "${bam}.bai" "${meta.sample}.pre-bqsr.sam"
    printf 'STUB_ONLY\n' > ${meta.sample}.pre_bqsr.versions.txt
    printf '{"status":"stub_only","process":"M3_PRE_BQSR"}\n' > ${meta.sample}.pre_bqsr.resources.json
    cp .command.sh ${meta.sample}.pre_bqsr.command.sh
    """
}
