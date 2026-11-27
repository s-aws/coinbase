"""Regression: stealth reveal-placement persisted as a child must seed correctly.

Background (2026-04-29 incident)
--------------------------------
The stealth manager inserts an ``order_parent`` row PRE-REST for every reveal
placement whose uuid differs from the stealth's ``stealth_order_id``. That
row carries ``parent_order_id = <chain root>`` so the flat hierarchy is
preserved.

A WS confirmation for that placement then reaches ``OrderEngine.process_user_order``
which calls ``_ensure_order_parent_row_exists`` â†’ ``_seed_parent_order_cache_from_db``
to hydrate the in-memory cache.

Bug: the original implementation of ``_seed_parent_order_cache_from_db``
ignored the persisted ``parent_order_id`` and seeded EVERY hydrated row as
a ROOT in ``orderbook.parent_order_ids``. Consequences:

  1. A linked placement could be simultaneously treated as a strategy root
     and as a child after periodic reconciliation.

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
  C. Batch and lazy hydration produce the same mutually-exclusive maps from
     ``order_parent.parent_order_id`` without an N+1 stealth_orders query.
  D. Status updates use durable execution ownership, with the accepted
     placement index as a cross-check rather than an ownership fallback.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from core.orderbook import OrderBook
from core.enums import FollowUpKind, OrderStatus, StealthOrderStatus
from core.exceptions import OrderProcessingError
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

    db_module = Mock()
    db_module.insert_order_parent = Mock(return_value=1)
    db_module.get_parent_order = Mock(return_value=None)
    db_module.update_order_parent_status = Mock(return_value=True)
    db_module.update_order_parent_execution_statuses = Mock(
        return_value={
            "placement_updated": True,
            "execution_owner_required": False,
            "execution_owner_valid": False,
            "execution_owner_updated": False,
        }
    )
    db_module.increment_order_parent_replacement_count = Mock(return_value=1)

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


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Contract A: hydrating a row whose parent_order_id is set seeds as CHILD.
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    engine.db_module.get_parent_order = Mock(side_effect=fake_get_parent_order)

    seeded = engine._seed_parent_order_cache_from_db(placement)
    assert seeded is True

    # Placement is a CHILD, not a root.
    assert engine.is_child_order(placement), (
        "Pre-inserted placement row was seeded as a ROOT â€” this is the "
        "2026-04-29 status-stuck-at-PENDING bug."
    )
    assert not engine.is_parent_order(placement)
    assert engine.get_parent_of_child(placement) == root

    # Chain root was hydrated as a root.
    assert engine.is_parent_order(root)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Contract B: hydrating a child must not re-increment the root's counter.
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    engine.db_module.get_parent_order = Mock(side_effect=fake_get_parent_order)

    # Persisted root already has current_order_replacement=1 (the placement).
    engine._seed_parent_order_cache_from_db(placement)

    # In-memory root counter must mirror the persisted value, NOT 1+1=2.
    root_entry = engine.orderbook.parent_order_ids[root]
    assert root_entry["current_order_replacement"] == 1, (
        "Hydrating a persisted child re-incremented the root counter. "
        "On every WS event / reconcile pass this would silently double-count."
    )
    assert root_entry["max_order_replacement"] == 0
    # And we MUST NOT have written an INCREMENT to the DB (that's the
    # observable side-effect of the duplicated-rule footgun).
    engine.db_module.increment_order_parent_replacement_count.assert_not_called()


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Contract C: batch hydration classifies flat rows exactly once.
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@pytest.mark.regression
def test_batch_and_lazy_hydration_build_the_same_disjoint_flat_maps():
    engine = _build_engine()
    root = "root-coid"
    placement = "placement-coid"

    def fake_get_parent_order(coid):
        if coid == placement:
            return _child_row(placement, root)
        if coid == root:
            return _root_row(root)
        return None

    engine.db_module.get_parent_order = Mock(side_effect=fake_get_parent_order)
    engine.db_module.get_parent_orders = Mock(
        return_value=[_child_row(placement, root), _root_row(root)]
    )

    assert engine._seed_parent_order_cache_from_db(placement) is True
    lazy_parents = engine.orderbook.parent_order_ids
    lazy_children = engine.orderbook.child_order_ids

    batch_parents, batch_children = (
        engine.build_parent_child_order_ids_snapshot()
    )

    assert batch_parents == lazy_parents
    assert batch_children == lazy_children == {placement: root}
    assert set(batch_parents).isdisjoint(batch_children)
    assert batch_parents[root]["orders"] == [placement]
    assert batch_parents[root]["current_order_replacement"] == 1
    assert batch_parents[root]["max_order_replacement"] == 0


@pytest.mark.regression
@pytest.mark.parametrize(
    "rows",
    (
        [_child_row("orphan", "missing-root")],
        [
            _root_row("root"),
            _child_row("child", "root"),
            _child_row("grandchild", "child"),
        ],
        [_child_row("self-linked", "self-linked")],
    ),
    ids=("missing-root", "nested-link", "self-link"),
)
def test_invalid_batch_linkage_retains_last_known_good_maps(rows):
    engine = _build_engine()
    old_parents = {"known-root": {"orders": []}}
    old_children = {"known-child": "known-root"}
    engine.orderbook.parent_order_ids = old_parents
    engine.orderbook.child_order_ids = old_children
    engine.db_module.get_parent_orders = Mock(return_value=rows)

    assert engine.load_parent_child_order_ids() is False
    assert engine.orderbook.parent_order_ids is old_parents
    assert engine.orderbook.child_order_ids is old_children
    engine.orderbook.atomic_replace_links.assert_not_called()


@pytest.mark.regression
@pytest.mark.parametrize("invalid_root", (None, _child_row("linked", "root")))
def test_invalid_lazy_linkage_does_not_partially_mutate_maps(invalid_root):
    engine = _build_engine()
    child = "child"
    linked = "linked"

    def fake_get_parent_order(coid):
        if coid == child:
            return _child_row(child, linked)
        if coid == linked:
            return invalid_root
        return None

    engine.db_module.get_parent_order = Mock(side_effect=fake_get_parent_order)

    with pytest.raises(OrderProcessingError):
        engine._seed_parent_order_cache_from_db(child)

    assert engine.orderbook.parent_order_ids == {}
    assert engine.orderbook.child_order_ids == {}


# Contract D: exchange status follows durable execution ownership.
def _placement_order(client_order_id: str, status=OrderStatus.OPEN.value):
    return {
        "client_order_id": client_order_id,
        "order_id": "exchange-uuid",
        "product_id": "BIP-20DEC30-CDE",
        "order_side": "SELL",
        "side": "SELL",
        "status": status,
        "limit_price": "76330.00",
        "outstanding_hold_amount": "0",
        "filled_size": "0",
    }


def _attach_indexed_owner(engine, owner):
    manager = Mock()
    manager.find_stealth_order_by_placed_order_id.return_value = owner
    bridge = Mock()
    bridge.stealth_manager = manager
    bridge.is_anchor_rearm_placement_tombstoned.return_value = False
    engine.stealth_order_bridge = bridge
    return manager


def _guard_result(placement, owner):
    return {
        "placement_client_order_id": placement,
        "execution_owner_client_order_id": owner,
        "execution_owner_required": owner is not None,
        "execution_owner_conflict": False,
        "execution_owner_valid": owner is not None,
        "placement_updated": True,
        "execution_owner_updated": owner is not None,
    }


@pytest.mark.regression
def test_distinct_placement_status_updates_child_execution_owner_not_strategy_root():
    engine = _build_engine()
    root = "stealth-root-coid"
    logical_child = "logical-child-coid"
    placement = "placement-coid"

    def fake_get_parent_order(coid):
        if coid == placement:
            return _child_row(placement, root)
        if coid == root:
            return _root_row(root)
        return None

    engine.db_module.get_parent_order = Mock(side_effect=fake_get_parent_order)
    _attach_indexed_owner(
        engine,
        {
            "stealth_order_id": logical_child,
            "parent_order_id": root,
        },
    )
    engine.db_module.update_order_parent_execution_statuses.return_value = (
        _guard_result(placement, logical_child)
    )

    engine.process_user_order(_placement_order(placement))

    engine.db_module.update_order_parent_execution_statuses.assert_called_once_with(
        placement,
        OrderStatus.OPEN.value,
        expected_execution_owner_client_order_id=logical_child,
    )


@pytest.mark.regression
def test_distinct_root_owned_placement_status_updates_strategy_root():
    engine = _build_engine()
    root = "stealth-root-coid"
    placement = "placement-coid"

    def fake_get_parent_order(coid):
        if coid == placement:
            return _child_row(placement, root)
        if coid == root:
            return _root_row(root)
        return None

    engine.db_module.get_parent_order = Mock(side_effect=fake_get_parent_order)
    _attach_indexed_owner(
        engine,
        {"stealth_order_id": root, "parent_order_id": None},
    )
    engine.db_module.update_order_parent_execution_statuses.return_value = (
        _guard_result(placement, root)
    )

    engine.process_user_order(_placement_order(placement))

    engine.db_module.update_order_parent_execution_statuses.assert_called_once_with(
        placement,
        OrderStatus.OPEN.value,
        expected_execution_owner_client_order_id=root,
    )


@pytest.mark.regression
def test_child_sid_backed_placement_updates_once_without_root_projection():
    engine = _build_engine()
    root = "stealth-root-coid"
    logical_child = "logical-child-coid"

    def fake_get_parent_order(coid):
        if coid == logical_child:
            return _child_row(logical_child, root)
        if coid == root:
            return _root_row(root)
        return None

    engine.db_module.get_parent_order = Mock(side_effect=fake_get_parent_order)
    _attach_indexed_owner(
        engine,
        {
            "stealth_order_id": logical_child,
            "parent_order_id": root,
        },
    )
    engine.db_module.update_order_parent_execution_statuses.return_value = (
        _guard_result(logical_child, logical_child)
    )

    engine.process_user_order(_placement_order(logical_child))

    engine.db_module.update_order_parent_execution_statuses.assert_called_once_with(
        logical_child,
        OrderStatus.OPEN.value,
        expected_execution_owner_client_order_id=logical_child,
    )


@pytest.mark.regression
def test_durable_owner_projects_before_accepted_index_is_available():
    engine = _build_engine()
    root = "stealth-root-coid"
    placement = "placement-coid"

    def fake_get_parent_order(coid):
        if coid == placement:
            return _child_row(placement, root)
        if coid == root:
            return _root_row(root)
        return None

    engine.db_module.get_parent_order = Mock(side_effect=fake_get_parent_order)
    _attach_indexed_owner(engine, None)
    logical_child = "logical-child-coid"
    engine.db_module.update_order_parent_execution_statuses.return_value = (
        _guard_result(placement, logical_child)
    )

    engine.process_user_order(_placement_order(placement))

    engine.db_module.update_order_parent_execution_statuses.assert_called_once_with(
        placement,
        OrderStatus.OPEN.value,
        expected_execution_owner_client_order_id=None,
    )


@pytest.mark.regression
def test_owner_evidence_conflict_pauses_and_suppresses_origination(monkeypatch):
    engine = _build_engine()
    root = "stealth-root-coid"
    logical_child = "logical-child-coid"
    placement = "placement-coid"

    def fake_get_parent_order(coid):
        if coid == placement:
            return _child_row(placement, root)
        if coid == root:
            return _root_row(root)
        return None

    engine.db_module.get_parent_order = Mock(side_effect=fake_get_parent_order)
    _attach_indexed_owner(
        engine,
        {
            "stealth_order_id": logical_child,
            "parent_order_id": root,
        },
    )
    engine.db_module.update_order_parent_execution_statuses.return_value = {
        "placement_client_order_id": placement,
        "execution_owner_client_order_id": root,
        "expected_execution_owner_client_order_id": logical_child,
        "execution_owner_required": True,
        "execution_owner_conflict": True,
        "execution_owner_valid": False,
        "placement_updated": True,
        "execution_owner_updated": False,
    }
    engine._process_ws_order_delta_without_strategy_origination = Mock(
        return_value=None
    )
    controller = Mock()
    monkeypatch.setattr(
        "core.order_engine.get_runtime_controller",
        lambda: controller,
    )

    engine.process_user_order(_placement_order(placement))

    controller.request_pause.assert_called_once_with()
    factual_ingest = (
        engine._process_ws_order_delta_without_strategy_origination
    )
    factual_ingest.assert_called_once()
    delta_call = factual_ingest.call_args
    assert delta_call.args[0]["client_order_id"] == placement


@pytest.mark.regression
def test_consumed_rearm_cancel_bypasses_generic_status_and_follow_up():
    """The manager owns placement and logical rows while its SID lock is held."""
    engine = _build_engine()
    root = "stealth-root-coid"
    placement = "placement-coid"

    def fake_get_parent_order(coid):
        if coid == placement:
            return _child_row(placement, root)
        if coid == root:
            return _root_row(root)
        return None

    engine.db_module.get_parent_order = Mock(side_effect=fake_get_parent_order)
    engine.stealth_order_bridge = Mock()
    engine.stealth_order_bridge.consume_anchor_rearm_cancellation.return_value = (
        StealthOrderStatus.HIDDEN
    )
    engine.handle_cancelled_order = Mock()
    engine.complete_follow_up_processing = Mock()
    engine._update_dashboard_order_status = Mock()

    engine.process_user_order(
        {
            "client_order_id": placement,
            "order_id": "exchange-uuid",
            "product_id": "BIP-20DEC30-CDE",
            "order_side": "SELL",
            "side": "SELL",
            "status": OrderStatus.CANCELLED.value,
            "limit_price": "76330.00",
            "outstanding_hold_amount": "0",
            "cumulative_quantity": "0",
            "number_of_fills": "0",
        }
    )

    engine.stealth_order_bridge.consume_anchor_rearm_cancellation.assert_called_once_with(
        placement,
        exchange_order_id="exchange-uuid",
        cumulative_filled_size=0.0,
        number_of_fills=0,
    )
    # The bridge consumer completed placement/logical persistence before returning.
    engine.db_module.update_order_parent_execution_statuses.assert_not_called()
    engine.handle_cancelled_order.assert_not_called()
    engine._update_dashboard_order_status.assert_called_once()
    dashboard_args = engine._update_dashboard_order_status.call_args.args
    assert dashboard_args[0] == placement
    assert dashboard_args[2] == OrderStatus.CANCELLED
    engine.complete_follow_up_processing.assert_called_once_with(
        FollowUpKind.CANCELLED,
        placement,
    )


@pytest.mark.regression
def test_operator_cancel_tombstone_skips_raw_projection_but_retries_follow_up():
    engine = _build_engine()
    root = "stealth-root-coid"
    placement = "placement-coid"
    engine.orderbook.parent_order_ids[root] = {
        "orders": [placement],
        "current_order_replacement": 1,
        "max_order_replacement": 0,
    }
    engine.orderbook.child_order_ids[placement] = root
    engine.stealth_order_bridge = Mock()
    engine.stealth_order_bridge.consume_anchor_rearm_cancellation.return_value = (
        None
    )
    engine.stealth_order_bridge.is_anchor_rearm_placement_tombstoned.return_value = (
        True
    )
    engine.handle_cancelled_order = Mock()
    engine._update_dashboard_order_status = Mock()
    cancelled_order = {
        "client_order_id": placement,
        "order_id": "exchange-uuid",
        "product_id": "BIP-20DEC30-CDE",
        "order_side": "SELL",
        "side": "SELL",
        "status": OrderStatus.CANCELLED.value,
        "limit_price": "76330.00",
        "outstanding_hold_amount": "0",
        "cumulative_quantity": "0",
        "number_of_fills": "0",
    }

    # First post-consumption dispatch and a later duplicate both retain the
    # newer logical-order OPEN projection, while generic follow-up processing
    # remains available to finish or retry idempotently.
    engine.process_user_order(dict(cancelled_order))
    engine.process_user_order(dict(cancelled_order))

    engine.db_module.update_order_parent_execution_statuses.assert_not_called()
    assert engine.handle_cancelled_order.call_count == 2
    assert (
        engine.stealth_order_bridge
        .is_anchor_rearm_placement_tombstoned.call_count
        == 2
    )


@pytest.mark.regression
def test_root_backed_rearm_cancel_does_not_project_raw_cancel_to_dashboard():
    """The logical SID may already be HIDDEN or re-revealed on return."""
    engine = _build_engine()
    root = "stealth-root-coid"
    engine.db_module.get_parent_order = Mock(return_value=_root_row(root))
    engine.stealth_order_bridge = Mock()
    engine.stealth_order_bridge.consume_anchor_rearm_cancellation.return_value = (
        StealthOrderStatus.HIDDEN
    )
    engine.handle_cancelled_order = Mock()
    engine.complete_follow_up_processing = Mock()
    engine._update_dashboard_order_status = Mock()

    engine.process_user_order(
        {
            "client_order_id": root,
            "order_id": "exchange-uuid",
            "product_id": "BIP-20DEC30-CDE",
            "side": "SELL",
            "status": OrderStatus.CANCELLED.value,
            "limit_price": "76330.00",
            "outstanding_hold_amount": "0",
            "cumulative_quantity": "0",
            "number_of_fills": "0",
        }
    )

    engine.db_module.update_order_parent_execution_statuses.assert_not_called()
    engine.handle_cancelled_order.assert_not_called()
    engine._update_dashboard_order_status.assert_not_called()


@pytest.mark.regression
def test_rearm_cancel_uses_pre_ingest_monotonic_fill_watermark():
    engine = _build_engine()
    root = "stealth-root-coid"
    placement = "placement-coid"

    def fake_get_parent_order(coid):
        if coid == placement:
            return _child_row(placement, root)
        if coid == root:
            return _root_row(root)
        return None

    engine.db_module.get_parent_order = Mock(side_effect=fake_get_parent_order)
    engine.order_progress_tracker.ingest(
        {
            "client_order_id": placement,
            "product_id": "BIP-20DEC30-CDE",
            "side": "SELL",
            "status": OrderStatus.OPEN.value,
            "cumulative_quantity": "2",
            "number_of_fills": "1",
        }
    )
    engine.stealth_order_bridge = Mock()
    engine.stealth_order_bridge.consume_anchor_rearm_cancellation.return_value = (
        StealthOrderStatus.CANCELLED
    )
    engine.handle_cancelled_order = Mock()

    engine.process_user_order(
        {
            "client_order_id": placement,
            "order_id": "exchange-uuid",
            "product_id": "BIP-20DEC30-CDE",
            "side": "SELL",
            "status": OrderStatus.CANCELLED.value,
            "limit_price": "76330.00",
            "outstanding_hold_amount": "0",
            "cumulative_quantity": "0",
            "number_of_fills": "0",
        }
    )

    engine.stealth_order_bridge.consume_anchor_rearm_cancellation.assert_called_once_with(
        placement,
        exchange_order_id="exchange-uuid",
        cumulative_filled_size=2.0,
        number_of_fills=1,
    )
