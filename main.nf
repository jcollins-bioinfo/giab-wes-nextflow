include { validateParameters; samplesheetToList } from 'plugin/nf-schema'
include { GIAB_WES } from './workflows/giab_wes'
include { M3_SHARED_PREPROCESSING } from './subworkflows/local/m3_shared_preprocessing/main'
include { M4_DUAL_CALLERS } from './subworkflows/local/m4_dual_callers/main'

workflow {
    main:
    if (params.help) {
        log.info 'Modes: foundation, m3_synthetic, m4_synthetic; canonical modes remain blocked. Use m3_test or m4_test with docker for invented fixtures.'
        return
    }
    validateParameters()
    def mode = params.workflow_mode
    if (!(mode in ['foundation', 'm3_synthetic', 'm3_canonical', 'm4_synthetic', 'm4_canonical'])) error 'Unknown workflow_mode'
    if (mode == 'm3_canonical') error 'Canonical M3 is blocked pending exact real known-sites/reference compatibility and domain gates'
    if (mode == 'm4_canonical') error 'Canonical M4 is blocked pending exact real known-sites/reference compatibility and domain gates'
    if (mode in ['m3_synthetic', 'm4_synthetic']) {
        if (!params.reference || !params.known_sites || !params.m3_fixture_manifest) error 'M3 requires reference, known_sites and m3_fixture_manifest'
        if (!params.retain_oq) error 'M3 requires OQ retention under ADR0003'
        if (params.benchmark || params.truth_vcf || params.truth_bed || params.targets) error 'M3 synthetic preprocessing cannot consume benchmark, truth or target inputs'
        if (!(params.m3_run_id ==~ /[A-Za-z0-9][A-Za-z0-9._-]*/)) error 'M3 run ID must be a safe identifier'
        if (!(params.m3_qc_window instanceof Number) || params.m3_qc_window < 1) error 'M3 QC window must be positive'
        def required_fixture = mode == 'm4_synthetic' ? 'm4-snv-positive' : 'm3-preprocessing'
        if (params.m3_fixture_id != required_fixture) error 'Workflow mode requires its exact registered synthetic fixture'
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
    accepted_callers = channel.empty()
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
            [repository_sha:evidence_sha, run_id:params.m3_run_id, fixture_id:params.m3_fixture_id], file("${projectDir}/config/m3-tools.json"), params.m3_qc_window)
        accepted_preprocessing = M3_SHARED_PREPROCESSING.out.artifacts
        if (mode == 'm4_synthetic') {
            M4_DUAL_CALLERS(M3_SHARED_PREPROCESSING.out.bam, M3_SHARED_PREPROCESSING.out.reference,
                M3_SHARED_PREPROCESSING.out.contracts, params.callers, file("${projectDir}/scripts/m4_inspect_deepvariant.py", checkIfExists: true))
            accepted_callers = M4_DUAL_CALLERS.out.artifacts
        }
    }
    publish:
    foundation_contract = completed_contract
    preprocessing = accepted_preprocessing
    caller_results = accepted_callers
}

output {
    foundation_contract { path 'foundation'; mode 'copy' }
    preprocessing { path 'm3'; mode 'copy' }
    caller_results { path "m4/${params.callers}"; mode 'copy' }
}
