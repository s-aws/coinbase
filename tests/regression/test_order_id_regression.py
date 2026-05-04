"""Regression guards for critical order ID and hierarchy behavior."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from configuration import OrderBook
from core.enums import OrderStatus
from core.order_engine import OrderEngine
from core.stealth_order_manager import StealthOrderManager


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

    db_module = Mock()
    db_module.insert_order_parent = Mock(return_value=1)

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
    return engine


@pytest.mark.regression
def test_websocket_user_message_example_contains_both_distinct_order_ids(project_root):
    """Contract: user messages provide both client_order_id and exchange order_id."""
    file_path = Path(project_root) / "websocket_reference" / "authenticated" / "user_message.json"
    payload = json.loads(file_path.read_text(encoding="utf-8"))

    order = payload["example"]["events"][0]["orders"][0]
    assert order["client_order_id"]
    assert order["order_id"]
    assert order["client_order_id"] != order["order_id"]


@pytest.mark.regression
def test_filled_order_lookup_uses_client_order_id_not_exchange_order_id():
    """Regression: stealth lookup must key off client_order_id during FILLED handling."""
    engine = _build_engine()

    stealth_manager = Mock()
    stealth_manager.find_stealth_order_by_placed_order_id = Mock(return_value=None)
    engine.stealth_order_bridge = Mock(stealth_manager=stealth_manager)
    # Claim must succeed so handle_filled_order proceeds past the early-return
    # guard and actually performs the stealth lookup we want to verify.
    engine.claim_follow_up_processing = Mock(return_value=True)
    engine.fill_repo = None
    # Disable follow-up replacement so handle_filled_order returns after the
    # stealth lookup without exercising the unrelated profit-target / DB paths
    # (which aren't meaningfully mockable on a spec'd OrderBook).
    engine.orderbook.should_replace = {"FILLED": False, "CANCELLED": False}

    filled_order = {
        "client_order_id": "client-order-001",
        "order_id": "exchange-order-001",
        "product_id": "BTC-USDC",
        "side": "BUY",
        "status": OrderStatus.FILLED.value,
        "outstanding_hold_amount": "0",
    }

    engine.handle_filled_order(filled_order)

    stealth_manager.find_stealth_order_by_placed_order_id.assert_called_once_with("client-order-001")


@pytest.mark.regression
def test_follow_up_stealth_order_keeps_flat_parent_hierarchy():
    """Regression: follow-up children remain attached to original root parent."""
    manager = StealthOrderManager(db_client=None)

    root_parent_id = "root-parent-aaa"
    filled_child_id = "filled-child-bbb"
    manager.in_memory_orders[filled_child_id] = {
        "stealth_order_id": filled_child_id,
        "product_id": "BTC-USDC",
        "side": "SELL",
        "total_size": 1.0,
        "limit_price": 50000.0,
        "reveal_condition_json": {"type": "time_delay", "delay_seconds": 0},
        "sizing_strategy_json": {"type": "fixed"},
        "reveal_pricing_policy": "configured_limit",
        "follow_up_reveal_direction": "opposite",
        "parent_order_id": root_parent_id,
    }

    create_stealth_order_mock = Mock(return_value="new-follow-up-ccc")
    manager.create_stealth_order = create_stealth_order_mock

    manager.create_follow_up_stealth_order(
        original_stealth_order_id=filled_child_id,
        side="BUY",
        total_size=1.0,
        limit_price=49950.0,
    )

    create_stealth_order_mock.assert_called_once()
    assert create_stealth_order_mock.call_args.kwargs["parent_order_id"] == root_parent_id
