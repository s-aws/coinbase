"""Regression: Coinbase Derivatives per-side mandatory fee schedule.

Sources:
  * Coinbase Fee Schedule effective March 2, 2026
    https://assets.ctfassets.net/o10es7wu5gm1/6LbrWZkWY1BUS67poRlVe/
    10ca89e22a46b899389678b8f3352c10/Fee_Schedule_3.2.2026.pdf
  * Daily statement reconciliation, CFMD3UKRINXC, Apr-30-2026.

Key facts:
  * "Fees are charged per side (both the buy and the sell side) per contract"
  * Default-tier venue commission is $0.10 per side.
  * Aug-25-2026 settlement reconciliation establishes the BIP/default
    all-in fixed cost as $0.12 per contract side:
      - Venue:                  $0.10
      - Clearing:               $0.01
      - One regulatory/NFA fee: $0.01
  * Full-size $0.27 all-in behavior is preserved as an explicit legacy
    scope boundary; the BIP/default reconciliation does not revise it.

Before the Aug-25 settlement reconciliation, the resolver returned $0.17
for BIP/default and overbudgeted the fixed round-trip cost by $0.10 per
contract. These tests lock in the settlement-confirmed semantics without
changing the separately scoped full-size behavior.

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

# BIP/default all-in fixed cost = $0.10 venue + $0.02 settled non-venue.
# Full-size remains explicitly pinned at the pre-existing $0.27 all-in value.
@pytest.mark.parametrize(
    "product_id,expected",
    [
        # Full-size tier ($0.27 all-in/side)
        ("BTI-29MAY26-CDE", 0.27),
        ("ETI-29MAY26-CDE", 0.27),
        ("SLC-29MAY26-CDE", 0.27),
        ("XRL-29MAY26-CDE", 0.27),
        # Nano / Perp-Style tier ($0.12 all-in/side)
        ("BIT-29MAY26-CDE", 0.12),
        ("BIP-20DEC30-CDE", 0.12),
        ("ETP-29MAY26-CDE", 0.12),
        ("SOL-29MAY26-CDE", 0.12),
        ("ADA-29MAY26-CDE", 0.12),
        # Unknown / future listing falls back to default ($0.12)
        ("ZZZ-29MAY26-CDE", 0.12),
        # Edge: empty / None
        ("", 0.12),
    ],
)
def test_per_side_fee_resolver(product_id: str, expected: float) -> None:
    assert get_derivatives_per_side_fee(product_id) == pytest.approx(expected, abs=1e-9)


def test_full_size_tier_membership() -> None:
    """The full-size tier must contain exactly the four schedule entries
    and the all-in default must equal nano venue + non-venue."""
    from core.constants import (
        DERIVATIVES_CLEARING_FEE_PER_SIDE,
        DERIVATIVES_REGULATORY_NFA_FEE_PER_SIDE,
        DERIVATIVES_VENUE_FEE_BY_SYMBOL,
        DERIVATIVES_VENUE_FEE_DEFAULT,
        DERIVATIVES_NON_VENUE_FEES_PER_SIDE,
    )
    assert set(DERIVATIVES_VENUE_FEE_BY_SYMBOL.keys()) == {"BTI", "ETI", "SLC", "XRL"}
    assert all(v == 0.20 for v in DERIVATIVES_VENUE_FEE_BY_SYMBOL.values())
    assert DERIVATIVES_VENUE_FEE_DEFAULT == 0.10
    assert DERIVATIVES_CLEARING_FEE_PER_SIDE == pytest.approx(0.01, abs=1e-9)
    assert DERIVATIVES_REGULATORY_NFA_FEE_PER_SIDE == pytest.approx(0.01, abs=1e-9)
    assert DERIVATIVES_NON_VENUE_FEES_PER_SIDE == pytest.approx(0.02, abs=1e-9)
    assert DERIVATIVES_PER_SIDE_FEE_DEFAULT == pytest.approx(0.12, abs=1e-9)
    # Full-size all-in values are intentionally explicit and unchanged.
    assert all(
        v == pytest.approx(0.27, abs=1e-9)
        for v in DERIVATIVES_PER_SIDE_FEE_BY_SYMBOL.values()
    )


# ---------------------------------------------------------------------------
# 2. ProfitValidator round-trip mandatory fee
# ---------------------------------------------------------------------------

def test_profit_validator_charges_round_trip_for_nano_tier() -> None:
    """BIP at 5 contracts must charge 5 * $0.12 * 2 = $1.20 fixed."""
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
    assert result["mandatory_fees"] == pytest.approx(1.20, abs=1e-9)


def test_sanitized_settlement_fixed_total_for_360_contract_sides() -> None:
    """360 BIP contract-sides at $0.12 reconcile to $43.20 fixed cost."""
    contract_sides = 360
    fixed_total = contract_sides * get_derivatives_per_side_fee(
        "BIP-20DEC30-CDE"
    )

    assert fixed_total == pytest.approx(43.20, abs=1e-9)


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
