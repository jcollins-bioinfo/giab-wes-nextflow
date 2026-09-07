# M2 Colab launcher

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/jcollins-bioinfo/giab-wes-nextflow/blob/main/notebooks/m2_colab.ipynb)

Start from a clean runtime, set `REPOSITORY_REF` to a reviewed immutable SHA, and run the thin notebook. It calls `scripts/run_m2_readiness.sh verify`, installs only this project with `python -m pip`, and generates deterministic nonhuman fixtures before samplesheet validation. The inherited Colab `ipython 7.34.0`/missing `jedi` resolver warning is not caused by the project's dependency set (`jsonschema` at runtime) and is not repaired by force-reinstalling unrelated packages.

For an interrupted data operation, reuse the same deliberate `RUN_ID`. Active I/O belongs in `/content/m2-stage`; the mounted `MyDrive/giab-wes-nextflow-private` directory is only the durable verified-source mirror. `hydrate` rehashes cached bytes before atomic local promotion, and `acquire` resumes package-managed partial files. Allow roughly the manifest's declared bytes plus working headroom on local disk and one source-copy capacity on Drive; inspect the preflight output for the current exact declared/free byte counts.

**Gate A** means all declared source objects were acquired and verified. **Gate B** requires the independently confirmed capture-design bytes and canonical materialized domains. A mirror can support Gate A recovery but never completes Gate B and never creates `COMPLETED.json`. The launcher refuses canonical preparation/publication while the gate is unresolved. `samtools` is detected before preparation; on Colab the deterministic installation path is `apt-get update && apt-get install -y samtools`.

The notebook and launcher have static/local tests only. They have not been executed in a real Colab runtime, and no Google Drive operation is claimed.
