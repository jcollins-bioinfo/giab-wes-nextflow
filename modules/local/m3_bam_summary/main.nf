// Synthetic M3 stage. Immutable tool identity; no caller or benchmark inputs.
process M3_BAM_SUMMARY {
    tag "${meta.sample}"
    cache 'deep'
    label 'm3_small'
    container 'quay.io/biocontainers/samtools@sha256:a130447589651ed09252aa95a5e4f4132942cdb54d835d81a04a9a930d656561'

    input:
    tuple val(meta), path(bam)

    output:
    tuple val(meta), path(bam), path("${bam}.bai"), path("${meta.sample}.final.sam"), path("${meta.sample}.header.sam"), path("${meta.sample}.flagstat.json"), path("${meta.sample}.idxstats.tsv"), path("${meta.sample}.stats.txt"), emit: summary
    path "${meta.sample}.bam_summary.versions.txt", emit: versions
    path "${meta.sample}.bam_summary.resources.json", emit: resources
    path "${meta.sample}.bam_summary.command.sh", emit: command

    script:
    """
    set -euo pipefail
    samtools quickcheck -v "${bam}"
    samtools index -@ ${task.cpus - 1} "${bam}" "${bam}.bai"
    samtools view -h "${bam}" > "${meta.sample}.final.sam"
    samtools view -H "${bam}" > "${meta.sample}.header.sam"
    samtools flagstat --output-fmt json "${bam}" > "${meta.sample}.flagstat.json"
    samtools idxstats "${bam}" > "${meta.sample}.idxstats.tsv"
    samtools stats "${bam}" > "${meta.sample}.stats.txt"
    samtools --version > ${meta.sample}.bam_summary.versions.txt 2>&1

    printf '{"task_id":null,"logical_artifact_id":"${meta.sample}.bam_summary","process":"M3_BAM_SUMMARY","requested_cpus":%s,"requested_memory_bytes":%s,"requested_time_seconds":%s,"container":"quay.io/biocontainers/samtools@sha256:a130447589651ed09252aa95a5e4f4132942cdb54d835d81a04a9a930d656561","architecture":"%s"}\n' ${task.cpus} ${task.memory.toBytes()} ${task.time.toSeconds()} "\$(uname -m)" > ${meta.sample}.bam_summary.resources.json
    cp .command.sh ${meta.sample}.bam_summary.command.sh
    """

    stub:
    """
    touch "${bam}.bai" "${meta.sample}.final.sam" "${meta.sample}.header.sam" "${meta.sample}.flagstat.json" "${meta.sample}.idxstats.tsv" "${meta.sample}.stats.txt"
    printf 'STUB_ONLY\n' > ${meta.sample}.bam_summary.versions.txt
    printf '{"status":"stub_only","process":"M3_BAM_SUMMARY"}\n' > ${meta.sample}.bam_summary.resources.json
    cp .command.sh ${meta.sample}.bam_summary.command.sh
    """
}
