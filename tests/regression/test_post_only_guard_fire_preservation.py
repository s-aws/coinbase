"""Regression: ``post_only`` is preserved when the configured-limit guard
fires with a known market.

Background (2026-05-01)
========================

``build_reveal_execution_plan`` resolves a reveal price from the
``RevealPricingPolicy`` and then passes the result through a GUARD that
falls back to ``configured_limit_price`` when the policy's chosen price
is *worse* than the operator's target (BUY higher / SELL lower than
configured). The guard sets ``fallback_used = True`` for the wire model.

Pre-fix bug: the post_only derivation conflated two different conditions
under the single ``fallback_used`` flag:

    1. Market data unknown (resolver couldn't read bid/ask) — legit
       reason to demote post_only to taker.
    2. Guard fired with a known market — choosing the configured price
       INSIDE the spread is *more* maker-likely than the policy's pick
       would have been. Demoting post_only here over-rejected reveals
       at the (much higher) taker rate, killing legitimate maker fills.

Fix: track ``market_data_unknown`` separately from the wire-level
``fallback_used``. Demote post_only only for case 1.

This test exercises both paths end-to-end via build_reveal_execution_plan.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.enums import (
    OrderSide,
    RevealPriceSource,
    RevealPricingPolicy,
    StealthOrderStatus,
)


def _bare_manager_with_order(order: dict, market_data: dict | None = None):
    """Construct a bare StealthOrderManager populated for plan building."""
    from core.orderbook import ClaimLedger
    from core.enums import StealthMutationKind
    from core.stealth_order_manager import StealthOrderManager
    from logging_service import get_logger

    mgr = StealthOrderManager.__new__(StealthOrderManager)
    mgr._mutation_claims = ClaimLedger(StealthMutationKind)
    mgr._placed_order_index = {}
    mgr.in_memory_orders = {order["stealth_order_id"]: order}
    mgr._market_cache = {order["product_id"]: market_data} if market_data else {}
    mgr.log_callback = lambda *a, **k: None
    mgr.logger = get_logger("StealthOrderManager.test")
    # Stub target movement resolution so plan building doesn't touch DB.
    mgr._resolve_target_movement_for_plan = MagicMock(
        return_value=(0.0011, "P", "stealth_orders")
    )
    return mgr


def _base_order(side: str, configured: float, sid: str = "sid") -> dict:
    return {
        "stealth_order_id": sid,
        "product_id": "BTC-USDC",
        "side": side,
        "status": StealthOrderStatus.HIDDEN.value,
        "limit_price": configured,
        "remaining_size": 1.0,
        "executed_size": 0.0,
        "reveal_pricing_policy": RevealPricingPolicy.TOP_OF_BOOK.value,
        "reveal_condition_json": {},
        "anchor_repricing_policy_json": {"enabled": False},
        "anchor_repricing_state_json": {},
        "revealed_orders": [],
    }


def test_post_only_preserved_when_guard_fires_with_known_market_buy():
    """BUY: top-of-book ask above configured → guard falls back to
    configured. Configured price is BELOW the ask, so it rests as
    maker. post_only must STAY True."""
    order = _base_order(side="BUY", configured=78300.0, sid="sid_buy_guard")
    market = {
        "product_id": "BTC-USDC",
        "source": "ticker",
        "bid": 78295.0,
        "ask": 78305.0,  # top_of_book BUY would pick 78305 → worse than 78300 → guard fires
        "price": 78300.0,
    }
    mgr = _bare_manager_with_order(order, market_data=market)

    plan = mgr.build_reveal_execution_plan(order["stealth_order_id"])

    assert plan is not None
    # Guard fired: submitted equals configured, not the ask.
    assert plan.submitted_limit_price == pytest.approx(78300.0)
    assert plan.reveal_price_source == RevealPriceSource.CONFIGURED_LIMIT.value
    # Wire-level back-compat: fallback_used reports the demotion.
    assert plan.fallback_used is True
    # CRITICAL: post_only must NOT be demoted — we know the market and
    # 78300 < 78305 ask → strict maker.
    assert plan.post_only is True, (
        "post_only must stay True when guard chooses a price strictly "
        "inside the known spread (more maker-likely than policy's pick)."
    )


def test_post_only_preserved_when_guard_fires_with_known_market_sell():
    """SELL: top-of-book bid below configured → guard falls back to
    configured. Configured price is ABOVE the bid, so it rests as
    maker. post_only must STAY True."""
    order = _base_order(side="SELL", configured=78305.0, sid="sid_sell_guard")
    market = {
        "product_id": "BTC-USDC",
        "source": "ticker",
        "bid": 78295.0,  # top_of_book SELL would pick 78295 → worse than 78305 → guard fires
        "ask": 78310.0,
        "price": 78300.0,
    }
    mgr = _bare_manager_with_order(order, market_data=market)

    plan = mgr.build_reveal_execution_plan(order["stealth_order_id"])

    assert plan is not None
    assert plan.submitted_limit_price == pytest.approx(78305.0)
    assert plan.reveal_price_source == RevealPriceSource.CONFIGURED_LIMIT.value
    assert plan.fallback_used is True
    assert plan.post_only is True, (
        "post_only must stay True for SELL guard fire — 78305 > 78295 bid → strict maker."
    )


def test_post_only_demoted_when_market_data_actually_unavailable():
    """Defensive path unchanged: when the resolver couldn't read bid/ask,
    demote post_only to taker. This is the LEGITIMATE fallback case."""
    order = _base_order(side="BUY", configured=78300.0, sid="sid_no_market")
    # source != "ticker" → resolver reports market_data_unknown
    market = {
        "product_id": "BTC-USDC",
        "source": "unavailable",
        "bid": 0,
        "ask": 0,
        "price": 0,
    }
    mgr = _bare_manager_with_order(order, market_data=market)

    plan = mgr.build_reveal_execution_plan(order["stealth_order_id"])

    assert plan is not None
    # Resolver fell back to configured because no usable market data.
    assert plan.submitted_limit_price == pytest.approx(78300.0)
    assert plan.fallback_used is True
    # post_only correctly demoted — we never validated this rests.
    assert plan.post_only is False, (
        "When market data is unavailable, post_only must demote to taker "
        "because the configured price was never validated to rest."
    )


def test_post_only_true_for_top_of_book_with_clean_market():
    """Sanity baseline: TOP_OF_BOOK with a healthy ticker keeps post_only=True
    via the standard policy → implies_post_only path."""
    order = _base_order(side="BUY", configured=78400.0, sid="sid_clean")
    market = {
        "product_id": "BTC-USDC",
        "source": "ticker",
        "bid": 78290.0,
        # ask 78295 < configured 78400 → policy picks 78295 (BETTER), guard does not fire
        "ask": 78295.0,
        "price": 78292.0,
    }
    mgr = _bare_manager_with_order(order, market_data=market)

    plan = mgr.build_reveal_execution_plan(order["stealth_order_id"])

    assert plan is not None
    assert plan.submitted_limit_price == pytest.approx(78295.0)
    assert plan.reveal_price_source == RevealPriceSource.TICKER_BEST_ASK.value
    assert plan.fallback_used is False
    assert plan.post_only is True
