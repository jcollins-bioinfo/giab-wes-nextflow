// Native observations remain private and require a provider task/image join.
def cloudObservationStart(task, process, label, inputs) {
    def metadata = groovy.json.JsonOutput.toJson([process: process, label: label,
        nextflow_task_id: task.id, attempt: task.attempt, declared_image: task.container,
        requested_cpus: task.cpus, requested_memory_bytes: task.memory.toBytes()])
    def quotedMetadata = "'" + metadata.replace("'", "'\"'\"'") + "'"
    """
    set -euo pipefail
    receipt_dir='receipt-${process}-${label}'
    mkdir "\$receipt_dir"
    date +%s > "\$receipt_dir/started.txt"
    printf '%s' ${quotedMetadata} | sed 's/}\$/,"architecture":"'"\$(uname -m)"'"}/' > "\$receipt_dir/task.json"
    cp .command.sh "\$receipt_dir/command.sh"
    observe_files() {
        for target in "\$@"; do
            if [ -d "\$target" ]; then find "\$target" -type f -print0; else printf '%s\\0' "\$target"; fi
        done | sort -z | while IFS= read -r -d '' artifact; do
            digest=\$(sha256sum -- "\$artifact" | cut -d ' ' -f 1)
            printf '%s\\t%s\\t%s\\n' "\$digest" "\$(stat -c %s -- "\$artifact")" "\$artifact"
        done
    }
    observe_files ${inputs} > "\$receipt_dir/inputs.tsv"
    """
}

def cloudObservationEnd(outputs, version) {
    """
    observe_files ${outputs} > "\$receipt_dir/outputs.tsv"
    ${version} > "\$receipt_dir/version.txt" 2>&1
    date +%s > "\$receipt_dir/completed.txt"
    """
}

def cloudModelObservation(filename) {
    """
    python3 - <<'PY' > "\$receipt_dir/${filename}"
import hashlib, json
from pathlib import Path
root = Path('/opt/models/wes')
names = ['fingerprint.pb', 'saved_model.pb', 'model.example_info.json', 'variables/variables.data-00000-of-00001', 'variables/variables.index']
files = []
for name in names:
    path = root / name
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    files.append({'filename': name, 'bytes': path.stat().st_size, 'sha256': digest.hexdigest()})
print(json.dumps({'model_type': 'WES', 'model_files': files}, sort_keys=True))
PY
    """
}

process CLOUD_AUTHENTICATE {
    label 'cloud_support'
    // Mutable S3 keys must be rehashed even when downstream work is resumed.
    cache false
    input:
    path manifest, stageAs: 'manifest.json'
    path input_files, stageAs: 'inputs/*'
    val manifest_sha256
    val backend
    output:
    path 'authenticated/reads', emit: reads
    path 'authenticated/reference', emit: reference
    path 'authenticated/index', emit: index
    path 'authenticated/known', emit: known
    path 'authenticated/domain', emit: domain
    path 'authenticated/truth', emit: truth
    path 'authenticated/authentication.json', emit: receipt
    path "receipt-CLOUD_AUTHENTICATE-shared", emit: observation
    script:
    """
    ${cloudObservationStart(task, "CLOUD_AUTHENTICATE", "shared", "\"manifest.json\" \"inputs\"")}
    python -I -m giab_wes_nextflow.cloud_science authenticate --manifest manifest.json --manifest-sha256 '${manifest_sha256}' --backend '${backend}' --inputs inputs --output authenticated
    ${cloudObservationEnd("\"authenticated/authentication.json\"", "python -I -c 'from giab_wes_nextflow import __version__; print(__version__)'")}
    """
}

process CLOUD_BWA_ALIGN {
    label 'cloud_bwa'
    input:
    path reads
    path reference
    output:
    path 'aligned.sam', emit: alignment
    path 'bwa.version.txt', emit: version
    path "receipt-CLOUD_BWA_ALIGN-shared", emit: observation
    script:
    """
    ${cloudObservationStart(task, "CLOUD_BWA_ALIGN", "shared", "\"${reads}\" \"${reference}\"")}
    test "\$(uname -m)" = x86_64
    (bwa 2>&1 || test \$? = 1) > bwa.version.txt
    grep -q '^Version: 0.7.17-r1188' bwa.version.txt
    bwa mem -t ${task.cpus} -R '@RG\\tID:NIST7035.L001\\tSM:HG001\\tLB:NIST7035\\tPL:ILLUMINA\\tPU:NIST7035.L001' ${reference}/reference.fa ${reads}/reads_1.fastq.gz ${reads}/reads_2.fastq.gz > aligned.sam
    ${cloudObservationEnd("\"aligned.sam\"", "cat bwa.version.txt")}
    """
}

process CLOUD_SORT {
    label 'cloud_samtools'
    input:
    path alignment
    output:
    path 'sorted.bam', emit: bam
    path "receipt-CLOUD_SORT-shared", emit: observation
    script:
    """
    ${cloudObservationStart(task, "CLOUD_SORT", "shared", "\"${alignment}\"")}
    samtools --version > samtools.version.txt
    grep -q '^samtools 1.24\$' samtools.version.txt
    samtools sort -@ ${task.cpus} -m 512M -T sorttmp -o sorted.bam ${alignment}
    samtools quickcheck -v sorted.bam
    ${cloudObservationEnd("\"sorted.bam\"", "cat samtools.version.txt")}
    """
}

process CLOUD_MARK_DUPLICATES {
    label 'cloud_gatk'
    input:
    path sorted
    output:
    path 'marked.bam', emit: bam
    path 'marked.bai', emit: bai
    path 'duplicates.txt', emit: metrics
    path "receipt-CLOUD_MARK_DUPLICATES-shared", emit: observation
    script:
    """
    ${cloudObservationStart(task, "CLOUD_MARK_DUPLICATES", "shared", "\"${sorted}\"")}
    gatk --version > gatk.version.txt 2>&1
    grep -q '4.7.0.0' gatk.version.txt
    gatk --java-options '-Xmx16g -Djava.io.tmpdir=.' MarkDuplicates -I ${sorted} -O marked.bam -M duplicates.txt --REMOVE_DUPLICATES false --REMOVE_SEQUENCING_DUPLICATES false --READ_NAME_REGEX null --CREATE_INDEX true --VALIDATION_STRINGENCY STRICT
    ${cloudObservationEnd("\"marked.bam\" \"marked.bai\" \"duplicates.txt\"", "cat gatk.version.txt")}
    """
}

process CLOUD_BQSR {
    label 'cloud_gatk'
    input:
    path marked
    path marked_index
    path reference
    path known
    output:
    path 'shared.bam', emit: bam
    path 'recal.table', emit: table
    path "receipt-CLOUD_BQSR-shared", emit: observation
    script:
    """
    ${cloudObservationStart(task, "CLOUD_BQSR", "shared", "\"${marked}\" \"${marked_index}\" \"${reference}\" \"${known}\"")}
    gatk --java-options '-Xmx16g -Djava.io.tmpdir=.' BaseRecalibrator -R ${reference}/reference.fa -I ${marked} --known-sites ${known}/bqsr_dbsnp138.no-alt.vcf.gz --known-sites ${known}/bqsr_known_indels.no-alt.vcf.gz --known-sites ${known}/bqsr_mills.no-alt.vcf.gz -O recal.table
    gatk --java-options '-Xmx16g -Djava.io.tmpdir=.' ApplyBQSR -R ${reference}/reference.fa -I ${marked} --bqsr-recal-file recal.table --emit-original-quals true --create-output-bam-index false -O shared.bam
    ${cloudObservationEnd("\"shared.bam\" \"recal.table\"", "gatk --version")}
    """
}

process CLOUD_BAM_OBSERVATIONS {
    label 'cloud_samtools'
    input:
    path bam
    output:
    path 'observations', emit: observations
    path "receipt-CLOUD_BAM_OBSERVATIONS-shared", emit: observation
    script:
    """
    ${cloudObservationStart(task, "CLOUD_BAM_OBSERVATIONS", "shared", "\"${bam}\"")}
    mkdir observations
    mv ${bam} observations/shared.bam
    cd observations
    samtools index -@ ${task.cpus} shared.bam
    samtools quickcheck -v shared.bam > quickcheck.txt
    samtools view -H shared.bam > header.sam
    samtools view shared.bam > records.sam
    samtools view -c -F 4 shared.bam > mapped.txt
    samtools view -c -F 2304 shared.bam > primary.txt
    samtools idxstats shared.bam > idxstats.txt
    samtools coverage shared.bam > coverage.tsv
    cd ..
    ${cloudObservationEnd("\"observations\"", "samtools --version")}
    """
}

process CLOUD_BAM_GATE {
    label 'cloud_support'
    input:
    path observations
    path reference
    path authentication
    output:
    path 'shared', emit: shared
    path 'shared-bam.json', emit: receipt
    path "receipt-CLOUD_BAM_GATE-shared", emit: observation
    script:
    """
    ${cloudObservationStart(task, "CLOUD_BAM_GATE", "shared", "\"${observations}/shared.bam\" \"${observations}/shared.bam.bai\" \"${reference}\" \"${authentication}\"")}
    python -I -m giab_wes_nextflow.cloud_science bam-gate --directory ${observations} --reference ${reference}/reference.fa --authentication ${authentication} --output shared-bam.json
    mkdir shared
    mv ${observations}/shared.bam ${observations}/shared.bam.bai shared/
    ${cloudObservationEnd("\"shared\" \"shared-bam.json\"", "python -I -c 'from giab_wes_nextflow import __version__; print(__version__)'")}
    """
}

process CLOUD_GATK_CALL {
    label 'cloud_gatk'
    input:
    path shared
    path reference
    path domain
    output:
    tuple val('gatk'), path('raw.vcf.gz'), emit: vcf
    path 'gatk-inputs.sha256', emit: identity
    path "receipt-CLOUD_GATK_CALL-gatk", emit: observation
    script:
    """
    ${cloudObservationStart(task, "CLOUD_GATK_CALL", "gatk", "\"${shared}\" \"${reference}\" \"${domain}\"")}
    sha256sum ${shared}/shared.bam ${shared}/shared.bam.bai ${reference}/reference.fa ${reference}/reference.fa.fai ${reference}/reference.dict ${domain}/regions.bed > gatk-inputs.sha256
    gatk --java-options '-Xmx16g -Djava.io.tmpdir=.' HaplotypeCaller -R ${reference}/reference.fa -I ${shared}/shared.bam -L ${domain}/regions.bed -O raw.vcf.gz --sample-name HG001 --native-pair-hmm-threads ${task.cpus} --standard-min-confidence-threshold-for-calling 30.0 --emit-ref-confidence NONE
    sha256sum -c gatk-inputs.sha256
    ${cloudObservationEnd("\"raw.vcf.gz\"", "gatk --version")}
    """
}

process CLOUD_DEEPVARIANT_CALL {
    label 'cloud_deepvariant'
    input:
    path shared
    path reference
    path domain
    output:
    tuple val('deepvariant'), path('raw.vcf.gz'), emit: vcf
    path 'deepvariant-inputs.sha256', emit: identity
    path "receipt-CLOUD_DEEPVARIANT_CALL-deepvariant", emit: observation
    script:
    """
    ${cloudObservationStart(task, "CLOUD_DEEPVARIANT_CALL", "deepvariant", "\"${shared}\" \"${reference}\" \"${domain}\"")}
    test "\$(uname -m)" = x86_64
    for flag in sse4_1 sse4_2 avx; do grep -qw "\$flag" /proc/cpuinfo; done
    sha256sum ${shared}/shared.bam ${shared}/shared.bam.bai ${reference}/reference.fa ${reference}/reference.fa.fai ${reference}/reference.dict ${domain}/regions.bed > deepvariant-inputs.sha256
    ${cloudModelObservation("model-before.json")}
    /opt/deepvariant/bin/run_deepvariant --model_type=WES --ref=${reference}/reference.fa --reads=${shared}/shared.bam --regions=${domain}/regions.bed --sample_name=HG001 --num_shards=${task.cpus} --postprocess_cpus=0 --make_examples_extra_args=use_original_quality_scores=true --output_vcf=raw.vcf.gz --intermediate_results_dir=intermediate --logging_dir=deepvariant.logs
    sha256sum -c deepvariant-inputs.sha256
    ${cloudModelObservation("model-after.json")}
    ${cloudObservationEnd("\"raw.vcf.gz\"", "/opt/deepvariant/bin/run_deepvariant --version")}
    """
}

process CLOUD_PREPARE_TRUTH {
    label 'cloud_bcftools'
    input:
    path truth
    output:
    tuple val('truth'), path('raw.vcf.gz'), emit: vcf
    path "receipt-CLOUD_PREPARE_TRUTH-truth", emit: observation
    script:
    """
    ${cloudObservationStart(task, "CLOUD_PREPARE_TRUTH", "truth", "\"${truth}\"")}
    bcftools view --no-version -r chr20,chr21,chr22 -Oz -o raw.vcf.gz ${truth}/truth.vcf.gz
    test "\$(bcftools query -l raw.vcf.gz)" = HG001
    ${cloudObservationEnd("\"raw.vcf.gz\"", "bcftools --version")}
    """
}

process CLOUD_NORMALIZE {
    tag "$source"
    label 'cloud_bcftools'
    input:
    tuple val(source), path(vcf)
    path reference
    output:
    tuple val(source), path('sorted.vcf'), emit: vcf
    path "receipt-CLOUD_NORMALIZE-${source}", emit: observation
    script:
    """
    ${cloudObservationStart(task, "CLOUD_NORMALIZE", "${source}", "\"${vcf}\" \"${reference}\"")}
    test "\$(bcftools query -l ${vcf})" = HG001
    bcftools index -f -t ${vcf}
    bcftools view -H ${vcf} > sequential.txt
    bcftools view -H -r "\$(cut -f1 ${reference}/reference.fa.fai | paste -sd, -)" ${vcf} > indexed.txt
    cmp sequential.txt indexed.txt
    bcftools norm -f ${reference}/reference.fa -c e -m -any --multi-overlaps 0 --old-rec-tag M5_ORIG --no-version -Ov -o split.vcf ${vcf}
    bcftools sort -Ov -o sorted.vcf split.vcf
    ${cloudObservationEnd("\"sorted.vcf\"", "bcftools --version")}
    """
}

process CLOUD_INCLUDE {
    tag "$source"
    label 'cloud_support'
    input:
    tuple val(source), path(sorted)
    path reference
    output:
    tuple val(source), path('included.vcf'), emit: vcf
    path "receipt-CLOUD_INCLUDE-${source}", emit: observation
    script:
    """
    ${cloudObservationStart(task, "CLOUD_INCLUDE", "${source}", "\"${sorted}\" \"${reference}\"")}
    python -I -m giab_wes_nextflow.cloud_science include --source ${sorted} --reference ${reference}/reference.fa --output included.vcf
    ${cloudObservationEnd("\"included.vcf\" \"included.json\"", "python -I -c 'from giab_wes_nextflow import __version__; print(__version__)'")}
    """
}

process CLOUD_COMPRESS {
    tag "$source"
    label 'cloud_bcftools'
    input:
    tuple val(source), path(included)
    path reference
    output:
    tuple val(source), path('normalized.vcf.gz'), path('normalized.vcf.gz.tbi'), emit: vcf
    path "receipt-CLOUD_COMPRESS-${source}", emit: observation
    script:
    """
    ${cloudObservationStart(task, "CLOUD_COMPRESS", "${source}", "\"${included}\" \"${reference}\"")}
    bcftools view --no-version -Oz -o normalized.vcf.gz ${included}
    bcftools index -t normalized.vcf.gz
    bcftools view -H normalized.vcf.gz > sequential.txt
    bcftools view -H -r "\$(cut -f1 ${reference}/reference.fa.fai | paste -sd, -)" normalized.vcf.gz > indexed.txt
    cmp sequential.txt indexed.txt
    ${cloudObservationEnd("\"normalized.vcf.gz\" \"normalized.vcf.gz.tbi\"", "bcftools --version")}
    """
}

process CLOUD_RTG_REFERENCE {
    label 'cloud_rtg'
    input:
    path reference
    output:
    path 'reference.sdf', emit: reference
    path "receipt-CLOUD_RTG_REFERENCE-shared", emit: observation
    script:
    """
    ${cloudObservationStart(task, "CLOUD_RTG_REFERENCE", "shared", "\"${reference}\"")}
    rtg version > rtg.version.txt
    grep -q '3.13' rtg.version.txt
    rtg format -o reference.sdf ${reference}/reference.fa
    ${cloudObservationEnd("\"reference.sdf\"", "cat rtg.version.txt")}
    """
}

process CLOUD_VCFEVAL {
    tag "$caller"
    label 'cloud_rtg'
    input:
    tuple val(caller), path(query, stageAs: 'query.vcf.gz'), path(query_index, stageAs: 'query.vcf.gz.tbi')
    tuple val(truth_label), path(baseline, stageAs: 'baseline.vcf.gz'), path(baseline_index, stageAs: 'baseline.vcf.gz.tbi')
    path sdf
    path truth_domain
    output:
    path "${caller}", emit: partitions
    path "receipt-CLOUD_VCFEVAL-${caller}", emit: observation
    script:
    """
    ${cloudObservationStart(task, "CLOUD_VCFEVAL", "${caller}", "\"query.vcf.gz\" \"query.vcf.gz.tbi\" \"baseline.vcf.gz\" \"baseline.vcf.gz.tbi\" \"${sdf}\" \"${truth_domain}\"")}
    rtg vcfeval -b baseline.vcf.gz -c query.vcf.gz -t ${sdf} -o ${caller} --evaluation-regions ${truth_domain}/evaluation.bed --sample HG001 --all-records --ref-overlap --output-mode split --no-roc --sample-ploidy 2 --threads ${task.cpus}
    ${cloudObservationEnd("\"${caller}\"", "rtg version")}
    """
}

process CLOUD_COLLECT {
    label 'cloud_support'
    input:
    path caller_identities
    path partitions
    path reference
    path shared_receipt
    path authentication
    path task_observations, stageAs: 'task-receipts/*'
    output:
    path 'cloud-evidence.json', emit: evidence
    path "receipt-CLOUD_COLLECT-shared", emit: observation
    script:
    """
    ${cloudObservationStart(task, "CLOUD_COLLECT", "shared", "\"${shared_receipt}\" \"${authentication}\"")}
    python -I -m giab_wes_nextflow.cloud_science collect --caller-identities gatk-inputs.sha256 deepvariant-inputs.sha256 --partitions gatk deepvariant --reference ${reference}/reference.fa --shared-receipt ${shared_receipt} --authentication ${authentication} --task-observations task-receipts/* --output cloud-evidence.json
    ${cloudObservationEnd("\"cloud-evidence.json\"", "python -I -c 'from giab_wes_nextflow import __version__; print(__version__)'")}
    """
}
