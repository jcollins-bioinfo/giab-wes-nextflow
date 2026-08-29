# Execution matrix

| Runtime | Architecture | M1 status |
|---|---|---|
| Nextflow 26.04.6 + Java 17 + Docker | CI host | supported minimum; see CI/run evidence |
| DeepVariant CPU/GPU linux/amd64 | x86_64; CPU AVX required | planned, not M1-tested |
| Apple Silicon/ARM64 | arm64 | orchestration compatibility only; caller untested |
| Apptainer, Colab, AWS, SLURM, Seqera/Wave | varied | not tested |
