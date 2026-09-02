"""Regression contracts for Coinbase authenticated user-channel dispatch.

The wire envelope type (``snapshot``/``update``/``patch``) is deliberately
separate from the lifecycle ``status`` carried by each order.  Bootstrap pages
must be reduced into one venue snapshot before any order lifecycle side effect
is allowed; only post-bootstrap deltas use ``process_user_order``.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from queue import Full, Queue
from unittest.mock import Mock, call

import pytest

import core.order_engine as order_engine_module
from core.enums import ChannelType, UserFeedPhase
from core.order_engine import OrderEngine, UserStreamEnvelope


pytestmark = pytest.mark.regression


def _order(index: int, *, status: str = "OPEN") -> dict:
    return {
        "client_order_id": f"00000000-0000-4000-8000-{index:012d}",
        "order_id": f"exchange-{index}",
        "product_id": "BTC-USDC",
        "status": status,
        "order_side": "BUY",
        "cumulative_quantity": "0",
        "leaves_quantity": "1",
        "filled_value": "0",
        "total_fees": "0",
        "number_of_fills": "0",
        "completion_percentage": "0",
        "outstanding_hold_amount": "0",
    }


def _bare_user_engine() -> OrderEngine:
    """Build the event-reducer surface without REST, DB, or worker threads."""

    engine = OrderEngine.__new__(OrderEngine)
    engine.process_user_order = Mock(name="process_user_order")
    engine.process_user_snapshot = Mock(name="process_user_snapshot")
    engine.snapshot_drift_check = Mock(name="snapshot_drift_check")
    engine._hydrate_orderbook_from_ws_snapshot = Mock(
        name="hydrate_orderbook_from_ws_snapshot"
    )
    engine.websocket_events = {
        event_type.upper(): {"type": event_type}
        for event_type in ("snapshot", "update", "patch")
    }
    engine.log_message = Mock(name="log_message")
    engine.build_event_log_payload = (
        lambda event, **details: {"event": event, **details}
    )
    engine.include_debug_fields = lambda **fields: fields
    return engine


def _private_ingress_engine(*, queue_size: int = 8):
    engine = _bare_user_engine()
    engine.subscription = type(
        "Subscription",
        (),
        {
            "channels": (
                ChannelType.HEARTBEATS.value,
                ChannelType.USER.value,
                ChannelType.TICKER.value,
                ChannelType.FUTURES_BALANCE_SUMMARY.value,
            ),
            "product_ids": ("BTC-USDC",),
        },
    )()
    engine.event_queue = {
        channel: Queue(maxsize=queue_size)
        for channel in engine.subscription.channels
    }
    engine._shutdown_event = threading.Event()
    engine.websocket_thread_maximum = 3
    engine._ensure_user_stream_state()
    reconnect_event = threading.Event()
    generation = engine._begin_user_stream_generation(reconnect_event)
    return engine, generation, reconnect_event


def _wire_user_message(
    sequence_num: int,
    events,
    *,
    timestamp=None,
    channel: str = ChannelType.USER.value,
) -> str:
    return json.dumps(
        {
            "channel": channel,
            "timestamp": timestamp or "2026-08-28T12:34:56.123456Z",
            "sequence_num": sequence_num,
            "events": events,
        }
    )


@pytest.mark.parametrize("continuation_type", ("patch", "update"))
def test_paginated_bootstrap_hydrates_once_without_lifecycle_side_effects(
    continuation_type,
):
    """Both documented wire dialects must reduce 50 + 50 + 9 atomically."""

    engine = _bare_user_engine()
    pages = (
        {"type": "snapshot", "orders": [_order(i) for i in range(50)]},
        {
            "type": continuation_type,
            "orders": [_order(i) for i in range(50, 100)],
        },
        {
            "type": continuation_type,
            "orders": [_order(i) for i in range(100, 109)],
        },
    )

    for page in pages:
        engine.process_user_event(page)

    engine.process_user_order.assert_not_called()
    engine.snapshot_drift_check.assert_called_once_with(
        {order["client_order_id"] for page in pages for order in page["orders"]},
        source="ws_user_snapshot",
    )
    engine._hydrate_orderbook_from_ws_snapshot.assert_called_once()
    hydrated = engine._hydrate_orderbook_from_ws_snapshot.call_args.args[0]
    assert [order["client_order_id"] for order in hydrated] == [
        order["client_order_id"] for page in pages for order in page["orders"]
    ]


@pytest.mark.parametrize("first_page_size", (0, 1, 49))
def test_short_initial_snapshot_completes_bootstrap(first_page_size):
    engine = _bare_user_engine()
    orders = [_order(index) for index in range(first_page_size)]

    engine.process_user_event({"type": "snapshot", "orders": orders})

    engine.process_user_order.assert_not_called()
    engine.snapshot_drift_check.assert_called_once_with(
        {order["client_order_id"] for order in orders},
        source="ws_user_snapshot",
    )
    engine._hydrate_orderbook_from_ws_snapshot.assert_called_once_with(orders)


@pytest.mark.parametrize("terminator_type", ("patch", "update"))
def test_exactly_fifty_orders_waits_for_a_short_terminator(terminator_type):
    engine = _bare_user_engine()
    first_page = [_order(index) for index in range(50)]

    engine.process_user_event({"type": "snapshot", "orders": first_page})

    engine.snapshot_drift_check.assert_not_called()
    engine._hydrate_orderbook_from_ws_snapshot.assert_not_called()
    engine.process_user_order.assert_not_called()

    engine.process_user_event({"type": terminator_type, "orders": []})

    engine.snapshot_drift_check.assert_called_once_with(
        {order["client_order_id"] for order in first_page},
        source="ws_user_snapshot",
    )
    engine._hydrate_orderbook_from_ws_snapshot.assert_called_once_with(first_page)
    engine.process_user_order.assert_not_called()


@pytest.mark.parametrize("total_orders", (51, 100))
def test_multi_page_bootstrap_handles_boundary_totals(total_orders):
    engine = _bare_user_engine()
    orders = [_order(index) for index in range(total_orders)]
    pages = [orders[index : index + 50] for index in range(0, total_orders, 50)]
    if total_orders % 50 == 0:
        pages.append([])

    for index, page in enumerate(pages):
        engine.process_user_event(
            {
                "type": "snapshot" if index == 0 else "patch",
                "orders": page,
            }
        )

    engine.process_user_order.assert_not_called()
    engine.snapshot_drift_check.assert_called_once_with(
        {order["client_order_id"] for order in orders},
        source="ws_user_snapshot",
    )
    engine._hydrate_orderbook_from_ws_snapshot.assert_called_once_with(orders)


@pytest.mark.parametrize("live_type", ("patch", "update"))
def test_post_bootstrap_update_and_patch_use_the_canonical_order_path(live_type):
    engine = _bare_user_engine()
    engine.process_user_event({"type": "snapshot", "orders": []})
    first = _order(1, status="OPEN")
    second = _order(2, status="FILLED")

    engine.process_user_event(
        {"type": live_type, "orders": [first, second]}
    )

    assert engine.process_user_order.call_args_list == [
        call(first),
        call(second),
    ]
    engine.snapshot_drift_check.assert_called_once_with(
        set(), source="ws_user_snapshot"
    )
    engine._hydrate_orderbook_from_ws_snapshot.assert_called_once_with([])


@pytest.mark.parametrize("event_type", ("patch", "update"))
@pytest.mark.parametrize(
    ("hold_case", "hold_value"),
    (
        ("missing", None),
        ("null", None),
        ("empty", ""),
        ("whitespace", " "),
        ("nonnumeric", "not-available"),
        ("positive", "2.51"),
        ("zero", "0"),
    ),
)
def test_private_ingress_treats_outstanding_hold_as_optional_metadata(
    event_type,
    hold_case,
    hold_value,
):
    engine, generation, reconnect_event = _private_ingress_engine()

    engine.on_user_message(
        _wire_user_message(1, [{"type": "snapshot", "orders": []}]),
        generation=generation,
    )
    engine.process_private_envelope(
        engine.event_queue[ChannelType.USER.value].get_nowait()
    )

    order = _order(1, status="FILLED")
    if hold_case == "missing":
        order.pop("outstanding_hold_amount")
    else:
        order["outstanding_hold_amount"] = hold_value

    engine.on_user_message(
        _wire_user_message(
            2,
            [{"type": event_type, "orders": [order]}],
        ),
        generation=generation,
    )
    engine.process_private_envelope(
        engine.event_queue[ChannelType.USER.value].get_nowait()
    )

    engine.process_user_order.assert_called_once_with(order)
    assert engine._user_feed_phase is UserFeedPhase.LIVE
    assert reconnect_event.is_set() is False


def test_incident_terminal_rows_are_not_suppressed_by_noncanonical_hold():
    engine, generation, reconnect_event = _private_ingress_engine()

    engine.on_user_message(
        _wire_user_message(1, [{"type": "snapshot", "orders": []}]),
        generation=generation,
    )
    engine.process_private_envelope(
        engine.event_queue[ChannelType.USER.value].get_nowait()
    )

    sizes = (5, 5, 70, 60, 60)
    first_cumulative = (5, 5, 56, 58, 29)
    first_statuses = ("FILLED", "FILLED", "OPEN", "OPEN", "OPEN")
    first_holds = ("2.51", "5.02", "40.17", "70.30", "100.43")
    first_rows = []
    terminal_rows = []
    for index, (size, cumulative, status, hold) in enumerate(
        zip(sizes, first_cumulative, first_statuses, first_holds),
        start=1,
    ):
        first = _order(index, status=status)
        first.update(
            {
                "avg_price": "77180",
                "cumulative_quantity": str(cumulative),
                "leaves_quantity": str(size - cumulative),
                "filled_value": str(cumulative * 77180),
                "number_of_fills": "1",
                "completion_percentage": str(cumulative / size * 100),
                "outstanding_hold_amount": hold,
            }
        )
        first_rows.append(first)

        terminal = {**first}
        terminal.update(
            {
                "status": "FILLED",
                "cumulative_quantity": str(size),
                "leaves_quantity": "0",
                "filled_value": str(size * 77180),
                "number_of_fills": "1" if cumulative == size else "2",
                "completion_percentage": "100",
                "outstanding_hold_amount": "0",
            }
        )
        terminal_rows.append(terminal)

    # The production log proves that a later row for the 70-unit order carried
    # the key but failed numeric validation; it did not retain the raw value.
    # None represents that noncanonical optional metadata here. It must not
    # reject the four valid sibling rows or tear down the user generation.
    terminal_rows[2]["outstanding_hold_amount"] = None

    for sequence_num, rows in ((2, first_rows), (3, terminal_rows)):
        engine.on_user_message(
            _wire_user_message(
                sequence_num,
                [{"type": "patch", "orders": rows}],
            ),
            generation=generation,
        )
        engine.process_private_envelope(
            engine.event_queue[ChannelType.USER.value].get_nowait()
        )

    assert engine.process_user_order.call_args_list == [
        *(call(order) for order in first_rows),
        *(call(order) for order in terminal_rows),
    ]
    assert engine._user_feed_phase is UserFeedPhase.LIVE
    assert reconnect_event.is_set() is False


def test_patch_envelope_does_not_rewrite_expired_lifecycle_status():
    engine = _bare_user_engine()
    engine.process_user_event({"type": "snapshot", "orders": []})
    expired = _order(1, status="EXPIRED")

    engine.process_user_event({"type": "patch", "orders": [expired]})

    engine.process_user_order.assert_called_once_with(expired)
    assert expired["status"] == "EXPIRED"


def test_live_delta_missing_client_order_id_fails_the_whole_event_closed():
    engine = _bare_user_engine()
    reconnect_event = threading.Event()
    generation = engine._begin_user_stream_generation(reconnect_event)
    engine.process_user_event(
        {"type": "snapshot", "orders": []}, generation=generation
    )
    missing_coid = _order(2)
    missing_coid.pop("client_order_id")
    valid = _order(1)

    engine.process_user_event(
        {"type": "patch", "orders": [missing_coid, valid]},
        generation=generation,
    )

    engine.process_user_order.assert_not_called()
    assert engine._user_feed_phase is UserFeedPhase.DESYNCHRONIZED
    assert reconnect_event.is_set()
    assert any(
        call_args.args[1].get("reason") == "incomplete_live_order_row"
        and call_args.args[1].get("missing_fields") == ["client_order_id"]
        for call_args in engine.log_message.call_args_list
        if len(call_args.args) >= 2 and isinstance(call_args.args[1], dict)
    )


def test_malformed_live_order_row_fails_closed_without_dispatch():
    engine = _bare_user_engine()
    reconnect_event = threading.Event()
    generation = engine._begin_user_stream_generation(reconnect_event)
    engine.process_user_event(
        {"type": "snapshot", "orders": []}, generation=generation
    )

    engine.process_user_event(
        {"type": "patch", "orders": [None]}, generation=generation
    )

    engine.process_user_order.assert_not_called()
    assert engine._user_feed_phase is UserFeedPhase.DESYNCHRONIZED
    assert reconnect_event.is_set()


def test_incomplete_bootstrap_order_row_fails_closed_before_hydration():
    engine = _bare_user_engine()
    reconnect_event = threading.Event()
    generation = engine._begin_user_stream_generation(reconnect_event)
    incomplete = _order(1)
    incomplete.pop("product_id")

    engine.process_user_event(
        {"type": "snapshot", "orders": [incomplete]},
        generation=generation,
    )

    engine.snapshot_drift_check.assert_not_called()
    engine._hydrate_orderbook_from_ws_snapshot.assert_not_called()
    engine.process_user_order.assert_not_called()
    assert engine._user_bootstrap_orders == {}
    assert engine._user_feed_phase is UserFeedPhase.DESYNCHRONIZED
    assert reconnect_event.is_set()
    assert any(
        args.args[1].get("reason") == "incomplete_bootstrap_order_row"
        and args.args[1].get("missing_fields") == ["product_id"]
        for args in engine.log_message.call_args_list
        if len(args.args) >= 2 and isinstance(args.args[1], dict)
    )


def test_known_wire_event_without_orders_or_positions_fails_closed():
    engine = _bare_user_engine()
    reconnect_event = threading.Event()
    generation = engine._begin_user_stream_generation(reconnect_event)

    engine.process_user_event({"type": "snapshot"}, generation=generation)

    assert engine._user_feed_phase is UserFeedPhase.DESYNCHRONIZED
    assert reconnect_event.is_set()


def test_orders_and_positions_in_one_live_event_are_dispatched_independently():
    engine = _bare_user_engine()
    engine.process_user_event({"type": "snapshot", "orders": []})
    order = _order(1)
    positions = {"perpetual_futures_positions": []}
    event = {"type": "patch", "orders": [order], "positions": positions}

    engine.process_user_event(event)

    engine.process_user_order.assert_called_once_with(order)
    engine.process_user_snapshot.assert_called_once_with(event)


def test_positions_only_snapshot_does_not_restart_live_order_bootstrap():
    engine = _bare_user_engine()
    engine.process_user_event({"type": "snapshot", "orders": []})
    positions_event = {
        "type": "snapshot",
        "positions": {"expiring_futures_positions": []},
    }

    engine.process_user_event(positions_event)

    assert engine._user_feed_phase is UserFeedPhase.LIVE
    engine.process_user_snapshot.assert_called_once_with(positions_event)
    engine._hydrate_orderbook_from_ws_snapshot.assert_called_once_with([])


def test_position_processing_survives_order_protocol_failure():
    engine = _bare_user_engine()
    reconnect_event = threading.Event()
    generation = engine._begin_user_stream_generation(reconnect_event)
    event = {
        "type": "patch",
        "orders": [_order(1)],
        "positions": {"expiring_futures_positions": []},
    }

    engine.process_user_event(event, generation=generation)

    engine.process_user_snapshot.assert_called_once_with(event)
    engine.process_user_order.assert_not_called()
    assert engine._user_feed_phase is UserFeedPhase.DESYNCHRONIZED
    assert reconnect_event.is_set()


@pytest.mark.parametrize(
    "invalid_update",
    (
        {"cumulative_quantity": None},
        {"number_of_fills": "1.5"},
        {"status": "filled"},
        {"order_side": "buy"},
        {"order_id": 123},
        {"product_id": "   "},
        {"client_order_id": 123},
        {"client_order_id": ""},
        {"client_order_id": "   "},
        {
            "cumulative_quantity": "1",
            "number_of_fills": "1",
            "completion_percentage": "50",
        },
    ),
)
def test_malformed_complete_live_row_desynchronizes_before_dispatch(
    invalid_update,
):
    engine = _bare_user_engine()
    reconnect_event = threading.Event()
    generation = engine._begin_user_stream_generation(reconnect_event)
    engine.process_user_event(
        {"type": "snapshot", "orders": []}, generation=generation
    )
    malformed = _order(1)
    malformed.update(invalid_update)

    engine.process_user_event(
        {"type": "patch", "orders": [malformed]}, generation=generation
    )

    engine.process_user_order.assert_not_called()
    assert engine._user_feed_phase is UserFeedPhase.DESYNCHRONIZED
    assert reconnect_event.is_set()


def test_orders_null_processes_positions_then_fails_closed():
    engine = _bare_user_engine()
    reconnect_event = threading.Event()
    generation = engine._begin_user_stream_generation(reconnect_event)
    engine.process_user_event(
        {"type": "snapshot", "orders": []}, generation=generation
    )
    event = {
        "type": "patch",
        "orders": None,
        "positions": {"expiring_futures_positions": []},
    }

    engine.process_user_event(event, generation=generation)

    engine.process_user_snapshot.assert_called_once_with(event)
    engine.process_user_order.assert_not_called()
    assert engine._user_feed_phase is UserFeedPhase.DESYNCHRONIZED
    assert reconnect_event.is_set()


def test_bootstrap_orders_do_not_suppress_positions_from_the_same_event():
    engine = _bare_user_engine()
    positions = {"perpetual_futures_positions": []}
    event = {
        "type": "snapshot",
        "orders": [_order(1)],
        "positions": positions,
    }

    engine.process_user_event(event)

    engine.process_user_order.assert_not_called()
    engine.process_user_snapshot.assert_called_once_with(event)
    engine._hydrate_orderbook_from_ws_snapshot.assert_called_once_with(
        event["orders"]
    )


def test_private_ingress_queues_the_complete_sequence_owned_envelope():
    engine, generation, _ = _private_ingress_engine()
    timestamp = "2026-08-28T12:34:56.654321Z"
    events = ({"type": "snapshot", "orders": [_order(1)]},)

    engine.on_user_message(
        _wire_user_message(42, events, timestamp=timestamp),
        generation=generation,
    )

    queued = engine.event_queue[ChannelType.USER.value].get_nowait()
    assert queued == UserStreamEnvelope(
        generation=generation,
        sequence_num=42,
        timestamp=timestamp,
        events=events,
    )
    assert engine._user_last_sequence_num == 42
    assert engine._user_feed_phase is UserFeedPhase.AWAITING_SNAPSHOT


def test_private_ingress_ignores_an_exact_sequence_duplicate():
    engine, generation, reconnect_event = _private_ingress_engine()
    message = _wire_user_message(
        7, [{"type": "snapshot", "orders": []}]
    )

    engine.on_user_message(message, generation=generation)
    engine.on_user_message(message, generation=generation)

    assert engine.event_queue[ChannelType.USER.value].qsize() == 1
    assert engine._user_feed_phase is UserFeedPhase.AWAITING_SNAPSHOT
    assert reconnect_event.is_set() is False
    assert any(
        args.args[1].get("event") == "user_envelope_duplicate_ignored"
        for args in engine.log_message.call_args_list
        if len(args.args) >= 2 and isinstance(args.args[1], dict)
    )


def test_conflicting_payload_at_same_sequence_fails_closed():
    engine, generation, reconnect_event = _private_ingress_engine()
    engine.on_user_message(
        _wire_user_message(7, [{"type": "snapshot", "orders": []}]),
        generation=generation,
    )

    engine.on_user_message(
        _wire_user_message(
            7,
            [{"type": "snapshot", "orders": [_order(1)]}],
        ),
        generation=generation,
    )

    assert engine.event_queue[ChannelType.USER.value].qsize() == 1
    assert engine._user_last_sequence_num == 7
    assert engine._user_feed_phase is UserFeedPhase.DESYNCHRONIZED
    assert reconnect_event.is_set()
    assert any(
        args.args[1].get("reason") == "conflicting_duplicate_sequence"
        for args in engine.log_message.call_args_list
        if len(args.args) >= 2 and isinstance(args.args[1], dict)
    )


@pytest.mark.parametrize(
    ("second_sequence", "expected_reason"),
    ((12, "sequence_gap"), (9, "sequence_regression")),
)
def test_sequence_discontinuity_desynchronizes_and_requests_reconnect(
    second_sequence,
    expected_reason,
):
    engine, generation, reconnect_event = _private_ingress_engine()
    event = [{"type": "snapshot", "orders": []}]
    engine.on_user_message(
        _wire_user_message(10, event), generation=generation
    )

    engine.on_user_message(
        _wire_user_message(second_sequence, event),
        generation=generation,
    )

    assert engine._user_feed_phase is UserFeedPhase.DESYNCHRONIZED
    assert reconnect_event.is_set()
    assert engine._user_last_sequence_num == 10
    assert engine.event_queue[ChannelType.USER.value].qsize() == 1
    assert any(
        args.args[1].get("event") == "user_stream_desynchronized"
        and args.args[1].get("reason") == expected_reason
        for args in engine.log_message.call_args_list
        if len(args.args) >= 2 and isinstance(args.args[1], dict)
    )


def test_desynchronized_generation_rejects_all_later_ingress():
    engine, generation, reconnect_event = _private_ingress_engine()
    event = [{"type": "snapshot", "orders": []}]
    engine.on_user_message(
        _wire_user_message(10, event), generation=generation
    )
    engine.on_user_message(
        _wire_user_message(12, event), generation=generation
    )
    assert reconnect_event.is_set()

    engine.on_user_message(
        _wire_user_message(11, event), generation=generation
    )

    assert engine._user_last_sequence_num == 10
    assert engine.event_queue[ChannelType.USER.value].qsize() == 1
    assert engine._user_feed_phase is UserFeedPhase.DESYNCHRONIZED


@pytest.mark.parametrize(
    ("auxiliary_channel", "auxiliary_event"),
    (
        (
            ChannelType.HEARTBEATS.value,
            {"type": "heartbeat", "current_time": "ignored"},
        ),
        (
            ChannelType.FUTURES_BALANCE_SUMMARY.value,
            {"type": "snapshot", "fcm_balance_summary": {}},
        ),
    ),
)
def test_auxiliary_private_channels_share_connection_sequence_continuity(
    auxiliary_channel,
    auxiliary_event,
):
    engine, generation, reconnect_event = _private_ingress_engine()
    user_event = [{"type": "snapshot", "orders": []}]
    engine.on_user_message(
        _wire_user_message(10, user_event), generation=generation
    )

    engine.on_user_message(
        _wire_user_message(
            11,
            [auxiliary_event],
            channel=auxiliary_channel,
        ),
        generation=generation,
    )
    engine.on_user_message(
        _wire_user_message(12, user_event), generation=generation
    )

    assert engine._user_feed_phase is UserFeedPhase.AWAITING_SNAPSHOT
    assert reconnect_event.is_set() is False
    assert engine._user_last_sequence_num == 12
    assert engine.event_queue[ChannelType.USER.value].qsize() == 3
    if auxiliary_channel != ChannelType.USER.value:
        assert engine.event_queue[auxiliary_channel].empty()


def test_subscription_acknowledgements_participate_in_global_sequence():
    engine, generation, reconnect_event = _private_ingress_engine()
    engine.on_user_message(
        _wire_user_message(
            20,
            [{"subscriptions": {"user": ["BTC-USDC"]}}],
            channel=ChannelType.SUBSCRIPTIONS.value,
        ),
        generation=generation,
    )
    engine.on_user_message(
        _wire_user_message(
            21,
            [{"type": "heartbeat", "heartbeat_counter": "1"}],
            channel=ChannelType.HEARTBEATS.value,
        ),
        generation=generation,
    )
    engine.on_user_message(
        _wire_user_message(22, [{"type": "snapshot", "orders": []}]),
        generation=generation,
    )

    assert engine._user_last_sequence_num == 22
    assert reconnect_event.is_set() is False
    assert engine.event_queue[ChannelType.HEARTBEATS.value].empty()
    assert engine.event_queue[ChannelType.USER.value].qsize() == 2


def test_public_channel_on_private_connection_fails_closed():
    engine, generation, reconnect_event = _private_ingress_engine()

    engine.on_user_message(
        _wire_user_message(
            1,
            [{"type": "update", "tickers": []}],
            channel=ChannelType.TICKER.value,
        ),
        generation=generation,
    )

    assert engine._user_feed_phase is UserFeedPhase.DESYNCHRONIZED
    assert reconnect_event.is_set()
    assert engine._user_last_sequence_num is None
    assert engine.event_queue[ChannelType.TICKER.value].empty()
    assert any(
        args.args[1].get("reason") == "unexpected_private_channel"
        for args in engine.log_message.call_args_list
        if len(args.args) >= 2 and isinstance(args.args[1], dict)
    )


@pytest.mark.parametrize(
    ("private_channel", "events"),
    (
        (ChannelType.USER.value, [{"type": "snapshot", "orders": []}]),
        (
            ChannelType.FUTURES_BALANCE_SUMMARY.value,
            [{"type": "snapshot", "fcm_balance_summary": {}}],
        ),
    ),
)
def test_private_channel_on_public_ingress_is_rejected(
    private_channel,
    events,
):
    engine, _, _ = _private_ingress_engine()

    engine.on_message(
        _wire_user_message(1, events, channel=private_channel)
    )

    assert engine.event_queue[private_channel].empty()


def test_private_queue_overflow_desynchronizes_instead_of_dropping_silently():
    engine, generation, reconnect_event = _private_ingress_engine(queue_size=1)
    sentinel = object()
    engine.event_queue[ChannelType.USER.value].put_nowait(sentinel)

    engine.on_user_message(
        _wire_user_message(1, [{"type": "snapshot", "orders": []}]),
        generation=generation,
    )

    assert engine._user_feed_phase is UserFeedPhase.DESYNCHRONIZED
    assert reconnect_event.is_set()
    assert engine._user_last_sequence_num is None
    assert engine.event_queue[ChannelType.USER.value].get_nowait() is sentinel
    assert any(
        args.args[1].get("reason") == "private_event_queue_full"
        for args in engine.log_message.call_args_list
        if len(args.args) >= 2 and isinstance(args.args[1], dict)
    )


@pytest.mark.parametrize("events", ([], [None]))
def test_private_ingress_malformed_event_list_requests_reconnect(events):
    engine, generation, reconnect_event = _private_ingress_engine()

    engine.on_user_message(
        _wire_user_message(1, events), generation=generation
    )

    assert engine._user_feed_phase is UserFeedPhase.DESYNCHRONIZED
    assert reconnect_event.is_set()
    assert engine.event_queue[ChannelType.USER.value].empty()


def test_new_generation_discards_partial_bootstrap_and_ignores_stale_envelope():
    engine, first_generation, _ = _private_ingress_engine()
    first_page = [_order(index) for index in range(50)]
    engine.process_user_event(
        {"type": "snapshot", "orders": first_page},
        generation=first_generation,
    )
    assert engine._user_feed_phase is UserFeedPhase.BOOTSTRAPPING
    assert len(engine._user_bootstrap_orders) == 50

    second_generation = engine._begin_user_stream_generation(
        threading.Event()
    )
    assert second_generation == first_generation + 1
    assert engine._user_feed_phase is UserFeedPhase.AWAITING_SNAPSHOT
    assert engine._user_bootstrap_orders == {}

    stale = UserStreamEnvelope(
        generation=first_generation,
        sequence_num=2,
        timestamp=None,
        events=({"type": "patch", "orders": [_order(50)]},),
    )
    engine.process_user_envelope(stale)
    engine.snapshot_drift_check.assert_not_called()
    engine._hydrate_orderbook_from_ws_snapshot.assert_not_called()

    current_order = _order(100)
    current = UserStreamEnvelope(
        generation=second_generation,
        sequence_num=1,
        timestamp=None,
        events=({"type": "snapshot", "orders": [current_order]},),
    )
    engine.process_user_envelope(current)

    engine.snapshot_drift_check.assert_called_once_with(
        {current_order["client_order_id"]}, source="ws_user_snapshot"
    )
    engine._hydrate_orderbook_from_ws_snapshot.assert_called_once_with(
        [current_order]
    )
    assert engine._user_feed_phase is UserFeedPhase.LIVE


def test_dispatched_order_from_old_generation_is_dropped_after_reconnect():
    engine, first_generation, _ = _private_ingress_engine()
    stale_order = _order(1)

    second_generation = engine._begin_user_stream_generation(
        threading.Event()
    )
    assert second_generation == first_generation + 1

    engine._process_dispatched_user_order(first_generation, stale_order)

    engine.process_user_order.assert_not_called()


def test_new_generation_waits_for_running_old_generation_lifecycle():
    engine, first_generation, _ = _private_ingress_engine()
    lifecycle_started = threading.Event()
    release_lifecycle = threading.Event()

    def process_order(_order):
        lifecycle_started.set()
        assert release_lifecycle.wait(timeout=2)

    engine.process_user_order.side_effect = process_order
    lifecycle_thread = threading.Thread(
        target=engine._process_dispatched_user_order,
        args=(first_generation, _order(1)),
    )
    lifecycle_thread.start()
    assert lifecycle_started.wait(timeout=2)

    next_generation = []
    generation_thread = threading.Thread(
        target=lambda: next_generation.append(
            engine._begin_user_stream_generation(threading.Event())
        )
    )
    generation_thread.start()
    generation_thread.join(timeout=0.05)
    assert generation_thread.is_alive()

    release_lifecycle.set()
    lifecycle_thread.join(timeout=2)
    generation_thread.join(timeout=2)

    assert lifecycle_thread.is_alive() is False
    assert generation_thread.is_alive() is False
    assert next_generation == [first_generation + 1]
    engine.process_user_order.assert_called_once()


def test_waiting_for_initial_snapshot_times_out_and_requests_reconnect(
    monkeypatch,
):
    clock = [100.0]
    monkeypatch.setattr(order_engine_module, "monotonic", lambda: clock[0])
    engine, _, reconnect_event = _private_ingress_engine()

    assert engine._user_feed_phase is UserFeedPhase.AWAITING_SNAPSHOT
    assert engine._user_bootstrap_deadline_monotonic == 110.0
    clock[0] = 109.999
    assert engine._check_user_bootstrap_timeout() is False

    clock[0] = 110.0
    assert engine._check_user_bootstrap_timeout() is True
    assert engine._user_feed_phase is UserFeedPhase.DESYNCHRONIZED
    assert reconnect_event.is_set()
    assert any(
        args.args[1].get("reason") == "initial_snapshot_timeout"
        and args.args[1].get("timeout_seconds") == 10.0
        for args in engine.log_message.call_args_list
        if len(args.args) >= 2 and isinstance(args.args[1], dict)
    )


def test_unterminated_bootstrap_times_out_and_requests_reconnect(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(order_engine_module, "monotonic", lambda: clock[0])
    engine, generation, reconnect_event = _private_ingress_engine()
    first_page = [_order(index) for index in range(50)]

    engine.process_user_event(
        {"type": "snapshot", "orders": first_page},
        generation=generation,
    )

    assert engine._user_feed_phase is UserFeedPhase.BOOTSTRAPPING
    assert engine._user_bootstrap_deadline_monotonic == 110.0
    clock[0] = 109.999
    assert engine._check_user_bootstrap_timeout() is False
    assert reconnect_event.is_set() is False

    clock[0] = 110.0
    assert engine._check_user_bootstrap_timeout() is True
    assert engine._user_feed_phase is UserFeedPhase.DESYNCHRONIZED
    assert engine._user_bootstrap_orders == {}
    assert engine._user_bootstrap_deadline_monotonic is None
    assert reconnect_event.is_set()
    assert any(
        args.args[1].get("reason") == "bootstrap_timeout"
        and args.args[1].get("timeout_seconds") == 10.0
        for args in engine.log_message.call_args_list
        if len(args.args) >= 2 and isinstance(args.args[1], dict)
    )


def test_completed_bootstrap_clears_timeout_deadline(monkeypatch):
    clock = [200.0]
    monkeypatch.setattr(order_engine_module, "monotonic", lambda: clock[0])
    engine, generation, reconnect_event = _private_ingress_engine()

    engine.process_user_event(
        {"type": "snapshot", "orders": []}, generation=generation
    )

    assert engine._user_feed_phase is UserFeedPhase.LIVE
    assert engine._user_bootstrap_deadline_monotonic is None
    clock[0] = 1000.0
    assert engine._check_user_bootstrap_timeout() is False
    assert reconnect_event.is_set() is False


def test_identical_payload_is_accepted_again_in_a_new_generation():
    engine, first_generation, _ = _private_ingress_engine()
    message = _wire_user_message(
        1, [{"type": "snapshot", "orders": []}]
    )
    engine.on_user_message(message, generation=first_generation)

    second_generation = engine._begin_user_stream_generation(
        threading.Event()
    )
    engine.on_user_message(message, generation=second_generation)

    queued = engine.event_queue[ChannelType.USER.value]
    assert [queued.get_nowait().generation for _ in range(2)] == [
        first_generation,
        second_generation,
    ]


def test_auxiliary_private_envelope_retains_metadata_and_is_generation_fenced():
    engine, first_generation, _ = _private_ingress_engine()
    engine.fee_manager = Mock(name="fee_manager")
    summary = {"type": "snapshot", "fcm_balance_summary": {"balance": "1"}}
    timestamp = "2026-08-28T13:14:15.000000Z"
    engine.on_user_message(
        _wire_user_message(
            0,
            [summary],
            channel=ChannelType.FUTURES_BALANCE_SUMMARY.value,
            timestamp=timestamp,
        ),
        generation=first_generation,
    )
    queued = engine.event_queue[ChannelType.USER.value].get_nowait()

    assert queued == UserStreamEnvelope(
        generation=first_generation,
        sequence_num=0,
        timestamp=timestamp,
        events=(summary,),
        channel=ChannelType.FUTURES_BALANCE_SUMMARY.value,
    )

    engine._begin_user_stream_generation(threading.Event())
    engine.process_private_envelope(queued)
    engine.fee_manager.update_margin_window_from_summary.assert_not_called()


def test_private_channels_reduce_in_connection_sequence_order():
    engine, generation, reconnect_event = _private_ingress_engine()
    engine._worker_queue_poll_seconds = 0.01
    engine.process_user_event(
        {"type": "snapshot", "orders": []}, generation=generation
    )
    effects = []
    engine.fee_manager = Mock(name="fee_manager")
    engine.fee_manager.update_margin_window_from_summary.side_effect = (
        lambda _summary: effects.append("fee")
    )

    def process_order(_order):
        effects.append("order")
        engine._shutdown_event.set()

    engine.process_user_order.side_effect = process_order
    engine.on_user_message(
        _wire_user_message(
            1,
            [{"type": "snapshot", "fcm_balance_summary": {"balance": "1"}}],
            channel=ChannelType.FUTURES_BALANCE_SUMMARY.value,
        ),
        generation=generation,
    )
    engine.on_user_message(
        _wire_user_message(
            2,
            [{"type": "patch", "orders": [_order(1)]}],
        ),
        generation=generation,
    )
    assert engine._shutdown_event.is_set() is False
    assert engine._user_feed_phase is UserFeedPhase.LIVE
    assert engine.event_queue[ChannelType.USER.value].qsize() == 2

    worker = threading.Thread(
        target=engine.generate_process_event_worker(
            ChannelType.USER.value
        ),
    )
    worker.start()
    worker.join(timeout=2)

    assert worker.is_alive() is False
    assert effects == ["fee", "order"]
    assert reconnect_event.is_set() is False
    assert engine.event_queue[ChannelType.USER.value].unfinished_tasks == 0


def test_queued_private_envelopes_cannot_mutate_after_desynchronization():
    engine, generation, _ = _private_ingress_engine()
    engine.fee_manager = Mock(name="fee_manager")
    position_event = {
        "type": "snapshot",
        "positions": {"expiring_futures_positions": []},
    }
    balance_event = {
        "type": "snapshot",
        "fcm_balance_summary": {"balance": "1"},
    }
    engine._mark_user_stream_desynchronized(
        generation=generation,
        reason="test_desync",
    )

    engine.process_private_envelope(
        UserStreamEnvelope(
            generation=generation,
            sequence_num=1,
            timestamp=None,
            events=(position_event,),
        )
    )
    engine.process_private_envelope(
        UserStreamEnvelope(
            generation=generation,
            sequence_num=2,
            timestamp=None,
            events=(balance_event,),
            channel=ChannelType.FUTURES_BALANCE_SUMMARY.value,
        )
    )

    engine.process_user_snapshot.assert_not_called()
    engine.fee_manager.update_margin_window_from_summary.assert_not_called()


def test_generation_change_waits_for_inflight_private_envelope_reduction():
    engine, generation, _ = _private_ingress_engine()
    position_started = threading.Event()
    release_position = threading.Event()

    def process_position(_event):
        position_started.set()
        assert release_position.wait(timeout=2)

    engine.process_user_snapshot.side_effect = process_position
    envelope = UserStreamEnvelope(
        generation=generation,
        sequence_num=1,
        timestamp=None,
        events=(
            {
                "type": "snapshot",
                "positions": {"expiring_futures_positions": []},
            },
        ),
    )
    reducer_thread = threading.Thread(
        target=engine.process_private_envelope,
        args=(envelope,),
    )
    reducer_thread.start()
    assert position_started.wait(timeout=2)

    generation_started = threading.Event()

    def begin_generation():
        engine._begin_user_stream_generation(threading.Event())
        generation_started.set()

    generation_thread = threading.Thread(target=begin_generation)
    generation_thread.start()
    assert generation_started.wait(timeout=0.05) is False

    release_position.set()
    reducer_thread.join(timeout=2)
    generation_thread.join(timeout=2)
    assert reducer_thread.is_alive() is False
    assert generation_thread.is_alive() is False
    assert generation_started.is_set()


@pytest.mark.parametrize(
    ("channels", "expected_public", "expected_private", "expected_count"),
    (
        (
            ("heartbeats", "user", "ticker", "futures_balance_summary"),
            ("heartbeats", "ticker"),
            ("heartbeats", "user", "futures_balance_summary"),
            4,
        ),
        (("user",), (), ("user",), 1),
        (("ticker",), ("ticker",), (), 3),
        ((), (), (), 0),
    ),
)
def test_channel_partition_has_one_private_owner_and_configured_public_fanout(
    channels,
    expected_public,
    expected_private,
    expected_count,
):
    engine = _bare_user_engine()
    engine.subscription = type(
        "Subscription", (), {"channels": channels}
    )()
    engine.websocket_thread_maximum = 3

    assert engine._configured_public_channels() == expected_public
    assert engine._configured_private_channels() == expected_private
    assert engine._configured_websocket_connection_count() == expected_count


def test_explicit_channel_roles_are_authoritative_and_worker_union_is_derived():
    engine = _bare_user_engine()
    engine.subscription = type(
        "Subscription",
        (),
        {
            "public_channels": ("heartbeats", "ticker"),
            "private_channels": ("heartbeats", "user"),
            "channels": ("stale-legacy-value",),
        },
    )()

    assert engine._configured_public_channels() == ("heartbeats", "ticker")
    assert engine._configured_private_channels() == ("heartbeats", "user")
    assert engine._configured_event_channels() == (
        "heartbeats",
        "ticker",
        "user",
    )

    engine.subscription.public_channels = []
    engine.subscription.private_channels = []
    assert engine._configured_event_channels() == ()


def _websocket_connection_engine() -> OrderEngine:
    engine = _bare_user_engine()
    engine.subscription = type(
        "Subscription",
        (),
        {
            "channels": (
                ChannelType.HEARTBEATS.value,
                ChannelType.USER.value,
                ChannelType.TICKER.value,
                ChannelType.FUTURES_BALANCE_SUMMARY.value,
            ),
            "product_ids": ("BTC-USDC",),
        },
    )()
    engine.event_queue = {
        channel: Queue(maxsize=8) for channel in engine.subscription.channels
    }
    engine.websocket_thread_maximum = 3
    engine._shutdown_event = threading.Event()
    engine.api_key = "test-key"
    engine.api_secret = "test-secret"
    engine.on_open = Mock(name="on_open")
    engine.on_message = Mock(name="on_message")
    engine._ensure_user_stream_state()
    return engine


def test_public_connection_uses_wsclient_and_only_public_channels(monkeypatch):
    engine = _websocket_connection_engine()
    sdk_token = object()
    public_factory = Mock(name="WSClient", return_value=sdk_token)
    private_factory = Mock(name="WSUserClient")
    wrapper = Mock(name="public_wrapper")
    wrapper.sleep_with_exception_check.return_value = True
    wrapper_factory = Mock(
        name="CoinbaseWebSocketClient", return_value=wrapper
    )
    monkeypatch.setattr(order_engine_module, "WSClient", public_factory)
    monkeypatch.setattr(order_engine_module, "WSUserClient", private_factory)
    monkeypatch.setattr(
        order_engine_module, "CoinbaseWebSocketClient", wrapper_factory
    )

    engine.connect_to_websocket()

    public_factory.assert_called_once_with(
        verbose=True,
        api_key="test-key",
        api_secret="test-secret",
        on_open=engine.on_open,
        on_message=engine.on_message,
    )
    private_factory.assert_not_called()
    wrapper_factory.assert_called_once_with(sdk_token)
    wrapper.connect.assert_called_once_with()
    wrapper.subscribe.assert_called_once_with(
        products=("BTC-USDC",),
        channels=(ChannelType.HEARTBEATS.value, ChannelType.TICKER.value),
    )
    wrapper.disconnect.assert_called_once_with()


def test_private_connection_uses_one_wsuserclient_and_preserves_envelope(
    monkeypatch,
):
    engine = _websocket_connection_engine()
    captured_callbacks = {}
    sdk_token = object()

    def build_private_sdk(**kwargs):
        captured_callbacks.update(kwargs)
        return sdk_token

    private_factory = Mock(name="WSUserClient", side_effect=build_private_sdk)
    public_factory = Mock(name="WSClient")
    wrapper = Mock(name="private_wrapper")

    def connect():
        captured_callbacks["on_open"]()

    message = _wire_user_message(
        100, [{"type": "snapshot", "orders": []}]
    )

    def receive_then_exit(_duration):
        captured_callbacks["on_message"](message)
        return True

    wrapper.connect.side_effect = connect
    wrapper.sleep_with_exception_check.side_effect = receive_then_exit
    wrapper_factory = Mock(
        name="CoinbaseWebSocketClient", return_value=wrapper
    )
    monkeypatch.setattr(order_engine_module, "WSClient", public_factory)
    monkeypatch.setattr(order_engine_module, "WSUserClient", private_factory)
    monkeypatch.setattr(
        order_engine_module, "CoinbaseWebSocketClient", wrapper_factory
    )

    engine.connect_to_user_websocket()

    private_factory.assert_called_once()
    private_kwargs = private_factory.call_args.kwargs
    assert private_kwargs == {
        "verbose": True,
        "api_key": "test-key",
        "api_secret": "test-secret",
        "on_open": captured_callbacks["on_open"],
        "on_message": captured_callbacks["on_message"],
        "retry": False,
    }
    public_factory.assert_not_called()
    wrapper_factory.assert_called_once_with(sdk_token)
    wrapper.subscribe.assert_called_once_with(
        products=("BTC-USDC",),
        channels=(
            ChannelType.HEARTBEATS.value,
            ChannelType.USER.value,
            ChannelType.FUTURES_BALANCE_SUMMARY.value,
        ),
    )
    wrapper.disconnect.assert_called_once_with()
    engine.on_open.assert_called_once_with()
    assert engine._user_stream_generation == 1
    queued = engine.event_queue[ChannelType.USER.value].get_nowait()
    assert isinstance(queued, UserStreamEnvelope)
    assert (queued.generation, queued.sequence_num) == (1, 100)


def test_startup_launches_configured_public_fanout_and_one_private_owner(
    monkeypatch,
):
    engine = _websocket_connection_engine()
    engine.load_parent_child_order_ids = Mock(return_value=True)
    engine._hydrate_order_progress_tracker_from_db = Mock()
    engine._raise_if_background_startup_stopped = Mock()
    engine._publish_engine_status = Mock()
    engine._start_hotpoint_background = Mock()
    engine._commit_startup_activation = Mock(return_value=True)
    engine.fee_manager = Mock(name="fee_manager")
    started = []
    engine._start_owned_thread = Mock(
        side_effect=lambda **kwargs: started.append(kwargs)
    )
    monkeypatch.setattr(
        order_engine_module, "MARKET_TICK_RECORDER_AVAILABLE", False
    )
    monkeypatch.setattr(order_engine_module, "MARKET_METRICS_AVAILABLE", False)

    engine._start_background_threads_unlocked()

    websocket_launches = {
        item["name"]: item["target"]
        for item in started
        if item["name"].startswith("websocket_thread_")
        or item["name"] == "user_websocket_thread"
    }
    assert set(websocket_launches) == {
        "websocket_thread_0",
        "websocket_thread_1",
        "websocket_thread_2",
        "user_websocket_thread",
    }
    for index in range(3):
        target = websocket_launches[f"websocket_thread_{index}"]
        assert target.__self__ is engine
        assert target.__func__ is OrderEngine.connect_to_websocket
    private_target = websocket_launches["user_websocket_thread"]
    assert private_target.__self__ is engine
    assert private_target.__func__ is OrderEngine.connect_to_user_websocket


def test_live_envelopes_are_fifo_per_coid_but_concurrent_across_coids():
    engine, generation, _ = _private_ingress_engine()
    engine.process_user_event(
        {"type": "snapshot", "orders": []}, generation=generation
    )
    first_a_started = threading.Event()
    release_first_a = threading.Event()
    second_a_started = threading.Event()
    independent_b_started = threading.Event()
    all_done = threading.Event()
    completed = []
    completed_lock = threading.Lock()

    def process_order(order):
        marker = order["marker"]
        if marker == "first-a":
            first_a_started.set()
            assert release_first_a.wait(timeout=1.0)
        elif marker == "second-a":
            second_a_started.set()
        elif marker == "independent-b":
            independent_b_started.set()
        with completed_lock:
            completed.append(marker)
            if len(completed) == 3:
                all_done.set()

    engine.process_user_order.side_effect = process_order
    executor = ThreadPoolExecutor(max_workers=2)
    engine._user_order_dispatcher = order_engine_module._KeyedSerialDispatcher(
        executor,
        max_pending=8,
    )
    first_a = {**_order(1), "marker": "first-a"}
    second_a = {**_order(1), "marker": "second-a"}
    independent_b = {**_order(2), "marker": "independent-b"}

    try:
        engine.process_user_envelope(
            UserStreamEnvelope(
                generation=generation,
                sequence_num=1,
                timestamp=None,
                events=(
                    {"type": "patch", "orders": [first_a, independent_b]},
                ),
            )
        )
        assert first_a_started.wait(timeout=1.0)
        assert independent_b_started.wait(timeout=1.0)

        engine.process_user_envelope(
            UserStreamEnvelope(
                generation=generation,
                sequence_num=2,
                timestamp=None,
                events=({"type": "patch", "orders": [second_a]},),
            )
        )
        assert second_a_started.wait(timeout=0.05) is False

        release_first_a.set()
        assert all_done.wait(timeout=1.0)
        assert completed.index("first-a") < completed.index("second-a")
    finally:
        release_first_a.set()
        engine._user_order_dispatcher.close()
        executor.shutdown(wait=True)


def test_keyed_dispatcher_rejects_work_at_its_pending_limit():
    executor = ThreadPoolExecutor(max_workers=1)
    dispatcher = order_engine_module._KeyedSerialDispatcher(
        executor,
        max_pending=1,
    )
    started = threading.Event()
    release = threading.Event()

    def block():
        started.set()
        assert release.wait(timeout=1.0)

    try:
        first = dispatcher.submit("first", block)
        assert started.wait(timeout=1.0)
        with pytest.raises(Full, match="dispatcher is full"):
            dispatcher.submit("second", lambda: None)
        release.set()
        first.result(timeout=1.0)
    finally:
        release.set()
        dispatcher.close()
        executor.shutdown(wait=True)


@pytest.mark.parametrize("rejection", (Full("full"), RuntimeError("closed")))
def test_dispatch_admission_failure_desynchronizes_before_order_processing(
    rejection,
):
    engine, generation, reconnect_event = _private_ingress_engine()
    engine.process_user_event(
        {"type": "snapshot", "orders": []}, generation=generation
    )
    engine._user_order_dispatcher = Mock(name="user_order_dispatcher")
    engine._user_order_dispatcher.submit_many.side_effect = rejection
    order = _order(1)

    engine.process_user_envelope(
        UserStreamEnvelope(
            generation=generation,
            sequence_num=1,
            timestamp=None,
            events=({"type": "patch", "orders": [order]},),
        )
    )

    engine.process_user_order.assert_not_called()
    assert engine._user_feed_phase is UserFeedPhase.DESYNCHRONIZED
    assert reconnect_event.is_set()
    assert any(
        args.args[1].get("reason") == "user_order_dispatch_rejected"
        and args.args[1].get("client_order_ids")
        == [order["client_order_id"]]
        for args in engine.log_message.call_args_list
        if len(args.args) >= 2 and isinstance(args.args[1], dict)
    )


def test_dispatch_capacity_rejects_a_whole_multi_order_envelope_atomically():
    engine, generation, reconnect_event = _private_ingress_engine()
    engine.process_user_event(
        {"type": "snapshot", "orders": []}, generation=generation
    )
    executor = ThreadPoolExecutor(max_workers=1)
    dispatcher = order_engine_module._KeyedSerialDispatcher(
        executor,
        max_pending=1,
    )
    engine._user_order_dispatcher = dispatcher
    orders = [_order(1, status="FILLED"), _order(2, status="EXPIRED")]

    try:
        engine.process_user_envelope(
            UserStreamEnvelope(
                generation=generation,
                sequence_num=1,
                timestamp=None,
                events=({"type": "patch", "orders": orders},),
            )
        )

        engine.process_user_order.assert_not_called()
        assert engine._user_feed_phase is UserFeedPhase.DESYNCHRONIZED
        assert reconnect_event.is_set()
        assert dispatcher._pending_count == 0
    finally:
        dispatcher.close()
        executor.shutdown(wait=True)


def test_dispatch_capacity_is_atomic_across_every_event_in_one_envelope():
    engine, generation, reconnect_event = _private_ingress_engine()
    engine.process_user_event(
        {"type": "snapshot", "orders": []}, generation=generation
    )
    executor = ThreadPoolExecutor(max_workers=1)
    dispatcher = order_engine_module._KeyedSerialDispatcher(
        executor,
        max_pending=1,
    )
    engine._user_order_dispatcher = dispatcher
    first = _order(1, status="FILLED")
    second = _order(2, status="EXPIRED")

    try:
        engine.process_user_envelope(
            UserStreamEnvelope(
                generation=generation,
                sequence_num=1,
                timestamp=None,
                events=(
                    {"type": "patch", "orders": [first]},
                    {"type": "update", "orders": [second]},
                ),
            )
        )

        engine.process_user_order.assert_not_called()
        assert engine._user_feed_phase is UserFeedPhase.DESYNCHRONIZED
        assert reconnect_event.is_set()
        assert dispatcher._pending_count == 0
    finally:
        dispatcher.close()
        executor.shutdown(wait=True)
