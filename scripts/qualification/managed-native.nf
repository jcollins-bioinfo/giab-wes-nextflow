// Nonhuman native-backend qualification. Never produces canonical HG001 results.
params.support_image = null
params.ecr_prefix = null
params.seed = null

process FIXTURE {
    container params.support_image
    cpus 2
    memory '8 GB'
    input:
    path seed
    output:
    path 'fixture'
    script:
    """
    test "\$(cat ${seed})" = giab-managed-nonhuman-qualification-v1
    python -I -m giab_wes_nextflow.m4_fixture --output fixture
    """
}

process ALIGN {
    container "${params.ecr_prefix}/bwa@sha256:c3a708bea7947a44288e675fd9791c7aaf0c97dba0710addba336ed193821f8a"
    cpus 2
    memory '8 GB'
    input:
    path fixture
    output:
    path 'aligned'
    script:
    """
    test "\$(uname -m)" = x86_64
    cp -r ${fixture} aligned
    cd aligned
    (bwa 2>&1 || test \$? = 1) > bwa.version.txt
    grep -q 'Version: 0.7.17-r1188' bwa.version.txt
    bwa index -a bwtsw reference.fa
    bwa mem -t 2 -R '@RG\\tID:SYN_L001\\tSM:SYNTHETIC01\\tLB:SYN_LIB\\tPL:ILLUMINA\\tPU:SYN_PU_L001' reference.fa reads_1.fastq.gz reads_2.fastq.gz > lane1.sam
    bwa mem -t 2 -R '@RG\\tID:SYN_L002\\tSM:SYNTHETIC01\\tLB:SYN_LIB\\tPL:ILLUMINA\\tPU:SYN_PU_L002' reference.fa reads_lane2_1.fastq.gz reads_lane2_2.fastq.gz > lane2.sam
    """
}

process SORT {
    container "${params.ecr_prefix}/samtools@sha256:a130447589651ed09252aa95a5e4f4132942cdb54d835d81a04a9a930d656561"
    cpus 2
    memory '8 GB'
    input:
    path aligned
    output:
    path 'sorted'
    script:
    """
    cp -r ${aligned} sorted
    cd sorted
    samtools --version > samtools.version.txt
    samtools faidx reference.fa
    samtools sort -@ 2 -o lane1.bam lane1.sam
    samtools sort -@ 2 -o lane2.bam lane2.sam
    samtools merge -@ 2 merged.bam lane1.bam lane2.bam
    samtools quickcheck -v merged.bam
    samtools index merged.bam
    """
}

process GATK {
    container "${params.ecr_prefix}/gatk@sha256:7da5cf586e1c463f0c72908f9ac7dec8c29e37912c82d6e7b3c250f27fcb3891"
    cpus 2
    memory '8 GB'
    input:
    path sorted
    output:
    path 'calls'
    script:
    """
    mkdir calls
    cp ${sorted}/reference.fa ${sorted}/reference.fa.fai ${sorted}/fixture-expectations.json calls/
    cp ${sorted}/known-sites.vcf calls/
    gatk --version > calls/gatk.version.txt 2>&1
    grep -q '4.7.0.0' calls/gatk.version.txt
    gatk CreateSequenceDictionary -R calls/reference.fa -O calls/reference.dict
    gatk IndexFeatureFile -I calls/known-sites.vcf
    gatk --java-options '-Xmx4g' MarkDuplicates -I ${sorted}/merged.bam -O marked.bam -M calls/duplicates.txt --REMOVE_DUPLICATES false --READ_NAME_REGEX null --CREATE_INDEX true
    gatk --java-options '-Xmx4g' BaseRecalibrator -R calls/reference.fa -I marked.bam --known-sites calls/known-sites.vcf -O calls/recal.table
    gatk --java-options '-Xmx4g' ApplyBQSR -R calls/reference.fa -I marked.bam --bqsr-recal-file calls/recal.table --emit-original-quals true -O calls/shared.bam --create-output-bam-index true
    gatk PrintReads -I calls/shared.bam -O calls/shared.sam
    cd calls
    sha256sum shared.bam shared.bai reference.fa reference.fa.fai reference.dict > shared-inputs.sha256
    gatk --java-options '-Xmx4g' HaplotypeCaller -R reference.fa -I shared.bam --native-pair-hmm-threads 2 --standard-min-confidence-threshold-for-calling 30.0 --emit-ref-confidence NONE -O gatk.vcf.gz
    sha256sum -c shared-inputs.sha256
    """
}

process DEEPVARIANT {
    container "${params.ecr_prefix}/deepvariant@sha256:962e5a83b1d76aae6990625d47102785f791603f2138aa1fa9aa4fb6a2eecbe6"
    cpus 2
    memory '8 GB'
    input:
    path calls
    output:
    path 'evaluated'
    script:
    """
    test "\$(uname -m)" = x86_64
    for flag in sse4_1 sse4_2 avx; do grep -qw "\$flag" /proc/cpuinfo; done
    cp -r ${calls} evaluated
    cd evaluated
    sha256sum -c shared-inputs.sha256
    export OMP_NUM_THREADS=2 TF_NUM_INTRAOP_THREADS=2 TF_NUM_INTEROP_THREADS=1
    /opt/deepvariant/bin/run_deepvariant --model_type=WES --ref=reference.fa --reads=shared.bam --sample_name=SYNTHETIC01 --num_shards=1 --postprocess_cpus=0 --make_examples_extra_args=use_original_quality_scores=true --output_vcf=deepvariant.vcf.gz --intermediate_results_dir=intermediate --logging_dir=logs
    sha256sum -c shared-inputs.sha256
    """
}

process ACCEPT {
    container params.support_image
    cpus 2
    memory '8 GB'
    input:
    path evaluated
    output:
    path 'native-qualification.json'
    script:
    """
    python - ${evaluated} <<'PYCODE'
    import gzip, hashlib, json, pathlib, sys
    root=pathlib.Path(sys.argv[1])
    fixture=json.loads((root/'fixture-expectations.json').read_text())
    expected=fixture['variant_sites']
    oq_records=0
    for line in (root/'shared.sam').read_text().splitlines():
        if line.startswith('@'): continue
        f=line.split('\\t'); flag=int(f[1])
        if flag & 2304: continue
        tags={x.split(':',2)[0]:x.split(':',2)[2] for x in f[11:]}
        original=fixture['read_expectations'][f[0]+('/1' if flag & 64 else '/2')]['original_qualities']
        if flag & 16: original=original[::-1]
        assert tags.get('OQ')==original, 'original quality identity mismatch'
        oq_records+=1
    assert oq_records==fixture['primary_read_count'], 'primary read count mismatch'
    observations={}
    for caller in ('gatk','deepvariant'):
        rows={}
        with gzip.open(root/(caller+'.vcf.gz'),'rt') as stream:
            for line in stream:
                if line.startswith('#'): continue
                f=line.rstrip().split('\\t')
                sample=dict(zip(f[8].split(':'),f[9].split(':')))
                rows[(f[0],int(f[1]),f[3],f[4])]=(sample.get('GT','').replace('|','/'),f[6])
        for site in expected:
            key=(site['contig'],site['position_1based'],site['ref'],site['alt'])
            observed=rows.get(key)
            assert observed and observed[0]==site['genotype'] and observed[1] in ('PASS','.'), (caller,key,observed)
        observations[caller]={'positive_sites_accepted':len(expected),'vcf_sha256':hashlib.sha256((root/(caller+'.vcf.gz')).read_bytes()).hexdigest()}
    report={'kind':'managed_nonhuman_native_qualification','canonical':False,'fixture_recipe':'1.1.0','original_quality_records_verified':oq_records,'callers':observations,'shared_bam_sha256':hashlib.sha256((root/'shared.bam').read_bytes()).hexdigest(),'full_cloud_workflow_qualified':False,'normalization_benchmark_qualified':False}
    pathlib.Path('native-qualification.json').write_text(json.dumps(report,indent=2)+'\\n')
    PYCODE
    """
}

process PREPARE_BENCHMARK {
    container params.support_image
    cpus 2
    memory '8 GB'
    time '15m'
    stageInMode 'copy'
    input:
    path evaluated
    path accepted
    output:
    path 'benchmark-inputs'
    script:
    """
    python -I -m giab_wes_nextflow.managed_qualification prepare --input ${evaluated} --accepted ${accepted} --output benchmark-inputs
    """
}

process NORMALIZE_BENCHMARK {
    container "${params.ecr_prefix}/bcftools@sha256:a3e0d3007ffe325c409b398f660840a3e7574d076219c6e82fc994ced87d47c3"
    cpus 2
    memory '8 GB'
    time '15m'
    input:
    path prepared
    output:
    path 'normalized'
    script:
    """
    cp -r ${prepared} normalized
    cd normalized
    for dataset in fixture native; do
      (
        cd "\$dataset"
        bcftools --version > normalize.version.txt
        grep -q '^bcftools 1.24\$' normalize.version.txt
        for caller in gatk deepvariant truth; do
            source="\$caller.vcf"
            if test -f "\$caller.vcf.gz"; then source="\$caller.vcf.gz"; fi
            test "\$(bcftools query -l "\$source")" = "\$(cat sample.txt)"
            bcftools view --no-version -Oz -o "\$caller.input.vcf.gz" "\$source"
            bcftools index --tbi "\$caller.input.vcf.gz"
            bcftools view -H "\$caller.input.vcf.gz" > sequential.txt
            bcftools view -H -r "\$(cut -f1 reference.fa.fai | paste -sd, -)" "\$caller.input.vcf.gz" > indexed.txt
            cmp sequential.txt indexed.txt
            bcftools norm -f reference.fa -c e -m -any --multi-overlaps 0 --old-rec-tag M5_ORIG --no-version -Ov -o split.vcf "\$caller.input.vcf.gz"
            bcftools sort -Ov -o "\$caller.sorted.vcf" split.vcf
        done
      )
    done
    """
}

process INCLUDE_BENCHMARK {
    container params.support_image
    cpus 2
    memory '8 GB'
    time '15m'
    stageInMode 'copy'
    input:
    path normalized
    output:
    path 'included'
    script:
    """
    python -I -m giab_wes_nextflow.managed_qualification include --input ${normalized} --output included
    """
}

process COMPRESS_BENCHMARK {
    container "${params.ecr_prefix}/bcftools@sha256:a3e0d3007ffe325c409b398f660840a3e7574d076219c6e82fc994ced87d47c3"
    cpus 2
    memory '8 GB'
    time '15m'
    input:
    path included
    output:
    path 'compressed'
    script:
    """
    cp -r ${included} compressed
    cd compressed
    for dataset in fixture native; do
      (
        cd "\$dataset"
        bcftools --version > compress.version.txt
        for caller in gatk deepvariant truth; do
            bcftools view --no-version -Oz -o "\$caller.normalized.vcf.gz" "\$caller.included.vcf"
            bcftools index --tbi "\$caller.normalized.vcf.gz"
            bcftools view -H "\$caller.normalized.vcf.gz" > sequential.txt
            bcftools view -H -r "\$(cut -f1 reference.fa.fai | paste -sd, -)" "\$caller.normalized.vcf.gz" > indexed.txt
            cmp sequential.txt indexed.txt
        done
      )
    done
    """
}

process RTG_BENCHMARK {
    container "${params.ecr_prefix}/rtg@sha256:b53115f1646258c5bd7af1e884fd06f1eab70ebb4ebc1161fff1e5529e200790"
    cpus 2
    memory '8 GB'
    time '15m'
    input:
    path compressed
    output:
    path 'benchmarked'
    script:
    """
    cp -r ${compressed} benchmarked
    cd benchmarked
    export RTG_MEM=2G
    for dataset in fixture native; do
      (
        cd "\$dataset"
        rtg version > rtg.version.txt
        grep -q 'RTG Tools 3.13' rtg.version.txt
        rtg format -o reference.sdf reference.fa
        for caller in gatk deepvariant; do
            rtg vcfeval -b truth.normalized.vcf.gz -c "\$caller.normalized.vcf.gz" -t reference.sdf -o "\$caller" --evaluation-regions evaluated.bed --sample "\$(cat sample.txt)" --all-records --ref-overlap --output-mode split --no-roc --sample-ploidy 2 --threads 2
        done
      )
    done
    """
}

process ACCEPT_BENCHMARK {
    container params.support_image
    cpus 2
    memory '8 GB'
    time '15m'
    stageInMode 'copy'
    input:
    path benchmarked
    output:
    path 'managed-qualification.json'
    script:
    """
    python -I -m giab_wes_nextflow.managed_qualification accept --input ${benchmarked} --output managed-qualification.json
    """
}

workflow {
    main:
    fixture = FIXTURE(file(params.seed))
    aligned = ALIGN(fixture)
    sorted = SORT(aligned)
    calls = GATK(sorted)
    evaluated = DEEPVARIANT(calls)
    accepted = ACCEPT(evaluated)
    benchmark_inputs = PREPARE_BENCHMARK(evaluated,accepted)
    normalized = NORMALIZE_BENCHMARK(benchmark_inputs)
    included = INCLUDE_BENCHMARK(normalized)
    compressed = COMPRESS_BENCHMARK(included)
    benchmarked = RTG_BENCHMARK(compressed)
    benchmark_accepted = ACCEPT_BENCHMARK(benchmarked)
    publish:
    qualification = benchmark_accepted
    native_evidence = evaluated
    benchmark_evidence = benchmarked
}

output {
    qualification { path 'qualification' }
    native_evidence { path 'private-nonhuman' }
    benchmark_evidence { path 'private-nonhuman-benchmark' }
}
