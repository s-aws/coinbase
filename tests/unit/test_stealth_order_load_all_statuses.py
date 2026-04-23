"""
Test for verifying EXECUTED orders are loaded after engine restart.

This test verifies the fix for: "ui_stealth_orders_manager.html is not displaying 
EXECUTED orders if engine is restarted"

The issue was that load_all_active_orders_from_db() only loaded HIDDEN orders,
causing EXECUTED orders to not appear in the UI after restart.
"""

import pytest
import json
from datetime import datetime
from unittest.mock import Mock, MagicMock
from core.stealth_order_manager import StealthOrderManager


class TestLoadAllStealthOrderStatuses:
    """Test that all stealth order statuses are loaded from database."""
    
    @pytest.fixture
    def mock_db_with_all_statuses(self):
        """Create a mock database with orders of all statuses."""
        class MockDBClient:
            def execute_query(self, query: str, params=None):
                """Mock query that returns orders of all statuses."""
                if "stealth_orders" in query:
                    return [
                        {
                            'stealth_order_id': 'order-hidden-1',
                            'product_id': 'BTC-USDC',
                            'side': 'BUY',
                            'total_size': 1.0,
                            'revealed_size': 0.0,
                            'remaining_size': 1.0,
                            'executed_size': 0.0,
                            'limit_price': 50000.0,
                            'status': 'HIDDEN',
                            'reveal_condition_type': 'price_threshold',
                            'reveal_condition_json': json.dumps({'type': 'price_threshold'}),
                            'sizing_strategy_json': json.dumps({}),
                            'reason': 'Test hidden order',
                            'notes': '',
                            'parent_order_id': None,
                            'revealed_orders': json.dumps([]),
                            'created_at': datetime.utcnow(),
                            'updated_at': datetime.utcnow(),
                            'visibility_score': 0.0,
                            'last_placement_at': None,
                            'condition_first_met_at': None,
                            'condition_confirmed_at': None,
                        },
                        {
                            'stealth_order_id': 'order-executed-1',
                            'product_id': 'ETH-USDC',
                            'side': 'SELL',
                            'total_size': 10.0,
                            'revealed_size': 10.0,
                            'remaining_size': 0.0,
                            'executed_size': 10.0,
                            'limit_price': 3000.0,
                            'status': 'EXECUTED',
                            'reveal_condition_type': 'price_threshold',
                            'reveal_condition_json': json.dumps({'type': 'price_threshold'}),
                            'sizing_strategy_json': json.dumps({}),
                            'reason': 'Test executed order',
                            'notes': 'This order should be visible after restart',
                            'parent_order_id': None,
                            'revealed_orders': json.dumps([
                                {
                                    'reveal_number': 1,
                                    'revealed_size': 10.0,
                                    'placement_price': 3000.0,
                                    'placed_order_id': 'placed-order-1',
                                    'reveal_time': datetime.utcnow().isoformat(),
                                    'market_price': 3100.0
                                }
                            ]),
                            'created_at': datetime.utcnow(),
                            'updated_at': datetime.utcnow(),
                            'visibility_score': 1.0,
                            'last_placement_at': datetime.utcnow(),
                            'condition_first_met_at': datetime.utcnow(),
                            'condition_confirmed_at': datetime.utcnow(),
                        },
                        {
                            'stealth_order_id': 'order-revealed-1',
                            'product_id': 'SOL-USDC',
                            'side': 'BUY',
                            'total_size': 100.0,
                            'revealed_size': 50.0,
                            'remaining_size': 50.0,
                            'executed_size': 50.0,
                            'limit_price': 150.0,
                            'status': 'REVEALED',
                            'reveal_condition_type': 'time_delay',
                            'reveal_condition_json': json.dumps({'type': 'time_delay'}),
                            'sizing_strategy_json': json.dumps({}),
                            'reason': 'Test revealed order',
                            'notes': '',
                            'parent_order_id': None,
                            'revealed_orders': json.dumps([]),
                            'created_at': datetime.utcnow(),
                            'updated_at': datetime.utcnow(),
                            'visibility_score': 0.5,
                            'last_placement_at': datetime.utcnow(),
                            'condition_first_met_at': datetime.utcnow(),
                            'condition_confirmed_at': datetime.utcnow(),
                        },
                        {
                            'stealth_order_id': 'order-cancelled-1',
                            'product_id': 'XRP-USDC',
                            'side': 'SELL',
                            'total_size': 1000.0,
                            'revealed_size': 100.0,
                            'remaining_size': 900.0,
                            'executed_size': 0.0,
                            'limit_price': 2.0,
                            'status': 'CANCELLED',
                            'reveal_condition_type': 'spread',
                            'reveal_condition_json': json.dumps({'type': 'spread'}),
                            'sizing_strategy_json': json.dumps({}),
                            'reason': 'Test cancelled order',
                            'notes': 'Cancelled before completion',
                            'parent_order_id': None,
                            'revealed_orders': json.dumps([]),
                            'created_at': datetime.utcnow(),
                            'updated_at': datetime.utcnow(),
                            'visibility_score': 0.1,
                            'last_placement_at': datetime.utcnow(),
                            'condition_first_met_at': None,
                            'condition_confirmed_at': None,
                        },
                    ]
                return []
            
            def close(self):
                pass
        
        return MockDBClient()
    
    def test_load_all_active_orders_includes_executed_orders(self, mock_db_with_all_statuses):
        """
        CRITICAL TEST: Verify that EXECUTED orders are loaded from database.
        
        This is the fix for: "ui_stealth_orders_manager.html is not displaying 
        EXECUTED orders if engine is restarted"
        """
        # Create manager with mock database
        def mock_log(level, data):
            pass
        
        manager = StealthOrderManager(mock_db_with_all_statuses, log_callback=mock_log)
        
        # Load orders from database
        loaded_count = manager.load_all_active_orders_from_db()
        
        # Verify we loaded orders
        assert loaded_count == 4, f"Expected 4 orders loaded, got {loaded_count}"
        
        # Verify EXECUTED order is in memory
        assert 'order-executed-1' in manager.in_memory_orders, \
            "EXECUTED order should be in memory after load"
        
        executed_order = manager.in_memory_orders['order-executed-1']
        assert executed_order['status'] == 'EXECUTED', \
            f"EXECUTED order status should be EXECUTED, got {executed_order['status']}"
        assert executed_order['executed_size'] == 10.0, \
            "EXECUTED order should have correct executed_size"
    
    def test_executed_orders_are_in_serializable_output(self, mock_db_with_all_statuses):
        """
        Verify that EXECUTED orders are included when getting serializable orders for UI.
        
        The UI calls stealth_manager.get_serializable_orders() which returns in_memory_orders.
        If EXECUTED orders are not in in_memory_orders, they won't show in the UI.
        """
        def mock_log(level, data):
            pass
        
        manager = StealthOrderManager(mock_db_with_all_statuses, log_callback=mock_log)
        manager.load_all_active_orders_from_db()
        
        # Get serializable orders (what the UI receives)
        serializable = manager.get_serializable_orders()
        
        # Verify EXECUTED order is in the serializable output
        assert 'order-executed-1' in serializable, \
            "EXECUTED order should be in serializable output for UI"
        
        # Verify other statuses are also present
        assert 'order-hidden-1' in serializable, "HIDDEN order should be present"
        assert 'order-revealed-1' in serializable, "REVEALED order should be present"
        assert 'order-cancelled-1' in serializable, "CANCELLED order should be present"
    
    def test_hidden_orders_reset_to_hidden_on_restart(self, mock_db_with_all_statuses):
        """
        Verify that HIDDEN and PENDING/TRIGGERED orders are reset to HIDDEN for fresh evaluation.
        
        EXECUTED, REVEALED, CANCELLED orders should keep their original status.
        """
        def mock_log(level, data):
            pass
        
        manager = StealthOrderManager(mock_db_with_all_statuses, log_callback=mock_log)
        manager.load_all_active_orders_from_db()
        
        # HIDDEN order should remain HIDDEN
        assert manager.in_memory_orders['order-hidden-1']['status'] == 'HIDDEN'
        
        # EXECUTED order should keep EXECUTED status
        assert manager.in_memory_orders['order-executed-1']['status'] == 'EXECUTED'
        
        # REVEALED order should keep REVEALED status
        assert manager.in_memory_orders['order-revealed-1']['status'] == 'REVEALED'
        
        # CANCELLED order should keep CANCELLED status
        assert manager.in_memory_orders['order-cancelled-1']['status'] == 'CANCELLED'
    
    def test_condition_timestamps_reset_only_for_re_evaluation_orders(self, mock_db_with_all_statuses):
        """
        Verify that condition_first_met_at and condition_confirmed_at are reset 
        only for orders being re-evaluated (HIDDEN/PENDING/TRIGGERED).
        
        For EXECUTED/REVEALED/CANCELLED, these timestamps should be preserved.
        """
        def mock_log(level, data):
            pass
        
        manager = StealthOrderManager(mock_db_with_all_statuses, log_callback=mock_log)
        manager.load_all_active_orders_from_db()
        
        # HIDDEN order should have reset timestamps (None)
        hidden_order = manager.in_memory_orders['order-hidden-1']
        assert hidden_order['condition_first_met_at'] is None
        assert hidden_order['condition_confirmed_at'] is None
        
        # EXECUTED order should preserve timestamps (not None)
        executed_order = manager.in_memory_orders['order-executed-1']
        assert executed_order['condition_first_met_at'] is not None
        assert executed_order['condition_confirmed_at'] is not None
        
        # REVEALED order should preserve timestamps
        revealed_order = manager.in_memory_orders['order-revealed-1']
        assert revealed_order['condition_first_met_at'] is not None
        assert revealed_order['condition_confirmed_at'] is not None
