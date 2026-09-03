process EMIT_FOUNDATION_CONTRACT {
    tag 'foundation_only'
    input:
    val normalized_rows
    val callers
    val profile
    output:
    path 'foundation-run-contract.json', emit: contract
    script:
    def canonical = groovy.json.JsonOutput.toJson(normalized_rows.collect { tuple ->
        [metadata: tuple[0], fastq_1: tuple[1][0].name, fastq_2: tuple[1][1].name]
    })
    def hash = java.security.MessageDigest.getInstance('SHA-256').digest(canonical.bytes).encodeHex().toString()
    def nfver = nextflow.version.toString()
    """
    cat > foundation-run-contract.json <<'JSON'
    {"schema_version":"1.0.0","pipeline_version":"0.2.0-dev.2","status":"foundation_only","fixture":"synthetic_nonhuman","input_manifest_sha256":"${hash}","caller_contract":"${callers}","nextflow_version":"${nfver}","profile":"${profile}","biological_processing":false,"benchmark_result":false}
    JSON
    """
}
