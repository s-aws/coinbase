"""No-live structural gates for the sealed V15R3 execution path."""

from __future__ import annotations

from contextlib import nullcontext
import inspect
import json
import os
import signal
from types import SimpleNamespace

import pytest

from tools import run_controlled_admin_spot_child_cancel_recovery_v15r4 as recovery


def test_v15r3_execution_transitions_before_authority_and_never_posts_cancel() -> None:
    source = inspect.getsource(recovery.execute_v15r3_plan)

    assert source.index("bind_completed_v15r2_shutdown") < source.index(
        "authorize_v15r3_execution"
    )
    assert source.index("authorize_v15r3_execution") < source.index(
        "base.AdminRuntime"
    )
    assert "transition_v15r2_runtime" not in source
    assert "signal_exact_process" not in source
    assert "post_v15r2_live_service_disabled" not in source
    assert "consume_v15r2_child_attempt" not in source
    assert ".place_limit_order(" not in source
    assert ".create_order(" not in source
    assert 'runtime.request("POST", cancel_path' not in source
    assert "runner_cancel_post_submitted" in source


def test_v15r3_execute_binds_completed_shutdown_without_replaying_transition(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan_path = tmp_path / "plan.json"
    plan = {"plan_sha256": "d" * 64}
    plan_path.write_text(json.dumps(plan) + "\n", encoding="utf-8")
    plan_path.chmod(0o600)
    events: list[str] = []

    class StopAfterTransition(Exception):
        pass

    monkeypatch.setattr(recovery, "PLAN_PATH", plan_path)
    monkeypatch.setattr(
        recovery.base,
        "ControlledExecutionLease",
        lambda: nullcontext(),
    )
    monkeypatch.setattr(recovery, "validate_v15r3_plan", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        recovery,
        "bind_completed_v15r2_shutdown",
        lambda *_args, **_kwargs: events.append("bind-completed")
        or {"status": "v15r2_to_v15r3_no_overlap_proven"},
    )
    monkeypatch.setattr(
        recovery,
        "transition_v15r2_runtime",
        lambda *_args, **_kwargs: pytest.fail(
            "completed shutdown must never replay predecessor transition"
        ),
    )

    def stop_after_transition(*_args, **_kwargs):
        events.append("authorize")
        raise StopAfterTransition

    monkeypatch.setattr(recovery, "authorize_v15r3_execution", stop_after_transition)

    with pytest.raises(StopAfterTransition):
        recovery.execute_v15r3_plan(
            plan_path=plan_path,
            confirmed_plan_sha256=plan["plan_sha256"],
        )

    assert events == ["bind-completed", "authorize"]


def test_v15r3_execution_helpers_exist_for_zero_budget_and_exact_monitoring() -> None:
    for name in (
        "transition_v15r2_runtime",
        "authorize_v15r3_execution",
        "build_v15r3_cancel_admission_context",
        "write_v15r3_cancel_proof_handoff",
        "set_v15r3_cancel_only_service",
        "v15r3_backend_claim_identity",
        "v15r3_operator_monitor_decision",
    ):
        assert callable(getattr(recovery, name))


def test_signal_exact_process_uses_pidfd_open_identity_signal_close_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = {
        "process_id": 1234,
        "start_identity": "111",
        "uid": 1000,
        "cwd": str(recovery.ROOT),
        "cwd_sha256": "a" * 64,
        "cmdline_sha256": "b" * 64,
    }
    events: list[object] = []

    monkeypatch.setattr(
        os,
        "pidfd_open",
        lambda process_id, flags=0: events.append(
            ("open", process_id, flags)
        )
        or 47,
    )
    monkeypatch.setattr(
        recovery,
        "_read_process_identity",
        lambda process_id: events.append(("identity", process_id)) or identity,
    )
    monkeypatch.setattr(
        signal,
        "pidfd_send_signal",
        lambda pidfd, signum, siginfo=None, flags=0: events.append(
            ("signal", pidfd, signum, siginfo, flags)
        ),
    )
    monkeypatch.setattr(
        os,
        "close",
        lambda pidfd: events.append(("close", pidfd)),
    )
    monkeypatch.setattr(
        os,
        "kill",
        lambda *_args: pytest.fail("os.kill must never be used for sealed signaling"),
    )

    recovery.signal_exact_process(identity, signal.SIGINT)

    assert events == [
        ("open", 1234, 0),
        ("identity", 1234),
        ("signal", 47, signal.SIGINT, None, 0),
        ("close", 47),
    ]


def test_signal_exact_process_identity_drift_closes_pidfd_without_signaling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = {
        "process_id": 1234,
        "start_identity": "111",
    }
    events: list[object] = []

    monkeypatch.setattr(
        os,
        "pidfd_open",
        lambda process_id, flags=0: events.append(
            ("open", process_id, flags)
        )
        or 47,
    )
    monkeypatch.setattr(
        recovery,
        "_read_process_identity",
        lambda process_id: events.append(("identity", process_id))
        or {**identity, "start_identity": "reused"},
    )
    monkeypatch.setattr(
        signal,
        "pidfd_send_signal",
        lambda *_args, **_kwargs: pytest.fail(
            "identity drift must block pidfd signaling"
        ),
    )
    monkeypatch.setattr(
        os,
        "close",
        lambda pidfd: events.append(("close", pidfd)),
    )
    monkeypatch.setattr(
        os,
        "kill",
        lambda *_args: pytest.fail("os.kill fallback is forbidden"),
    )

    with pytest.raises(
        recovery.ProofFailure,
        match="v15r3_signal_process_identity_changed",
    ):
        recovery.signal_exact_process(identity, signal.SIGTERM)

    assert events == [
        ("open", 1234, 0),
        ("identity", 1234),
        ("close", 47),
    ]


@pytest.mark.parametrize("missing_api", ["pidfd_open", "pidfd_send_signal"])
def test_signal_exact_process_fails_closed_when_pidfd_api_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    missing_api: str,
) -> None:
    identity = {"process_id": 1234, "start_identity": "111"}
    events: list[object] = []

    monkeypatch.setattr(
        os,
        "pidfd_open",
        None
        if missing_api == "pidfd_open"
        else lambda *_args: events.append("open") or 47,
    )
    monkeypatch.setattr(
        signal,
        "pidfd_send_signal",
        None
        if missing_api == "pidfd_send_signal"
        else lambda *_args, **_kwargs: events.append("signal"),
    )
    monkeypatch.setattr(
        recovery,
        "_read_process_identity",
        lambda _process_id: events.append("identity") or identity,
    )
    monkeypatch.setattr(os, "close", lambda _pidfd: events.append("close"))
    monkeypatch.setattr(
        os,
        "kill",
        lambda *_args: pytest.fail("os.kill fallback is forbidden"),
    )

    with pytest.raises(
        recovery.ProofFailure,
        match="v15r3_pidfd_api_unavailable",
    ):
        recovery.signal_exact_process(identity, signal.SIGTERM)

    assert events == []


def test_signal_exact_process_source_has_no_pid_based_kill_fallback() -> None:
    source = inspect.getsource(recovery.signal_exact_process)

    assert "pidfd_open" in source
    assert "pidfd_send_signal" in source
    assert "os.kill(" not in source


def test_same_kernel_process_identity_ignores_mutable_exec_and_cwd_fields() -> None:
    sealed = {
        "process_id": 1234,
        "start_identity": "111",
        "uid": 1000,
        "cwd": "/home/ec2-user/coinbase",
        "cwd_sha256": "a" * 64,
        "cmdline_sha256": "b" * 64,
    }
    changed_in_place = {
        **sealed,
        "cwd": "/tmp",
        "cwd_sha256": "c" * 64,
        "cmdline_sha256": "d" * 64,
    }
    reused_pid = {**changed_in_place, "start_identity": "222"}

    assert recovery.same_kernel_process_identity(sealed, changed_in_place) is True
    assert recovery.same_kernel_process_identity(sealed, reused_pid) is False
    loader_source = inspect.getsource(
        recovery.load_v15r3_completed_shutdown_binding
    )
    assert "not same_kernel_process_identity(" in loader_source
    assert "_read_process_identity(process_id) != identity" not in loader_source


def test_r2_service_disable_uses_canonical_admin_actor_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Session:
        trust_env = True

        @staticmethod
        def post(url, *, headers, json, timeout):
            captured.update(
                {"url": url, "headers": headers, "body": json, "timeout": timeout}
            )
            return SimpleNamespace(
                status_code=200,
                json=lambda: {
                    "decision": {
                        "decision_id": "disable-v15r2",
                        "resolver_eligible": False,
                        "service_enabled": False,
                        "requested_service_status": "live_disabled",
                    }
                },
            )

    monkeypatch.setattr(
        recovery,
        "_read_process_environment",
        lambda _pid: {"COINBASE_ADMIN_API_BEARER_TOKEN": "secret-token"},
    )
    monkeypatch.setattr(recovery.requests, "Session", Session)

    result = recovery.post_v15r2_live_service_disabled(
        plan={"backend_commit": "a" * 40}, runtime_pid=1234
    )

    headers = captured["headers"]
    assert headers["X-Admin-Actor"] == recovery.ACTOR_ID
    assert "X-Admin-Actor-Id" not in headers
    assert headers["X-Admin-Roles"] == "admin"
    assert result["service_enabled"] is False


def test_admin_port_proof_binds_loopback_without_missing_base_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[object] = []

    class Socket:
        def setsockopt(self, *args):
            events.append(("setsockopt", args))

        def bind(self, address):
            events.append(("bind", address))

        def close(self):
            events.append(("close",))

    monkeypatch.setattr(recovery.socket, "socket", lambda *_args: Socket())

    proof = recovery.prove_admin_port_free()

    assert ("bind", ("127.0.0.1", recovery.base.PORT)) in events
    assert events[-1] == ("close",)
    assert proof == {
        "port": recovery.base.PORT,
        "free": True,
        "competitor_pid": None,
    }


def test_post_transition_child_read_does_not_require_account_active_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validation: dict[str, object] = {}
    order = {
        "client_order_id": recovery.CHILD_CLIENT_ORDER_ID,
        "order_id": recovery.CHILD_EXCHANGE_ORDER_ID,
        "status": "OPEN",
        "filled_size": "0",
        "filled_value": "0",
        "total_fees": "0",
        "number_of_fills": "0",
    }
    monkeypatch.setattr(recovery.base, "hydrate_test_credentials", object)
    monkeypatch.setattr(
        recovery.base,
        "coinbase_preflight",
        lambda *_args, **_kwargs: pytest.fail(
            "the expected active child makes active-zero preflight invalid"
        ),
    )
    monkeypatch.setattr(
        recovery.base,
        "exact_exchange_order",
        lambda *_args, **_kwargs: order,
    )
    monkeypatch.setattr(
        recovery.base,
        "_validate_exact_coinbase_gtc_child_order",
        lambda value, **kwargs: validation.update(kwargs) or value,
    )

    result = recovery.read_exact_active_child_after_transition()

    assert result["client_order_id"] == recovery.CHILD_CLIENT_ORDER_ID
    assert result["exchange_order_id"] == recovery.CHILD_EXCHANGE_ORDER_ID
    assert result["status"] == "OPEN"
    assert result["filled_size"] == "0"
    assert validation["expected_exchange_order_id"] == (
        recovery.CHILD_EXCHANGE_ORDER_ID
    )
    assert validation["expected_portfolio_id"] == recovery.TEST_PORTFOLIO_ID
    assert validation["expected_child_tuple"] == {
        "root_client_order_id": recovery.ROOT_CLIENT_ORDER_ID,
        "client_order_id": recovery.CHILD_CLIENT_ORDER_ID,
        "product_id": recovery.PRODUCT_ID,
        "side": "SELL",
        "base_size": "0.00001583",
        "limit_price": "107702.14",
        "order_type": "LIMIT",
        "time_in_force": "GOOD_UNTIL_CANCELLED",
        "post_only": False,
    }


@pytest.mark.parametrize(
    ("mutation", "blocker"),
    [
        ({"filled_size": "0.00000001"}, "v15_zero_fill_not_zero"),
        ({"total_fees": None}, "v15_zero_fill_field_missing"),
        ({"status": "FILLED"}, "v15r3_transition_child_not_active_zero_fill"),
        ({"status": "CANCELLED"}, "v15r3_transition_child_not_active_zero_fill"),
    ],
)
def test_post_transition_child_read_rejects_fill_or_terminal_drift(
    mutation: dict[str, object],
    blocker: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order = {
        "client_order_id": recovery.CHILD_CLIENT_ORDER_ID,
        "order_id": recovery.CHILD_EXCHANGE_ORDER_ID,
        "status": "OPEN",
        "filled_size": "0",
        "filled_value": "0",
        "total_fees": "0",
        "number_of_fills": "0",
        **mutation,
    }
    monkeypatch.setattr(recovery.base, "hydrate_test_credentials", object)
    monkeypatch.setattr(
        recovery.base,
        "exact_exchange_order",
        lambda *_args, **_kwargs: order,
    )
    monkeypatch.setattr(
        recovery.base,
        "_validate_exact_coinbase_gtc_child_order",
        lambda value, **_kwargs: value,
    )

    with pytest.raises(recovery.ProofFailure, match=blocker):
        recovery.read_exact_active_child_after_transition()
