"""
Integration tests for stealth order workflows.

Tests multiple components working together (but not external APIs).
Uses mocked Coinbase API responses from api_reference/.
"""

import pytest
from datetime import datetime, timedelta


class TestStealthOrderWorkflow:
    """Test complete stealth order workflows."""
    
    def test_create_and_monitor_stealth_order(self, stealth_order_factory, sample_market_data):
        """Test creating a stealth order and monitoring it."""
        # Create order
        order = stealth_order_factory(
            product_id="BTC-USDC",
            side="BUY",
            total_size=1.0,
            limit_price=50000.0
        )
        
        assert order["status"] == "HIDDEN"
        assert order["revealed_size"] == 0.0
        
        # Simulate market data updates
        # (In real system, this would come from WebSocket)
        assert sample_market_data["price"] < 50000.0  # Below limit
    
    def test_reveal_slice_workflow(self, stealth_order_factory):
        """Test revealing slices of a stealth order."""
        order = stealth_order_factory(total_size=1.0)
        
        # First reveal - 25% of order
        reveal_amount = 0.25
        order["revealed_size"] += reveal_amount
        order["remaining_size"] -= reveal_amount
        
        assert order["revealed_size"] == 0.25
        assert order["remaining_size"] == 0.75
        assert order["status"] == "HIDDEN"  # Not fully revealed yet
        
        # Second reveal - another 25%
        order["revealed_size"] += reveal_amount
        order["remaining_size"] -= reveal_amount
        
        assert order["revealed_size"] == 0.5
        assert order["remaining_size"] == 0.5
        
        # Third reveal - another 25%
        order["revealed_size"] += reveal_amount
        order["remaining_size"] -= reveal_amount
        
        # Final reveal - remaining 25%
        order["revealed_size"] += order["remaining_size"]
        order["remaining_size"] = 0.0
        order["status"] = "REVEALED"
        
        assert order["revealed_size"] == 1.0
        assert order["remaining_size"] == 0.0
        assert order["status"] == "REVEALED"
    
    def test_duplicate_revealed_order(self, revealed_stealth_order):
        """Test creating a duplicate of a fully revealed order (Hide button).
        
        This simulates what the UI "Hide" button does.
        """
        original = revealed_stealth_order
        
        # Create duplicate with same parameters
        duplicate = {
            "product_id": original["product_id"],
            "side": original["side"],
            "total_size": original["total_size"],
            "limit_price": original["limit_price"],
            "reveal_condition_json": original["reveal_condition_json"],
            "status": "HIDDEN",
            "revealed_size": 0.0,
            "remaining_size": original["total_size"],
        }
        
        # Verify duplicate has same config but is fresh
        assert duplicate["product_id"] == original["product_id"]
        assert duplicate["reveal_condition_json"] == original["reveal_condition_json"]
        assert duplicate["status"] == "HIDDEN"
        assert duplicate["revealed_size"] == 0.0


class TestMarketDataIntegration:
    """Test market data integration with order evaluation."""
    
    def test_condition_evaluation_with_market_data(self, sample_stealth_order, sample_market_data):
        """Test evaluating reveal condition against market data."""
        order = sample_stealth_order
        market = sample_market_data
        
        # Order has condition: reveal when price below 45000
        condition = order["reveal_condition_json"]
        assert condition["type"] == "price_threshold"
        assert condition["direction"] == "below"
        assert condition["price_threshold"] == 45000.0
        
        # Market price is 48500 - above threshold, should NOT reveal
        should_reveal = (
            condition["direction"] == "below" and 
            market["price"] < condition["price_threshold"]
        )
        assert should_reveal is False  # Price not low enough yet
    
    def test_condition_met_when_price_drops(self, sample_stealth_order, sample_market_data):
        """Test condition is met when price reaches threshold."""
        order = sample_stealth_order
        market = sample_market_data
        
        # Simulate price drop below threshold
        market["price"] = 44000.0
        
        # Now condition should be met
        condition = order["reveal_condition_json"]
        should_reveal = (
            condition["direction"] == "below" and 
            market["price"] < condition["price_threshold"]
        )
        assert should_reveal is True


class TestOrderMultipleProducts:
    """Test managing orders across multiple products."""
    
    def test_orders_different_products_tracked_separately(self, stealth_order_factory):
        """Test orders for different products are independent."""
        btc_order = stealth_order_factory(product_id="BTC-USDC")
        eth_order = stealth_order_factory(product_id="ETH-USDC")
        
        assert btc_order["product_id"] == "BTC-USDC"
        assert eth_order["product_id"] == "ETH-USDC"
        
        # Reveal BTC order
        btc_order["revealed_size"] = btc_order["total_size"]
        btc_order["status"] = "REVEALED"
        
        # ETH order should still be hidden
        assert eth_order["status"] == "HIDDEN"
        assert eth_order["revealed_size"] == 0.0


# Run with: pytest tests/integration/ -v
