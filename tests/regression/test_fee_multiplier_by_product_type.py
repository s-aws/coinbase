"""Regression: fee multiplier must be product-type-aware.

Background (2026-05-01)
========================

Pre-fix behaviour: ``FeeManager.DEFAULT_MULTIPLIER = 2.0`` doubled the
live taker fee for every product, futures and spot alike. On futures,
where the live taker is ~5 bps and the per-contract mandatory fee
already provides a fixed-cost floor, this made any ``target_movement``
under ~12 bps structurally infeasible (the BIT-29MAY26-CDE incident).

Fix: split into ``FUTURES_FEE_MULTIPLIER = 1.0`` (no cushion — futures
fees are too small for a 100% safety margin to be anything but a
target-movement killer) and ``SPOT_FEE_MULTIPLIER = 1.1`` (10% cushion
to absorb tier-slip on the higher 60-bps spot schedule). Routed by
product type via the same orderbook-backed resolver
``ProfitValidator`` uses, so the two paths can never disagree on
product classification.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from calculation.fee_manager import FeeManager


_SRC = (
    Path(__file__).resolve().parents[2]
    / "calculation"
    / "fee_manager.py"
).read_text(encoding="utf-8")


class _StubRestClient:
    """Minimal REST client that returns a known taker rate."""
    def get_transaction_summary(self):
        return {"fee_tier": {"taker_fee_rate": "0.0006"}}  # 6 bps


def _make_orderbook(product_type_by_id: dict[str, str]) -> Mock:
    """Build a Mock orderbook whose ``product`` dict carries the given
    product_type for each id."""
    ob = Mock()
    ob.product = {
        pid: {"product_type": ptype}
        for pid, ptype in product_type_by_id.items()
    }
    return ob


# ---------------------------------------------------------------------------
# Static-source guards
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_split_multipliers_are_named_constants():
    """Both multipliers MUST exist as named constants so the split
    can't silently revert to a single global value."""
    assert "FUTURES_FEE_MULTIPLIER" in _SRC
    assert "SPOT_FEE_MULTIPLIER" in _SRC


@pytest.mark.regression
def test_legacy_default_multiplier_alias_preserved():
    """Back-compat: tests / external callers still reading
    ``FeeManager.DEFAULT_MULTIPLIER`` must keep working. The alias
    should resolve to the SPOT value (the more conservative cushion)."""
    assert FeeManager.DEFAULT_MULTIPLIER == FeeManager.SPOT_FEE_MULTIPLIER


@pytest.mark.regression
def test_resolver_helper_is_called_from_public_paths():
    """The product-type resolver must be invoked by every fee-rate
    accessor; missing one would silently revert that path to the
    pre-fix global multiplier."""
    assert "_resolve_multiplier_unlocked" in _SRC
    # All three public read paths must route through the resolver.
    assert _SRC.count("_resolve_multiplier_unlocked(product_id)") >= 3


# ---------------------------------------------------------------------------
# Behavioural tests
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_futures_product_uses_futures_multiplier():
    """A FUTURE product_id must yield base_fee * FUTURES_FEE_MULTIPLIER
    * regime_factor (no doubling)."""
    ob = _make_orderbook({"BIT-29MAY26-CDE": "FUTURE"})
    mgr = FeeManager(_StubRestClient(), log_callback=lambda *_: None, orderbook=ob)
    # Force a known base rate and bypass the live REST refresh.
    mgr._taker_fee_rate = 0.0006

    rate = mgr.get_profit_validation_fee_rate(product_id="BIT-29MAY26-CDE")
    expected = 0.0006 * FeeManager.FUTURES_FEE_MULTIPLIER * 1.0  # neutral regime
    assert rate == pytest.approx(expected)
    # Sanity: with a 1.0x multiplier on futures, the rate equals the
    # raw taker fee (modulo regime). The pre-fix bug would return 2x
    # this number.
    assert rate == pytest.approx(0.0006)


@pytest.mark.regression
def test_spot_product_uses_spot_multiplier():
    """A SPOT product_id must yield base_fee * SPOT_FEE_MULTIPLIER."""
    ob = _make_orderbook({"BTC-USDC": "SPOT"})
    mgr = FeeManager(_StubRestClient(), log_callback=lambda *_: None, orderbook=ob)
    mgr._taker_fee_rate = 0.0060

    rate = mgr.get_profit_validation_fee_rate(product_id="BTC-USDC")
    expected = 0.0060 * FeeManager.SPOT_FEE_MULTIPLIER * 1.0
    assert rate == pytest.approx(expected)


@pytest.mark.regression
def test_unknown_product_falls_back_to_spot_multiplier():
    """Conservative default: when product_id cannot be resolved, use
    the SPOT (higher) multiplier. Cushioning a futures product is
    suboptimal but not unsafe; under-cushioning a spot product would
    break profitability checks."""
    mgr = FeeManager(_StubRestClient(), log_callback=lambda *_: None, orderbook=None)
    mgr._taker_fee_rate = 0.0006

    rate = mgr.get_profit_validation_fee_rate(product_id="DOES-NOT-EXIST")
    expected = 0.0006 * FeeManager.SPOT_FEE_MULTIPLIER * 1.0
    assert rate == pytest.approx(expected)


@pytest.mark.regression
def test_no_product_id_falls_back_to_spot_multiplier():
    """Same fallback applies when product_id is omitted entirely."""
    mgr = FeeManager(_StubRestClient(), log_callback=lambda *_: None)
    mgr._taker_fee_rate = 0.0006

    rate = mgr.get_profit_validation_fee_rate()
    expected = 0.0006 * FeeManager.SPOT_FEE_MULTIPLIER * 1.0
    assert rate == pytest.approx(expected)


@pytest.mark.regression
def test_get_fee_info_reports_resolved_multiplier():
    """``get_fee_info`` must surface the multiplier it actually used,
    not a hardcoded default. Operators read this in diagnostics."""
    ob = _make_orderbook({"BIT-29MAY26-CDE": "FUTURE", "BTC-USDC": "SPOT"})
    mgr = FeeManager(_StubRestClient(), log_callback=lambda *_: None, orderbook=ob)
    mgr._taker_fee_rate = 0.0006

    futures_info = mgr.get_fee_info(product_id="BIT-29MAY26-CDE")
    spot_info = mgr.get_fee_info(product_id="BTC-USDC")

    assert futures_info["multiplier"] == FeeManager.FUTURES_FEE_MULTIPLIER
    assert spot_info["multiplier"] == FeeManager.SPOT_FEE_MULTIPLIER
    assert futures_info["profit_validation_fee_rate"] < spot_info["profit_validation_fee_rate"]
