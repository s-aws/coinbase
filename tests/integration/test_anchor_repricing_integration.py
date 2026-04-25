"""
Integration tests for ticker-driven anchor repricing.

Tests StealthOrderManager.process_anchor_repricing_for_product() end-to-end
with real in-memory order state but no database or external API calls.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from core.stealth_order_manager import StealthOrderManager
from core.enums import StealthOrderStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_manager() -> StealthOrderManager:
    """Create a manager with no DB and noop persistence helpers."""
    mgr = StealthOrderManager(db_client=None)
    mgr._save_stealth_order_to_db = MagicMock()
    mgr._update_stealth_order = MagicMock()
    return mgr


def _make_order(
    mgr: StealthOrderManager,
    *,
    product_id: str = "BTC-USDC",
    side: str = "BUY",
    limit_price: float = 50_000.0,
    status: str = StealthOrderStatus.HIDDEN.value,
    policy: dict | None = None,
    state: dict | None = None,
) -> str:
    """Insert a pre-built stealth order directly into the manager's cache."""
    import uuid
    oid = str(uuid.uuid4())
    mgr.in_memory_orders[oid] = {
        "stealth_order_id": oid,
        "product_id": product_id,
        "side": side,
        "total_size": 1.0,
        "revealed_size": 0.0,
        "remaining_size": 1.0,
        "executed_size": 0.0,
        "limit_price": limit_price,
        "status": status,
        "reveal_condition_type": "time_delay",
        "reveal_condition_json": {"type": "time_delay", "delay_seconds": 3600},
        "revealed_orders": [],
        "reason": "normal_placement",
        "parent_order_id": None,
        "condition_confirmed_at": None,
        "condition_first_met_at": None,
        "anchor_repricing_policy_json": policy or {
            "enabled": True,
            "reference_price_source": "midpoint",
            "distance_type": "P",
            "target_distance": 0.01,
            "max_distance": 0.05,
            "update_mode": "adaptive",
            "fixed_interval_seconds": 60,
            "min_price_change": 0.0,
            "hysteresis_bps": 0,
            "min_reprice_interval_seconds": 0,
            "max_reprices_per_hour": 9999,
            "post_only_required": False,
            "allow_revealed_reprice": False,
        },
        "anchor_repricing_state_json": state or {},
    }
    return oid


def _set_ticker(mgr: StealthOrderManager, product_id: str, bid: float, ask: float):
    mgr._market_cache[product_id] = {
        "product_id": product_id,
        "bid": bid,
        "ask": ask,
        "price": (bid + ask) / 2,
        "volume_1m": 1.0,
        "source": "ticker",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAnchorRepricingIntegration:
    """End-to-end anchor repricing integration tests."""

    def test_hidden_order_reprices_on_ticker_update(self):
        """A HIDDEN order with repricing enabled should receive a new limit_price
        when a ticker arrives and no cooldown is active."""
        mgr = _make_manager()
        oid = _make_order(mgr, limit_price=50_000.0)
        # Midpoint of 49_800 / 49_900 = 49_850; 1 % below midpoint (BUY) = 49_350.15
        _set_ticker(mgr, "BTC-USDC", bid=49_800.0, ask=49_900.0)

        processed = mgr.process_anchor_repricing_for_product("BTC-USDC")

        order = mgr.in_memory_orders[oid]
        assert processed == 1
        assert order["limit_price"] != 50_000.0, "Limit price should have been updated"
        # BUY order should move below midpoint
        assert order["limit_price"] < (49_800.0 + 49_900.0) / 2

    def test_hysteresis_prevents_tiny_reprice(self):
        """When min_price_change is large the order should NOT be repriced."""
        policy = {
            "enabled": True,
            "reference_price_source": "midpoint",
            "distance_type": "A",
            "target_distance": 10.0,
            "max_distance": 50.0,
            "update_mode": "adaptive",
            "fixed_interval_seconds": 60,
            "min_price_change": 9999.0,   # require $9 999 price change → never triggers
            "hysteresis_bps": 0,
            "min_reprice_interval_seconds": 0,
            "max_reprices_per_hour": 9999,
            "post_only_required": False,
            "allow_revealed_reprice": False,
        }
        mgr = _make_manager()
        oid = _make_order(mgr, limit_price=49_840.0, policy=policy)
        _set_ticker(mgr, "BTC-USDC", bid=49_800.0, ask=49_900.0)

        processed = mgr.process_anchor_repricing_for_product("BTC-USDC")

        assert processed == 0
        assert mgr.in_memory_orders[oid]["limit_price"] == 49_840.0

    def test_rate_limit_skips_reprice_before_interval(self):
        """If next_reprice_at is in the future, the order should be skipped."""
        future = (datetime.utcnow() + timedelta(hours=1)).isoformat()
        mgr = _make_manager()
        oid = _make_order(mgr, limit_price=50_000.0, state={"next_reprice_at": future})
        _set_ticker(mgr, "BTC-USDC", bid=49_800.0, ask=49_900.0)

        processed = mgr.process_anchor_repricing_for_product("BTC-USDC")

        assert processed == 0
        assert mgr.in_memory_orders[oid]["limit_price"] == 50_000.0

    def test_max_boundary_price_enforced_buy(self):
        """For a BUY order, if the current price is below the max boundary it should
        be clamped up to the max boundary price."""
        policy = {
            "enabled": True,
            "reference_price_source": "midpoint",
            "distance_type": "P",
            "target_distance": 0.01,   # 1 % below midpoint
            "max_distance": 0.02,      # max 2 % below midpoint
            "update_mode": "adaptive",
            "fixed_interval_seconds": 60,
            "min_price_change": 0.0,
            "hysteresis_bps": 0,
            "min_reprice_interval_seconds": 0,
            "max_reprices_per_hour": 9999,
            "post_only_required": False,
            "allow_revealed_reprice": False,
        }
        # Set current price far below max boundary (50_000 vs max ~49_000)
        mgr = _make_manager()
        _make_order(mgr, limit_price=40_000.0, policy=policy)   # way below max
        _set_ticker(mgr, "BTC-USDC", bid=49_800.0, ask=49_900.0)

        # Midpoint = 49_850; max_boundary for BUY = midpoint * (1 - 0.02) = 48_853
        processed = mgr.process_anchor_repricing_for_product("BTC-USDC")

        # Should be processed (outside max → clamp to max boundary)
        assert processed == 1

    def test_no_ticker_no_reprice(self):
        """When market data source is not 'ticker', repricing must be skipped."""
        mgr = _make_manager()
        oid = _make_order(mgr, limit_price=50_000.0)
        mgr._market_cache["BTC-USDC"] = {
            "product_id": "BTC-USDC",
            "bid": 49_800.0,
            "ask": 49_900.0,
            "price": 49_850.0,
            "volume_1m": 1.0,
            "source": "synthetic_follow_up_seed",   # not "ticker"
        }

        processed = mgr.process_anchor_repricing_for_product("BTC-USDC")

        assert processed == 0
        assert mgr.in_memory_orders[oid]["limit_price"] == 50_000.0

    def test_repricing_disabled_skips(self):
        """An order with enabled=False in the policy must never be repriced."""
        policy = {
            "enabled": False,
            "reference_price_source": "midpoint",
            "distance_type": "P",
            "target_distance": 0.01,
            "max_distance": 0.05,
            "update_mode": "adaptive",
            "fixed_interval_seconds": 60,
            "min_price_change": 0.0,
            "hysteresis_bps": 0,
            "min_reprice_interval_seconds": 0,
            "max_reprices_per_hour": 9999,
            "post_only_required": False,
        }
        mgr = _make_manager()
        oid = _make_order(mgr, limit_price=50_000.0, policy=policy)
        _set_ticker(mgr, "BTC-USDC", bid=49_800.0, ask=49_900.0)

        processed = mgr.process_anchor_repricing_for_product("BTC-USDC")

        assert processed == 0
        assert mgr.in_memory_orders[oid]["limit_price"] == 50_000.0
