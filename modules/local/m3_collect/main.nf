// Contracts are evaluated by the installed package after every real tool succeeds.
process M3_COLLECT {
    tag "${meta.sample}"
    cache 'deep'
    label 'm3_small'
    container null
    input:
    tuple val(meta), path(bam), path(bai), path(sam), path(header), path(flagstat), path(idxstats), path(stats)
    path pre_bqsr_sam
    path duplicate_metrics
    path coverage_summary
    path preflight
    path expectations
    path stages
    val stage_labels
    path lanes
    path tool_versions
    val tool_names
    path resource_records
    path commands
    path artifacts
    val artifact_names
    path tool_lock
    output:
    path 'contracts', emit: contracts
    script:
    def stage_args = stages.withIndex().collect { value, index -> "--stage '${stage_labels[index]}=${value}'" }.join(' ')
    def lane_args = lanes.collect { value -> "--lane-validation '${value}'" }.join(' ')
    def version_args = tool_versions.withIndex().collect { value, index -> "--tool-version '${tool_names[index]}=${value}'" }.join(' ')
    def artifact_args = artifacts.withIndex().collect { value, index -> "--artifact '${artifact_names[index]}=${value}'" }.join(' ')
    def command_args = commands.collect { value -> "--artifact 'command_${value.name.replaceAll(/[^A-Za-z0-9_-]/, '_')}=${value}'" }.join(' ')
    def resource_args = resource_records.collect { value -> "--resource-record '${value}'" }.join(' ')
    def tools = new groovy.json.JsonSlurper().parseText(tool_lock.text).tools
    def container_args = tools.collect { name, declaration -> "--container '${name}=${declaration.image}'" }.join(' ')
    """
    set -euo pipefail
    cp .command.sh m3_collect.command.sh
    printf '{"task_id":null,"logical_artifact_id":"m3_collect","process":"M3_COLLECT","requested_cpus":%s,"requested_memory_bytes":%s,"requested_time_seconds":%s,"container":null,"architecture":"%s"}\n' ${task.cpus} ${task.memory.toBytes()} ${task.time.toSeconds()} "\$(uname -m)" > m3_collect.resources.json
    python -I -m giab_wes_nextflow.m3_cli collect \
        --preflight "${preflight}" --sam "${sam}" --pre-bqsr-sam "${pre_bqsr_sam}" \
        --bam "${bam}" --bai "${bai}" --flagstat "${flagstat}" --idxstats "${idxstats}" \
        --samtools-stats "${stats}" --duplicate-metrics "${duplicate_metrics}" \
        --coverage-summary "${coverage_summary}" --expectations "${expectations}" --output-dir contracts \
        --stage "analysis_ready=${bam}" ${stage_args} ${lane_args} ${version_args} \
        ${artifact_args} ${command_args} ${resource_args} ${container_args} \
        --artifact "command_M3_COLLECT=m3_collect.command.sh" --artifact "sam_header=${header}" \
        --resource-record m3_collect.resources.json
    """
    stub:
    """
    mkdir contracts
    printf '{"schema_version":"1.0.0","status":"stub_only","synthetic":true,"biological_processing":false,"validation_status":"not_validated","canonical":false}\n' > contracts/m3-manifest.json
    """
}
