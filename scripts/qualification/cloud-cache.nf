// Nonhuman, one-task managed cache probe. This never executes HG001 science.
params.input = null
params.reference = 'reference-A'
params.domain = 'domain-A'
params.setting = 'setting-A'
params.probe_image = null

process CACHE_PROBE {
    cache 'deep'
    container params.probe_image
    input:
    path source, stageAs: 'input.txt'
    val reference
    val domain
    val setting
    output:
    path 'receipt.txt'
    script:
    """
    cat input.txt > receipt.txt
    printf '%s\\n' '${reference}' '${domain}' '${setting}' >> receipt.txt
    # COMMAND_VARIANT
    """
}

workflow {
    main:
    if (!(params.probe_image ==~ /[^\s]+@sha256:[0-9a-f]{64}/)) error('Pinned image required')
    if (!(params.reference in ['reference-A', 'reference-B'])) error('Unexpected reference fixture')
    if (!(params.domain in ['domain-A', 'domain-B'])) error('Unexpected domain fixture')
    if (!(params.setting in ['setting-A', 'setting-B'])) error('Unexpected parameter fixture')
    result = CACHE_PROBE(file(params.input, checkIfExists: true), params.reference, params.domain, params.setting)
    publish:
    receipt = result
}

output {
    receipt { path 'probe'; mode 'copy' }
}
