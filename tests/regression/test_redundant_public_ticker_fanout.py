"""Regression guard for redundant public websocket ticker fan-out."""

import json
from queue import Queue

from business.event_processor import EventProcessor
from core.enums import ChannelType
from core.order_engine import OrderEngine


def test_replica_timestamps_do_not_defeat_payload_dedup() -> None:
    engine = OrderEngine.__new__(OrderEngine)
    engine.event_queue = {ChannelType.TICKER.value: Queue(maxsize=3)}
    engine.evt_bridge = EventProcessor()
    engine.log_message = lambda *_args, **_kwargs: None
    engine.build_event_log_payload = (
        lambda event, **details: {"event": event, **details}
    )
    engine.include_debug_fields = lambda **fields: fields
    ticker_event = {
        "type": "update",
        "tickers": [
            {
                "product_id": "BTC-USD",
                "price": "65000",
                "best_bid": "64999",
                "best_ask": "65001",
            }
        ],
    }

    for message_timestamp in (
        "2026-08-27T12:34:56.001Z",
        "2026-08-27T12:34:56.003Z",
    ):
        engine.on_message(
            json.dumps(
                {
                    "channel": ChannelType.TICKER.value,
                    "timestamp": message_timestamp,
                    "events": [ticker_event],
                }
            )
        )

    assert engine.event_queue[ChannelType.TICKER.value].qsize() == 1
