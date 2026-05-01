"""
Phase 2: Adaptive repricing with extended guardrails.

Tests for:
- volatility_sensitivity: Adjust repricing frequency based on market volatility
- max_reprice_window_seconds: Hard cap on repricing interval
- enable_spread_monitoring: Skip repricing if spread exceeds threshold
- require_minimum_volume: Skip repricing if 1m volume insufficient
"""

import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from core.enums import StealthOrderStatus
from core.stealth_order_manager import StealthOrderManager


def _make_manager(in_memory_orders=None):
    """Create manager with mocked persistence."""
    manager = StealthOrderManager(db_client=None, log_callback=MagicMock())
    manager._save_stealth_order_to_db = MagicMock()
    manager._update_stealth_order = MagicMock()
    if in_memory_orders:
        manager.in_memory_orders.update(in_memory_orders)
    return manager


class TestPhase2AdaptiveRepricing:
    """Tests for volatility-sensitive repricing intervals."""

    def test_adaptive_interval_with_volatility_adjustment(self):
        """Volatility sensitivity scales repricing intervals."""
        manager = _make_manager()
        
        policy = {
            "enabled": True,
            "update_mode": "adaptive",
            "volatility_sensitivity": 1.5,  # Extend interval by 50% in high vol
        }
        
        # Baseline: spread < 50 bps (no volatility boost)
        market_data_low_spread = {
            "bid": 40000.0,
            "ask": 40010.0,  # ~25 bps spread
            "source": "ticker",
        }
        
        # High volatility: spread > 50 bps (triggers volatility boost)
        market_data_high_vol = {
            "bid": 40000.0,
            "ask": 40300.0,  # ~150 bps spread (>50)
            "source": "ticker",
        }
        
        # Adaptive: current=40100, target=40050, max=40000
        # target_gap=50, max_gap=100 -> target_gap < max_gap -> 120s base
        interval_low_spread = manager._next_anchor_reprice_seconds(
            policy, 40100.0, 40050.0, 40000.0, market_data_low_spread
        )
        
        # High volatility with same prices -> extended due to volatility
        interval_high_vol = manager._next_anchor_reprice_seconds(
            policy, 40100.0, 40050.0, 40000.0, market_data_high_vol
        )
        
        # Low spread: 120s base (no adjustment)
        assert interval_low_spread == 120
        # High vol: 120 * 1.5 = 180 (extended by sensitivity)
        assert interval_high_vol == 180


    def test_max_reprice_window_hard_cap(self):
        """max_reprice_window_seconds enforces hard cap on interval."""
        manager = _make_manager()
        
        policy = {
            "enabled": True,
            "update_mode": "adaptive",
            "volatility_sensitivity": 3.0,  # Would extend significantly
            "max_reprice_window_seconds": 180,  # Hard cap at 3 minutes
        }
        
        market_data_high_vol = {
            "bid": 40000.0,
            "ask": 40500.0,  # Very wide spread
            "source": "ticker",
        }
        
        interval = manager._next_anchor_reprice_seconds(
            policy, 40050.0, 40040.0, 40030.0, market_data_high_vol
        )
        
        # Should be capped at max_reprice_window_seconds
        assert interval <= 180


    def test_fixed_mode_ignores_volatility(self):
        """Fixed mode: volatility has no effect on interval."""
        manager = _make_manager()
        
        policy = {
            "enabled": True,
            "update_mode": "fixed",
            "fixed_interval_seconds": 120,
            "volatility_sensitivity": 2.0,  # Should be ignored
        }
        
        market_data_high_vol = {
            "bid": 40000.0,
            "ask": 40500.0,
            "source": "ticker",
        }
        
        interval = manager._next_anchor_reprice_seconds(
            policy, 40050.0, 40040.0, 40030.0, market_data_high_vol
        )
        
        # Fixed mode returns fixed interval regardless of volatility
        assert interval == 120


    def test_next_interval_calculation_with_no_market_data(self):
        """Repricing intervals work without market_data (backwards compatibility)."""
        manager = _make_manager()
        
        policy = {
            "enabled": True,
            "update_mode": "adaptive",
            "volatility_sensitivity": 2.0,
            "max_reprice_window_seconds": 600,
        }
        
        # Call with market_data=None (should not crash)
        # current=40100, target=40050, max=40000 -> returns 120
        interval = manager._next_anchor_reprice_seconds(
            policy, 40100.0, 40050.0, 40000.0, None
        )
        
        # Should return base adaptive interval (120)
        assert interval == 120


class TestPhase2SpreadMonitoring:
    """Tests for spread-based repricing guardrails."""

    def test_spread_monitoring_disabled_by_default(self):
        """Spread monitoring is opt-in via enable_spread_monitoring."""
        manager = _make_manager()

        # Set price-change gates to 0 so we isolate the spread-monitoring
        # behavior (otherwise the policy's default min_price_change /
        # hysteresis_bps would short-circuit before we reach the spread
        # check). Same pattern as test_spread_monitoring_skips_wide_spreads.
        policy = {
            "enabled": True,
            "enable_spread_monitoring": False,  # Not enabled
            "max_spread_bps": 50.0,
            "min_price_change": 0.0,
            "hysteresis_bps": 0.0,
            "min_reprice_interval_seconds": 0,
            "max_reprices_per_hour": 100,
        }
        
        state = {"reprice_history": []}
        
        # Even with massive spread, should not skip when monitoring disabled
        market_data = {
            "bid": 40000.0,
            "ask": 41000.0,  # 500 bps spread!
            "source": "ticker",
        }
        
        should_skip = manager._should_skip_anchor_reprice(
            state, policy, 40010.0, 40000.0, False, market_data
        )
        assert should_skip is False


    def test_spread_monitoring_skips_wide_spreads(self):
        """Wide spreads block repricing when monitoring enabled."""
        manager = _make_manager()
        
        policy = {
            "enabled": True,
            "enable_spread_monitoring": True,
            "max_spread_bps": 100.0,  # Max 100 bps spread
            "min_price_change": 0.01,
            "min_reprice_interval_seconds": 0,
            "hysteresis_bps": 0.0,
            "max_reprices_per_hour": 100,  # High limit to not trigger
        }
        
        state = {"reprice_history": []}
        
        # Normal spread: 50 bps (below limit) -> should not skip
        market_data_normal = {
            "bid": 40000.0,
            "ask": 40020.0,
            "source": "ticker",
        }
        
        should_skip = manager._should_skip_anchor_reprice(
            state, policy, 40010.0, 40000.0, False, market_data_normal
        )
        assert should_skip is False
        
        # Wide spread: 200 bps (exceeds limit) -> should skip
        market_data_wide = {
            "bid": 40000.0,
            "ask": 40400.0,
            "source": "ticker",
        }
        
        should_skip = manager._should_skip_anchor_reprice(
            state, policy, 40200.0, 40200.0, False, market_data_wide
        )
        assert should_skip is True


class TestPhase2VolumeRequirements:
    """Tests for minimum volume guardrails."""

    def test_volume_requirement_disabled_by_default(self):
        """Volume requirement defaults to 0 (no requirement)."""
        manager = _make_manager()
        
        policy = {
            "enabled": True,
            "require_minimum_volume": 0.0,  # No requirement
            "min_price_change": 0.01,
            "min_reprice_interval_seconds": 0,
            "hysteresis_bps": 0.0,
            "max_reprices_per_hour": 100,
        }
        
        state = {"reprice_history": []}
        
        market_data = {
            "bid": 40000.0,
            "ask": 40001.0,
            "volume_1m": 0.001,  # Minimal volume
            "source": "ticker",
        }
        
        # Low volume should not block repricing without requirement
        should_skip = manager._should_skip_anchor_reprice(
            state, policy, 40010.0, 40000.0, False, market_data
        )
        assert should_skip is False


    def test_volume_requirement_blocks_low_volume(self):
        """Repricing blocked if 1m volume below threshold."""
        manager = _make_manager()
        
        policy = {
            "enabled": True,
            "require_minimum_volume": 100.0,  # Need 100 BTC/min volume
            "min_price_change": 0.01,
            "min_reprice_interval_seconds": 0,
            "hysteresis_bps": 0.0,
            "max_reprices_per_hour": 100,
        }
        
        state = {"reprice_history": []}
        
        # Sufficient volume: repricing proceeds
        market_data_high_vol = {
            "bid": 40000.0,
            "ask": 40001.0,
            "volume_1m": 150.0,
            "source": "ticker",
        }
        
        should_skip = manager._should_skip_anchor_reprice(
            state, policy, 40010.0, 40000.0, False, market_data_high_vol
        )
        assert should_skip is False
        
        # Insufficient volume: repricing blocked
        market_data_low_vol = {
            "bid": 40000.0,
            "ask": 40001.0,
            "volume_1m": 50.0,  # Below 100 threshold
            "source": "ticker",
        }
        
        should_skip = manager._should_skip_anchor_reprice(
            state, policy, 40010.0, 40000.0, False, market_data_low_vol
        )
        assert should_skip is True


class TestPhase2PolicyNormalization:
    """Tests for policy field normalization with defaults."""

    def test_new_policy_fields_normalized_with_defaults(self):
        """New Phase 2 fields get sensible defaults when policy enabled."""
        manager = _make_manager()
        
        policy_input = {
            "enabled": True,
            "reference_price_source": "midpoint",
            "distance_type": "A",
            "target_distance": 10.0,
            "max_distance": 20.0,
        }
        policy = manager._normalize_anchor_repricing_policy(policy_input)
        
        # New Phase 2 fields should exist with defaults
        assert policy.get("volatility_sensitivity") == 1.0
        assert policy.get("max_reprice_window_seconds") == 600
        assert policy.get("require_minimum_volume") == 0.0
        assert policy.get("enable_spread_monitoring") is False
        assert policy.get("max_spread_bps") == 50.0


    def test_volatility_sensitivity_bounded(self):
        """Volatility sensitivity clamped to [0.1, 2.0]."""
        manager = _make_manager()
        
        # Too low: clamped to 0.1
        policy = manager._normalize_anchor_repricing_policy({
            "enabled": True,
            "reference_price_source": "midpoint",
            "distance_type": "A",
            "target_distance": 10.0,
            "max_distance": 20.0,
            "volatility_sensitivity": 0.01
        })
        assert policy["volatility_sensitivity"] == 0.1
        
        # Too high: clamped to 2.0
        policy = manager._normalize_anchor_repricing_policy({
            "enabled": True,
            "reference_price_source": "midpoint",
            "distance_type": "A",
            "target_distance": 10.0,
            "max_distance": 20.0,
            "volatility_sensitivity": 5.0
        })
        assert policy["volatility_sensitivity"] == 2.0
        
        # Valid: passed through
        policy = manager._normalize_anchor_repricing_policy({
            "enabled": True,
            "reference_price_source": "midpoint",
            "distance_type": "A",
            "target_distance": 10.0,
            "max_distance": 20.0,
            "volatility_sensitivity": 1.5
        })
        assert policy["volatility_sensitivity"] == 1.5


    def test_max_reprice_window_must_exceed_min_interval(self):
        """max_reprice_window_seconds enforced >= min_reprice_interval_seconds."""
        manager = _make_manager()
        
        policy = manager._normalize_anchor_repricing_policy({
            "enabled": True,
            "reference_price_source": "midpoint",
            "distance_type": "A",
            "target_distance": 10.0,
            "max_distance": 20.0,
            "min_reprice_interval_seconds": 60.0,
            "max_reprice_window_seconds": 30.0,  # Lower than min!
        })
        
        # Should be boosted to meet minimum
        assert policy["max_reprice_window_seconds"] >= 60


class TestPhase2Integration:
    """End-to-end tests combining multiple Phase 2 features."""

    def test_combined_guardrails_trigger_correctly(self):
        """Multiple guardrails can block repricing together."""
        manager = _make_manager()
        
        policy = {
            "enabled": True,
            "enable_spread_monitoring": True,
            "max_spread_bps": 50.0,
            "require_minimum_volume": 100.0,
            "min_price_change": 0.01,
            "min_reprice_interval_seconds": 0,
            "hysteresis_bps": 0.0,
            "max_reprices_per_hour": 100,
        }
        
        state = {"reprice_history": []}
        
        # Market: wide spread + low volume
        market_data = {
            "bid": 40000.0,
            "ask": 40500.0,  # 1250 bps spread!
            "volume_1m": 10.0,  # Below 100 requirement
            "source": "ticker",
        }
        
        # Both guardrails trigger - repricing blocked
        should_skip = manager._should_skip_anchor_reprice(
            state, policy, 40010.0, 40000.0, False, market_data
        )
        assert should_skip is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
