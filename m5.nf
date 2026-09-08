include { M5_COMMON_BENCHMARK } from './subworkflows/local/m5_common_benchmark/main'

def resolve_input(base, value) {
    if (!(value instanceof String) || !value) error 'M5 input path must be nonempty'
    file(base.resolve(value), checkIfExists: true)
}

// This downstream entry never invokes preprocessing or callers.
workflow {
    main:
    if (!params.m5_manifest) error 'M5 requires an explicit synthetic manifest'
    if (!(params.callers in ['gatk', 'deepvariant', 'both'])) error 'Unknown M5 caller selection'
    def manifest_file = file(params.m5_manifest, checkIfExists: true)
    // Validate once in the installed package; parse its canonical stdout, never reread
    // an ambiguous source with JsonSlurper's last-key-wins behavior.
    def manifest_check = new ProcessBuilder('python', '-m', 'giab_wes_nextflow.m5_manifest', manifest_file.toString()).redirectErrorStream(true).start()
    def manifest_text = manifest_check.inputStream.text
    if (manifest_check.waitFor() != 0) error "M5 manifest validation failed: ${manifest_text}"
    def manifest = new groovy.json.JsonSlurper().parseText(manifest_text)
    def fields = ['synthetic', 'sample', 'domain_id', 'reference', 'fai', 'dictionary', 'truth', 'truth_index', 'confidence', 'domain', 'queries'] as Set
    if (manifest.keySet() != fields || manifest.synthetic != true) error 'M5 entry requires its closed synthetic manifest; canonical execution is not qualified'
    if (!(manifest.sample ==~ /[A-Za-z0-9][A-Za-z0-9._-]*/) || !(manifest.domain_id ==~ /[A-Za-z0-9][A-Za-z0-9._-]*/)) error 'Unsafe sample/domain identifier'
    if (!(manifest.queries instanceof List) || manifest.queries.size() != 2 || manifest.queries.collect { row -> row.caller }.toSet() != ['gatk', 'deepvariant'] as Set) error 'M5 manifest requires exactly one query per caller'
    def reference = tuple(resolve_input(manifest_file.parent, manifest.reference), resolve_input(manifest_file.parent, manifest.fai), resolve_input(manifest_file.parent, manifest.dictionary))
    def benchmark_inputs = tuple(resolve_input(manifest_file.parent, manifest.truth), resolve_input(manifest_file.parent, manifest.truth_index), resolve_input(manifest_file.parent, manifest.confidence), resolve_input(manifest_file.parent, manifest.domain))
    def queries = manifest.queries.findAll { row -> params.callers == 'both' || row.caller == params.callers }.collect { row ->
        if (row.keySet() != ['caller', 'vcf', 'index'] as Set) error 'Unknown query fields'
        tuple([caller:row.caller, sample:manifest.sample, domain_id:manifest.domain_id], resolve_input(manifest_file.parent, row.vcf), resolve_input(manifest_file.parent, row.index))
    }
    M5_COMMON_BENCHMARK(channel.fromList(queries), channel.value(reference), channel.value(benchmark_inputs))
    publish:
    normalization = M5_COMMON_BENCHMARK.out.normalization
    benchmarks = M5_COMMON_BENCHMARK.out.benchmarks
}

output {
    normalization { path { meta, _vcf, _index, _lineage -> "m5/${meta.caller}/normalization" }; mode 'copy' }
    benchmarks { path { meta, _result -> "m5/${meta.caller}/benchmark" }; mode 'copy' }
}
