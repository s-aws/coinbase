"""
Test to verify that stealth orders preserve their target_movement when revealed and filled.

This test validates the fix for the issue where stealth orders with target_movement=0.005
would calculate follow-up prices using the default target_movement instead of 0.005.
"""

import uuid
from unittest.mock import Mock, MagicMock, patch
from decimal import Decimal

from core.order_engine import OrderEngine
from core.enums import OrderStatus, OrderSide
from configuration import OrderBook


def test_stealth_revealed_order_preserves_target_movement():
    """
    Test that when a stealth order with target_movement=0.005 is revealed and fills,
    the follow-up order uses that target_movement (0.5%) instead of the default.
    """
    
    # Setup: Create mock objects
    orderbook = Mock(spec=OrderBook)
    orderbook.parent_order_ids = {}
    orderbook.child_order_ids = {}
    orderbook.order = {}
    orderbook.positions = {"FUTURE": {}}
    orderbook.should_replace = {"FILLED": True, "CANCELLED": True}
    orderbook.default_max_order_replacement = 11
    orderbook.profit_target = {"FUTURE": {"BUY": 0.0012, "SELL": 0.0012}, "SPOT": {"BUY": 0.004, "SELL": 0.004}}
    
    db_module = Mock()
    subscription = Mock()
    subscription.channels = []  # Mock subscription channels
    
    # Create OrderEngine
    engine = OrderEngine(
        orderbook=orderbook,
        db_module=db_module,
        subscription=subscription,
        api_key="test_key",
        api_secret="test_secret",
        order_post_only={"BUY": False, "SELL": False},
    )
    
    # Mock the stealth order bridge
    stealth_manager = Mock()
    stealth_bridge = Mock()
    stealth_bridge.stealth_manager = stealth_manager
    engine.stealth_order_bridge = stealth_bridge
    
    # Setup: Create a stealth order with target_movement=0.005
    stealth_order_id = str(uuid.uuid4())
    revealed_order_id = str(uuid.uuid4())
    
    stealth_order = {
        "stealth_order_id": stealth_order_id,
        "parent_order_id": None,  # Root stealth order
        "product_id": "BIP-20DEC30-CDE",
        "side": "SELL",
        "total_size": 1.0,
        "limit_price": 78300.0,
    }
    
    # Mock finding the stealth order
    stealth_manager.find_stealth_order_by_placed_order_id = Mock(return_value=stealth_order)
    
    # Mock the parent order entry in database with target_movement=0.005
    parent_order_data = {
        "id": 1,
        "client_order_id": stealth_order_id,
        "product_id": "BIP-20DEC30-CDE",
        "side": "SELL",
        "size": 1.0,
        "price": 78300.0,
        "target_movement": 0.005,  # This is the key value!
        "target_movement_type": "P",
        "max_order_replacement": 11,
        "current_order_replacement": 0,
        "status": "PENDING",
    }
    
    db_module.get_parent_order = Mock(return_value=parent_order_data)
    db_module.insert_order_parent = Mock(return_value=1)
    
    # Create the fill event
    fill_event = {
        "client_order_id": revealed_order_id,
        "order_id": str(uuid.uuid4()),  # Exchange order ID
        "product_id": "BIP-20DEC30-CDE",
        "order_side": "SELL",
        "side": "SELL",
        "price": 78300.0,
        "avg_price": 78300.0,
        "size": 1.0,
        "status": OrderStatus.FILLED.value,
        "outstanding_hold_amount": "0",
    }
    
    # Mock other dependencies
    engine.resolve_profit_target = Mock(return_value=0.0012)  # Default profit target
    engine.order_limit_price_or_avg_price = Mock(return_value=78300.0)
    engine._is_external_order = Mock(return_value=False)
    engine.normalize_product_type = Mock(return_value="FUTURE")
    engine.register_child_order = Mock()
    
    with patch('core.order_engine.resolve_order_side') as mock_resolve_side, \
         patch('core.order_engine.resolve_order_size') as mock_resolve_size, \
         patch('core.order_engine.OrderStatus') as mock_status:
        
        mock_resolve_side.return_value = "SELL"
        mock_resolve_size.return_value = 1.0
        mock_status.FILLED.value = "FILLED"
        
        # Test: Call resolve_parent_client_order_id with the stealth order target_movement
        stealth_target_movement = {
            "target_movement": 0.005,
            "target_movement_type": "P"
        }
        
        is_parent, parent_id = engine.resolve_parent_client_order_id(
            client_order_id=revealed_order_id,
            order=fill_event,
            create_parent=True,
            status=OrderStatus.FILLED.value,
            stealth_order=stealth_target_movement,
        )
        
        # Verify: Parent entry was created with correct target_movement
        assert is_parent is True
        assert parent_id == revealed_order_id
        assert revealed_order_id in orderbook.parent_order_ids
        assert orderbook.parent_order_ids[revealed_order_id]["target_movement"]["movement"] == 0.005
        assert orderbook.parent_order_ids[revealed_order_id]["target_movement"]["type"] == "P"
        
        # Verify: Database insertion was called with correct target_movement
        db_module.insert_order_parent.assert_called_once()
        call_kwargs = db_module.insert_order_parent.call_args[1]
        assert call_kwargs["target_movement"] == 0.005
        assert call_kwargs["target_movement_type"] == "P"
        
        print("âœ“ Test passed: Stealth order target_movement=0.005 was preserved correctly")


def test_process_user_order_backfills_stealth_exchange_order_id_before_hold_return():
    orderbook = Mock(spec=OrderBook)
    orderbook.parent_order_ids = {}
    orderbook.child_order_ids = {}
    orderbook.order = {}
    orderbook.positions = {"FUTURE": {}}
    orderbook.should_replace = {"FILLED": True, "CANCELLED": True}
    orderbook.default_max_order_replacement = 11
    orderbook.profit_target = {"FUTURE": {"BUY": 0.0012, "SELL": 0.0012}, "SPOT": {"BUY": 0.004, "SELL": 0.004}}

    db_module = Mock()
    subscription = Mock()
    subscription.channels = []

    engine = OrderEngine(
        orderbook=orderbook,
        db_module=db_module,
        subscription=subscription,
        api_key="test_key",
        api_secret="test_secret",
        order_post_only={"BUY": False, "SELL": False},
    )

    stealth_manager = Mock()
    stealth_bridge = Mock()
    stealth_bridge.stealth_manager = stealth_manager
    engine.stealth_order_bridge = stealth_bridge
    engine.normalize_product_type = Mock(return_value="FUTURE")

    order = {
        "client_order_id": str(uuid.uuid4()),
        "order_id": str(uuid.uuid4()),
        "product_id": "BIP-20DEC30-CDE",
        "side": "SELL",
        "status": OrderStatus.FILLED.value,
        "outstanding_hold_amount": "10.5",
    }

    engine.process_user_order(order)

    stealth_bridge.sync_exchange_order_id_for_placed_order.assert_called_once_with(
        order["client_order_id"],
        order["order_id"],
    )


def test_seed_parent_order_cache_from_db_hydrates_existing_stealth_parent():
    orderbook = Mock(spec=OrderBook)
    orderbook.parent_order_ids = {}
    orderbook.child_order_ids = {}
    orderbook.order = {}
    orderbook.positions = {"FUTURE": {}}
    orderbook.should_replace = {"FILLED": True, "CANCELLED": True}
    orderbook.default_max_order_replacement = 11
    orderbook.profit_target = {"FUTURE": {"BUY": 0.0012, "SELL": 0.0012}, "SPOT": {"BUY": 0.004, "SELL": 0.004}}

    db_module = Mock()
    db_module.get_parent_order.return_value = {
        "id": 3,
        "client_order_id": "19b099e6-ea7d-4dbf-86a1-958d74bd4616",
        "target_movement": 0.002,
        "target_movement_type": "P",
        "max_order_replacement": 11,
        "current_order_replacement": 1,
    }
    subscription = Mock()
    subscription.channels = []

    engine = OrderEngine(
        orderbook=orderbook,
        db_module=db_module,
        subscription=subscription,
        api_key="test_key",
        api_secret="test_secret",
        order_post_only={"BUY": False, "SELL": False},
    )

    hydrated = engine._seed_parent_order_cache_from_db("19b099e6-ea7d-4dbf-86a1-958d74bd4616")

    assert hydrated is True
    assert orderbook.parent_order_ids["19b099e6-ea7d-4dbf-86a1-958d74bd4616"]["parent_id"] == 3
    assert orderbook.parent_order_ids["19b099e6-ea7d-4dbf-86a1-958d74bd4616"]["target_movement"]["movement"] == 0.002
    assert orderbook.parent_order_ids["19b099e6-ea7d-4dbf-86a1-958d74bd4616"]["current_order_replacement"] == 1


if __name__ == "__main__":
    test_stealth_revealed_order_preserves_target_movement()
