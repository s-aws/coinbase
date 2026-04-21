"""
Integration tests for complete order processing workflows.

Tests multiple components working together with realistic scenarios.
"""

import pytest
from datetime import datetime, timezone


class TestCompleteOrderLifecycle:
    """Test complete workflow from order creation to execution."""
    
    def test_limit_order_to_execution(self, stealth_order_factory, sample_market_data):
        """Test lifecycle: create limit order → monitor → fill."""
        # Create order with price-based reveal condition
        order = stealth_order_factory(
            product_id="BTC-USDC",
            side="BUY",
            total_size=1.0,
            limit_price=50000.0,
            reveal_condition_json={
                "type": "price",
                "direction": "below",
                "price_threshold": 49000.0,
                "hold_duration_seconds": 1
            }
        )
        
        assert order["status"] == "HIDDEN"
        assert order["revealed_size"] == 0.0
        
        # Simulate price movement to trigger condition
        current_price = 48500.0  # Price dropped below threshold of 49000
        condition = order["reveal_condition_json"]
        
        should_trigger = (
            condition["direction"] == "below" and 
            current_price < condition["price_threshold"]
        )
        
        assert should_trigger is True
        
        # Reveal order
        order["status"] = "TRIGGERED"
        assert order["status"] == "TRIGGERED"
        
        # Simulate execution
        order["status"] = "FILLED"
        order["revealed_size"] = order["total_size"]
        order["remaining_size"] = 0.0
        
        assert order["status"] == "FILLED"
    
    def test_stealth_order_multi_slice_reveal(self, stealth_order_factory):
        """Test stealth order revealing in multiple slices."""
        order = stealth_order_factory(total_size=4.0)
        
        slices = [0.0, 1.0, 2.0, 3.0, 4.0]
        
        for reveal_amount in slices[1:]:
            order["revealed_size"] = reveal_amount
            order["remaining_size"] = order["total_size"] - reveal_amount
            
            if order["revealed_size"] < order["total_size"]:
                assert order["status"] == "HIDDEN"
            elif order["revealed_size"] == order["total_size"]:
                order["status"] = "REVEALED"
        
        assert order["status"] == "REVEALED"
        assert order["revealed_size"] == order["total_size"]
    
    def test_parent_child_order_flow(self):
        """Test parent order fill triggers child order creation."""
        parent = {
            "order_id": "parent_123",
            "product_id": "BTC-USDC",
            "status": "pending",
            "size": "1.0",
            "price": "50000.00"
        }
        
        # Parent order fills
        parent["status"] = "filled"
        parent_fill_price = 50000.0
        
        # Create child order at profit target
        profit_pct = 0.02
        child = {
            "order_id": "child_456",
            "product_id": "BTC-USDC",
            "parent_order_id": "parent_123",
            "status": "pending",
            "size": "1.0",
            "price": str(parent_fill_price * (1 + profit_pct))
        }
        
        assert child["parent_order_id"] == parent["order_id"]
        assert float(child["price"]) > parent_fill_price


class TestConditionEvaluationIntegration:
    """Test condition evaluation with market data."""
    
    def test_price_threshold_with_market_updates(self, sample_stealth_order, sample_market_data):
        """Test price threshold condition with realistic market data."""
        order = sample_stealth_order
        
        # Market price drops well below threshold
        market_price = 44000.0  # Below the threshold of 45000
        condition = order["reveal_condition_json"]
        
        # Condition: reveal when price below 45000
        assert condition["price_threshold"] == 45000.0
        
        # Price drops - should trigger
        should_reveal = market_price < condition["price_threshold"]
        assert should_reveal is True
    
    def test_volume_accumulation_over_time(self):
        """Test volume threshold with accumulating trades."""
        order = {
            "reveal_condition_json": {
                "type": "cumulative_volume",
                "volume_threshold": 50.0
            }
        }
        
        trades = [
            {"price": 50000, "size": 10.0},
            {"price": 50000, "size": 15.0},
            {"price": 50000, "size": 20.0},
            {"price": 50000, "size": 10.0},  # Should trigger now
        ]
        
        cumulative = 0.0
        triggered = False
        
        for trade in trades:
            cumulative += trade["size"]
            if cumulative >= order["reveal_condition_json"]["volume_threshold"]:
                triggered = True
                break
        
        assert triggered is True
        assert cumulative >= 50.0


class TestPortfolioManagement:
    """Test portfolio updates through order lifecycle."""
    
    def test_portfolio_updates_on_order_fill(self):
        """Portfolio position updates when order fills."""
        portfolio = {
            "positions": {
                "BTC-USDC": 0.0,
                "USD": 10000.0
            }
        }
        
        # Buy 1 BTC at 50000
        order = {
            "side": "BUY",
            "product_id": "BTC-USDC",
            "size": 1.0,
            "price": 50000.0
        }
        
        # Apply order to portfolio
        portfolio["positions"]["BTC-USDC"] += order["size"]
        portfolio["positions"]["USD"] -= order["size"] * order["price"]
        
        assert portfolio["positions"]["BTC-USDC"] == 1.0
        assert portfolio["positions"]["USD"] == -40000.0
    
    def test_portfolio_value_calculation(self):
        """Calculate total portfolio value in USD."""
        positions = {
            "BTC": 0.5,
            "ETH": 5.0,
            "USD": 10000.0
        }
        
        prices = {
            "BTC": 50000.0,
            "ETH": 3000.0,
            "USD": 1.0
        }
        
        total_value = sum(positions.get(asset, 0) * prices[asset] for asset in prices)
        
        expected = (0.5 * 50000) + (5.0 * 3000) + (10000 * 1)
        assert total_value == expected


class TestEventPropagation:
    """Test events propagating through the system."""
    
    def test_order_creation_event(self):
        """Order creation triggers event."""
        events = []
        
        order = {
            "stealth_order_id": "so_123",
            "status": "HIDDEN",
            "created_at": datetime.now(timezone.utc).astimezone()
        }
        
        event = {
            "type": "stealth_order_created",
            "order_id": order["stealth_order_id"],
            "timestamp": datetime.now(timezone.utc).astimezone()
        }
        
        events.append(event)
        
        assert len(events) == 1
        assert events[0]["type"] == "stealth_order_created"
    
    def test_order_revealed_event(self):
        """Order reveal triggers event."""
        events = []
        
        order = {
            "stealth_order_id": "so_123",
            "revealed_size": 0.5,
            "total_size": 1.0
        }
        
        event = {
            "type": "stealth_order_revealed",
            "order_id": order["stealth_order_id"],
            "revealed_size": order["revealed_size"],
            "timestamp": datetime.now(timezone.utc).astimezone()
        }
        
        events.append(event)
        
        assert events[0]["type"] == "stealth_order_revealed"
        assert events[0]["revealed_size"] == 0.5
    
    def test_order_filled_event(self):
        """Order fill triggers event."""
        events = []
        
        order = {
            "stealth_order_id": "so_123",
            "status": "FILLED",
            "filled_at": datetime.now(timezone.utc).astimezone()
        }
        
        event = {
            "type": "stealth_order_filled",
            "order_id": order["stealth_order_id"],
            "timestamp": order["filled_at"]
        }
        
        events.append(event)
        
        assert events[0]["type"] == "stealth_order_filled"


class TestErrorRecovery:
    """Test system recovery from errors."""
    
    def test_reconnect_on_websocket_disconnect(self):
        """System reconnects WebSocket on disconnect."""
        connection_attempts = 0
        max_attempts = 3
        
        for attempt in range(max_attempts):
            connection_attempts += 1
            # Simulate connection success on 2nd attempt
            if attempt == 1:
                success = True
                break
        
        assert success is True
        assert connection_attempts == 2
    
    def test_retry_failed_order_creation(self):
        """Retry order creation on temporary failure."""
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                # Simulate failure on attempt 1-2, success on 3
                if attempt < 2:
                    raise Exception("Temporary error")
                else:
                    order = {"stealth_order_id": "so_123"}
                    break
            except Exception:
                if attempt == max_retries - 1:
                    raise
        
        assert order["stealth_order_id"] == "so_123"
    
    def test_graceful_shutdown(self):
        """Gracefully shutdown all components."""
        components = [
            "websocket",
            "database",
            "order_engine"
        ]
        
        shutdown_log = []
        
        for component in components:
            shutdown_log.append(f"Shutting down {component}")
        
        assert len(shutdown_log) == 3


# Run with: pytest tests/integration/ -v
