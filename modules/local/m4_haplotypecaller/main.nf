// Copy staging prevents Docker from mounting preprocessing/fixture parent paths.
process M4_HAPLOTYPECALLER {
    tag "${meta.sample}"
    cache 'deep'
    label 'm4_gatk'
    cpus 2
    memory '4 GB'
    time '30m'
    stageInMode 'copy'
    container 'registry-1.docker.io/broadinstitute/gatk@sha256:7da5cf586e1c463f0c72908f9ac7dec8c29e37912c82d6e7b3c250f27fcb3891'
    containerOptions { workflow.containerEngine == 'docker' ? '--network none --user $(id -u):$(id -g)' : '' }
    input:
    tuple val(meta), path(caller_inputs, stageAs: 'caller-inputs/*')
    output:
    tuple val(meta), path("${meta.sample}.gatk.native.vcf.gz"), path("${meta.sample}.gatk.native.vcf.gz.tbi"), path('gatk.versions.txt'), path('gatk.command.sh'), path('gatk.resources.json'), emit: result
    path 'gatk.run.log', emit: log
    script:
    """
    set -euo pipefail
    cp .command.sh gatk.command.sh
    printf '{"task_id":null,"logical_artifact_id":"m4_gatk","process":"M4_HAPLOTYPECALLER","requested_cpus":%s,"requested_memory_bytes":%s,"requested_time_seconds":%s,"container":"registry-1.docker.io/broadinstitute/gatk@sha256:7da5cf586e1c463f0c72908f9ac7dec8c29e37912c82d6e7b3c250f27fcb3891","architecture":"%s"}\n' ${task.cpus} ${task.memory.toBytes()} ${task.time.toSeconds()} "\$(uname -m)" > gatk.resources.json
    gatk --version > gatk.versions.txt 2>&1
    gatk --java-options "-Xmx3072m" HaplotypeCaller \
        --reference caller-inputs/reference.fa --input caller-inputs/shared.bam \
        --intervals caller-inputs/regions.bed --interval-padding 0 \
        --native-pair-hmm-threads 2 --standard-min-confidence-threshold-for-calling 30.0 \
        --emit-ref-confidence NONE --create-output-variant-index true \
        --output "${meta.sample}.gatk.native.vcf.gz" 2>&1 | tee gatk.run.log
    """
    stub:
    """
    touch "${meta.sample}.gatk.native.vcf.gz" "${meta.sample}.gatk.native.vcf.gz.tbi"
    printf 'STUB_ONLY\n' > gatk.versions.txt
    printf '{"status":"stub_only"}\n' > gatk.resources.json
    printf 'STUB_ONLY\n' > gatk.run.log
    cp .command.sh gatk.command.sh
    """
}
