"""No-live structural gates for the sealed V15R3 execution path."""

from __future__ import annotations

import inspect
import os
import signal
from types import SimpleNamespace

import pytest

from tools import run_controlled_admin_spot_child_cancel_recovery_v15r3 as recovery


def test_v15r3_execution_transitions_before_authority_and_never_posts_cancel() -> None:
    source = inspect.getsource(recovery.execute_v15r3_plan)

    assert source.index("transition_v15r2_runtime") < source.index(
        "authorize_v15r3_execution"
    )
    assert source.index("authorize_v15r3_execution") < source.index(
        "base.AdminRuntime"
    )
    assert "consume_v15r2_child_attempt" not in source
    assert ".place_limit_order(" not in source
    assert ".create_order(" not in source
    assert 'runtime.request("POST", cancel_path' not in source
    assert "runner_cancel_post_submitted" in source


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
