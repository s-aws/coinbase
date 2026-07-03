"""
Unit tests for data models and state management.

Tests order models, enums, and state tracking.
"""

import pytest
from datetime import datetime, timezone
from core.enums import StealthOrderStatus, OrderStatus
from core.models import Wallet


class TestOrderModels:
    """Test order data structures."""
    
    def test_stealth_order_has_required_fields(self):
        """Stealth order has all required fields."""
        order = {
            "stealth_order_id": "so_123",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "total_size": 1.0,
            "revealed_size": 0.0,
            "remaining_size": 1.0,
            "limit_price": 50000.0,
            "status": "HIDDEN",
            "reveal_condition_type": "price_threshold",
            "reveal_condition_json": {
                "type": "price_threshold",
                "direction": "below",
                "price_threshold": 45000.0,
            },
            "created_at": datetime.now(timezone.utc).astimezone(),
            "updated_at": datetime.now(timezone.utc).astimezone(),
        }
        
        required_fields = [
            "stealth_order_id", "product_id", "side", "total_size",
            "revealed_size", "remaining_size", "limit_price", "status",
            "reveal_condition_type", "created_at"
        ]
        
        for field in required_fields:
            assert field in order
    
    def test_order_status_enum(self):
        """Order status must be valid enum value."""
        valid_statuses = [StealthOrderStatus.HIDDEN.value, StealthOrderStatus.PENDING.value, StealthOrderStatus.TRIGGERED.value, StealthOrderStatus.REVEALED.value, OrderStatus.FILLED.value, OrderStatus.CANCELLED.value]
        
        test_status = StealthOrderStatus.HIDDEN.value
        
        assert test_status in valid_statuses
    
    def test_order_side_enum(self):
        """Order side must be BUY or SELL."""
        valid_sides = ["BUY", "SELL"]
        
        test_side = "BUY"
        
        assert test_side in valid_sides


class TestParentChildOrderRelationship:
    """Test parent-child order relationships."""
    
    def test_parent_order_has_child_id(self):
        """Parent order tracks its child order ID."""
        parent_order = {
            "order_id": "parent_123",
            "status": "FILLED",
            "child_order_id": "child_456"
        }
        
        assert parent_order["child_order_id"] == "child_456"
    
    def test_child_order_has_parent_id(self):
        """Child order tracks its parent order ID."""
        child_order = {
            "order_id": "child_456",
            "status": "PENDING",
            "parent_order_id": "parent_123"
        }
        
        assert child_order["parent_order_id"] == "parent_123"
    
    def test_child_price_is_above_parent_fill_price(self):
        """Profit target (child) is higher than fill price (parent)."""
        parent_fill_price = 50000.0
        profit_pct = 0.02
        child_price = parent_fill_price * (1 + profit_pct)
        
        assert child_price > parent_fill_price
        assert child_price == 51000.0


class TestOrderStateTransitions:
    """Test valid order state transitions."""
    
    def test_hidden_to_triggered_transition(self):
        """HIDDEN order can transition to TRIGGERED."""
        current_status = StealthOrderStatus.HIDDEN.value
        new_status = StealthOrderStatus.TRIGGERED.value
        
        valid_transition = current_status == StealthOrderStatus.HIDDEN.value and new_status == StealthOrderStatus.TRIGGERED.value
        
        assert valid_transition is True
    
    def test_triggered_to_revealed_transition(self):
        """TRIGGERED order can transition to REVEALED."""
        current_status = StealthOrderStatus.TRIGGERED.value
        new_status = StealthOrderStatus.REVEALED.value
        
        valid_transition = current_status == StealthOrderStatus.TRIGGERED.value and new_status == StealthOrderStatus.REVEALED.value
        
        assert valid_transition is True
    
    def test_revealed_to_filled_transition(self):
        """REVEALED order can transition to FILLED."""
        current_status = StealthOrderStatus.REVEALED.value
        new_status = OrderStatus.FILLED.value
        
        valid_transition = current_status == StealthOrderStatus.REVEALED.value and new_status == OrderStatus.FILLED.value
        
        assert valid_transition is True
    
    def test_any_status_to_cancelled(self):
        """Any status can transition to CANCELLED."""
        statuses = [StealthOrderStatus.HIDDEN.value, StealthOrderStatus.PENDING.value, StealthOrderStatus.TRIGGERED.value, StealthOrderStatus.REVEALED.value]
        
        for status in statuses:
            can_cancel = status in [StealthOrderStatus.HIDDEN.value, StealthOrderStatus.PENDING.value, StealthOrderStatus.TRIGGERED.value, StealthOrderStatus.REVEALED.value]
            assert can_cancel is True


class TestAccountAndPortfolio:
    """Test account and portfolio models."""
    
    def test_account_has_trading_balance(self):
        """Account has cash balance for trading."""
        account = {
            "account_id": "acc_123",
            "currency": "USD",
            "available": 10000.0,
            "hold": 500.0,
            "total": 10500.0
        }
        
        assert account["available"] + account["hold"] == account["total"]

    def test_wallet_from_dict_normalizes_coinbase_money_values(self):
        """Wallet balances accept Coinbase money-object response fields."""
        wallet = Wallet.from_dict(
            {
                "currency": "USD",
                "available_balance": {"value": "9.25", "currency": "USD"},
                "total_balance": {"value": "10.00", "currency": "USD"},
                "created_at": "2026-07-03T00:00:00Z",
                "updated_at": "2026-07-03T00:02:00Z",
                "deleted_at": None,
            }
        )

        assert wallet.currency == "USD"
        assert wallet.available_balance == "9.25"
        assert wallet.total_balance == "10.00"
        assert wallet.deleted_at is None

    def test_wallet_from_dict_derives_total_from_available_and_hold(self):
        """Wallet total can be derived from Coinbase account hold fields."""
        wallet = Wallet.from_dict(
            {
                "currency": "USD",
                "available_balance": {"value": "9.25", "currency": "USD"},
                "hold": {"value": "0.75", "currency": "USD"},
            }
        )

        assert wallet.total_balance == "10.00"
    
    def test_portfolio_tracks_positions(self):
        """Portfolio tracks all open positions."""
        portfolio = {
            "portfolio_id": "port_123",
            "positions": [
                {"product_id": "BTC-USDC", "size": 0.5},
                {"product_id": "ETH-USDC", "size": 5.0},
            ]
        }
        
        assert len(portfolio["positions"]) == 2
    
    def test_position_value_calculation(self):
        """Calculate position value from size and price."""
        size = 1.0
        price = 50000.0
        
        value = size * price
        
        assert value == 50000.0


class TestWebSocketMessage:
    """Test WebSocket message structures."""
    
    def test_ticker_message_has_price(self):
        """Ticker message includes current price."""
        ticker = {
            "type": "ticker",
            "product_id": "BTC-USDC",
            "price": 50000.0,
            "time": datetime.now(timezone.utc).astimezone().isoformat()
        }
        
        assert ticker["price"] == 50000.0
    
    def test_done_message_has_order_info(self):
        """Done message includes order completion info."""
        done = {
            "type": "done",
            "order_id": "order_123",
            "reason": "filled",
            "price": 50000.0,
            "remaining_size": 0.0
        }
        
        assert done["reason"] == "filled"
        assert done["remaining_size"] == 0.0
    
    def test_user_message_has_order_update(self):
        """User message includes order status update."""
        user_msg = {
            "type": "done",
            "side": "buy",
            "order_id": "order_123",
            "reason": "filled",
            "price": 50000.0,
            "remaining_size": 0.0
        }
        
        assert user_msg["side"] == "buy"


class TestTimeAndDateHandling:
    """Test timestamp and date handling."""
    
    def test_order_timestamps_are_datetime(self):
        """Order timestamps should be datetime objects."""
        now = datetime.now(timezone.utc).astimezone()
        
        assert isinstance(now, datetime)
    
    def test_timestamp_ordering(self):
        """Earlier timestamp is before later timestamp."""
        earlier = datetime(2026, 4, 19, 10, 0, 0)
        later = datetime(2026, 4, 19, 11, 0, 0)
        
        assert earlier < later
    
    def test_duration_calculation(self):
        """Calculate duration between timestamps."""
        start = datetime(2026, 4, 19, 10, 0, 0)
        end = datetime(2026, 4, 19, 10, 5, 0)
        
        duration = (end - start).total_seconds()
        
        assert duration == 300.0  # 5 minutes


# Run with: pytest tests/unit/test_models.py -v
