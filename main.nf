include { validateParameters; samplesheetToList } from 'plugin/nf-schema'
include { GIAB_WES } from './workflows/giab_wes'

workflow {
    if (params.help) {
        log.info 'M1 foundation: --input CSV --callers gatk|deepvariant|both --outdir PATH'
        return
    }
    validateParameters()
    def rows = samplesheetToList(params.input, "${projectDir}/assets/schema_input.json")
    GIAB_WES(Channel.of(rows), params.callers, workflow.profile ?: 'standard')
    publish:
    foundation_contract = GIAB_WES.out.contract
}

output {
    foundation_contract {
        path 'foundation'
        mode 'copy'
    }
}

workflow.onComplete {
    log.info "foundation_only success=${workflow.success}"
}
