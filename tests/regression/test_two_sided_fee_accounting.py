"""Regression: percentage fees must be charged on BOTH sides.

Background (2026-05-01)
========================

Pre-fix, ``ProfitValidator.is_profitable`` computed percentage fees as
``follow_up_price * size * fee_rate`` \u2014 only the close-side fee. The
``FeeManager.DEFAULT_MULTIPLIER = 2.0`` quietly compensated by doubling
the effective rate, so the math came out right by accident.

When the multiplier was split into product-type-aware values
(``FUTURES_FEE_MULTIPLIER = 1.0``, ``SPOT_FEE_MULTIPLIER = 1.1``) the
hidden compensation evaporated. Futures profitability checks suddenly
under-counted fees by 50%: a stealth order at the apparent break-even
target would actually book a loss equal to one fee instance.

Fix: the formula now uses ``(filled_price + follow_up_price) * size *
fee_rate`` so the round-trip is explicit, and the break-even formula
uses ``open * (1 + fee_rate) / (1 - fee_rate)`` (BUY parent) /
``open * (1 - fee_rate) / (1 + fee_rate)`` (SELL parent) instead of the
old single-sided shortcuts.

This regression file pins both: math + static-source guard.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from calculation.profit_validator import ProfitValidator


_SRC = (
    Path(__file__).resolve().parents[2]
    / "calculation"
    / "profit_validator.py"
).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Static-source guards
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_percentage_fee_formula_uses_both_sides():
    """The percentage-fee formula MUST sum open + close prices.

    Catches a regression to the pre-2026-05-01 single-sided shortcut
    ``follow_up_price * effective_size * fee_rate`` (no ``filled_price``
    addend), which under-counts fees by one full instance.
    """
    assert "(filled_price + follow_up_price) * effective_size * fee_rate" in _SRC, (
        "Percentage fee formula reverted to single-sided. Coinbase "
        "charges taker fee on every fill (open AND close); computing "
        "only one side under-counts fees by 50% and breaks any "
        "profitability validation that depended on the (now removed) "
        "FeeManager 2.0x compensating multiplier."
    )


@pytest.mark.regression
def test_breakeven_formula_uses_both_sides():
    """Break-even formula MUST use ``(1 \u00b1 fee_rate)`` on BOTH numerator
    and denominator. The old single-sided shortcuts
    ``filled_price / (1 - fee_rate)`` (BUY) and
    ``filled_price / (1 + fee_rate)`` (SELL) under-state the price the
    market needs to reach for an actual zero-loss exit."""
    # BUY parent \u2192 SELL close
    assert "filled_price * (1 + fee_rate) / (1 - fee_rate)" in _SRC
    # SELL parent \u2192 BUY close
    assert "filled_price * (1 - fee_rate) / (1 + fee_rate)" in _SRC


@pytest.mark.regression
def test_legacy_hardcoded_multiplier_2_removed_from_validator():
    """The old ``multiplier = 2.0`` and ``/ 2.0`` constants in
    ``validate_order_profitability`` were leftovers from when the
    multiplier was unilaterally 2.0. They lie about the live rate after
    the product-type split. Must stay gone."""
    # Specifically the bare assignment at the validator's metadata block.
    assert '"multiplier": 2.0' not in _SRC
    assert "self._get_fee_rate() / 2.0" not in _SRC


# ---------------------------------------------------------------------------
# Behavioural tests
# ---------------------------------------------------------------------------


class _StaticFeeManager:
    """Pin the effective fee rate so tests don't depend on REST or
    regime state."""
    def __init__(self, rate: float):
        self._rate = rate

    def get_profit_validation_fee_rate(self, product_id=None, post_only=False):
        # post_only accepted for API parity with FeeManager; this stub
        # pins a single rate regardless of liquidity assumption.
        return self._rate


@pytest.mark.regression
def test_round_trip_percentage_fee_equals_open_plus_close_times_rate():
    """``percentage_fees`` returned by ``is_profitable`` must equal
    ``(open + close) * size * effective_rate`` for SPOT (no mandatory
    fee, no contract_size adjustment confusion)."""
    fee_rate = 0.001  # 10 bps effective
    validator = ProfitValidator(fee_manager=_StaticFeeManager(fee_rate))

    open_price = 50_000.0
    close_price = 50_500.0
    size = 1.0  # 1 BTC SPOT

    result = validator.is_profitable(
        filled_price=open_price,
        follow_up_price=close_price,
        side="BUY",
        order_size=size,
        product_type="SPOT",
    )

    expected_pct_fee = (open_price + close_price) * size * fee_rate
    assert result["percentage_fees"] == pytest.approx(expected_pct_fee), (
        f"Expected {expected_pct_fee} (round-trip), got "
        f"{result['percentage_fees']} (likely close-side only \u2014 "
        f"the pre-2026-05-01 bug)"
    )


@pytest.mark.regression
def test_breakeven_satisfies_round_trip_zero_profit():
    """Break-even price plugged back into ``is_profitable`` must
    produce net_profit \u2248 0, not a positive (under-counted fees) or
    deeply negative (over-counted) result."""
    fee_rate = 0.001
    validator = ProfitValidator(fee_manager=_StaticFeeManager(fee_rate))

    open_price = 50_000.0
    breakeven = validator._calculate_breakeven_price(
        filled_price=open_price,
        side="BUY",
        order_size=1.0,
        fee_rate=fee_rate,
    )

    # Round-trip closed form: sell = buy * (1 + r) / (1 - r)
    expected_breakeven = open_price * (1 + fee_rate) / (1 - fee_rate)
    assert breakeven == pytest.approx(expected_breakeven)

    result = validator.is_profitable(
        filled_price=open_price,
        follow_up_price=breakeven,
        side="BUY",
        order_size=1.0,
        product_type="SPOT",
    )
    # Tolerance allows for floating-point noise but not a missing fee
    # leg (which would be on the order of ``open_price * fee_rate``
    # \u2248 $50, far above any rounding).
    assert abs(result["net_profit"]) < 0.01, (
        f"Break-even price gave net_profit={result['net_profit']:.4f}; "
        f"a non-zero result indicates the fee accounting in "
        f"is_profitable disagrees with the break-even formula."
    )


@pytest.mark.regression
def test_target_below_two_sided_fee_floor_is_unprofitable():
    """A target movement equal to the ONE-sided fee rate must NOT
    pass profitability \u2014 it would have been (incorrectly) profitable
    under the pre-fix single-sided formula."""
    fee_rate = 0.001  # 10 bps
    validator = ProfitValidator(fee_manager=_StaticFeeManager(fee_rate))

    open_price = 50_000.0
    # Move price by exactly fee_rate (10 bps). Pre-fix formula would
    # have netted a small profit (gross 10 bps - close-only fee 10 bps
    # at slightly different absolute = tiny positive). The corrected
    # formula sees gross 10 bps - round-trip fee ~20 bps = clearly
    # negative.
    close_price = open_price * (1 + fee_rate)

    result = validator.is_profitable(
        filled_price=open_price,
        follow_up_price=close_price,
        side="BUY",
        order_size=1.0,
        product_type="SPOT",
    )
    assert not result["is_profitable"]
    # Loss should be approximately the missing open-side fee
    # (open * fee_rate = 50). Sanity-check the magnitude so we know
    # we're catching the right bug.
    assert result["net_profit"] < 0
    assert abs(result["net_profit"] + open_price * fee_rate) < open_price * fee_rate * 0.5
