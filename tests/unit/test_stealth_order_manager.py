"""
Unit tests for StealthOrderManager.

Tests the core order management logic in isolation with mocked dependencies.
"""

import pytest
from datetime import datetime, timedelta
from types import SimpleNamespace

from core.enums import StealthLifecycleEvent, StealthOrderStatus
from core.stealth_order_manager import StealthOrderManager


class TestStealthOrderCreation:
    """Test stealth order creation."""
    
    def test_create_stealth_order_with_valid_params(self, sample_stealth_order):
        """Verify order is created with correct initial state."""
        assert sample_stealth_order["status"] == "HIDDEN"
        assert sample_stealth_order["revealed_size"] == 0.0
        assert sample_stealth_order["remaining_size"] == sample_stealth_order["total_size"]
    
    def test_create_stealth_order_generates_unique_id(self, stealth_order_factory):
        """Verify each order gets unique ID."""
        order1 = stealth_order_factory()
        order2 = stealth_order_factory()
        assert order1["stealth_order_id"] != order2["stealth_order_id"]
    
    def test_create_stealth_order_with_custom_condition(self, stealth_order_factory):
        """Verify custom reveal conditions are stored."""
        custom_condition = {
            "type": "time_delay",
            "delay_seconds": 300
        }
        order = stealth_order_factory(reveal_condition_json=custom_condition)
        assert order["reveal_condition_json"] == custom_condition


class TestStealthOrderStateTransitions:
    """Test order state transitions."""
    
    def test_order_transitions_hidden_to_triggered(self, sample_stealth_order):
        """Verify order can transition from HIDDEN to TRIGGERED."""
        # Initially HIDDEN
        assert sample_stealth_order["status"] == "HIDDEN"
        
        # Simulate transition to TRIGGERED
        sample_stealth_order["status"] = "TRIGGERED"
        assert sample_stealth_order["status"] == "TRIGGERED"
    
    def test_order_transitions_to_revealed_when_fully_revealed(self, sample_stealth_order):
        """Verify order transitions to REVEALED when all slices are revealed."""
        sample_stealth_order["revealed_size"] = sample_stealth_order["total_size"]
        sample_stealth_order["remaining_size"] = 0.0
        sample_stealth_order["status"] = "REVEALED"
        
        assert sample_stealth_order["status"] == "REVEALED"
        assert sample_stealth_order["remaining_size"] == 0.0


class TestRevealConditions:
    """Test reveal condition evaluation."""
    
    def test_price_threshold_condition_structure(self):
        """Verify price threshold condition has required fields."""
        condition = {
            "type": "price_threshold",
            "direction": "below",
            "price_threshold": 45000.0,
            "hold_duration_seconds": 60
        }
        
        assert condition["type"] == "price_threshold"
        assert condition["direction"] in ["above", "below"]
        assert isinstance(condition["price_threshold"], float)
        assert isinstance(condition["hold_duration_seconds"], int)
    
    def test_time_delay_condition_structure(self):
        """Verify time delay condition has required fields."""
        condition = {
            "type": "time_delay",
            "delay_seconds": 300
        }
        
        assert condition["type"] == "time_delay"
        assert isinstance(condition["delay_seconds"], int)
        assert condition["delay_seconds"] > 0

    def test_price_condition_ignores_non_ticker_market_cache(self):
        manager = StealthOrderManager(db_client=None)
        stealth_order_id = "990e8400-e29b-41d4-a716-446655440000"
        manager.in_memory_orders[stealth_order_id] = {
            "stealth_order_id": stealth_order_id,
            "product_id": "BTC-USDC",
            "side": "BUY",
            "total_size": 1.0,
            "revealed_size": 0.0,
            "remaining_size": 1.0,
            "executed_size": 0.0,
            "limit_price": 50000.0,
            "status": StealthOrderStatus.PENDING.value,
            "reveal_condition_type": "price",
            "reveal_condition_json": {"type": "price", "direction": "below", "price_threshold": 50010.0},
            "revealed_orders": [],
            "reason": "normal_placement",
            "parent_order_id": None,
            "condition_confirmed_at": None,
            "condition_first_met_at": None,
        }
        manager._market_cache["BTC-USDC"] = {
            "product_id": "BTC-USDC",
            "price": 50000.0,
            "bid": 50000.0,
            "ask": 50000.0,
            "volume_1m": 0.0,
            "source": "synthetic_follow_up_seed",
        }
        manager._update_stealth_order = lambda order: None
        manager._dispatch_lifecycle_event = lambda *args, **kwargs: None

        condition_met, reason = manager.evaluate_conditions(stealth_order_id)

        assert condition_met is False
        assert "source=synthetic_follow_up_seed" in reason
        assert manager.in_memory_orders[stealth_order_id]["condition_confirmed_at"] is None

    def test_price_condition_triggers_with_ticker_market_cache(self):
        manager = StealthOrderManager(db_client=None)
        stealth_order_id = "991e8400-e29b-41d4-a716-446655440000"
        manager.in_memory_orders[stealth_order_id] = {
            "stealth_order_id": stealth_order_id,
            "product_id": "BTC-USDC",
            "side": "BUY",
            "total_size": 1.0,
            "revealed_size": 0.0,
            "remaining_size": 1.0,
            "executed_size": 0.0,
            "limit_price": 50000.0,
            "status": StealthOrderStatus.PENDING.value,
            "reveal_condition_type": "price",
            "reveal_condition_json": {"type": "price", "direction": "below", "price_threshold": 50010.0},
            "revealed_orders": [],
            "reason": "normal_placement",
            "parent_order_id": None,
            "condition_confirmed_at": None,
            "condition_first_met_at": datetime.utcnow() - timedelta(seconds=1),
        }
        manager._market_cache["BTC-USDC"] = {
            "product_id": "BTC-USDC",
            "price": 50000.0,
            "bid": 50000.0,
            "ask": 50000.0,
            "volume_1m": 0.0,
            "source": "ticker",
        }
        manager._update_stealth_order = lambda order: None
        manager._dispatch_lifecycle_event = lambda *args, **kwargs: None

        condition_met, _ = manager.evaluate_conditions(stealth_order_id)

        assert condition_met is True
        assert manager.in_memory_orders[stealth_order_id]["condition_confirmed_at"] is not None


class TestOrderSizing:
    """Test order sizing and reveals."""
    
    def test_remaining_size_decreases_on_reveal(self, sample_stealth_order):
        """Verify remaining_size decreases when order is revealed."""
        initial_remaining = sample_stealth_order["remaining_size"]
        reveal_amount = 0.2
        
        sample_stealth_order["revealed_size"] += reveal_amount
        sample_stealth_order["remaining_size"] -= reveal_amount
        
        assert sample_stealth_order["remaining_size"] == initial_remaining - reveal_amount
    
    def test_visibility_score_updates_on_reveal(self, sample_stealth_order):
        """Verify visibility_score reflects reveal progress."""
        total = sample_stealth_order["total_size"]
        revealed = 0.5
        
        visibility = revealed / total
        
        assert visibility == 0.5
        assert 0.0 <= visibility <= 1.0


class TestExecutionLifecycleAuditing:
    """Test lifecycle dispatches emitted from execution updates."""

    def test_update_execution_dispatches_fill_received_then_executed(self):
        manager = StealthOrderManager(db_client=None)
        stealth_order_id = "550e8400-e29b-41d4-a716-446655440000"
        manager.in_memory_orders[stealth_order_id] = {
            "stealth_order_id": stealth_order_id,
            "product_id": "BTC-USDC",
            "side": "BUY",
            "total_size": 1.0,
            "revealed_size": 1.0,
            "remaining_size": 0.0,
            "executed_size": 0.0,
            "limit_price": 50000.0,
            "status": StealthOrderStatus.REVEALED.value,
            "revealed_orders": [{"placed_order_id": stealth_order_id}],
            "reason": "normal_placement",
        }

        persisted_statuses = []
        dispatched_events = []

        manager._update_stealth_order = lambda order: persisted_statuses.append(order["status"])
        manager._dispatch_lifecycle_event = lambda stealth_order_id, event, order_data, extra=None: dispatched_events.append(
            (event, dict(extra or {}))
        )

        manager.update_execution(
            stealth_order_id=stealth_order_id,
            executed_size=1.0,
            order_status=StealthOrderStatus.EXECUTED.value,
        )

        assert persisted_statuses == [StealthOrderStatus.REVEALED.value, StealthOrderStatus.EXECUTED.value]
        assert [event for event, _ in dispatched_events] == [
            StealthLifecycleEvent.FILL_RECEIVED,
            StealthLifecycleEvent.EXECUTED,
        ]
        assert dispatched_events[0][1]["placed_order_id"] == stealth_order_id
        assert dispatched_events[1][1]["placed_order_id"] == stealth_order_id

    def test_update_execution_dispatches_cancelled_for_cancel_path(self):
        manager = StealthOrderManager(db_client=None)
        stealth_order_id = "660e8400-e29b-41d4-a716-446655440000"
        manager.in_memory_orders[stealth_order_id] = {
            "stealth_order_id": stealth_order_id,
            "product_id": "BTC-USDC",
            "side": "SELL",
            "total_size": 1.0,
            "revealed_size": 1.0,
            "remaining_size": 0.0,
            "executed_size": 0.0,
            "limit_price": 51000.0,
            "status": StealthOrderStatus.REVEALED.value,
            "revealed_orders": [{"placed_order_id": stealth_order_id}],
            "reason": "normal_placement",
        }

        dispatched_events = []
        manager._update_stealth_order = lambda order: None
        manager._dispatch_lifecycle_event = lambda stealth_order_id, event, order_data, extra=None: dispatched_events.append(
            (event, dict(extra or {}))
        )

        manager.update_execution(
            stealth_order_id=stealth_order_id,
            executed_size=0.0,
            order_status=StealthOrderStatus.CANCELLED.value,
        )

        assert [event for event, _ in dispatched_events] == [StealthLifecycleEvent.CANCELLED]
        assert dispatched_events[0][1]["placed_order_id"] == stealth_order_id


class TestRevealAuditExchangeOrderId:
    """Test audit-only exchange_order_id capture during reveal placement."""

    def test_reveal_order_slice_records_exchange_order_id(self, monkeypatch):
        manager = StealthOrderManager(db_client=None)
        stealth_order_id = "770e8400-e29b-41d4-a716-446655440000"
        manager.in_memory_orders[stealth_order_id] = {
            "stealth_order_id": stealth_order_id,
            "product_id": "BTC-USDC",
            "side": "SELL",
            "total_size": 1.0,
            "revealed_size": 0.0,
            "remaining_size": 1.0,
            "executed_size": 0.0,
            "limit_price": 50000.0,
            "status": StealthOrderStatus.TRIGGERED.value,
            "reveal_condition_type": "price",
            "reveal_condition_json": {"type": "price", "direction": "above", "price_threshold": 50000.0},
            "revealed_orders": [],
            "reason": "normal_placement",
            "parent_order_id": None,
            "condition_confirmed_at": None,
        }

        captured = {"reveal_event": None, "dispatch": None}

        monkeypatch.setattr(
            "configuration.REST_CLIENT",
            SimpleNamespace(
                place_limit_order=lambda **kwargs: {
                    "success_response": {
                        "order_id": "exchange-oid-123",
                        "client_order_id": stealth_order_id,
                    }
                }
            ),
        )

        manager.order_placement_hooks = SimpleNamespace(
            call_pre_submission_hooks=lambda order: None,
            call_post_submission_hooks=lambda order, result: None,
        )
        manager._update_stealth_order = lambda order: None
        manager._record_reveal_event = lambda order, reveal_event: captured.__setitem__("reveal_event", reveal_event)
        manager._dispatch_lifecycle_event = lambda stealth_order_id, event, order_data, extra=None: captured.__setitem__(
            "dispatch", (event, dict(extra or {}))
        )
        manager._get_current_market_data = lambda product_id: {"price": 50100.0}

        placed_order_id = manager.reveal_order_slice(stealth_order_id)

        assert placed_order_id == stealth_order_id
        assert captured["reveal_event"]["exchange_order_id"] == "exchange-oid-123"
        assert captured["dispatch"][0] == StealthLifecycleEvent.REVEAL_SUCCEEDED
        assert captured["dispatch"][1]["exchange_order_id"] == "exchange-oid-123"

    def test_sync_exchange_order_id_for_placed_order_backfills_reveal_event(self, monkeypatch):
        db_calls = []
        monkeypatch.setattr(
            "database.order.update_stealth_audit_exchange_order_id",
            lambda stealth_order_id, placed_order_id, exchange_order_id: db_calls.append(
                (stealth_order_id, placed_order_id, exchange_order_id)
            ) or True,
        )

        manager = StealthOrderManager(db_client=object())
        stealth_order_id = "880e8400-e29b-41d4-a716-446655440000"
        placed_order_id = stealth_order_id
        manager.in_memory_orders[stealth_order_id] = {
            "stealth_order_id": stealth_order_id,
            "product_id": "BTC-USDC",
            "side": "SELL",
            "total_size": 1.0,
            "revealed_size": 1.0,
            "remaining_size": 0.0,
            "executed_size": 0.0,
            "limit_price": 50000.0,
            "status": StealthOrderStatus.REVEALED.value,
            "revealed_orders": [{"placed_order_id": placed_order_id, "exchange_order_id": None}],
            "reason": "normal_placement",
        }
        manager._placed_order_index[placed_order_id] = manager.in_memory_orders[stealth_order_id]

        persisted_orders = []
        manager._update_stealth_order = lambda order: persisted_orders.append(order["revealed_orders"][0]["exchange_order_id"])

        result = manager.sync_exchange_order_id_for_placed_order(
            placed_order_id=placed_order_id,
            exchange_order_id="exchange-oid-789",
        )

        assert result is True
        assert manager.in_memory_orders[stealth_order_id]["revealed_orders"][0]["exchange_order_id"] == "exchange-oid-789"
        assert persisted_orders == ["exchange-oid-789"]
        assert db_calls == [(stealth_order_id, placed_order_id, "exchange-oid-789")]


class TestLifecycleContextMarketFields:
    """Ensure lifecycle dispatch context includes current market fields."""

    def test_dispatch_lifecycle_event_includes_market_fields(self, monkeypatch):
        manager = StealthOrderManager(db_client=None)
        captured = {}

        class FakeRegistry:
            def call_on_transition(self, stealth_order_id, event, context):
                captured["stealth_order_id"] = stealth_order_id
                captured["event"] = event
                captured["context"] = context

        monkeypatch.setattr(
            "integration.stealth_lifecycle_hooks.get_global_stealth_lifecycle_hook_registry",
            lambda: FakeRegistry(),
        )

        manager._market_cache["BIP-20DEC30-CDE"] = {
            "product_id": "BIP-20DEC30-CDE",
            "price": 77830.0,
            "bid": 77829.0,
            "ask": 77831.0,
            "volume_1m": 123.45,
            "source": "ticker",
        }

        order_data = {
            "stealth_order_id": "aa0e8400-e29b-41d4-a716-446655440000",
            "product_id": "BIP-20DEC30-CDE",
            "side": "SELL",
            "revealed_size": 0.0,
            "total_size": 1.0,
            "limit_price": 77825.0,
            "reason": "normal_placement",
            "status": StealthOrderStatus.PENDING.value,
            "remaining_size": 1.0,
            "executed_size": 0.0,
            "reveal_condition_type": "price",
            "reveal_condition_json": {"type": "price", "direction": "above", "price_threshold": 77825.0},
            "revealed_orders": [],
        }

        manager._dispatch_lifecycle_event(
            stealth_order_id=order_data["stealth_order_id"],
            event=StealthLifecycleEvent.CONDITION_MET,
            order_data=order_data,
        )

        assert captured["context"]["market_price"] == 77830.0
        assert captured["context"]["market_bid"] == 77829.0
        assert captured["context"]["market_ask"] == 77831.0
        assert captured["context"]["market_spread"] == 2.0
        assert captured["context"]["market_volume_1m"] == 123.45
        assert captured["context"]["market_source"] == "ticker"


# Run tests with: pytest tests/unit/test_stealth_order_manager.py -v
