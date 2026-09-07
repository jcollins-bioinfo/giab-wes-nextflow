// The WES model consumes OQ from the same accepted physical BAM used by GATK.
process M4_DEEPVARIANT {
    tag "${meta.sample}"
    cache 'deep'
    label 'm4_deepvariant'
    cpus 2
    memory '8 GB'
    time '30m'
    stageInMode 'copy'
    container 'registry-1.docker.io/google/deepvariant@sha256:962e5a83b1d76aae6990625d47102785f791603f2138aa1fa9aa4fb6a2eecbe6'
    containerOptions { workflow.containerEngine == 'docker' ? '--network none --user $(id -u):$(id -g)' : '' }
    input:
    tuple val(meta), path(caller_inputs, stageAs: 'caller-inputs/*')
    path inspector
    output:
    tuple val(meta), path("${meta.sample}.deepvariant.native.vcf.gz"), path("${meta.sample}.deepvariant.native.vcf.gz.tbi"), path('deepvariant.versions.txt'), path('deepvariant.command.sh'), path('deepvariant.resources.json'), path("${meta.sample}.deepvariant.native.g.vcf.gz"), path("${meta.sample}.deepvariant.native.g.vcf.gz.tbi"), path('m4-deepvariant-model-before.json'), path('m4-deepvariant-inference.json'), emit: result
    path 'deepvariant.run.log', emit: log
    path 'deepvariant.logs', emit: stage_logs
    script:
    """
    set -euo pipefail
    export OMP_NUM_THREADS=2 TF_NUM_INTRAOP_THREADS=2 TF_NUM_INTEROP_THREADS=1
    cp .command.sh deepvariant.command.sh
    printf '{"task_id":null,"logical_artifact_id":"m4_deepvariant","process":"M4_DEEPVARIANT","requested_cpus":%s,"requested_memory_bytes":%s,"requested_time_seconds":%s,"container":"registry-1.docker.io/google/deepvariant@sha256:962e5a83b1d76aae6990625d47102785f791603f2138aa1fa9aa4fb6a2eecbe6","architecture":"%s"}\n' ${task.cpus} ${task.memory.toBytes()} ${task.time.toSeconds()} "\$(uname -m)" > deepvariant.resources.json
    /opt/deepvariant/bin/run_deepvariant --version > deepvariant.versions.txt 2>&1
    python3 "${inspector}" --model-root /opt/models/wes \
        --expected-model-metadata-sha256 10a47721a3ea86f6c25bcabda3af5c31a936a3183847ac8a25857a709359187a \
        --model-only --output m4-deepvariant-model-before.json
    /opt/deepvariant/bin/run_deepvariant \
        --model_type=WES --ref=caller-inputs/reference.fa --reads=caller-inputs/shared.bam \
        --regions=caller-inputs/regions.bed --sample_name="${meta.sample}" \
        --num_shards=1 --postprocess_cpus=0 \
        --make_examples_extra_args=use_original_quality_scores=true \
        --output_vcf="${meta.sample}.deepvariant.native.vcf.gz" \
        --output_gvcf="${meta.sample}.deepvariant.native.g.vcf.gz" \
        --intermediate_results_dir=deepvariant.intermediate --logging_dir=deepvariant.logs \
        2>&1 | tee deepvariant.run.log
    python3 "${inspector}" --model-root /opt/models/wes \
        --expected-model-metadata-sha256 10a47721a3ea86f6c25bcabda3af5c31a936a3183847ac8a25857a709359187a \
        --reference-fai caller-inputs/reference.fa.fai \
        --examples deepvariant.intermediate/make_examples.tfrecord-00000-of-00001.gz \
        --call-variants deepvariant.intermediate/call_variants_output.tfrecord.gz \
        --output m4-deepvariant-inference.json
    """
    stub:
    """
    touch "${meta.sample}.deepvariant.native.vcf.gz" "${meta.sample}.deepvariant.native.vcf.gz.tbi"
    touch "${meta.sample}.deepvariant.native.g.vcf.gz" "${meta.sample}.deepvariant.native.g.vcf.gz.tbi"
    printf 'STUB_ONLY\n' > deepvariant.versions.txt
    printf '{"status":"stub_only"}\n' > deepvariant.resources.json
    printf '{"status":"stub_only","inference_validated":false}\n' > m4-deepvariant-model-before.json
    printf '{"status":"stub_only","inference_validated":false}\n' > m4-deepvariant-inference.json
    printf 'STUB_ONLY\n' > deepvariant.run.log
    mkdir deepvariant.logs
    printf 'STUB_ONLY\n' > deepvariant.logs/stub.txt
    cp .command.sh deepvariant.command.sh
    """
}
