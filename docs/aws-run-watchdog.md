# Bounded HealthOmics run supervision

`giab_wes_nextflow.run_watchdog.run_guarded` is a blocking launch-and-supervise
entry point. A launcher must complete its scientific, image, immutable-package,
source-object and operator-identity gates first. Replace only its final
`start_run` call with `run_guarded`; the watchdog does not qualify science.

The caller supplies an authenticated `omics` client, its verified STS `identity`,
the exact `request`, a `reservation_key`, and private `policy_path` and
`ledger_path` paths. Both files must be outside Git checkouts. The controller
must keep running until a terminal status is verified. A failed scientific run
can be terminal; inspect the returned `status` before claiming success.

Private policy schema version 1 requires:

- `policy_id`, `account_id`, `region`, `reviewed_at`, and `expires_at` (UTC ISO
  timestamps), `ceiling_usd`, and `posted_gross_usd`.
- If posted gross is unknown, `posted_gross_usd` is null and a positive
  `unknown_posted_upper_bound_usd` plus `unknown_posted_basis` are mandatory.
  Estimated posted charges must retain separate allowance for delayed accrual.
- `fixed_reserves_usd` has exactly `prior_unbilled`, `staging_verification`,
  `registry`, `s3_logs`, `cancellation_cleanup`, and `billing_delay`. Cleanup
  must have a positive reserve. No credits are subtracted from gross costs.
- `poll_seconds` is between 1 and 60; `cancel_grace_seconds` between 1 and 900.
- `reservations` maps each approved attempt key to `workflow_id`,
  `group` (`id`, `maxCpus`, `maxRuns`, `maxDuration`, `maxGpus`),
  `max_wall_seconds`, `max_memory_gib_per_cpu`, `storage_assumption_basis`,
  `storage_upper_gib`, `vcpu_hour_usd`, `dynamic_gib_hour_usd`,
  `rounding_and_task_retry_usd`, and `reservation_usd`.

Each reservation must cover the maximum CPU and reviewed dynamic-storage
estimate for wall lifetime plus cancellation grace, with a separate positive
allowance for minimum task billing and task retries. Group concurrency is one;
parallel distinct groups consume their combined journal reservations. Resource
prices are operator-supplied conservative inputs, not embedded pricing claims.
CPU/memory requests from task observations must remain within the reviewed
price assumptions. Workflow retries must also fit the approved duration and
rounding allowance.

Initialize the private ledger once with `initialize_ledger(path, policy,
inventory_observed_at=..., no_unjournaled_runs=True)` after a successful recent
live run/controller inventory. It refuses to overwrite an existing ledger.
Every attempt retains its full reservation after completion, failure or
cancellation. Adjust private accounting only after explicit reconciliation;
never erase the ledger or treat a failed attempt as free. A supervision error
sets `reconciliation_required`, blocking further submissions until resolved.

A deterministic request is saved before submission. A dedicated
`WatchdogRequest` tag binds discovery and cancellation to the full request.
An ambiguous API outcome is inspected using the existing request identity;
the controller never blindly resubmits. A new attempt needs a separately
budgeted reservation key. Per-request lifetime locks prevent duplicate
controllers, and atomic private journal updates protect shared commitments.

Resume supervision with `scripts/aws/watch_run.py --policy PRIVATE_POLICY
--ledger PRIVATE_LEDGER --request-id REQUEST_ID`; append `--cancel` for scoped
cancellation. Cancellation remains available after policy expiry or a
`stop_new_submissions` flag. The command controls only the identity bound in
the private journal. It never deletes run metadata or durable outputs.

SIGINT, SIGTERM, deadline expiry, changed policy, resource-bound violations or
monitor failures trigger a bounded cancellation attempt. The journal records
`CANCELLATION_UNCONFIRMED` or `SUBMISSION_UNKNOWN` if terminal state cannot be
verified. These states require operator action; they are not proof of cleanup.

The server-side run-group duration is verified before admission and during
execution. It is a backstop if the local controller dies, sleeps, loses network
access, or loses credentials; this local process cannot guarantee cancellation
while unavailable. Retain a functioning authenticated controller and verify
the remaining server-side bounds before allowing unattended completion.

Dynamic storage is not a live hard cap. HealthOmics reports its peak through
`GetRun.storageCapacity` after completion, and short runs may lack that value.
The watchdog keeps this observation unavailable until reported, reserves an
explicit reviewed upper estimate, and requires reconciliation if the returned
peak exceeds it. Run-group ceilings, these estimates, and cancellation calls
do not constitute instantaneous or perfect billing enforcement. See
[AWS run storage documentation](https://docs.aws.amazon.com/omics/latest/dev/workflows-run-types.html).
