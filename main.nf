include { validateParameters; samplesheetToList } from 'plugin/nf-schema'
include { GIAB_WES } from './workflows/giab_wes'
include { M3_SHARED_PREPROCESSING } from './subworkflows/local/m3_shared_preprocessing/main'

workflow {
    main:
    if (params.help) {
        log.info 'Modes: foundation or m3_synthetic; m3_canonical remains blocked. Use -profile m3_test,docker for the invented fixture.'
        return
    }
    validateParameters()
    def mode = params.workflow_mode
    if (!(mode in ['foundation', 'm3_synthetic', 'm3_canonical'])) error 'Unknown workflow_mode'
    if (mode == 'm3_canonical') error 'Canonical M3 is blocked pending exact real known-sites/reference compatibility and domain gates'
    if (mode == 'm3_synthetic') {
        if (!params.reference || !params.known_sites || !params.m3_fixture_manifest) error 'M3 requires reference, known_sites and m3_fixture_manifest'
        if (!params.retain_oq) error 'M3 requires OQ retention under ADR0003'
        if (params.benchmark || params.truth_vcf || params.truth_bed || params.targets) error 'M3 synthetic preprocessing cannot consume benchmark, truth or target inputs'
        if (!(params.m3_run_id ==~ /[A-Za-z0-9][A-Za-z0-9._-]*/)) error 'M3 run ID must be a safe identifier'
        if (!(params.m3_qc_window instanceof Number) || params.m3_qc_window < 1) error 'M3 QC window must be positive'
    }
    def samplesheet = file(params.input, checkIfExists: true)
    def input_base = mode == 'foundation' ? projectDir : samplesheet.toAbsolutePath().parent
    def sampleFields = ['sample', 'library', 'lane', 'read_group_id', 'platform_unit', 'fastq_1', 'fastq_2', 'sequencing_center', 'platform']
    def rows = samplesheetToList(params.input, "${projectDir}/assets/schema_input.json").collect { values ->
        sampleFields.withIndex().collectEntries { field, index ->
            def value = field in ['fastq_1', 'fastq_2'] ? input_base.resolve(values[index].toString()) : values[index]
            [(field): value]
        }
    }
    completed_contract = channel.empty()
    accepted_preprocessing = channel.empty()
    if (mode == 'foundation') {
        GIAB_WES(channel.of(rows), params.callers, workflow.profile ?: 'standard')
        completed_contract = GIAB_WES.out.map { contract ->
            log.info 'foundation_only contract emitted'
            contract
        }
    } else {
        def evidence_sha = params.m3_repository_sha ?: workflow.commitId
        if (!(evidence_sha ==~ /[0-9a-f]{40}/)) error 'M3 requires an exact 40-character repository SHA'
        M3_SHARED_PREPROCESSING(channel.of(rows), samplesheet, file(params.reference, checkIfExists: true),
            file(params.known_sites, checkIfExists: true), file(params.m3_fixture_manifest, checkIfExists: true),
            [repository_sha:evidence_sha, run_id:params.m3_run_id], file("${projectDir}/config/m3-tools.json"), params.m3_qc_window)
        accepted_preprocessing = M3_SHARED_PREPROCESSING.out.artifacts
    }
    publish:
    foundation_contract = completed_contract
    preprocessing = accepted_preprocessing
}

output {
    foundation_contract { path 'foundation'; mode 'copy' }
    preprocessing { path 'm3'; mode 'copy' }
}
