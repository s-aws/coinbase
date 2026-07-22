"""Pure V7-V9 minimum-size policy for the bounded BTC-USDC proof."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
from typing import Any, Literal


MINIMUM_SIZE_POLICY_REVISION = (
    "BTC_USDC_POST_ONLY_BEST_BID_MINIMUM_SIZE_V2"
)
MINIMUM_SIZE_PRODUCT_ID = "BTC-USDC"
MINIMUM_SIZE_MAX_SUBMITTED_NOTIONAL_USDC = Decimal("3.10")
MINIMUM_SIZE_ABSOLUTE_EXECUTION_CAP_USDC = Decimal("3.10")
MINIMUM_SIZE_V4_EXECUTION_CAP_USDC = Decimal("1.00")
MINIMUM_SIZE_MAX_AGE = timedelta(seconds=30)
MINIMUM_SIZE_MAX_FUTURE_SKEW = timedelta(seconds=1)

MinimumSizeV4BoundaryClassification = Literal[
    "minimum_size_v4_base_minimum_conflict",
    "minimum_size_v4_quote_minimum_conflict",
    "minimum_size_v4_increment_conflict",
    "minimum_size_v4_fee_reserve_conflict",
    "minimum_size_v4_boundary_not_reproduced",
]


class MinimumSizePolicyBlocked(ValueError):
    """Fixed, value-blind rejection from the pure derivation boundary."""


@dataclass(frozen=True, slots=True)
class MinimumSizeBuyPlan:
    """Identity-free, minimum-sized terms for one immutable successor."""

    policy_revision: Literal[
        "BTC_USDC_POST_ONLY_BEST_BID_MINIMUM_SIZE_V2"
    ]
    product_id: Literal["BTC-USDC"]
    side: Literal["BUY"]
    base_size: str
    limit_price: str
    submitted_notional_usdc: str
    possible_execution_notional_usdc: str
    max_submitted_notional_usdc: Literal["3.10"]
    max_possible_execution_notional_usdc: str
    v4_boundary_classification: MinimumSizeV4BoundaryClassification
    post_only: Literal[True]


def _decimal(value: Any, *, code: str, allow_zero: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise MinimumSizePolicyBlocked(code)
    try:
        parsed = Decimal(str(value).strip())
    except (AttributeError, InvalidOperation, TypeError, ValueError):
        raise MinimumSizePolicyBlocked(code) from None
    if (
        not parsed.is_finite()
        or parsed < 0
        or (not allow_zero and parsed == 0)
    ):
        raise MinimumSizePolicyBlocked(code)
    return parsed


def _aware_utc(value: Any, *, code: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise MinimumSizePolicyBlocked(code)
    return value.astimezone(timezone.utc)


def _floor_to_increment(value: Decimal, increment: Decimal) -> Decimal:
    return (value / increment).to_integral_value(rounding=ROUND_FLOOR) * increment


def _ceil_to_increment(value: Decimal, increment: Decimal) -> Decimal:
    return (value / increment).to_integral_value(rounding=ROUND_CEILING) * increment


def _text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _v4_boundary_classification(
    *,
    minimum_base: Decimal,
    minimum_quote: Decimal,
    base_from_base_minimum: Decimal,
    base_from_quote_minimum: Decimal,
    base_size: Decimal,
    limit_price: Decimal,
    submitted: Decimal,
    fee_reserved_cap: Decimal,
) -> MinimumSizeV4BoundaryClassification:
    if submitted <= MINIMUM_SIZE_V4_EXECUTION_CAP_USDC:
        if fee_reserved_cap > MINIMUM_SIZE_V4_EXECUTION_CAP_USDC:
            return "minimum_size_v4_fee_reserve_conflict"
        return "minimum_size_v4_boundary_not_reproduced"
    if minimum_base * limit_price > MINIMUM_SIZE_V4_EXECUTION_CAP_USDC:
        return "minimum_size_v4_base_minimum_conflict"
    if minimum_quote > MINIMUM_SIZE_V4_EXECUTION_CAP_USDC:
        return "minimum_size_v4_quote_minimum_conflict"
    if (
        base_size > base_from_base_minimum
        or base_size > base_from_quote_minimum
        or submitted > MINIMUM_SIZE_V4_EXECUTION_CAP_USDC
    ):
        return "minimum_size_v4_increment_conflict"
    return "minimum_size_v4_boundary_not_reproduced"


def derive_minimum_size_buy_plan(
    *,
    product_id: str,
    best_bid: Any,
    best_ask: Any,
    market_observed_at: datetime,
    evaluated_at: datetime,
    base_increment: Any,
    quote_increment: Any,
    price_increment: Any,
    base_min_size: Any,
    quote_min_size: Any,
    available_usdc: Any,
    maker_fee_rate: Any,
) -> MinimumSizeBuyPlan:
    """Derive the smallest documented maker BUY and its fee-reserved cap.

    Price is the fresh same-snapshot best bid rounded down to the documented
    price increment. Size is the smallest base-increment multiple satisfying
    both documented base and quote minimums. The proof-only execution cap is
    the smallest quote-increment multiple covering submitted notional plus the
    documented maker-fee reserve; both caps remain strictly below 3.10 USDC.
    """

    if product_id != MINIMUM_SIZE_PRODUCT_ID:
        raise MinimumSizePolicyBlocked("minimum_size_product_blocked")
    observed = _aware_utc(
        market_observed_at,
        code="minimum_size_snapshot_timestamp_invalid",
    )
    evaluated = _aware_utc(
        evaluated_at,
        code="minimum_size_snapshot_timestamp_invalid",
    )
    if observed - evaluated > MINIMUM_SIZE_MAX_FUTURE_SKEW:
        raise MinimumSizePolicyBlocked("minimum_size_snapshot_future")
    if evaluated - observed > MINIMUM_SIZE_MAX_AGE:
        raise MinimumSizePolicyBlocked("minimum_size_snapshot_stale")

    bid = _decimal(best_bid, code="minimum_size_snapshot_invalid")
    ask = _decimal(best_ask, code="minimum_size_snapshot_invalid")
    if ask < bid:
        raise MinimumSizePolicyBlocked("minimum_size_snapshot_invalid")
    base_tick = _decimal(
        base_increment,
        code="minimum_size_product_metadata_invalid",
    )
    quote_tick = _decimal(
        quote_increment,
        code="minimum_size_product_metadata_invalid",
    )
    price_tick = _decimal(
        price_increment,
        code="minimum_size_product_metadata_invalid",
    )
    minimum_base = _decimal(
        base_min_size,
        code="minimum_size_product_metadata_invalid",
    )
    minimum_quote = _decimal(
        quote_min_size,
        code="minimum_size_product_metadata_invalid",
    )

    limit_price = _floor_to_increment(bid, price_tick)
    if limit_price <= 0:
        raise MinimumSizePolicyBlocked("minimum_size_product_metadata_invalid")
    if limit_price >= ask:
        raise MinimumSizePolicyBlocked("minimum_size_post_only_crossing")

    wallet = _decimal(
        available_usdc,
        code="minimum_size_wallet_insufficient",
    )
    fee = _decimal(
        maker_fee_rate,
        code="minimum_size_fee_invalid",
        allow_zero=True,
    )
    if fee >= 1:
        raise MinimumSizePolicyBlocked("minimum_size_fee_invalid")

    base_from_base_minimum = _ceil_to_increment(minimum_base, base_tick)
    base_from_quote_minimum = _ceil_to_increment(
        minimum_quote / limit_price,
        base_tick,
    )
    base_size = max(base_from_base_minimum, base_from_quote_minimum)
    if (
        base_size <= 0
        or _floor_to_increment(base_size, base_tick) != base_size
    ):
        raise MinimumSizePolicyBlocked("minimum_size_increment_conflict")

    submitted = base_size * limit_price
    if submitted < minimum_quote or base_size < minimum_base:
        raise MinimumSizePolicyBlocked("minimum_size_increment_conflict")
    if submitted >= MINIMUM_SIZE_MAX_SUBMITTED_NOTIONAL_USDC:
        raise MinimumSizePolicyBlocked("minimum_size_submitted_cap_conflict")

    required_wallet = submitted * (Decimal("1") + fee)
    fee_reserved_cap = _ceil_to_increment(required_wallet, quote_tick)
    if fee_reserved_cap >= MINIMUM_SIZE_ABSOLUTE_EXECUTION_CAP_USDC:
        raise MinimumSizePolicyBlocked("minimum_size_fee_reserve_cap_conflict")
    if wallet < fee_reserved_cap:
        raise MinimumSizePolicyBlocked("minimum_size_wallet_insufficient")

    classification = _v4_boundary_classification(
        minimum_base=minimum_base,
        minimum_quote=minimum_quote,
        base_from_base_minimum=base_from_base_minimum,
        base_from_quote_minimum=base_from_quote_minimum,
        base_size=base_size,
        limit_price=limit_price,
        submitted=submitted,
        fee_reserved_cap=fee_reserved_cap,
    )
    return MinimumSizeBuyPlan(
        policy_revision=MINIMUM_SIZE_POLICY_REVISION,
        product_id=MINIMUM_SIZE_PRODUCT_ID,
        side="BUY",
        base_size=_text(base_size),
        limit_price=_text(limit_price),
        submitted_notional_usdc=_text(submitted),
        possible_execution_notional_usdc=_text(submitted),
        max_submitted_notional_usdc="3.10",
        max_possible_execution_notional_usdc=_text(fee_reserved_cap),
        v4_boundary_classification=classification,
        post_only=True,
    )
