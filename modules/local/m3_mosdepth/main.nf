// Synthetic M3 stage. Immutable tool identity; no caller or benchmark inputs.
process M3_MOSDEPTH {
    tag "${meta.sample}"
    cache 'deep'
    label 'm3_small'
    container 'quay.io/biocontainers/mosdepth@sha256:63f50e21185f5ce50fb0b6c6d3b3d4b7e50ab19356096f1045ca2538b739793c'

    input:
    tuple val(meta), path(bam), path(bai)
    val window_size

    output:
    tuple val(meta), path("${meta.sample}.mosdepth.summary.txt"), path("${meta.sample}.mosdepth.global.dist.txt"), path("${meta.sample}.mosdepth.region.dist.txt"), path("${meta.sample}.regions.bed.gz"), path("${meta.sample}.regions.bed.gz.csi"), path("${meta.sample}.thresholds.bed.gz"), path("${meta.sample}.thresholds.bed.gz.csi"), emit: coverage
    path "${meta.sample}.mosdepth.versions.txt", emit: versions
    path "${meta.sample}.mosdepth.resources.json", emit: resources
    path "${meta.sample}.mosdepth.command.sh", emit: command

    script:
    """
    set -euo pipefail
    mosdepth --threads ${task.cpus} --no-per-base --by ${window_size} \
        --flag 1796 --mapq 0 --thresholds 1,5,10,20,30 "${meta.sample}" "${bam}"
    mosdepth --version > ${meta.sample}.mosdepth.versions.txt 2>&1

    printf '{"task_id":null,"logical_artifact_id":"${meta.sample}.mosdepth","process":"M3_MOSDEPTH","requested_cpus":%s,"requested_memory_bytes":%s,"requested_time_seconds":%s,"container":"quay.io/biocontainers/mosdepth@sha256:63f50e21185f5ce50fb0b6c6d3b3d4b7e50ab19356096f1045ca2538b739793c","architecture":"%s"}\n' ${task.cpus} ${task.memory.toBytes()} ${task.time.toSeconds()} "\$(uname -m)" > ${meta.sample}.mosdepth.resources.json
    cp .command.sh ${meta.sample}.mosdepth.command.sh
    """

    stub:
    """
    touch "${meta.sample}.mosdepth.summary.txt" "${meta.sample}.mosdepth.global.dist.txt" "${meta.sample}.mosdepth.region.dist.txt" "${meta.sample}.regions.bed.gz" "${meta.sample}.regions.bed.gz.csi" "${meta.sample}.thresholds.bed.gz" "${meta.sample}.thresholds.bed.gz.csi"
    printf 'STUB_ONLY\n' > ${meta.sample}.mosdepth.versions.txt
    printf '{"status":"stub_only","process":"M3_MOSDEPTH"}\n' > ${meta.sample}.mosdepth.resources.json
    cp .command.sh ${meta.sample}.mosdepth.command.sh
    """
}
