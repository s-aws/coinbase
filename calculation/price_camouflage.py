"""Round-number camouflage for limit prices.

Many market-making and stop-hunting algorithms cluster activity around
"round" prices — 50000, 50500, 1.00, 0.50, etc. — because those are
where retail stop-loss and take-profit orders concentrate. Placing a
limit at one of those exact levels marks an order as retail flow and
makes it a more attractive target for adverse selection.

This module provides a single function, ``camouflage_round_price()``,
that nudges a price off-magnet by a small number of ticks in a
configurable direction:

* ``"passive"``  — move AWAY from the resting market (BUY → lower,
                   SELL → higher). Better fill price IF you fill;
                   higher chance of missing.
* ``"aggressive"`` — move TOWARD the resting market (BUY → higher,
                   SELL → lower). Easier fill, slightly worse price.

The nudge is **deterministic** for a given (price, side, seed) tuple,
so:
  - Reproducing a strategy gives the same prices.
  - Repeated reveals of the same logical order land at the same
    camouflaged price (no drift).
  - Tests can pin behavior without freezing time or mocking RNG.

Always returns a tick-aligned price by routing through
``quantize_to_increment()``. Callers must pass the product's
``price_increment`` string from ``products.json`` so we never produce
a price the exchange will reject.

Honest scope notes:
  - This is one layer of evasion. It does not defeat a sophisticated
    counterparty that watches for ALL orders near round numbers, not
    exact hits. It just removes the cheapest tell.
  - Camouflage is **off by default** in every consumer because it
    silently changes prices, which violates the "generator follows
    instruction" property of ``create_limit_order_span``. Opt in
    explicitly per call.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Optional

from calculation.formatter import quantize_to_increment


# Public side strings (kept as plain strings to avoid a circular import
# on ``core.enums``; values match ``OrderSide.BUY/SELL`` for a producer/
# consumer contract that the regression test below pins).
_BUY = "BUY"
_SELL = "SELL"

# Public mode strings.
MODE_PASSIVE = "passive"
MODE_AGGRESSIVE = "aggressive"
_MODES = frozenset({MODE_PASSIVE, MODE_AGGRESSIVE})


def _trailing_zero_count(price: float, increment: str) -> int:
    """How many trailing zero ticks above the increment does ``price`` carry?

    Examples (increment "1"):
        50000 -> 4   (50_000 has four trailing zeros at tick scale)
        50500 -> 2
        50001 -> 0

    Examples (increment "0.01"):
        100.00  -> 4   (10000 ticks)
        100.50  -> 1
        100.51  -> 0

    Returns 0 for non-positive inputs.
    """
    if price <= 0:
        return 0
    inc = Decimal(str(increment))
    if inc <= 0:
        return 0
    ticks = int((Decimal(str(price)) / inc).to_integral_value())
    if ticks == 0:
        return 0
    count = 0
    while ticks % 10 == 0:
        ticks //= 10
        count += 1
    return count


def _deterministic_offset_ticks(seed: str, max_ticks: int) -> int:
    """Hash ``seed`` to an integer in ``[1, max_ticks]`` (never zero).

    We never return zero because the whole point is to *not* land on
    the magnet. ``max_ticks`` is clamped to >= 1.
    """
    if max_ticks < 1:
        return 1
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    raw = int.from_bytes(digest[:4], "big")
    return (raw % max_ticks) + 1


def camouflage_round_price(
    price: float,
    *,
    side: str,
    price_increment: str,
    mode: str = MODE_PASSIVE,
    seed: Optional[str] = None,
    max_offset_ticks: int = 7,
    min_zeros_to_camouflage: int = 2,
) -> float:
    """Nudge a round price off-magnet, side-aware and tick-aligned.

    Args:
        price: The price you'd otherwise submit.
        side: ``"BUY"`` or ``"SELL"``. Determines nudge direction
            relative to the market under each mode.
        price_increment: The product's tick size as a string (from
            ``products.json``: ``metadata[product_id]["price_increment"]``).
        mode: ``"passive"`` (away from market — better price, harder
            fill) or ``"aggressive"`` (toward market — easier fill,
            slightly worse price). Defaults to ``"passive"`` because
            the operator usually wants the better fill price; this
            is the same risk/reward as posting a slightly more
            patient limit.
        seed: Determinism key. For a stealth-order reveal you'd
            typically pass the ``stealth_order_id`` so every reveal of
            the same logical order lands at the same camouflaged
            price. If ``None``, a price-derived seed is used (so the
            same input always produces the same output but two
            different orders at the same price collide).
        max_offset_ticks: Upper bound on the camouflage shift, in
            ticks. The actual shift is in ``[1, max_offset_ticks]``.
            Default 7 — small enough to not affect economics on most
            products, large enough to clear the typical 1-5-tick stop
            cluster.
        min_zeros_to_camouflage: Only nudge prices with at least this
            many trailing zero ticks. Default 2 (50500 yes, 50501 no).
            Set to 0 to nudge every price.

    Returns:
        Nudged price, quantized to ``price_increment``. Returns the
        input unchanged if camouflage isn't warranted (price isn't
        round enough) or if inputs are invalid (non-positive price,
        unknown side, etc.) — never raises on bad input by design,
        because price-path code must not break order placement.

    Examples:
        >>> # BUY at round 50000 with $1 ticks, passive (move down).
        >>> p = camouflage_round_price(
        ...     50000.0, side="BUY", price_increment="1", seed="sid_abc",
        ... )
        >>> 49993 <= p <= 49999
        True

        >>> # SELL at 50000, passive (move up).
        >>> p = camouflage_round_price(
        ...     50000.0, side="SELL", price_increment="1", seed="sid_abc",
        ... )
        >>> 50001 <= p <= 50007
        True

        >>> # 50001 isn't round enough; left alone.
        >>> camouflage_round_price(
        ...     50001.0, side="BUY", price_increment="1", seed="x",
        ... )
        50001.0
    """
    if price is None or price <= 0:
        return price
    if side not in (_BUY, _SELL):
        return price
    if mode not in _MODES:
        return price

    zeros = _trailing_zero_count(price, price_increment)
    if zeros < max(0, min_zeros_to_camouflage):
        return price

    seed_str = seed if seed is not None else f"{side}|{price}|{price_increment}"
    offset_ticks = _deterministic_offset_ticks(seed_str, max_offset_ticks)
    inc = float(price_increment)
    offset = offset_ticks * inc

    # Mode → sign convention:
    #   passive: BUY pays less (down), SELL receives more (up).
    #   aggressive: BUY pays more (up), SELL receives less (down).
    if mode == MODE_PASSIVE:
        nudged = price - offset if side == _BUY else price + offset
    else:  # aggressive
        nudged = price + offset if side == _BUY else price - offset

    if nudged <= 0:
        return price

    # Always re-quantize. ``camouflage`` should never produce a price
    # the exchange will reject. Direction matches the side's
    # economic preference so the snap doesn't undo the nudge.
    direction = "down" if side == _BUY else "up"
    try:
        return float(quantize_to_increment(nudged, str(price_increment), direction=direction))
    except (ValueError, ArithmeticError):
        return price
