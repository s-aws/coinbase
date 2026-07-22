"""Pure, versioned terms policy for the bounded BTC-USDC successor proof."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from typing import Any, Literal

from core.operator_spot_near_market_evidence import NEAR_MARKET_POLICY_REVISION

NEAR_MARKET_PRODUCT_ID = "BTC-USDC"
NEAR_MARKET_MAX_SUBMITTED_NOTIONAL_USDC = Decimal("3.10")
NEAR_MARKET_MAX_POSSIBLE_EXECUTION_NOTIONAL_USDC = Decimal("1.00")
NEAR_MARKET_MAX_AGE = timedelta(seconds=30)
NEAR_MARKET_MAX_FUTURE_SKEW = timedelta(seconds=1)


class NearMarketPolicyBlocked(ValueError):
    """Fixed, value-blind rejection from the pure derivation boundary."""


@dataclass(frozen=True, slots=True)
class NearMarketBuyPlan:
    """Identity-free terms ready for one immutable Automation definition."""

    policy_revision: Literal["BTC_USDC_POST_ONLY_BEST_BID_V1"]
    product_id: Literal["BTC-USDC"]
    side: Literal["BUY"]
    base_size: str
    limit_price: str
    submitted_notional_usdc: str
    possible_execution_notional_usdc: str
    max_submitted_notional_usdc: Literal["3.10"]
    max_possible_execution_notional_usdc: Literal["1.00"]
    post_only: Literal[True]


def _decimal(value: Any, *, code: str, allow_zero: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise NearMarketPolicyBlocked(code)
    try:
        parsed = Decimal(str(value).strip())
    except (AttributeError, InvalidOperation, TypeError, ValueError):
        raise NearMarketPolicyBlocked(code) from None
    if (
        not parsed.is_finite()
        or parsed < 0
        or (not allow_zero and parsed == 0)
    ):
        raise NearMarketPolicyBlocked(code)
    return parsed


def _aware_utc(value: Any, *, code: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise NearMarketPolicyBlocked(code)
    if value.utcoffset() is None:
        raise NearMarketPolicyBlocked(code)
    return value.astimezone(timezone.utc)


def _floor_to_increment(value: Decimal, increment: Decimal) -> Decimal:
    return (value / increment).to_integral_value(rounding=ROUND_FLOOR) * increment


def _text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def derive_near_market_buy_plan(
    *,
    product_id: str,
    best_bid: Any,
    best_ask: Any,
    market_observed_at: datetime,
    evaluated_at: datetime,
    base_increment: Any,
    price_increment: Any,
    base_min_size: Any,
    quote_min_size: Any,
    available_usdc: Any,
    maker_fee_rate: Any,
) -> NearMarketBuyPlan:
    """Derive one capped maker BUY from one documented market snapshot.

    The price is the fresh same-snapshot best bid rounded down to the product
    tick. Size is rounded down to the base increment after reserving the
    documented maker fee from the available USDC wallet. No caller-supplied
    order term is accepted.
    """

    if product_id != NEAR_MARKET_PRODUCT_ID:
        raise NearMarketPolicyBlocked("near_market_product_blocked")
    observed = _aware_utc(
        market_observed_at,
        code="near_market_snapshot_timestamp_invalid",
    )
    evaluated = _aware_utc(
        evaluated_at,
        code="near_market_snapshot_timestamp_invalid",
    )
    if observed - evaluated > NEAR_MARKET_MAX_FUTURE_SKEW:
        raise NearMarketPolicyBlocked("near_market_snapshot_future")
    if evaluated - observed > NEAR_MARKET_MAX_AGE:
        raise NearMarketPolicyBlocked("near_market_snapshot_stale")

    bid = _decimal(best_bid, code="near_market_snapshot_invalid")
    ask = _decimal(best_ask, code="near_market_snapshot_invalid")
    if ask < bid:
        raise NearMarketPolicyBlocked("near_market_snapshot_invalid")
    try:
        base_tick = _decimal(
            base_increment,
            code="near_market_product_metadata_invalid",
        )
        price_tick = _decimal(
            price_increment,
            code="near_market_product_metadata_invalid",
        )
        minimum_base = _decimal(
            base_min_size,
            code="near_market_product_metadata_invalid",
        )
        minimum_quote = _decimal(
            quote_min_size,
            code="near_market_product_metadata_invalid",
        )
    except NearMarketPolicyBlocked:
        raise

    limit_price = _floor_to_increment(bid, price_tick)
    if limit_price <= 0:
        raise NearMarketPolicyBlocked("near_market_product_metadata_invalid")
    if limit_price >= ask:
        raise NearMarketPolicyBlocked("near_market_post_only_crossing")

    wallet = _decimal(
        available_usdc,
        code="near_market_wallet_insufficient",
    )
    fee = _decimal(
        maker_fee_rate,
        code="near_market_fee_invalid",
        allow_zero=True,
    )
    if fee >= 1:
        raise NearMarketPolicyBlocked("near_market_fee_invalid")
    notional_budget = min(
        NEAR_MARKET_MAX_SUBMITTED_NOTIONAL_USDC,
        NEAR_MARKET_MAX_POSSIBLE_EXECUTION_NOTIONAL_USDC,
        wallet / (Decimal("1") + fee),
    )
    base_size = _floor_to_increment(notional_budget / limit_price, base_tick)
    submitted = base_size * limit_price
    if (
        base_size <= 0
        or base_size < minimum_base
        or submitted < minimum_quote
        or submitted > NEAR_MARKET_MAX_SUBMITTED_NOTIONAL_USDC
        or submitted > NEAR_MARKET_MAX_POSSIBLE_EXECUTION_NOTIONAL_USDC
        or submitted * (Decimal("1") + fee) > wallet
    ):
        raise NearMarketPolicyBlocked("near_market_no_valid_size")

    submitted_text = _text(submitted)
    return NearMarketBuyPlan(
        policy_revision=NEAR_MARKET_POLICY_REVISION,
        product_id=NEAR_MARKET_PRODUCT_ID,
        side="BUY",
        base_size=_text(base_size),
        limit_price=_text(limit_price),
        submitted_notional_usdc=submitted_text,
        possible_execution_notional_usdc=submitted_text,
        max_submitted_notional_usdc="3.10",
        max_possible_execution_notional_usdc="1.00",
        post_only=True,
    )


def evaluate_near_market_post_only_limit(
    *,
    side: Any,
    limit_price: Any,
    post_only: Any,
    best_bid: Any,
    best_ask: Any,
    market_source: Any,
) -> dict[str, Any]:
    """Evaluate the narrow V4-V6 standing rule with sanitized evidence."""

    try:
        price = _decimal(limit_price, code="near_market_limit_invalid")
        bid = _decimal(best_bid, code="near_market_snapshot_invalid")
        ask = _decimal(best_ask, code="near_market_snapshot_invalid")
    except NearMarketPolicyBlocked as exc:
        return {
            "allowed": False,
            "effective_allowed": False,
            "blocker": str(exc),
            "policy": NEAR_MARKET_POLICY_REVISION,
        }
    blocker = None
    if str(side or "").upper() != "BUY":
        blocker = "near_market_side_blocked"
    elif post_only is not True:
        blocker = "near_market_post_only_required"
    elif market_source != "coinbase_rest_market_trade_snapshot":
        blocker = "near_market_market_source_invalid"
    elif ask < bid:
        blocker = "near_market_snapshot_invalid"
    elif price > bid:
        blocker = "near_market_limit_above_bid"
    elif price >= ask:
        blocker = "near_market_post_only_crossing"
    allowed = blocker is None
    return {
        "allowed": allowed,
        "effective_allowed": allowed,
        "blocker": blocker,
        "policy": NEAR_MARKET_POLICY_REVISION,
        "post_only_required": True,
        "same_snapshot_required": True,
    }
