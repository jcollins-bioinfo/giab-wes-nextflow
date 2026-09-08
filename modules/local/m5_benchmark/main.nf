process M5_BENCHMARK {
    tag "${meta.caller}:${meta.domain_id}"
    label 'm5_host'
    stageInMode 'copy'
    input:
    tuple val(meta), path(query, name: 'query.vcf.gz'), path(query_index, name: 'query.vcf.gz.tbi'), path(lineage, name: 'normalization.json')
    tuple path(reference, name: 'reference.fa'), path(fai, name: 'reference.fa.fai'), path(dictionary, name: 'reference.dict')
    tuple path(truth, name: 'truth.vcf.gz'), path(truth_index, name: 'truth.vcf.gz.tbi'), path(confidence, name: 'confidence.bed'), path(domain, name: 'evaluation.bed')
    output:
    tuple val(meta), path('benchmark'), emit: result
    script:
    """
    mkdir normalized
    cp query.vcf.gz normalized/normalized.vcf.gz
    cp query.vcf.gz.tbi normalized/normalized.vcf.gz.tbi
    cp normalization.json normalized/normalization.json
    python -m giab_wes_nextflow.m5 benchmark --normalized normalized \
        --truth truth.vcf.gz --truth-index truth.vcf.gz.tbi --confidence confidence.bed --domain evaluation.bed \
        --reference reference.fa --fai reference.fa.fai --dictionary reference.dict \
        --sample '${meta.sample}' --caller '${meta.caller}' --domain-id '${meta.domain_id}' --output benchmark
    """
    stub:
    """
    mkdir benchmark
    echo '{"status":"stub_only","canonical":false,"metrics":null}' > benchmark/benchmark.json
    """
}
