include { M5_NORMALIZE } from '../../../modules/local/m5_normalize/main'
include { M5_BENCHMARK } from '../../../modules/local/m5_benchmark/main'

workflow M5_COMMON_BENCHMARK {
    take:
    queries
    reference
    benchmark_inputs
    main:
    M5_NORMALIZE(queries, reference)
    M5_BENCHMARK(M5_NORMALIZE.out.normalized, reference, benchmark_inputs)
    emit:
    normalization = M5_NORMALIZE.out.normalized
    benchmarks = M5_BENCHMARK.out.result
}
