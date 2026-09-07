// Synthetic M3 stage. Immutable tool identity; no caller or benchmark inputs.
process M3_APPLY_BQSR {
    tag "${meta.sample}"
    cache 'deep'
    label 'm3_java'
    container 'registry-1.docker.io/broadinstitute/gatk@sha256:7da5cf586e1c463f0c72908f9ac7dec8c29e37912c82d6e7b3c250f27fcb3891'

    input:
    tuple val(meta), path(bam), path(bai), path(table)
    path reference_bundle, stageAs: 'reference_bundle/*'

    output:
    tuple val(meta), path("${meta.sample}.analysis-ready.bam"), emit: bam
    path "${meta.sample}.apply_bqsr.versions.txt", emit: versions
    path "${meta.sample}.apply_bqsr.resources.json", emit: resources
    path "${meta.sample}.apply_bqsr.command.sh", emit: command

    script:
    """
    set -euo pipefail
    gatk --java-options "-Xmx1024m" ApplyBQSR --reference "reference_bundle/reference.fa" \
        --input "${bam}" --bqsr-recal-file "${table}" --emit-original-quals true \
        --create-output-bam-index false --output "${meta.sample}.analysis-ready.bam"
    gatk --version > ${meta.sample}.apply_bqsr.versions.txt 2>&1

    printf '{"task_id":null,"logical_artifact_id":"${meta.sample}.apply_bqsr","process":"M3_APPLY_BQSR","requested_cpus":%s,"requested_memory_bytes":%s,"requested_time_seconds":%s,"container":"registry-1.docker.io/broadinstitute/gatk@sha256:7da5cf586e1c463f0c72908f9ac7dec8c29e37912c82d6e7b3c250f27fcb3891","architecture":"%s"}\n' ${task.cpus} ${task.memory.toBytes()} ${task.time.toSeconds()} "\$(uname -m)" > ${meta.sample}.apply_bqsr.resources.json
    cp .command.sh ${meta.sample}.apply_bqsr.command.sh
    """

    stub:
    """
    touch "${meta.sample}.analysis-ready.bam"
    printf 'STUB_ONLY\n' > ${meta.sample}.apply_bqsr.versions.txt
    printf '{"status":"stub_only","process":"M3_APPLY_BQSR"}\n' > ${meta.sample}.apply_bqsr.resources.json
    cp .command.sh ${meta.sample}.apply_bqsr.command.sh
    """
}
