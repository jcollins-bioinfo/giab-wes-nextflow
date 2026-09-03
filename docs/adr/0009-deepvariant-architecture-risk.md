# ADR 0009: DeepVariant architecture qualification risk

**Status:** risk accepted for early M4 testing (2026-09-03)

DeepVariant is not executed in M2. Its pinned WES container must be qualified early in M4 on the intended x86_64/AVX runtime. ARM64 and Apple Silicon compatibility, Docker emulation, and Colab execution are explicitly **untested**, not inferred from orchestration compatibility. Failure requires a documented runtime decision; it does not authorize different reads, preprocessing, model, or caller evidence.
