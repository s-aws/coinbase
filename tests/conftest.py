"""
Pytest configuration and shared fixtures.

This file is automatically loaded by pytest and provides:
- Common fixtures for all test categories
- Database setup/teardown
- Mock factories
- Test configuration
"""

import os

# ============================================================================
# CRITICAL: prod-DB guard. Must run BEFORE any `database.*` module is imported
# so the env-driven defaults in `database.database` resolve to the test
# instance (port 9876), never prod (5432).
#
# Background: 2026-04-27 — `tests/unit/test_order_moves.py` instantiated
# `PostgresDB()` with no args, which defaulted to port 5432 and wrote 40
# phantom rows into the production `order_parent` table. Never again.
# ============================================================================
os.environ.setdefault("COINBASE_DB_HOST", "127.0.0.1")
os.environ.setdefault("COINBASE_DB_PORT", "9876")
os.environ.setdefault("COINBASE_DB_NAME", "postgres")
os.environ.setdefault("COINBASE_DB_USER", "postgres")
os.environ.setdefault("COINBASE_DB_PASSWORD", "postgres")

import pytest
import json
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any

# Add project root to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


# ===================== PROD-DB CONNECTION GUARD =====================

# Belt-and-suspenders: even if a test passes explicit `port=5432`, refuse to
# connect. To run a test against prod (you almost never should), set
# `ALLOW_PROD_DB=1` in the environment.
def _install_prod_db_guard():
    from database import database as _db_mod

    _original_connect = _db_mod.PostgresDB.connect

    def _guarded_connect(self):
        if (
            self.port == 5432
            and self.host in ("127.0.0.1", "localhost")
            and os.environ.get("ALLOW_PROD_DB") != "1"
        ):
            raise RuntimeError(
                f"REFUSED: test attempted to connect to prod DB at "
                f"{self.host}:{self.port}. Use port 9876 (test instance) or "
                f"set ALLOW_PROD_DB=1 to override."
            )
        return _original_connect(self)

    _db_mod.PostgresDB.connect = _guarded_connect


_install_prod_db_guard()


# ===================== MARKERS =====================

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "external: mark test as external API test (requires credentials)"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
    config.addinivalue_line(
        "markers", "regression: mark test as regression test (must pass before deploy)"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as integration test (touches real DB / external services)"
    )
    config.addinivalue_line(
        "markers", "serial: mark test as requiring the serial regression lane"
    )


# ===================== FIXTURES =====================

@pytest.fixture
def project_root():
    """Path to project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture
def api_reference(project_root):
    """Access to api_reference directory for Coinbase response samples."""
    return project_root / "api_reference"


@pytest.fixture
def websocket_reference(project_root):
    """Access to websocket_reference directory for WebSocket message samples."""
    return project_root / "websocket_reference"


@pytest.fixture
def fixtures_dir(project_root):
    """Access to test fixtures directory."""
    return project_root / "tests" / "fixtures"


# ===================== SAMPLE ORDER FIXTURES =====================

@pytest.fixture
def sample_stealth_order():
    """Sample stealth order data for testing."""
    return {
        "stealth_order_id": "test-order-123",
        "product_id": "BTC-USDC",
        "side": "BUY",
        "total_size": 1.0,
        "revealed_size": 0.0,
        "remaining_size": 1.0,
        "executed_size": 0.0,
        "limit_price": 50000.0,
        "status": "HIDDEN",
        "reveal_condition_type": "price_threshold",
        "reveal_condition_json": {
            "type": "price_threshold",
            "direction": "below",
            "price_threshold": 45000.0,
            "hold_duration_seconds": 60
        },
        "sizing_strategy_json": {
            "strategy": "equal_slices",
            "num_slices": 5
        },
        "revealed_orders": [],
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "visibility_score": 0.0,
        "notes": "Test order"
    }


@pytest.fixture
def revealed_stealth_order(sample_stealth_order):
    """Sample stealth order that has been fully revealed."""
    order = sample_stealth_order.copy()
    order["status"] = "REVEALED"
    order["revealed_size"] = 1.0
    order["remaining_size"] = 0.0
    order["revealed_orders"] = [
        {
            "reveal_number": 1,
            "revealed_size": 0.2,
            "placement_price": 50000.0,
            "placed_order_id": "coinbase-order-1",
            "reveal_time": datetime.utcnow() - timedelta(minutes=5),
            "market_price": 48000.0
        }
    ]
    return order


@pytest.fixture
def sample_market_data():
    """Sample market data for testing evaluators."""
    return {
        "product_id": "BTC-USDC",
        "price": 48500.0,
        "bid": 48400.0,
        "ask": 48600.0,
        "volume_1m": 150.5,
        "volume_24h": 45000.0,
        "timestamp": datetime.utcnow()
    }


# ===================== DATABASE FIXTURES =====================

@pytest.fixture
def mock_db_client():
    """Mock database client for testing without real database."""
    class MockDBClient:
        def __init__(self):
            self.orders = {}  # In-memory storage
        
        def execute_query(self, query: str, params: tuple = None) -> list:
            """Mock query execution."""
            return []
        
        def execute_update(self, query: str, params: tuple = None) -> None:
            """Mock update execution."""
            pass
        
        def close(self) -> None:
            """Mock close."""
            pass
    
    return MockDBClient()


# ===================== API RESPONSE FIXTURES =====================

@pytest.fixture
def coinbase_list_orders_response():
    """Sample Coinbase API response for list orders."""
    return {
        "orders": [
            {
                "order_id": "123e4567-e89b-12d3-a456-426614174000",
                "product_id": "BTC-USDC",
                "side": "BUY",
                "order_type": "limit",
                "time_in_force": "GOOD_UNTIL_CANCELLED",
                "limit_price": "50000.00",
                "size": "1.0",
                "status": "OPEN",
                "created_time": "2026-04-19T10:00:00Z"
            }
        ]
    }


@pytest.fixture
def coinbase_create_order_response():
    """Sample Coinbase API response for order creation."""
    return {
        "success": True,
        "order_id": "123e4567-e89b-12d3-a456-426614174001",
        "product_id": "BTC-USDC",
        "side": "BUY",
        "order_type": "limit",
        "limit_price": "50000.00",
        "size": "1.0",
        "status": "PENDING"
    }


@pytest.fixture
def coinbase_cancel_order_response():
    """Sample Coinbase API response for order cancellation."""
    return {
        "success": True,
        "order_id": "123e4567-e89b-12d3-a456-426614174001"
    }


# ===================== WEBSOCKET FIXTURES =====================

@pytest.fixture
def sample_ticker_message():
    """Sample WebSocket ticker message from Coinbase."""
    return {
        "type": "ticker",
        "product_id": "BTC-USDC",
        "price": "48500.00",
        "time": "2026-04-19T10:00:00.000000Z",
        "best_bid": "48400.00",
        "best_ask": "48600.00",
        "side": "buy",
        "last_size": "0.1"
    }


@pytest.fixture
def sample_done_message():
    """Sample WebSocket done message (order fill)."""
    return {
        "type": "done",
        "product_id": "BTC-USDC",
        "order_id": "d50ec984-77a8-460a-b958-66f114b0de9b",
        "reason": "filled",
        "side": "buy",
        "price": "49500.00",
        "remaining_size": "0"
    }


# ===================== MOCK FACTORIES =====================

@pytest.fixture
def stealth_order_factory():
    """Factory for creating test stealth orders with custom attributes."""
    def _create_order(**kwargs):
        order = {
            "stealth_order_id": kwargs.get("stealth_order_id", f"test-{datetime.utcnow().timestamp()}"),
            "product_id": kwargs.get("product_id", "BTC-USDC"),
            "side": kwargs.get("side", "BUY"),
            "total_size": kwargs.get("total_size", 1.0),
            "revealed_size": kwargs.get("revealed_size", 0.0),
            "remaining_size": kwargs.get("remaining_size", 1.0),
            "limit_price": kwargs.get("limit_price", 50000.0),
            "status": kwargs.get("status", "HIDDEN"),
            "reveal_condition_type": kwargs.get("reveal_condition_type", "price_threshold"),
            "reveal_condition_json": kwargs.get("reveal_condition_json", {}),
            "created_at": kwargs.get("created_at", datetime.utcnow()),
            "updated_at": kwargs.get("updated_at", datetime.utcnow()),
        }
        return order
    
    return _create_order


# ===================== CONFIGURATION =====================

@pytest.fixture(scope="session")
def test_config():
    """Test configuration settings."""
    return {
        "database_url": ":memory:",  # Use in-memory SQLite for tests
        "api_timeout": 5,  # Short timeout for tests
        "websocket_timeout": 10,
        "max_retries": 2
    }
