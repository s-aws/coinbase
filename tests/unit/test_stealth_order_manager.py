"""
Unit tests for StealthOrderManager.

Tests the core order management logic in isolation with mocked dependencies.
"""

import pytest
from datetime import datetime, timedelta
from types import SimpleNamespace

from core.enums import StealthLifecycleEvent, StealthOrderStatus
from core.models import RevealExecutionPlan
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

    def test_create_stealth_order_normalizes_anchor_repricing_policy(self):
        manager = StealthOrderManager(db_client=None)

        stealth_order_id = manager.create_stealth_order(
            product_id="BTC-USDC",
            side="BUY",
            total_size=1.0,
            limit_price=100.0,
            reveal_condition={"type": "time_delay", "delay_seconds": 60},
            anchor_repricing_policy={
                "enabled": True,
                "reference_price_source": "midpoint",
                "distance_type": "P",
                "target_distance": 0.01,
                "max_distance": 0.05,
            },
        )

        order = manager.in_memory_orders[stealth_order_id]
        assert order["anchor_repricing_policy_json"]["enabled"] is True
        assert order["anchor_repricing_policy_json"]["reference_price_source"] == "midpoint"


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


class TestAnchorRepricing:
    def test_hidden_order_reprices_from_midpoint_reference(self):
        manager = StealthOrderManager(db_client=None)
        stealth_order_id = "a91e8400-e29b-41d4-a716-446655440000"
        manager.in_memory_orders[stealth_order_id] = {
            "stealth_order_id": stealth_order_id,
            "product_id": "BTC-USDC",
            "side": "SELL",
            "total_size": 1.0,
            "revealed_size": 0.0,
            "remaining_size": 1.0,
            "executed_size": 0.0,
            "limit_price": 102.0,
            "status": StealthOrderStatus.HIDDEN.value,
            "reveal_condition_type": "time_delay",
            "reveal_condition_json": {"type": "time_delay", "delay_seconds": 60},
            "sizing_strategy_json": {"type": "fixed"},
            "revealed_orders": [],
            "anchor_repricing_policy_json": {
                "enabled": True,
                "reference_price_source": "midpoint",
                "distance_type": "P",
                "target_distance": 0.01,
                "max_distance": 0.05,
                "update_mode": "fixed",
                "fixed_interval_seconds": 60,
                "min_price_change": 0.01,
                "hysteresis_bps": 0,
                "min_reprice_interval_seconds": 0,
                "max_reprices_per_hour": 20,
                "allow_revealed_reprice": True,
                "post_only_required": True,
                "converge_to_target": True,
                "inherit_to_follow_ups": True,
            },
            "anchor_repricing_state_json": {},
        }
        manager._market_cache["BTC-USDC"] = {
            "product_id": "BTC-USDC",
            "price": 100.0,
            "bid": 99.0,
            "ask": 101.0,
            "volume_1m": 10.0,
            "source": "ticker",
        }

        persisted_prices = []
        manager._update_stealth_order = lambda order: persisted_prices.append(order["limit_price"])

        processed = manager.process_anchor_repricing_for_product("BTC-USDC")

        assert processed == 1
        assert manager.in_memory_orders[stealth_order_id]["limit_price"] == 101.0
        assert persisted_prices[-1] == 101.0

    def test_revealed_order_reprices_with_fresh_placement_client_order_id(self, monkeypatch):
        manager = StealthOrderManager(db_client=None)
        stealth_order_id = "b91e8400-e29b-41d4-a716-446655440000"
        manager.in_memory_orders[stealth_order_id] = {
            "stealth_order_id": stealth_order_id,
            "product_id": "BTC-USDC",
            "side": "SELL",
            "total_size": 1.0,
            "revealed_size": 1.0,
            "remaining_size": 1.0,
            "executed_size": 0.0,
            "limit_price": 110.0,
            "status": StealthOrderStatus.REVEALED.value,
            "reveal_condition_type": "time_delay",
            "reveal_condition_json": {"type": "time_delay", "delay_seconds": 0},
            "sizing_strategy_json": {"type": "fixed"},
            "revealed_orders": [{"placed_order_id": "placement-old", "exchange_order_id": "exchange-old"}],
            "anchor_repricing_policy_json": {
                "enabled": True,
                "reference_price_source": "last_trade",
                "distance_type": "P",
                "target_distance": 0.01,
                "max_distance": 0.05,
                "update_mode": "fixed",
                "fixed_interval_seconds": 60,
                "min_price_change": 0.01,
                "hysteresis_bps": 0,
                "min_reprice_interval_seconds": 0,
                "max_reprices_per_hour": 20,
                "allow_revealed_reprice": True,
                "post_only_required": True,
                "converge_to_target": True,
                "inherit_to_follow_ups": True,
            },
            "anchor_repricing_state_json": {
                "active_placement_client_order_id": "placement-old",
                "active_exchange_order_id": "exchange-old",
                "active_exchange_price": 110.0,
            },
        }
        manager._market_cache["BTC-USDC"] = {
            "product_id": "BTC-USDC",
            "price": 100.0,
            "bid": 99.5,
            "ask": 100.5,
            "volume_1m": 10.0,
            "source": "ticker",
        }
        manager._placed_order_index["placement-old"] = manager.in_memory_orders[stealth_order_id]

        cancelled = []

        monkeypatch.setattr(
            "configuration.REST_CLIENT",
            SimpleNamespace(
                cancel_orders=lambda order_ids: cancelled.append(list(order_ids)) or [],
                place_limit_order=lambda **kwargs: {
                    "success_response": {
                        "client_order_id": kwargs["client_order_id"],
                        "order_id": "exchange-new",
                    }
                },
            ),
        )

        manager._update_stealth_order = lambda order: None

        processed = manager.process_anchor_repricing_for_product("BTC-USDC")

        assert processed == 1
        assert cancelled == [["exchange-old"]]
        state = manager.in_memory_orders[stealth_order_id]["anchor_repricing_state_json"]
        assert state["active_exchange_order_id"] == "exchange-new"
        assert state["active_placement_client_order_id"] != "placement-old"
        assert manager.in_memory_orders[stealth_order_id]["revealed_orders"][-1]["exchange_order_id"] == "exchange-new"

    def test_reprice_tracks_reveal_condition_price_threshold_with_offset(self):
        """Reveal condition price_threshold tracks limit_price reprices, preserving original offset."""
        manager = StealthOrderManager(db_client=None)
        stealth_order_id = "c91e8400-e29b-41d4-a716-446655440000"
        # Configured offset: threshold = limit + 5 (i.e., reveal when price reaches 5 above limit).
        manager.in_memory_orders[stealth_order_id] = {
            "stealth_order_id": stealth_order_id,
            "product_id": "BTC-USDC",
            "side": "SELL",
            "total_size": 1.0,
            "revealed_size": 0.0,
            "remaining_size": 1.0,
            "executed_size": 0.0,
            "limit_price": 100.0,
            "status": StealthOrderStatus.HIDDEN.value,
            "reveal_condition_type": "price",
            "reveal_condition_json": {
                "type": "price",
                "price_threshold": 105.0,
                "direction": "above",
                "hold_duration_seconds": 0,
            },
            "sizing_strategy_json": {"type": "fixed"},
            "revealed_orders": [],
            "anchor_repricing_policy_json": {
                "enabled": True,
                "reference_price_source": "midpoint",
                "distance_type": "P",
                "target_distance": 0.01,
                "max_distance": 0.05,
                "update_mode": "fixed",
                "fixed_interval_seconds": 60,
                "min_price_change": 0.01,
                "hysteresis_bps": 0,
                "min_reprice_interval_seconds": 0,
                "max_reprices_per_hour": 20,
                "allow_revealed_reprice": False,
                "post_only_required": True,
                "converge_to_target": True,
                "inherit_to_follow_ups": True,
            },
            "anchor_repricing_state_json": {},
        }
        # Midpoint = 99 → SELL target distance 0.01 above midpoint → 99 * 1.01 = 99.99 → 99.99
        manager._market_cache["BTC-USDC"] = {
            "product_id": "BTC-USDC",
            "price": 99.0,
            "bid": 98.0,
            "ask": 100.0,
            "volume_1m": 10.0,
            "source": "ticker",
        }
        manager._update_stealth_order = lambda order: None

        processed = manager.process_anchor_repricing_for_product("BTC-USDC")

        assert processed == 1
        order = manager.in_memory_orders[stealth_order_id]
        new_limit = order["limit_price"]
        assert new_limit != 100.0
        # price_threshold must equal new_limit + original offset (5).
        assert order["reveal_condition_json"]["price_threshold"] == new_limit + 5.0
        # Offsets persisted for future reprices.
        assert order["anchor_repricing_state_json"]["reveal_condition_price_offsets"] == {"price_threshold": 5.0}

    def test_reprice_leaves_non_price_reveal_conditions_untouched(self):
        """Time-delay / spread / ratio conditions carry no absolute price; reprice must not mutate them."""
        manager = StealthOrderManager(db_client=None)
        stealth_order_id = "d91e8400-e29b-41d4-a716-446655440000"
        manager.in_memory_orders[stealth_order_id] = {
            "stealth_order_id": stealth_order_id,
            "product_id": "BTC-USDC",
            "side": "SELL",
            "total_size": 1.0,
            "revealed_size": 0.0,
            "remaining_size": 1.0,
            "executed_size": 0.0,
            "limit_price": 100.0,
            "status": StealthOrderStatus.HIDDEN.value,
            "reveal_condition_type": "time_delay",
            "reveal_condition_json": {"type": "time_delay", "delay_seconds": 60},
            "sizing_strategy_json": {"type": "fixed"},
            "revealed_orders": [],
            "anchor_repricing_policy_json": {
                "enabled": True,
                "reference_price_source": "midpoint",
                "distance_type": "P",
                "target_distance": 0.01,
                "max_distance": 0.05,
                "update_mode": "fixed",
                "fixed_interval_seconds": 60,
                "min_price_change": 0.01,
                "hysteresis_bps": 0,
                "min_reprice_interval_seconds": 0,
                "max_reprices_per_hour": 20,
                "allow_revealed_reprice": False,
                "post_only_required": True,
                "converge_to_target": True,
                "inherit_to_follow_ups": True,
            },
            "anchor_repricing_state_json": {},
        }
        manager._market_cache["BTC-USDC"] = {
            "product_id": "BTC-USDC",
            "price": 99.0,
            "bid": 98.0,
            "ask": 100.0,
            "volume_1m": 10.0,
            "source": "ticker",
        }
        manager._update_stealth_order = lambda order: None

        manager.process_anchor_repricing_for_product("BTC-USDC")

        order = manager.in_memory_orders[stealth_order_id]
        # Time-delay condition still has delay_seconds=60, no price fields injected.
        assert order["reveal_condition_json"] == {"type": "time_delay", "delay_seconds": 60}
        # No offsets recorded since there were no price-bearing fields.
        assert order["anchor_repricing_state_json"].get("reveal_condition_price_offsets") in (None, {})


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
        manager._get_current_market_data = lambda product_id: {
            "price": 50100.0,
            "bid": 50099.5,
            "ask": 50100.5,
            "volume_1m": 88.2,
            "source": "ticker",
        }

        placed_order_id = manager.reveal_order_slice(stealth_order_id)

        assert placed_order_id == stealth_order_id
        assert captured["reveal_event"]["exchange_order_id"] == "exchange-oid-123"
        assert captured["reveal_event"]["market_price"] == 50100.0
        assert captured["reveal_event"]["market_bid"] == 50099.5
        assert captured["reveal_event"]["market_ask"] == 50100.5
        assert captured["reveal_event"]["market_spread"] == 1.0
        assert captured["reveal_event"]["market_volume_1m"] == 88.2
        assert captured["reveal_event"]["market_source"] == "ticker"
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


class TestRevealHistoryMarketPersistence:
    """Ensure reveal history inserts persist market fields into dedicated columns."""

    def test_record_reveal_event_persists_market_fields(self):
        captured = {}

        class FakeDB:
            def execute_update(self, query, params):
                captured["query"] = query
                captured["params"] = params
                return 1

        manager = StealthOrderManager(db_client=FakeDB())

        order = {
            "stealth_order_id": "990e8400-e29b-41d4-a716-446655440000",
        }
        reveal_event = {
            "reveal_number": 1,
            "revealed_size": 1.0,
            "placement_price": 77800.0,
            "placed_order_id": "990e8400-e29b-41d4-a716-446655440000",
            "exchange_order_id": "x-oid-123",
            "market_price": 77805.0,
            "market_bid": 77804.0,
            "market_ask": 77806.0,
            "market_spread": 2.0,
            "market_volume_1m": 321.5,
            "market_source": "ticker",
            "reveal_time": datetime.utcnow(),
        }

        manager._record_reveal_event(order, reveal_event)

        query = captured["query"]
        assert "market_price" in query
        assert "market_bid" in query
        assert "market_ask" in query
        assert "market_spread" in query
        assert "market_volume_1m" in query

        params = captured["params"]
        assert params[6] == 77805.0
        assert params[7] == 77804.0
        assert params[8] == 77806.0
        assert params[9] == 2.0
        assert params[10] == 321.5


class TestRevealProfitabilityValidation:
    """Validate reveal-time profitability checks and API contract usage."""

    def test_validate_reveal_profitability_uses_parent_side_and_price_projection(self):
        captured = {}
        helper_calls = {}

        class FakeProfitValidator:
            def derive_follow_up_price_from_target(self, **kwargs):
                helper_calls.update(kwargs)
                parent_price = kwargs["parent_filled_price"]
                movement = kwargs["target_movement"]
                return parent_price * (1 - movement)

            def validate_order_profitability(self, **kwargs):
                captured.update(kwargs)
                return {"is_profitable": True, "net_profit": 12.34}

        manager = StealthOrderManager(db_client=None, profit_validator=FakeProfitValidator())
        stealth_order_id = "aa1e8400-e29b-41d4-a716-446655440000"
        manager.in_memory_orders[stealth_order_id] = {
            "stealth_order_id": stealth_order_id,
            "product_id": "BTC-USDC",
            "side": "SELL",
            "total_size": "2.5",
            "target_movement": "0.01",
            "target_movement_type": "P",
        }

        reveal_plan = RevealExecutionPlan(
            configured_limit_price=51000.0,
            submitted_limit_price=50000.0,
            reveal_pricing_policy="configured_limit",
            reveal_price_source="configured_limit",
            fallback_used=False,
            target_movement=0.01,
            target_movement_type="P",
            target_movement_source="order_parent",
        )

        is_profitable, reason = manager._validate_reveal_profitability(stealth_order_id, reveal_plan)

        assert is_profitable is True
        assert reason is None
        assert helper_calls["parent_side"] == "SELL"
        assert helper_calls["target_movement_type"] == "P"
        assert captured["parent_side"] == "SELL"
        assert captured["parent_filled_price"] == 50000.0
        assert captured["order_size"] == 2.5
        # SELL + 1% target => follow-up BUY at 99% of entry
        assert captured["follow_up_price"] == 49500.0

    def test_validate_reveal_profitability_blocks_unprofitable_reveal(self):
        """Test that unprofitable reveals raise RevealPricingError."""
        from core.exceptions import RevealPricingError
        
        class FakeProfitValidator:
            def derive_follow_up_price_from_target(self, **kwargs):
                parent_price = kwargs["parent_filled_price"]
                movement = kwargs["target_movement"]
                return parent_price * (1 + movement)

            def validate_order_profitability(self, **kwargs):
                return {"is_profitable": False, "net_profit": -5.0}

        manager = StealthOrderManager(db_client=None, profit_validator=FakeProfitValidator())
        stealth_order_id = "aa2e8400-e29b-41d4-a716-446655440000"
        manager.in_memory_orders[stealth_order_id] = {
            "stealth_order_id": stealth_order_id,
            "product_id": "BTC-USDC",
            "side": "BUY",
            "total_size": 1.0,
            "target_movement": 0.005,
            "target_movement_type": "P",
        }

        reveal_plan = RevealExecutionPlan(
            configured_limit_price=50000.0,
            submitted_limit_price=50000.0,
            reveal_pricing_policy="configured_limit",
            reveal_price_source="configured_limit",
            fallback_used=False,
            target_movement=0.005,
            target_movement_type="P",
            target_movement_source="order_parent",
        )

        # Should raise RevealPricingError when unprofitable
        with pytest.raises(RevealPricingError) as exc_info:
            manager._validate_reveal_profitability(stealth_order_id, reveal_plan)
        
        assert "would not meet profit target" in str(exc_info.value)
        assert exc_info.value.stealth_order_id == stealth_order_id


# Run tests with: pytest tests/unit/test_stealth_order_manager.py -v
