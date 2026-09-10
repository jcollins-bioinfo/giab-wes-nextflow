# AWS infrastructure (implementation, not deployment evidence)

Terraform provisions infrastructure; Nextflow orchestrates scientific computation.
The default is `us-west-2`; this module rejects a silent region change and a root
principal. `enable_batch=false` and `enable_explorer=false` omit paid compute and
serving resources. An apply still creates billable storage/log services when used.
No Terraform provisioner registers or executes a scientific workflow.

## Authenticate and import the IAM bootstrap

Use an organization/IAM Identity Center administrator to create a human operator
identity and a project-scoped permission set. Authenticate using `aws configure
sso --profile giab-operator` and `aws sso login --profile giab-operator`; export
`AWS_PROFILE=giab-operator`. Use temporary credentials; never root access keys.
An existing approved non-root federated role is also suitable. Root cannot assume
an IAM role; creating service roles alone does not provide human operator access.
The operator needs deployment permissions for the resources in the reviewed plan,
with `iam:PassRole` limited to these project role ARNs and their respective service
principals. Execution roles must not receive infrastructure deployment rights.
There is deliberately no invented human trust principal, IAM user, or CI deploy
role. PR CI needs no AWS credential.

On 2026-09-10 the seven `giab-wes-demo-*` service roles and six `project-access`
inline policies were bootstrapped separately under the owner's limited explicit
root authorization. All role trusts and policies were read back and matched
`iam-roles.json.tftpl`. No role has AdministratorAccess. Import them before the
first apply; do not try to recreate them or attach broad managed policies:

```bash
export AWS_PROFILE=giab-operator AWS_REGION=us-west-2
python scripts/aws/preflight.py --region us-west-2
terraform -chdir=infra/aws init
cp infra/aws/environments/demo/terraform.tfvars.example infra/aws/terraform.tfvars
# Edit account_id and budget notification settings in this gitignored file.
cp infra/aws/import-bootstrapped-roles.tf.example infra/aws/import-bootstrapped-roles.tf
terraform -chdir=infra/aws plan -out=reviewed.tfplan
# Only after a separate explicit deployment decision:
terraform -chdir=infra/aws apply reviewed.tfplan
```

The import example records exact role/policy addresses. `iam-roles.json.tftpl` is
the single shared template for both bootstrap and Terraform, with account, region,
project name and bucket substitutions. Check the post-import plan for unexpected
trust/policy changes. Terraform's root precondition does not make it safe to run
Terraform as root: select a non-root identity before invoking any provider calls.
If the fixed `/aws/omics/WorkflowLog` group or Batch service-linked role already
exists, import it after preflight rather than taking ownership silently. Keep
state, plans and tfvars private. Local state is acceptable for one operator's
initial bootstrap; move it to a separately provisioned encrypted, versioned S3
backend with locking before shared operations.

## Resource and trust boundaries

| Component | Implementation and limits |
|---|---|
| Durable data | Account/region-qualified private versioned S3 data bucket; SSE-S3, public access blocked, TLS required, `prevent_destroy`, no completed-object lifecycle expiration. Prefixes `source/`, `reference/`, `index/`, `domain/`, `known-sites/`, `truth/`, `results/`, `evidence/`, `provenance/`. Persist index qualification and reference checksum identity together. |
| Disposable data | Separate versioned work bucket. Only `work/` expires after 30 days, with noncurrent versions removed after another seven days. Resume is limited by retained work AND the external Nextflow controller's `.nextflow/cache`. `cache/` is retained until deliberate reviewed cleanup. |
| Registry | Eight immutable/scanned/encrypted private ECR repositories: support, Explorer and six tool mirrors. Digests and source-to-ECR mapping receipts must be verified before use. Scientific versions are not changed by Terraform. |
| Batch jobs | Separate caller/preprocessing role with explicit truth-object deny; evaluator role adds read-only `truth/` access. Both write results/evidence/provenance and work only, not scientific source objects. |
| Batch infrastructure | EC2 instance role has project ECR/log access and ECS agent control actions, no S3. Batch uses its AWS-managed service-linked role. Distinct task execution role handles image/log startup. |
| HealthOmics | Workflow-wide service role reads scientific inputs/truth and writes output/cache. HealthOmics has a workflow role rather than per-process roles here; truth isolation is workflow dataflow/staging isolation, not an IAM boundary between tasks. Caller task inputs must exclude truth. |
| Explorer | Execution role pulls only its ECR repository and writes its log group. Runtime role has zero AWS permissions: initial image carries reviewed public-safe evidence. S3 loading is not implemented by granting arbitrary bucket access. |
| Observability | Project Batch and Explorer log groups; service-fixed HealthOmics WorkflowLog, 90-day retention. Archive evidence to durable S3 before log expiration. |
| Budget | Optional account-wide monthly budget with 80% actual and 100% forecast email alerts. Account scope catches spend before cost allocation tags are activated. Alerts do not stop resources. |

ECR has intentionally **no automatic image expiration**. ECR lifecycle rules
cannot test whether an untagged digest is still referenced by a deployed ECS task,
Nextflow run or HealthOmics cache; deleting it would weaken immutable provenance.
This is a deliberate safety exception to automatic lifecycle cleanup. Delete
only after enumerating active/recoverable run references and retaining a verified
release mirror. S3 disposal is restricted independently to the work prefix.

IAM policies are operationally scoped but not a claim of hostile multi-tenant
isolation. Never copy truth resources under general source/work prefixes. The
controller and benchmark tasks can stage truth; caller inputs must not. The
HealthOmics service role can read truth across the workflow, so any stronger
security boundary would require separately orchestrated workflows/accounts.

## Batch compute and quota gate

Only explicit x86 instance types are allowed. Default `max_vcpus=4`,
`min_vcpus=0`, 300 GiB encrypted gp3 root scratch, no inbound security-group ports.
The small environment is for an approved bounded smoke run; the canonical DAG's
large task requests need larger explicitly selected instance types, a larger
ceiling and effective quotas. Do not reduce scientific requirements to fit 5
vCPUs. Query both On-Demand Standard quota `L-1216C47A` and Spot Standard quota
`L-34B43A08`. A reasonable first requested ceiling for canonical development is
32 vCPUs on the chosen market; quota approval is not capacity availability.

`BEST_FIT_PROGRESSIVE` / `SPOT_PRICE_CAPACITY_OPTIMIZED` may exceed `max_vcpus` by
one instance. Budget and quota headroom must include the largest allowed instance;
this configured ceiling is **not a hard monetary cap**. With the smoke defaults,
allow for up to eight vCPUs during scaling. 5 vCPUs cannot establish canonical
scalability. Spot is opt-in; interruptions retry only under the bounded Nextflow
policy, with durable work and resume evidence. Terraform creates ten digest-pinned task/tool job definitions with separate caller
and benchmark roles; Nextflow overrides their commands/resources at submission.
`batch_job_definitions` exports `job-definition://NAME:REVISION` references for
`cloud_batch_job_definitions`. This is necessary because Nextflow has one global
`aws.batch.jobRole`; unsupported `--job-role` container options are not used.
Supply the reviewed `cloud_support_image` before enabling Batch. Optional
`batch_tool_mirrors` must retain each preregistered upstream manifest digest.

The ECS AL2023 host bootstraps checksum-pinned AWS CLI 2.31.0 in `/opt/giab-awscli` for
Nextflow S3 staging. Set `aws.batch.cliPath='/opt/giab-awscli/bin/aws'` and
`aws.batch.logsGroup` from `log_groups.batch`; use the job/execution role outputs.
The staging client is host software, not a subordinate scientific container.
The Linux x86_64 AWS CLI v2 installer is bound to the SHA-256 of the exact
versioned download from awscli.amazonaws.com; the self-contained bundle avoids
Python venv symlinks resolving against a different scientific image. Every custom
job definition explicitly mounts only `/opt/giab-awscli` read-only. No Docker
socket or other host path is mounted. This bootstrap/staging client has not been
live-qualified against the tool images. A tested, versioned ECS-compatible AMI
is the production-hardening alternative. Capture cloud-init logs,
AMI identity, ECS image and launch-template version with each qualification run.

Networking creates a dedicated VPC, two public subnets, an internet gateway and a
free S3 gateway endpoint only when Batch or Explorer is enabled. There is no NAT
Gateway. Compute gets a public IPv4 address with no inbound ports; Explorer tasks
accept only ALB traffic on 8050. Outbound TLS reaches ECR/S3/CloudWatch and bootstrap
repositories. Private subnets with ECR/Logs interface endpoints and controlled
egress are the production alternative; endpoints/NAT add fixed hourly charges.

## HealthOmics and cache

Use `healthomics_execution_role_arn`, `canonical_output_uri` and
`healthomics_cache_uri` with `scripts/aws/healthomics.py`. Repository policies
allow same-account, same-region HealthOmics workflows to pull project mirrors.
Same-account workflow-role S3 permissions include `cache/`; no public/service-wide
bucket grant is required. Call caching is only an execution recovery aid: retain
source, manifest, input/reference/domain SHA-256, image digests, engine identity,
parameters and cache hit/miss evidence. S3 multipart ETags are not SHA-256 proofs.
Cache storage is billable and not automatically cleaned. Copy final canonical
evidence outside cache/work before cleanup.

## Explorer serving and DNS

After building/scanning the image, provide its project ECR `@sha256:` URI and set
`enable_explorer=true`, `authorize_paid_services=true` in a reviewed plan. Fargate
uses x86 Linux, 0.25 vCPU / 512 MiB, desired count one, a read-only root filesystem
and writable `/tmp`. Circuit breaker rollback and ALB startup grace are enabled.
The ALB checks existing `readyz`; the container checks `healthz`. Readiness means
the bundled synthetic evidence is valid; it is not evidence of a canonical run.
Callbacks only render validated evidence and never calculate biological metrics.

TLS has two supported DNS routes:

1. Existing external DNS: leave `create_delegated_zone=false`. Supply an issued
   us-west-2 ACM certificate, or create only the certificate first with a targeted
   reviewed apply (`-target='module.explorer[0].aws_acm_certificate.explorer[0]'`).
   Read `explorer_certificate_validation_records` and add those CNAMEs to the
   existing DNS provider. After validation, complete the reviewed apply. Add a
   CNAME for `apps.johnpatrickcollins.info` to `explorer_alb_dns_name`.
2. Delegate only `apps.johnpatrickcollins.info`: set `create_delegated_zone=true`.
   First create the subdomain zone/certificate with reviewed targeted applies,
   then add the exact four `apps_delegation_name_servers` as NS records for `apps`
   at the current parent-zone provider. Terraform manages ACM CNAME and ALB alias
   records inside the delegated zone. The parent domain is never migrated.

The ACM validation resource waits up to 30 minutes; external records/delegation
must be in place before completing deployment. DNS and Explorer are optional and
cannot block base scientific infrastructure. Hosted zones, ALB/LCU capacity,
public IPv4, continuous Fargate task time, Container Insights, logs and storage
incur charges even without traffic or analysis. Setting desired count zero stops
Fargate task charges but retains ALB/DNS costs; disabling the Explorer module in a
reviewed apply removes those serving resources. Refresh pricing before approval. A 730-hour/month estimate checked against the
public us-west-2 AWS price lists on 2026-09-10 is:

| Always-on component | Rate / assumption | Estimated USD/month |
|---|---|---:|
| Fargate task | 0.25 vCPU at $0.04048/vCPU-hour + 0.5 GiB at $0.004445/GiB-hour | $9.01 |
| ALB base | $0.0225/hour | $16.43 |
| Public IPv4 | Three addresses (two ALB + one task) at $0.005/address-hour | $10.95 |
| Optional delegated hosted zone | One zone | $0.50 |

The base is approximately **$36.39/month**, or **$36.89 with a hosted zone**,
before ALB LCUs ($0.008/LCU-hour), additional/scaled IPv4 addresses, rolling deploy
overlap, logs/Container Insights, ECR/S3, data transfer, taxes and scientific runs.
One continuously consumed LCU adds $5.84/month. Credits/free-tier discounts are
not assumed. Sources: [Oregon Fargate price list](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonECS/current/us-west-2/index.json),
[Oregon ALB price list](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AWSELB/current/us-west-2/index.json),
[public IPv4 pricing](https://aws.amazon.com/vpc/pricing/),
[Route 53 pricing](https://aws.amazon.com/route53/pricing/).

## Validate and diagnose

```bash
terraform -chdir=infra/aws fmt -check -recursive
terraform -chdir=infra/aws init -backend=false
terraform -chdir=infra/aws validate
terraform -chdir=infra/aws test
```

The mocked-provider tests verify safe defaults, rejection of root and
rejection of implicit paid compute. These checks need no AWS credentials and do not query an account. `plan` does.
After an authorized deployment, inspect Batch `DescribeJobs` attempt
`statusReason`, `container.reason`, exit code and the linked log stream; 137 often
indicates OOM but must be correlated with memory evidence. For HealthOmics retain
`get-run`, paginated `list-run-tasks`, engine logs and task/cache evidence. For
Explorer inspect ECS service events, stopped-task reasons, target health and
`healthz`/`readyz` separately. Enable an account management-event CloudTrail (or
verify an existing organizational trail) before public serving; this module does
not silently duplicate account-wide audit infrastructure.

Primary references: [Nextflow AWS execution](https://docs.seqera.io/nextflow/aws),
[AWS Batch launch templates](https://docs.aws.amazon.com/batch/latest/userguide/launch-templates.html),
[HealthOmics service roles](https://docs.aws.amazon.com/omics/latest/dev/permissions-service.html),
[HealthOmics ECR access](https://docs.aws.amazon.com/omics/latest/dev/permissions-ecr.html),
[HealthOmics caching](https://docs.aws.amazon.com/omics/latest/dev/how-run-cache.html),
[AWS ECS task parameters](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_definition_parameters.html).
