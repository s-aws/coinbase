"""Test the resolve_order_size and resolve_order_side helper functions."""

import pytest
from calculation.resolver import resolve_order_size, resolve_order_side


class TestResolveOrderSize:
    """Test resolve_order_size with various field names."""
    
    def test_resolve_size_from_leaves_quantity(self):
        """Resolve size from leaves_quantity field."""
        order = {"leaves_quantity": 10.5}
        assert resolve_order_size(order) == 10.5
    
    def test_resolve_size_from_cumulative_quantity(self):
        """Resolve size from cumulative_quantity field."""
        order = {"cumulative_quantity": 5.0}
        assert resolve_order_size(order) == 5.0
    
    def test_resolve_size_from_filled_size(self):
        """Resolve size from filled_size field."""
        order = {"filled_size": "3.5"}
        assert resolve_order_size(order) == 3.5
    
    def test_resolve_size_from_base_size(self):
        """Resolve size from base_size field."""
        order = {"base_size": "2.25"}
        assert resolve_order_size(order) == 2.25
    
    def test_resolve_size_from_size(self):
        """Resolve size from size field."""
        order = {"size": 1.0}
        assert resolve_order_size(order) == 1.0
    
    def test_resolve_size_priority_order(self):
        """Verify field priority - leaves_quantity takes precedence."""
        order = {
            "leaves_quantity": 10.0,
            "filled_size": 5.0,
            "size": 1.0
        }
        # Should return leaves_quantity (highest priority)
        assert resolve_order_size(order) == 10.0
    
    def test_resolve_size_missing_returns_zero(self):
        """Return 0.0 when no size field found."""
        order = {"product_id": "BTC-USDC"}
        assert resolve_order_size(order) == 0.0
    
    def test_resolve_size_empty_dict(self):
        """Return 0.0 for empty order dict."""
        order = {}
        assert resolve_order_size(order) == 0.0
    
    def test_resolve_size_zero_value(self):
        """Return 0.0 when size is zero."""
        order = {"filled_size": 0.0}
        assert resolve_order_size(order) == 0.0


class TestResolveOrderSide:
    """Test resolve_order_side with various field names."""
    
    def test_resolve_side_from_order_side(self):
        """Resolve side from order_side field."""
        order = {"order_side": "BUY"}
        assert resolve_order_side(order) == "BUY"
    
    def test_resolve_side_from_side(self):
        """Resolve side from side field."""
        order = {"side": "SELL"}
        assert resolve_order_side(order) == "SELL"
    
    def test_resolve_side_lowercase(self):
        """Normalize lowercase side to uppercase."""
        order = {"side": "buy"}
        assert resolve_order_side(order) == "BUY"
    
    def test_resolve_side_with_whitespace(self):
        """Handle whitespace around side value."""
        order = {"order_side": "  SELL  "}
        assert resolve_order_side(order) == "SELL"
    
    def test_resolve_side_priority_order(self):
        """Verify order_side takes priority over side."""
        order = {
            "order_side": "BUY",
            "side": "SELL"
        }
        # Should return order_side (higher priority)
        assert resolve_order_side(order) == "BUY"
    
    def test_resolve_side_missing_returns_none(self):
        """Return None when no side field found."""
        order = {"product_id": "BTC-USDC"}
        assert resolve_order_side(order) is None
    
    def test_resolve_side_empty_dict(self):
        """Return None for empty order dict."""
        order = {}
        assert resolve_order_side(order) is None
    
    def test_resolve_side_invalid_value(self):
        """Return None for invalid side value."""
        order = {"side": "INVALID"}
        assert resolve_order_side(order) is None


class TestHelperIntegration:
    """Test helpers work together for order status logging."""
    
    def test_order_logging_with_helpers(self):
        """Test resolving complete order info for logging."""
        order = {
            "product_id": "BIP-20DEC30-CDE",
            "order_side": "SELL",
            "filled_size": "1.0"
        }
        
        product_id = order.get("product_id")
        side = resolve_order_side(order)
        size = resolve_order_size(order)
        
        # Simulate log format
        log_message = f"Order FILLED: {product_id} {side} {size}"
        assert log_message == "Order FILLED: BIP-20DEC30-CDE SELL 1.0"
    
    def test_order_logging_with_fallback_fields(self):
        """Test resolving with alternative field names."""
        order = {
            "product_id": "BTC-USDC",
            "side": "BUY",
            "base_size": "0.5"
        }
        
        product_id = order.get("product_id")
        side = resolve_order_side(order)
        size = resolve_order_size(order)
        
        log_message = f"Order OPEN: {product_id} {side} {size}"
        assert log_message == "Order OPEN: BTC-USDC BUY 0.5"
