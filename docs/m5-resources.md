# M5 resource evidence

`giab_wes_nextflow.m5_resources` parses completed Nextflow trace files into a
versioned, schema-validated task table and deterministic attribution summaries.
The collector runs **after Nextflow exits**, when the trace is complete. It does
not infer workflow completion from individual task rows: retain the Nextflow exit
status, command, run identity and workflow acceptance evidence alongside the report.
A trace digest binds the report to the exact input bytes. The package version
identifies the collector implementation. Synthetic reports qualify parsing and
attribution only; they are not canonical caller-cost estimates.

## Collection

Keep `trace.raw = true` and include `attempt` in the configured trace fields.
The CLI requires `--trace-units nextflow-raw-ms-bytes`: durations and realtime are
milliseconds, memory is bytes, and `%cpu` is utilization relative to one logical
CPU. Human-formatted traces are rejected. Missing columns, `-`, `NA` and empty
numeric cells become null values with reasons; they never silently become zero.
A missing historical `attempt` remains unknown rather than being assumed to be 1.

After the Nextflow command finishes, invoke:

```bash
python -m giab_wes_nextflow.m5_resources \
  --trace results/pipeline_info/execution_trace.tsv \
  --trace-units nextflow-raw-ms-bytes \
  --runtime-json runtime.json \
  --started-at 2026-09-08T12:00:00+00:00 \
  --ended-at 2026-09-08T12:10:00+00:00 \
  --output m5-resources.json
```

The example timestamps illustrate the format; supply the actual observed
invocation boundaries. Alternatively pass `--observed-wall-seconds` from an
external invocation timer. Without either form, elapsed wall time is explicitly
unavailable. It is never reconstructed from task start/end spans or summed task
times, which exclude launch/shutdown overhead and may overlap.

The runtime JSON must contain all four keys below. Replace nulls only with actual
observations and then set their reasons to null. `input_bytes` is the total size
of the source input dataset for this invocation, counted once; `evaluated_bases`
is the evaluation-domain union size, not a sum across overlapping domains or
callers. Unknown runtime metadata remains explicit. These values are supplied by
the collector operator; they are not cryptographic host attestation or evidence
that an accelerator was used merely because one was available.

```json
{
  "architecture": {"value": null, "reason": "runtime architecture not recorded"},
  "accelerator": {"value": null, "reason": "accelerator use not observed"},
  "input_bytes": {"value": null, "reason": "source input inventory unavailable"},
  "evaluated_bases": {"value": null, "reason": "evaluation domain unavailable"}
}
```

For observed CPU-only execution, use an accelerator value such as `none_used`;
architecture can be the observed runtime `x86_64` or `aarch64`. String values
must describe observations, not silently substitute for unknown fields.

## Attribution and arithmetic

| Attribution group | Explicit process policy |
| --- | --- |
| `shared_preprocessing` | All accepted M3 preprocessing tasks, including index construction if executed, plus common M4 input validation/preparation |
| `gatk_incremental` | `M4_HAPLOTYPECALLER` and `M4_COLLECT_GATK` |
| `deepvariant_incremental` | `M4_DEEPVARIANT` and `M4_COLLECT_DEEPVARIANT` |
| `common_normalization_benchmark` | Common `M4_BUNDLE` packaging overhead and both callers' `M5_NORMALIZE` / `M5_BENCHMARK` tasks |
| `end_to_end` | All recorded task attempts, plus separately observed invocation wall time |

Common normalization/benchmarking therefore includes shared bundle packaging;
it is not attributed to either scientific caller. Caller collectors are part of
the corresponding caller's incremental delivery overhead. A newly introduced
process requires an explicit mapping change; unfamiliar or malformed process
names fail closed. Workflow prefixes and complete display tags are removed in
that order so a tag such as `(gatk:SYNTHETIC01)` cannot change process identity.

Each task retains its ID, optional attempt number, full name, hash when available,
status, cache flag, exit code, requested CPU/memory, duration, realtime, CPU
utilization and peak RSS/virtual memory. Recognized terminal states are
`COMPLETED`, `CACHED`, `FAILED` and `ABORTED`. Completed and cached rows require
exit code zero. Failed/retried attempts remain in the accounting. Duplicate or
ambiguous task-ID/attempt pairs, unfinished/unknown statuses, malformed numeric
values, negative values and mixed units are rejected.

Every group and the end-to-end task summary has separate `executed_attempts` and
`cached_prior_attempts` tables. A cached row's retained metrics describe prior
execution; they do not measure cache-lookup overhead during the current run.
Missing cached evidence cannot count as free work. A group with no executed tasks
has unavailable execution totals with reason `no tasks`, not an asserted zero
cost. Resume comparisons require these partitions and independently observed
invocation timing; cached and uncached observations cannot be compared as equal
work. The failed-attempt partition is represented in explicit status counts.

CPU-hours are an **estimate** from
`realtime_seconds × cpu_percent / 100 / 3600`. `%cpu` already accounts for use
across logical CPUs, so requested CPUs are never multiplied into this estimate.
The parser does not label that result measured CPU time. Measured CPU-hours are
null because this raw trace contract contains no direct measured CPU-time field.
Zero realtime also yields an unavailable estimate: trace resolution may hide
short-running work. Any incomplete task-level evidence makes the corresponding
aggregate unavailable instead of returning a partial sum as a total.

Summed task duration and summed realtime remain separate from elapsed wall time.
Memory summaries are the **maximum of individual task peaks**, never the sum and
never a claimed simultaneous peak of the whole run. Measuring a simultaneous run
peak requires different evidence. Requested memory describes allocation requests,
not observed consumption. Raw Nextflow monitoring and utilization sampling have
resolution limits; these reports do not establish canonical costs, infrastructure
prices, accuracy, a scalar caller winner, clinical validity or generalization.

## Validation boundary

`build_report(...)` validates against the installed `m5-resources.schema.json`.
`validate_report(...)` additionally recomputes attribution, CPU estimates, wall
timing and group totals, and rejects duplicate attempts. The root and packaged
schemas are byte-identical. The package owns all arithmetic; a future UI may
render these fields but cannot redefine them.

Unit tests cover exact arithmetic, cache mixtures, failures/retries, missing
metrics, negative/malformed inputs, status/name ambiguity, timestamps, schema
missingness, report tampering and deterministic CLI output. Existing recorded M3
first/resume traces are parsed as compatibility evidence without regenerating or
rerunning M3. Those traces lack attempt fields and preserve that limitation.
No synthetic resource numbers establish canonical HG001 cost.

M5's host Python launcher starts tool containers through the Docker daemon.
Nextflow task CPU/RSS observations therefore do not independently measure those
container processes. Treat these observations as launcher scope unless a separate
container accounting source is captured; no fair M5 engine resource comparison
is established by this trace alone.
