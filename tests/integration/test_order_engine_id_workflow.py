"""Integration tests for OrderEngine ID handling and parent-child workflow."""

from unittest.mock import Mock

from configuration import OrderBook
from core.enums import FollowUpKind, OrderStatus, StealthOrderStatus
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
    return engine, orderbook


def test_handle_filled_order_uses_client_order_id_for_stealth_lookup():
    engine, _ = _build_engine()

    stealth_manager = Mock()
    stealth_manager.find_stealth_order_by_placed_order_id = Mock(return_value=None)
    engine.stealth_order_bridge = Mock(stealth_manager=stealth_manager)
    # Claim must succeed for handle_filled_order to reach the stealth lookup.
    # The lookup is the actual behavior under test (passes client_order_id, not
    # order_id); the should_replace short-circuit below stops the engine before
    # any follow-up creation runs, so no additional DB/REST mocking is needed.
    engine.claim_follow_up_processing = Mock(return_value=True)
    engine.orderbook.should_replace = {"FILLED": False, "CANCELLED": False}
    engine.fill_repo = None

    filled_order = {
        "client_order_id": "550e8400-e29b-41d4-a716-446655440000",
        "order_id": "7c4a3d3e-e8f2-4e7a-9c1d-5a6e9f2b8c1d",
        "product_id": "BTC-USDC",
        "side": "BUY",
        "status": OrderStatus.FILLED.value,
        "outstanding_hold_amount": "0",
    }

    engine.handle_filled_order(filled_order)

    stealth_manager.find_stealth_order_by_placed_order_id.assert_called_once_with(
        filled_order["client_order_id"]
    )


def test_filled_stealth_updates_execution_before_follow_up_policy_returns():
    engine, _ = _build_engine()
    stealth_order = {"stealth_order_id": "stealth-root"}
    stealth_manager = Mock()
    stealth_manager.find_stealth_order_by_placed_order_id.return_value = stealth_order
    engine.stealth_order_bridge = Mock(stealth_manager=stealth_manager)
    engine.claim_follow_up_processing = Mock(return_value=True)
    engine._register_stealth_placement_under_root = Mock()
    engine.orderbook.should_replace = {"FILLED": False, "CANCELLED": False}

    engine.handle_filled_order(
        {
            "client_order_id": "placement-1",
            "order_id": "exchange-1",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "status": OrderStatus.FILLED.value,
            "cumulative_quantity": "1.25",
        }
    )

    engine.stealth_order_bridge.update_execution.assert_called_once_with(
        stealth_order_id="stealth-root",
        executed_size=1.25,
        order_status=StealthOrderStatus.EXECUTED.value,
        placement_client_order_id="placement-1",
    )


def test_filled_stealth_releases_claim_when_execution_persistence_fails():
    engine, _ = _build_engine()
    stealth_order = {"stealth_order_id": "stealth-root"}
    stealth_manager = Mock()
    stealth_manager.find_stealth_order_by_placed_order_id.return_value = (
        stealth_order
    )
    engine.stealth_order_bridge = Mock(stealth_manager=stealth_manager)
    engine.stealth_order_bridge.update_execution.return_value = False
    engine.claim_follow_up_processing = Mock(return_value=True)
    engine.release_follow_up_processing = Mock()
    engine._register_stealth_placement_under_root = Mock()
    engine.compute_order_template = Mock()

    engine.handle_filled_order(
        {
            "client_order_id": "placement-1",
            "order_id": "exchange-1",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "status": OrderStatus.FILLED.value,
            "cumulative_quantity": "1.25",
        }
    )

    engine.release_follow_up_processing.assert_called_once_with(
        FollowUpKind.FILLED,
        "placement-1",
    )
    engine.compute_order_template.assert_not_called()


def test_process_user_order_syncs_exchange_order_id_before_fill_handling():
    engine, _ = _build_engine()

    stealth_manager = Mock()
    stealth_bridge = Mock(stealth_manager=stealth_manager)
    engine.stealth_order_bridge = stealth_bridge
    engine.handle_filled_order = Mock()

    order = {
        "client_order_id": "660e8400-e29b-41d4-a716-446655440000",
        "order_id": "exchange-abc-123",
        "product_id": "BIP-20DEC30-CDE",
        "side": "SELL",
        "status": OrderStatus.FILLED.value,
        "outstanding_hold_amount": "0",
    }

    engine.process_user_order(order)

    stealth_bridge.sync_exchange_order_id_for_placed_order.assert_called_once_with(
        order["client_order_id"],
        order["order_id"],
    )
    engine.handle_filled_order.assert_called_once()


def test_child_replacement_resolves_to_original_parent(monkeypatch):
    engine, orderbook = _build_engine()

    parent_id = "parent-111"
    first_child = "child-222"
    next_child = "child-333"

    orderbook.parent_order_ids[parent_id] = {
        "orders": [first_child],
        "target_movement": {"movement": 0.005, "type": "P"},
        "max_order_replacement": 11,
        "current_order_replacement": 1,
    }
    orderbook.child_order_ids[first_child] = parent_id

    monkeypatch.setattr(
        "database.order.increment_order_parent_replacement_count",
        lambda _parent_client_order_id: 2,
    )

    _, resolved_parent = engine.resolve_parent_client_order_id(first_child)
    engine.register_child_order(next_child, resolved_parent)

    assert resolved_parent == parent_id
    assert orderbook.child_order_ids[next_child] == parent_id
    assert next_child in orderbook.parent_order_ids[parent_id]["orders"]
