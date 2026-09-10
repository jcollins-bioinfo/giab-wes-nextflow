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
    script:
    """
    python -I -m giab_wes_nextflow.cloud_science authenticate --manifest manifest.json --manifest-sha256 '${manifest_sha256}' --backend '${backend}' --inputs inputs --output authenticated
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
    script:
    """
    test "\$(uname -m)" = x86_64
    (bwa 2>&1 || test \$? = 1) > bwa.version.txt
    grep -q '^Version: 0.7.17-r1188' bwa.version.txt
    bwa mem -t ${task.cpus} -R '@RG\\tID:NIST7035.L001\\tSM:HG001\\tLB:NIST7035\\tPL:ILLUMINA\\tPU:NIST7035.L001' ${reference}/reference.fa ${reads}/reads_1.fastq.gz ${reads}/reads_2.fastq.gz > aligned.sam
    """
}

process CLOUD_SORT {
    label 'cloud_samtools'
    input:
    path alignment
    output:
    path 'sorted.bam'
    script:
    """
    samtools --version > samtools.version.txt
    grep -q '^samtools 1.24\$' samtools.version.txt
    samtools sort -@ ${task.cpus} -m 512M -T sorttmp -o sorted.bam ${alignment}
    samtools quickcheck -v sorted.bam
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
    script:
    """
    gatk --version > gatk.version.txt 2>&1
    grep -q '4.7.0.0' gatk.version.txt
    gatk --java-options '-Xmx16g -Djava.io.tmpdir=.' MarkDuplicates -I ${sorted} -O marked.bam -M duplicates.txt --REMOVE_DUPLICATES false --REMOVE_SEQUENCING_DUPLICATES false --READ_NAME_REGEX null --CREATE_INDEX true --VALIDATION_STRINGENCY STRICT
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
    script:
    """
    gatk --java-options '-Xmx16g -Djava.io.tmpdir=.' BaseRecalibrator -R ${reference}/reference.fa -I ${marked} --known-sites ${known}/bqsr_dbsnp138.no-alt.vcf.gz --known-sites ${known}/bqsr_known_indels.no-alt.vcf.gz --known-sites ${known}/bqsr_mills.no-alt.vcf.gz -O recal.table
    gatk --java-options '-Xmx16g -Djava.io.tmpdir=.' ApplyBQSR -R ${reference}/reference.fa -I ${marked} --bqsr-recal-file recal.table --emit-original-quals true --create-output-bam-index false -O shared.bam
    """
}

process CLOUD_BAM_OBSERVATIONS {
    label 'cloud_samtools'
    input:
    path bam
    output:
    path 'observations'
    script:
    """
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
    script:
    """
    python -I -m giab_wes_nextflow.cloud_science bam-gate --directory ${observations} --reference ${reference}/reference.fa --authentication ${authentication} --output shared-bam.json
    mkdir shared
    mv ${observations}/shared.bam ${observations}/shared.bam.bai shared/
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
    script:
    """
    sha256sum ${shared}/shared.bam ${shared}/shared.bam.bai ${reference}/reference.fa ${reference}/reference.fa.fai ${reference}/reference.dict ${domain}/regions.bed > gatk-inputs.sha256
    gatk --java-options '-Xmx16g -Djava.io.tmpdir=.' HaplotypeCaller -R ${reference}/reference.fa -I ${shared}/shared.bam -L ${domain}/regions.bed -O raw.vcf.gz --sample-name HG001 --native-pair-hmm-threads ${task.cpus} --standard-min-confidence-threshold-for-calling 30.0 --emit-ref-confidence NONE
    sha256sum -c gatk-inputs.sha256
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
    script:
    """
    test "\$(uname -m)" = x86_64
    for flag in sse4_1 sse4_2 avx; do grep -qw "\$flag" /proc/cpuinfo; done
    sha256sum ${shared}/shared.bam ${shared}/shared.bam.bai ${reference}/reference.fa ${reference}/reference.fa.fai ${reference}/reference.dict ${domain}/regions.bed > deepvariant-inputs.sha256
    /opt/deepvariant/bin/run_deepvariant --model_type=WES --ref=${reference}/reference.fa --reads=${shared}/shared.bam --regions=${domain}/regions.bed --sample_name=HG001 --num_shards=${task.cpus} --postprocess_cpus=0 --make_examples_extra_args=use_original_quality_scores=true --output_vcf=raw.vcf.gz --intermediate_results_dir=intermediate --logging_dir=deepvariant.logs
    sha256sum -c deepvariant-inputs.sha256
    """
}

process CLOUD_PREPARE_TRUTH {
    label 'cloud_bcftools'
    input:
    path truth
    output:
    tuple val('truth'), path('raw.vcf.gz')
    script:
    """
    bcftools view --no-version -r chr20,chr21,chr22 -Oz -o raw.vcf.gz ${truth}/truth.vcf.gz
    test "\$(bcftools query -l raw.vcf.gz)" = HG001
    """
}

process CLOUD_NORMALIZE {
    tag "$source"
    label 'cloud_bcftools'
    input:
    tuple val(source), path(vcf)
    path reference
    output:
    tuple val(source), path('sorted.vcf')
    script:
    """
    test "\$(bcftools query -l ${vcf})" = HG001
    bcftools index -f -t ${vcf}
    bcftools view -H ${vcf} > sequential.txt
    bcftools view -H -r "\$(cut -f1 ${reference}/reference.fa.fai | paste -sd, -)" ${vcf} > indexed.txt
    cmp sequential.txt indexed.txt
    bcftools norm -f ${reference}/reference.fa -c e -m -any --multi-overlaps 0 --old-rec-tag M5_ORIG --no-version -Ov -o split.vcf ${vcf}
    bcftools sort -Ov -o sorted.vcf split.vcf
    """
}

process CLOUD_INCLUDE {
    tag "$source"
    label 'cloud_support'
    input:
    tuple val(source), path(sorted)
    path reference
    output:
    tuple val(source), path('included.vcf')
    script:
    """
    python -I -m giab_wes_nextflow.cloud_science include --source ${sorted} --reference ${reference}/reference.fa --output included.vcf
    """
}

process CLOUD_COMPRESS {
    tag "$source"
    label 'cloud_bcftools'
    input:
    tuple val(source), path(included)
    path reference
    output:
    tuple val(source), path('normalized.vcf.gz'), path('normalized.vcf.gz.tbi')
    script:
    """
    bcftools view --no-version -Oz -o normalized.vcf.gz ${included}
    bcftools index -t normalized.vcf.gz
    bcftools view -H normalized.vcf.gz > sequential.txt
    bcftools view -H -r "\$(cut -f1 ${reference}/reference.fa.fai | paste -sd, -)" normalized.vcf.gz > indexed.txt
    cmp sequential.txt indexed.txt
    """
}

process CLOUD_RTG_REFERENCE {
    label 'cloud_rtg'
    input:
    path reference
    output:
    path 'reference.sdf'
    script:
    """
    rtg version > rtg.version.txt
    grep -q '3.13' rtg.version.txt
    rtg format -o reference.sdf ${reference}/reference.fa
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
    script:
    """
    rtg vcfeval -b baseline.vcf.gz -c query.vcf.gz -t ${sdf} -o ${caller} --evaluation-regions ${truth_domain}/evaluation.bed --sample HG001 --all-records --ref-overlap --output-mode split --no-roc --sample-ploidy 2 --threads ${task.cpus}
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
    output:
    path 'cloud-evidence.json'
    script:
    """
    python -I -m giab_wes_nextflow.cloud_science collect --caller-identities gatk-inputs.sha256 deepvariant-inputs.sha256 --partitions gatk deepvariant --reference ${reference}/reference.fa --shared-receipt ${shared_receipt} --authentication ${authentication} --output cloud-evidence.json
    """
}
