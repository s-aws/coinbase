"""Integration: ``OrderEngine._maybe_dispatch_hotpoint`` end-to-end with mocks.

Covers the wiring path that pure-unit tests on the building blocks
(detector / rate limiter / placer / sweeper) cannot reach:

  * The detector + rate limiter + policy are constructed at engine init.
  * A WS-derived ``OrderSnapshotDelta`` flowing through the dispatcher
    correctly funnels into the placer ONLY when the parent has
    ``enable_hotpoint_replication=TRUE``.
  * The runtime kill switch suppresses placement.
  * The opt-in gate prevents non-hotpoint-flagged parents from ever
    feeding the detector.
  * Auto-placed rows do NOT cascade (their parents have the flag FALSE).
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock, patch

import pytest

from business.order_progress import OrderSnapshotDelta
from configuration import OrderBook
from core.order_engine import OrderEngine


pytestmark = pytest.mark.regression


def _build_engine():
    orderbook = Mock(spec=OrderBook)
    orderbook.parent_order_ids = {}
    orderbook.child_order_ids = {}
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
    orderbook.product = {
        "BTC-USDC": {
            "base_min_size": "0.001",
            "base_increment": "0.001",
            "price_increment": "0.5",
        },
    }

    db_module = Mock()
    db_module.insert_order_parent = Mock(return_value=1)
    db_module.get_parent_order = Mock(return_value=None)

    subscription = Mock()
    subscription.channels = ["user"]

    engine = OrderEngine(
        orderbook=orderbook,
        db_module=db_module,
        subscription=subscription,
        api_key="test_key",
        api_secret="test_secret",
        order_post_only={"BUY": False, "SELL": False},
    )
    engine.stealth_order_bridge = None
    engine.fill_repo = None
    engine.event_stream_publisher = None
    engine.fill_event_hooks = None
    engine.websocket_hooks = Mock()
    return engine


def _delta(coid="child-coid", side="BUY", price=100.0):
    return OrderSnapshotDelta(
        client_order_id=coid,
        product_id="BTC-USDC",
        side=side,
        cumulative_quantity=0.001,
        filled_value=0.1,
        total_fees=0.0,
        number_of_fills=1,
        leaves_quantity=0.0,
        completion_percentage=100.0,
        outstanding_hold_amount=0.0,
        status="FILLED",
        size_delta=0.001,
        value_delta=0.1,
        fee_delta=0.0,
        derived_price=price,
        derived_trade_key=f"trade-{coid}-1",
        snapshot_seq=1,
        observed_at=datetime.utcnow(),
    )


# ----------------------------------------------------------------------------
# Subsystem constructed at init
# ----------------------------------------------------------------------------

def test_subsystem_initialised_at_engine_construction():
    engine = _build_engine()
    assert engine._hotpoint_detector is not None
    assert engine._hotpoint_rate_limiter is not None
    assert engine._hotpoint_policy is not None
    # Default: enabled.
    assert engine.is_hotpoint_auto_place_enabled() is True


# ----------------------------------------------------------------------------
# Opt-in gate â€” only flagged parents feed the detector
# ----------------------------------------------------------------------------

def test_non_optin_parent_never_feeds_detector():
    engine = _build_engine()
    # Cache miss -> DB lookup returns None -> treated as not opted in.
    engine.get_parent_of_child = Mock(return_value="parent-root")
    spy_record = Mock(wraps=engine._hotpoint_detector.record_fill)
    engine._hotpoint_detector.record_fill = spy_record

    engine._maybe_dispatch_hotpoint(_delta())

    spy_record.assert_not_called()


def test_optin_parent_via_orderbook_cache_feeds_detector():
    engine = _build_engine()
    engine.orderbook.parent_order_ids["parent-root"] = {
        "enable_hotpoint_replication": True,
    }
    engine.get_parent_of_child = Mock(return_value="parent-root")

    spy_record = Mock(wraps=engine._hotpoint_detector.record_fill)
    engine._hotpoint_detector.record_fill = spy_record

    engine._maybe_dispatch_hotpoint(_delta())

    spy_record.assert_called_once()


# ----------------------------------------------------------------------------
# Trigger -> placement happy path
# ----------------------------------------------------------------------------

def test_three_fills_from_optin_parent_trigger_placement():
    engine = _build_engine()
    engine.orderbook.parent_order_ids["parent-root"] = {
        "enable_hotpoint_replication": True,
    }
    engine.get_parent_of_child = Mock(return_value="parent-root")

    fake_rest = Mock()
    fake_insert = Mock(return_value=1)

    with patch("configuration.REST_CLIENT", fake_rest), \
         patch("database.order.insert_order_parent", fake_insert):
        for _ in range(3):
            engine._maybe_dispatch_hotpoint(_delta(price=100.0))

    fake_rest.limit_order_gtc.assert_called_once()
    fake_insert.assert_called_once()
    submitted_kwargs = fake_insert.call_args.kwargs
    assert submitted_kwargs["auto_placed_by_hotpoint"] is True
    assert submitted_kwargs["enable_hotpoint_replication"] is False
    assert submitted_kwargs["parent_order_id"] is None


# ----------------------------------------------------------------------------
# Kill switch
# ----------------------------------------------------------------------------

def test_kill_switch_off_blocks_placement_but_records_fills():
    engine = _build_engine()
    engine.orderbook.parent_order_ids["parent-root"] = {
        "enable_hotpoint_replication": True,
    }
    engine.get_parent_of_child = Mock(return_value="parent-root")
    engine.set_hotpoint_auto_place_enabled(False)

    fake_rest = Mock()
    fake_insert = Mock(return_value=1)

    with patch("configuration.REST_CLIENT", fake_rest), \
         patch("database.order.insert_order_parent", fake_insert):
        for _ in range(3):
            engine._maybe_dispatch_hotpoint(_delta(price=100.0))

    fake_rest.limit_order_gtc.assert_not_called()
    fake_insert.assert_not_called()
    # Detector has 3 fills recorded â€” flipping the switch back on later
    # should immediately allow the next trigger to fire.
    from business.hotpoint_detector import compute_bucket_id
    bid = compute_bucket_id(100.0, engine._hotpoint_width_pct)
    assert engine._hotpoint_detector.fills_in_window(
        product_id="BTC-USDC", side="BUY", bucket_id=bid, now=999.0,
    ) == 3


def test_kill_switch_can_be_toggled_at_runtime():
    engine = _build_engine()
    assert engine.is_hotpoint_auto_place_enabled() is True
    engine.set_hotpoint_auto_place_enabled(False)
    assert engine.is_hotpoint_auto_place_enabled() is False
    engine.set_hotpoint_auto_place_enabled(True)
    assert engine.is_hotpoint_auto_place_enabled() is True


# ----------------------------------------------------------------------------
# No cascade â€” auto-placed rows must not be opted in
# ----------------------------------------------------------------------------

def test_auto_placed_rows_inserted_without_cascade_flag():
    """Verifies the no-cascade contract from the design.

    A successful placement persists with:
      auto_placed_by_hotpoint=TRUE   (sweeper / rate-limit rebuild target)
      enable_hotpoint_replication=FALSE  (no cascade)

    If a fill ever arrives for the auto-placed row, the dispatcher's
    opt-in gate immediately rejects it.
    """
    engine = _build_engine()
    engine.orderbook.parent_order_ids["parent-root"] = {
        "enable_hotpoint_replication": True,
    }
    # The auto-placed row gets cached with the FALSE flag.
    engine.orderbook.parent_order_ids["auto-placed-coid"] = {
        "enable_hotpoint_replication": False,
    }
    engine.get_parent_of_child = lambda coid: (
        "parent-root" if coid == "child-coid" else "auto-placed-coid"
    )

    spy_record = Mock(wraps=engine._hotpoint_detector.record_fill)
    engine._hotpoint_detector.record_fill = spy_record

    # A fill on the auto-placed COID must NOT enter the detector.
    auto_delta = _delta(coid="auto-placed-coid", price=100.0)
    engine._maybe_dispatch_hotpoint(auto_delta)
    spy_record.assert_not_called()


# ----------------------------------------------------------------------------
# Robustness â€” failures inside dispatch never propagate
# ----------------------------------------------------------------------------

def test_dispatch_swallows_unexpected_exceptions():
    engine = _build_engine()
    engine.get_parent_of_child = Mock(side_effect=RuntimeError("boom"))
    # Must not raise.
    engine._maybe_dispatch_hotpoint(_delta())


def test_non_positive_price_short_circuits():
    engine = _build_engine()
    engine.orderbook.parent_order_ids["parent-root"] = {
        "enable_hotpoint_replication": True,
    }
    engine.get_parent_of_child = Mock(return_value="parent-root")
    spy_record = Mock(wraps=engine._hotpoint_detector.record_fill)
    engine._hotpoint_detector.record_fill = spy_record

    engine._maybe_dispatch_hotpoint(_delta(price=0.0))
    engine._maybe_dispatch_hotpoint(_delta(price=-1.0))
    spy_record.assert_not_called()


def test_delta_without_new_match_short_circuits():
    """Engine guards on is_new_match BEFORE calling dispatcher in the real
    pipeline, but the dispatcher itself must also defend so direct callers
    can't bypass the gate.
    """
    engine = _build_engine()
    engine.orderbook.parent_order_ids["parent-root"] = {
        "enable_hotpoint_replication": True,
    }
    engine.get_parent_of_child = Mock(return_value="parent-root")
    spy_record = Mock(wraps=engine._hotpoint_detector.record_fill)
    engine._hotpoint_detector.record_fill = spy_record

    no_advance = _delta()
    no_advance = no_advance.__class__(**{**no_advance.__dict__, "size_delta": 0.0})
    engine._maybe_dispatch_hotpoint(no_advance)
    spy_record.assert_not_called()


# ----------------------------------------------------------------------------
# UI snapshot helper
# ----------------------------------------------------------------------------

def test_state_snapshot_shape_with_no_activity():
    engine = _build_engine()
    with patch(
        "database.order.get_recent_auto_placed_hotpoint_rows",
        return_value=[],
    ):
        snap = engine.get_hotpoint_state_snapshot()
    assert snap["enabled"] is True
    assert snap["subsystem_initialized"] is True
    assert snap["active_buckets"] == []
    assert snap["recent_auto_placements"] == []
    cfg = snap["config"]
    for key in (
        "width_pct", "trigger_n", "trigger_window_seconds",
        "rate_limit_n", "rate_limit_window_seconds",
        "decay_sweep_interval_seconds", "default_policy",
    ):
        assert key in cfg


def test_state_snapshot_includes_active_bucket_after_fill():
    engine = _build_engine()
    engine.orderbook.parent_order_ids["parent-root"] = {
        "enable_hotpoint_replication": True,
    }
    engine.get_parent_of_child = Mock(return_value="parent-root")
    engine._maybe_dispatch_hotpoint(_delta(price=100.0))

    with patch(
        "database.order.get_recent_auto_placed_hotpoint_rows",
        return_value=[],
    ):
        snap = engine.get_hotpoint_state_snapshot()
    assert len(snap["active_buckets"]) == 1
    bucket = snap["active_buckets"][0]
    assert bucket["product_id"] == "BTC-USDC"
    assert bucket["side"] == "BUY"
    assert bucket["fills_in_window"] == 1


def test_state_snapshot_surfaces_recent_placements():
    engine = _build_engine()
    fake_rows = [
        {"client_order_id": "abc", "product_id": "BTC-USDC", "side": "BUY",
         "price": 100.0, "epoch_seconds": 1000.0},
        {"client_order_id": "def", "product_id": "ETH-USDC", "side": "SELL",
         "price": 3000.0, "epoch_seconds": 1100.0},
    ]
    with patch(
        "database.order.get_recent_auto_placed_hotpoint_rows",
        return_value=fake_rows,
    ):
        snap = engine.get_hotpoint_state_snapshot()
    assert len(snap["recent_auto_placements"]) == 2
    assert snap["recent_auto_placements"][0]["client_order_id"] == "abc"
    assert snap["recent_auto_placements"][1]["price"] == 3000.0
