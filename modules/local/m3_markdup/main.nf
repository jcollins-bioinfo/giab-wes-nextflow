// Synthetic M3 stage. Immutable tool identity; no caller or benchmark inputs.
process M3_MARKDUP {
    tag "${meta.sample}"
    cache 'deep'
    label 'm3_java'
    container 'registry-1.docker.io/broadinstitute/gatk@sha256:7da5cf586e1c463f0c72908f9ac7dec8c29e37912c82d6e7b3c250f27fcb3891'

    input:
    tuple val(meta), path(bam)

    output:
    tuple val(meta), path("${meta.sample}.markdup.bam"), path("${meta.sample}.duplicates.txt"), emit: bam
    path "${meta.sample}.markdup.versions.txt", emit: versions
    path "${meta.sample}.markdup.resources.json", emit: resources
    path "${meta.sample}.markdup.command.sh", emit: command

    script:
    """
    set -euo pipefail
    gatk --java-options "-Xmx1024m" MarkDuplicates --INPUT "${bam}" \
        --OUTPUT "${meta.sample}.markdup.bam" --METRICS_FILE "${meta.sample}.duplicates.txt" \
        --REMOVE_DUPLICATES false --REMOVE_SEQUENCING_DUPLICATES false --READ_NAME_REGEX null \
        --CREATE_INDEX false --VALIDATION_STRINGENCY STRICT
    gatk --version > ${meta.sample}.markdup.versions.txt 2>&1

    printf '{"task_id":null,"logical_artifact_id":"${meta.sample}.markdup","process":"M3_MARKDUP","requested_cpus":%s,"requested_memory_bytes":%s,"requested_time_seconds":%s,"container":"registry-1.docker.io/broadinstitute/gatk@sha256:7da5cf586e1c463f0c72908f9ac7dec8c29e37912c82d6e7b3c250f27fcb3891","architecture":"%s"}\n' ${task.cpus} ${task.memory.toBytes()} ${task.time.toSeconds()} "\$(uname -m)" > ${meta.sample}.markdup.resources.json
    cp .command.sh ${meta.sample}.markdup.command.sh
    """

    stub:
    """
    touch "${meta.sample}.markdup.bam" "${meta.sample}.duplicates.txt"
    printf 'STUB_ONLY\n' > ${meta.sample}.markdup.versions.txt
    printf '{"status":"stub_only","process":"M3_MARKDUP"}\n' > ${meta.sample}.markdup.resources.json
    cp .command.sh ${meta.sample}.markdup.command.sh
    """
}
