include { validateParameters; samplesheetToList } from 'plugin/nf-schema'
include { GIAB_WES } from './workflows/giab_wes'

workflow {
    main:
    if (params.help) {
        log.info 'M1 foundation: --input CSV --callers gatk|deepvariant|both --outdir PATH'
        return
    }
    validateParameters()
    def sampleFields = ['sample', 'library', 'lane', 'read_group_id', 'platform_unit', 'fastq_1', 'fastq_2', 'sequencing_center', 'platform']
    def rows = samplesheetToList(params.input, "${projectDir}/assets/schema_input.json").collect { values ->
        sampleFields.withIndex().collectEntries { field, index ->
            def value = field in ['fastq_1', 'fastq_2'] ? projectDir.resolve(values[index].toString()) : values[index]
            [(field): value]
        }
    }
    GIAB_WES(channel.of(rows), params.callers, workflow.profile ?: 'standard')
    completed_contract = GIAB_WES.out.map { contract ->
        log.info 'foundation_only contract emitted'
        contract
    }

    publish:
    foundation_contract = completed_contract
}

output {
    foundation_contract {
        path 'foundation'
        mode 'copy'
    }
}
