"""Integration tests for OrderEngine ID handling and parent-child workflow."""

from unittest.mock import Mock

from configuration import OrderBook
from core.enums import OrderStatus
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


def test_process_user_order_syncs_exchange_order_id_before_fill_handling():
    engine, _ = _build_engine()

    stealth_manager = Mock()
    engine.stealth_order_bridge = Mock(stealth_manager=stealth_manager)
    engine.handle_filled_order = Mock()
    engine._validate_user_order_portfolio_scope = Mock(return_value=True)

    order = {
        "client_order_id": "660e8400-e29b-41d4-a716-446655440000",
        "order_id": "exchange-abc-123",
        "product_id": "BIP-20DEC30-CDE",
        "side": "SELL",
        "status": OrderStatus.FILLED.value,
        "outstanding_hold_amount": "0",
    }

    engine.process_user_order(order)

    stealth_manager.sync_exchange_order_id_for_placed_order.assert_called_once_with(
        order["client_order_id"],
        order["order_id"],
    )
    engine.handle_filled_order.assert_called_once()


def test_goal6_websocket_order_is_value_blind_outside_protected_anchor():
    engine, orderbook = _build_engine()
    goal6_order = {
        "reveal_condition_json": {
            "operator_manual_reveal_required": True,
        }
    }
    stealth_manager = Mock()
    stealth_manager.find_stealth_order_by_placed_order_id = Mock(
        return_value=goal6_order
    )
    engine.stealth_order_bridge = Mock(stealth_manager=stealth_manager)
    engine.handle_filled_order = Mock()
    engine._validate_user_order_portfolio_scope = Mock(return_value=True)
    engine.websocket_hooks.call_pre_order_status = Mock()
    engine.websocket_hooks.call_post_order_status = Mock()
    order = {
        "client_order_id": "660e8400-e29b-41d4-a716-446655440001",
        "order_id": "private-exchange-order-id",
        "product_id": "BTC-USDC",
        "side": "BUY",
        "status": OrderStatus.FILLED.value,
        "outstanding_hold_amount": "0",
    }

    engine.process_user_order(order)

    stealth_manager.sync_exchange_order_id_for_placed_order.assert_called_once_with(
        order["client_order_id"],
        order["order_id"],
    )
    pre_order = engine.websocket_hooks.call_pre_order_status.call_args.args[1]
    post_order = engine.websocket_hooks.call_post_order_status.call_args.args[1]
    handled_order = engine.handle_filled_order.call_args.args[0]
    assert "order_id" not in pre_order
    assert "order_id" not in post_order
    assert "order_id" not in handled_order
    assert "order_id" not in orderbook.order.get(
        order["client_order_id"],
        {},
    )


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
