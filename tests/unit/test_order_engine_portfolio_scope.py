from __future__ import annotations

from core.order_engine import OrderEngine


TEST_PORTFOLIO_ID = "11111111-2222-4333-8444-555555555555"
DEFAULT_PORTFOLIO_ID = "f4dfdb77-aa88-53d0-9c37-da3a0762ce54"


def _engine() -> tuple[OrderEngine, list[str], list[tuple[str, str]]]:
    callbacks: list[str] = []
    logs: list[tuple[str, str]] = []
    engine = OrderEngine.__new__(OrderEngine)
    engine.expected_retail_portfolio_id = TEST_PORTFOLIO_ID
    engine._event_monitoring_lost_callback = lambda: callbacks.append("drain")
    engine._portfolio_scope_violation_reported = False
    engine.log_message = lambda level, message: logs.append((level, message))
    return engine, callbacks, logs


def test_user_order_portfolio_scope_accepts_only_exact_test_uuid() -> None:
    engine, callbacks, logs = _engine()

    assert engine._validate_user_order_portfolio_scope(
        {"retail_portfolio_id": TEST_PORTFOLIO_ID}
    ) is True
    assert callbacks == []
    assert logs == []


def test_user_order_portfolio_scope_rejects_missing_or_default_and_drains_once() -> None:
    engine, callbacks, logs = _engine()

    assert engine._validate_user_order_portfolio_scope({}) is False
    assert engine._validate_user_order_portfolio_scope(
        {"retail_portfolio_id": DEFAULT_PORTFOLIO_ID}
    ) is False

    assert callbacks == ["drain"]
    assert len(logs) == 2
    assert all(level == "error" for level, _message in logs)
    assert TEST_PORTFOLIO_ID in logs[0][1]
    assert DEFAULT_PORTFOLIO_ID in logs[1][1]


def test_user_order_portfolio_scope_is_inactive_for_legacy_default_runtime() -> None:
    engine, callbacks, logs = _engine()
    engine.expected_retail_portfolio_id = None

    assert engine._validate_user_order_portfolio_scope({}) is True
    assert callbacks == []
    assert logs == []
