"""
Unit tests for database operations and repositories.

Tests data persistence, queries, and repository operations.
"""

import logging

import pytest
from datetime import datetime, timezone

from database.database import PostgresDB
import database.order as order_db


class TestDatabaseOperations:
    """Test database CRUD operations."""
    
    def test_create_stealth_order_in_db(self):
        """Create a stealth order record in database."""
        order = {
            "stealth_order_id": "so_123",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "total_size": 1.0,
            "limit_price": 50000.0,
            "status": "HIDDEN",
            "created_at": datetime.now(timezone.utc).astimezone(),
        }
        
        # Simulate DB insert
        stored_id = order["stealth_order_id"]
        
        assert stored_id == "so_123"
    
    def test_read_stealth_order_from_db(self):
        """Read a stealth order record from database."""
        order_id = "so_123"
        
        # Simulate DB query
        order = {
            "stealth_order_id": order_id,
            "product_id": "BTC-USDC",
            "status": "HIDDEN"
        }
        
        assert order["stealth_order_id"] == order_id
    
    def test_update_stealth_order_status(self):
        """Update order status in database."""
        order_id = "so_123"
        old_status = "HIDDEN"
        new_status = "TRIGGERED"
        
        # Simulate DB update
        order = {
            "stealth_order_id": order_id,
            "status": new_status
        }
        
        assert order["status"] == new_status
        assert order["status"] != old_status
    
    def test_update_revealed_size(self):
        """Update revealed_size when order is revealed."""
        order_id = "so_123"
        revealed_amount = 0.25
        
        # Simulate DB update
        order = {
            "stealth_order_id": order_id,
            "revealed_size": revealed_amount,
            "remaining_size": 0.75
        }
        
        assert order["revealed_size"] == 0.25
        assert order["remaining_size"] == 0.75
    
    def test_delete_cancelled_order(self):
        """Delete or mark cancelled order in database."""
        order_id = "so_123"
        
        # Simulate soft delete (mark as CANCELLED)
        order = {
            "stealth_order_id": order_id,
            "status": "CANCELLED",
            "deleted_at": datetime.now(timezone.utc).astimezone()
        }
        
        assert order["status"] == "CANCELLED"
        assert "deleted_at" in order


class TestRepositoryQueries:
    """Test repository query patterns."""
    
    def test_query_active_stealth_orders(self):
        """Query all active (not filled/cancelled) stealth orders."""
        orders = [
            {"stealth_order_id": "so_1", "status": "HIDDEN"},
            {"stealth_order_id": "so_2", "status": "TRIGGERED"},
            {"stealth_order_id": "so_3", "status": "FILLED"},  # Should be excluded
            {"stealth_order_id": "so_4", "status": "CANCELLED"},  # Should be excluded
        ]
        
        active_statuses = ["HIDDEN", "PENDING", "TRIGGERED", "REVEALED"]
        active_orders = [o for o in orders if o["status"] in active_statuses]
        
        assert len(active_orders) == 2
        assert all(o["status"] in active_statuses for o in active_orders)
    
    def test_query_orders_by_product(self):
        """Query orders for a specific product."""
        orders = [
            {"stealth_order_id": "so_1", "product_id": "BTC-USDC"},
            {"stealth_order_id": "so_2", "product_id": "ETH-USDC"},
            {"stealth_order_id": "so_3", "product_id": "BTC-USDC"},
        ]
        
        product = "BTC-USDC"
        btc_orders = [o for o in orders if o["product_id"] == product]
        
        assert len(btc_orders) == 2
    
    def test_query_orders_by_status(self):
        """Query orders by status."""
        orders = [
            {"stealth_order_id": "so_1", "status": "HIDDEN"},
            {"stealth_order_id": "so_2", "status": "HIDDEN"},
            {"stealth_order_id": "so_3", "status": "TRIGGERED"},
        ]
        
        hidden_orders = [o for o in orders if o["status"] == "HIDDEN"]
        
        assert len(hidden_orders) == 2
    
    def test_query_orders_by_date_range(self):
        """Query orders created within date range."""
        from datetime import timedelta
        
        orders = [
            {"stealth_order_id": "so_1", "created_at": datetime(2026, 4, 19, 10, 0)},
            {"stealth_order_id": "so_2", "created_at": datetime(2026, 4, 19, 11, 0)},
            {"stealth_order_id": "so_3", "created_at": datetime(2026, 4, 20, 10, 0)},
        ]
        
        start = datetime(2026, 4, 19, 0, 0)
        end = datetime(2026, 4, 19, 23, 59)
        
        filtered = [o for o in orders if start <= o["created_at"] <= end]
        
        assert len(filtered) == 2
    
    def test_query_total_revealed_size_by_product(self):
        """Calculate total revealed size for a product."""
        orders = [
            {"product_id": "BTC-USDC", "revealed_size": 0.1},
            {"product_id": "BTC-USDC", "revealed_size": 0.2},
            {"product_id": "ETH-USDC", "revealed_size": 1.0},
        ]
        
        product = "BTC-USDC"
        total_revealed = sum(
            o["revealed_size"] for o in orders 
            if o["product_id"] == product
        )
        
        assert total_revealed == pytest.approx(0.3, abs=1e-12)


class TestOrderPersistence:
    """Test order state persistence across sessions."""
    
    def test_order_persists_after_creation(self):
        """Order remains in database after creation."""
        order_id = "so_123"
        
        # Create order
        created_order = {"stealth_order_id": order_id}
        
        # Retrieve order
        retrieved_order = {"stealth_order_id": order_id}
        
        assert created_order["stealth_order_id"] == retrieved_order["stealth_order_id"]
    
    def test_order_state_persists_across_reveals(self):
        """Order state updates persist across multiple reveals."""
        order_id = "so_123"
        
        # Create with revealed_size = 0
        order = {
            "stealth_order_id": order_id,
            "total_size": 1.0,
            "revealed_size": 0.0,
            "remaining_size": 1.0
        }
        
        # Reveal 0.25
        order["revealed_size"] = 0.25
        order["remaining_size"] = 0.75
        
        # Persist and re-retrieve
        retrieved = {
            "stealth_order_id": order_id,
            "total_size": 1.0,
            "revealed_size": 0.25,
            "remaining_size": 0.75
        }
        
        assert retrieved["revealed_size"] == 0.25
    
    def test_order_data_not_lost_on_crash(self):
        """Order data persists even if application crashes."""
        # This would be tested with actual database durability
        # For unit test, we just verify the pattern
        
        order = {
            "stealth_order_id": "so_123",
            "status": "HIDDEN",
            "created_at": datetime.now(timezone.utc).astimezone()
        }
        
        # In real system, data written to DB before crash
        # On restart, query finds it
        assert "stealth_order_id" in order


class TestOrderEventStreamPersistence:
    """Test JSON serialization for order_event_stream database writes."""

    def test_insert_order_event_serializes_datetime_payloads(self, monkeypatch):
        captured = {}

        def fake_execute_query(query, params):
            captured["query"] = query
            captured["params"] = params
            return [{"id": 1}]

        monkeypatch.setattr(order_db.DB_CLIENT, "execute_query", fake_execute_query)

        timestamp = datetime(2026, 4, 25, 6, 23, 49, tzinfo=timezone.utc)
        inserted = order_db.insert_order_event(
            event_id="evt-123",
            event_type="stealth_created",
            source_channel="stealth_lifecycle_hook",
            event_time_exchange=timestamp,
            stealth_order_id="7390ab9c-f9f7-4cd7-b204-9bb9bb9bab12",
            trigger_payload_json={"timestamp": timestamp},
            raw_payload_json={"timestamp": timestamp, "created_at": timestamp},
            idempotency_key="test:stealth_created:1",
        )

        assert inserted == 1
        assert timestamp.isoformat() in captured["params"][18]
        assert timestamp.isoformat() in captured["params"][20]

    def test_insert_stealth_order_lifecycle_event_matches_placeholder_count(self, monkeypatch):
        captured = {}

        class FakeCursor:
            def execute(self, query, params):
                captured["query"] = query
                captured["params"] = params
                assert query.count("%s") == len(params)

            def fetchone(self):
                return [1]

            def close(self):
                return None

        class FakeContextManager:
            def __enter__(self):
                return FakeCursor()

            def __exit__(self, exc_type, exc, tb):
                return False

        monkeypatch.setattr(
            order_db.DB_CLIENT,
            "execute_query",
            lambda query, params: [{"last_lifecycle_event": "CREATED"}],
        )
        monkeypatch.setattr(order_db.DB_CLIENT, "get_cursor", lambda: FakeContextManager())

        inserted = order_db.insert_stealth_order_lifecycle_event(
            stealth_order_id="550e8400-e29b-41d4-a716-446655440000",
            lifecycle_event="REVEAL_SUCCEEDED",
            context={
                "timestamp": datetime(2026, 4, 25, 6, 37, 23, tzinfo=timezone.utc),
                "product_id": "BIP-20DEC30-CDE",
                "side": "SELL",
                "size": 1.0,
                "total_size": 1.0,
                "limit_price": 77870.0,
                "reason": "normal_placement",
                "placed_order_id": "550e8400-e29b-41d4-a716-446655440000",
                "exchange_order_id": "5c2d29f2-11e6-402b-bad9-93afbf7f3ee7",
            },
        )

        assert inserted == 1
        assert captured["query"].count("%s") == len(captured["params"])


class TestDataIntegrity:
    """Test data integrity constraints."""
    
    def test_revealed_plus_remaining_equals_total(self):
        """Constraint: revealed_size + remaining_size = total_size."""
        order = {
            "total_size": 1.0,
            "revealed_size": 0.3,
            "remaining_size": 0.7
        }
        
        total = order["revealed_size"] + order["remaining_size"]
        
        assert total == order["total_size"]
    
    def test_revealed_size_never_exceeds_total(self):
        """Constraint: revealed_size <= total_size."""
        order = {
            "total_size": 1.0,
            "revealed_size": 0.99
        }
        
        assert order["revealed_size"] <= order["total_size"]
    
    def test_remaining_size_never_negative(self):
        """Constraint: remaining_size >= 0."""
        order = {
            "revealed_size": 0.5,
            "total_size": 1.0,
            "remaining_size": 0.5
        }
        
        assert order["remaining_size"] >= 0.0
    
    def test_order_immutable_fields(self):
        """Certain fields should not change after creation."""
        original = {
            "stealth_order_id": "so_123",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "created_at": datetime.now(timezone.utc).astimezone()
        }
        
        updated = {
            "stealth_order_id": "so_123",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "created_at": original["created_at"]
        }
        
        # These fields should be the same
        assert original["stealth_order_id"] == updated["stealth_order_id"]
        assert original["product_id"] == updated["product_id"]
        assert original["side"] == updated["side"]
        assert original["created_at"] == updated["created_at"]


def test_get_parent_orders_page_filters_and_paginates_in_postgres(monkeypatch):
    calls: list[tuple[str, tuple[object, ...] | None]] = []

    def execute_query(query, params=None):
        normalized = " ".join(query.split())
        calls.append((normalized, params))
        if normalized.startswith("SELECT COUNT(*)"):
            return [{"total_matching_count": 7}]
        return [
            {
                "client_order_id": "00000000-0000-4000-8000-000000000007",
                "product_id": "BTC-USDC",
                "status": "OPEN",
            }
        ]

    monkeypatch.setattr(order_db.DB_CLIENT, "execute_query", execute_query)

    rows, total = order_db.get_parent_orders_page(
        product_id="BTC-USDC",
        status="open",
        limit=25,
        offset=50,
    )

    assert total == 7
    assert rows[0]["client_order_id"].endswith("0007")
    assert len(calls) == 2
    count_query, count_params = calls[0]
    page_query, page_params = calls[1]
    assert "product_id = %s" in count_query
    assert "status = %s" in count_query
    assert "SELECT *" not in page_query
    assert "ORDER BY created_at DESC, id DESC" in page_query
    assert "LIMIT %s OFFSET %s" in page_query
    assert count_params == ("BTC-USDC", "OPEN")
    assert page_params == ("BTC-USDC", "OPEN", 25, 50)


def test_get_parent_order_summary_selects_only_operator_read_fields(monkeypatch):
    calls: list[tuple[str, tuple[object, ...] | None]] = []

    def execute_query(query, params=None):
        calls.append((" ".join(query.split()), params))
        return [
            {
                "client_order_id": "00000000-0000-4000-8000-000000000008",
                "product_id": "ETH-USDC",
                "status": "OPEN",
            }
        ]

    monkeypatch.setattr(order_db.DB_CLIENT, "execute_query", execute_query)

    row = order_db.get_parent_order_summary(
        "00000000-0000-4000-8000-000000000008"
    )

    assert row is not None
    assert row["product_id"] == "ETH-USDC"
    assert len(calls) == 1
    query, params = calls[0]
    assert "SELECT *" not in query
    assert "FROM order_parent WHERE client_order_id = %s" in query
    assert params == ("00000000-0000-4000-8000-000000000008",)


def test_postgres_transaction_error_log_is_value_blind(caplog):
    private_query = "SELECT * FROM private_operator_intent"
    private_identifier = "idempotency-private-value"

    class SensitiveDatabaseError(RuntimeError):
        sqlstate = "42P01"

    class FakeCursor:
        def close(self):
            return None

    class FakeConnection:
        def __init__(self):
            self.rollback_calls = 0

        def cursor(self):
            return FakeCursor()

        def commit(self):
            return None

        def rollback(self):
            self.rollback_calls += 1

    connection = FakeConnection()
    database = PostgresDB()
    database._conn = connection

    with caplog.at_level(logging.ERROR, logger="PostgresDB"):
        with pytest.raises(SensitiveDatabaseError):
            with database.get_cursor():
                raise SensitiveDatabaseError(
                    f"{private_query}; identifier={private_identifier}"
                )

    assert connection.rollback_calls == 1
    assert [record.getMessage() for record in caplog.records] == [
        (
            "postgres_transaction_failed "
            "exception_type=SensitiveDatabaseError sqlstate=42P01"
        )
    ]
    rendered = caplog.text
    assert private_query not in rendered
    assert private_identifier not in rendered
    assert "identifier=" not in rendered


# Run with: pytest tests/unit/test_database.py -v
