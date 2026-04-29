"""Unit tests for the OrderEngine WS-derived progress pipeline.

Exercises the post-Step-4 architecture where ``OrderProgressTracker`` is the
single source of truth for cumulative-counter watermarks and the engine
routes the resulting :class:`OrderSnapshotDelta` to:
  * fill-ledger row generation,
  * partial-fill follow-up creation,
  * watermark persistence + audit emission.
"""

import threading
from math import isclose
from unittest.mock import Mock

from configuration import OrderBook
from core.enums import OrderStatus
from core.order_engine import OrderEngine


def _build_engine_for_partial_fill_tests() -> OrderEngine:
    orderbook = Mock(spec=OrderBook)
    orderbook.parent_order_ids = {}
    orderbook.child_order_ids = {}
    orderbook.order = {}
    orderbook.positions = {"FUTURE": {}}
    orderbook.should_replace = {"FILLED": True, "CANCELLED": True}
    orderbook.default_max_order_replacement = 11
    orderbook.product = {
        "BTC-USDC": {
            "base_increment": "0.01",
            "quote_increment": "0.01",
            "price_increment": "0.01",
            "future_product_details": {"contract_size": "1"},
        }
    }
    orderbook.profit = {"SPOT": {"BUY": 0.001, "SELL": 0.001}}
    orderbook.mandatory_fee_per_contract = {}

    # Mock the v2 ``diagnostic_snapshot`` method to return a dict assembled
    # from the attributes above.  ``compute_order_template`` (and friends) now
    # call this method instead of reading attributes individually.
    orderbook.diagnostic_snapshot.side_effect = lambda: {
        "order": orderbook.order,
        "positions": orderbook.positions,
        "product": orderbook.product,
        "profit": orderbook.profit,
        "mandatory_fee_per_contract": orderbook.mandatory_fee_per_contract,
        "parent_order_ids": orderbook.parent_order_ids,
        "child_order_ids": orderbook.child_order_ids,
    }

    db_helper = Mock()
    db_helper.get_parent_order.return_value = {
        "target_movement": 0.001,
        "target_movement_type": "P",
        "allow_partial_fills": True,
    }

    subscription = Mock()
    subscription.channels = []

    engine = OrderEngine(
        orderbook=orderbook,
        db_helper=db_helper,
        subscription=subscription,
        api_key="test_key",
        api_secret="test_secret",
        order_post_only={"BUY": False, "SELL": False},
    )

    # Avoid any incidental DB writes during unit tests.
    engine._persist_progress_from_record = Mock()
    engine._append_order_match_audit = Mock()

    return engine


def _link_child_to_opted_in_parent(
    engine: OrderEngine,
    client_order_id: str,
    parent_client_order_id: str,
    *,
    allow_partial_fills: bool = True,
) -> None:
    engine.orderbook.child_order_ids[client_order_id] = parent_client_order_id
    engine.orderbook.parent_order_ids[parent_client_order_id] = {
        "allow_partial_fills": allow_partial_fills,
        "orders": [client_order_id],
        "target_movement": {"movement": 0.001, "type": "P"},
        "max_order_replacement": 11,
        "current_order_replacement": 0,
    }


# ---------------------------------------------------------------------------
# _process_ws_order_delta — fill ledger path
# ---------------------------------------------------------------------------


def test_process_ws_order_delta_emits_one_fill_per_cumulative_advance():
    """Successive WS events with growing cumulative_quantity must produce one
    derived fill per delta — never one row for the final cumulative total."""
    engine = _build_engine_for_partial_fill_tests()
    client_order_id = "parent-incremental-1"
    _link_child_to_opted_in_parent(
        engine, client_order_id, "parent-incremental-1-root", allow_partial_fills=False
    )

    fill_repo = Mock()
    fill_repo.append_derived_fill = Mock(return_value=True)
    engine.fill_repo = fill_repo
    engine.fill_event_hooks = None

    base_order = {
        "client_order_id": client_order_id,
        "product_id": "BIP-20DEC30-CDE",
        "order_side": "SELL",
        "avg_price": "78000",
        "limit_price": "78000",
    }

    # Match 1: 1.0 @ 78000, total fees 0.228
    e1 = dict(
        base_order,
        cumulative_quantity="1.0",
        filled_value="78000",
        total_fees="0.228",
        number_of_fills=1,
        status="OPEN",
    )
    engine._process_ws_order_delta(e1)

    # Match 2: 4.0 @ 78000, total fees 1.14 (cumulative)
    e2 = dict(
        base_order,
        cumulative_quantity="5.0",
        filled_value="390000",
        total_fees="1.14",
        number_of_fills=2,
        status="FILLED",
    )
    engine._process_ws_order_delta(e2)

    assert fill_repo.append_derived_fill.call_count == 2

    delta1 = fill_repo.append_derived_fill.call_args_list[0].args[0]
    delta2 = fill_repo.append_derived_fill.call_args_list[1].args[0]

    assert isclose(delta1.size_delta, 1.0)
    assert isclose(delta1.derived_price, 78000.0)
    assert isclose(delta1.fee_delta, 0.228, abs_tol=1e-9)

    assert isclose(delta2.size_delta, 4.0)
    assert isclose(delta2.derived_price, 78000.0)
    assert isclose(delta2.fee_delta, 0.912, abs_tol=1e-9)

    # Total preserved across the two derived rows.
    assert isclose(delta1.size_delta + delta2.size_delta, 5.0)
    assert isclose(delta1.fee_delta + delta2.fee_delta, 1.14, abs_tol=1e-9)


def test_process_ws_order_delta_idempotent_on_repeated_event():
    """Same WS snapshot delivered twice (e.g., reconnect replay) must produce
    only one ledger row because the tracker's watermark refuses replays."""
    engine = _build_engine_for_partial_fill_tests()
    client_order_id = "parent-incremental-2"
    _link_child_to_opted_in_parent(
        engine, client_order_id, "parent-incremental-2-root", allow_partial_fills=False
    )

    fill_repo = Mock()
    fill_repo.append_derived_fill = Mock(return_value=True)
    engine.fill_repo = fill_repo
    engine.fill_event_hooks = None

    evt = {
        "client_order_id": client_order_id,
        "product_id": "BTC-USDC",
        "order_side": "BUY",
        "cumulative_quantity": "0.5",
        "filled_value": "21000",
        "total_fees": "0.10",
        "number_of_fills": 1,
        "avg_price": "42000",
        "limit_price": "42000",
        "status": "OPEN",
    }

    engine._process_ws_order_delta(evt)
    engine._process_ws_order_delta(evt)

    # Second call sees no new cumulative delta and must not append.
    assert fill_repo.append_derived_fill.call_count == 1


def test_process_ws_order_delta_no_op_when_no_cumulative():
    """Events without cumulative info (PENDING, snapshot pre-fill) must be ignored."""
    engine = _build_engine_for_partial_fill_tests()

    fill_repo = Mock()
    fill_repo.append_derived_fill = Mock(return_value=True)
    engine.fill_repo = fill_repo
    engine.fill_event_hooks = None

    delta = engine._process_ws_order_delta({"client_order_id": "nope"})
    # Tracker still emits a delta on first sight (status alone). Fill ledger
    # must NOT be touched because there is no size advance.
    fill_repo.append_derived_fill.assert_not_called()


# ---------------------------------------------------------------------------
# Partial-fill follow-up routing
# ---------------------------------------------------------------------------


def test_partial_fill_below_min_accumulates_carry_and_emits_event():
    engine = _build_engine_for_partial_fill_tests()

    client_order_id = "child-1"
    parent_client_order_id = "parent-1"
    _link_child_to_opted_in_parent(engine, client_order_id, parent_client_order_id)

    engine._create_partial_fill_follow_up = Mock(return_value=0)

    publisher = Mock()
    publisher.enabled = True
    engine.event_stream_publisher = publisher

    order = {
        "client_order_id": client_order_id,
        "product_id": "BTC-USDC",
        "order_side": "BUY",
        "cumulative_quantity": "0.003",
        "leaves_quantity": "0.007",
        "number_of_fills": 1,
        "completion_percentage": "30",
        "status": "OPEN",
    }

    engine._process_ws_order_delta(order)

    engine._create_partial_fill_follow_up.assert_not_called()
    # Watermark persistence must run (at least once for the fresh delta).
    assert engine._persist_progress_from_record.called

    event_types = [call.kwargs["event_type"] for call in publisher.publish_event.call_args_list]
    assert "partial_fill_detected" in event_types
    assert "partial_fill_below_min_accumulated" in event_types


def test_partial_fill_due_followups_uses_created_units_for_carry_math():
    engine = _build_engine_for_partial_fill_tests()

    client_order_id = "child-2"
    parent_client_order_id = "parent-2"
    _link_child_to_opted_in_parent(engine, client_order_id, parent_client_order_id)

    engine._create_partial_fill_follow_up = Mock(return_value=1)

    publisher = Mock()
    publisher.enabled = True
    engine.event_stream_publisher = publisher

    order = {
        "client_order_id": client_order_id,
        "product_id": "BTC-USDC",
        "order_side": "BUY",
        "cumulative_quantity": "0.035",
        "number_of_fills": 2,
        "completion_percentage": "35",
        "status": "OPEN",
        "leaves_quantity": "0.965",
    }

    engine._process_ws_order_delta(order)

    engine._create_partial_fill_follow_up.assert_called_once_with(
        client_order_id=client_order_id,
        parent_client_order_id=parent_client_order_id,
        min_order_size=0.01,
        follow_ups_due=3,
    )

    # 2026-04-29 race fix: carry consumption now happens atomically INSIDE
    # ``_create_partial_fill_follow_up`` via
    # ``OrderProgressTracker.claim_follow_up_units``. Since this test mocks
    # the creator out, no claim happens, and the tracker's carry is
    # unchanged from the ingest (full 0.035 accumulated).
    record = engine.order_progress_tracker.get_record(client_order_id)
    assert record is not None
    assert isclose(record.carry_remainder_qty, 0.035, abs_tol=1e-12)
    assert record.partial_follow_ups_created == 0

    queued_calls = [
        call for call in publisher.publish_event.call_args_list
        if call.kwargs.get("event_type") == "partial_fill_follow_up_queued"
    ]
    assert len(queued_calls) == 1
    queued_payload = queued_calls[0].kwargs["payload"]
    assert queued_payload["follow_ups_due"] == 3
    assert queued_payload["follow_ups_created"] == 1


def test_partial_fill_opt_out_skips_processing():
    engine = _build_engine_for_partial_fill_tests()

    client_order_id = "child-3"
    parent_client_order_id = "parent-3"
    _link_child_to_opted_in_parent(
        engine, client_order_id, parent_client_order_id, allow_partial_fills=False
    )

    engine._create_partial_fill_follow_up = Mock(return_value=0)

    order = {
        "client_order_id": client_order_id,
        "product_id": "BTC-USDC",
        "order_side": "BUY",
        "cumulative_quantity": "0.02",
        "leaves_quantity": "0.08",
        "number_of_fills": 1,
        "completion_percentage": "20",
        "status": "OPEN",
    }

    engine._process_ws_order_delta(order)

    # Opt-out: no follow-up creation.
    engine._create_partial_fill_follow_up.assert_not_called()


def test_create_partial_fill_follow_up_clips_to_remaining_replacements():
    engine = _build_engine_for_partial_fill_tests()

    client_order_id = "placed-order-1"
    parent_client_order_id = "parent-4"

    engine.can_create_follow_up_order = Mock(
        return_value=(
            True,
            {"max_order_replacement": 11, "current_order_replacement": 10},
        )
    )
    engine.resolve_parent_target_movement = Mock(return_value={"movement": 0.001, "type": "P"})
    engine.compute_partial_fill_order_template = Mock(
        return_value={
            "start_price": "100.0",
            "side": "BUY",
            "order_base_size": "0.01",
            "product_id": "BTC-USDC",
        }
    )
    engine.register_child_order = Mock()

    stealth_manager = Mock()
    stealth_manager.find_stealth_order_by_placed_order_id.return_value = {
        "stealth_order_id": "stealth-parent-1",
        "reveal_condition_json": {"type": "price", "direction": "below"},
        "follow_up_reveal_direction": "opposite",
    }
    stealth_manager.create_follow_up_stealth_order.return_value = "stealth-child-1"

    engine.stealth_order_bridge = Mock(stealth_manager=stealth_manager)
    engine.db_helper.get_parent_order.return_value = {
        "target_movement": 0.001,
        "target_movement_type": "P",
    }

    # 2026-04-29 race fix: ``_create_partial_fill_follow_up`` now atomically
    # claims units from the tracker BEFORE placement. Seed a record with at
    # least ``follow_ups_due`` units of carry so the claim succeeds.
    engine.order_progress_tracker.hydrate([
        {
            "client_order_id": client_order_id,
            "parent_client_order_id": parent_client_order_id,
            "product_id": "BTC-USDC",
            "side": "BUY",
            "original_order_size": 1.0,
            "min_order_size": 0.01,
            "carry_remainder_qty": 0.05,
            "partial_follow_ups_created": 0,
        }
    ])

    created_units = engine._create_partial_fill_follow_up(
        client_order_id=client_order_id,
        parent_client_order_id=parent_client_order_id,
        min_order_size=0.01,
        follow_ups_due=5,
    )

    assert created_units == 1
    stealth_manager.create_follow_up_stealth_order.assert_called_once()
    follow_up_kwargs = stealth_manager.create_follow_up_stealth_order.call_args.kwargs
    assert isclose(float(follow_up_kwargs["total_size"]), 0.01, rel_tol=0.0, abs_tol=1e-12)
    engine.register_child_order.assert_called_once_with("stealth-child-1", parent_client_order_id)

    # Atomic claim must have decremented carry by exactly 1 * min_size.
    record = engine.order_progress_tracker.get_record(client_order_id)
    assert record is not None
    assert isclose(record.carry_remainder_qty, 0.04, abs_tol=1e-12)
    assert record.partial_follow_ups_created == 1


def test_partial_fill_out_of_order_event_does_not_create_duplicate_followup():
    """An out-of-order/regressing cumulative must never trigger follow-ups."""
    engine = _build_engine_for_partial_fill_tests()

    client_order_id = "child-5"
    parent_client_order_id = "parent-5"
    _link_child_to_opted_in_parent(engine, client_order_id, parent_client_order_id)

    # Prime the tracker as if 0.03 cumulative has already been processed.
    engine.order_progress_tracker.hydrate([
        {
            "client_order_id": client_order_id,
            "parent_client_order_id": parent_client_order_id,
            "product_id": "BTC-USDC",
            "side": "BUY",
            "original_order_size": 1.0,
            "min_order_size": 0.01,
            "last_cumulative_qty_processed": 0.03,
            "carry_remainder_qty": 0.0,
            "last_number_of_fills_seen": 2,
            "last_completion_pct_seen": 30.0,
            "partial_follow_ups_created": 3,
        }
    ])

    engine._create_partial_fill_follow_up = Mock(return_value=0)
    engine._persist_progress_from_record = Mock()

    publisher = Mock()
    publisher.enabled = True
    engine.event_stream_publisher = publisher

    # Out-of-order event: cumulative regresses from 0.03 to 0.02
    order = {
        "client_order_id": client_order_id,
        "product_id": "BTC-USDC",
        "order_side": "BUY",
        "cumulative_quantity": "0.02",
        "number_of_fills": 2,
        "completion_percentage": "20",
        "status": "OPEN",
    }

    engine._process_ws_order_delta(order)

    engine._create_partial_fill_follow_up.assert_not_called()
    engine._persist_progress_from_record.assert_not_called()
    assert publisher.publish_event.call_count == 0


def test_partial_fill_equal_watermark_event_does_not_create_duplicate_followup():
    engine = _build_engine_for_partial_fill_tests()

    client_order_id = "child-6"
    parent_client_order_id = "parent-6"
    _link_child_to_opted_in_parent(engine, client_order_id, parent_client_order_id)

    engine.order_progress_tracker.hydrate([
        {
            "client_order_id": client_order_id,
            "parent_client_order_id": parent_client_order_id,
            "product_id": "BTC-USDC",
            "side": "BUY",
            "original_order_size": 1.0,
            "min_order_size": 0.01,
            "last_cumulative_qty_processed": 0.03,
            "carry_remainder_qty": 0.0,
            "last_number_of_fills_seen": 2,
            "last_completion_pct_seen": 30.0,
            "partial_follow_ups_created": 3,
        }
    ])

    engine._create_partial_fill_follow_up = Mock(return_value=0)
    engine._persist_progress_from_record = Mock()

    publisher = Mock()
    publisher.enabled = True
    engine.event_stream_publisher = publisher

    # Duplicate event: cumulative remains unchanged at 0.03
    order = {
        "client_order_id": client_order_id,
        "product_id": "BTC-USDC",
        "order_side": "BUY",
        "cumulative_quantity": "0.03",
        "number_of_fills": 2,
        "completion_percentage": "30",
        "status": "OPEN",
    }

    engine._process_ws_order_delta(order)

    engine._create_partial_fill_follow_up.assert_not_called()
    engine._persist_progress_from_record.assert_not_called()
    assert publisher.publish_event.call_count == 0


def test_partial_fill_concurrent_duplicate_events_create_followup_once():
    engine = _build_engine_for_partial_fill_tests()

    client_order_id = "child-7"
    parent_client_order_id = "parent-7"
    _link_child_to_opted_in_parent(engine, client_order_id, parent_client_order_id)

    engine.order_progress_tracker.hydrate([
        {
            "client_order_id": client_order_id,
            "parent_client_order_id": parent_client_order_id,
            "product_id": "BTC-USDC",
            "side": "BUY",
            "original_order_size": 1.0,
            "min_order_size": 0.01,
            "last_cumulative_qty_processed": 0.0,
            "carry_remainder_qty": 0.0,
            "last_number_of_fills_seen": 0,
            "last_completion_pct_seen": 0.0,
            "partial_follow_ups_created": 0,
        }
    ])

    engine._create_partial_fill_follow_up = Mock(return_value=2)
    engine._persist_progress_from_record = Mock()

    publisher = Mock()
    publisher.enabled = True
    engine.event_stream_publisher = publisher

    order = {
        "client_order_id": client_order_id,
        "product_id": "BTC-USDC",
        "order_side": "BUY",
        "cumulative_quantity": "0.02",
        "number_of_fills": 1,
        "completion_percentage": "20",
        "status": "OPEN",
    }

    barrier = threading.Barrier(2)

    def _worker():
        barrier.wait()
        engine._process_ws_order_delta(order)

    t1 = threading.Thread(target=_worker)
    t2 = threading.Thread(target=_worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Both threads processed the same event payload; tracker per-COID lock
    # ensures follow-up creation happens only once.
    engine._create_partial_fill_follow_up.assert_called_once_with(
        client_order_id=client_order_id,
        parent_client_order_id=parent_client_order_id,
        min_order_size=0.01,
        follow_ups_due=2,
    )


# ---------------------------------------------------------------------------
# process_user_order routing
# ---------------------------------------------------------------------------


def test_process_user_order_update_routes_through_tracker():
    engine = _build_engine_for_partial_fill_tests()

    engine._process_ws_order_delta = Mock(return_value=None)
    engine._update_dashboard_order_status = Mock()
    engine.websocket_hooks.call_post_order_status = Mock()

    order = {
        "client_order_id": "child-update-1",
        "product_id": "BTC-USDC",
        "order_side": "BUY",
        "status": "UPDATE",
        "cumulative_quantity": "0.01",
    }

    engine.process_user_order(order)

    engine._process_ws_order_delta.assert_called_once()
    engine._update_dashboard_order_status.assert_called_once()
    engine.websocket_hooks.call_post_order_status.assert_called_once()


def test_finalize_partial_fill_progress_drops_tracker_record():
    engine = _build_engine_for_partial_fill_tests()

    client_order_id = "child-finalize-1"
    engine.order_progress_tracker.hydrate([
        {
            "client_order_id": client_order_id,
            "parent_client_order_id": "parent-finalize-1",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "original_order_size": 1.0,
            "min_order_size": 0.01,
            "last_cumulative_qty_processed": 0.01,
            "carry_remainder_qty": 0.0,
            "last_number_of_fills_seen": 1,
            "last_completion_pct_seen": 10.0,
            "partial_follow_ups_created": 1,
        }
    ])

    assert engine.order_progress_tracker.get_record(client_order_id) is not None

    engine._finalize_partial_fill_progress(client_order_id, "FINALIZED")

    assert engine.order_progress_tracker.get_record(client_order_id) is None


def test_partial_fill_template_flips_side_for_opposite_exit():
    """Partial-fill follow-up must be the EXIT trade for the just-filled units:
    opposite-side at a target-adjusted price, regardless of in-flight status."""
    engine = _build_engine_for_partial_fill_tests()

    client_order_id = "child-filled-snapshot-1"
    engine.orderbook.order[client_order_id] = {
        "client_order_id": client_order_id,
        "product_id": "BTC-USDC",
        "status": OrderStatus.OPEN.value,  # mid-fill, not terminal
        "order_side": "BUY",
        "side": "BUY",
        "limit_price": "100.0",
        "avg_price": "100.0",
        "size": "1.0",
        "filled_size": "0.5",
        "leaves_quantity": "0.5",
    }

    partial_template = engine.compute_partial_fill_order_template(client_order_id)
    assert partial_template["side"] == "SELL"
    # Price moved up by profit target (BUY parent → SELL exit above entry).
    assert float(partial_template["start_price"]) > 100.0
