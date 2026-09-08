// Only collector-accepted preprocessing may cross the caller-input boundary.
process M4_PREPARE_INPUTS {
    tag "${meta.sample}"
    cache 'deep'
    label 'm3_small'
    container null
    input:
    tuple val(meta), path(bam), path(bai)
    path reference_bundle, stageAs: 'reference_bundle/*'
    path preprocessing_bundle, stageAs: 'preprocessing-contracts/*'
    output:
    tuple val(meta), path('caller-inputs/*'), emit: inputs
    script:
    """
    set -euo pipefail
    python -I -m giab_wes_nextflow.m4_cli prepare-inputs \
        --bundle preprocessing-contracts --bam "${bam}" --bai "${bai}" \
        --reference-bundle reference_bundle --output-dir caller-inputs
    """
    stub:
    """
    mkdir caller-inputs
    cp -L "${bam}" caller-inputs/shared.bam
    cp -L "${bai}" caller-inputs/shared.bam.bai
    cp -L reference_bundle/reference.fa caller-inputs/reference.fa
    cp -L reference_bundle/reference.fa.fai caller-inputs/reference.fa.fai
    cp -L reference_bundle/reference.dict caller-inputs/reference.dict
    printf 'chrSYN1\t0\t12000\nchrSYN2\t0\t8000\n' > caller-inputs/regions.bed
    printf '{"status":"stub_only","validation_status":"not_validated","canonical":false}\n' > caller-inputs/m4-inputs.json
    """
}
