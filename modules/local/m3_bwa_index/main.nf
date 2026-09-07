// Synthetic M3 stage. Immutable tool identity; no caller or benchmark inputs.
process M3_BWA_INDEX {
    tag "stage"
    cache 'deep'
    debug true
    label 'm3_small'
    container 'quay.io/biocontainers/bwa-mem2@sha256:374f4b910b4b04d32772fccd4cab1cdcd0758356856a960cfa8b1edebfd38c9f'

    input:
    path reference
    path source_gate

    output:
    path 'bwa_index/*', emit: index
    path "bwa_index.versions.txt", emit: versions
    path "bwa_index.resources.json", emit: resources
    path "bwa_index.command.sh", emit: command

    script:
    """
    set -euo pipefail
    mkdir bwa_index
    cp -L "${reference}" bwa_index/reference.fa
    bwa-mem2 index bwa_index/reference.fa
    bwa-mem2 version 2>&1 | tee bwa_index.versions.txt

    printf '{"task_id":null,"logical_artifact_id":"bwa_index","process":"M3_BWA_INDEX","requested_cpus":%s,"requested_memory_bytes":%s,"requested_time_seconds":%s,"container":"quay.io/biocontainers/bwa-mem2@sha256:374f4b910b4b04d32772fccd4cab1cdcd0758356856a960cfa8b1edebfd38c9f","architecture":"%s"}\n' ${task.cpus} ${task.memory.toBytes()} ${task.time.toSeconds()} "\$(uname -m)" > bwa_index.resources.json
    cp .command.sh bwa_index.command.sh
    """

    stub:
    """
    mkdir bwa_index
    cp -L "${reference}" bwa_index/reference.fa
    touch bwa_index/reference.fa.0123 bwa_index/reference.fa.amb bwa_index/reference.fa.ann bwa_index/reference.fa.pac bwa_index/reference.fa.bwt.2bit.64
    printf 'STUB_ONLY\n' > bwa_index.versions.txt
    printf '{"status":"stub_only","process":"M3_BWA_INDEX"}\n' > bwa_index.resources.json
    cp .command.sh bwa_index.command.sh
    """
}
