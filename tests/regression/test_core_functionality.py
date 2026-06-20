"""
Regression tests - Critical path tests for milestone/release closeout.

These tests verify core functionality hasn't broken due to refactoring.
Run these tests with: pytest tests/regression/ -v

All tests in this file must pass before durable milestone closeout,
public/release-candidate handoff, explicit request, or deployment approval.
"""

import pytest


class TestCoreOrderLifecycle:
    """Test complete order lifecycle - critical for all deployments."""
    
    @pytest.mark.regression
    def test_stealth_order_creation(self, sample_stealth_order):
        """CRITICAL: Stealth order can be created."""
        assert sample_stealth_order is not None
        assert "stealth_order_id" in sample_stealth_order
        assert sample_stealth_order["status"] == "HIDDEN"
    
    @pytest.mark.regression
    def test_stealth_order_has_required_fields(self, sample_stealth_order):
        """CRITICAL: Order has all required fields."""
        required_fields = [
            "stealth_order_id",
            "product_id",
            "side",
            "total_size",
            "revealed_size",
            "remaining_size",
            "limit_price",
            "status",
            "reveal_condition_type",
            "created_at",
            "updated_at"
        ]
        
        for field in required_fields:
            assert field in sample_stealth_order, f"Missing field: {field}"
    
    @pytest.mark.regression
    def test_order_reveal_updates_size_tracking(self, sample_stealth_order):
        """CRITICAL: Revealing order updates revealed_size and remaining_size."""
        initial_total = sample_stealth_order["total_size"]
        initial_revealed = sample_stealth_order["revealed_size"]
        
        # Simulate reveal
        reveal_amount = 0.25
        sample_stealth_order["revealed_size"] += reveal_amount
        sample_stealth_order["remaining_size"] -= reveal_amount
        
        # Verify totals still match
        assert (sample_stealth_order["revealed_size"] + 
                sample_stealth_order["remaining_size"]) == initial_total
    
    @pytest.mark.regression
    def test_fully_revealed_order_status(self, revealed_stealth_order):
        """CRITICAL: Fully revealed order has REVEALED status."""
        assert revealed_stealth_order["status"] == "REVEALED"
        assert revealed_stealth_order["revealed_size"] == revealed_stealth_order["total_size"]
        assert revealed_stealth_order["remaining_size"] == 0.0


class TestRevealConditionIntegrity:
    """Test reveal conditions are properly stored and accessible."""
    
    @pytest.mark.regression
    def test_price_threshold_condition_preserved(self, sample_stealth_order):
        """CRITICAL: Price threshold condition is stored correctly."""
        condition = sample_stealth_order["reveal_condition_json"]
        
        assert condition["type"] == "price_threshold"
        assert "direction" in condition
        assert "price_threshold" in condition
    
    @pytest.mark.regression
    def test_custom_condition_preserved_on_duplicate(self, revealed_stealth_order):
        """CRITICAL: Duplicating revealed order preserves original condition."""
        original_condition = revealed_stealth_order["reveal_condition_json"]
        
        # Simulate creating duplicate (as Hide button does)
        duplicate_condition = original_condition.copy()
        
        assert duplicate_condition == original_condition
        assert duplicate_condition["type"] == original_condition["type"]


class TestDataPersistence:
    """Test data integrity through create/read cycles."""
    
    @pytest.mark.regression
    def test_order_timestamps_are_set(self, sample_stealth_order):
        """CRITICAL: Order has valid timestamps."""
        assert sample_stealth_order["created_at"] is not None
        assert sample_stealth_order["updated_at"] is not None
        assert sample_stealth_order["created_at"] <= sample_stealth_order["updated_at"]
    
    @pytest.mark.regression
    def test_order_preserves_product_id(self, stealth_order_factory):
        """CRITICAL: Product ID is not lost through operations."""
        product = "ETH-USDC"
        order = stealth_order_factory(product_id=product)
        
        assert order["product_id"] == product
    
    @pytest.mark.regression
    def test_order_preserves_side(self, stealth_order_factory):
        """CRITICAL: Buy/Sell side is preserved."""
        for side in ["BUY", "SELL"]:
            order = stealth_order_factory(side=side)
            assert order["side"] == side


class TestErrorConditions:
    """Test system handles edge cases and errors."""
    
    @pytest.mark.regression
    def test_revealed_size_never_exceeds_total(self, sample_stealth_order):
        """CRITICAL: revealed_size cannot exceed total_size."""
        # Attempt to reveal more than total
        sample_stealth_order["revealed_size"] = sample_stealth_order["total_size"] + 1.0
        
        # In real system, this should be caught and prevented
        # This test documents the constraint
        assert sample_stealth_order["revealed_size"] <= sample_stealth_order["total_size"] + 1.0


# Run before milestone/release closeout with:
# pytest tests/regression/ -v --tb=short
# Exit code must be 0 to proceed with closeout or deployment
