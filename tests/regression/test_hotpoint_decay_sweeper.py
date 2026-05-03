"""Tests for ``business.hotpoint_decay_sweeper``."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from business.hotpoint_decay_sweeper import HotpointDecaySweeper
from business.hotpoint_detector import HotpointDetector, compute_bucket_id


pytestmark = pytest.mark.regression


def _make_sweeper(rows, *, detector=None, rest=None):
    det = detector or HotpointDetector(
        width_pct=0.005, trigger_n=2, trigger_window_seconds=60
    )
    rest = rest or MagicMock()
    sweeper = HotpointDecaySweeper(
        detector=det,
        width_pct=0.005,
        interval_seconds=30,
        list_open_fn=lambda: rows,
        rest_client=rest,
    )
    return sweeper, det, rest


def test_cold_bucket_cancels():
    """A resting auto-placed row whose bucket has zero in-window fills cancels."""
    rows = [{"client_order_id": "abc", "product_id": "X", "side": "BUY", "price": 100.0}]
    sweeper, _, rest = _make_sweeper(rows)
    decisions = sweeper.run_once(now=0.0)
    assert len(decisions) == 1 and decisions[0].cancel is True
    rest.cancel_orders.assert_called_once_with(order_ids=["abc"])


def test_hot_bucket_does_not_cancel():
    rows = [{"client_order_id": "abc", "product_id": "X", "side": "BUY", "price": 100.0}]
    sweeper, det, rest = _make_sweeper(rows)
    # Inject a fill into the bucket.
    det.record_fill(product_id="X", side="BUY", fill_price=100.0, now=0.0)
    decisions = sweeper.run_once(now=1.0)
    assert decisions[0].cancel is False
    rest.cancel_orders.assert_not_called()


def test_mixed_bucket_states():
    rows = [
        {"client_order_id": "cold", "product_id": "X", "side": "BUY", "price": 100.0},
        {"client_order_id": "hot", "product_id": "X", "side": "BUY", "price": 1000.0},
    ]
    sweeper, det, rest = _make_sweeper(rows)
    det.record_fill(product_id="X", side="BUY", fill_price=1000.0, now=0.0)
    sweeper.run_once(now=1.0)
    rest.cancel_orders.assert_called_once_with(order_ids=["cold"])


def test_cancel_failure_is_logged_not_raised():
    rows = [{"client_order_id": "abc", "product_id": "X", "side": "BUY", "price": 100.0}]
    rest = MagicMock()
    rest.cancel_orders.side_effect = RuntimeError("api down")
    log = MagicMock()
    sweeper = HotpointDecaySweeper(
        detector=HotpointDetector(
            width_pct=0.005, trigger_n=2, trigger_window_seconds=60
        ),
        width_pct=0.005,
        interval_seconds=30,
        list_open_fn=lambda: rows,
        rest_client=rest,
        log_callback=log,
    )
    decisions = sweeper.run_once(now=0.0)
    assert decisions[0].cancel is True
    # Sweeper survived; logged the failure.
    assert any(
        call.args[0] == "warning" and call.args[1].get("event") == "hotpoint_decay_cancel_failed"
        for call in log.call_args_list
    )


def test_list_failure_returns_empty_decisions():
    def boom():
        raise RuntimeError("db down")

    rest = MagicMock()
    sweeper = HotpointDecaySweeper(
        detector=HotpointDetector(
            width_pct=0.005, trigger_n=2, trigger_window_seconds=60
        ),
        width_pct=0.005,
        interval_seconds=30,
        list_open_fn=boom,
        rest_client=rest,
    )
    decisions = sweeper.run_once(now=0.0)
    assert decisions == []
    rest.cancel_orders.assert_not_called()


def test_bad_row_skipped():
    rows = [
        {"client_order_id": "ok", "product_id": "X", "side": "BUY", "price": 100.0},
        {"missing_keys": True},
    ]
    sweeper, _, rest = _make_sweeper(rows)
    decisions = sweeper.run_once(now=0.0)
    # Only the valid row produced a decision.
    assert len(decisions) == 1 and decisions[0].client_order_id == "ok"
    rest.cancel_orders.assert_called_once_with(order_ids=["ok"])


def test_zero_price_row_skipped():
    rows = [
        {"client_order_id": "zero", "product_id": "X", "side": "BUY", "price": 0.0},
        {"client_order_id": "ok", "product_id": "X", "side": "BUY", "price": 100.0},
    ]
    sweeper, _, rest = _make_sweeper(rows)
    decisions = sweeper.run_once(now=0.0)
    assert [d.client_order_id for d in decisions] == ["ok"]


def test_constructor_validation():
    det = HotpointDetector(width_pct=0.005, trigger_n=2, trigger_window_seconds=60)
    with pytest.raises(ValueError):
        HotpointDecaySweeper(
            detector=det, width_pct=0.005, interval_seconds=0,
            list_open_fn=lambda: [], rest_client=MagicMock(),
        )
    with pytest.raises(ValueError):
        HotpointDecaySweeper(
            detector=det, width_pct=0, interval_seconds=10,
            list_open_fn=lambda: [], rest_client=MagicMock(),
        )
