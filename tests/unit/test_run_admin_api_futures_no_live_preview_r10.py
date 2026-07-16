"""Focused synthetic safety tests for the dormant Slice 2R10 Preview tool."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from application.admin_api import futures_order_preview as preview_module
from application.admin_api.futures_order_preview import (
    FuturesOrderPreviewArtifactError,
    FuturesOrderPreviewArtifactStore,
)
from tests.unit.test_admin_api_futures_order_preview import (
    NOW,
    _r8_compatible_rest_client,
)
from tools import run_admin_api_futures_no_live_preview_r10 as r10_tool


_READ_COUNTERS = {
    "api_key_permissions": 1,
    "portfolio_catalog": 1,
    "product": 1,
    "best_bid_ask": 1,
    "futures_positions": 1,
    "futures_margin_collateral": 1,
}
_ATTEMPT_COUNTERS = {
    "preview_order": 1,
    "retry": 0,
    "fallback": 0,
    "create_order": 0,
    "cancel_order": 0,
    "close_position": 0,
    "reduce_position": 0,
}


def test_r10_preflight_is_fully_offline_and_uses_v2_bindings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "fixed-r10-preview.jsonl"
    monkeypatch.setattr(r10_tool, "production_artifact_path", lambda: path)
    monkeypatch.setattr(
        r10_tool,
        "validate_production_predecessor",
        lambda: dict(preview_module.FUTURES_PREVIEW_R9_TERMINAL_BINDING),
    )
    monkeypatch.setattr(
        r10_tool,
        "_build_r10_canonical_preview_session",
        lambda: (_ for _ in ()).throw(
            AssertionError("credential hydration or Coinbase client construction")
        ),
    )
    monkeypatch.setattr(
        r10_tool,
        "build_rest_client",
        lambda: (_ for _ in ()).throw(
            AssertionError("Preview facade constructed")
        ),
    )

    assert r10_tool.R9_PREVIEW_CALL_AUTHORITY_ACTIVE is False
    assert r10_tool.R10_PREVIEW_CALL_AUTHORITY_ACTIVE is False
    assert r10_tool.R10_FINAL_AUDIT_BINDING_READY is False
    assert r10_tool.main(["--preflight"]) == 0

    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "prepared"
    assert summary["blocker"] is None
    assert summary["predecessor_binding"] == (
        preview_module.FUTURES_PREVIEW_R9_TERMINAL_BINDING
    )
    assert summary["preview_response_schema_binding"] == (
        preview_module.FUTURES_PREVIEW_R10_RESPONSE_SCHEMA_BINDING
    )
    assert summary["post_preview_diagnostic_binding"] == (
        preview_module.FUTURES_PREVIEW_R10_POST_PREVIEW_DIAGNOSTIC_BINDING
    )
    assert summary["claim_contract_ready"] is True
    assert summary["live_authority_active"] is False
    assert summary["final_audit_binding_ready"] is False
    assert summary["coinbase_read_ran"] is False
    assert summary["preview_order_attempt_count"] == 0
    assert summary["exchange_submission_attempt_count"] == 0
    assert summary["artifact_created"] is False
    assert not path.exists()


def test_r10_confirmation_is_blocked_before_path_predecessor_or_client(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def forbidden(label: str):
        return lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError(label)
        )

    monkeypatch.setattr(
        r10_tool,
        "production_artifact_path",
        forbidden("R10 path inspected"),
    )
    monkeypatch.setattr(
        r10_tool,
        "validate_production_predecessor",
        forbidden("R9 predecessor inspected"),
    )
    monkeypatch.setattr(
        r10_tool,
        "_build_r10_canonical_preview_session",
        forbidden("credential hydration or Coinbase client construction"),
    )

    assert r10_tool.main(["--confirm-one-r10-preview"]) == 2

    summary = json.loads(capsys.readouterr().err)
    assert summary == {
        "artifact_created": False,
        "artifact_path": str(preview_module.FUTURES_PREVIEW_R10_ARTIFACT_PATH),
        "blocker": "futures_preview_r10_call_authority_inactive",
        "coinbase_read_ran": False,
        "exchange_submission_attempt_count": 0,
        "live_coinbase_execution": "not_run",
        "preview_order_attempt_count": 0,
        "status": "blocked",
    }


def test_r10_cli_help_is_a_permanent_consumed_tombstone() -> None:
    help_text = " ".join(r10_tool.build_parser().format_help().split())

    assert "permanently disabled" in help_text
    assert "R10 is consumed and has no live authority" in help_text
    assert "permanently rejects consumed R10" in help_text
    assert "after a separate final audited gate activation" not in help_text


def test_r10_deferred_client_requires_exclusive_r10_claim_before_hydration(
    tmp_path: Path,
) -> None:
    hydration_attempts = 0

    def forbidden_factory():
        nonlocal hydration_attempts
        hydration_attempts += 1
        raise AssertionError("session hydrated without an R10 claim")

    deferred = r10_tool.DeferredR10PreviewRestClient(
        store=FuturesOrderPreviewArtifactStore(tmp_path / "absent-r10.jsonl"),
        session_factory=forbidden_factory,
    )

    with pytest.raises(
        FuturesOrderPreviewArtifactError,
        match="R10 claim is unavailable",
    ):
        deferred.get_api_key_permissions()

    assert hydration_attempts == 0


def test_r10_synthetic_accepted_session_is_exactly_bounded_and_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_legacy_current = "PRIVATE-R10-LEGACY-CURRENT"
    private_legacy_projected = "PRIVATE-R10-LEGACY-PROJECTED"
    delegate = _r8_compatible_rest_client()
    margin_snapshot_reader = delegate.get_futures_margin_collateral_snapshot
    delegate.read_calls.clear()

    def recorded_margin_snapshot():
        delegate.read_calls.append("futures_margin_collateral")
        return margin_snapshot_reader()

    delegate.get_futures_margin_collateral_snapshot = recorded_margin_snapshot
    delegate.preview_response.update(
        {
            "current_liquidation_buffer": private_legacy_current,
            "projected_liquidation_buffer": private_legacy_projected,
        }
    )
    path = tmp_path / "accepted-r10.jsonl"
    store = r10_tool.build_r10_store(path)
    session = r10_tool._R10CanonicalPreviewSession(delegate)
    deferred = r10_tool.DeferredR10PreviewRestClient(
        store=store,
        prepared_session=session,
    )
    monkeypatch.setattr(
        r10_tool,
        "validate_production_predecessor",
        lambda: dict(preview_module.FUTURES_PREVIEW_R9_TERMINAL_BINDING),
    )
    producer = r10_tool.build_r10_producer(
        rest_client=deferred,
        store=store,
        now=lambda: NOW,
        correlation_id_factory=lambda: (
            "299cb4b8-b99d-4663-baa8-da9db777e62d"
        ),
        idempotency_key_factory=lambda: (
            "eb47c508-d834-44bc-9732-138cf60770d8"
        ),
    )
    claim = producer.build_claim()
    preview_module._validate_r10_ephemeral_claim_record(claim)
    handoffs: list[r10_tool.R10AcceptedSessionHandoff] = []

    def accepted_callback(
        ephemeral: dict[str, object],
        persisted: dict[str, object],
    ) -> None:
        assert ephemeral["portfolio_id"] == "default-portfolio-uuid"
        assert persisted["portfolio_id"] == "withheld"
        handoffs.append(deferred.take_accepted_session(ephemeral, persisted))

    terminal = producer.run(accepted_callback=accepted_callback)

    assert terminal == store.read_completed()
    assert terminal["artifact_type"] == (
        preview_module.FUTURES_PREVIEW_R10_ARTIFACT_TYPE
    )
    assert terminal["predecessor_binding"] == (
        preview_module.FUTURES_PREVIEW_R9_TERMINAL_BINDING
    )
    assert terminal["preview_response_schema_binding"] == (
        preview_module.FUTURES_PREVIEW_R10_RESPONSE_SCHEMA_BINDING
    )
    assert terminal["post_preview_diagnostic_binding"] == (
        preview_module.FUTURES_PREVIEW_R10_POST_PREVIEW_DIAGNOSTIC_BINDING
    )
    assert terminal["status"] == terminal["outcome"] == "accepted"
    assert terminal["read_counters"] == _READ_COUNTERS
    assert terminal["attempt_counters"] == _ATTEMPT_COUNTERS
    assert terminal["exchange_submission_attempt_count"] == 0
    assert terminal["submitted_notional_usdc"] == "0"
    assert terminal["executed_notional_usdc"] == "0"
    assert terminal["live_execution"] == "not_run"
    assert terminal["live_coinbase_execution"] == "not_run"
    assert delegate.read_calls == [
        "api_key_permissions",
        "portfolio_catalog",
        "product",
        "best_bid_ask",
        "futures_positions",
        "futures_margin_collateral",
        "preview_order",
    ]
    assert len(delegate.preview_calls) == 1
    assert delegate.forbidden_calls == []
    assert path.stat().st_mode & 0o777 == 0o400
    persisted_text = path.read_text(encoding="utf-8")
    assert private_legacy_current not in persisted_text
    assert private_legacy_projected not in persisted_text
    assert len(handoffs) == 1
    assert handoffs[0].delegate is delegate
    handoffs[0].account_binding.validate()

    with pytest.raises(
        FuturesOrderPreviewArtifactError,
        match="R10 call was already attempted",
    ):
        deferred.preview_order(
            product_id="AVP-20DEC30-CDE",
            side="BUY",
            order_configuration={
                "limit_limit_gtc": {
                    "base_size": "1",
                    "limit_price": "6.45",
                    "post_only": True,
                }
            },
        )
    with pytest.raises(
        FuturesOrderPreviewArtifactError,
        match="accepted session was already released",
    ):
        deferred.take_accepted_session(terminal, terminal)
    with pytest.raises(AttributeError):
        getattr(deferred, "create_order")
    assert len(delegate.preview_calls) == 1
    assert delegate.forbidden_calls == []


def test_r10_fixed_builders_cannot_redirect_predecessor_or_artifact_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "r10-claim.jsonl"
    store = r10_tool.build_r10_store(path)
    monkeypatch.setattr(
        r10_tool,
        "validate_production_predecessor",
        lambda: dict(preview_module.FUTURES_PREVIEW_R9_TERMINAL_BINDING),
    )
    producer = r10_tool.build_r10_producer(rest_client=object(), store=store)

    claim = producer.build_claim()

    assert store.path == path
    assert claim["artifact_type"] == (
        preview_module.FUTURES_PREVIEW_R10_ARTIFACT_TYPE
    )
    assert claim["predecessor_binding"] == (
        preview_module.FUTURES_PREVIEW_R9_TERMINAL_BINDING
    )
    preview_module._validate_r10_ephemeral_claim_record(claim)
    assert r10_tool.production_artifact_path() == (
        preview_module.FUTURES_PREVIEW_R10_ARTIFACT_PATH
    )
