// Synthetic M3 stage. Immutable tool identity; no caller or benchmark inputs.
process M3_FASTQ_VALIDATE {
    tag "${meta.read_group_id}"
    cache 'deep'
    label 'm3_small'
    container null

    input:
    tuple val(meta), path(reads)
    path reference_bundle, stageAs: 'reference_bundle/*'
    path expectations
    path source_gate
    val run_meta

    output:
    tuple val(meta), path(reads), path("${meta.read_group_id}.fastq-validation.json"), emit: reads
    path "${meta.read_group_id}.fastq_validation.versions.txt", emit: versions
    path "${meta.read_group_id}.fastq_validation.resources.json", emit: resources
    path "${meta.read_group_id}.fastq_validation.command.sh", emit: command

    script:
    """
    set -euo pipefail
    python -I -m giab_wes_nextflow.m3_cli validate-fastq \
        --fastq1 "${reads[0]}" --fastq2 "${reads[1]}" --sample "${meta.sample}" \
        --library "${meta.library}" --lane "${meta.lane}" --read-group "${meta.read_group_id}" \
        --platform-unit "${meta.platform_unit}" --platform ILLUMINA \
        --reference "reference_bundle/reference.fa" --reference-fai "reference_bundle/reference.fa.fai" \
        --reference-dict "reference_bundle/reference.dict" --fixture-manifest "${expectations}" \
        --run-id "${run_meta.run_id}" --fixture-id "${run_meta.fixture_id ?: 'm3-preprocessing'}" \
        --output "${meta.read_group_id}.fastq-validation.json"
    python -I -c 'import giab_wes_nextflow; print(giab_wes_nextflow.__version__)' > ${meta.read_group_id}.fastq_validation.versions.txt 2>&1

    printf '{"task_id":null,"logical_artifact_id":"${meta.read_group_id}.fastq_validation","process":"M3_FASTQ_VALIDATE","requested_cpus":%s,"requested_memory_bytes":%s,"requested_time_seconds":%s,"container":null,"architecture":"%s"}\n' ${task.cpus} ${task.memory.toBytes()} ${task.time.toSeconds()} "\$(uname -m)" > ${meta.read_group_id}.fastq_validation.resources.json
    cp .command.sh ${meta.read_group_id}.fastq_validation.command.sh
    """

    stub:
    """
    printf '{"status":"stub_only"}\n' > "${meta.read_group_id}.fastq-validation.json"
    printf 'STUB_ONLY\n' > ${meta.read_group_id}.fastq_validation.versions.txt
    printf '{"status":"stub_only","process":"M3_FASTQ_VALIDATE"}\n' > ${meta.read_group_id}.fastq_validation.resources.json
    cp .command.sh ${meta.read_group_id}.fastq_validation.command.sh
    """
}
