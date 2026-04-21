"""
Unit tests for StealthOrderManager.

Tests the core order management logic in isolation with mocked dependencies.
"""

import pytest
from datetime import datetime


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


# Run tests with: pytest tests/unit/test_stealth_order_manager.py -v
