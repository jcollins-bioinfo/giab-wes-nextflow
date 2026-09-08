// Each caller selection has its own immutable manifest and publication path.
process M4_BUNDLE {
    tag "${caller_mode}"
    cache 'deep'
    label 'm3_small'
    stageInMode 'copy'
    container null
    input:
    path caller_inputs, stageAs: 'caller-inputs/*'
    path caller_results
    val caller_mode
    output:
    path 'contracts', emit: contracts
    script:
    def result_args = caller_results.collect { result -> "--caller-result '${result}'" }.join(' ')
    """
    set -euo pipefail
    python -I -m giab_wes_nextflow.m4_cli bundle \
        --inputs caller-inputs ${result_args} --output-dir contracts
    """
    stub:
    """
    mkdir contracts
    cp -L caller-inputs/m4-inputs.json contracts/m4-inputs.json
    cp -L ${caller_results.join(' ')} contracts/
    printf '{"status":"stub_only","callers":"${caller_mode}","validation_status":"not_validated","canonical":false,"biological_processing":false,"inference_validated":false}\n' > contracts/m4-manifest.json
    """
}
