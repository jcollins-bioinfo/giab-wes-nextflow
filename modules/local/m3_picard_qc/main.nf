// Synthetic M3 stage. Immutable tool identity; no caller or benchmark inputs.
process M3_PICARD_QC {
    tag "${meta.sample}"
    cache 'deep'
    label 'm3_java'
    container 'registry-1.docker.io/broadinstitute/gatk@sha256:7da5cf586e1c463f0c72908f9ac7dec8c29e37912c82d6e7b3c250f27fcb3891'

    input:
    tuple val(meta), path(bam), path(bai)
    path reference_bundle, stageAs: 'reference_bundle/*'

    output:
    tuple val(meta), path("${meta.sample}.alignment_summary_metrics.txt"), emit: metrics
    path "${meta.sample}.picard_qc.versions.txt", emit: versions
    path "${meta.sample}.picard_qc.resources.json", emit: resources
    path "${meta.sample}.picard_qc.command.sh", emit: command

    script:
    """
    set -euo pipefail
    gatk --java-options "-Xmx1024m" CollectAlignmentSummaryMetrics --INPUT "${bam}" \
        --REFERENCE_SEQUENCE "reference_bundle/reference.fa" \
        --OUTPUT "${meta.sample}.alignment_summary_metrics.txt" --VALIDATION_STRINGENCY STRICT
    gatk --version > ${meta.sample}.picard_qc.versions.txt 2>&1

    printf '{"task_id":null,"logical_artifact_id":"${meta.sample}.picard_qc","process":"M3_PICARD_QC","requested_cpus":%s,"requested_memory_bytes":%s,"requested_time_seconds":%s,"container":"registry-1.docker.io/broadinstitute/gatk@sha256:7da5cf586e1c463f0c72908f9ac7dec8c29e37912c82d6e7b3c250f27fcb3891","architecture":"%s"}\n' ${task.cpus} ${task.memory.toBytes()} ${task.time.toSeconds()} "\$(uname -m)" > ${meta.sample}.picard_qc.resources.json
    cp .command.sh ${meta.sample}.picard_qc.command.sh
    """

    stub:
    """
    touch "${meta.sample}.alignment_summary_metrics.txt"
    printf 'STUB_ONLY\n' > ${meta.sample}.picard_qc.versions.txt
    printf '{"status":"stub_only","process":"M3_PICARD_QC"}\n' > ${meta.sample}.picard_qc.resources.json
    cp .command.sh ${meta.sample}.picard_qc.command.sh
    """
}
