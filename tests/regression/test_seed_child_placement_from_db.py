"""Regression: stealth reveal-placement persisted as a child must seed correctly.

Background (2026-04-29 incident)
--------------------------------
The stealth manager inserts an ``order_parent`` row PRE-REST for every reveal
placement whose uuid differs from the stealth's ``stealth_order_id``. That
row carries ``parent_order_id = <chain root>`` so the flat hierarchy is
preserved.

A WS confirmation for that placement then reaches ``OrderEngine.process_user_order``
which calls ``_ensure_order_parent_row_exists`` → ``_seed_parent_order_cache_from_db``
to hydrate the in-memory cache.

Bug: the original implementation of ``_seed_parent_order_cache_from_db``
ignored the persisted ``parent_order_id`` and seeded EVERY hydrated row as
a ROOT in ``orderbook.parent_order_ids``. Consequences:

  1. ``is_parent_order(placement_coid)`` returned True, so status updates
     ran ``UPDATE order_parent SET status=... WHERE client_order_id=<placement>``
     — the chain ROOT row never received status updates and stayed PENDING
     forever even after the placement filled (observed: stealth row 61
     stuck at PENDING while placement row 62 went FILLED).

  2. Any subsequent ``register_child_order(stealth_followup, placement)``
     would create an in-memory grandchild because ``placement`` was treated
     as a root.

Contract pinned by this module:

  A. When the persisted ``order_parent`` row has ``parent_order_id`` set,
     the seeder registers the COID as a CHILD under the chain root, NOT
     as a new root.
  B. Hydrating a child does NOT increment the root's
     ``current_order_replacement`` (the persisted value already reflects
     reality; re-incrementing on every WS event / reconcile pass would
     double-count).
  C. Status updates for a child placement update both the placement row
     AND propagate to the chain root row.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from configuration import OrderBook
from core.enums import OrderStatus
from core.order_engine import OrderEngine


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

    db_helper = Mock()
    db_helper.insert_order_parent = Mock(return_value=1)
    db_helper.get_parent_order = Mock(return_value=None)
    db_helper.update_order_parent_status = Mock(return_value=True)
    db_helper.increment_order_parent_replacement_count = Mock(return_value=1)

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
    engine.stealth_order_bridge = None
    engine.fill_repo = None
    engine.event_stream_publisher = None
    engine.fill_event_hooks = None
    engine.websocket_hooks = Mock()
    engine.claim_follow_up_processing = Mock(return_value=True)
    return engine


def _root_row(coid: str) -> dict:
    return {
        "id": 100,
        "client_order_id": coid,
        "parent_order_id": None,
        "target_movement": "0.0014",
        "target_movement_type": "P",
        "max_order_replacement": 0,
        "current_order_replacement": 1,
        "allow_partial_fills": False,
    }


def _child_row(coid: str, root_coid: str) -> dict:
    return {
        "id": 101,
        "client_order_id": coid,
        "parent_order_id": root_coid,
        "target_movement": "0.0014",
        "target_movement_type": "P",
        "max_order_replacement": 0,
        "current_order_replacement": 0,
        "allow_partial_fills": False,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Contract A: hydrating a row whose parent_order_id is set seeds as CHILD.
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.regression
def test_seed_from_db_registers_child_when_parent_link_present():
    engine = _build_engine()
    root = "2f274206-ec40-49db-8302-e53a951bdccb"
    placement = "f6281a12-8b4d-43e1-9059-553bd832ed96"

    def fake_get_parent_order(coid):
        if coid == placement:
            return _child_row(placement, root)
        if coid == root:
            return _root_row(root)
        return None

    engine.db_helper.get_parent_order = Mock(side_effect=fake_get_parent_order)

    seeded = engine._seed_parent_order_cache_from_db(placement)
    assert seeded is True

    # Placement is a CHILD, not a root.
    assert engine.is_child_order(placement), (
        "Pre-inserted placement row was seeded as a ROOT — this is the "
        "2026-04-29 status-stuck-at-PENDING bug."
    )
    assert not engine.is_parent_order(placement)
    assert engine.get_parent_of_child(placement) == root

    # Chain root was hydrated as a root.
    assert engine.is_parent_order(root)


# ─────────────────────────────────────────────────────────────────────────────
# Contract B: hydrating a child must not re-increment the root's counter.
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.regression
def test_seed_from_db_does_not_reincrement_root_replacement_counter():
    engine = _build_engine()
    root = "root-coid"
    placement = "placement-coid"

    def fake_get_parent_order(coid):
        if coid == placement:
            return _child_row(placement, root)
        if coid == root:
            return _root_row(root)
        return None

    engine.db_helper.get_parent_order = Mock(side_effect=fake_get_parent_order)

    # Persisted root already has current_order_replacement=1 (the placement).
    engine._seed_parent_order_cache_from_db(placement)

    # In-memory root counter must mirror the persisted value, NOT 1+1=2.
    root_entry = engine.orderbook.parent_order_ids[root]
    assert root_entry["current_order_replacement"] == 1, (
        "Hydrating a persisted child re-incremented the root counter. "
        "On every WS event / reconcile pass this would silently double-count."
    )
    # And we MUST NOT have written an INCREMENT to the DB (that's the
    # observable side-effect of the duplicated-rule footgun).
    engine.db_helper.increment_order_parent_replacement_count.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Contract C: status updates on a child propagate to the chain root.
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.regression
def test_status_update_propagates_from_child_placement_to_chain_root():
    """When the placement is a child of a stealth root, ``process_user_order``
    must update both the placement's order_parent row AND the chain root's
    row, so the dashboard's view of the logical order reflects reality.
    """
    engine = _build_engine()
    root = "stealth-root-coid"
    placement = "placement-coid"

    def fake_get_parent_order(coid):
        if coid == placement:
            return _child_row(placement, root)
        if coid == root:
            return _root_row(root)
        return None

    engine.db_helper.get_parent_order = Mock(side_effect=fake_get_parent_order)

    placement_order = {
        "client_order_id": placement,
        "order_id": "exchange-uuid",
        "product_id": "BIP-20DEC30-CDE",
        "order_side": "SELL",
        "side": "SELL",
        "status": OrderStatus.OPEN.value,
        "limit_price": "76330.00",
        "outstanding_hold_amount": "0",
        "filled_size": "0",
    }

    engine.process_user_order(placement_order)

    # Both rows must have received the OPEN status update.
    update_calls = engine.db_helper.update_order_parent_status.call_args_list
    targets = {
        call.kwargs.get("client_order_id") or call.args[0]
        for call in update_calls
    }
    assert placement in targets, "placement row was not updated"
    assert root in targets, (
        f"chain root {root} did not receive the status update — this is the "
        "observable symptom of the 2026-04-29 stealth-status-stuck-at-PENDING "
        f"bug. update_order_parent_status calls: {update_calls}"
    )
