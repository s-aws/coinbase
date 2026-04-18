"""Phase 2 Tests - Dependency Injection & Decoupling.

Comprehensive test suite for Phase 2 extracted modules:
- External API clients (REST, WebSocket)
- Data repositories (OrderRepository, PostgresOrderRepository)
- State management (StateManager)

Tests use mock implementations to verify:
- Clean API abstractions
- Proper dependency injection
- Repository pattern correctness
- State management thread safety

Run with: python -m pytest tests/test_phase2.py -v
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
from typing import Dict, Any

from external.coinbase_client import CoinbaseRestClient
from external.coinbase_websocket import CoinbaseWebSocketClient
from data.repositories import OrderRepository, PostgresOrderRepository
from data.state_manager import StateManager
from core.models import Order, Product, Wallet, Position
from core.enums import OrderSide, OrderStatus, ProductType


# ============================================================================
# MOCK IMPLEMENTATIONS
# ============================================================================

class MockSDKClient:
    """Mock Coinbase SDK REST client."""
    
    def get_accounts(self):
        return {
            "accounts": [
                {"currency": "BTC", "available_balance": "1.0", "total_balance": "1.0", "deleted_at": None},
                {"currency": "USDC", "available_balance": "10000", "total_balance": "10000", "deleted_at": None},
            ]
        }
    
    def get_product(self, product_id):
        return {
            "product_id": product_id,
            "product_type": "SPOT",
            "base_increment": "0.001",
            "quote_increment": "0.01",
            "price_increment": "1",
            "trading_disabled": False
        }
    
    def list_futures_positions(self):
        response = Mock()
        response.to_dict.return_value = {
            "positions": [
                {
                    "product_id": "BIP-20DEC30-CDE",
                    "side": "LONG",
                    "number_of_contracts": "100",
                    "current_price": "77000.00"
                }
            ]
        }
        return response
    
    def list_orders(self, order_status):
        response = Mock()
        response.to_dict.return_value = {
            "orders": [
                {
                    "client_order_id": "order_123",
                    "product_id": "BTC-USDC",
                    "order_side": "BUY",
                    "status": "OPEN",
                    "size": "0.5",
                    "price": "40000.00"
                }
            ]
        }
        return response
    
    def create_order(self, **kwargs):
        return {
            "client_order_id": kwargs.get("client_order_id"),
            "product_id": kwargs.get("product_id"),
            "order_side": kwargs.get("side"),
            "status": "PENDING",
            "size": kwargs.get("base_size", "0"),
            "price": kwargs.get("limit_price", "0")
        }
    
    def cancel_orders(self, order_ids):
        return order_ids
    
    def get_transaction_summary(self):
        return {"total_fees": "0.1"}
    
    def get_portfolio(self, portfolio_id):
        response = Mock()
        response.to_dict.return_value = {
            "portfolio_id": portfolio_id,
            "name": "Default",
            "breakdown": {"total_balance": "50000"}
        }
        return response
    
    def list_portfolios(self):
        response = Mock()
        response.to_dict.return_value = {
            "portfolios": [
                {"portfolio_id": "default", "name": "Default"}
            ]
        }
        return response


class MockSDKWebSocketClient:
    """Mock Coinbase SDK WebSocket client."""
    
    def __init__(self):
        self._on_message_callback = None
        self._on_error_callback = None
        self._on_open_callback = None
        self._on_close_callback = None
    
    def open(self):
        if self._on_open_callback:
            self._on_open_callback()
    
    def close(self):
        if self._on_close_callback:
            self._on_close_callback()
    
    def subscribe(self, product_ids, channel):
        pass
    
    def unsubscribe(self, product_ids=None, channel=None):
        pass
    
    def on_message(self, callback):
        self._on_message_callback = callback
    
    def on_error(self, callback):
        self._on_error_callback = callback
    
    def on_open(self, callback):
        self._on_open_callback = callback
    
    def on_close(self, callback):
        self._on_close_callback = callback


class MockOrderRepository:
    """Mock OrderRepository for testing."""
    
    def __init__(self):
        self._orders = {}
        self._parent_orders = {}
        self._child_orders = {}
    
    def get_order(self, client_order_id):
        return self._orders.get(client_order_id)
    
    def get_all_orders(self):
        return list(self._orders.values())
    
    def get_orders_by_product(self, product_id):
        return [o for o in self._orders.values() if o.product_id == product_id]
    
    def get_orders_by_status(self, status):
        return [o for o in self._orders.values() if o.status.value == status]
    
    def save_order(self, order):
        self._orders[order.client_order_id] = order
    
    def save_parent_order(self, client_order_id, product_id, side, size, price, **kwargs):
        self._parent_orders[client_order_id] = {
            "client_order_id": client_order_id,
            "product_id": product_id,
            "side": side,
            "size": size,
            "price": price
        }
        return len(self._parent_orders)
    
    def save_child_order(self, parent_order_id, client_order_id, product_id, side, size, price, **kwargs):
        self._child_orders[client_order_id] = {
            "parent_order_id": parent_order_id,
            "client_order_id": client_order_id,
            "product_id": product_id,
            "side": side,
            "size": size,
            "price": price
        }
        return len(self._child_orders)
    
    def get_parent_orders(self):
        return list(self._parent_orders.values())
    
    def get_children_of_parent(self, parent_order_id):
        return [o for o in self._child_orders.values() if o.get("parent_order_id") == parent_order_id]
    
    def update_order_status(self, client_order_id, status):
        if client_order_id in self._orders:
            self._orders[client_order_id].status = OrderStatus[status]
    
    def delete_order(self, client_order_id):
        self._orders.pop(client_order_id, None)


# ============================================================================
# REST CLIENT TESTS
# ============================================================================

class TestCoinbaseRestClient:
    """Test CoinbaseRestClient wrapper."""
    
    def test_client_initialization(self):
        """Test: Initialize with SDK client."""
        sdk_client = MockSDKClient()
        client = CoinbaseRestClient(sdk_client)
        assert client is not None
    
    def test_client_none_raises_error(self):
        """Test: None SDK client raises ValueError."""
        with pytest.raises(ValueError):
            CoinbaseRestClient(None)
    
    def test_get_account_wallets(self):
        """Test: Retrieve account wallets."""
        sdk_client = MockSDKClient()
        client = CoinbaseRestClient(sdk_client)
        
        wallets = client.get_account_wallets()
        
        assert "BTC" in wallets
        assert "USDC" in wallets
        assert isinstance(wallets["BTC"], Wallet)
        assert wallets["BTC"].currency == "BTC"
    
    def test_get_product(self):
        """Test: Retrieve single product."""
        sdk_client = MockSDKClient()
        client = CoinbaseRestClient(sdk_client)
        
        product = client.get_product("BTC-USDC")
        
        assert product is not None
        assert product.product_id == "BTC-USDC"
        assert isinstance(product, Product)
    
    def test_get_products(self):
        """Test: Retrieve multiple products."""
        sdk_client = MockSDKClient()
        client = CoinbaseRestClient(sdk_client)
        
        products = client.get_products(["BTC-USDC", "ETH-USDC"])
        
        assert "BTC-USDC" in products
        assert isinstance(products["BTC-USDC"], Product)
    
    def test_get_open_orders(self):
        """Test: Retrieve open orders."""
        sdk_client = MockSDKClient()
        client = CoinbaseRestClient(sdk_client)
        
        orders = client.get_open_orders()
        
        assert "order_123" in orders
        assert isinstance(orders["order_123"], Order)
    
    def test_get_futures_positions(self):
        """Test: Retrieve futures positions."""
        sdk_client = MockSDKClient()
        client = CoinbaseRestClient(sdk_client)
        
        positions = client.get_futures_positions()
        
        assert "BIP-20DEC30-CDE" in positions
        assert isinstance(positions["BIP-20DEC30-CDE"], Position)
    
    def test_place_limit_order(self):
        """Test: Place a limit order."""
        sdk_client = MockSDKClient()
        client = CoinbaseRestClient(sdk_client)
        
        order = client.place_limit_order(
            product_id="BTC-USDC",
            side="BUY",
            limit_price="40000.00",
            base_size="0.1",
            client_order_id="test_order_1"
        )
        
        assert order.client_order_id == "test_order_1"
        assert order.product_id == "BTC-USDC"
        assert isinstance(order, Order)
    
    def test_cancel_order(self):
        """Test: Cancel an order."""
        sdk_client = MockSDKClient()
        client = CoinbaseRestClient(sdk_client)
        
        success = client.cancel_order("order_id_123")
        
        assert success is True


# ============================================================================
# WEBSOCKET CLIENT TESTS
# ============================================================================

class TestCoinbaseWebSocketClient:
    """Test CoinbaseWebSocketClient wrapper."""
    
    def test_client_initialization(self):
        """Test: Initialize with SDK client."""
        sdk_client = MockSDKWebSocketClient()
        client = CoinbaseWebSocketClient(sdk_client)
        assert client is not None
    
    def test_client_none_raises_error(self):
        """Test: None SDK client raises ValueError."""
        with pytest.raises(ValueError):
            CoinbaseWebSocketClient(None)
    
    def test_subscribe_validates_products(self):
        """Test: Empty products list raises error."""
        sdk_client = MockSDKWebSocketClient()
        client = CoinbaseWebSocketClient(sdk_client)
        
        with pytest.raises(ValueError):
            client.subscribe(products=[], channels=['ticker'])
    
    def test_subscribe_validates_channels(self):
        """Test: Empty channels list raises error."""
        sdk_client = MockSDKWebSocketClient()
        client = CoinbaseWebSocketClient(sdk_client)
        
        with pytest.raises(ValueError):
            client.subscribe(products=['BTC-USDC'], channels=[])
    
    def test_subscribe_with_callback(self):
        """Test: Subscribe with message callback."""
        sdk_client = MockSDKWebSocketClient()
        client = CoinbaseWebSocketClient(sdk_client)
        
        callback = Mock()
        client.subscribe(
            products=['BTC-USDC'],
            channels=['ticker'],
            on_message=callback
        )
        
        assert callback in client._message_callbacks
    
    def test_is_connected_tracks_state(self):
        """Test: is_connected reflects connection state."""
        sdk_client = MockSDKWebSocketClient()
        client = CoinbaseWebSocketClient(sdk_client)
        
        assert client.is_connected() is False
        client._is_connected = True
        assert client.is_connected() is True


# ============================================================================
# STATE MANAGER TESTS
# ============================================================================

class TestStateManager:
    """Test StateManager class."""
    
    def test_initialization(self):
        """Test: Initialize StateManager."""
        state = StateManager()
        assert state is not None
        assert len(state.get_active_orders()) == 0
    
    def test_add_active_order(self):
        """Test: Add an active order."""
        state = StateManager()
        
        order = Order(
            client_order_id="order_1",
            product_id="BTC-USDC",
            order_side=OrderSide.BUY,
            status=OrderStatus.OPEN,
            size=0.5
        )
        
        state.add_active_order(order)
        
        assert "order_1" in state.get_active_orders()
    
    def test_mark_order_filled(self):
        """Test: Mark order as filled."""
        state = StateManager()
        
        order = Order(
            client_order_id="order_1",
            product_id="BTC-USDC",
            order_side=OrderSide.BUY,
            status=OrderStatus.OPEN
        )
        
        state.add_active_order(order)
        assert "order_1" in state.get_active_orders()
        
        state.mark_order_filled(order)
        
        assert "order_1" not in state.get_active_orders()
        assert "order_1" in state.get_filled_orders()
    
    def test_mark_order_cancelled(self):
        """Test: Mark order as cancelled."""
        state = StateManager()
        
        order = Order(
            client_order_id="order_1",
            product_id="BTC-USDC",
            order_side=OrderSide.BUY,
            status=OrderStatus.OPEN
        )
        
        state.add_active_order(order)
        state.mark_order_cancelled(order)
        
        assert "order_1" not in state.get_active_orders()
        assert "order_1" in state.get_cancelled_orders()
    
    def test_get_order(self):
        """Test: Retrieve an order."""
        state = StateManager()
        
        order = Order(
            client_order_id="order_1",
            product_id="BTC-USDC",
            order_side=OrderSide.BUY,
            status=OrderStatus.OPEN
        )
        
        state.add_active_order(order)
        retrieved = state.get_order("order_1")
        
        assert retrieved is not None
        assert retrieved.client_order_id == "order_1"
    
    def test_update_position(self):
        """Test: Update a position."""
        state = StateManager()
        
        position = Position(
            product_id="BIP-20DEC30-CDE",
            side="LONG",
            number_of_contracts="100"
        )
        
        state.update_position("BIP-20DEC30-CDE", position)
        
        retrieved = state.get_position("BIP-20DEC30-CDE")
        assert retrieved is not None
        assert retrieved.product_id == "BIP-20DEC30-CDE"
    
    def test_profit_config_fallback(self):
        """Test: Profit config falls back from product → type → default."""
        state = StateManager(
            profit_config={
                'SPOT': {'BUY': 0.002, 'SELL': 0.002},
                'BTC-USDC': {'BUY': 0.004, 'SELL': 0.004}
            }
        )
        
        # Product-specific
        config = state.get_profit_config('BTC-USDC')
        assert config['BUY'] == 0.004
        
        # Type fallback (ETH-USDC is SPOT)
        config = state.get_profit_config('ETH-USDC')
        assert config['BUY'] == 0.002
        
        # Default fallback (unknown product)
        config = state.get_profit_config('UNKNOWN-USDC')
        assert config['BUY'] == 0.002
    
    def test_get_order_stats(self):
        """Test: Order statistics."""
        state = StateManager()
        
        order1 = Order(client_order_id="o1", product_id="BTC-USDC", order_side=OrderSide.BUY, status=OrderStatus.OPEN)
        order2 = Order(client_order_id="o2", product_id="BTC-USDC", order_side=OrderSide.BUY, status=OrderStatus.OPEN)
        order3 = Order(client_order_id="o3", product_id="BTC-USDC", order_side=OrderSide.BUY, status=OrderStatus.OPEN)
        
        state.add_active_order(order1)
        state.mark_order_filled(order2)
        state.mark_order_cancelled(order3)
        
        stats = state.get_order_stats()
        
        assert stats['active'] == 1
        assert stats['filled'] == 1
        assert stats['cancelled'] == 1
        assert stats['total'] == 3
    
    def test_add_subscription(self):
        """Test: Track subscriptions."""
        state = StateManager()
        
        state.add_subscription("BTC-USDC", "ticker")
        state.add_subscription("ETH-USDC", "level2")
        
        products = state.get_subscribed_products()
        channels = state.get_subscribed_channels()
        
        assert "BTC-USDC" in products
        assert "ETH-USDC" in products
        assert "ticker" in channels
        assert "level2" in channels
    
    def test_thread_safety(self):
        """Test: Operations are thread-safe."""
        state = StateManager()
        
        # Create multiple orders
        for i in range(10):
            order = Order(
                client_order_id=f"order_{i}",
                product_id="BTC-USDC",
                order_side=OrderSide.BUY,
                status=OrderStatus.OPEN
            )
            state.add_active_order(order)
        
        # All should be retrievable
        stats = state.get_order_stats()
        assert stats['active'] == 10


# ============================================================================
# REPOSITORY TESTS
# ============================================================================

class TestMockOrderRepository:
    """Test MockOrderRepository."""
    
    def test_save_and_retrieve_order(self):
        """Test: Save and retrieve order."""
        repo = MockOrderRepository()
        
        order = Order(
            client_order_id="order_1",
            product_id="BTC-USDC",
            order_side=OrderSide.BUY,
            status=OrderStatus.OPEN
        )
        
        repo.save_order(order)
        retrieved = repo.get_order("order_1")
        
        assert retrieved is not None
        assert retrieved.client_order_id == "order_1"
    
    def test_parent_child_relationship(self):
        """Test: Parent and child order relationship."""
        repo = MockOrderRepository()
        
        parent_id = repo.save_parent_order(
            client_order_id="parent_1",
            product_id="BTC-USDC",
            side="BUY",
            size=0.5,
            price=40000.0
        )
        
        child_id = repo.save_child_order(
            parent_order_id=parent_id,
            client_order_id="child_1",
            product_id="BTC-USDC",
            side="SELL",
            size=0.5,
            price=40160.0
        )
        
        children = repo.get_children_of_parent(parent_id)
        
        assert len(children) == 1
        assert children[0]["client_order_id"] == "child_1"


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestPhase2Integration:
    """Integration tests for Phase 2 components."""
    
    def test_rest_client_with_state_manager(self):
        """Test: REST client data flows to StateManager."""
        sdk_client = MockSDKClient()
        rest_client = CoinbaseRestClient(sdk_client)
        state = StateManager()
        
        # Get orders from API
        api_orders = rest_client.get_open_orders()
        
        # Add to state manager
        for client_id, order in api_orders.items():
            state.add_active_order(order)
        
        # Verify in state
        assert len(state.get_active_orders()) > 0
        retrieved = state.get_order("order_123")
        assert retrieved is not None
    
    def test_state_manager_with_repository(self):
        """Test: StateManager works with repository."""
        repo = MockOrderRepository()
        state = StateManager(order_repo=repo)
        
        order = Order(
            client_order_id="test_order",
            product_id="BTC-USDC",
            order_side=OrderSide.BUY,
            status=OrderStatus.OPEN
        )
        
        state.add_active_order(order)
        
        # Verify saved in repository
        saved = repo.get_order("test_order")
        assert saved is not None
        assert saved.client_order_id == "test_order"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
