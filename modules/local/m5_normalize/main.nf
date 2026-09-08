process M5_NORMALIZE {
    tag "${meta.caller}"
    label 'm5_host'
    stageInMode 'copy'
    input:
    tuple val(meta), path(query, name: 'query.vcf.gz'), path(query_index, name: 'query.vcf.gz.tbi')
    tuple path(reference, name: 'reference.fa'), path(fai, name: 'reference.fa.fai'), path(dictionary, name: 'reference.dict')
    output:
    tuple val(meta), path('normalized/normalized.vcf.gz'), path('normalized/normalized.vcf.gz.tbi'), path('normalized/normalization.json'), emit: normalized
    script:
    """
    python -m giab_wes_nextflow.m5 normalize --vcf query.vcf.gz --index query.vcf.gz.tbi \
        --reference reference.fa --fai reference.fa.fai --dictionary reference.dict \
        --sample '${meta.sample}' --caller '${meta.caller}' --output normalized
    """
    stub:
    """
    mkdir normalized
    touch normalized/normalized.vcf.gz normalized/normalized.vcf.gz.tbi
    echo '{"status":"stub_only","canonical":false,"biological_processing":false}' > normalized/normalization.json
    """
}
