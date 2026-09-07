include { M4_PREPARE_INPUTS } from '../../../modules/local/m4_prepare_inputs/main'
include { M4_HAPLOTYPECALLER } from '../../../modules/local/m4_haplotypecaller/main'
include { M4_DEEPVARIANT } from '../../../modules/local/m4_deepvariant/main'
include { M4_COLLECT_CALLER as M4_COLLECT_GATK } from '../../../modules/local/m4_collect_caller/main'
include { M4_COLLECT_CALLER as M4_COLLECT_DEEPVARIANT } from '../../../modules/local/m4_collect_caller/main'
include { M4_BUNDLE } from '../../../modules/local/m4_bundle/main'

workflow M4_DUAL_CALLERS {
    take:
    accepted_bam
    accepted_reference
    preprocessing_bundle
    caller_mode
    inspector
    main:
    if (!(caller_mode in ['gatk', 'deepvariant', 'both'])) error 'Unknown M4 caller selection'
    preprocessing_files = preprocessing_bundle.map { directory ->
        ['manifest', 'alignment', 'qc', 'coverage', 'resources', 'provenance'].collect { kind -> directory.resolve('m3-' + kind + '.json') }
    }
    M4_PREPARE_INPUTS(accepted_bam, accepted_reference, preprocessing_files)
    isolated = M4_PREPARE_INPUTS.out.inputs
    isolated_files = isolated.map { _meta, inputs -> inputs }
    caller_contracts = channel.empty()
    native_outputs = channel.empty()
    if (caller_mode in ['gatk', 'both']) {
        M4_HAPLOTYPECALLER(isolated)
        gatk = M4_HAPLOTYPECALLER.out.result
        gatk_collection = gatk.map { meta, vcf, index, version, command, resources ->
            tuple(meta, 'gatk', [vcf, index, version, command, resources], ['vcf', 'vcf-index', 'version-file', 'command-file', 'resources'])
        }
        M4_COLLECT_GATK(gatk_collection, isolated_files)
        caller_contracts = caller_contracts.mix(M4_COLLECT_GATK.out.contract)
        native_outputs = native_outputs.mix(gatk.flatMap { item -> item[1..5] }, M4_HAPLOTYPECALLER.out.log)
    }
    if (caller_mode in ['deepvariant', 'both']) {
        M4_DEEPVARIANT(isolated, inspector)
        deepvariant = M4_DEEPVARIANT.out.result
        dv_collection = deepvariant.map { meta, vcf, index, version, command, resources, gvcf, gindex, model_before, inference ->
            tuple(meta, 'deepvariant', [vcf, index, version, command, resources, gvcf, gindex, model_before, inference],
                ['vcf', 'vcf-index', 'version-file', 'command-file', 'resources', 'gvcf', 'gvcf-index', 'model-before', 'inference'])
        }
        M4_COLLECT_DEEPVARIANT(dv_collection, isolated_files)
        caller_contracts = caller_contracts.mix(M4_COLLECT_DEEPVARIANT.out.contract)
        native_outputs = native_outputs.mix(deepvariant.flatMap { item -> item[1..9] }, M4_DEEPVARIANT.out.log, M4_DEEPVARIANT.out.stage_logs)
    }
    results = caller_contracts.collect().map { files -> files.sort { a, b -> a.name <=> b.name } }
    M4_BUNDLE(isolated_files, results, caller_mode)
    accepted_outputs = M4_BUNDLE.out.contracts.combine(native_outputs.collect()).map { items -> items.flatten() }.flatMap { item -> item }
    emit:
    artifacts = accepted_outputs
    contracts = M4_BUNDLE.out.contracts
}
