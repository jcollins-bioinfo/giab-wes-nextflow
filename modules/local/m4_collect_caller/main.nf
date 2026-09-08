// Native outputs are accepted by the installed model after caller execution.
process M4_COLLECT_CALLER {
    tag "${caller}:${meta.sample}"
    cache 'deep'
    label 'm3_small'
    stageInMode 'copy'
    container null
    input:
    tuple val(meta), val(caller), path(files), val(roles)
    path caller_inputs, stageAs: 'caller-inputs/*'
    output:
    path "m4-${caller}.json", emit: contract
    script:
    def file_args = files.withIndex().collect { value, index -> "--${roles[index]} '${value}'" }.join(' ')
    """
    set -euo pipefail
    python -I -m giab_wes_nextflow.m4_cli collect-caller \
        --caller "${caller}" --inputs caller-inputs ${file_args} --output "m4-${caller}.json"
    """
    stub:
    """
    printf '{"status":"stub_only","caller":"${caller}","validation_status":"not_validated","canonical":false,"inference_validated":false}\n' > "m4-${caller}.json"
    """
}
