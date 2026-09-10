# AWS operator utilities

These scripts inspect or prepare operations by default. Importing their Python
helpers does not contact AWS. Install the repository with its `aws` extra in a
project virtual environment. All live operations first call STS and reject root
and ordinary IAM-user credentials before contacting another service. Use a
short-lived assumed-role session through the documented operator authentication
path; never create root access keys.

The initial deployment region is **us-west-2**. No account state in this document
is a current inspection result. The prompt's historical 5-vCPU quota must be
refreshed after a non-root role is connected.

## Read-only preflight

```bash
python scripts/aws/preflight.py --profile giab-operator --region us-west-2 \
  --desired-vcpus 32 --json work/aws-preflight.json
```

JSON goes to stdout and the optional file; a short summary goes to stderr.
Exit 2 means blockers remain; exit 1 means the inspection itself failed. Root
receives a report after **only** `GetCallerIdentity`; inventories remain unknown.
Every inventory is paginated. Denied requests are recorded as errors, never zero
resources. The utility inventories S3/ECR/Batch/HealthOmics/ECS/logs/networking/
ACM/Route53 and reads EC2 and HealthOmics Service Quotas. Resource names matching
the project prefix are candidates, not proof of Terraform ownership. Read success
and SDK endpoint advertisement are reported separately from deployment readiness.

The On-Demand standard quota is `L-1216C47A`; the independent standard Spot quota
is `L-34B43A08`. The report prints exact quota-increase commands for the selected
CPU ceiling; it **never executes** them. For a 32-vCPU ceiling, request 32 for the
selected market, allowing additional headroom if other account workloads exist.
A quota is an account limit, not available capacity or unused vCPU headroom.
A 4-vCPU smoke task may fit a historical 5-vCPU limit but must check current
usage and actual instance availability. It does not establish canonical readiness.

## Verify actual Batch job definitions

Nextflow selects separate ordinary/benchmark roles through revision-pinned
custom Batch job definitions. After approved infrastructure deployment, export
the Terraform `batch_job_definition_inventory` output and inspect actual AWS
state before scheduling:

```bash
terraform -chdir=infra/aws output -json batch_job_definition_inventory > work/batch-definitions.json
python scripts/aws/batch_check.py --profile giab-operator \
  --definitions work/batch-definitions.json \
  --job-role arn:aws:iam::123456789012:role/PROJECT-BATCH-JOB \
  --benchmark-role arn:aws:iam::123456789012:role/PROJECT-BATCH-BENCHMARK \
  --support-image 123456789012.dkr.ecr.us-west-2.amazonaws.com/giab-support@sha256:ACTUAL_DIGEST \
  --output work/batch-definitions-receipt.json
```

The exact ten keys are `support`, `support-benchmark`, `bwa`, `samtools`, `gatk`,
`deepvariant`, `bcftools`, `bcftools-benchmark`, `rtg`, `rtg-benchmark`, each with
`name` (`name:revision` or revision-pinned ARN), `image` and `job_role_arn`.
The checker reads ACTIVE definitions and verifies the exact configured image,
reviewed upstream digest, role, EC2 platform, absence of privileged mode and
absence of an ARM64 runtime setting. Its only allowed host mount is the exact
read-only `/opt/giab-awscli` directory at the same container path, needed for
Nextflow's S3 staging with custom job definitions. Docker socket and other host
mounts are rejected. It prints the receipt SHA-256
needed by the cloud DAG. It does not register definitions or submit jobs.
This inspection does not replace IAM policy-effect review, EC2 instance-family
architecture checks, quota inspection or direct-container qualification.

## Deterministic HealthOmics package and registration plan

Commit reviewed code before packaging for a canonical run. Offline packaging of
a dirty tree is permitted for development and clearly recorded; canonical
submission rejects it. Store outputs outside source files.

```bash
python scripts/aws/healthomics.py --output work/package-evidence.json package \
  --zip work/healthomics-workflow.zip
python scripts/aws/healthomics.py --output work/registration-plan.json register \
  --zip work/healthomics-workflow.zip --name giab-hg001-cloud \
  --registry-map work/ecr-image-map.json
```

The ZIP includes `cloud.nf`, configuration, modules, source helpers and a manifest
of every bundled file's SHA-256 and byte count. File ordering, ZIP times and file
modes are fixed; a sidecar records the ZIP hash and source HEAD. The sidecar is
verified before registration. Generated scientific data and credentials are not
included. Source symlinks are rejected.

The generated ZIP configuration excludes the unused foundation `nf-schema@2.8.0`
plugin block, avoiding an unnecessary plugin download in HealthOmics. The original
configuration SHA and exact packaging transformation are recorded in the ZIP
manifest. The repository configuration, engine minimum and scientific parameters
remain unchanged. Any different plugin block fails packaging pending review.

`ecr-image-map.json` has this shape (the repeated digest is illustrative and must
be replaced with a reviewed manifest digest):

```json
{
  "imageMappings": [
    {
      "sourceImage": "upstream.example/tool@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "destinationImage": "123456789012.dkr.ecr.us-west-2.amazonaws.com/tool@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    }
  ]
}
```

Mirror every scientific image required by the cloud profile, preserve the exact
reviewed upstream digest, and verify the destination manifest digest with ECR.
For manifest lists, copy all platforms/child manifests to preserve the upstream
manifest-list identity, while scheduling only the qualified amd64 image. Record
source, destination, architecture, digest and verification evidence. A matching
string in the map is not evidence that an image was actually pushed or tested.
This utility validates map identity; it does not build, push or qualify images.
The support runtime also needs a reviewed private ECR digest.

Only after separate operator authorization, adding `--allow-register` creates a
private workflow, tagged with package/source identity, from the small local ZIP.
Registration is a mutation, not genomics execution. Terraform owns S3/ECR/IAM;
this utility does not use Terraform provisioners. The inspected Terraform AWS
provider 6.64.0 schema has no HealthOmics resources, so run-group creation also
uses a separate explicit utility operation:

```bash
python scripts/aws/healthomics.py --output work/run-group-plan.json create-group
```

The fixed defaults cap the group at 32 CPUs, one concurrent run and 2880 minutes.
After separate authorization, add `--allow-create-group` to create it and save
the returned group ID for the run plan. Creating a group does not execute a run.

## Engine compatibility blocker

As checked on 2026-09-10, AWS documents HealthOmics `engineVersion` **26.04.0**
(or its `26.04` alias). This repository requires **>=26.04.6**. Profiles and the
26.04 major/minor release being supported do **not** prove patch compatibility.
The tools preserve the repository requirement and default to the documented
version, producing a blocked plan. Do not lower the requirement silently.
A service upgrade plus an independently authorized engine-qualification run
must establish the exact supported patch before canonical submission. The submit
utility reads that run's actual `engineVersion` and completion status from AWS;
a local success or typed version string is insufficient.

## Input-bound run and cache plans

The cloud manifest is produced/validated against `cloud_contract.py`, including
all authenticated input/reference/domain/truth and qualification records. Keep its
exact bytes at the supplied S3 URI. Manifest SHA-256 is checked by the launcher
and the workflow. Multipart ETags never serve as SHA-256 identities.

```bash
python scripts/aws/healthomics.py --output work/run-plan.json plan \
  --zip work/healthomics-workflow.zip \
  --manifest work/cloud-inputs.json \
  --manifest-uri s3://PROJECT-DATA/provenance/cloud-inputs.json \
  --support-image 123456789012.dkr.ecr.us-west-2.amazonaws.com/giab-support@sha256:ACTUAL_DIGEST \
  --workflow-id WORKFLOW_ID --run-group-id RUN_GROUP_ID \
  --role-arn arn:aws:iam::123456789012:role/PROJECT-HEALTHOMICS-ROLE \
  --output-uri s3://PROJECT-DATA/results/hg001-chr20-22/RUN_ID/
python scripts/aws/healthomics.py --output work/cache-plan.json create-cache \
  --plan work/run-plan.json --cache-uri s3://PROJECT-WORK/cache/
```

Uppercase values are placeholders, not runnable identities. The plan defaults to
26.04.0 and reports the compatibility blocker. A future qualified supported exact
version can be selected explicitly with `--engine-version`; no short alias is
accepted. After approval, `create-cache --allow-create-cache` creates a cache only
if the plan has no blockers. Add its returned ID with `plan --cache-id CACHE_ID`
to regenerate the run plan.

Each cache is scoped by a SHA-256 identity over the exact workflow package,
complete scientific manifest (including reference/domain hashes), digest-pinned
support image, parameters, profile and exact engine. Submission requires the
cache's AWS tag to match that identity. Default `CACHE_ON_FAILURE` supports
recovery; cached reuse must never be reported as new uncached compute. Durable
input prefixes must be immutable to scientific execution roles. The cloud
workflow's authentication tasks still recheck content rather than trusting S3
ETags. Keep cached outputs online and preserve their retention for the period
needed for recovery; cleanup requires an explicit decision.

Paid submission is intentionally explicit and independently gated:

```bash
python scripts/aws/healthomics.py --profile giab-operator --output work/run-receipt.json submit \
  --plan work/run-plan.json --preflight work/aws-preflight.json \
  --engine-qualification-run QUALIFIED_RUN_ID --allow-paid-run
```

It checks: no offline plan blockers; temporary non-root role; complete same-account
us-west-2 preflight less than one hour old; registered ACTIVE workflow package tag;
actual exact engine from a completed qualification run; execution role account;
run-group maximum <=32 CPUs, one concurrent run and <=2880 minutes; exact S3
manifest bytes; and matching cache scientific identity. CPU/time bounds are not a
dollar-denominated spend cap. Terraform budgets and lifecycle controls remain
necessary. Reusing an identical plan keeps an identical idempotency token;
use a new output URI to intentionally start another run.

## Execution evidence

```bash
python scripts/aws/healthomics.py --profile giab-operator --output work/run-evidence.json \
  evidence --run-id RUN_ID
PYTHONPATH=src python -m pytest -q tests/unit/test_aws_support.py
```

Evidence retains `GetRun` and paginated task responses, including `cacheHit`,
with separate hit/miss/unknown counts. An absent `cacheHit` is unknown, not a miss.
Inspect `/aws/omics/WorkflowLog`, run/task status, failure reason, actual engine
version and resource evidence. The export never calls a cached run an uncached
compute measurement. No successful API response alone establishes a scientifically
valid HG001 canonical bundle.

## AWS API references

- [HealthOmics engine versions and profiles](https://docs.aws.amazon.com/omics/latest/dev/starting-a-run.html)
- [CreateWorkflow: ZIP, private ECR and registry map](https://docs.aws.amazon.com/omics/latest/api/API_CreateWorkflow.html)
- [StartRun: engineSettings, cacheId, cacheBehavior and dynamic storage](https://docs.aws.amazon.com/omics/latest/api/API_StartRun.html)
- [CreateRunCache](https://docs.aws.amazon.com/omics/latest/api/API_CreateRunCache.html)
- [GetRun: actual engineVersion](https://docs.aws.amazon.com/omics/latest/api/API_GetRun.html)
- [ListRunTasks: cacheHit](https://docs.aws.amazon.com/omics/latest/api/API_ListRunTasks.html)
- [EC2 instance quotas](https://docs.aws.amazon.com/ec2/latest/instancetypes/ec2-instance-quotas.html)
