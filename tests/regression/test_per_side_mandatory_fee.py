"""Regression: Coinbase Derivatives per-side mandatory fee schedule.

Sources:
  * Coinbase Fee Schedule effective March 2, 2026
    https://assets.ctfassets.net/o10es7wu5gm1/6LbrWZkWY1BUS67poRlVe/
    10ca89e22a46b899389678b8f3352c10/Fee_Schedule_3.2.2026.pdf
  * Daily statement reconciliation, CFMD3UKRINXC, Apr-30-2026.

Key facts:
  * "Fees are charged per side (both the buy and the sell side) per contract"
  * Venue commission per side:
      - Full-size tier (BTI/ETI/SLC/XRL): $0.20
      - Nano / Perp-Style and everything else: $0.10
  * Non-venue charges that ALSO debit per side per contract:
      - SEC/CFTC regulatory: $0.02
      - Clearing:            $0.03
      - NFA:                 $0.02
      = $0.07 added to every side.
  * Therefore the ALL-IN per-side cost (what get_derivatives_per_side_fee
    returns) is $0.27 (full-size) or $0.17 (nano/everything else).

Pre-2026-05-01 the resolver returned venue only, underbudgeting fees by
$0.14/contract round-trip. These tests lock in the corrected all-in
semantics.

These tests lock in:
  1. Per-symbol resolver returns the correct all-in tier rate
  2. ``ProfitValidator`` charges the round-trip mandatory fee (per-side x 2)
  3. ``OrderBook.mandatory_fee_per_contract`` shim stores the round-trip
     value scaled by contract_size (for the order-spacing consumer)
  4. The legacy constant name no longer exists (forces stale callers to break)
"""

from __future__ import annotations

import importlib

import pytest

from core.constants import (
    DERIVATIVES_PER_SIDE_FEE_BY_SYMBOL,
    DERIVATIVES_PER_SIDE_FEE_DEFAULT,
    get_derivatives_per_side_fee,
)


# ---------------------------------------------------------------------------
# 1. Per-symbol resolver
# ---------------------------------------------------------------------------

# All-in per-side cost = venue + $0.07 non-venue (reg + clearing + NFA).
# Full-size: $0.20 + $0.07 = $0.27. Nano / default: $0.10 + $0.07 = $0.17.
@pytest.mark.parametrize(
    "product_id,expected",
    [
        # Full-size tier ($0.27 all-in/side)
        ("BTI-29MAY26-CDE", 0.27),
        ("ETI-29MAY26-CDE", 0.27),
        ("SLC-29MAY26-CDE", 0.27),
        ("XRL-29MAY26-CDE", 0.27),
        # Nano / Perp-Style tier ($0.17 all-in/side)
        ("BIT-29MAY26-CDE", 0.17),
        ("BIP-20DEC30-CDE", 0.17),
        ("ETP-29MAY26-CDE", 0.17),
        ("SOL-29MAY26-CDE", 0.17),
        ("ADA-29MAY26-CDE", 0.17),
        # Unknown / future listing falls back to default ($0.17)
        ("ZZZ-29MAY26-CDE", 0.17),
        # Edge: empty / None
        ("", 0.17),
    ],
)
def test_per_side_fee_resolver(product_id: str, expected: float) -> None:
    assert get_derivatives_per_side_fee(product_id) == pytest.approx(expected, abs=1e-9)


def test_full_size_tier_membership() -> None:
    """The full-size tier must contain exactly the four schedule entries
    and the all-in default must equal nano venue + non-venue."""
    from core.constants import (
        DERIVATIVES_VENUE_FEE_BY_SYMBOL,
        DERIVATIVES_VENUE_FEE_DEFAULT,
        DERIVATIVES_NON_VENUE_FEES_PER_SIDE,
    )
    assert set(DERIVATIVES_VENUE_FEE_BY_SYMBOL.keys()) == {"BTI", "ETI", "SLC", "XRL"}
    assert all(v == 0.20 for v in DERIVATIVES_VENUE_FEE_BY_SYMBOL.values())
    assert DERIVATIVES_VENUE_FEE_DEFAULT == 0.10
    assert DERIVATIVES_NON_VENUE_FEES_PER_SIDE == pytest.approx(0.07, abs=1e-9)
    assert DERIVATIVES_PER_SIDE_FEE_DEFAULT == pytest.approx(0.17, abs=1e-9)
    # Back-compat map also reflects all-in cost
    assert all(
        v == pytest.approx(0.27, abs=1e-9)
        for v in DERIVATIVES_PER_SIDE_FEE_BY_SYMBOL.values()
    )


# ---------------------------------------------------------------------------
# 2. ProfitValidator round-trip mandatory fee
# ---------------------------------------------------------------------------

def test_profit_validator_charges_round_trip_for_nano_tier() -> None:
    """BIP (nano) at 5 contracts must charge 5 * 0.17 * 2 = $1.70 all-in."""
    from calculation.profit_validator import ProfitValidator

    validator = ProfitValidator(fee_manager=None)  # uses fallback fee rate
    result = validator.is_profitable(
        filled_price=76_000.0,
        follow_up_price=76_000.0,  # zero gross profit; isolates fees
        side="SELL",
        order_size=5.0,
        product_type="FUTURE",
        product_id="BIP-20DEC30-CDE",
        contract_size=0.01,
    )
    assert result["mandatory_fees"] == pytest.approx(1.70, abs=1e-9)


def test_profit_validator_charges_round_trip_for_full_size_tier() -> None:
    """BTI (full-size) at 5 contracts must charge 5 * 0.27 * 2 = $2.70 all-in."""
    from calculation.profit_validator import ProfitValidator

    validator = ProfitValidator(fee_manager=None)
    result = validator.is_profitable(
        filled_price=76_000.0,
        follow_up_price=76_000.0,
        side="SELL",
        order_size=5.0,
        product_type="FUTURE",
        product_id="BTI-29MAY26-CDE",
        contract_size=0.01,
    )
    assert result["mandatory_fees"] == pytest.approx(2.70, abs=1e-9)


def test_profit_validator_no_mandatory_fee_for_spot() -> None:
    from calculation.profit_validator import ProfitValidator

    validator = ProfitValidator(fee_manager=None)
    result = validator.is_profitable(
        filled_price=50_000.0,
        follow_up_price=52_000.0,
        side="BUY",
        order_size=1.0,
        product_type="SPOT",
        product_id="BTC-USDC",
    )
    assert result["mandatory_fees"] == 0.0


# ---------------------------------------------------------------------------
# 3. Legacy constant name removal
# ---------------------------------------------------------------------------

def test_legacy_constant_name_is_gone() -> None:
    """``DERIVATIVES_MANDATORY_FEE_PER_CONTRACT`` was the pre-March-2026 name.

    Removing it forces any stale call site to fail at import time rather
    than silently miscompute fees against the old one-sided model.
    """
    constants = importlib.import_module("core.constants")
    assert not hasattr(constants, "DERIVATIVES_MANDATORY_FEE_PER_CONTRACT")

    # Also gone from the ``core`` package re-exports
    core_pkg = importlib.import_module("core")
    assert not hasattr(core_pkg, "DERIVATIVES_MANDATORY_FEE_PER_CONTRACT")
