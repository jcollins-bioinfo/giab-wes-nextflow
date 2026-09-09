nextflow.enable.dsl = 2

// Dedicated canonical entrypoint. The notebook verifies installed code identity;
// runtime qualification and authenticated source gates precede this workflow.
params.preprocess_spec = null
params.benchmark_spec = null
params.runtime_spec = null
params.canonical_ready = false

process CANONICAL_PREPROCESS {
    label 'canonical_shared'
    cache 'deep'
    input:
    path specification, stageAs: 'specification.json'
    path runtime, stageAs: 'runtime.json'
    output:
    path 'preprocessed'
    script:
    """
    python -I -m giab_wes_nextflow.canonical_science preprocess --spec '${specification}' --runtime '${runtime}' --output preprocessed
    """
    stub:
    """
    mkdir -p preprocessed
    printf '{"status":"stub_only","synthetic":true,"canonical":false}\\n' > preprocessed/receipt.json
    """
}

process CANONICAL_CALL {
    tag "$caller"
    label 'canonical_caller'
    cache 'deep'
    input:
    val caller
    path preprocessed
    path runtime, stageAs: 'runtime.json'
    output:
    tuple val(caller), path('called')
    script:
    """
    python -I -m giab_wes_nextflow.canonical_science call --caller '${caller}' --shared '${preprocessed}/shared' --runtime '${runtime}' --output called
    """
    stub:
    """
    mkdir -p called
    printf '{"status":"stub_only","synthetic":true,"canonical":false}\\n' > called/receipt.json
    """
}

process CANONICAL_BENCHMARK {
    tag "$caller"
    label 'canonical_benchmark'
    cache 'deep'
    input:
    tuple val(caller), path(called)
    path preprocessed
    path specification, stageAs: 'specification.json'
    path runtime, stageAs: 'runtime.json'
    output:
    tuple val(caller), path('benchmarked')
    script:
    """
    python -I -m giab_wes_nextflow.canonical_science benchmark --caller '${caller}' --raw '${called}' --shared '${preprocessed}/shared' --spec '${specification}' --runtime '${runtime}' --output benchmarked
    """
    stub:
    """
    mkdir -p benchmarked
    printf '{"status":"stub_only","synthetic":true,"canonical":false}\\n' > benchmarked/receipt.json
    """
}

workflow {
    main:
    if (!params.canonical_ready) error('Canonical execution requires the installed package preflight and runtime qualification')
    if (!params.preprocess_spec || !params.benchmark_spec || !params.runtime_spec) error('Missing canonical input contracts')
    preprocessing = CANONICAL_PREPROCESS(file(params.preprocess_spec, checkIfExists: true), file(params.runtime_spec, checkIfExists: true))
    native_calls = CANONICAL_CALL(channel.of('gatk', 'deepvariant'), preprocessing, file(params.runtime_spec, checkIfExists: true))
    benchmarked = CANONICAL_BENCHMARK(native_calls, preprocessing, file(params.benchmark_spec, checkIfExists: true), file(params.runtime_spec, checkIfExists: true))
    publish:
    shared = preprocessing
    callers = native_calls
    benchmarks = benchmarked
}

output {
    shared { path 'canonical/shared' }
    callers { path { caller, _directory -> "canonical/${caller}/native" } }
    benchmarks { path { caller, _directory -> "canonical/${caller}/benchmark" } }
}
