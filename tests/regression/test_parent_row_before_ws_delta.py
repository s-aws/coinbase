"""Regression: order_parent row must exist BEFORE _process_ws_order_delta.

Bug seen 2026-04-28 (production logs):

    OrderDB - ERROR - [PARTIAL-FILL] upsert_partial_fill_progress failed for
        8f81799f-...: ForeignKeyViolation: insert or update on table
        "partial_fill_progress" violates foreign key constraint
        "partial_fill_progress_client_order_id_fkey"
    DETAIL: Key (client_order_id)=(8f81799f-...) is not present in table
        "order_parent".

For an externally-placed order arriving on the WS user channel, the parent
row was created LATE — only after the FILLED/CANCELLED routing inside
``handle_filled_order`` / ``handle_cancelled_order``. The watermark write
in ``_process_ws_order_delta`` ran first, hit the FK, and the order's
fills (already in ``fill_ledger``) were left without a watermark row.

Contract pinned by this module:

  1. ``process_user_order`` must call ``_ensure_order_parent_row_exists``
     BEFORE ``_process_ws_order_delta``.
  2. ``_ensure_order_parent_row_exists`` is idempotent — already-tracked
     orders see no extra DB inserts.
  3. ``_is_external_order`` continues to return True for orders that
     arrived from outside our engine, even after the hoisted insert tags
     them in the cache. Without this, the downstream
     ``_handle_external_order_tracking`` path would silently stop firing
     for external orders.
"""
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from configuration import OrderBook
from core.enums import OrderStatus
from core.order_engine import OrderEngine


def _build_engine():
    """Minimal engine with mocked DB / orderbook (mirrors test_order_id_regression)."""
    orderbook = Mock(spec=OrderBook)
    orderbook.parent_order_ids = {}
    orderbook.child_order_ids = {}
    orderbook.order = {}
    orderbook.positions = {"FUTURE": {}}
    orderbook.should_replace = {"FILLED": False, "CANCELLED": False}
    orderbook.default_max_order_replacement = 11
    # `resolve_profit_target` reads from `orderbook.profit` (per-product
    # override) then falls back to per-product-type. Set both so the hoist's
    # call to resolve_parent_client_order_id can compute a target_movement.
    orderbook.profit = {
        "FUTURE": {"BUY": 0.0012, "SELL": 0.0012},
        "SPOT": {"BUY": 0.004, "SELL": 0.004},
    }
    orderbook.profit_target = orderbook.profit
    orderbook.get_position_side = Mock(return_value=None)

    db_helper = Mock()
    db_helper.insert_order_parent = Mock(return_value=1)
    # Crucially: get_parent_order returns None so the order is treated as
    # genuinely unknown (the bug condition).
    db_helper.get_parent_order = Mock(return_value=None)
    db_helper.update_order_parent_status = Mock(return_value=True)

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
    # Disable everything that isn't being tested here.
    engine.stealth_order_bridge = None
    engine.fill_repo = None
    engine.event_stream_publisher = None
    engine.fill_event_hooks = None
    engine.websocket_hooks = Mock()
    engine.claim_follow_up_processing = Mock(return_value=True)
    return engine


@pytest.mark.regression
def test_parent_row_is_created_before_ws_order_delta_processing():
    """Pin call order: ensure runs before delta processing.

    Without the hoist, ``_process_ws_order_delta`` would run first against a
    COID with no ``order_parent`` row and produce the FK violation observed
    in production.
    """
    engine = _build_engine()

    call_order: list[str] = []

    real_ensure = engine._ensure_order_parent_row_exists
    real_delta = engine._process_ws_order_delta

    def spy_ensure(order):
        call_order.append("ensure_parent")
        return real_ensure(order)

    def spy_delta(order):
        call_order.append("process_delta")
        # By the time we reach delta processing, the parent row MUST be
        # present in the in-memory cache (the FK precondition).
        coid = order.get("client_order_id")
        assert coid in engine.orderbook.parent_order_ids, (
            f"FK precondition violated: {coid} reached "
            f"_process_ws_order_delta without an order_parent row in cache. "
            f"This is the 2026-04-28 bug."
        )
        return real_delta(order)

    engine._ensure_order_parent_row_exists = spy_ensure
    engine._process_ws_order_delta = spy_delta

    external_order = {
        "client_order_id": "8f81799f-48da-477d-9f1f-322f89211a90",
        "order_id": "99cb68a7-a121-4247-b3c8-443d8f67c1c3",
        "product_id": "BIP-20DEC30-CDE",
        "order_side": "SELL",
        "side": "SELL",
        "status": OrderStatus.FILLED.value,
        "limit_price": "77900.00",
        "outstanding_hold_amount": "0",
        "filled_size": "1.0",
    }

    engine.process_user_order(external_order)

    assert call_order, "neither hook fired"
    assert call_order.index("ensure_parent") < call_order.index("process_delta"), (
        f"ensure_parent must run before process_delta; got {call_order}"
    )
    engine.db_helper.insert_order_parent.assert_called_once()


@pytest.mark.regression
def test_ensure_is_idempotent_for_already_tracked_orders():
    """Re-calling the ensure helper for a known parent must not re-insert.

    Pins idempotency so the new pre-step adds no DB cost in the steady-state
    case (orders we placed ourselves).
    """
    engine = _build_engine()
    coid = "internal-coid-123"

    # Simulate the order already being in our orderbook (we placed it).
    engine.orderbook.parent_order_ids[coid] = {
        "orders": [],
        "target_movement": {"movement": 0.0, "type": "P"},
        "max_order_replacement": 11,
        "current_order_replacement": 0,
    }

    engine._ensure_order_parent_row_exists({
        "client_order_id": coid,
        "product_id": "BTC-USDC",
        "order_side": "BUY",
        "status": OrderStatus.OPEN.value,
        "limit_price": "42000.00",
        "filled_size": "0",
    })

    engine.db_helper.insert_order_parent.assert_not_called()
    engine.db_helper.get_parent_order.assert_not_called()


@pytest.mark.regression
def test_ensure_hydrates_from_db_without_inserting_when_row_exists():
    """If the row is in DB but not yet cached, hydrate and don't re-insert."""
    engine = _build_engine()
    coid = "stealth-already-persisted"

    # Stealth order manager already inserted the row at creation time.
    engine.db_helper.get_parent_order = Mock(return_value={
        "id": 42,
        "client_order_id": coid,
        "target_movement": "0.002",
        "target_movement_type": "P",
        "max_order_replacement": 11,
        "current_order_replacement": 0,
        "allow_partial_fills": False,
    })

    engine._ensure_order_parent_row_exists({
        "client_order_id": coid,
        "product_id": "BTC-USDC",
        "order_side": "BUY",
        "status": OrderStatus.OPEN.value,
        "limit_price": "42000.00",
        "filled_size": "0",
    })

    engine.db_helper.get_parent_order.assert_called_once_with(coid)
    engine.db_helper.insert_order_parent.assert_not_called()
    assert coid in engine.orderbook.parent_order_ids


@pytest.mark.regression
def test_externally_created_orders_still_route_to_external_tracking():
    """The hoisted insert must NOT mask externally-placed orders.

    Before the fix, ``_is_external_order`` returned True iff the COID was
    absent from the in-memory cache. After the fix the COID *is* in the
    cache (we just put it there), but it must remain classified as external
    so ``handle_filled_order`` / ``handle_cancelled_order`` route to
    ``_handle_external_order_tracking`` and emit ``external_order_filled``
    / ``external_order_cancelled`` events.
    """
    engine = _build_engine()
    coid = "fa295dc5-3c97-4f70-8cb8-516ace6a153d"

    # Simulate the hoist running for a brand-new external order.
    engine._ensure_order_parent_row_exists({
        "client_order_id": coid,
        "product_id": "BIT-29MAY26-CDE",
        "order_side": "SELL",
        "status": OrderStatus.CANCELLED.value,
        "limit_price": "78065.00",
        "filled_size": "0",
    })

    cached = engine.orderbook.parent_order_ids.get(coid)
    assert cached is not None, "ensure should have created the cache entry"
    assert cached.get("externally_created") is True, (
        "external orders inserted by the hoist must be tagged so "
        "_is_external_order keeps returning True"
    )
    assert engine._is_external_order(coid) is True

    # Internally-placed orders (no flag) are NOT external.
    internal_coid = "internal-coid-456"
    engine.orderbook.parent_order_ids[internal_coid] = {
        "orders": [],
        "target_movement": {"movement": 0.0, "type": "P"},
        "max_order_replacement": 11,
        "current_order_replacement": 0,
    }
    assert engine._is_external_order(internal_coid) is False
