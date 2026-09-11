// Executes the actual cloud modules on a byte-frozen, separately typed fixture.
// Package with this file's relative path and cloud-dag.config; never cloud.nf.
params.seed = null
params.cloud_repository_sha = null
params.cloud_support_image = null
params.bwa_image = null
params.samtools_image = null
params.gatk_image = null
params.deepvariant_image = null
params.bcftools_image = null
params.rtg_image = null

include { CLOUD_AUTHENTICATE; CLOUD_BWA_ALIGN; CLOUD_SORT; CLOUD_MARK_DUPLICATES; CLOUD_BQSR; CLOUD_BAM_OBSERVATIONS; CLOUD_BAM_GATE; CLOUD_GATK_CALL; CLOUD_DEEPVARIANT_CALL; CLOUD_PREPARE_TRUTH; CLOUD_NORMALIZE; CLOUD_INCLUDE; CLOUD_COMPRESS; CLOUD_RTG_REFERENCE; CLOUD_VCFEVAL; CLOUD_COLLECT } from '../../modules/local/cloud/tasks'

process QUALIFICATION_FIXTURE {
    label 'cloud_support'
    input:
    path seed
    output:
    path 'fixture'
    script:
    """
    test "\$(cat ${seed})" = giab-managed-nonhuman-qualification-v1
    python -I -m giab_wes_nextflow.cloud_qualification generate --output fixture
    """
}

process QUALIFICATION_INDEX {
    label 'cloud_bwa'
    input:
    path fixture
    output:
    path 'indexed'
    script:
    """
    cp -r ${fixture} indexed
    cd indexed
    test "\$(uname -m)" = x86_64
    (bwa 2>&1 || test \$? = 1) > bwa.version.txt
    grep -q '^Version: 0.7.17-r1188' bwa.version.txt
    bwa index -a bwtsw reference.fa
    """
}

process QUALIFICATION_VCFS {
    label 'cloud_bcftools'
    input:
    path indexed
    output:
    path 'prepared'
    script:
    """
    cp -r ${indexed} prepared
    cd prepared
    bcftools --version > bcftools.version.txt
    grep -q '^bcftools 1.24\$' bcftools.version.txt
    bcftools view --no-version -Oz -o truth.vcf.gz truth.vcf
    bcftools index -t truth.vcf.gz
    for name in bqsr_dbsnp138 bqsr_known_indels bqsr_mills; do
        bcftools view --no-version -Oz -o "\$name.no-alt.vcf.gz" known-sites.vcf
        bcftools index -t "\$name.no-alt.vcf.gz"
    done
    """
}

process QUALIFICATION_MANIFEST {
    label 'cloud_support'
    input:
    path prepared
    val repository_sha
    output:
    path 'manifested/manifest.json', emit: manifest
    path 'manifested/manifest.sha256', emit: digest
    path 'manifested/inputs/*', emit: files
    script:
    """
    python -I -m giab_wes_nextflow.cloud_qualification manifest --input ${prepared} --output manifested --repository-sha '${repository_sha}'
    """
}

process QUALIFICATION_ACCEPT {
    label 'cloud_support'
    input:
    path evidence
    output:
    path 'cloud-dag-qualification.json'
    script:
    """
    python -I -m giab_wes_nextflow.cloud_qualification accept --input ${evidence} --output cloud-dag-qualification.json
    """
}

workflow {
    main:
    if (!(params.cloud_repository_sha ==~ /[0-9a-f]{40}/)) error('Exact qualification source SHA required')
    if (params.cloud_backend != 'healthomics') error('Use the isolated HealthOmics qualification configuration')
    fixture = QUALIFICATION_FIXTURE(file(params.seed, checkIfExists: true))
    indexed = QUALIFICATION_INDEX(fixture)
    prepared = QUALIFICATION_VCFS(indexed)
    manifest = QUALIFICATION_MANIFEST(prepared,params.cloud_repository_sha)
    authenticated = CLOUD_AUTHENTICATE(manifest.manifest,manifest.files,manifest.digest.map { it.text.trim() },params.cloud_backend)
    reference = authenticated.reference.first()
    domain = authenticated.domain.first()
    truthAssets = authenticated.truth.first()
    authentication = authenticated.receipt.first()
    aligned = CLOUD_BWA_ALIGN(authenticated.reads,authenticated.index)
    sorted = CLOUD_SORT(aligned.alignment)
    marked = CLOUD_MARK_DUPLICATES(sorted.bam)
    recalibrated = CLOUD_BQSR(marked.bam,marked.bai,reference,authenticated.known)
    observed = CLOUD_BAM_OBSERVATIONS(recalibrated.bam)
    validated = CLOUD_BAM_GATE(observed.observations,reference,authentication)
    shared = validated.shared.first()
    gatk = CLOUD_GATK_CALL(shared,reference,domain)
    deepvariant = CLOUD_DEEPVARIANT_CALL(shared,reference,domain)
    truth = CLOUD_PREPARE_TRUTH(truthAssets)
    normalized = CLOUD_NORMALIZE(gatk.vcf.mix(deepvariant.vcf,truth.vcf),reference)
    included = CLOUD_INCLUDE(normalized.vcf,reference)
    compressed = CLOUD_COMPRESS(included.vcf,reference)
    split = compressed.vcf.branch { source, _vcf, _index ->
        truth: source == 'truth'
        query: true
    }
    baseline = split.truth.first()
    sdf = CLOUD_RTG_REFERENCE(reference)
    benchmark = CLOUD_VCFEVAL(split.query,baseline,sdf.reference.first(),truthAssets)
    observations = authenticated.observation.mix(aligned.observation,sorted.observation,marked.observation,
        recalibrated.observation,observed.observation,validated.observation,gatk.observation,
        deepvariant.observation,truth.observation,normalized.observation,included.observation,
        compressed.observation,sdf.observation,benchmark.observation)
    evidence = CLOUD_COLLECT(gatk.identity.mix(deepvariant.identity).collect(),benchmark.partitions.collect(),
        reference,validated.receipt,authentication,observations.collect())
    accepted = QUALIFICATION_ACCEPT(evidence.evidence)
    publish:
    qualification = accepted
    private_evidence = evidence.evidence
    task_observations = observations.mix(evidence.observation)
    normalized_calls = compressed.vcf
    benchmark_partitions = benchmark.partitions
}

output {
    qualification { path 'qualification' }
    private_evidence { path 'private-nonhuman/evidence' }
    task_observations { path 'private-nonhuman/tasks' }
    normalized_calls { path { caller, _vcf, _index -> "private-nonhuman/${caller}/normalized" } }
    benchmark_partitions { path 'private-nonhuman/benchmark' }
}
