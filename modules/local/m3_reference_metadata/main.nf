// Synthetic M3 stage. Immutable tool identity; no caller or benchmark inputs.
process M3_REFERENCE_METADATA {
    tag "synthetic_reference"
    cache 'deep'
    label 'm3_java'
    container 'registry-1.docker.io/broadinstitute/gatk@sha256:7da5cf586e1c463f0c72908f9ac7dec8c29e37912c82d6e7b3c250f27fcb3891'

    input:
    path reference_bundle, stageAs: 'reference_bundle/*'
    path known_sites

    output:
    path 'prepared_reference/*', emit: reference
    path 'prepared_known_sites/known-sites.vcf', emit: known_sites
    path 'prepared_known_sites/known-sites.vcf.idx', emit: known_sites_index
    path "reference_metadata.versions.txt", emit: versions
    path "reference_metadata.resources.json", emit: resources
    path "reference_metadata.command.sh", emit: command

    script:
    """
    set -euo pipefail
    mkdir prepared_reference prepared_known_sites
    cp -L "reference_bundle/reference.fa" prepared_reference/reference.fa
    cp -L "reference_bundle/reference.fa.fai" prepared_reference/reference.fa.fai
    cp -L "${known_sites}" prepared_known_sites/known-sites.vcf
    gatk --java-options "-Xmx1024m" CreateSequenceDictionary \
        --REFERENCE prepared_reference/reference.fa --OUTPUT prepared_reference/reference.dict
    gatk --java-options "-Xmx1024m" IndexFeatureFile --input prepared_known_sites/known-sites.vcf
    gatk --version > reference_metadata.versions.txt 2>&1

    printf '{"task_id":null,"logical_artifact_id":"reference_metadata","process":"M3_REFERENCE_METADATA","requested_cpus":%s,"requested_memory_bytes":%s,"requested_time_seconds":%s,"container":"registry-1.docker.io/broadinstitute/gatk@sha256:7da5cf586e1c463f0c72908f9ac7dec8c29e37912c82d6e7b3c250f27fcb3891","architecture":"%s"}\n' ${task.cpus} ${task.memory.toBytes()} ${task.time.toSeconds()} "\$(uname -m)" > reference_metadata.resources.json
    cp .command.sh reference_metadata.command.sh
    """

    stub:
    """
    mkdir prepared_reference prepared_known_sites
    cp -L "reference_bundle/reference.fa" prepared_reference/reference.fa
    touch prepared_reference/reference.fa.fai prepared_reference/reference.dict
    cp -L "${known_sites}" prepared_known_sites/known-sites.vcf
    touch prepared_known_sites/known-sites.vcf.idx
    printf 'STUB_ONLY\n' > reference_metadata.versions.txt
    printf '{"status":"stub_only","process":"M3_REFERENCE_METADATA"}\n' > reference_metadata.resources.json
    cp .command.sh reference_metadata.command.sh
    """
}
