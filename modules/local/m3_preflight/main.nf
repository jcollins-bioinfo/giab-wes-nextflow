// Synthetic M3 stage. Immutable tool identity; no caller or benchmark inputs.
process M3_PREFLIGHT {
    tag "synthetic_source_gate"
    cache 'deep'
    label 'm3_small'
    container null

    input:
    path samplesheet
    path reference
    path known_sites
    path expectations
    path source_reads
    val run_meta

    output:
    path 'm3-preflight.json', emit: contract
    path "source_preflight.versions.txt", emit: versions
    path "source_preflight.resources.json", emit: resources
    path "source_preflight.command.sh", emit: command

    script:
    """
    set -euo pipefail
    python -I -m giab_wes_nextflow.m3_cli preflight \
        --samplesheet "${samplesheet}" --reference "${reference}" \
        --known-sites "${known_sites}" --expectations "${expectations}" \
        --repository-sha "${run_meta.repository_sha}" --run-id "${run_meta.run_id}" \
        --output m3-preflight.json
    python -I -c 'import giab_wes_nextflow; print(giab_wes_nextflow.__version__)' > source_preflight.versions.txt 2>&1

    printf '{"task_id":null,"logical_artifact_id":"source_preflight","process":"M3_PREFLIGHT","requested_cpus":%s,"requested_memory_bytes":%s,"requested_time_seconds":%s,"container":null,"architecture":"%s"}\n' ${task.cpus} ${task.memory.toBytes()} ${task.time.toSeconds()} "\$(uname -m)" > source_preflight.resources.json
    cp .command.sh source_preflight.command.sh
    """

    stub:
    """
    printf '{"status":"stub_only","canonical":false}\n' > m3-preflight.json
    printf 'STUB_ONLY\n' > source_preflight.versions.txt
    printf '{"status":"stub_only","process":"M3_PREFLIGHT"}\n' > source_preflight.resources.json
    cp .command.sh source_preflight.command.sh
    """
}
