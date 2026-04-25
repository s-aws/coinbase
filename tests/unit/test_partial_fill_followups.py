"""Unit tests for partial-fill follow-up creation and persistence math."""

import threading
from math import isclose
from unittest.mock import Mock

from configuration import OrderBook
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
            "future_product_details": {"contract_size": "1"},
        }
    }
    orderbook.profit = {"SPOT": {"BUY": 0.001, "SELL": 0.001}}
    orderbook.mandatory_fee_per_contract = {}

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

    return engine


def test_partial_fill_below_min_accumulates_carry_and_emits_event():
    engine = _build_engine_for_partial_fill_tests()

    client_order_id = "child-1"
    parent_client_order_id = "parent-1"
    engine.orderbook.child_order_ids[client_order_id] = parent_client_order_id
    engine.orderbook.parent_order_ids[parent_client_order_id] = {
        "allow_partial_fills": True,
        "orders": [client_order_id],
        "target_movement": {"movement": 0.001, "type": "P"},
        "max_order_replacement": 11,
        "current_order_replacement": 0,
    }

    engine._create_partial_fill_follow_up = Mock(return_value=0)
    engine._save_partial_fill_progress = Mock()

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
    }

    engine._handle_partial_fill_if_enabled(client_order_id, order)

    engine._create_partial_fill_follow_up.assert_not_called()
    engine._save_partial_fill_progress.assert_called_once()

    kwargs = engine._save_partial_fill_progress.call_args.kwargs
    assert isclose(kwargs["carry_remainder"], 0.003, rel_tol=0.0, abs_tol=1e-12)
    assert kwargs["follow_ups_created"] == 0

    event_types = [call.kwargs["event_type"] for call in publisher.publish_event.call_args_list]
    assert "partial_fill_detected" in event_types
    assert "partial_fill_below_min_accumulated" in event_types


def test_partial_fill_due_followups_uses_created_units_for_carry_math():
    engine = _build_engine_for_partial_fill_tests()

    client_order_id = "child-2"
    parent_client_order_id = "parent-2"

    engine._partial_fill_state[client_order_id] = {
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

    engine._create_partial_fill_follow_up = Mock(return_value=1)
    engine._save_partial_fill_progress = Mock()

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
    }

    engine._handle_partial_fill_if_enabled(client_order_id, order)

    engine._create_partial_fill_follow_up.assert_called_once_with(
        client_order_id=client_order_id,
        parent_client_order_id=parent_client_order_id,
        min_order_size=0.01,
        follow_ups_due=3,
    )

    kwargs = engine._save_partial_fill_progress.call_args.kwargs
    assert isclose(kwargs["carry_remainder"], 0.025, rel_tol=0.0, abs_tol=1e-12)
    assert kwargs["follow_ups_created"] == 1

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

    engine.orderbook.child_order_ids[client_order_id] = parent_client_order_id
    engine.orderbook.parent_order_ids[parent_client_order_id] = {
        "allow_partial_fills": False,
        "orders": [client_order_id],
        "target_movement": {"movement": 0.001, "type": "P"},
        "max_order_replacement": 11,
        "current_order_replacement": 0,
    }

    engine._create_partial_fill_follow_up = Mock(return_value=0)
    engine._save_partial_fill_progress = Mock()

    order = {
        "client_order_id": client_order_id,
        "product_id": "BTC-USDC",
        "order_side": "BUY",
        "cumulative_quantity": "0.02",
        "leaves_quantity": "0.08",
        "number_of_fills": 1,
        "completion_percentage": "20",
    }

    engine._handle_partial_fill_if_enabled(client_order_id, order)

    engine._create_partial_fill_follow_up.assert_not_called()
    engine._save_partial_fill_progress.assert_not_called()


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
    engine.compute_order_template = Mock(
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


def test_partial_fill_out_of_order_event_does_not_create_duplicate_followup():
    engine = _build_engine_for_partial_fill_tests()

    client_order_id = "child-5"
    parent_client_order_id = "parent-5"

    # Existing processed state: watermark already advanced to 0.03
    engine._partial_fill_state[client_order_id] = {
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

    engine._create_partial_fill_follow_up = Mock(return_value=0)
    engine._save_partial_fill_progress = Mock()

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
    }

    engine._handle_partial_fill_if_enabled(client_order_id, order)

    # No delta advancement -> no follow-up queueing and no watermark write
    engine._create_partial_fill_follow_up.assert_not_called()
    engine._save_partial_fill_progress.assert_not_called()
    assert publisher.publish_event.call_count == 0


def test_partial_fill_equal_watermark_event_does_not_create_duplicate_followup():
    engine = _build_engine_for_partial_fill_tests()

    client_order_id = "child-6"
    parent_client_order_id = "parent-6"

    # Existing processed state: watermark already at 0.03
    engine._partial_fill_state[client_order_id] = {
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

    engine._create_partial_fill_follow_up = Mock(return_value=0)
    engine._save_partial_fill_progress = Mock()

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
    }

    engine._handle_partial_fill_if_enabled(client_order_id, order)

    # No advancement -> no follow-up queueing and no watermark write
    engine._create_partial_fill_follow_up.assert_not_called()
    engine._save_partial_fill_progress.assert_not_called()
    assert publisher.publish_event.call_count == 0


def test_partial_fill_concurrent_duplicate_events_create_followup_once():
    engine = _build_engine_for_partial_fill_tests()

    client_order_id = "child-7"
    parent_client_order_id = "parent-7"

    engine._partial_fill_state[client_order_id] = {
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

    def _fake_save_partial_fill_progress(**kwargs):
        with engine._partial_fill_state_lock:
            engine._partial_fill_state[client_order_id] = {
                "parent_client_order_id": kwargs["parent_client_order_id"],
                "product_id": kwargs["product_id"],
                "side": kwargs["side"],
                "original_order_size": kwargs["original_order_size"],
                "min_order_size": kwargs["min_order_size"],
                "last_cumulative_qty_processed": kwargs["cumulative_qty"],
                "carry_remainder_qty": kwargs["carry_remainder"],
                "last_number_of_fills_seen": kwargs["number_of_fills"],
                "last_completion_pct_seen": kwargs["completion_pct"],
                "partial_follow_ups_created": kwargs["follow_ups_created"],
            }

    engine._save_partial_fill_progress = Mock(side_effect=_fake_save_partial_fill_progress)
    engine._create_partial_fill_follow_up = Mock(return_value=2)

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
    }

    barrier = threading.Barrier(2)

    def _worker():
        barrier.wait()
        engine._handle_partial_fill_if_enabled(client_order_id, order)

    t1 = threading.Thread(target=_worker)
    t2 = threading.Thread(target=_worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Both threads processed the same event payload; lock serialization ensures
    # follow-up creation happens only once.
    engine._create_partial_fill_follow_up.assert_called_once_with(
        client_order_id=client_order_id,
        parent_client_order_id=parent_client_order_id,
        min_order_size=0.01,
        follow_ups_due=2,
    )
