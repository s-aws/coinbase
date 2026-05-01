"""Regression tests for calculation.price_camouflage.

The camouflage helper is opt-in and side-effect-free; these tests pin
the contract callers depend on:

* Round prices are nudged off-magnet, never onto another magnet.
* Side determines direction: passive BUY -> down, passive SELL -> up.
* Aggressive mode flips that.
* Output is always tick-aligned (matches the product's price_increment).
* Output is deterministic for a given (price, side, seed).
* Non-round prices are left strictly alone.
* Bad inputs return the input unchanged (never raise).
"""

import pytest

from calculation.price_camouflage import (
    MODE_AGGRESSIVE,
    MODE_PASSIVE,
    camouflage_round_price,
)


def _is_tick_aligned(price: float, increment: str) -> bool:
    from decimal import Decimal
    return (Decimal(str(price)) / Decimal(str(increment))) % 1 == 0


def test_passive_buy_moves_down():
    p = camouflage_round_price(50000.0, side="BUY", price_increment="1",
                               mode=MODE_PASSIVE, seed="sid_a")
    assert 50000 - 7 <= p < 50000


def test_passive_sell_moves_up():
    p = camouflage_round_price(50000.0, side="SELL", price_increment="1",
                               mode=MODE_PASSIVE, seed="sid_a")
    assert 50000 < p <= 50000 + 7


def test_aggressive_buy_moves_up():
    p = camouflage_round_price(50000.0, side="BUY", price_increment="1",
                               mode=MODE_AGGRESSIVE, seed="sid_a")
    assert 50000 < p <= 50000 + 7


def test_aggressive_sell_moves_down():
    p = camouflage_round_price(50000.0, side="SELL", price_increment="1",
                               mode=MODE_AGGRESSIVE, seed="sid_a")
    assert 50000 - 7 <= p < 50000


def test_output_is_tick_aligned():
    p = camouflage_round_price(50000.0, side="BUY", price_increment="0.5",
                               seed="sid_b")
    assert _is_tick_aligned(p, "0.5")


def test_deterministic_for_same_inputs():
    p1 = camouflage_round_price(50000.0, side="BUY", price_increment="1", seed="sid_x")
    p2 = camouflage_round_price(50000.0, side="BUY", price_increment="1", seed="sid_x")
    assert p1 == p2


def test_different_seeds_can_produce_different_offsets():
    """Statistical: across many seeds we expect at least two distinct outputs.
    Single-seed equality is allowed (collisions exist), so we sample broadly."""
    outputs = {
        camouflage_round_price(
            50000.0, side="BUY", price_increment="1", seed=f"sid_{i}",
        )
        for i in range(64)
    }
    assert len(outputs) > 1


def test_non_round_price_left_alone():
    # 50001 has zero trailing zero ticks at $1 increment.
    assert camouflage_round_price(
        50001.0, side="BUY", price_increment="1", seed="x"
    ) == 50001.0


def test_below_min_zeros_threshold_left_alone():
    # 50500 has 2 trailing zeros; raise threshold to 3 so it should pass through.
    assert camouflage_round_price(
        50500.0, side="BUY", price_increment="1", seed="x",
        min_zeros_to_camouflage=3,
    ) == 50500.0


def test_invalid_side_returns_input_unchanged():
    assert camouflage_round_price(
        50000.0, side="LONG", price_increment="1", seed="x"
    ) == 50000.0


def test_invalid_mode_returns_input_unchanged():
    assert camouflage_round_price(
        50000.0, side="BUY", price_increment="1", mode="evil", seed="x"
    ) == 50000.0


def test_non_positive_price_returns_input_unchanged():
    assert camouflage_round_price(
        0.0, side="BUY", price_increment="1", seed="x"
    ) == 0.0
    assert camouflage_round_price(
        -10.0, side="BUY", price_increment="1", seed="x"
    ) == -10.0


def test_does_not_drive_price_below_zero():
    # Tiny price, big offset cap. Camouflage must NOT produce <= 0.
    p = camouflage_round_price(
        1.0, side="BUY", price_increment="0.01", seed="x",
        max_offset_ticks=10000,
    )
    assert p > 0


def test_side_mode_constants_match_order_side_enum():
    """Producer/consumer contract: side strings used here must match
    the canonical OrderSide enum so callers can pass either freely."""
    from core.enums import OrderSide
    assert OrderSide.BUY.value == "BUY"
    assert OrderSide.SELL.value == "SELL"
