// Synthetic M3 stage. Immutable tool identity; no caller or benchmark inputs.
process M3_RECALIBRATE {
    tag "${meta.sample}"
    cache 'deep'
    label 'm3_java'
    container 'registry-1.docker.io/broadinstitute/gatk@sha256:7da5cf586e1c463f0c72908f9ac7dec8c29e37912c82d6e7b3c250f27fcb3891'

    input:
    tuple val(meta), path(bam), path(bai), path(pre_bqsr_sam), path(duplicate_metrics)
    path reference_bundle, stageAs: 'reference_bundle/*'
    path known_sites
    path known_sites_index

    output:
    tuple val(meta), path("${meta.sample}.recal.table"), emit: table
    path "${meta.sample}.recalibrate.versions.txt", emit: versions
    path "${meta.sample}.recalibrate.resources.json", emit: resources
    path "${meta.sample}.recalibrate.command.sh", emit: command

    script:
    """
    set -euo pipefail
    gatk --java-options "-Xmx1024m" BaseRecalibrator --reference "reference_bundle/reference.fa" \
        --input "${bam}" --known-sites "${known_sites}" --output "${meta.sample}.recal.table"
    gatk --version > ${meta.sample}.recalibrate.versions.txt 2>&1

    printf '{"task_id":null,"logical_artifact_id":"${meta.sample}.recalibrate","process":"M3_RECALIBRATE","requested_cpus":%s,"requested_memory_bytes":%s,"requested_time_seconds":%s,"container":"registry-1.docker.io/broadinstitute/gatk@sha256:7da5cf586e1c463f0c72908f9ac7dec8c29e37912c82d6e7b3c250f27fcb3891","architecture":"%s"}\n' ${task.cpus} ${task.memory.toBytes()} ${task.time.toSeconds()} "\$(uname -m)" > ${meta.sample}.recalibrate.resources.json
    cp .command.sh ${meta.sample}.recalibrate.command.sh
    """

    stub:
    """
    touch "${meta.sample}.recal.table"
    printf 'STUB_ONLY\n' > ${meta.sample}.recalibrate.versions.txt
    printf '{"status":"stub_only","process":"M3_RECALIBRATE"}\n' > ${meta.sample}.recalibrate.resources.json
    cp .command.sh ${meta.sample}.recalibrate.command.sh
    """
}
