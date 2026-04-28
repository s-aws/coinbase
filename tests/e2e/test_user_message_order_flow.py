"""E2E-style tests for user message order flow and ID semantics."""

import json
from pathlib import Path
from unittest.mock import Mock

from configuration import OrderBook
from core.order_engine import OrderEngine


def _build_engine():
    orderbook = Mock(spec=OrderBook)
    orderbook.parent_order_ids = {}
    orderbook.child_order_ids = {}
    orderbook.order = {}
    orderbook.positions = {"FUTURE": {}}
    orderbook.should_replace = {"FILLED": True, "CANCELLED": True}
    orderbook.default_max_order_replacement = 11
    orderbook.profit_target = {
        "FUTURE": {"BUY": 0.0012, "SELL": 0.0012},
        "SPOT": {"BUY": 0.004, "SELL": 0.004},
    }
    orderbook.get_position_side = Mock(return_value=None)

    db_helper = Mock()
    db_helper.insert_order_parent = Mock(return_value=1)

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
    return engine


def test_user_event_flow_uses_client_order_id_for_stealth_correlation(project_root):
    """Process real-like user payload through engine entrypoint and enforce ID semantics."""
    engine = _build_engine()

    reference_path = Path(project_root) / "websocket_reference" / "authenticated" / "user_message.json"
    payload = json.loads(reference_path.read_text(encoding="utf-8"))
    sample_order = payload["example"]["events"][0]["orders"][0].copy()
    sample_order["status"] = "FILLED"
    sample_order["outstanding_hold_amount"] = "0"

    stealth_manager = Mock()
    stealth_manager.find_stealth_order_by_placed_order_id = Mock(return_value=None)
    stealth_manager.sync_exchange_order_id_for_placed_order = Mock()
    engine.stealth_order_bridge = Mock(stealth_manager=stealth_manager)

    # Claim must succeed for handle_filled_order to reach the stealth lookup.
    # Disabling should_replace stops execution after the lookup so we don't need
    # to mock the entire follow-up chain.
    engine.claim_follow_up_processing = Mock(return_value=True)
    engine.orderbook.should_replace = {"FILLED": False, "CANCELLED": False}
    engine.fill_repo = None

    engine.process_user_event({"type": "filled", "orders": [sample_order]})

    stealth_manager.sync_exchange_order_id_for_placed_order.assert_called_once_with(
        sample_order["client_order_id"],
        sample_order["order_id"],
    )
    stealth_manager.find_stealth_order_by_placed_order_id.assert_called_once_with(
        sample_order["client_order_id"]
    )
