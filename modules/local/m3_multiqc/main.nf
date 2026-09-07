// Synthetic M3 stage. Immutable tool identity; no caller or benchmark inputs.
process M3_MULTIQC {
    tag "stage"
    cache 'deep'
    label 'm3_small'
    container 'ghcr.io/multiqc/multiqc@sha256:976be2094a3bc1dab7315ad03440d43aab09bf7756f84f3a92ef7ae1013e4bfd'
    // Match the execution host's work-directory owner; the image defaults to UID 1000.
    containerOptions { workflow.containerEngine == 'docker' ? '--user $(id -u):$(id -g)' : '' }

    input:
    path reports

    output:
    path 'multiqc_report.html', emit: html
    path 'multiqc_data', emit: data
    path 'qc_reports', emit: source_reports
    path "multiqc.versions.txt", emit: versions
    path "multiqc.resources.json", emit: resources
    path "multiqc.command.sh", emit: command

    script:
    def report_args = reports.collect { report -> "'${report}'" }.join(' ')
    """
    set -euo pipefail
    mkdir qc_reports
    cp -L ${report_args} qc_reports/
    multiqc --force --filename multiqc_report.html --outdir . \
        --module fastqc --module samtools --module picard --module mosdepth --require-logs qc_reports
    multiqc --version > multiqc.versions.txt 2>&1

    printf '{"task_id":null,"logical_artifact_id":"multiqc","process":"M3_MULTIQC","requested_cpus":%s,"requested_memory_bytes":%s,"requested_time_seconds":%s,"container":"ghcr.io/multiqc/multiqc@sha256:976be2094a3bc1dab7315ad03440d43aab09bf7756f84f3a92ef7ae1013e4bfd","architecture":"%s"}\n' ${task.cpus} ${task.memory.toBytes()} ${task.time.toSeconds()} "\$(uname -m)" > multiqc.resources.json
    cp .command.sh multiqc.command.sh
    """

    stub:
    """
    mkdir multiqc_data qc_reports
    printf '<html><body>STUB ONLY: biological processing not validated</body></html>\n' > multiqc_report.html
    printf '{"status":"stub_only"}\n' > multiqc_data/stub.json
    printf 'STUB_ONLY\n' > multiqc.versions.txt
    printf '{"status":"stub_only","process":"M3_MULTIQC"}\n' > multiqc.resources.json
    cp .command.sh multiqc.command.sh
    """
}
