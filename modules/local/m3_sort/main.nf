// Synthetic M3 stage. Immutable tool identity; no caller or benchmark inputs.
process M3_SORT {
    tag "${meta.read_group_id}"
    cache 'deep'
    label 'm3_small'
    container 'quay.io/biocontainers/samtools@sha256:a130447589651ed09252aa95a5e4f4132942cdb54d835d81a04a9a930d656561'

    input:
    tuple val(meta), path(sam)

    output:
    tuple val(meta), path("${meta.read_group_id}.aligned.bam"), path("${meta.read_group_id}.sorted.bam"), emit: bams
    path "${meta.read_group_id}.sort.versions.txt", emit: versions
    path "${meta.read_group_id}.sort.resources.json", emit: resources
    path "${meta.read_group_id}.sort.command.sh", emit: command

    script:
    """
    set -euo pipefail
    samtools view --bam --output "${meta.read_group_id}.aligned.bam" "${sam}"
    samtools sort -@ ${task.cpus - 1} -m 256M -o "${meta.read_group_id}.sorted.bam" "${meta.read_group_id}.aligned.bam"
    samtools --version > ${meta.read_group_id}.sort.versions.txt 2>&1

    printf '{"task_id":null,"logical_artifact_id":"${meta.read_group_id}.sort","process":"M3_SORT","requested_cpus":%s,"requested_memory_bytes":%s,"requested_time_seconds":%s,"container":"quay.io/biocontainers/samtools@sha256:a130447589651ed09252aa95a5e4f4132942cdb54d835d81a04a9a930d656561","architecture":"%s"}\n' ${task.cpus} ${task.memory.toBytes()} ${task.time.toSeconds()} "\$(uname -m)" > ${meta.read_group_id}.sort.resources.json
    cp .command.sh ${meta.read_group_id}.sort.command.sh
    """

    stub:
    """
    touch "${meta.read_group_id}.aligned.bam" "${meta.read_group_id}.sorted.bam"
    printf 'STUB_ONLY\n' > ${meta.read_group_id}.sort.versions.txt
    printf '{"status":"stub_only","process":"M3_SORT"}\n' > ${meta.read_group_id}.sort.resources.json
    cp .command.sh ${meta.read_group_id}.sort.command.sh
    """
}
