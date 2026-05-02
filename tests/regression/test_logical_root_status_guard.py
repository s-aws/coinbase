"""Regression: logical root status propagation must not rely on stale last-write-wins.

The placement row for a reveal child should still receive raw exchange status
updates. The logical root row, however, should use a guarded updater when the
runtime exposes one so stale `PENDING` events cannot rewind a root that already
advanced to `OPEN`.
"""

from unittest.mock import Mock

import pytest

import database.order as order_db
from configuration import OrderBook
from core.order_engine import OrderEngine


def _build_engine():
    orderbook = Mock(spec=OrderBook)
    orderbook.parent_order_ids = {"root-coid": {"orders": []}}
    orderbook.child_order_ids = {"child-coid": "root-coid"}
    orderbook.order = {}
    orderbook.positions = {"FUTURE": {}}
    orderbook.should_replace = {"FILLED": False, "CANCELLED": False}
    orderbook.default_max_order_replacement = 11
    orderbook.profit = {
        "FUTURE": {"BUY": 0.0012, "SELL": 0.0012},
        "SPOT": {"BUY": 0.004, "SELL": 0.004},
    }
    orderbook.profit_target = orderbook.profit
    orderbook.get_position_side = Mock(return_value=None)

    db_helper = Mock()
    db_helper.update_order_parent_status = Mock(return_value=1)

    subscription = Mock()
    subscription.channels = ["user"]

    engine = OrderEngine(
        orderbook=orderbook,
        db_helper=db_helper,
        subscription=subscription,
        api_key="test_key",
        api_secret="test_secret",
        order_post_only={"BUY": False, "SELL": False},
    )
    return engine, db_helper


@pytest.mark.regression
def test_child_status_propagation_uses_guarded_root_updater_when_available():
    engine, db_helper = _build_engine()
    db_helper.update_order_parent_status_if_progressing = Mock(return_value=0)

    engine._update_logical_root_parent_status("root-coid", "PENDING")

    db_helper.update_order_parent_status_if_progressing.assert_called_once_with(
        client_order_id="root-coid",
        status="PENDING",
    )
    db_helper.update_order_parent_status.assert_not_called()


@pytest.mark.regression
def test_child_status_propagation_falls_back_when_guarded_helper_is_unavailable():
    engine, db_helper = _build_engine()

    engine._update_logical_root_parent_status("root-coid", "OPEN")

    db_helper.update_order_parent_status.assert_called_once_with(
        client_order_id="root-coid",
        status="OPEN",
    )


@pytest.mark.regression
def test_db_helper_advances_open_from_pending(monkeypatch):
    calls = []

    def fake_execute_query(query, params):
        calls.append((query, params))
        if "RETURNING client_order_id" in query:
            return [{"client_order_id": "root-coid"}]
        raise AssertionError(f"Unexpected query: {query}")

    monkeypatch.setattr(order_db.DB_CLIENT, "execute_query", fake_execute_query)

    updated = order_db.update_order_parent_status_if_progressing(
        client_order_id="root-coid",
        status="OPEN",
    )

    assert updated == 1
    assert len(calls) == 1
    assert calls[0][1] == ("OPEN", "root-coid", "PENDING", "OPEN")


@pytest.mark.regression
def test_db_helper_skips_regressive_pending_after_open(monkeypatch):
    calls = []

    def fake_execute_query(query, params):
        calls.append((query, params))
        if "RETURNING client_order_id" in query:
            return []
        if "SELECT status FROM order_parent" in query:
            return [{"status": "OPEN"}]
        raise AssertionError(f"Unexpected query: {query}")

    monkeypatch.setattr(order_db.DB_CLIENT, "execute_query", fake_execute_query)

    updated = order_db.update_order_parent_status_if_progressing(
        client_order_id="root-coid",
        status="PENDING",
    )

    assert updated == 0
    assert len(calls) == 2
    assert calls[0][1] == ("PENDING", "root-coid", "PENDING")
    assert calls[1][1] == ("root-coid",)


@pytest.mark.regression
def test_db_helper_logs_regressive_skip_explicitly(monkeypatch, caplog):
    def fake_execute_query(query, params):
        if "RETURNING client_order_id" in query:
            return []
        if "SELECT status FROM order_parent" in query:
            return [{"status": "OPEN"}]
        raise AssertionError(f"Unexpected query: {query}")

    monkeypatch.setattr(order_db.DB_CLIENT, "execute_query", fake_execute_query)

    with caplog.at_level("INFO", logger="OrderDB"):
        updated = order_db.update_order_parent_status_if_progressing(
            client_order_id="root-coid",
            status="PENDING",
        )

    assert updated == 0
    assert any(
        "Logical parent order status skipped as regressive: root-coid stays OPEN (attempted PENDING)"
        in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.regression
def test_db_helper_logs_missing_root_row_explicitly(monkeypatch, caplog):
    def fake_execute_query(query, params):
        if "RETURNING client_order_id" in query:
            return []
        if "SELECT status FROM order_parent" in query:
            return []
        raise AssertionError(f"Unexpected query: {query}")

    monkeypatch.setattr(order_db.DB_CLIENT, "execute_query", fake_execute_query)

    with caplog.at_level("WARNING", logger="OrderDB"):
        updated = order_db.update_order_parent_status_if_progressing(
            client_order_id="missing-root",
            status="OPEN",
        )

    assert updated == 0
    assert any(
        "No parent order found to advance status: missing-root" in record.getMessage()
        for record in caplog.records
    )