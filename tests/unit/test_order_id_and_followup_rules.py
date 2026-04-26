"""Unit tests for order ID contracts and stealth follow-up invariants."""

from unittest.mock import Mock

from core.stealth_order_manager import StealthOrderManager


def test_find_stealth_order_by_placed_order_id_uses_client_order_id_index():
    """Lookup must be keyed by client_order_id, not exchange order_id."""
    manager = StealthOrderManager(db_client=None)

    client_order_id = "550e8400-e29b-41d4-a716-446655440000"
    exchange_order_id = "7c4a3d3e-e8f2-4e7a-9c1d-5a6e9f2b8c1d"
    tracked_order = {"stealth_order_id": client_order_id}

    manager._placed_order_index[client_order_id] = tracked_order

    assert manager.find_stealth_order_by_placed_order_id(client_order_id) is tracked_order
    assert manager.find_stealth_order_by_placed_order_id(exchange_order_id) is None


def test_sync_exchange_order_id_does_not_overwrite_existing_audit_id():
    """Audit exchange_order_id is write-once per reveal event."""
    manager = StealthOrderManager(db_client=None)

    client_order_id = "660e8400-e29b-41d4-a716-446655440000"
    manager.in_memory_orders[client_order_id] = {
        "stealth_order_id": client_order_id,
        "revealed_orders": [
            {
                "placed_order_id": client_order_id,
                "exchange_order_id": "exchange-original-001",
            }
        ],
    }
    manager._placed_order_index[client_order_id] = manager.in_memory_orders[client_order_id]

    updated = manager.sync_exchange_order_id_for_placed_order(
        placed_order_id=client_order_id,
        exchange_order_id="exchange-new-002",
    )

    assert updated is False
    assert (
        manager.in_memory_orders[client_order_id]["revealed_orders"][0]["exchange_order_id"]
        == "exchange-original-001"
    )


def test_create_follow_up_uses_root_parent_and_inherits_pricing_policy():
    """Follow-up children must stay linked to original parent and inherit pricing policy."""
    manager = StealthOrderManager(db_client=None)

    original_stealth_order_id = "770e8400-e29b-41d4-a716-446655440000"
    root_parent_id = "880e8400-e29b-41d4-a716-446655440000"
    manager.in_memory_orders[original_stealth_order_id] = {
        "stealth_order_id": original_stealth_order_id,
        "product_id": "BTC-USDC",
        "side": "SELL",
        "total_size": 1.0,
        "limit_price": 50000.0,
        "reveal_condition_json": {"type": "time_delay", "delay_seconds": 0},
        "sizing_strategy_json": {"type": "fixed"},
        "reveal_pricing_policy": "top_of_book",
        "follow_up_reveal_direction": "opposite",
        "parent_order_id": root_parent_id,
        "target_movement": 0.004,
        "target_movement_type": "P",
    }

    create_stealth_order_mock = Mock(return_value="990e8400-e29b-41d4-a716-446655440000")
    manager.create_stealth_order = create_stealth_order_mock

    follow_up_id = manager.create_follow_up_stealth_order(
        original_stealth_order_id=original_stealth_order_id,
        side="BUY",
        total_size=1.0,
        limit_price=49800.0,
    )

    assert follow_up_id == "990e8400-e29b-41d4-a716-446655440000"
    create_stealth_order_mock.assert_called_once()
    call_kwargs = create_stealth_order_mock.call_args.kwargs
    assert call_kwargs["parent_order_id"] == root_parent_id
    assert call_kwargs["reveal_pricing_policy"] == "top_of_book"
