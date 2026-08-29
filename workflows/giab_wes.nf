include { INPUT_VALIDATION } from '../subworkflows/local/input_validation/main'
include { EMIT_FOUNDATION_CONTRACT } from '../modules/local/emit_foundation_contract/main'

workflow GIAB_WES {
    take:
    rows
    callers
    profile
    main:
    INPUT_VALIDATION(rows)
    EMIT_FOUNDATION_CONTRACT(INPUT_VALIDATION.out.tuples, callers, profile)
    emit:
    contract = EMIT_FOUNDATION_CONTRACT.out.contract
}
