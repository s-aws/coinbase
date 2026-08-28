"""Focused contracts for OrderEngine's bounded ticker-ingress lane."""

from __future__ import annotations

import json
import threading
from queue import Queue
from types import SimpleNamespace

import core.order_engine as order_engine_module
from business.event_processor import EventProcessor
from core.enums import ChannelType, TickerPublicationDisposition
from core.order_engine import OrderEngine


def _bare_ingress_engine(*, queue_size: int) -> OrderEngine:
    engine = OrderEngine.__new__(OrderEngine)
    engine.event_queue = {
        ChannelType.TICKER.value: Queue(maxsize=queue_size),
    }
    engine.evt_bridge = SimpleNamespace(claim_event=lambda _event: True)
    engine.log_message = lambda *_args, **_kwargs: None
    engine.build_event_log_payload = (
        lambda event, **details: {"event": event, **details}
    )
    engine.include_debug_fields = lambda **fields: fields
    return engine


def _ticker_event(product_id: str, price: str) -> dict:
    return {
        "type": "update",
        "tickers": [
            {
                "product_id": product_id,
                "price": price,
                "best_bid": "0",
                "best_ask": "0",
            }
        ],
    }


def test_on_message_carries_envelope_and_local_receipt_into_ticker_queue(
    monkeypatch,
):
    engine = _bare_ingress_engine(queue_size=2)
    wire_event = _ticker_event("BTC-USD", "65000")
    message_timestamp = "2026-08-27T12:34:56.123456Z"
    clock = [42.5]
    monkeypatch.setattr(order_engine_module, "monotonic", lambda: clock[0])

    def delayed_dedup_claim(event):
        # Neither socket-specific field may alter the event identity seen by
        # fan-out websocket clients.
        assert event == wire_event
        assert order_engine_module._COINBASE_MESSAGE_TIMESTAMP_KEY not in event
        assert order_engine_module._TICKER_RECEIVED_MONOTONIC_KEY not in event
        clock[0] = 99.0
        return True

    engine.evt_bridge = SimpleNamespace(claim_event=delayed_dedup_claim)

    engine.on_message(
        json.dumps(
            {
                "channel": ChannelType.TICKER.value,
                "timestamp": message_timestamp,
                "events": [wire_event],
            }
        )
    )

    queued_event = engine.event_queue[ChannelType.TICKER.value].get_nowait()
    assert queued_event[
        order_engine_module._COINBASE_MESSAGE_TIMESTAMP_KEY
    ] == message_timestamp
    assert queued_event[
        order_engine_module._TICKER_RECEIVED_MONOTONIC_KEY
    ] == 42.5
    assert queued_event["tickers"] == wire_event["tickers"]
    assert order_engine_module._COINBASE_MESSAGE_TIMESTAMP_KEY not in wire_event


def test_ticker_dedup_collapses_same_payload_at_distinct_envelope_times():
    engine = _bare_ingress_engine(queue_size=3)
    engine.evt_bridge = EventProcessor()
    wire_event = _ticker_event("BTC-USD", "65000")

    for message_timestamp in (
        "2026-08-27T12:34:56Z",
        "2026-08-27T12:34:57Z",
    ):
        engine.on_message(
            json.dumps(
                {
                    "channel": ChannelType.TICKER.value,
                    "timestamp": message_timestamp,
                    "events": [wire_event],
                }
            )
        )

    engine.on_message(
        json.dumps(
            {
                "channel": ChannelType.TICKER.value,
                "timestamp": "2026-08-27T12:34:58Z",
                "events": [_ticker_event("BTC-USD", "65001")],
            }
        )
    )

    queued = engine.event_queue[ChannelType.TICKER.value]
    assert queued.qsize() == 2
    assert [
        queued.get_nowait()[
            order_engine_module._COINBASE_MESSAGE_TIMESTAMP_KEY
        ]
        for _ in range(2)
    ] == [
        "2026-08-27T12:34:56Z",
        "2026-08-27T12:34:58Z",
    ]


def test_ticker_dedup_still_collapses_same_envelope_fanout():
    engine = _bare_ingress_engine(queue_size=3)
    engine.evt_bridge = EventProcessor()
    barrier = threading.Barrier(3)
    errors = []

    def deliver(message_timestamp):
        try:
            barrier.wait(timeout=1)
            engine.on_message(
                json.dumps(
                    {
                        "channel": ChannelType.TICKER.value,
                        "timestamp": message_timestamp,
                        "events": [_ticker_event("BTC-USD", "65000")],
                    }
                )
            )
        except Exception as error:  # pragma: no cover - asserted below
            errors.append(error)

    threads = [
        threading.Thread(
            target=deliver,
            args=(f"2026-08-27T12:34:5{second}Z",),
        )
        for second in (6, 7)
    ]
    for thread in threads:
        thread.start()
    barrier.wait(timeout=1)
    for thread in threads:
        thread.join(timeout=1)

    assert errors == []
    assert all(not thread.is_alive() for thread in threads)
    assert engine.event_queue[ChannelType.TICKER.value].qsize() == 1


def test_full_ticker_queue_discards_backlog_with_exact_product_counts():
    engine = _bare_ingress_engine(queue_size=2)
    ticker_queue = engine.event_queue[ChannelType.TICKER.value]

    first = {
        "type": "update",
        "tickers": [
            {"product_id": "BTC-USD", "price": "1"},
            {"product_id": "ETH-USD", "price": "2"},
        ],
    }
    second = _ticker_event("BTC-USD", "3")
    newest = _ticker_event("SOL-USD", "4")
    ticker_queue.put_nowait(first)
    ticker_queue.put_nowait(second)

    discarded_count, reset_counts = (
        engine._enqueue_ticker_event_with_recovery(
            ChannelType.TICKER.value,
            newest,
        )
    )

    assert discarded_count == 2
    assert reset_counts == {"BTC-USD": 2, "ETH-USD": 1}
    assert ticker_queue.qsize() == 1
    assert ticker_queue.get_nowait() is newest
    assert newest[
        order_engine_module._TICKER_CONTINUITY_RESET_COUNTS_KEY
    ] == {"BTC-USD": 2, "ETH-USD": 1}
    assert newest["tickers"][0]["product_id"] == "SOL-USD"


def test_repeated_ticker_overflow_preserves_prior_continuity_loss_counts():
    engine = _bare_ingress_engine(queue_size=1)
    ticker_queue = engine.event_queue[ChannelType.TICKER.value]
    ticker_queue.put_nowait(_ticker_event("BTC-USD", "1"))

    first_recovery = _ticker_event("ETH-USD", "2")
    engine._enqueue_ticker_event_with_recovery(
        ChannelType.TICKER.value,
        first_recovery,
    )
    assert first_recovery[
        order_engine_module._TICKER_CONTINUITY_RESET_COUNTS_KEY
    ] == {"BTC-USD": 1}

    second_recovery = _ticker_event("SOL-USD", "3")
    discarded_count, reset_counts = (
        engine._enqueue_ticker_event_with_recovery(
            ChannelType.TICKER.value,
            second_recovery,
        )
    )

    assert discarded_count == 1
    assert reset_counts == {"BTC-USD": 1, "ETH-USD": 1}
    assert second_recovery[
        order_engine_module._TICKER_CONTINUITY_RESET_COUNTS_KEY
    ] == reset_counts
    assert ticker_queue.get_nowait() is second_recovery


def test_overflow_retains_newest_coinbase_envelope_not_latest_host_producer():
    engine = _bare_ingress_engine(queue_size=1)
    ticker_queue = engine.event_queue[ChannelType.TICKER.value]
    newer = _ticker_event("BTC-USD", "2")
    newer[order_engine_module._COINBASE_MESSAGE_TIMESTAMP_KEY] = (
        "2026-08-27T12:00:02Z"
    )
    newer[order_engine_module._TICKER_RECEIVED_MONOTONIC_KEY] = 100.0
    ticker_queue.put_nowait(newer)

    older_current = _ticker_event("ETH-USD", "1")
    older_current[order_engine_module._COINBASE_MESSAGE_TIMESTAMP_KEY] = (
        "2026-08-27T12:00:01Z"
    )
    older_current[order_engine_module._TICKER_RECEIVED_MONOTONIC_KEY] = 101.0
    discarded_count, reset_counts = (
        engine._enqueue_ticker_event_with_recovery(
            ChannelType.TICKER.value,
            older_current,
        )
    )

    assert discarded_count == 1
    assert reset_counts == {"ETH-USD": 1}
    retained = ticker_queue.get_nowait()
    assert retained is newer
    assert retained[
        order_engine_module._TICKER_CONTINUITY_RESET_COUNTS_KEY
    ] == {"ETH-USD": 1}
    assert retained[
        order_engine_module._TICKER_RECEIVED_MONOTONIC_KEY
    ] == 100.0


def test_ticker_worker_publishes_resets_before_retained_tick_and_forwards_time(
    monkeypatch,
):
    engine = OrderEngine.__new__(OrderEngine)
    engine._shutdown_event = threading.Event()
    engine._worker_queue_poll_seconds = 0.01
    engine.event_queue = {ChannelType.TICKER.value: Queue()}
    engine.ticker_lock = threading.RLock()
    engine.ticker = {}
    engine.fee_manager = None
    engine.log_message = lambda *_args, **_kwargs: None
    engine.build_event_log_payload = (
        lambda event, **details: {"event": event, **details}
    )
    engine.include_debug_fields = lambda **fields: fields

    calls = []

    class RecordingStealthBridge:
        def publish_market_continuity_reset(
            self,
            product_id,
            *,
            discarded_event_count,
            event_time,
        ):
            calls.append(
                (
                    "reset",
                    product_id,
                    discarded_event_count,
                    event_time,
                )
            )

        def publish_ticker_update(self, product_id, ticker, *, event_time):
            calls.append(("ticker", product_id, ticker, event_time))
            return TickerPublicationDisposition.ACCEPTED

        def process_due_anchor_repricing(
            self,
            product_id,
            ticker,
            *,
            event_time,
            received_monotonic,
        ):
            calls.append(
                (
                    "anchor",
                    product_id,
                    ticker,
                    event_time,
                    received_monotonic,
                )
            )
            engine._shutdown_event.set()

    engine.stealth_order_bridge = RecordingStealthBridge()

    monkeypatch.setattr(
        order_engine_module,
        "get_trading_product_id",
        lambda product_id: product_id,
    )
    monkeypatch.setattr(
        order_engine_module,
        "broadcast_ticker",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        order_engine_module,
        "record_spread_tick",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        order_engine_module,
        "_get_market_tick_recorder",
        lambda: None,
    )
    monkeypatch.setattr(order_engine_module, "MARKET_METRICS_AVAILABLE", False)
    monkeypatch.setattr(order_engine_module, "monotonic", lambda: 123.456)

    event_time = "2026-08-27T12:35:00Z"
    retained_ticker = _ticker_event("SOL-USD", "0")["tickers"][0]
    engine.event_queue[ChannelType.TICKER.value].put_nowait(
        {
            "type": "update",
            "tickers": [retained_ticker],
            order_engine_module._COINBASE_MESSAGE_TIMESTAMP_KEY: event_time,
            order_engine_module._TICKER_RECEIVED_MONOTONIC_KEY: 111.222,
            order_engine_module._TICKER_CONTINUITY_RESET_COUNTS_KEY: {
                "BTC-USD": 2,
                "ETH-USD": 1,
            },
        }
    )

    engine.generate_process_event_worker(ChannelType.TICKER.value)()

    assert calls[:2] == [
        ("reset", "BTC-USD", 2, event_time),
        ("reset", "ETH-USD", 1, event_time),
    ]
    assert calls[2] == (
        "ticker",
        "SOL-USD",
        retained_ticker,
        event_time,
    )
    assert calls[3] == (
        "anchor",
        "SOL-USD",
        retained_ticker,
        event_time,
        111.222,
    )
    assert engine.ticker["SOL-USD"] == retained_ticker
    assert engine.event_queue[ChannelType.TICKER.value].unfinished_tasks == 0


def test_ticker_worker_suppresses_only_stale_product_side_effects(monkeypatch):
    engine = OrderEngine.__new__(OrderEngine)
    engine._shutdown_event = threading.Event()
    engine._worker_queue_poll_seconds = 0.01
    engine.event_queue = {ChannelType.TICKER.value: Queue()}
    engine.ticker_lock = threading.RLock()
    previous_stale_ticker = _ticker_event("SOL-USD", "11")["tickers"][0]
    engine.ticker = {"SOL-USD": previous_stale_ticker}
    engine.log_message = lambda *_args, **_kwargs: None
    engine.build_event_log_payload = (
        lambda event, **details: {"event": event, **details}
    )
    engine.include_debug_fields = lambda **fields: fields

    side_effects = []

    class RecordingStealthBridge:
        def publish_ticker_update(self, product_id, ticker, *, event_time):
            side_effects.append(("publish", product_id, ticker, event_time))
            if product_id == "SOL-USD":
                return TickerPublicationDisposition.STALE_INVALIDATION
            return TickerPublicationDisposition.ACCEPTED

        def process_due_anchor_repricing(
            self,
            product_id,
            ticker,
            *,
            event_time,
            received_monotonic,
        ):
            side_effects.append(
                (
                    "anchor",
                    product_id,
                    ticker,
                    event_time,
                    received_monotonic,
                )
            )
            engine._shutdown_event.set()

    class RecordingTickRecorder:
        def record(self, **kwargs):
            side_effects.append(("record", kwargs))

    class RecordingMetricsTracker:
        def record(self, **kwargs):
            side_effects.append(("metrics", kwargs))

    engine.stealth_order_bridge = RecordingStealthBridge()
    engine.fee_manager = SimpleNamespace(
        update_volume_signal=lambda *args, **_kwargs: side_effects.append(
            ("fee", args)
        )
    )

    monkeypatch.setattr(
        order_engine_module,
        "get_trading_product_id",
        lambda product_id: product_id,
    )
    monkeypatch.setattr(
        order_engine_module,
        "broadcast_ticker",
        lambda *args, **kwargs: side_effects.append(
            ("dashboard", args, kwargs)
        ),
    )
    monkeypatch.setattr(
        order_engine_module,
        "record_spread_tick",
        lambda *args, **_kwargs: side_effects.append(("spread", args)),
    )
    monkeypatch.setattr(
        order_engine_module,
        "_get_market_tick_recorder",
        lambda: RecordingTickRecorder(),
    )
    monkeypatch.setattr(order_engine_module, "MARKET_METRICS_AVAILABLE", True)
    monkeypatch.setattr(
        order_engine_module,
        "_get_market_metrics_tracker",
        lambda: RecordingMetricsTracker(),
    )

    stale_ticker = {
        "product_id": "SOL-USD",
        "price": "10",
        "best_bid": "9",
        "best_ask": "11",
        "volume_24_h": "1440",
    }
    accepted_ticker = {
        "product_id": "ETH-USD",
        "price": "20",
        "best_bid": "19",
        "best_ask": "21",
        "volume_24_h": "2880",
    }
    event_time = "2026-08-27T12:34:56Z"
    engine.event_queue[ChannelType.TICKER.value].put_nowait(
        {
            "type": "update",
            "tickers": [stale_ticker, accepted_ticker],
            order_engine_module._COINBASE_MESSAGE_TIMESTAMP_KEY: event_time,
            order_engine_module._TICKER_RECEIVED_MONOTONIC_KEY: 111.222,
        }
    )

    engine.generate_process_event_worker(ChannelType.TICKER.value)()

    assert side_effects == [
        ("publish", "SOL-USD", stale_ticker, event_time),
        ("publish", "ETH-USD", accepted_ticker, event_time),
        ("dashboard", ("ETH-USD", 20.0), {"cb_time": event_time}),
        ("spread", ("ETH-USD", 19.0, 21.0)),
        (
            "record",
            {
                "product_id": "ETH-USD",
                "price": 20.0,
                "best_bid": 19.0,
                "best_ask": 21.0,
            },
        ),
        ("metrics", {"product_id": "ETH-USD", "price": 20.0}),
        ("fee", ("ETH-USD", 2880.0)),
        (
            "anchor",
            "ETH-USD",
            accepted_ticker,
            event_time,
            111.222,
        ),
    ]
    assert engine.ticker["SOL-USD"] is previous_stale_ticker
    assert engine.ticker["ETH-USD"] is accepted_ticker
    assert engine.event_queue[ChannelType.TICKER.value].unfinished_tasks == 0
