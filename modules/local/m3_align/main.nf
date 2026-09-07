// Synthetic M3 stage. Immutable tool identity; no caller or benchmark inputs.
process M3_ALIGN {
    tag "${meta.read_group_id}"
    cache 'deep'
    label 'm3_small'
    container 'quay.io/biocontainers/bwa-mem2@sha256:374f4b910b4b04d32772fccd4cab1cdcd0758356856a960cfa8b1edebfd38c9f'

    input:
    tuple val(meta), path(reads), path(validation)
    path bwa_index, stageAs: 'bwa_index/*'

    output:
    tuple val(meta), path("${meta.read_group_id}.aligned.sam"), emit: sam
    path "${meta.read_group_id}.align.versions.txt", emit: versions
    path "${meta.read_group_id}.align.resources.json", emit: resources
    path "${meta.read_group_id}.align.command.sh", emit: command

    script:
    """
    set -euo pipefail
    bwa-mem2 mem -t ${task.cpus} -K 1000000 \
        -R '@RG\\tID:${meta.read_group_id}\\tSM:${meta.sample}\\tLB:${meta.library}\\tPU:${meta.platform_unit}\\tPL:ILLUMINA' \
        "bwa_index/reference.fa" "${reads[0]}" "${reads[1]}" > "${meta.read_group_id}.aligned.sam"
    bwa-mem2 version > ${meta.read_group_id}.align.versions.txt 2>&1

    printf '{"task_id":null,"logical_artifact_id":"${meta.read_group_id}.align","process":"M3_ALIGN","requested_cpus":%s,"requested_memory_bytes":%s,"requested_time_seconds":%s,"container":"quay.io/biocontainers/bwa-mem2@sha256:374f4b910b4b04d32772fccd4cab1cdcd0758356856a960cfa8b1edebfd38c9f","architecture":"%s"}\n' ${task.cpus} ${task.memory.toBytes()} ${task.time.toSeconds()} "\$(uname -m)" > ${meta.read_group_id}.align.resources.json
    cp .command.sh ${meta.read_group_id}.align.command.sh
    """

    stub:
    """
    touch "${meta.read_group_id}.aligned.sam"
    printf 'STUB_ONLY\n' > ${meta.read_group_id}.align.versions.txt
    printf '{"status":"stub_only","process":"M3_ALIGN"}\n' > ${meta.read_group_id}.align.resources.json
    cp .command.sh ${meta.read_group_id}.align.command.sh
    """
}
