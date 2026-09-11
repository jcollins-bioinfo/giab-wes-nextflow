// Independent Broad BQSR resources; canonical completion requires durable rehash.
params.reference_fasta = null
params.reference_fai = null
params.reference_dictionary = null
params.reference_manifest = null
params.dbsnp = null
params.dbsnp_index = null
params.known_indels = null
params.known_indels_index = null
params.mills = null
params.mills_index = null
params.support_image = null
params.ecr_prefix = null

process FILTER_KNOWN_SITES {
    container params.support_image
    cpus 2
    memory '8 GB'
    time '3h'
    stageInMode 'copy'
    input:
    path reference_files
    path sources
    output:
    path 'filtered'
    script:
    """
    mkdir reference
    cp ${reference_files} reference/
    python -I -m giab_wes_nextflow.cloud_known_sites prepare --reference reference --sources ${sources} --output filtered
    """
}

process COMPRESS_KNOWN_SITES {
    container "${params.ecr_prefix}/bcftools@sha256:a3e0d3007ffe325c409b398f660840a3e7574d076219c6e82fc994ced87d47c3"
    cpus 2
    memory '8 GB'
    time '2h'
    input:
    path filtered
    output:
    path 'compressed'
    script:
    """
    mkdir compressed
    bcftools --version > compressed/compress.version.txt
    grep -q '^bcftools 1.24\$' compressed/compress.version.txt
    (cd ${filtered} && sha256sum -c filtered-inputs.sha256)
    cp ${filtered}/known-sites-preparation.json ${filtered}/contigs.txt ${filtered}/filtered-inputs.sha256 compressed/
    for source in ${filtered}/*.no-alt.vcf; do
        name=\$(basename "\$source")
        bcftools view --no-version -H "\$source" | sha256sum > "compressed/\$name.source-records.sha256"
        bcftools view --no-version -Oz -o "compressed/\$name.gz" "\$source"
    done
    """
}

process INDEX_VALIDATE_KNOWN_SITES {
    container "${params.ecr_prefix}/bcftools@sha256:a3e0d3007ffe325c409b398f660840a3e7574d076219c6e82fc994ced87d47c3"
    cpus 2
    memory '8 GB'
    time '2h'
    input:
    path compressed
    output:
    path 'indexed'
    script:
    """
    cp -r ${compressed} indexed
    cd indexed
    bcftools --version > index.version.txt
    grep -q '^bcftools 1.24\$' index.version.txt
    for source in *.no-alt.vcf.gz; do
        name=\${source%.gz}
        bcftools index --tbi --force "\$source"
        bcftools index --nrecords "\$source" > "\$name.count"
        bcftools view --no-version -H "\$source" | sha256sum > "\$name.sequential.sha256"
        bcftools view --no-version -H -r "\$(cat contigs.txt)" "\$source" | sha256sum > "\$name.indexed.sha256"
        cmp "\$name.source-records.sha256" "\$name.sequential.sha256"
        cmp "\$name.sequential.sha256" "\$name.indexed.sha256"
    done
    """
}

process ACCEPT_KNOWN_SITES {
    container params.support_image
    cpus 2
    memory '8 GB'
    time '1h'
    stageInMode 'copy'
    input:
    path indexed
    output:
    path 'known-sites', emit: assets
    path 'known-sites-validation.json', emit: receipt
    script:
    """
    python -I -m giab_wes_nextflow.cloud_known_sites accept --input ${indexed} --output known-sites
    """
}

workflow {
    main:
    reference_files = [params.reference_fasta,params.reference_fai,params.reference_dictionary,params.reference_manifest].collect { file(it) }
    sources = [params.dbsnp,params.dbsnp_index,params.known_indels,params.known_indels_index,params.mills,params.mills_index].collect { file(it) }
    filtered = FILTER_KNOWN_SITES(reference_files,sources)
    compressed = COMPRESS_KNOWN_SITES(filtered)
    indexed = INDEX_VALIDATE_KNOWN_SITES(compressed)
    accepted = ACCEPT_KNOWN_SITES(indexed)
    publish:
    known_sites = accepted.assets
    qualification = accepted.receipt
    native_evidence = indexed
}

output {
    known_sites { path 'private-known-sites' }
    qualification { path 'qualification' }
    native_evidence { path 'private-known-sites-native' }
}
