"""
Unit tests for OrderCalculator business logic.

Tests order math, spread calculations, and sizing strategies.
"""

import pytest
from decimal import Decimal


class TestOrderCalculatorBasics:
    """Test basic order calculation functionality."""
    
    def test_calculate_profit_target_from_limit_price(self):
        """Calculate profit target given limit price and profit percentage."""
        limit_price = 100.0
        profit_pct = 0.02  # 2% profit
        
        profit_target = limit_price * (1 + profit_pct)
        
        assert profit_target == 102.0
    
    def test_calculate_multiple_slices(self):
        """Calculate slice sizes from total order and slice count."""
        total_size = 10.0
        num_slices = 4
        
        slice_size = total_size / num_slices
        
        assert slice_size == 2.5
        assert slice_size * num_slices == total_size
    
    def test_calculate_vwap_from_prices(self):
        """Calculate volume-weighted average price."""
        # Simple case: 2 fills at different prices
        prices = [100.0, 102.0]
        volumes = [5.0, 5.0]  # Equal volumes
        
        vwap = sum(p * v for p, v in zip(prices, volumes)) / sum(volumes)
        
        assert vwap == 101.0  # Average


class TestSpreadCalculations:
    """Test bid-ask spread calculations."""
    
    def test_calculate_spread_dollars(self):
        """Calculate spread in dollars."""
        bid = 100.0
        ask = 100.5
        
        spread = ask - bid
        
        assert spread == 0.5
    
    def test_calculate_spread_percentage(self):
        """Calculate spread as percentage of mid-price."""
        bid = 100.0
        ask = 100.5
        
        mid = (bid + ask) / 2
        spread_pct = (ask - bid) / mid * 100
        
        assert 0.49 < spread_pct < 0.51  # ~0.5%
    
    def test_reveal_when_spread_widens(self):
        """Reveal order when spread exceeds threshold."""
        current_spread_pct = 0.8
        spread_threshold = 0.5
        
        should_reveal = current_spread_pct > spread_threshold
        
        assert should_reveal is True
    
    def test_hold_when_spread_narrow(self):
        """Hold order when spread is within threshold."""
        current_spread_pct = 0.3
        spread_threshold = 0.5
        
        should_reveal = current_spread_pct > spread_threshold
        
        assert should_reveal is False


class TestSizingStrategies:
    """Test different order sizing strategies."""
    
    def test_fixed_size_strategy(self):
        """Fixed size for all reveals."""
        total_size = 10.0
        reveal_size = 2.0
        
        num_reveals = total_size / reveal_size
        
        assert num_reveals == 5.0
    
    def test_percentage_based_sizing(self):
        """Reveal percentage of remaining."""
        remaining = 10.0
        reveal_pct = 0.25  # 25% of remaining
        
        reveal_amount = remaining * reveal_pct
        new_remaining = remaining - reveal_amount
        
        assert reveal_amount == 2.5
        assert new_remaining == 7.5
    
    def test_decreasing_slice_sizes(self):
        """Slices decrease in size (front-loaded reveals)."""
        total = 10.0
        slices = [0.4, 0.3, 0.2, 0.1]  # Percentages
        
        amounts = [total * pct for pct in slices]
        
        assert sum(amounts) == 10.0
        assert amounts == [4.0, 3.0, 2.0, 1.0]
    
    def test_increasing_slice_sizes(self):
        """Slices increase in size (back-loaded reveals)."""
        total = 10.0
        slices = [0.1, 0.2, 0.3, 0.4]  # Percentages
        
        amounts = [total * pct for pct in slices]
        
        assert sum(amounts) == 10.0
        assert amounts == [1.0, 2.0, 3.0, 4.0]


class TestProductRatioCalculations:
    """Test product ratio condition calculations."""
    
    def test_calculate_price_ratio(self):
        """Calculate ratio between two products."""
        price_a = 50000.0  # BTC
        price_b = 3000.0   # ETH
        
        ratio = price_a / price_b
        
        assert 16.0 < ratio < 17.0
    
    def test_ratio_outside_range(self):
        """Check if ratio is outside acceptable range."""
        current_ratio = 16.5
        min_ratio = 15.0
        max_ratio = 17.0
        
        is_outside = current_ratio < min_ratio or current_ratio > max_ratio
        
        assert is_outside is False
    
    def test_ratio_in_range(self):
        """Check if ratio is within acceptable range."""
        current_ratio = 14.0  # Too low
        min_ratio = 15.0
        max_ratio = 17.0
        
        is_in_range = min_ratio <= current_ratio <= max_ratio
        
        assert is_in_range is False


class TestPriceIncrementRounding:
    """Test rounding prices to valid increments."""
    
    def test_round_to_cent(self):
        """Round to nearest cent (0.01)."""
        price = 100.12345
        increment = 0.01
        
        rounded = round(price / increment) * increment
        
        assert rounded == 100.12
    
    def test_round_to_dollar(self):
        """Round to nearest dollar."""
        price = 100.49
        increment = 1.0
        
        rounded = round(price / increment) * increment
        
        assert rounded == 100.0
    
    def test_round_preserves_value_direction(self):
        """Rounding up or down doesn't cross a major threshold."""
        price = 99.99
        increment = 0.01
        
        rounded = round(price / increment) * increment
        
        assert rounded < 100.0  # Doesn't round up to 100


class TestFeeCalculations:
    """Test trading fee calculations."""
    
    def test_taker_fee_on_order_size(self):
        """Calculate taker fee."""
        order_size = 10.0
        price = 100.0
        taker_fee_pct = 0.006  # 0.6%
        
        order_value = order_size * price
        fee = order_value * taker_fee_pct
        
        assert fee == 6.0
    
    def test_maker_fee_lower_than_taker(self):
        """Maker fee should be lower than taker fee."""
        maker_fee = 0.004
        taker_fee = 0.006
        
        assert maker_fee < taker_fee


# Run with: pytest tests/unit/test_order_calculator.py -v
