// Synthetic M3 stage. Immutable tool identity; no caller or benchmark inputs.
process M3_FASTQC {
    tag "${meta.read_group_id}"
    cache 'deep'
    label 'm3_small'
    container 'quay.io/biocontainers/fastqc@sha256:e194048df39c3145d9b4e0a14f4da20b59d59250465b6f2a9cb698445fd45900'

    input:
    tuple val(meta), path(reads), path(validation)

    output:
    tuple val(meta), path("*_fastqc.zip"), path("*_fastqc.html"), emit: reports
    path "${meta.read_group_id}.fastqc.versions.txt", emit: versions
    path "${meta.read_group_id}.fastqc.resources.json", emit: resources
    path "${meta.read_group_id}.fastqc.command.sh", emit: command

    script:
    """
    set -euo pipefail
    fastqc --threads ${task.cpus} --outdir . "${reads[0]}" "${reads[1]}"
    fastqc --version > ${meta.read_group_id}.fastqc.versions.txt 2>&1

    printf '{"task_id":null,"logical_artifact_id":"${meta.read_group_id}.fastqc","process":"M3_FASTQC","requested_cpus":%s,"requested_memory_bytes":%s,"requested_time_seconds":%s,"container":"quay.io/biocontainers/fastqc@sha256:e194048df39c3145d9b4e0a14f4da20b59d59250465b6f2a9cb698445fd45900","architecture":"%s"}\n' ${task.cpus} ${task.memory.toBytes()} ${task.time.toSeconds()} "\$(uname -m)" > ${meta.read_group_id}.fastqc.resources.json
    cp .command.sh ${meta.read_group_id}.fastqc.command.sh
    """

    stub:
    """
    touch "${reads[0].simpleName}_fastqc.zip" "${reads[0].simpleName}_fastqc.html" "${reads[1].simpleName}_fastqc.zip" "${reads[1].simpleName}_fastqc.html"
    printf 'STUB_ONLY\n' > ${meta.read_group_id}.fastqc.versions.txt
    printf '{"status":"stub_only","process":"M3_FASTQC"}\n' > ${meta.read_group_id}.fastqc.resources.json
    cp .command.sh ${meta.read_group_id}.fastqc.command.sh
    """
}
