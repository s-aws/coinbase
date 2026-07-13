"""No-live preparation and transition tests for sealed V15R6 recovery."""

from __future__ import annotations

from copy import deepcopy
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import signal
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from application.admin_api import root_child_cancel as authority
from tests.unit.test_admin_api_root_child_cancel_v15r3 import _v15r5_plan
from tools import run_controlled_admin_spot_child_cancel_recovery_v15r6 as recovery


NOW = datetime(2026, 7, 13, 9, 0, tzinfo=timezone.utc)
APPROVAL_ID = (
    "controlled-child-cancel-v15r6-"
    "55555555-5555-4555-8555-555555555555"
)


def _plan(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    source = _v15r5_plan()
    monkeypatch.setattr(recovery, "backend_commit", lambda: "a" * 40)
    monkeypatch.setattr(recovery, "frontend_commit", lambda: "b" * 40)
    monkeypatch.setattr(recovery, "runner_sha256", lambda: "c" * 64)
    return recovery.build_v15r6_plan(
        source,
        local_active_child=dict(source["local_active_child_binding"]),
        rejected_v15r5_execution_binding=deepcopy(
            authority.CONTROLLED_V15R6_REJECTED_EXECUTION_BINDING
        ),
        now=NOW,
        approval_id=APPROVAL_ID,
    )


def test_v15r6_plan_is_exact_direct_exchange_id_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _v15r5_plan()
    assert NOW > datetime.fromisoformat(str(source["expires_at"]))
    plan = _plan(monkeypatch)

    assert plan["schema_version"] == "24"
    assert plan["authority_kind"] == authority.CONTROLLED_V15R6_AUTHORITY_KIND
    assert plan["placement_attempt_count"] == 0
    assert plan["cancel_command_maximum"] == 1
    assert plan["exchange_cancel_submission_identity"] == (
        "authoritative_exchange_order_id_resolved_from_client_order_id"
    )
    assert plan["exchange_order_id_fallback_authorized"] is False
    assert plan["predecessor_runtime_signal_attempt_maximum"] == 1
    assert plan["predecessor_runtime_restart_attempt_maximum"] == 0
    assert plan["predecessor_runtime_signal"] == "SIGTERM"
    assert plan["runtime_no_overlap_required"] is True
    assert plan["rejected_v15r5_execution_binding"] == (
        authority.CONTROLLED_V15R6_REJECTED_EXECUTION_BINDING
    )
    assert plan["plan_sha256"] == recovery.plan_hash(plan)
    assert (
        datetime.fromisoformat(str(plan["expires_at"]))
        - datetime.fromisoformat(str(plan["created_at"]))
    ).total_seconds() == 120 * 60
    assert datetime.fromisoformat(str(plan["created_at"])) == NOW
    recovery.validate_v15r6_plan_structure(
        plan,
        expected_hash=str(plan["plan_sha256"]),
        now=NOW,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("exchange_cancel_submission_identity", "client_order_id_first"),
        ("predecessor_runtime_signal_attempt_maximum", 2),
        ("predecessor_runtime_restart_attempt_maximum", 1),
        ("predecessor_runtime_signal", "SIGKILL"),
        ("runtime_no_overlap_required", False),
    ],
)
def test_v15r6_plan_rejects_submission_or_transition_broadening(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    plan = _plan(monkeypatch)
    plan[field] = value
    plan["plan_sha256"] = recovery.plan_hash(plan)

    with pytest.raises(recovery.ProofFailure):
        recovery.validate_v15r6_plan_structure(
            plan,
            expected_hash=str(plan["plan_sha256"]),
            now=NOW,
        )


def test_parent_loss_projection_excludes_mutable_timestamp_and_order_payload() -> None:
    report = {
        **dict(
            authority.CONTROLLED_V15R6_REJECTED_EXECUTION_BINDING[
                "parent_authority_loss_semantic_projection"
            ]
        ),
        "updated_at": "changes-every-poll",
        "authoritative_active_orders": [{"updated_time": "also-mutable"}],
        "sealed_cancel_reconciliation": {"readiness": {"detail": "mutable"}},
    }

    assert recovery.parent_authority_loss_projection(report) == (
        authority.CONTROLLED_V15R6_REJECTED_EXECUTION_BINDING[
            "parent_authority_loss_semantic_projection"
        ]
    )


def test_rejected_v15r5_source_scope_uses_its_historical_plan_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = {"created_at": "2026-07-13T07:33:32.146852+00:00"}
    observed: list[datetime | None] = []
    monkeypatch.setattr(
        recovery.authority,
        "validate_controlled_v15r5_recovery_plan_scope",
        lambda _plan, *, now=None: observed.append(now),
    )

    recovery.validate_rejected_v15r5_source_plan(source)

    assert observed == [datetime.fromisoformat(source["created_at"])]


def test_v15r6_consumes_both_exact_service_disable_records() -> None:
    expected = deepcopy(authority.CONTROLLED_V15R6_REJECTED_EXECUTION_BINDING)
    rows = [
        {
            "service_enabled": False,
            "requested_service_status": "live_disabled",
            "live_coinbase_execution_approved": False,
            "max_submitted_notional_usdc": "0",
            "max_executed_notional_usdc": "0",
            "decision_id": "transition-disable",
        },
        {
            "service_enabled": False,
            "requested_service_status": "live_disabled",
            "live_coinbase_execution_approved": False,
            "max_submitted_notional_usdc": "0",
            "max_executed_notional_usdc": "0",
            "decision_id": "parent-loss-disable",
        },
    ]
    expected["record_hashes"] = {
        **dict(expected["record_hashes"]),
        "service_disabled": recovery._canonical_record_sha256(rows[0]),
        "parent_loss_service_disabled": recovery._canonical_record_sha256(
            rows[1]
        ),
    }

    recovery.validate_rejected_v15r5_service_disable_records(rows, expected)

    rows[0]["max_submitted_notional_usdc"] = "2.00"
    with pytest.raises(recovery.ProofFailure, match="service_disable_record"):
        recovery.validate_rejected_v15r5_service_disable_records(rows, expected)


def test_v15r6_final_sentinel_requires_runtime_exit_and_zero_sdk_calls() -> None:
    sentinel = {
        "phase": "runtime_exited",
        "process_id": 695321,
        "root_create_order_call_count": 0,
        "root_create_order_maximum": 0,
        "child_place_limit_order_call_count": 0,
        "child_place_limit_order_maximum": 0,
        "root_sdk_inflight": False,
        "child_sdk_inflight": False,
        "critical_failure": False,
        "denied_call_count": 0,
        "installed": True,
        "wrapper_identity_proven": True,
        "error": None,
    }

    recovery.validate_final_v15r5_sentinel(sentinel, expected_process_id=695321)

    sentinel["child_place_limit_order_call_count"] = 1
    with pytest.raises(recovery.ProofFailure, match="final_sentinel"):
        recovery.validate_final_v15r5_sentinel(
            sentinel, expected_process_id=695321
        )


def test_v15r6_transition_signals_exact_predecessor_once_and_never_restarts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(monkeypatch)
    identity = dict(
        authority.CONTROLLED_V15R6_REJECTED_EXECUTION_BINDING[
            "runtime_process_identity"
        ]
    )
    calls: list[tuple[dict[str, object], int]] = []
    monkeypatch.setattr(
        recovery,
        "load_rejected_v15r5_execution_binding",
        lambda: deepcopy(authority.CONTROLLED_V15R6_REJECTED_EXECUTION_BINDING),
    )
    monkeypatch.setattr(recovery, "_read_process_identity", lambda _pid: identity)
    monkeypatch.setattr(
        recovery,
        "signal_exact_process",
        lambda exact, signum: calls.append((dict(exact), signum)),
    )
    monkeypatch.setattr(recovery, "wait_exact_process_absent", lambda _exact: True)
    monkeypatch.setattr(
        recovery,
        "prove_admin_port_free",
        lambda: {"port": 8787, "free": True, "competitor_pid": None},
    )
    monkeypatch.setattr(
        recovery,
        "read_exact_active_child_after_transition",
        lambda: deepcopy(
            authority.CONTROLLED_V15R6_REJECTED_EXECUTION_BINDING[
                "child_readback"
            ]
        ),
    )
    monkeypatch.setattr(
        recovery,
        "final_mutable_artifact_hashes",
        lambda: {
            "parent_authority_loss": "d" * 64,
            "runtime_log": "e" * 64,
            "sentinel": "f" * 64,
        },
    )
    monkeypatch.setattr(
        recovery, "validate_v15r6_clean_synced_environment", lambda _plan: None
    )
    signal_claim_path = tmp_path / "signal-claim.json"

    receipt = recovery.transition_v15r5_runtime(
        plan,
        confirmed_plan_sha256=str(plan["plan_sha256"]),
        transition_path=tmp_path / "transition.json",
        signal_claim_path=signal_claim_path,
        now=NOW,
    )

    assert calls == [(identity, signal.SIGTERM)]
    assert receipt["predecessor_signal_attempt_count"] == 1
    assert receipt["predecessor_restart_attempt_count"] == 0
    assert receipt["predecessor_process_absent"] is True
    assert receipt["admin_port_8787_free"] is True
    assert receipt["exact_child_open_zero_fill"] is True
    assert receipt["predecessor_signal_claim"]["attempt_number"] == 1
    assert "sentinel" not in receipt["pre_signal_stable_artifact_hashes"]
    assert set(receipt["post_signal_final_mutable_artifact_hashes"]) == {
        "parent_authority_loss",
        "runtime_log",
        "sentinel",
    }
    assert signal_claim_path.is_file()
    assert (tmp_path / "transition.json").is_file()


def test_v15r6_transition_identity_drift_fails_before_signal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(monkeypatch)
    signalled = False
    monkeypatch.setattr(
        recovery,
        "load_rejected_v15r5_execution_binding",
        lambda: deepcopy(authority.CONTROLLED_V15R6_REJECTED_EXECUTION_BINDING),
    )
    monkeypatch.setattr(
        recovery,
        "_read_process_identity",
        lambda _pid: {"process_id": 695321, "start_identity": "reused"},
    )

    def signal_forbidden(_identity, _signum) -> None:
        nonlocal signalled
        signalled = True

    monkeypatch.setattr(recovery, "signal_exact_process", signal_forbidden)
    monkeypatch.setattr(
        recovery, "validate_v15r6_clean_synced_environment", lambda _plan: None
    )

    with pytest.raises(recovery.ProofFailure, match="process_identity_changed"):
        recovery.transition_v15r5_runtime(
            plan,
            confirmed_plan_sha256=str(plan["plan_sha256"]),
            transition_path=tmp_path / "transition.json",
            signal_claim_path=tmp_path / "signal-claim.json",
            now=NOW,
        )
    assert signalled is False
    assert not (tmp_path / "transition.json").exists()


def test_v15r6_dirty_backend_fails_final_gate_before_signal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(monkeypatch)
    identity = dict(
        authority.CONTROLLED_V15R6_REJECTED_EXECUTION_BINDING[
            "runtime_process_identity"
        ]
    )
    signalled = False
    monkeypatch.setattr(
        recovery,
        "load_rejected_v15r5_execution_binding",
        lambda: deepcopy(authority.CONTROLLED_V15R6_REJECTED_EXECUTION_BINDING),
    )
    monkeypatch.setattr(recovery, "_read_process_identity", lambda _pid: identity)

    def fake_git(*args: str, cwd: Path = recovery.ROOT) -> str:
        if args[:2] == ("status", "--porcelain"):
            return " M application/admin_api/command_service.py" if cwd == recovery.ROOT else ""
        if args[0] == "rev-list":
            return "0\t0"
        if args == ("rev-parse", "HEAD"):
            return str(
                plan["backend_commit"]
                if cwd == recovery.ROOT
                else plan["frontend_commit"]
            )
        raise AssertionError((args, cwd))

    monkeypatch.setattr(recovery, "_git", fake_git)

    def signal_forbidden(_identity, _signum) -> None:
        nonlocal signalled
        signalled = True

    monkeypatch.setattr(recovery, "signal_exact_process", signal_forbidden)
    with pytest.raises(recovery.ProofFailure, match="backend_not_clean_and_synced"):
        recovery.transition_v15r5_runtime(
            plan,
            confirmed_plan_sha256=str(plan["plan_sha256"]),
            transition_path=tmp_path / "transition.json",
            signal_claim_path=tmp_path / "signal-claim.json",
            now=NOW,
        )
    assert signalled is False


def test_v15r6_occupied_successor_path_fails_before_signal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(monkeypatch)
    marker = tmp_path / "marker.json"
    marker.write_text("occupied", encoding="utf-8")
    signalled = False

    def signal_forbidden(_identity, _signum) -> None:
        nonlocal signalled
        signalled = True

    monkeypatch.setattr(recovery, "signal_exact_process", signal_forbidden)
    with pytest.raises(recovery.ProofFailure, match="successor_artifact_exists"):
        recovery.transition_v15r5_runtime(
            plan,
            confirmed_plan_sha256=str(plan["plan_sha256"]),
            transition_path=tmp_path / "transition.json",
            signal_claim_path=tmp_path / "signal-claim.json",
            marker_path=marker,
            placement_ledger_path=tmp_path / "placements.jsonl",
            cancel_ledger_path=tmp_path / "cancel.jsonl",
            backend_claim_log_path=tmp_path / "claims.jsonl",
            handoff_path=tmp_path / "handoff.json",
            now=NOW,
        )
    assert signalled is False


def test_v15r6_rechecks_expiry_immediately_before_signal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(monkeypatch)
    identity = dict(
        authority.CONTROLLED_V15R6_REJECTED_EXECUTION_BINDING[
            "runtime_process_identity"
        ]
    )
    signalled = False
    monkeypatch.setattr(
        recovery,
        "load_rejected_v15r5_execution_binding",
        lambda: deepcopy(authority.CONTROLLED_V15R6_REJECTED_EXECUTION_BINDING),
    )
    monkeypatch.setattr(recovery, "_read_process_identity", lambda _pid: identity)
    monkeypatch.setattr(
        recovery, "validate_v15r6_clean_synced_environment", lambda _plan: None
    )

    def signal_forbidden(_identity, _signum) -> None:
        nonlocal signalled
        signalled = True

    monkeypatch.setattr(recovery, "signal_exact_process", signal_forbidden)
    with pytest.raises(recovery.ProofFailure, match="expired_or_ttl_invalid"):
        recovery.transition_v15r5_runtime(
            plan,
            confirmed_plan_sha256=str(plan["plan_sha256"]),
            transition_path=tmp_path / "transition.json",
            signal_claim_path=tmp_path / "signal-claim.json",
            now=NOW,
            pre_signal_now=datetime.fromisoformat(str(plan["expires_at"])),
        )
    assert signalled is False


def test_v15r6_signal_claim_permanently_consumes_ambiguous_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(monkeypatch)
    identity = dict(
        authority.CONTROLLED_V15R6_REJECTED_EXECUTION_BINDING[
            "runtime_process_identity"
        ]
    )
    calls = 0
    monkeypatch.setattr(
        recovery,
        "load_rejected_v15r5_execution_binding",
        lambda: deepcopy(authority.CONTROLLED_V15R6_REJECTED_EXECUTION_BINDING),
    )
    monkeypatch.setattr(recovery, "_read_process_identity", lambda _pid: identity)
    monkeypatch.setattr(
        recovery, "validate_v15r6_clean_synced_environment", lambda _plan: None
    )

    def ambiguous_signal(_identity, _signum) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("signal outcome unknown")

    monkeypatch.setattr(recovery, "signal_exact_process", ambiguous_signal)
    transition_path = tmp_path / "transition.json"
    signal_claim_path = tmp_path / "signal-claim.json"
    kwargs = {
        "confirmed_plan_sha256": str(plan["plan_sha256"]),
        "transition_path": transition_path,
        "signal_claim_path": signal_claim_path,
        "now": NOW,
    }
    with pytest.raises(RuntimeError, match="signal outcome unknown"):
        recovery.transition_v15r5_runtime(plan, **kwargs)
    assert calls == 1
    assert signal_claim_path.is_file()
    assert not transition_path.exists()

    with pytest.raises(recovery.ProofFailure, match="successor_artifact_exists"):
        recovery.transition_v15r5_runtime(plan, **kwargs)
    assert calls == 1


def test_v15r6_shutdown_never_force_kills_on_sigterm_timeout() -> None:
    process = MagicMock()
    process.pid = 700001
    process.poll.return_value = None
    process.wait.side_effect = subprocess.TimeoutExpired("runtime", 45)
    runtime = SimpleNamespace(
        process=process,
        log_handle=MagicMock(),
        exchange_safe_to_shutdown=True,
        state_dir=Path("/tmp/v15r6-test-runtime"),
    )

    result = recovery.stop_v15r6_runtime_without_forced_kill(runtime)

    process.send_signal.assert_called_once_with(signal.SIGTERM)
    process.kill.assert_not_called()
    assert result["runtime_forced_kill_attempted"] is False
    assert result["runtime_preserved_for_reconciliation"] is True


def test_v15r6_approval_text_is_explicit_about_signal_and_single_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(monkeypatch)

    text = recovery.approval_text(plan)

    assert str(plan["plan_sha256"]) in text
    assert "exactly 1 root-client_order_id-bound child-cancel attempt" in text
    assert "authoritative exchange order_id" in text
    assert "exactly 1 predecessor runtime SIGTERM attempt" in text
    assert "0 predecessor restart attempts" in text
    assert "0 root placement attempts" in text
    assert "0 child placement attempts" in text


def _transition_receipt(plan: dict[str, object]) -> dict[str, object]:
    rejected = authority.CONTROLLED_V15R6_REJECTED_EXECUTION_BINDING
    signal_claim: dict[str, object] = {
        "schema_version": "1",
        "status": "v15r6_predecessor_signal_attempt_claimed",
        "controlled_plan_sha256": plan["plan_sha256"],
        "predecessor_plan_sha256": rejected["plan_sha256"],
        "predecessor_runtime_process_identity": deepcopy(
            rejected["runtime_process_identity"]
        ),
        "signal": "SIGTERM",
        "attempt_number": 1,
        "restart_attempt_count": 0,
        "forced_kill_attempt_count": 0,
        "claimed_at": "2026-07-13T09:00:30+00:00",
    }
    signal_claim["claim_sha256"] = recovery.signal_claim_hash(signal_claim)
    receipt: dict[str, object] = {
        "schema_version": "1",
        "status": "v15r5_to_v15r6_no_overlap_proven",
        "transition_mode": "one_exact_sigterm_zero_restarts",
        "controlled_plan_sha256": plan["plan_sha256"],
        "predecessor_plan_sha256": rejected["plan_sha256"],
        "predecessor_runtime_process_identity": deepcopy(
            rejected["runtime_process_identity"]
        ),
        "predecessor_signal": "SIGTERM",
        "predecessor_signal_claim": signal_claim,
        "predecessor_signal_attempt_count": 1,
        "predecessor_restart_attempt_count": 0,
        "predecessor_process_absent": True,
        "admin_port_8787_free": True,
        "competitor_pid": None,
        "pre_signal_stable_artifact_hashes": (
            recovery.stable_v15r5_artifact_hashes(rejected)
        ),
        "pre_signal_parent_authority_loss_semantic_projection": deepcopy(
            rejected["parent_authority_loss_semantic_projection"]
        ),
        "post_signal_final_mutable_artifact_hashes": {
            "parent_authority_loss": "d" * 64,
            "runtime_log": "e" * 64,
            "sentinel": "f" * 64,
        },
        "exact_child_open_zero_fill": True,
        "child_readback": deepcopy(rejected["child_readback"]),
        "recorded_at": "2026-07-13T09:01:00+00:00",
    }
    receipt["transition_sha256"] = recovery.transition_hash(receipt)
    return receipt


def test_v15r6_authorization_consumes_only_after_exact_no_overlap_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(monkeypatch)
    plan_path = tmp_path / "plan.json"
    marker_path = tmp_path / "marker.json"
    placement_path = tmp_path / "placements.jsonl"
    cancel_path = tmp_path / "cancel.jsonl"
    claim_path = tmp_path / "claims.jsonl"
    handoff_path = tmp_path / "handoff.json"
    signal_claim_path = tmp_path / "signal-claim.json"
    recovery.base._replace_owner_only_json(plan_path, plan)
    recovery.base._replace_owner_only_json(
        signal_claim_path,
        dict(_transition_receipt(plan)["predecessor_signal_claim"]),
    )

    result = recovery.authorize_v15r6_execution(
        plan_path,
        expected_hash=str(plan["plan_sha256"]),
        frozen_plan=plan,
        transition=_transition_receipt(plan),
        now=datetime(2026, 7, 13, 9, 2, tzinfo=timezone.utc),
        marker_path=marker_path,
        placement_ledger_path=placement_path,
        cancel_ledger_path=cancel_path,
        backend_claim_log_path=claim_path,
        handoff_path=handoff_path,
        signal_claim_path=signal_claim_path,
    )

    assert result["authority"] == authority.CONTROLLED_V15R6_AUTHORITY_KIND
    assert result["plan_sha256"] == plan["plan_sha256"]
    assert marker_path.is_file()
    assert placement_path.read_bytes() == b""
    assert cancel_path.read_bytes() == b""
    assert claim_path.read_bytes() == b""
    assert not handoff_path.exists()

    drifted = _transition_receipt(plan)
    drifted["predecessor_signal_attempt_count"] = 2
    drifted["transition_sha256"] = recovery.transition_hash(drifted)
    with pytest.raises(recovery.ProofFailure, match="transition_evidence_invalid"):
        recovery.validate_v15r6_transition_receipt(
            plan,
            expected_hash=str(plan["plan_sha256"]),
            transition=drifted,
        )


def test_v15r6_monitor_stops_on_durable_post_boundary_rejection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(monkeypatch)
    cancel = dict(plan["cancel_command"])
    idempotency = tmp_path / "idempotency.jsonl"
    idempotency.write_text(
        json.dumps(
            {
                "idempotency_key": cancel["idempotency_key"],
                "status": "rejected",
                "response": {
                    "status": "rejected",
                    "failure_stage": "cancellation_rejected",
                    "live_exchange_submitted": True,
                    "live_coinbase_orders_ran": True,
                },
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    idempotency.chmod(0o600)
    runtime = SimpleNamespace(state_dir=tmp_path)

    assert recovery.v15r6_post_boundary_runtime_decision(runtime, plan) == (
        "operator_cancel_rejected_active_child_reconciliation_only"
    )

    idempotency.unlink()
    assert recovery.v15r6_post_boundary_runtime_decision(runtime, plan) is None


def test_v15r6_execution_orders_transition_before_authority_and_runtime_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(monkeypatch)
    plan_path = tmp_path / "plan.json"
    recovery.base._replace_owner_only_json(plan_path, plan)
    events: list[str] = []

    monkeypatch.setattr(recovery, "PLAN_PATH", plan_path)
    monkeypatch.setattr(recovery, "RUNTIME_PATH", tmp_path / "transition.json")
    monkeypatch.setattr(
        recovery,
        "validate_v15r6_plan_structure",
        lambda *_args, **_kwargs: events.append("validate"),
    )
    monkeypatch.setattr(
        recovery,
        "transition_v15r5_runtime",
        lambda *_args, **_kwargs: events.append("transition") or {},
    )
    monkeypatch.setattr(
        recovery,
        "authorize_v15r6_execution",
        lambda *_args, **_kwargs: events.append("authorize") or {},
    )
    monkeypatch.setattr(
        recovery.base,
        "ControlledExecutionLease",
        lambda: nullcontext(),
    )

    class RuntimeMustNotStartEarly(RuntimeError):
        pass

    def runtime_factory(**_kwargs):
        events.append("runtime")
        raise RuntimeMustNotStartEarly

    monkeypatch.setattr(recovery.base, "AdminRuntime", runtime_factory)

    with pytest.raises(RuntimeMustNotStartEarly):
        recovery.execute_v15r6_plan(
            plan_path=plan_path,
            confirmed_plan_sha256=str(plan["plan_sha256"]),
        )

    assert events == ["validate", "transition", "authorize", "runtime"]


def test_v15r6_preparation_writes_only_the_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _v15r5_plan()
    monkeypatch.setattr(recovery, "backend_commit", lambda: "a" * 40)
    monkeypatch.setattr(recovery, "frontend_commit", lambda: "b" * 40)
    monkeypatch.setattr(recovery, "runner_sha256", lambda: "c" * 64)
    monkeypatch.setattr(
        recovery,
        "load_rejected_v15r5_execution_binding",
        lambda: deepcopy(authority.CONTROLLED_V15R6_REJECTED_EXECUTION_BINDING),
    )
    monkeypatch.setattr(recovery.v15r5, "_json", lambda *_args, **_kwargs: source)
    monkeypatch.setattr(
        recovery.v15r5,
        "read_local_active_child_binding",
        lambda: dict(source["local_active_child_binding"]),
    )
    plan_path = tmp_path / "plan.json"
    execution_paths = [
        tmp_path / "marker.json",
        tmp_path / "placements.jsonl",
        tmp_path / "cancel.jsonl",
        tmp_path / "claims.jsonl",
        tmp_path / "handoff.json",
        tmp_path / "runtime.json",
        tmp_path / "signal-claim.json",
    ]

    result = recovery.prepare_v15r6_plan(
        plan_path=plan_path,
        marker_path=execution_paths[0],
        placement_ledger_path=execution_paths[1],
        cancel_ledger_path=execution_paths[2],
        backend_claim_log_path=execution_paths[3],
        handoff_path=execution_paths[4],
        runtime_path=execution_paths[5],
        signal_claim_path=execution_paths[6],
        now=NOW,
        require_clean_environment=False,
    )

    assert result["status"] == "prepared"
    assert result["marker_written"] is False
    assert result["ledger_written"] is False
    assert result["runtime_started"] is False
    assert result["predecessor_signal_sent"] is False
    assert plan_path.is_file()
    assert all(not path.exists() for path in execution_paths)
