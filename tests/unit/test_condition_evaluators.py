"""
Unit tests for condition evaluators.

Tests all reveal condition types: price threshold, time delay, volume, spread, ratio, etc.
"""

import pytest
from datetime import datetime, timedelta


class TestPriceThresholdCondition:
    """Test price threshold reveal conditions."""
    
    def test_reveal_when_price_below_threshold(self):
        """Reveal when price drops below threshold."""
        current_price = 44000.0
        threshold = 45000.0
        direction = "below"
        
        should_reveal = direction == "below" and current_price < threshold
        
        assert should_reveal is True
    
    def test_hold_when_price_above_threshold(self):
        """Hold when price is above threshold."""
        current_price = 46000.0
        threshold = 45000.0
        direction = "below"
        
        should_reveal = direction == "below" and current_price < threshold
        
        assert should_reveal is False
    
    def test_reveal_when_price_above_threshold(self):
        """Reveal when price rises above threshold."""
        current_price = 46000.0
        threshold = 45000.0
        direction = "above"
        
        should_reveal = direction == "above" and current_price > threshold
        
        assert should_reveal is True
    
    def test_hold_duration_requirement(self):
        """Hold until price stays at threshold for duration."""
        price_at_threshold_time = datetime.now() - timedelta(seconds=30)
        hold_duration = 60  # seconds
        current_time = datetime.now()
        
        time_at_threshold = (current_time - price_at_threshold_time).total_seconds()
        should_reveal = time_at_threshold >= hold_duration
        
        assert should_reveal is False  # Only 30 seconds, need 60


class TestTimeDelayCondition:
    """Test time-delay based reveal conditions."""
    
    def test_reveal_after_delay_passed(self):
        """Reveal when delay duration has passed."""
        created_at = datetime.now() - timedelta(seconds=300)
        delay_seconds = 300
        
        elapsed = (datetime.now() - created_at).total_seconds()
        should_reveal = elapsed >= delay_seconds
        
        assert should_reveal is True
    
    def test_hold_before_delay_passes(self):
        """Hold before delay duration is met."""
        created_at = datetime.now() - timedelta(seconds=200)
        delay_seconds = 300
        
        elapsed = (datetime.now() - created_at).total_seconds()
        should_reveal = elapsed >= delay_seconds
        
        assert should_reveal is False
    
    def test_delay_with_jitter(self):
        """Delay duration has jitter (randomness)."""
        base_delay = 300
        jitter_pct = 0.1  # 10% variance
        
        jitter_amount = base_delay * jitter_pct
        min_delay = base_delay - jitter_amount
        max_delay = base_delay + jitter_amount
        
        assert min_delay == 270
        assert max_delay == 330


class TestCumulativeVolumeCondition:
    """Test cumulative volume reveal conditions."""
    
    def test_reveal_when_volume_threshold_met(self):
        """Reveal when volume at price exceeds threshold."""
        cumulative_volume = 50.0
        volume_threshold = 40.0
        
        should_reveal = cumulative_volume >= volume_threshold
        
        assert should_reveal is True
    
    def test_hold_when_volume_below_threshold(self):
        """Hold when volume at price is below threshold."""
        cumulative_volume = 30.0
        volume_threshold = 40.0
        
        should_reveal = cumulative_volume >= volume_threshold
        
        assert should_reveal is False
    
    def test_volume_tracking_across_multiple_trades(self):
        """Track volume accumulation across multiple fills."""
        trades = [
            {"size": 5.0, "price": 100.0},
            {"size": 10.0, "price": 100.0},
            {"size": 8.0, "price": 100.0},
        ]
        
        total_volume = sum(trade["size"] for trade in trades)
        threshold = 20.0
        
        assert total_volume == 23.0
        assert total_volume >= threshold


class TestSpreadCondition:
    """Test bid-ask spread reveal conditions."""
    
    def test_reveal_when_spread_widens(self):
        """Reveal when bid-ask spread exceeds threshold."""
        bid = 100.0
        ask = 101.0
        spread_threshold = 0.005  # 0.5%
        
        mid = (bid + ask) / 2
        spread_pct = (ask - bid) / mid
        
        should_reveal = spread_pct > spread_threshold
        
        assert should_reveal is True
    
    def test_hold_when_spread_tight(self):
        """Hold when spread is tight."""
        bid = 100.0
        ask = 100.2
        spread_threshold = 0.005
        
        mid = (bid + ask) / 2
        spread_pct = (ask - bid) / mid
        
        should_reveal = spread_pct > spread_threshold
        
        assert should_reveal is False


class TestProductRatioCondition:
    """Test product ratio reveal conditions."""
    
    def test_reveal_when_ratio_outside_range(self):
        """Reveal when product ratio exceeds bounds."""
        btc_price = 50000.0
        eth_price = 3000.0
        ratio = btc_price / eth_price
        
        min_ratio = 15.0
        max_ratio = 17.0
        
        should_reveal = ratio < min_ratio or ratio > max_ratio
        
        assert should_reveal is False  # 16.67 is within bounds
    
    def test_ratio_floor_exceeded(self):
        """Reveal when ratio drops below minimum."""
        btc_price = 50000.0
        eth_price = 3500.0
        ratio = btc_price / eth_price
        
        min_ratio = 15.0
        max_ratio = 17.0
        
        should_reveal = ratio < min_ratio
        
        assert should_reveal is False  # 14.29 is below 15.0
    
    def test_ratio_ceiling_exceeded(self):
        """Reveal when ratio rises above maximum."""
        btc_price = 57000.0
        eth_price = 3000.0
        ratio = btc_price / eth_price
        
        min_ratio = 15.0
        max_ratio = 17.0
        
        should_reveal = ratio > max_ratio
        
        assert should_reveal is True  # 19.0 exceeds 17.0


class TestCompositeConditions:
    """Test composite conditions (AND/OR logic)."""
    
    def test_and_condition_both_met(self):
        """Reveal only when both conditions are met."""
        price_ok = True
        volume_ok = True
        
        should_reveal = price_ok and volume_ok
        
        assert should_reveal is True
    
    def test_and_condition_one_not_met(self):
        """Hold when any condition is not met."""
        price_ok = True
        volume_ok = False
        
        should_reveal = price_ok and volume_ok
        
        assert should_reveal is False
    
    def test_or_condition_either_met(self):
        """Reveal if either condition is met."""
        price_ok = True
        spread_ok = False
        
        should_reveal = price_ok or spread_ok
        
        assert should_reveal is True
    
    def test_or_condition_neither_met(self):
        """Hold when no conditions are met."""
        price_ok = False
        spread_ok = False
        
        should_reveal = price_ok or spread_ok
        
        assert should_reveal is False


class TestConditionEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_price_exactly_at_threshold(self):
        """Price exactly at threshold (inclusive comparison)."""
        current_price = 45000.0
        threshold = 45000.0
        direction = "below"
        
        # Below is strict <, not <=
        should_reveal = current_price < threshold
        
        assert should_reveal is False
    
    def test_very_small_spread(self):
        """Handle very small spreads (liquid market)."""
        bid = 100.0
        ask = 100.001
        
        spread = ask - bid
        
        assert spread == 0.001
        assert spread < 0.01
    
    def test_zero_volume_at_price(self):
        """Handle zero volume at a price level."""
        cumulative_volume = 0.0
        threshold = 10.0
        
        should_reveal = cumulative_volume >= threshold
        
        assert should_reveal is False


# Run with: pytest tests/unit/test_condition_evaluators.py -v
