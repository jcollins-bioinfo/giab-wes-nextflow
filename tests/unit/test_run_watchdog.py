"""Run admission and cancellation tests use invented costs and no cloud access."""
import copy
import json
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

from giab_wes_nextflow import run_watchdog as guard


class Clock:
    def __init__(self):
        self.value = time.time()

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class Omics:
    def __init__(self, spec):
        self.spec = spec
        self.runs = {}
        self.starts = []
        self.cancels = []
        self.tasks = []
        self.start_error = False
        self.list_error = False
        self.cancel_completes = True
        self.complete_on_read = True

    def get_run_group(self, **kwargs):
        return self.spec["group"]

    def get_paginator(self, operation):
        outer = self
        class Paginator:
            def paginate(self, **kwargs):
                if outer.list_error:
                    raise PermissionError("Denied inventory is unknown")
                if operation == "list_runs":
                    return [{"items": list(outer.runs.values())}]
                assert operation == "list_run_tasks"
                return [{"items": outer.tasks}]
        return Paginator()

    def start_run(self, **request):
        self.starts.append(request)
        self.runs["123"] = dict(request, id="123", status="RUNNING")
        if self.start_error:
            raise ConnectionError("Response lost after service accepted submission")
        return {"id": "123", "status": "RUNNING"}

    def get_run(self, id):
        result = self.runs[id]
        if self.complete_on_read:
            result["status"] = "COMPLETED"
        return result

    def cancel_run(self, id):
        self.cancels.append(id)
        if self.cancel_completes:
            self.runs[id]["status"] = "CANCELLED"


@pytest.fixture
def case(tmp_path):
    clock = Clock()
    policy = {
        "schema_version": 1, "policy_id": "test-only", "account_id": "111122223333",
        "region": "us-west-2", "reviewed_at": guard.utc(clock.now() - 10),
        "expires_at": guard.utc(clock.now() + 3600), "ceiling_usd": "10",
        "posted_gross_usd": None, "unknown_posted_upper_bound_usd": "2",
        "unknown_posted_basis": "Invented fixture reserve; no billing claim",
        "fixed_reserves_usd": {key: "0.1" for key in guard.FIXED_RESERVES},
        "poll_seconds": 5, "cancel_grace_seconds": 20,
        "reservations": {"fixture": {
            "workflow_id": "88", "group": {"id": "77", "maxCpus": 2, "maxRuns": 1,
                                               "maxDuration": 10, "maxGpus": 0},
            "max_wall_seconds": 600, "max_memory_gib_per_cpu": 8,
            "storage_assumption_basis": "Reviewed deterministic nonhuman fixture",
            "storage_upper_gib": "2", "vcpu_hour_usd": "1", "dynamic_gib_hour_usd": "0.1",
            "rounding_and_task_retry_usd": "0.1", "reservation_usd": "1",
        }},
    }
    identity = {"Account": policy["account_id"],
                "Arn": "arn:aws:sts::111122223333:assumed-role/giab-operator/fixture"}
    request = {
        "workflowId": "88", "workflowType": "PRIVATE", "name": "fixture-run", "runGroupId": "77",
        "roleArn": "arn:aws:iam::111122223333:role/fixture-execution", "parameters": {"seed": "invented"},
        "outputUri": "s3://invented-fixture-bucket/results/", "storageType": "DYNAMIC", "retentionMode": "RETAIN",
        "engineSettings": {"engineVersion": "26.04.0", "syntaxVersion": "v2"},
        "tags": {"Project": "giab-wes-nextflow"}, "requestId": "a" * 64,
    }
    policy_path, ledger = tmp_path / "policy.json", tmp_path / "ledger.json"
    guard.atomic_json(policy_path, policy)
    guard.initialize_ledger(ledger, policy, inventory_observed_at=guard.utc(clock.now()), no_unjournaled_runs=True)
    omics = Omics(policy["reservations"]["fixture"])
    args = dict(omics=omics, request=request, policy_path=policy_path, ledger_path=ledger,
                reservation_key="fixture", identity=identity, now=clock.now, sleep=clock.sleep, monotonic=clock.now)
    return policy, args, clock


def save_policy(policy, args):
    guard.atomic_json(args["policy_path"], policy)


def record(args):
    return json.loads(args["ledger_path"].read_text())["runs"][args["request"]["requestId"]]


def test_success_keeps_full_reserve_and_unknown_billing(case):
    policy, args, _ = case
    assert guard.run_guarded(**args)["status"] == "COMPLETED"
    assert len(args["omics"].starts) == 1
    assert args["omics"].starts[0]["tags"]["WatchdogRequest"] == args["request"]["requestId"]
    assert record(args)["reservation_usd"] == "1"
    assert policy["posted_gross_usd"] is None
    assert guard.projected_gross(policy, guard.read_ledger(args["ledger_path"], policy)) == guard.money("3.6")
    assert args["ledger_path"].stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("value", [None, -1, "NaN", "Infinity", "-Infinity"])
def test_invalid_cost_rejected(value):
    with pytest.raises(guard.GuardError):
        guard.money(value)


def test_unknown_posted_never_zero(case):
    policy, args, _ = case
    policy["unknown_posted_upper_bound_usd"] = "0"
    save_policy(policy, args)
    with pytest.raises(guard.GuardError, match="Unknown posted gross"):
        guard.run_guarded(**args)
    assert not args["omics"].starts


def test_estimated_posted_zero_still_retains_unbilled_reserves(case):
    policy, args, _ = case
    policy["posted_gross_usd"] = "0"
    save_policy(policy, args)
    guard.run_guarded(**args)
    assert guard.projected_gross(policy, guard.read_ledger(args["ledger_path"], policy)) == guard.money("1.6")


def test_reservation_failure_stops_before_start(case):
    policy, args, _ = case
    policy["ceiling_usd"] = "3"
    save_policy(policy, args)
    with pytest.raises(guard.GuardError, match="ceiling"):
        guard.run_guarded(**args)
    assert not args["omics"].starts


def test_storage_and_cancel_grace_are_included(case):
    policy, args, _ = case
    policy["reservations"]["fixture"]["reservation_usd"] = "0.2"
    save_policy(policy, args)
    with pytest.raises(guard.GuardError, match="compute/storage/lifetime"):
        guard.run_guarded(**args)


def test_denied_inventory_is_not_empty(case):
    _, args, _ = case
    args["omics"].list_error = True
    with pytest.raises(PermissionError):
        guard.run_guarded(**args)
    assert not args["omics"].starts


def test_retry_existing_request_never_starts_twice(case):
    _, args, _ = case
    guard.run_guarded(**args)
    guard.run_guarded(**args)
    assert len(args["omics"].starts) == 1


def test_changed_request_under_same_id_rejected(case):
    _, args, _ = case
    guard.run_guarded(**args)
    args["request"]["parameters"]["seed"] = "changed"
    with pytest.raises(guard.GuardError, match="identity changed"):
        guard.run_guarded(**args)
    assert len(args["omics"].starts) == 1


def test_new_attempt_cannot_reuse_old_reservation(case):
    _, args, _ = case
    guard.run_guarded(**args)
    args["request"]["requestId"] = "b" * 64
    with pytest.raises(guard.GuardError, match="already consumed"):
        guard.run_guarded(**args)


def test_lost_submission_response_reconciles_then_cancels(case):
    _, args, _ = case
    args["omics"].complete_on_read = False
    args["omics"].start_error = True
    with pytest.raises(ConnectionError):
        guard.run_guarded(**args)
    assert len(args["omics"].starts) == 1
    assert args["omics"].cancels == ["123"]
    assert record(args)["status"] == "CANCELLED"
    assert record(args)["reservation_usd"] == "1"
    assert record(args)["original_error"]["operation"] == "StartRun"
    assert record(args)["original_error"]["type"] == "ConnectionError"


@pytest.mark.parametrize("code", sorted(guard.EXPLICIT_START_REJECTIONS))
def test_explicit_start_rejection_is_recorded_without_cancel_wait(case, code):
    from botocore.exceptions import ClientError
    _, args, clock = case
    observed = clock.now()
    def rejected_start(**request):
        raise ClientError({"Error": {"Code": code, "Message": "Exact invented rejection detail"},
                           "ResponseMetadata": {"HTTPStatusCode": 400}}, "StartRun")
    args["omics"].start_run = rejected_start
    with pytest.raises(ClientError, match="Exact invented rejection detail"):
        guard.run_guarded(**args)
    found = record(args)
    assert found["status"] == "SUBMISSION_REJECTED"
    assert found["reservation_usd"] == "1" and found["run_id"] is None
    assert found["original_error"]["operation"] == "StartRun"
    assert "Exact invented rejection detail" in found["original_error"]["message"]
    assert clock.now() == observed and not args["omics"].cancels


def test_server_error_remains_ambiguous_and_original_is_saved_before_discovery(case):
    from botocore.exceptions import ClientError
    _, args, clock = case
    initial = clock.now()
    def server_error(**request):
        raise ClientError({"Error": {"Code": "ValidationException", "Message": "Invented server fault"},
                           "ResponseMetadata": {"HTTPStatusCode": 500}}, "StartRun")
    args["omics"].start_run = server_error
    original_sleep = args["sleep"]
    def inspect_before_wait(seconds):
        assert record(args)["original_error"]["operation"] == "StartRun"
        assert "Invented server fault" in record(args)["original_error"]["message"]
        original_sleep(seconds)
    args["sleep"] = inspect_before_wait
    with pytest.raises(guard.GuardError, match="Cancellation not confirmed"):
        guard.run_guarded(**args)
    assert record(args)["status"] == "SUBMISSION_UNKNOWN"
    assert clock.now() > initial and not args["omics"].cancels


def test_deadline_cancels_and_verifies_terminal(case):
    _, args, _ = case
    args["omics"].complete_on_read = False
    with pytest.raises(guard.GuardError, match="wall lifetime"):
        guard.run_guarded(**args)
    assert args["omics"].cancels == ["123"]
    assert record(args)["terminal_verified_at"]


def test_memory_outside_price_assumption_cancels(case):
    _, args, _ = case
    args["omics"].complete_on_read = False
    args["omics"].tasks = [{"cpus": 2, "memory": 32}]
    with pytest.raises(guard.GuardError, match="unreserved price class"):
        guard.run_guarded(**args)
    assert args["omics"].cancels == ["123"]


def test_cancellation_request_is_not_terminal_proof(case):
    _, args, _ = case
    args["omics"].complete_on_read = False
    args["omics"].cancel_completes = False
    args["omics"].tasks = [{"cpus": 2, "memory": 32}]
    with pytest.raises(guard.GuardError, match="Cancellation not confirmed"):
        guard.run_guarded(**args)
    assert record(args)["status"] == "CANCELLATION_UNCONFIRMED"
    assert "terminal_verified_at" not in record(args)


def test_signal_cancels_and_restores_previous_handler(case):
    _, args, clock = case
    args["omics"].complete_on_read = False
    original = signal.getsignal(signal.SIGTERM)
    first = True
    def sleep(seconds):
        nonlocal first
        if first:
            first = False
            signal.raise_signal(signal.SIGTERM)
        clock.sleep(seconds)
    args["sleep"] = sleep
    with pytest.raises(KeyboardInterrupt):
        guard.run_guarded(**args)
    assert args["omics"].cancels == ["123"]
    assert signal.getsignal(signal.SIGTERM) == original


def test_unrelated_run_never_cancelled(case):
    policy, args, _ = case
    guard.run_guarded(**args)
    args["omics"].runs["123"]["parameters"] = {"seed": "unrelated"}
    with pytest.raises(guard.GuardError, match="unrelated"):
        guard.cancel_bound(args["omics"], record(args)["request"], args["ledger_path"], policy,
                           now=args["now"], sleep=args["sleep"], monotonic=args["monotonic"])
    assert not args["omics"].cancels


@pytest.mark.parametrize("field,changed", [
    ("engineSettings", {"engineVersion": "26.04.6", "syntaxVersion": "v2"}),
    ("engineSettings", {"engineVersion": "26.04.0", "syntaxVersion": "v1"}),
    ("retentionMode", "REMOVE"),
])
def test_engine_parser_and_retention_are_read_back_before_control(case, field, changed):
    policy, args, _ = case
    guard.run_guarded(**args)
    args["omics"].runs["123"][field] = changed
    with pytest.raises(guard.GuardError, match="Run identity differs"):
        guard.cancel_bound(args["omics"], record(args)["request"], args["ledger_path"], policy,
                           now=args["now"], sleep=args["sleep"], monotonic=args["monotonic"])
    assert not args["omics"].cancels


def test_expired_stopped_policy_allows_scoped_cancellation(case):
    policy, args, clock = case
    policy.update(expires_at=guard.utc(clock.now() - 1), stop_new_submissions=True)
    save_policy(policy, args)
    with pytest.raises(guard.GuardError):
        guard.load_policy(args["policy_path"])
    assert guard.load_policy(args["policy_path"], for_cancel=True)["stop_new_submissions"]


def test_existing_ledger_cannot_be_reset(case):
    policy, args, clock = case
    with pytest.raises(guard.GuardError, match="never reset"):
        guard.initialize_ledger(args["ledger_path"], policy,
                                inventory_observed_at=guard.utc(clock.now()), no_unjournaled_runs=True)


def test_private_files_cannot_be_written_inside_git(tmp_path):
    (tmp_path / ".git").mkdir()
    with pytest.raises(guard.GuardError, match="outside Git"):
        guard.atomic_json(tmp_path / "private.json", {})


def test_concurrent_controller_lock_rejected(case):
    _, args, _ = case
    with guard.locked(str(args["ledger_path"]) + "." + args["request"]["requestId"]):
        with pytest.raises(guard.GuardError, match="Another controller"):
            guard.run_guarded(**args)
    assert not args["omics"].starts


@pytest.mark.parametrize("script", ["start_cloud_index.py", "start_native_qualification.py"])
def test_launchers_require_watchdog_configuration_before_aws(script, tmp_path):
    import sys
    path = Path(__file__).resolve().parents[2] / "scripts" / "aws" / script
    command = [sys.executable, str(path), "--work", str(tmp_path)]
    if script == "start_cloud_index.py":
        command += ["--receipts", str(tmp_path)]
    result = subprocess.run(command, capture_output=True, text=True,
                            env={**os.environ, "GIAB_AWS_ACCOUNT_ID": "111122223333"}, timeout=10)
    assert result.returncode == 2
    assert "--watchdog-policy" in result.stderr and "--watchdog-ledger" in result.stderr
