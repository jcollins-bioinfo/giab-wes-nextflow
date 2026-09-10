include { CLOUD_AUTHENTICATE; CLOUD_BWA_ALIGN; CLOUD_SORT; CLOUD_MARK_DUPLICATES; CLOUD_BQSR; CLOUD_BAM_OBSERVATIONS; CLOUD_BAM_GATE; CLOUD_GATK_CALL; CLOUD_DEEPVARIANT_CALL; CLOUD_PREPARE_TRUTH; CLOUD_NORMALIZE; CLOUD_INCLUDE; CLOUD_COMPRESS; CLOUD_RTG_REFERENCE; CLOUD_VCFEVAL; CLOUD_COLLECT } from './modules/local/cloud/tasks'

workflow {
    main:
    if (params.cloud_allow_spend != true) error('Cloud scheduling is disabled; separately authorize spend after quota, identity, engine and scientific preflight')
    if (!(params.cloud_backend in ['awsbatch', 'healthomics'])) error('Choose cloud_awsbatch or cloud_healthomics profile')
    if (!(params.cloud_support_image ==~ /[^\s]+@sha256:[0-9a-f]{64}/)) error('Published digest-pinned support image required')
    if (!(params.cloud_manifest_sha256 ==~ /[0-9a-f]{64}/) || !(params.cloud_repository_sha ==~ /[0-9a-f]{40}/)) error('Reviewed manifest and source SHA required')
    if (!params.cloud_manifest) error('Authenticated cloud input manifest required')
    if (params.cloud_backend == 'awsbatch' && (params.cloud_batch_queue == 'CONFIGURED_ONLY_NOT_AUTHORIZED' || !params.cloud_batch_job_role || !params.cloud_batch_benchmark_job_role)) error('Configured Batch queue and separate execution/benchmark roles required')
    manifest = file(params.cloud_manifest, checkIfExists: true)
    manifestDigest = java.security.MessageDigest.getInstance('SHA-256').digest(manifest.bytes).encodeHex().toString()
    if (manifestDigest != params.cloud_manifest_sha256) error('Cloud manifest SHA differs before staging')
    specification = new groovy.json.JsonSlurper().parseText(manifest.text)
    if (specification.repository_sha != params.cloud_repository_sha) error('Cloud input qualification source SHA differs')
    if (specification.sample != 'HG001' || specification.scope != 'hg001_chr20_22_coding') error('Unapproved canonical sample/scope')
    pins = [:]
    ['m3-tools', 'm4-tools', 'm5-tools'].each { name ->
        new groovy.json.JsonSlurper().parseText(file("${projectDir}/config/${name}.json").text).tools.each { tool, record -> pins[tool] = record.image }
    }
    pins.bwa = new groovy.json.JsonSlurper().parseText(file("${projectDir}/config/canonical-assets.json").text).aligner.image
    params.cloud_images.each { tool, image ->
        if (!pins.containsKey(tool) || image.split('@sha256:')[-1] != pins[tool].split('@sha256:')[-1] || !(image ==~ /[^\s]+@sha256:[0-9a-f]{64}/)) error("Unreviewed scientific image: ${tool}")
    }
    if (params.cloud_backend == 'awsbatch') {
        if (!params.cloud_batch_definitions_receipt || !(params.cloud_batch_definitions_receipt_sha256 ==~ /[0-9a-f]{64}/)) error('Read-only verified Batch definition receipt and SHA required')
        proofFile = file(params.cloud_batch_definitions_receipt, checkIfExists: true)
        proofDigest = java.security.MessageDigest.getInstance('SHA-256').digest(proofFile.bytes).encodeHex().toString()
        if (proofDigest != params.cloud_batch_definitions_receipt_sha256) error('Batch definition receipt SHA differs')
        proof = new groovy.json.JsonSlurper().parseText(proofFile.text)
        proofAge = java.time.Duration.between(java.time.Instant.parse(proof.observed_at), java.time.Instant.now()).seconds
        if (proofAge < 0 || proofAge > 3600 || proof.region != 'us-west-2') error('Batch job definition verification expired or wrong region; rerun batch_check.py')
        if (proof.ordinary_role != params.cloud_batch_job_role || proof.benchmark_role != params.cloud_batch_benchmark_job_role) error('Batch receipt role identity differs')
        expectedKeys = ['support', 'support-benchmark', 'bwa', 'samtools', 'gatk', 'deepvariant', 'bcftools', 'bcftools-benchmark', 'rtg', 'rtg-benchmark']
        if (proof.kind != 'cloud_batch_definitions' || proof.status != 'verified' || proof.definitions.keySet() != expectedKeys.toSet() || params.cloud_batch_job_definitions.keySet() != expectedKeys.toSet()) error('Incomplete verified Batch definitions')
        if (params.cloud_batch_job_role == params.cloud_batch_benchmark_job_role) error('Caller and benchmark IAM roles must differ')
        proof.definitions.each { key, definition ->
            def tool = key.replace('-benchmark', '')
            def expectedImage = tool == 'support' ? params.cloud_support_image : (params.cloud_images[tool] ?: pins[tool])
            def expectedRole = key.endsWith('-benchmark') ? params.cloud_batch_benchmark_job_role : params.cloud_batch_job_role
            if (definition.image != expectedImage || definition.job_role_arn != expectedRole || params.cloud_batch_job_definitions[key] != "job-definition://${definition.name}" || !(definition.name ==~ /[A-Za-z0-9_-]+:[1-9][0-9]*/)) error("Batch image, role or revision differs: ${key}")
        }
    }
    inputFiles = (specification.assets.values() + specification.qualifications.values()).collect { item -> file(item.uri, checkIfExists: true) }
    authenticated = CLOUD_AUTHENTICATE(manifest, inputFiles, params.cloud_manifest_sha256, params.cloud_backend)
    // Value channels broadcast singleton assets into every downstream task.
    reference = authenticated.reference.first()
    domain = authenticated.domain.first()
    truthAssets = authenticated.truth.first()
    authentication = authenticated.receipt.first()
    aligned = CLOUD_BWA_ALIGN(authenticated.reads, authenticated.index)
    sorted = CLOUD_SORT(aligned.alignment)
    marked = CLOUD_MARK_DUPLICATES(sorted)
    recalibrated = CLOUD_BQSR(marked.bam, marked.bai, reference, authenticated.known)
    observed = CLOUD_BAM_OBSERVATIONS(recalibrated.bam)
    validated = CLOUD_BAM_GATE(observed, reference, authentication)
    shared = validated.shared.first()
    gatk = CLOUD_GATK_CALL(shared, reference, domain)
    deepvariant = CLOUD_DEEPVARIANT_CALL(shared, reference, domain)
    truth = CLOUD_PREPARE_TRUTH(truthAssets)
    normalized = CLOUD_NORMALIZE(gatk.vcf.mix(deepvariant.vcf, truth), reference)
    included = CLOUD_INCLUDE(normalized, reference)
    compressed = CLOUD_COMPRESS(included, reference)
    split = compressed.branch { source, _vcf, _index ->
        truth: source == 'truth'
        query: true
    }
    baseline = split.truth.first()
    sdf = CLOUD_RTG_REFERENCE(reference).first()
    benchmark = CLOUD_VCFEVAL(split.query, baseline, sdf, truthAssets)
    evidence = CLOUD_COLLECT(gatk.identity.mix(deepvariant.identity).collect(), benchmark.partitions.collect(), reference, validated.receipt, authentication)
    publish:
    private_evidence = evidence
    shared_bam = validated.shared
    raw_calls = gatk.vcf.mix(deepvariant.vcf)
    normalized_calls = compressed
    benchmark_partitions = benchmark.partitions
}

output {
    private_evidence { path 'cloud/private/evidence' }
    shared_bam { path 'cloud/private/shared' }
    raw_calls { path { caller, _vcf -> "cloud/private/${caller}/native" } }
    normalized_calls { path { caller, _vcf, _index -> "cloud/private/${caller}/normalized" } }
    benchmark_partitions { path 'cloud/private/benchmark' }
}
