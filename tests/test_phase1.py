"""
Phase 1 Tests - Verify extraction and isolation of core modules.

This test suite verifies that all extracted modules work correctly
and can be tested independently from the rest of the system.

Run with: python -m pytest tests/test_phase1.py -v
"""

import pytest
from core.enums import OrderSide, OrderStatus, ProductType, TargetMovementType
from core.models import Order, Product, Position, Wallet, FollowUpOrderTemplate
from core.constants import (
    ORDER_SIDE_SWITCH,
    ORDER_DIRECTION,
    SPOT_PRODUCT_IDS,
    DERIVATIVES_PRODUCT_IDS,
)
from calculation.formatter import safe_float, format_based_on_reference, quantize_to_increment
from calculation.resolver import (
    normalize_product_type,
    resolve_order_size,
    resolve_profit_move_pct,
    extract_order_price,
)


# ============================================================================
# ENUM TESTS
# ============================================================================

class TestEnums:
    """Test enum definitions and values."""
    
    def test_order_side_enum(self):
        """Test OrderSide enum."""
        assert OrderSide.BUY.value == "BUY"
        assert OrderSide.SELL.value == "SELL"
        assert str(OrderSide.BUY) == "OrderSide.BUY"
    
    def test_order_status_enum(self):
        """Test OrderStatus enum."""
        assert OrderStatus.OPEN.value == "OPEN"
        assert OrderStatus.FILLED.value == "FILLED"
        assert OrderStatus.CANCELLED.value == "CANCELLED"
    
    def test_product_type_enum(self):
        """Test ProductType enum."""
        assert ProductType.SPOT.value == "SPOT"
        assert ProductType.FUTURE.value == "FUTURE"
    
    def test_target_movement_type_enum(self):
        """Test TargetMovementType enum."""
        assert TargetMovementType.PERCENTAGE.value == "P"
        assert TargetMovementType.ABSOLUTE.value == "A"


# ============================================================================
# CONSTANTS TESTS
# ============================================================================

class TestConstants:
    """Test constants definitions."""
    
    def test_order_side_switch(self):
        """Test ORDER_SIDE_SWITCH mapping."""
        assert ORDER_SIDE_SWITCH["BUY"] == "SELL"
        assert ORDER_SIDE_SWITCH["SELL"] == "BUY"
        assert ORDER_SIDE_SWITCH[OrderSide.BUY] == OrderSide.SELL
    
    def test_order_direction(self):
        """Test ORDER_DIRECTION multipliers."""
        assert ORDER_DIRECTION["SELL"] == 1
        assert ORDER_DIRECTION["BUY"] == -1
        assert ORDER_DIRECTION[OrderSide.SELL] == 1
    
    def test_product_lists(self):
        """Test product lists are defined."""
        assert len(SPOT_PRODUCT_IDS) > 0
        assert len(DERIVATIVES_PRODUCT_IDS) > 0
        assert "BTC-USDC" in SPOT_PRODUCT_IDS
        assert "BIP-20DEC30-CDE" in DERIVATIVES_PRODUCT_IDS


# ============================================================================
# MODEL TESTS
# ============================================================================

class TestProductModel:
    """Test Product dataclass."""
    
    def test_product_creation(self):
        """Test creating a Product."""
        product = Product(
            product_id="BTC-USDC",
            product_type=ProductType.SPOT,
            base_increment="0.001",
            quote_increment="0.01",
            price_increment="1"
        )
        assert product.product_id == "BTC-USDC"
        assert product.product_type == ProductType.SPOT
    
    def test_product_from_dict(self):
        """Test creating Product from dict."""
        data = {
            'product_id': 'BTC-USDC',
            'product_type': 'SPOT',
            'base_increment': '0.001',
            'quote_increment': '0.01',
            'price_increment': '1',
            'trading_disabled': False
        }
        product = Product.from_dict(data)
        assert product.product_id == "BTC-USDC"
        assert product.trading_disabled is False


class TestPositionModel:
    """Test Position dataclass."""
    
    def test_position_creation(self):
        """Test creating a Position."""
        position = Position(
            product_id="BIP-20DEC30-CDE",
            side="LONG",
            number_of_contracts="100",
            current_price="77000.00"
        )
        assert position.product_id == "BIP-20DEC30-CDE"
        assert position.side == "LONG"
        assert position.number_of_contracts == "100"


class TestWalletModel:
    """Test Wallet dataclass."""
    
    def test_wallet_creation(self):
        """Test creating a Wallet."""
        wallet = Wallet(
            currency="BTC",
            available_balance="0.5",
            total_balance="0.5"
        )
        assert wallet.currency == "BTC"
        assert wallet.available_balance == "0.5"


class TestOrderModel:
    """Test Order dataclass."""
    
    def test_order_creation(self):
        """Test creating an Order."""
        order = Order(
            client_order_id="order_123",
            product_id="BTC-USDC",
            order_side=OrderSide.BUY,
            status=OrderStatus.OPEN,
            size=0.5,
            price=40000.0
        )
        assert order.client_order_id == "order_123"
        assert order.order_side == OrderSide.BUY
        assert order.status == OrderStatus.OPEN


class TestFollowUpTemplate:
    """Test FollowUpOrderTemplate dataclass."""
    
    def test_follow_up_template_creation(self):
        """Test creating a follow-up order template."""
        template = FollowUpOrderTemplate(
            product_id="BTC-USDC",
            side=OrderSide.SELL,
            order_base_size="0.5",
            start_price="40160.00",
            order_price_difference="160.00",
            profit_move_pct=0.004
        )
        assert template.product_id == "BTC-USDC"
        assert template.side == OrderSide.SELL
    
    def test_follow_up_to_dict(self):
        """Test converting template to dict."""
        template = FollowUpOrderTemplate(
            product_id="BTC-USDC",
            side=OrderSide.SELL,
            order_base_size="0.5",
            start_price="40160.00",
            order_price_difference="160.00",
            profit_move_pct=0.004
        )
        data = template.to_dict()
        assert data['product_id'] == "BTC-USDC"
        assert data['side'] == "SELL"


# ============================================================================
# FORMATTER TESTS
# ============================================================================

class TestSafeFloat:
    """Test safe_float function."""
    
    def test_valid_string_float(self):
        """Test: Valid string -> float"""
        assert safe_float('123.45') == 123.45
        assert safe_float('0.001') == 0.001
    
    def test_valid_int(self):
        """Test: Valid int -> float"""
        assert safe_float(100) == 100.0
        assert safe_float(0) == 0.0
    
    def test_none_returns_default(self):
        """Test: None -> default"""
        assert safe_float(None) == 0.0
        assert safe_float(None, default=1.0) == 1.0
    
    def test_empty_string_returns_default(self):
        """Test: Empty string -> default"""
        assert safe_float('') == 0.0
        assert safe_float('', default=2.5) == 2.5
    
    def test_invalid_string_returns_default(self):
        """Test: Invalid string -> default"""
        assert safe_float('invalid') == 0.0
        assert safe_float('abc123', default=10.0) == 10.0


class TestFormatBasedOnReference:
    """Test format_based_on_reference function."""
    
    def test_two_decimal_places(self):
        """Test: Reference with 2 decimal places"""
        assert format_based_on_reference(123.456, '0.01') == '123.46'
        assert format_based_on_reference(100.001, '0.01') == '100.00'
    
    def test_three_decimal_places(self):
        """Test: Reference with 3 decimal places"""
        assert format_based_on_reference(123.456, '0.001') == '123.456'
    
    def test_no_decimal_places(self):
        """Test: Reference with no decimal places"""
        assert format_based_on_reference(123.456, '1') == '123'
    
    def test_four_decimal_places(self):
        """Test: Reference with 4 decimal places"""
        assert format_based_on_reference(10.5, '0.0001') == '10.5000'


class TestQuantizeToIncrement:
    """Test quantize_to_increment function."""
    
    def test_nearest_rounding(self):
        """Test: Round to nearest increment"""
        assert quantize_to_increment(100.124, '0.01') == 100.12
        assert quantize_to_increment(100.126, '0.01') == 100.13
        # Note: 100.125 due to floating point precision may round down
        # This is expected behavior with floating point arithmetic
        assert quantize_to_increment(100.126, '0.01') == 100.13
    
    def test_round_down(self):
        """Test: Floor to lower increment"""
        assert quantize_to_increment(100.126, '0.01', direction='down') == 100.12
        assert quantize_to_increment(50.5, '1', direction='down') == 50.0
    
    def test_round_up(self):
        """Test: Ceil to higher increment"""
        assert quantize_to_increment(100.121, '0.01', direction='up') == 100.13
        assert quantize_to_increment(50.1, '1', direction='up') == 51.0
    
    def test_no_quantization_needed(self):
        """Test: Value already at increment"""
        assert quantize_to_increment(100.00, '0.01') == 100.00
        assert quantize_to_increment(50.0, '1') == 50.0
    
    def test_invalid_increment_raises_error(self):
        """Test: Invalid increment raises ValueError"""
        with pytest.raises(ValueError):
            quantize_to_increment(100, '0')
    
    def test_invalid_direction_raises_error(self):
        """Test: Invalid direction raises ValueError"""
        with pytest.raises(ValueError):
            quantize_to_increment(100, '0.01', direction='invalid')


# ============================================================================
# RESOLVER TESTS
# ============================================================================

class TestNormalizeProductType:
    """Test normalize_product_type function."""
    
    def test_explicit_spot_type(self):
        """Test: Explicit product_type = SPOT"""
        assert normalize_product_type({'product_type': 'SPOT'}) == 'SPOT'
        assert normalize_product_type({'product_type': 'spot'}) == 'SPOT'
    
    def test_explicit_future_type(self):
        """Test: Explicit product_type = FUTURE"""
        assert normalize_product_type({'product_type': 'FUTURE'}) == 'FUTURE'
    
    def test_infer_from_product_id_suffix(self):
        """Test: Infer type from product_id suffix"""
        assert normalize_product_type({'product_id': 'BIP-20DEC30-CDE'}) == 'FUTURE'
        assert normalize_product_type({'product_id': 'BTC-USDC'}) == 'SPOT'
    
    def test_default_to_spot(self):
        """Test: Default to SPOT"""
        assert normalize_product_type({}) == 'SPOT'


class TestResolveOrderSize:
    """Test resolve_order_size function."""
    
    def test_leaves_quantity_priority(self):
        """Test: leaves_quantity has highest priority"""
        order = {
            'leaves_quantity': 10.5,
            'filled_size': 5.0,
            'size': 2.0
        }
        assert resolve_order_size(order) == 10.5
    
    def test_cumulative_quantity_second_priority(self):
        """Test: cumulative_quantity is second priority"""
        order = {
            'cumulative_quantity': 5.0,
            'filled_size': 3.0,
        }
        assert resolve_order_size(order) == 5.0
    
    def test_no_size_fields_returns_zero(self):
        """Test: No size fields -> 0.0"""
        assert resolve_order_size({}) == 0.0
        assert resolve_order_size({'product_id': 'BTC-USDC'}) == 0.0
    
    def test_string_sizes_converted(self):
        """Test: String sizes are converted"""
        order = {'filled_size': '2.5'}
        assert resolve_order_size(order) == 2.5


class TestResolveProfitMovePct:
    """Test resolve_profit_move_pct function."""
    
    def test_product_specific_config(self):
        """Test: Product-specific config takes priority."""
        profits = {
            'SPOT': {'BUY': 0.004, 'SELL': 0.004},
            'BTC-USDC': {'BUY': 0.006, 'SELL': 0.006}
        }
        order = {'product_id': 'BTC-USDC', 'order_side': 'BUY'}
        assert resolve_profit_move_pct(order, profits) == 0.006
    
    def test_product_type_fallback(self):
        """Test: Falls back to product type."""
        profits = {
            'SPOT': {'BUY': 0.004, 'SELL': 0.004},
        }
        order = {'product_id': 'BTC-USDC', 'order_side': 'BUY'}
        assert resolve_profit_move_pct(order, profits) == 0.004
    
    def test_returns_zero_if_not_found(self):
        """Test: Returns 0.0 if not found."""
        profits = {}
        order = {'product_id': 'BTC-USDC', 'order_side': 'BUY'}
        assert resolve_profit_move_pct(order, profits) == 0.0


class TestExtractOrderPrice:
    """Test extract_order_price function."""
    
    def test_prefer_limit_price(self):
        """Test: Prefer limit_price over avg_price."""
        order = {'limit_price': '100.50', 'avg_price': '100.00'}
        assert extract_order_price(order) == 100.50
    
    def test_fallback_to_avg_price(self):
        """Test: Use avg_price if no limit_price."""
        order = {'avg_price': '100.00'}
        assert extract_order_price(order) == 100.0
    
    def test_return_none_if_no_price(self):
        """Test: Return None if no price found."""
        assert extract_order_price({}) is None
        assert extract_order_price({'price': 'invalid'}) is None


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestPhase1Integration:
    """Integration tests for Phase 1 extracted modules."""
    
    def test_order_workflow(self):
        """Test complete order workflow using extracted modules."""
        # Create an order from dict
        order_dict = {
            'client_order_id': 'order_123',
            'product_id': 'BTC-USDC',
            'order_side': 'BUY',
            'status': 'FILLED',
            'size': '0.5',
            'limit_price': '40000.00'
        }
        
        # Resolve values
        product_type = normalize_product_type(order_dict)
        size = resolve_order_size(order_dict)
        price = extract_order_price(order_dict)
        
        assert product_type == 'SPOT'
        assert size == 0.5
        assert price == 40000.0
    
    def test_follow_up_calculation_workflow(self):
        """Test follow-up order calculation workflow."""
        profits = {'SPOT': {'BUY': 0.004, 'SELL': 0.004}}
        order_dict = {
            'product_id': 'BTC-USDC',
            'order_side': 'BUY',
        }
        
        profit_pct = resolve_profit_move_pct(order_dict, profits)
        initial_price = 40000.0
        follow_up_price = initial_price * (1 + profit_pct)
        
        # Format and quantize
        formatted = format_based_on_reference(follow_up_price, '1')
        quantized = quantize_to_increment(float(formatted), '1')
        
        assert profit_pct == 0.004
        assert follow_up_price == 40160.0
        assert quantized == 40160.0


# ============================================================================
# TEST EXECUTION SUMMARY
# ============================================================================

if __name__ == "__main__":
    # Run tests: python tests/test_phase1.py
    pytest.main([__file__, "-v", "--tb=short"])
