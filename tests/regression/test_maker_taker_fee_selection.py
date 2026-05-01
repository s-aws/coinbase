"""Regression: maker vs taker fee selection by ``post_only``.

Background (2026-05-01)
========================

Pre-fix: every fee calculation used the taker rate exclusively. A
TOP_OF_BOOK reveal that posts as a maker would still be costed at
~6 bps in the pre-flight feasibility check, over-rejecting profitable
orders. Coinbase's ``transaction_summary.fee_tier`` returns BOTH
``maker_fee_rate`` and ``taker_fee_rate``; we must use the right one.

Contract under test:

1. ``FeeManager._refresh_fee_rate`` extracts BOTH rates and clamps
   maker to taker if the API ever returns maker > taker.
2. ``FeeManager.get_profit_validation_fee_rate(post_only=True)``
   returns ``maker_fee_rate * multiplier * regime_factor``.
3. ``FeeManager.get_profit_validation_fee_rate(post_only=False)`` (the
   default) returns the taker-based rate (back-compat).
4. ``ProfitValidator.validate_order_profitability(post_only=True)``
   threads the flag down and tags the result with
   ``liquidity_assumption == "maker"``.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from calculation.fee_manager import FeeManager


_FEE_MANAGER_SRC = (
    Path(__file__).resolve().parents[2]
    / "calculation"
    / "fee_manager.py"
).read_text(encoding="utf-8")


_PROFIT_VALIDATOR_SRC = (
    Path(__file__).resolve().parents[2]
    / "calculation"
    / "profit_validator.py"
).read_text(encoding="utf-8")


class _StubRestClientBoth:
    """REST stub returning both maker and taker rates."""

    def __init__(self, maker: str = "0.0040", taker: str = "0.0060"):
        self._maker = maker
        self._taker = taker

    def get_transaction_summary(self):
        return {
            "fee_tier": {
                "maker_fee_rate": self._maker,
                "taker_fee_rate": self._taker,
            }
        }


class _StubRestClientTakerOnly:
    """Older API shape returning only taker_fee_rate (no maker_fee_rate)."""

    def get_transaction_summary(self):
        return {"fee_tier": {"taker_fee_rate": "0.0060"}}


class _StubRestClientInvertedRates:
    """Pathological API response: maker > taker (should be clamped)."""

    def get_transaction_summary(self):
        return {
            "fee_tier": {
                "maker_fee_rate": "0.0099",
                "taker_fee_rate": "0.0060",
            }
        }


def _make_orderbook(product_id: str, product_type: str = "FUTURE") -> Mock:
    ob = Mock()
    ob.product = {product_id: {"product_type": product_type}}
    return ob


# ---------------------------------------------------------------------------
# Static-source guards
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_default_maker_constant_exists():
    """``DEFAULT_MAKER_FEE_RATE`` must exist as a named constant so a
    silent default-removal can't strand the maker path on zero."""
    assert "DEFAULT_MAKER_FEE_RATE" in _FEE_MANAGER_SRC


@pytest.mark.regression
def test_refresh_extracts_both_rates_from_fee_tier():
    """``_refresh_fee_rate`` must read BOTH ``maker_fee_rate`` and
    ``taker_fee_rate`` out of the same ``fee_tier`` dict."""
    assert 'fee_tier.get("maker_fee_rate")' in _FEE_MANAGER_SRC
    assert 'fee_tier.get("taker_fee_rate")' in _FEE_MANAGER_SRC


@pytest.mark.regression
def test_get_profit_validation_fee_rate_accepts_post_only():
    """The accessor must accept ``post_only`` so callers can ask for
    the right tier without monkey-patching internal state."""
    assert "post_only: bool = False" in _FEE_MANAGER_SRC
    assert "self._maker_fee_rate if post_only else self._taker_fee_rate" in _FEE_MANAGER_SRC


@pytest.mark.regression
def test_profit_validator_threads_post_only():
    """``validate_order_profitability`` must accept and propagate
    ``post_only`` end-to-end so reveal/feasibility callers control the
    fee tier explicitly."""
    assert "post_only: bool = False" in _PROFIT_VALIDATOR_SRC
    assert 'liquidity_assumption' in _PROFIT_VALIDATOR_SRC


# ---------------------------------------------------------------------------
# Behavioural tests — FeeManager
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_refresh_populates_both_rates():
    ob = _make_orderbook("BIT-29MAY26-CDE")
    mgr = FeeManager(_StubRestClientBoth(maker="0.0040", taker="0.0060"),
                     log_callback=lambda *_: None, orderbook=ob)
    mgr._refresh_fee_rate()
    assert mgr._taker_fee_rate == pytest.approx(0.0060)
    assert mgr._maker_fee_rate == pytest.approx(0.0040)


@pytest.mark.regression
def test_post_only_uses_maker_rate():
    """``get_profit_validation_fee_rate(post_only=True)`` must base the
    output on the maker rate, not the taker rate."""
    ob = _make_orderbook("BIT-29MAY26-CDE")
    mgr = FeeManager(_StubRestClientBoth(maker="0.0040", taker="0.0060"),
                     log_callback=lambda *_: None, orderbook=ob)
    mgr._taker_fee_rate = 0.0060
    mgr._maker_fee_rate = 0.0040

    taker_rate = mgr.get_profit_validation_fee_rate(
        product_id="BIT-29MAY26-CDE", post_only=False)
    maker_rate = mgr.get_profit_validation_fee_rate(
        product_id="BIT-29MAY26-CDE", post_only=True)

    # Both apply the same multiplier+regime, so the maker output must
    # be strictly less than the taker output for these inputs.
    assert maker_rate < taker_rate
    # And the ratio must equal the underlying rate ratio (no extra
    # multiplier hiding on either path).
    assert maker_rate / taker_rate == pytest.approx(0.0040 / 0.0060, rel=1e-6)


@pytest.mark.regression
def test_default_post_only_false_preserves_taker_path():
    """Back-compat: existing callers that don't pass ``post_only``
    must keep getting the taker-based rate."""
    ob = _make_orderbook("BIT-29MAY26-CDE")
    mgr = FeeManager(_StubRestClientBoth(),
                     log_callback=lambda *_: None, orderbook=ob)
    mgr._taker_fee_rate = 0.0060
    mgr._maker_fee_rate = 0.0040

    default_rate = mgr.get_profit_validation_fee_rate(product_id="BIT-29MAY26-CDE")
    explicit_taker = mgr.get_profit_validation_fee_rate(
        product_id="BIT-29MAY26-CDE", post_only=False)

    assert default_rate == pytest.approx(explicit_taker)


@pytest.mark.regression
def test_maker_clamped_to_taker_when_api_returns_inverted_rates():
    """Coinbase invariant: maker <= taker. If the API ever returns a
    pathological ``maker > taker``, we must clamp to taker rather than
    silently accept a higher maker rate (which would over-charge the
    fee model for post-only orders)."""
    ob = _make_orderbook("BIT-29MAY26-CDE")
    mgr = FeeManager(_StubRestClientInvertedRates(),
                     log_callback=lambda *_: None, orderbook=ob)
    mgr._refresh_fee_rate()
    assert mgr._maker_fee_rate <= mgr._taker_fee_rate


@pytest.mark.regression
def test_maker_falls_back_to_default_when_api_omits_it():
    """If the API only returns ``taker_fee_rate`` (older shape), the
    maker rate must fall back to ``DEFAULT_MAKER_FEE_RATE`` rather
    than crash or silently set maker = 0."""
    ob = _make_orderbook("BIT-29MAY26-CDE")
    mgr = FeeManager(_StubRestClientTakerOnly(),
                     log_callback=lambda *_: None, orderbook=ob)
    mgr._refresh_fee_rate()
    assert mgr._taker_fee_rate == pytest.approx(0.0060)
    # Should be the default (or clamped to taker if default > taker)
    assert mgr._maker_fee_rate > 0
    assert mgr._maker_fee_rate <= mgr._taker_fee_rate
