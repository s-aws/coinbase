#!/usr/bin/env python3
"""
Test that stealth order revealed slices correctly trigger follow-up orders.

This test verifies the fix for the issue where stealth order slices were marked
as external orders and didn't trigger follow-ups.
"""

import sys
import os
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.order_engine import OrderEngine
from configuration import OrderBook
from core.constants import DEFAULT_MAX_ORDER_REPLACEMENT


def test_stealth_revealed_order_not_marked_external():
    """Test that stealth-revealed orders are registered in orderbook before external check."""

    # Setup
    orderbook = OrderBook()
    orderbook.should_replace = {"FILLED": True}

    # Create mock dependencies
    mock_db_module = MagicMock()
    mock_subscription = MagicMock()

    order_engine = OrderEngine(
        orderbook=orderbook,
        db_module=mock_db_module,
        subscription=mock_subscription,
        api_key="test_key",
        api_secret="test_secret",
        order_post_only=False
    )

    # Create a mock stealth order manager
    mock_stealth_manager = MagicMock()
    mock_stealth_bridge = MagicMock()
    mock_stealth_bridge.stealth_manager = mock_stealth_manager
    order_engine.stealth_order_bridge = mock_stealth_bridge

    # Setup parent order
    parent_client_order_id = str(uuid.uuid4())
    orderbook.parent_order_ids[parent_client_order_id] = {
        "orders": [],
        "target_movement": {},
        "max_order_replacement": DEFAULT_MAX_ORDER_REPLACEMENT,
        "current_order_replacement": 0,
    }

    # Setup revealed slice order
    revealed_client_order_id = str(uuid.uuid4())

    # Create mock stealth order with parent_order_id
    mock_stealth_order = {
        "stealth_order_id": str(uuid.uuid4()),
        "parent_order_id": parent_client_order_id,
        "revealed_orders": [{"placed_order_id": revealed_client_order_id}],
        "follow_up_reveal_direction": "opposite",
        "reveal_condition_json": {"type": "time_delay"},
    }

    # Mock the stealth order lookup to return our stealth order
    mock_stealth_manager.find_stealth_order_by_placed_order_id.return_value = mock_stealth_order

    # Create the fill event
    fill_order = {
        "client_order_id": revealed_client_order_id,
        "order_id": str(uuid.uuid4()),
        "product_id": "BTC-USD",
        "side": "SELL",
        "status": "FILLED",
        "price": "45000.00",
        "size": "1.0",
        "created_at": datetime.utcnow().isoformat(),
    }

    # Mock dependent methods
    order_engine.claim_follow_up_processing = MagicMock(return_value=True)
    order_engine.can_create_follow_up_order = MagicMock(return_value=(True, {}))
    order_engine.resolve_parent_target_movement = MagicMock(return_value={})
    order_engine.compute_order_template = MagicMock(return_value={
        "product_id": "BTC-USD",
        "side": "BUY",
        "order_base_size": 1.0,
        "start_price": 45000.0,
    })
    order_engine.child_order_already_exists = MagicMock(return_value=False)
    order_engine.log_message = MagicMock()
    order_engine.apply_position_update = MagicMock()
    order_engine.record_follow_up_order = MagicMock()
    order_engine.complete_follow_up_processing = MagicMock()

    # Call handle_filled_order
    order_engine.handle_filled_order(fill_order)

    # Verify: The revealed order should be registered in the orderbook
    assert revealed_client_order_id in orderbook.child_order_ids, \
        f"Revealed order {revealed_client_order_id} should be in child_order_ids"

    assert orderbook.child_order_ids[revealed_client_order_id] == parent_client_order_id, \
        f"Revealed order should be linked to parent {parent_client_order_id}"

    assert revealed_client_order_id in orderbook.parent_order_ids[parent_client_order_id]["orders"], \
        f"Revealed order should be in parent's orders list"

    # Verify: The follow-up processing should have been claimed (not marked as external)
    order_engine.claim_follow_up_processing.assert_called()

    # Verify: An external order log should NOT have been created
    for call in order_engine.log_message.call_args_list:
        if call[0][0] == "order":
            payload = call[0][1]
            assert payload.get("event") != "external_order_filled", \
                "Stealth-revealed order should NOT be logged as external"

    print("âœ… TEST PASSED: Stealth-revealed orders are correctly registered in orderbook")
    print(f"   - Revealed order {revealed_client_order_id[:8]}... registered as child")
    print(f"   - Parent order {parent_client_order_id[:8]}... has revealed slice in orders list")
    print(f"   - Follow-up processing was claimed (not marked external)")


if __name__ == "__main__":
    try:
        test_stealth_revealed_order_not_marked_external()
        print("\nâœ… All tests passed!")
        sys.exit(0)
    except AssertionError as e:
        print(f"\nâŒ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nâŒ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
