# Exact Nextflow 26.04.0 investigation

Status: partial local evidence; **not qualified for managed scientific execution**.
Historical 26.04.6 M3-M5 observations and the production guard remain unchanged.

The version floor first appears in `bd2c447b5e3b24d371ac84a81e2180990d4ef6cd`
(`fix(lint): align external pipeline with nf-core checks`, August 29). Its presence
is not proof that every cloud feature needs that patch. The cloud package removes
only the unused foundation nf-schema plugin and records that transform.

The exact distribution tested was `nextflow-26.04.0-dist`, build 12031, SHA-256
`5e2b4a354b4d7634d7211b71417d61606878fb49e9b224b50ded6e2c69114870`.
AWS's current run documentation supports full `engineVersion=26.04.0` and
`syntaxVersion=v1` or `v2`. A floating `26.04` alias is not acceptable evidence.

## Relevant upstream changes

Primary release notes accessed September 11, 2026 UTC:

- [26.04.1](https://github.com/nextflow-io/nextflow/releases/tag/v26.04.1): module-run binary execution and plugin updates. This project invokes workflow processes, not `module run`.
- [26.04.2](https://github.com/nextflow-io/nextflow/releases/tag/v26.04.2): strict-parser parameter references in task hashes (#7165), typed-output function calls/path normalization, optional/destructured module-run inputs. The cloud processes use explicit task inputs and task resource values; no typed-process/record opt-in is present. That narrows exposure but does not replace execution tests.
- [26.04.3](https://github.com/nextflow-io/nextflow/releases/tag/v26.04.3): parser/type diagnostics and plugin fixes.
- [26.04.4](https://github.com/nextflow-io/nextflow/releases/tag/v26.04.4): typed output/job arrays, record staging, double completion-handler invocation (#7191), timestamp handling and plugin updates. The current cloud path has no user completion handler or typed-record tasks. Its tuple workflow-output closures still need explicit qualification.
- [26.04.5](https://github.com/nextflow-io/nextflow/releases/tag/v26.04.5): value-channel flatMap fix, metrics and plugin changes. The cloud graph uses first/broadcast channels, not flatMap.
- [26.04.6](https://github.com/nextflow-io/nextflow/releases/tag/v26.04.6): plugin updates in the published notes.

## Observations and reproducible probes

`scripts/qualification/nextflow_engine.py` executes small nonhuman tasks and
records actual task hashes/status, not an emulated hash implementation. Parser
and full engine version are explicit. On the local Mac, parser v1 completed the
initial task, reused unchanged input, and invalidated parameter, reference/domain
identity and same-size/same-mtime input-content changes under deep caching.
Tuple workflow-output publication also completed.

The container-digest negative test returned CACHED with no container runtime.
It remains a failed qualification case: a local uncontainerized executor does not
establish backend image identity. The added Linux CI matrix runs both parsers
with two genuinely different immutable images, exercises command changes, and
retains the traces. This is local Docker qualification, never HealthOmics proof.

The Mac's later strict-parser and full cloud preview attempts failed during Java
security-provider initialization (`SHA-1 not available`) before graph execution.
The attempts are retained; this is not evidence of workflow incompatibility.
No production manifest/version floor was lowered to hide this failure.

```bash
python scripts/qualification/nextflow_engine.py --nextflow /path/to/nextflow-26.04.0 \
  --parser v1 --work /private/tmp/giab-engine-probe \
  --container-image "$VERIFIED_IMAGE_A" --alternate-container-image "$VERIFIED_IMAGE_B"
```

Use the exact immutable images recorded in `.github/workflows/aws-cloud.yml`.
The portable command takes real image arguments; it does not discover or retag
images. Probe receipt status must be inspected before any compatibility claim.

Remaining: both parser CI results, actual packaged cloud graph execution, explicit
StartRun parser identity, native GATK/DeepVariant managed nonhuman qualification,
managed input staging/output receipts and cache negatives. Only those results can
justify a backend-specific guard and packaging change. EC2 quota warnings do not
block HealthOmics inspection; HealthOmics compatibility warnings do not block
Batch inspection. Neither inspection result authorizes scheduling on its own.

[AWS engine settings](https://docs.aws.amazon.com/omics/latest/dev/starting-a-run.html)
are the supported-runtime authority; upstream release notes identify risks rather
than proving whether this project is affected.
