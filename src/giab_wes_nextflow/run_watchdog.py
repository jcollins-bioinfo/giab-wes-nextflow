"""Private gross-cost reservations and bounded, identity-bound run supervision.

This is a conservative admission controller, not a billing cap. Dynamic storage
is reserved from an explicitly reviewed upper estimate: HealthOmics reports its
peak after completion, sometimes not at all for short runs. A killed laptop or
lost credentials can prevent cancellation; the verified server run-group limit
is the remaining backstop. Never describe a cancellation request as completion.

Policy and journal belong outside a repository. No price, account, personal
budget, or credential is embedded here. Completed and failed attempts retain
their full reservations until a separate private cost reconciliation.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import tempfile
import time

from .aws_support import canonical_json, require_role

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}
BOUND_FIELDS = ("workflowId", "workflowType", "roleArn", "name", "runGroupId",
                "parameters", "outputUri", "storageType", "engineSettings", "retentionMode")
FIXED_RESERVES = {"prior_unbilled", "staging_verification", "registry", "s3_logs",
                  "cancellation_cleanup", "billing_delay"}
EXPLICIT_START_REJECTIONS = {"ValidationException", "AccessDeniedException",
                             "ResourceNotFoundException", "ServiceQuotaExceededException"}


class GuardError(ValueError):
    """Admission or run supervision failed closed."""


def money(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise GuardError("A finite nonnegative cost value is required") from None
    if not result.is_finite() or result < 0:
        raise GuardError("A finite nonnegative cost value is required")
    return result


def timestamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise GuardError("Timezone-aware policy timestamp required")
    return result.timestamp()


def utc(now):
    return datetime.fromtimestamp(now, timezone.utc).isoformat()


def private_path(path):
    path = Path(path).resolve()
    if any((p / ".git").exists() for p in path.parents):
        raise GuardError("Watchdog policy and journal must be outside Git checkouts")
    return path


def atomic_json(path, data):
    path = private_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w") as out:
            json.dump(data, out, sort_keys=True, indent=2, default=str)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@contextmanager
def locked(path):
    path = private_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    except BlockingIOError:
        raise GuardError("Another controller holds this journal/request lock") from None
    finally:
        os.close(fd)


def load_policy(path, now=None, *, for_cancel=False):
    p = json.loads(private_path(path).read_text())
    now = time.time() if now is None else now
    if p.get("schema_version") != 1 or not p.get("policy_id"):
        raise GuardError("Unsupported watchdog policy")
    if not for_cancel and not timestamp(p["reviewed_at"]) <= now < timestamp(p["expires_at"]):
        raise GuardError("Watchdog policy is not currently reviewed/valid")
    if not for_cancel and p.get("stop_new_submissions"):
        raise GuardError("New paid submissions stopped by private policy")
    money(p["ceiling_usd"])
    if not re.fullmatch(r"\d{12}", p["account_id"]) or p["region"] != "us-west-2":
        raise GuardError("Private account and qualified region required")
    posted = p["posted_gross_usd"]
    if posted is None:
        if money(p["unknown_posted_upper_bound_usd"]) <= 0 or not p.get("unknown_posted_basis"):
            raise GuardError("Unknown posted gross requires a positive reviewed upper reserve and basis")
    else:
        money(posted)
    if set(p["fixed_reserves_usd"]) != FIXED_RESERVES:
        raise GuardError("Prior accrual, staging, registry, storage/logs, cleanup and billing-delay reserves required")
    for value in p["fixed_reserves_usd"].values():
        money(value)
    if money(p["fixed_reserves_usd"]["cancellation_cleanup"]) <= 0:
        raise GuardError("Positive cancellation/cleanup reserve required")
    if not 1 <= p["poll_seconds"] <= 60 or not 1 <= p["cancel_grace_seconds"] <= 900:
        raise GuardError("Polling/cancellation grace must be bounded")
    for spec in p["reservations"].values():
        group = spec["group"]
        if (not 0 < group["maxCpus"] <= 32 or group["maxRuns"] != 1
                or not 0 < group["maxDuration"] <= 2880 or group.get("maxGpus", 0) != 0):
            raise GuardError("Each approved group must bound CPU, concurrency, duration and GPUs")
        if not group["maxDuration"] * 60 <= spec["max_wall_seconds"] <= 172800:
            raise GuardError("Wall lifetime must cover the server run limit and remain bounded")
        if not 0 < spec["max_memory_gib_per_cpu"] <= 8 or not spec["storage_assumption_basis"]:
            raise GuardError("Reviewed memory and storage assumptions required")
        for key in ("vcpu_hour_usd", "dynamic_gib_hour_usd", "storage_upper_gib"):
            if money(spec[key]) <= 0:
                raise GuardError("Positive conservative resource pricing/size required")
        # Compute includes controller/staging allowance and cancellation grace;
        # rounding reserve covers minimum billed task durations and failed tasks.
        hours = Decimal(spec["max_wall_seconds"] + p["cancel_grace_seconds"]) / Decimal(3600)
        required = hours * (group["maxCpus"] * money(spec["vcpu_hour_usd"])
                            + money(spec["storage_upper_gib"]) * money(spec["dynamic_gib_hour_usd"]))
        if money(spec["rounding_and_task_retry_usd"]) <= 0:
            raise GuardError("Positive task rounding/retry reserve required")
        required += money(spec["rounding_and_task_retry_usd"])
        if money(spec["reservation_usd"]) < required:
            raise GuardError("Run reservation is below its conservative compute/storage/lifetime bound")
    return p


def initialize_ledger(path, policy, *, inventory_observed_at, no_unjournaled_runs):
    """Explicit, one-time initialization after live run/controller reconciliation."""
    if not no_unjournaled_runs:
        raise GuardError("Reconcile existing runs before initializing a journal")
    if not 0 <= time.time() - timestamp(inventory_observed_at) <= 3600:
        raise GuardError("Recent live run inventory required")
    path = private_path(path)
    with locked(path):
        if path.exists():
            raise GuardError("Journal already exists; never reset incurred commitments")
        atomic_json(path, {"schema_version": 1, "policy_id": policy["policy_id"],
                           "inventory_observed_at": inventory_observed_at,
                           "account_id": policy["account_id"], "runs": {}})


def read_ledger(path, policy):
    value = json.loads(private_path(path).read_text())
    if (value.get("schema_version") != 1 or value.get("policy_id") != policy["policy_id"]
            or value.get("account_id") != policy["account_id"]):
        raise GuardError("Journal/policy/account binding differs")
    return value


def projected_gross(policy, ledger):
    posted = policy["posted_gross_usd"]
    # No credits subtraction, and no release for completed or failed attempts.
    baseline = money(policy["unknown_posted_upper_bound_usd"] if posted is None else posted)
    return (baseline + sum(map(money, policy["fixed_reserves_usd"].values()), Decimal(0))
            + sum((money(r["reservation_usd"]) for r in ledger["runs"].values()), Decimal(0)))


def validate_request(policy, request, key, identity):
    require_role(identity)
    prefix = f"arn:aws:sts::{policy['account_id']}:assumed-role/giab-operator/"
    if identity.get("Account") != policy["account_id"] or not identity["Arn"].startswith(prefix):
        raise GuardError("Exact private account and operator role required")
    spec = policy["reservations"][key]
    if (request["runGroupId"] != spec["group"]["id"] or request["workflowId"] != spec["workflow_id"]
            or request["workflowType"] != "PRIVATE" or request["storageType"] != "DYNAMIC"
            or request.get("retentionMode") != "RETAIN" or "runId" in request
            or request["roleArn"].split(":")[4] != policy["account_id"]
            or request.get("tags", {}).get("Project") != "giab-wes-nextflow"
            or not re.fullmatch(r"[0-9a-f]{64}", request["requestId"])):
        raise GuardError("Request does not match approved private reservation")
    return spec


def validate_group(omics, spec):
    expected = spec["group"]
    found = omics.get_run_group(id=expected["id"])
    for key in ("maxCpus", "maxRuns", "maxDuration", "maxGpus"):
        if found.get(key, 0) != expected.get(key, 0):
            raise GuardError("Server run-group bounds differ from private reservation")


def bind_run(omics, request, run_id):
    run = omics.get_run(id=run_id)
    if any(run.get(k) != request.get(k) for k in BOUND_FIELDS):
        raise GuardError("Run identity differs; refusing to control an unrelated run")
    if run.get("tags", {}).get("WatchdogRequest") != request["requestId"]:
        raise GuardError("Run lacks the deterministic controller binding")
    return run


def discover_run(omics, request):
    found = []
    for page in omics.get_paginator("list_runs").paginate(runGroupId=request["runGroupId"]):
        for item in page.get("items", []):
            if item.get("name") == request["name"]:
                run = bind_run(omics, request, item["id"])
                found.append(run)
    if len(found) > 1:
        raise GuardError("Multiple matching runs; manual reconciliation required")
    return found[0] if found else None


def update_record(path, policy, request_id, **values):
    with locked(path):
        ledger = read_ledger(path, policy)
        ledger["runs"][request_id].update(values)
        atomic_json(path, ledger)


def prepare_submission(omics, request, policy, ledger_path, key, identity, now):
    """Reserve before StartRun; an uncertain submission is never blindly retried."""
    request = json.loads(json.dumps(request))
    request.setdefault("tags", {})["WatchdogRequest"] = request["requestId"]
    spec = validate_request(policy, request, key, identity)
    validate_group(omics, spec)
    digest = hashlib.sha256(canonical_json(request)).hexdigest()
    with locked(ledger_path):
        ledger = read_ledger(ledger_path, policy)
        if ledger.get("reconciliation_required"):
            raise GuardError("Private cost/run reconciliation required before another submission")
        prior = ledger["runs"].get(request["requestId"])
        if prior:
            if prior["request_sha256"] != digest or prior["reservation_key"] != key:
                raise GuardError("Deterministic request identity changed")
        else:
            # One attempt per reservation key; a retry requires another explicitly
            # budgeted key. The failed attempt remains charged in this journal.
            if any(r["reservation_key"] == key for r in ledger["runs"].values()):
                raise GuardError("Reservation already consumed; explicitly reserve any retry")
            ledger["runs"][request["requestId"]] = {
                "request_sha256": digest, "request": request, "reservation_key": key,
                "reservation_usd": str(money(spec["reservation_usd"])),
                "submitted_at": utc(now), "deadline": utc(now + spec["max_wall_seconds"]),
                "status": "RESERVED", "run_id": None,
            }
        if projected_gross(policy, ledger) > money(policy["ceiling_usd"]):
            raise GuardError("Gross incurred/committed/reserved total exceeds authorized ceiling")
        existing = discover_run(omics, request)
        if existing:
            ledger["runs"][request["requestId"]].update(run_id=existing["id"], status=existing["status"])
        elif prior:
            raise GuardError("Prior submission outcome unknown; inspect runs before any resubmission")
        atomic_json(ledger_path, ledger)
    return request, existing


def task_limits(omics, run_id, spec):
    for page in omics.get_paginator("list_run_tasks").paginate(id=run_id):
        for task in page.get("items", []):
            # Cached entries may omit requested resources and consume no compute.
            if task.get("cacheHit"):
                continue
            cpus, memory = task.get("cpus"), task.get("memory")
            if cpus is not None and (cpus <= 0 or cpus > spec["group"]["maxCpus"]):
                raise GuardError("Observed task CPU request exceeds reservation")
            if memory is not None and cpus and Decimal(str(memory)) > cpus * money(spec["max_memory_gib_per_cpu"]):
                raise GuardError("Observed task memory selects an unreserved price class")
            if task.get("gpus", 0):
                raise GuardError("Unreserved GPU task observed")


def cancel_bound(omics, request, ledger_path, policy, *, now=time.time, sleep=time.sleep,
                 monotonic=time.monotonic):
    """Return only with verified terminal state; failures remain durably unsafe."""
    record = read_ledger(ledger_path, policy)["runs"][request["requestId"]]
    run_id = record.get("run_id")
    deadline = monotonic() + policy["cancel_grace_seconds"]
    last_error = None
    while monotonic() < deadline:
        try:
            if not run_id:
                found = discover_run(omics, request)
                if not found:
                    sleep(min(policy["poll_seconds"], max(0, deadline - monotonic())))
                    continue
                run_id = found["id"]
                update_record(ledger_path, policy, request["requestId"], run_id=run_id)
            run = bind_run(omics, request, run_id)
            if run["status"] in TERMINAL:
                update_record(ledger_path, policy, request["requestId"], status=run["status"],
                              terminal_verified_at=utc(now()), cancellation_pending=False)
                return run
            update_record(ledger_path, policy, request["requestId"], cancellation_pending=True,
                          cancel_requested_at=utc(now()))
            omics.cancel_run(id=run_id)
        except GuardError:
            raise  # Never cancel a mismatched run.
        except Exception as exc:
            last_error = type(exc).__name__
            if run_id:
                # A successful StartRun response or exact discovered identity
                # already binds this ID. A denied/transient GetRun must not
                # prevent the independent cancellation attempt.
                try:
                    omics.cancel_run(id=run_id)
                except Exception as cancel_exc:
                    last_error = type(cancel_exc).__name__
        sleep(min(policy["poll_seconds"], max(0, deadline - monotonic())))
    update_record(ledger_path, policy, request["requestId"], status="CANCELLATION_UNCONFIRMED" if run_id else "SUBMISSION_UNKNOWN",
                  cancellation_pending=True, last_error_type=last_error)
    raise GuardError("Cancellation not confirmed; server group timeout is the remaining backstop")


@contextmanager
def stop_signals():
    previous = {}
    def stop(signum, frame):
        # Ignore repeated termination while bounded cancellation is in progress.
        for sig in previous:
            signal.signal(sig, signal.SIG_IGN)
        raise KeyboardInterrupt("Controller stop requested")
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, stop)
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def run_guarded(*, omics, request, policy_path, ledger_path, reservation_key, identity,
                now=time.time, sleep=time.sleep, monotonic=time.monotonic):
    """Blocking launch+watch entry point; launchers must retain this controller."""
    policy = load_policy(policy_path, now())
    request_id = request["requestId"]
    # Held for the whole run, while the short shared journal lock permits another
    # separately reserved group to execute concurrently.
    with locked(str(ledger_path) + "." + request_id), stop_signals():
        bound_request, existing = prepare_submission(
            omics, request, policy, ledger_path, reservation_key, identity, now())
        record = read_ledger(ledger_path, policy)["runs"][request_id]
        # The persisted UTC deadline supports restarts. The process-local
        # monotonic deadline also survives backward corrections of wall time.
        monotonic_deadline = monotonic() + max(0, timestamp(record["deadline"]) - now())
        operation = "JournalUpdate"
        try:
            if existing is None:
                update_record(ledger_path, policy, request_id, status="SUBMITTING")
                operation = "StartRun"
                response = omics.start_run(**bound_request)
                operation = "JournalUpdate"
                update_record(ledger_path, policy, request_id, run_id=response["id"], status=response["status"])
            spec = policy["reservations"][reservation_key]
            while True:
                operation = "PolicyAndJournalValidation"
                current_policy = load_policy(policy_path, now())
                if canonical_json(current_policy) != canonical_json(policy):
                    raise GuardError("Policy changed during execution; cancel and reconcile")
                ledger = read_ledger(ledger_path, policy)
                record = ledger["runs"][request_id]
                operation = "GetRun"
                run = bind_run(omics, bound_request, record["run_id"])
                operation = "JournalUpdate"
                peak = run.get("storageCapacity") if run["status"] in TERMINAL else None
                update_record(ledger_path, policy, request_id, status=run["status"], heartbeat_at=utc(now()),
                              dynamic_storage_peak_gib=peak or None,
                              dynamic_storage_observation="post-run peak; live upper estimate reserved")
                if run["status"] in TERMINAL:
                    update_record(ledger_path, policy, request_id, terminal_verified_at=utc(now()))
                    operation = "ListRunTasks"
                    task_limits(omics, run["id"], spec)
                    if peak and money(peak) > money(spec["storage_upper_gib"]):
                        raise GuardError("Completed dynamic storage exceeds reservation; reconcile before new work")
                    return run
                if now() >= timestamp(record["deadline"]) or monotonic() >= monotonic_deadline:
                    raise GuardError("Bounded controller wall lifetime exceeded")
                if projected_gross(policy, ledger) > money(policy["ceiling_usd"]):
                    raise GuardError("Gross reservation ceiling exceeded")
                operation = "GetRunGroup"
                validate_group(omics, spec)
                operation = "ListRunTasks"
                task_limits(omics, run["id"], spec)
                operation = "ControllerWait"
                sleep(min(policy["poll_seconds"], max(0, timestamp(record["deadline"]) - now()),
                          max(0, monotonic_deadline - monotonic())))
        except BaseException as exc:
            with locked(ledger_path):
                ledger = read_ledger(ledger_path, policy)
                ledger["reconciliation_required"] = True
                failed = ledger["runs"][request_id]
                # Preserve the originating exception before any cancellation
                # attempts. Provider details stay in this private journal;
                # later cleanup failures must not overwrite the original.
                failed["original_error"] = {"type": type(exc).__name__, "message": str(exc),
                                            "operation": operation, "observed_at": utc(now())}
                rejected = False
                if operation == "StartRun" and not failed.get("run_id"):
                    from botocore.exceptions import ClientError
                    if isinstance(exc, ClientError):
                        code = exc.response.get("Error", {}).get("Code")
                        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
                        rejected = code in EXPLICIT_START_REJECTIONS and 400 <= status < 500
                        if rejected:
                            failed.update(status="SUBMISSION_REJECTED", submission_rejection_code=code,
                                          cancellation_pending=False)
                atomic_json(ledger_path, ledger)
            if rejected:
                raise  # Explicit service rejection incurred no accepted run ID.
            cancel_bound(omics, bound_request, ledger_path, policy, now=now, sleep=sleep, monotonic=monotonic)
            raise
