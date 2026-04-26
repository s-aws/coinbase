"""
Test to verify product_type is correctly passed to profit validator.

Regression test for: Profit validator was receiving product_type='SPOT' 
even for FUTURE orders because it wasn't being passed to validate_order_profitability.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
from datetime import datetime
from core.stealth_order_manager import StealthOrderManager
from core.enums import OrderSide, ProductType
from configuration import safe_float


class TestProductTypeProfitabilityValidation:
    """Test that product_type is correctly passed during profitability validation."""
    
    @pytest.fixture
    def mock_dependencies(self):
        """Create mock dependencies."""
        return {
            'db_client': Mock(),
            'profit_validator': Mock(),
        }
    
    @pytest.fixture
    def stealth_manager(self, mock_dependencies):
        """Create a StealthOrderManager with mocked dependencies."""
        manager = StealthOrderManager(
            db_client=mock_dependencies['db_client'],
            profit_validator=mock_dependencies['profit_validator'],
        )
        
        # Mock the profit_validator methods
        manager.profit_validator.derive_follow_up_price_from_target = Mock(return_value=77540.0)
        manager.profit_validator.validate_order_profitability = Mock(
            return_value={
                "is_profitable": True,
                "net_profit": 17.23,
                "total_fees": 12.77
            }
        )
        
        return manager
    
    def test_anchor_reprice_passes_product_type_for_future_order(self, stealth_manager):
        """Test that _validate_anchor_reprice_profitability passes product_type=FUTURE."""
        # Arrange: Create a FUTURE order
        order = {
            'stealth_order_id': 'test-id-1',
            'product_id': 'BIP-20DEC30-CDE',  # FUTURE product
            'side': 'BUY',
            'total_size': 20.0,
            'remaining_size': 20.0,
            'target_movement': 0.002,
            'target_movement_type': 'P',
        }
        stealth_manager.in_memory_orders['test-id-1'] = order
        
        # Patch PRODUCT_METADATA
        with patch('core.stealth_order_manager.PRODUCT_METADATA', {
            'BIP-20DEC30-CDE': {
                'type': 'FUTURE',
                'contract_size': 0.01
            }
        }):
            # Act: Validate anchor repricing profitability
            is_profitable, reason = stealth_manager._validate_anchor_reprice_profitability(
                order=order,
                candidate_entry_price=77390.0
            )
        
        # Assert: Validate that validate_order_profitability was called with product_type
        stealth_manager.profit_validator.validate_order_profitability.assert_called_once()
        call_kwargs = stealth_manager.profit_validator.validate_order_profitability.call_args[1]
        
        assert call_kwargs['product_type'] == ProductType.FUTURE.value, \
            f"Expected product_type='{ProductType.FUTURE.value}', got {call_kwargs.get('product_type')}"
        assert call_kwargs['product_id'] == 'BIP-20DEC30-CDE', \
            f"Expected product_id='BIP-20DEC30-CDE', got {call_kwargs.get('product_id')}"
        assert call_kwargs['contract_size'] == 0.01, \
            f"Expected contract_size=0.01, got {call_kwargs.get('contract_size')}"
    
    def test_reveal_profitability_passes_product_type_for_future_order(self, stealth_manager):
        """Test that _validate_reveal_profitability passes product_type=FUTURE."""
        # Arrange: Create a FUTURE order
        order = {
            'stealth_order_id': 'test-id-2',
            'product_id': 'BIP-20DEC30-CDE',
            'side': 'SELL',
            'total_size': 20.0,
            'remaining_size': 20.0,
            'target_movement': 0.002,
            'target_movement_type': 'P',
            'limit_price': 77540.0,
            'reveal_pricing_policy': 'top_of_book',
            'reveal_condition_json': {},
        }
        stealth_manager.in_memory_orders['test-id-2'] = order
        
        # Create a mock RevealExecutionPlan
        from core.models import RevealExecutionPlan
        reveal_plan = RevealExecutionPlan(
            configured_limit_price=77540.0,
            submitted_limit_price=77540.0,
            reveal_pricing_policy='top_of_book',
            reveal_price_source='ticker_best_bid',
            fallback_used=False,
            market_source='ticker',
            market_bid=77540.0,
            market_ask=77545.0
        )
        
        # Patch PRODUCT_METADATA
        with patch('core.stealth_order_manager.PRODUCT_METADATA', {
            'BIP-20DEC30-CDE': {
                'type': 'FUTURE',
                'contract_size': 0.01
            }
        }):
            # Act: Validate reveal profitability
            is_profitable, reason = stealth_manager._validate_reveal_profitability(
                stealth_order_id='test-id-2',
                reveal_execution_plan=reveal_plan
            )
        
        # Assert: Validate that validate_order_profitability was called with product_type
        stealth_manager.profit_validator.validate_order_profitability.assert_called_once()
        call_kwargs = stealth_manager.profit_validator.validate_order_profitability.call_args[1]
        
        assert call_kwargs['product_type'] == ProductType.FUTURE.value, \
            f"Expected product_type='{ProductType.FUTURE.value}', got {call_kwargs.get('product_type')}"
        assert call_kwargs['product_id'] == 'BIP-20DEC30-CDE', \
            f"Expected product_id='BIP-20DEC30-CDE', got {call_kwargs.get('product_id')}"
        assert call_kwargs['contract_size'] == 0.01, \
            f"Expected contract_size=0.01, got {call_kwargs.get('contract_size')}"
    
    def test_anchor_reprice_passes_product_type_spot_for_spot_order(self, stealth_manager):
        """Test that product_type='SPOT' is passed for SPOT orders."""
        # Arrange: Create a SPOT order
        order = {
            'stealth_order_id': 'test-id-3',
            'product_id': 'BTC-USDC',  # SPOT product
            'side': 'BUY',
            'total_size': 0.5,
            'remaining_size': 0.5,
            'target_movement': 0.01,
            'target_movement_type': 'P',
        }
        stealth_manager.in_memory_orders['test-id-3'] = order
        
        # Patch PRODUCT_METADATA
        with patch('core.stealth_order_manager.PRODUCT_METADATA', {
            'BTC-USDC': {
                'type': 'SPOT',
                'quote_increment': '0.01',
            }
        }):
            # Act: Validate anchor repricing profitability
            is_profitable, reason = stealth_manager._validate_anchor_reprice_profitability(
                order=order,
                candidate_entry_price=42000.0
            )
        
        # Assert: Validate that product_type='SPOT' was passed
        stealth_manager.profit_validator.validate_order_profitability.assert_called_once()
        call_kwargs = stealth_manager.profit_validator.validate_order_profitability.call_args[1]
        
        assert call_kwargs['product_type'] == ProductType.SPOT.value, \
            f"Expected product_type='{ProductType.SPOT.value}', got {call_kwargs.get('product_type')}"
        assert call_kwargs['product_id'] == 'BTC-USDC', \
            f"Expected product_id='BTC-USDC', got {call_kwargs.get('product_id')}"
        assert call_kwargs.get('contract_size') is None, \
            f"Expected contract_size=None for SPOT, got {call_kwargs.get('contract_size')}"
    
    def test_validate_order_profitability_receives_all_product_params(self, stealth_manager):
        """Test that is_profitable receives all product-related parameters."""
        # Arrange: Setup profit validator mock to capture calls to is_profitable
        is_profitable_calls = []
        
        def mock_is_profitable(**kwargs):
            is_profitable_calls.append(kwargs)
            return {
                'is_profitable': True,
                'net_profit': 100.0,
                'gross_profit': 150.0,
                'total_fees': 50.0,
                'open_side': 'BUY',
                'close_side': 'SELL',
            }
        
        def mock_validate_order_profitability(**kwargs):
            # Call is_profitable with the parameters we received
            result = mock_is_profitable(
                filled_price=kwargs.get('parent_filled_price'),
                follow_up_price=kwargs.get('follow_up_price'),
                side=kwargs.get('parent_side'),
                order_size=kwargs.get('order_size'),
                min_profit_margin=kwargs.get('min_margin_pct', 0.0),
                product_type=kwargs.get('product_type', 'SPOT'),
                product_id=kwargs.get('product_id'),
                position_side=kwargs.get('position_side'),
                contract_size=kwargs.get('contract_size'),
            )
            result['is_valid'] = True
            return result
        
        stealth_manager.profit_validator.validate_order_profitability = mock_validate_order_profitability
        stealth_manager.profit_validator.derive_follow_up_price_from_target = Mock(return_value=77540.0)
        
        # Create FUTURE order
        order = {
            'stealth_order_id': 'test-id-4',
            'product_id': 'BIP-20DEC30-CDE',
            'side': 'BUY',
            'total_size': 20.0,
            'remaining_size': 20.0,
            'target_movement': 0.002,
            'target_movement_type': 'P',
        }
        stealth_manager.in_memory_orders['test-id-4'] = order
        
        # Patch PRODUCT_METADATA
        with patch('core.stealth_order_manager.PRODUCT_METADATA', {
            'BIP-20DEC30-CDE': {
                'type': 'FUTURE',
                'contract_size': 0.01
            }
        }):
            # Act: Validate profitability
            stealth_manager._validate_anchor_reprice_profitability(
                order=order,
                candidate_entry_price=77390.0
            )
        
        # Assert: Check that is_profitable was called with all parameters
        assert len(is_profitable_calls) == 1, f"Expected 1 call to is_profitable, got {len(is_profitable_calls)}"
        call_kwargs = is_profitable_calls[0]
        
        assert call_kwargs.get('product_type') == 'FUTURE', \
            f"Expected product_type='FUTURE', got {call_kwargs.get('product_type')}"
        assert call_kwargs.get('product_id') == 'BIP-20DEC30-CDE', \
            f"Expected product_id='BIP-20DEC30-CDE', got {call_kwargs.get('product_id')}"
        assert call_kwargs.get('contract_size') == 0.01, \
            f"Expected contract_size=0.01, got {call_kwargs.get('contract_size')}"
        assert 'side' in call_kwargs  # parent_side
        assert 'filled_price' in call_kwargs  # parent_filled_price
        assert 'follow_up_price' in call_kwargs
        assert 'order_size' in call_kwargs
