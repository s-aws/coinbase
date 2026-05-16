"""Regression: polluted non-UUID parent rows must not break reconciliation."""

from unittest.mock import Mock, patch

import pytest

from configuration import OrderBook
from core.enums import TargetMovementType
from core.order_engine import OrderEngine


def _build_engine() -> OrderEngine:
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
    db_module.get_parent_orders = Mock(return_value=[])

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
    return engine


@pytest.mark.regression
def test_snapshot_skips_stealth_child_lookup_for_non_uuid_parent_id():
    engine = _build_engine()
    polluted_parent_id = "test_order_6"
    engine.db_module.get_parent_orders.return_value = [
        {
            "id": 6,
            "client_order_id": polluted_parent_id,
            "target_movement": "0.0014",
            "target_movement_type": TargetMovementType.PERCENTAGE.value,
            "max_order_replacement": 0,
            "current_order_replacement": 0,
            "allow_partial_fills": False,
        }
    ]

    with patch("database.order.get_stealth_children_for_parent") as get_children:
        parent_order_ids, child_order_ids = engine.build_parent_child_order_ids_snapshot()

    get_children.assert_not_called()
    assert parent_order_ids[polluted_parent_id]["orders"] == []
    assert child_order_ids == {}

