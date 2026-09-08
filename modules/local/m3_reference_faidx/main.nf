// Synthetic M3 stage. Immutable tool identity; no caller or benchmark inputs.
process M3_REFERENCE_FAIDX {
    tag "synthetic_reference"
    cache 'deep'
    label 'm3_small'
    container 'quay.io/biocontainers/samtools@sha256:a130447589651ed09252aa95a5e4f4132942cdb54d835d81a04a9a930d656561'

    input:
    path reference
    path source_gate

    output:
    path 'reference_bundle/*', emit: reference
    path "reference_faidx.versions.txt", emit: versions
    path "reference_faidx.resources.json", emit: resources
    path "reference_faidx.command.sh", emit: command

    script:
    """
    set -euo pipefail
    mkdir reference_bundle
    cp -L "${reference}" reference_bundle/reference.fa
    samtools faidx reference_bundle/reference.fa
    samtools --version > reference_faidx.versions.txt 2>&1

    printf '{"task_id":null,"logical_artifact_id":"reference_faidx","process":"M3_REFERENCE_FAIDX","requested_cpus":%s,"requested_memory_bytes":%s,"requested_time_seconds":%s,"container":"quay.io/biocontainers/samtools@sha256:a130447589651ed09252aa95a5e4f4132942cdb54d835d81a04a9a930d656561","architecture":"%s"}\n' ${task.cpus} ${task.memory.toBytes()} ${task.time.toSeconds()} "\$(uname -m)" > reference_faidx.resources.json
    cp .command.sh reference_faidx.command.sh
    """

    stub:
    """
    mkdir reference_bundle
    cp -L "${reference}" reference_bundle/reference.fa
    touch reference_bundle/reference.fa.fai
    printf 'STUB_ONLY\n' > reference_faidx.versions.txt
    printf '{"status":"stub_only","process":"M3_REFERENCE_FAIDX"}\n' > reference_faidx.resources.json
    cp .command.sh reference_faidx.command.sh
    """
}
