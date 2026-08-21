"""Canonical normalization for every exchange-bound limit price.

This module deliberately owns the product-grid boundary.  Callers select an
explicit :class:`~core.enums.PriceRoundingPolicy`, then persist and submit only
the returned ``effective_price``.  Missing or invalid product metadata fails
closed; no raw price is returned as an exchange-safe fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from calculation.formatter import quantize_to_increment
from configuration import get_product_metadata
from core.enums import (
    OrderSide,
    PriceRoundingPolicy,
    RoundingDirection,
)


@dataclass(frozen=True)
class PriceNormalizationResult:
    """Auditable outcome of :func:`normalize_price_for_product`.

    ``effective_price`` is populated only when ``ok`` is true.  This makes a
    missing tick, invalid side, or malformed value fail closed instead of
    leaving callers a raw price they could accidentally persist or submit.
    """

    ok: bool
    requested_price: Optional[float]
    effective_price: Optional[float]
    increment: Optional[str]
    policy: Optional[PriceRoundingPolicy]
    rounding_direction: Optional[RoundingDirection]
    adjusted: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.ok


def _decimal(value: Any) -> Optional[Decimal]:
    try:
        converted = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return converted if converted.is_finite() else None


def _coerce_policy(policy: Any) -> Optional[PriceRoundingPolicy]:
    if isinstance(policy, PriceRoundingPolicy):
        return policy
    try:
        return PriceRoundingPolicy(str(policy))
    except (TypeError, ValueError):
        return None


def _coerce_side(side: Any) -> Optional[OrderSide]:
    if isinstance(side, OrderSide):
        return side
    try:
        return OrderSide(str(side).upper())
    except (TypeError, ValueError):
        return None


def _rounding_direction(
    policy: PriceRoundingPolicy,
    side: Any,
) -> Optional[RoundingDirection]:
    if policy == PriceRoundingPolicy.NEAREST:
        return RoundingDirection.NEAREST
    if policy == PriceRoundingPolicy.UP:
        return RoundingDirection.UP
    if policy == PriceRoundingPolicy.DOWN:
        return RoundingDirection.DOWN

    normalized_side = _coerce_side(side)
    if normalized_side == OrderSide.BUY:
        return RoundingDirection.DOWN
    if normalized_side == OrderSide.SELL:
        return RoundingDirection.UP
    return None


def normalize_price_for_product(
    price: Any,
    *,
    product_id: str,
    side: Any = None,
    policy: PriceRoundingPolicy = PriceRoundingPolicy.SIDE_CONSERVATIVE,
) -> PriceNormalizationResult:
    """Normalize one exchange-bound price against authoritative metadata.

    ``SIDE_CONSERVATIVE`` preserves configured/manual limit intent by rounding
    BUY down and SELL up.  ``NEAREST``, ``UP``, and ``DOWN`` remain explicit
    policies for paths whose established semantics require them (for example
    hotpoint placement and anchor-boundary repricing).
    """
    normalized_policy = _coerce_policy(policy)
    requested_decimal = _decimal(price)
    requested_price = (
        float(requested_decimal) if requested_decimal is not None else None
    )

    if normalized_policy is None:
        return PriceNormalizationResult(
            False,
            requested_price,
            None,
            None,
            None,
            None,
            False,
            f"unsupported price rounding policy: {policy!r}",
        )
    if requested_decimal is None:
        return PriceNormalizationResult(
            False,
            None,
            None,
            None,
            normalized_policy,
            None,
            False,
            f"price must be a finite number, got {price!r}",
        )
    if requested_decimal <= 0:
        return PriceNormalizationResult(
            False,
            requested_price,
            None,
            None,
            normalized_policy,
            None,
            False,
            f"price must be greater than 0, got {price!r}",
        )
    if not product_id:
        return PriceNormalizationResult(
            False,
            requested_price,
            None,
            None,
            normalized_policy,
            None,
            False,
            "product_id is required for price normalization",
        )

    metadata = get_product_metadata(str(product_id))
    increment_value = metadata.get("price_increment")
    if increment_value in (None, ""):
        return PriceNormalizationResult(
            False,
            requested_price,
            None,
            None,
            normalized_policy,
            None,
            False,
            f"missing price_increment for {product_id}",
        )

    increment = str(increment_value)
    increment_decimal = _decimal(increment)
    if increment_decimal is None or increment_decimal <= 0:
        return PriceNormalizationResult(
            False,
            requested_price,
            None,
            increment,
            normalized_policy,
            None,
            False,
            f"invalid price_increment {increment!r} for {product_id}",
        )

    direction = _rounding_direction(normalized_policy, side)
    if direction is None:
        return PriceNormalizationResult(
            False,
            requested_price,
            None,
            increment,
            normalized_policy,
            None,
            False,
            "SIDE_CONSERVATIVE price normalization requires side BUY or SELL",
        )

    try:
        effective_price = quantize_to_increment(
            requested_decimal,
            increment,
            direction=direction.value,
        )
    except (ArithmeticError, TypeError, ValueError) as exc:
        return PriceNormalizationResult(
            False,
            requested_price,
            None,
            increment,
            normalized_policy,
            direction,
            False,
            f"price normalization failed for {product_id}: {exc}",
        )

    effective_decimal = _decimal(effective_price)
    if effective_decimal is None or effective_decimal <= 0:
        return PriceNormalizationResult(
            False,
            requested_price,
            None,
            increment,
            normalized_policy,
            direction,
            False,
            f"normalized price must be greater than 0 for {product_id}",
        )

    return PriceNormalizationResult(
        True,
        requested_price,
        float(effective_decimal),
        increment,
        normalized_policy,
        direction,
        effective_decimal != requested_decimal,
        "",
    )
