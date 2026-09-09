# Canonical runtime operation and incident triage

Run the canonical notebook on Linux/amd64 Colab. Keep all active runtime state,
container engines, image caches, task roots and temporary files below `/content`
outside Drive. The normal notebook setting `allow_install=True` permits the
owner-authorized public tool downloads. The known 50.99 GiB allocation can use
an explicit ceiling no greater than 44 GiB; this does not authorize constructing
a BWA-MEM2 index requiring about 80.84 GiB before headroom.

The installed package exposes:

```python
from pathlib import Path
from giab_wes_nextflow.canonical_runtime import Runtime

runtime = Runtime(Path('/content/analysis/runtime'), allow_install=True,
                  cpus=8, memory_bytes=44 * 1024**3)
runtime.discover()  # Functional probe; status remains configured_only.
```

The canonical launcher then calls `canonical_smoke.qualify`, which runs actual
representative callers and their independent positive-site validator. Scientific
Nextflow stages require its saved qualified receipt. A successful installer or
version command is insufficient. A new notebook/runtime must rehydrate and
revalidate appropriate data and runtime state; a historical Docker success does
not qualify the present Colab host.

`Runtime.run(tool, args, task_dir=..., stage=..., timeout_seconds=...)` binds only
that explicit task directory and returns audit paths, source image/runtime
identity, requested resources, elapsed wall time, CPU evidence and missingness.
Arguments exclude the executable. `stdout_path` is a file so large SAM output is
never forced into notebook memory. `expected_exit_codes=(0, 1)` is available only
where a tool's documented informational invocation needs it, such as BWA usage
output. Caller commands must succeed with exit zero. Automatic retries are never
used for arbitrary scientific failures.

Private diagnostics are under `runtime/audit/`: JSON command receipts and separate
stdout/stderr files. `runtime-state.json` distinguishes configured, functionally
probed and qualified states. The notebook's public-safe bundle removes private
command paths and human-data content; do not publish raw audit logs as public
website assets.

| Symptom | Action |
| --- | --- |
| No Apptainer/Singularity executable | Allow the pinned udocker installation route; do not install Docker blindly. |
| User namespace, FUSE or seccomp failure | Read discovery diagnostics. PRoot P2 receives one fresh smoke attempt after a P1 technical failure. |
| Positive SNV or version gate fails | Stop qualification and preserve diagnostics. Do not lower the acceptance gate or call the runtime qualified. |
| Runtime download interrupted | Rerun with the same scratch root; verified complete partials promote without another download and partial ranges resume. |
| Installed runtime inventory changed | Stop reuse. Preserve evidence and choose a fresh runtime installation directory. |
| RSS ceiling or wall timeout exceeded | Preserve the audit receipt and validated checkpoints. Resume within the preregistered limits; do not silently increase memory or alter callers. |
| Colab runtime reset | Restart the notebook. Revalidate durable completed assets/checkpoints; active work and unvalidated partial outputs are not durable evidence. |
| SLURM/AWS/Seqera/Wave requested | These profiles are configured-only. They need their own authorization, worker qualification and execution evidence. |

The runtime libraries and profile composition have synthetic unit/configuration
checks. Actual no-Docker Colab execution remains a future observation until a
qualified receipt is returned. PRoot's reduced isolation and sampled memory
accounting limitations must remain attached to any resulting resource report.
