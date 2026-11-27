"""Canonical planning for declarative stealth-order spans.

The browser, Python compatibility wrapper, and bridge all use this module so
price stepping, size distribution, hierarchy, and derived policy behavior
cannot drift into separate implementations. Planning is side-effect free: the
entire request is validated and normalized before the bridge writes any rung.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_DOWN
import math
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple
import uuid

from calculation.price_validation import normalize_price_for_product
from calculation.size_validation import validate_and_quantize_size
from core.enums import (
    Direction,
    FollowUpRevealDirection,
    OrderSide,
    PriceRoundingPolicy,
    RepricingDistanceType,
    RevealConditionType,
    RevealPricingPolicy,
    StealthSpanCreationMode,
    StealthSpanSizeDistribution,
    TargetMovementType,
)
from core.models import RepricingPolicy


_MAX_SPAN_ORDERS = 100


class StealthSpanValidationError(ValueError):
    """Raised when a span cannot be planned without writing partial state."""


@dataclass(frozen=True)
class StealthSpanOrderSpec:
    """One fully materialized, exchange-grid-valid span rung."""

    index: int
    client_order_id: str
    product_id: str
    side: str
    total_size: float
    limit_price: float
    reveal_condition: Dict[str, Any]
    reveal_pricing_policy: str
    sizing_strategy: Dict[str, Any]
    parent_order_id: Optional[str]
    follow_up_reveal_direction: str
    notes: str
    max_order_replacements: int
    target_movement: float
    target_movement_type: str
    allow_partial_fills: bool
    anchor_repricing_policy: Dict[str, Any]
    enable_hotpoint_replication: bool

    def creation_kwargs(self) -> Dict[str, Any]:
        """Return the existing single-order creation contract for this rung."""

        return {
            "stealth_order_id": self.client_order_id,
            "product_id": self.product_id,
            "side": self.side,
            "total_size": self.total_size,
            "limit_price": self.limit_price,
            "reveal_condition": deepcopy(self.reveal_condition),
            "reveal_pricing_policy": self.reveal_pricing_policy,
            "sizing_strategy": deepcopy(self.sizing_strategy),
            "parent_order_id": self.parent_order_id,
            "follow_up_reveal_direction": self.follow_up_reveal_direction,
            "reason": "programmatic_order_span",
            "notes": self.notes,
            "max_order_replacements": self.max_order_replacements,
            "target_movement": self.target_movement,
            "target_movement_type": self.target_movement_type,
            "allow_partial_fills": self.allow_partial_fills,
            "anchor_repricing_policy": deepcopy(self.anchor_repricing_policy),
            "enable_hotpoint_replication": self.enable_hotpoint_replication,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "client_order_id": self.client_order_id,
            "parent_order_id": self.parent_order_id,
            "product_id": self.product_id,
            "side": self.side,
            "size": self.total_size,
            "price": self.limit_price,
            "reveal_condition": deepcopy(self.reveal_condition),
            "anchor_repricing_policy": deepcopy(self.anchor_repricing_policy),
        }


@dataclass(frozen=True)
class StealthSpanPlan:
    """Validated immutable plan consumed by the bridge coordinator."""

    span_id: str
    creation_mode: StealthSpanCreationMode
    size_distribution: StealthSpanSizeDistribution
    requested_total_size: float
    effective_total_size: float
    orders: Tuple[StealthSpanOrderSpec, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "span_id": self.span_id,
            "creation_mode": self.creation_mode.value,
            "size_distribution": self.size_distribution.value,
            "requested_count": len(self.orders),
            "requested_total_size": self.requested_total_size,
            "effective_total_size": self.effective_total_size,
            "orders": [order.to_dict() for order in self.orders],
        }


def _finite_decimal(value: Any, field_name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise StealthSpanValidationError(
            f"{field_name} must be a finite number"
        ) from exc
    if not result.is_finite():
        raise StealthSpanValidationError(f"{field_name} must be a finite number")
    return result


def _enum_value(enum_type, value: Any, field_name: str):
    try:
        return enum_type(str(value))
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(member.value for member in enum_type)
        raise StealthSpanValidationError(
            f"{field_name} must be one of: {allowed}"
        ) from exc


def _positive_int(value: Any, field_name: str, *, maximum: Optional[int] = None) -> int:
    if isinstance(value, bool):
        raise StealthSpanValidationError(f"{field_name} must be a positive integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise StealthSpanValidationError(
            f"{field_name} must be a positive integer"
        ) from exc
    if str(value).strip() not in {str(result), f"{result}.0"}:
        raise StealthSpanValidationError(f"{field_name} must be a positive integer")
    if result < 1 or (maximum is not None and result > maximum):
        suffix = f" between 1 and {maximum}" if maximum is not None else " greater than 0"
        raise StealthSpanValidationError(f"{field_name} must be{suffix}")
    return result


def _nonnegative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise StealthSpanValidationError(f"{field_name} must be a non-negative integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise StealthSpanValidationError(
            f"{field_name} must be a non-negative integer"
        ) from exc
    if result < 0 or float(value) != result:
        raise StealthSpanValidationError(f"{field_name} must be a non-negative integer")
    return result


def _weights(count: int, distribution: StealthSpanSizeDistribution) -> Tuple[int, ...]:
    if distribution == StealthSpanSizeDistribution.EQUAL:
        return (1,) * count
    if distribution == StealthSpanSizeDistribution.ASCENDING:
        return tuple(range(1, count + 1))
    if distribution == StealthSpanSizeDistribution.DESCENDING:
        return tuple(range(count, 0, -1))
    # Exactly ``count`` values for odd and even spans: 4 -> 1,2,2,1.
    return tuple(min(index + 1, count - index) for index in range(count))


def _apportion_units(total_units: int, weights: Sequence[int]) -> Tuple[int, ...]:
    count = len(weights)
    if total_units < count:
        raise StealthSpanValidationError(
            "total_size is too small to allocate at least one base increment "
            "to every span order"
        )

    remaining = total_units - count
    weight_sum = sum(weights)
    raw_shares = [Decimal(remaining * weight) / Decimal(weight_sum) for weight in weights]
    extras = [int(share.to_integral_value(rounding=ROUND_DOWN)) for share in raw_shares]
    residual = remaining - sum(extras)
    residual_order = sorted(
        range(count),
        key=lambda index: (raw_shares[index] - extras[index], weights[index], -index),
        reverse=True,
    )
    for index in residual_order[:residual]:
        extras[index] += 1
    return tuple(extra + 1 for extra in extras)


def _allocate_sizes(
    *,
    product_id: str,
    total_size: Decimal,
    prices: Sequence[float],
    weights: Sequence[int],
    product_metadata: Mapping[str, Any],
) -> Tuple[Tuple[float, ...], float]:
    metadata = dict(product_metadata)
    increment_raw = metadata.get("base_increment")
    increment = None
    if increment_raw not in (None, ""):
        try:
            candidate = Decimal(str(increment_raw))
        except InvalidOperation:
            candidate = Decimal(0)
        if candidate.is_finite() and candidate > 0:
            increment = candidate

    if increment is not None:
        total_units = int((total_size / increment).to_integral_value(rounding=ROUND_DOWN))
        unit_allocations = _apportion_units(total_units, weights)
        size_decimals = tuple(increment * units for units in unit_allocations)
    else:
        weight_sum = Decimal(sum(weights))
        provisional = [
            (total_size * Decimal(weight)) / weight_sum for weight in weights[:-1]
        ]
        size_decimals = tuple(provisional + [total_size - sum(provisional, Decimal(0))])

    effective_sizes = []
    for index, (size, price) in enumerate(zip(size_decimals, prices)):
        result = validate_and_quantize_size(
            float(size),
            product_id=product_id,
            price=price,
            product_metadata=metadata,
        )
        if not result.ok:
            raise StealthSpanValidationError(
                f"span order {index + 1} has an invalid size: {result.reason}"
            )
        effective_sizes.append(float(result.size))

    effective_total = math.fsum(effective_sizes)
    return tuple(effective_sizes), effective_total


def _validate_reveal_condition(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise StealthSpanValidationError("reveal_condition must be an object")
    condition = deepcopy(dict(raw))
    condition_type = _enum_value(
        RevealConditionType,
        condition.get("type"),
        "reveal_condition.type",
    )
    condition["type"] = condition_type.value

    if condition_type == RevealConditionType.PRICE_THRESHOLD:
        threshold = _finite_decimal(
            condition.get("price_threshold"),
            "reveal_condition.price_threshold",
        )
        if threshold <= 0:
            raise StealthSpanValidationError(
                "reveal_condition.price_threshold must be greater than 0"
            )
        direction = _enum_value(
            Direction,
            condition.get("direction"),
            "reveal_condition.direction",
        )
        condition["price_threshold"] = float(threshold)
        condition["direction"] = direction.value
        hold = _nonnegative_int(
            condition.get("hold_duration_seconds", 0),
            "reveal_condition.hold_duration_seconds",
        )
        condition["hold_duration_seconds"] = hold
    elif condition_type == RevealConditionType.TIME_DELAY:
        condition["delay_seconds"] = _nonnegative_int(
            condition.get("delay_seconds", 0),
            "reveal_condition.delay_seconds",
        )
        condition["jitter_seconds"] = _nonnegative_int(
            condition.get("jitter_seconds", 0),
            "reveal_condition.jitter_seconds",
        )
    elif condition_type == RevealConditionType.SPREAD:
        max_spread = _finite_decimal(
            condition.get("max_spread"),
            "reveal_condition.max_spread",
        )
        if max_spread <= 0:
            raise StealthSpanValidationError(
                "reveal_condition.max_spread must be greater than 0"
            )
        condition["max_spread"] = float(max_spread)

    return condition


def _materialize_anchor_policy(
    raw: Any,
    *,
    index: int,
    price_step: Decimal,
    start_price: Decimal,
) -> Dict[str, Any]:
    try:
        RepricingPolicy.validate_storage_input(raw)
    except ValueError as exc:
        raise StealthSpanValidationError(
            f"invalid anchor_repricing_policy: {exc}"
        ) from exc
    policy = RepricingPolicy.from_dict(dict(raw) if isinstance(raw, Mapping) else None)
    if not policy.enabled or policy.target_distance <= 0:
        return {"enabled": False}

    offset = abs(price_step) * index
    if policy.distance_type == RepricingDistanceType.PERCENT:
        offset /= start_price
    materialized = policy.to_dict()
    materialized["target_distance"] = policy.target_distance + float(offset)
    materialized["max_distance"] = policy.max_distance + float(offset)
    if materialized["max_distance"] < materialized["target_distance"]:
        raise StealthSpanValidationError(
            "anchor_repricing_policy.max_distance must be greater than or equal "
            "to target_distance"
        )
    return materialized


def plan_stealth_order_span(
    raw: Mapping[str, Any],
    *,
    metadata_reader: Callable[[str], Mapping[str, Any]],
) -> StealthSpanPlan:
    """Validate and normalize a declarative span without mutating state."""

    if not isinstance(raw, Mapping):
        raise StealthSpanValidationError("span request must be an object")

    try:
        span_uuid = uuid.UUID(str(raw.get("span_id")))
    except (TypeError, ValueError, AttributeError) as exc:
        raise StealthSpanValidationError("span_id must be a UUID") from exc
    span_id = str(span_uuid)

    product_id = str(raw.get("product_id") or "").strip()
    if not product_id:
        raise StealthSpanValidationError("product_id is required")
    product_metadata = dict(metadata_reader(product_id) or {})
    try:
        side = OrderSide(str(raw.get("side") or "").upper())
    except ValueError as exc:
        raise StealthSpanValidationError("side must be BUY or SELL") from exc

    count = _positive_int(raw.get("order_count"), "order_count", maximum=_MAX_SPAN_ORDERS)
    creation_mode = _enum_value(
        StealthSpanCreationMode,
        raw.get("creation_mode"),
        "creation_mode",
    )
    distribution = _enum_value(
        StealthSpanSizeDistribution,
        raw.get("size_distribution"),
        "size_distribution",
    )
    start_price = _finite_decimal(raw.get("start_price"), "start_price")
    price_step = _finite_decimal(raw.get("price_step"), "price_step")
    total_size = _finite_decimal(raw.get("total_size"), "total_size")
    if start_price <= 0:
        raise StealthSpanValidationError("start_price must be greater than 0")
    if price_step < 0:
        raise StealthSpanValidationError("price_step must be zero or greater")
    if total_size <= 0:
        raise StealthSpanValidationError("total_size must be greater than 0")

    prices = []
    seen_prices = set()
    price_sign = Decimal(-1) if side == OrderSide.BUY else Decimal(1)
    for index in range(count):
        requested_price = start_price + price_sign * price_step * index
        result = normalize_price_for_product(
            requested_price,
            product_id=product_id,
            side=side,
            policy=PriceRoundingPolicy.SIDE_CONSERVATIVE,
            product_metadata=product_metadata,
        )
        if not result.ok or result.effective_price is None:
            raise StealthSpanValidationError(
                f"span order {index + 1} has an invalid price: {result.reason}"
            )
        effective_price = float(result.effective_price)
        price_key = Decimal(str(effective_price))
        if price_key in seen_prices:
            raise StealthSpanValidationError(
                "price_step produces duplicate effective span prices after "
                "product-increment normalization"
            )
        seen_prices.add(price_key)
        prices.append(effective_price)

    sizes, effective_total_size = _allocate_sizes(
        product_id=product_id,
        total_size=total_size,
        prices=prices,
        weights=_weights(count, distribution),
        product_metadata=product_metadata,
    )

    base_condition = _validate_reveal_condition(raw.get("reveal_condition"))
    try:
        reveal_pricing_policy = RevealPricingPolicy(
            str(raw.get("reveal_pricing_policy") or RevealPricingPolicy.CONFIGURED_LIMIT.value)
        )
    except ValueError as exc:
        raise StealthSpanValidationError(
            "reveal_pricing_policy must be configured_limit, top_of_book, or midpoint"
        ) from exc
    try:
        follow_up_direction = FollowUpRevealDirection(
            str(
                raw.get("follow_up_reveal_direction")
                or FollowUpRevealDirection.OPPOSITE.value
            )
        )
    except ValueError as exc:
        raise StealthSpanValidationError(
            "follow_up_reveal_direction must be same or opposite"
        ) from exc
    target_movement = _finite_decimal(
        raw.get("target_movement", 0),
        "target_movement",
    )
    if target_movement < 0:
        raise StealthSpanValidationError("target_movement must be zero or greater")
    target_movement_type = _enum_value(
        TargetMovementType,
        raw.get("target_movement_type", TargetMovementType.PERCENTAGE.value),
        "target_movement_type",
    )
    max_replacements = _nonnegative_int(
        raw.get("max_order_replacements", 0),
        "max_order_replacements",
    )
    sizing_strategy_raw = raw.get("sizing_strategy") or {"type": "fixed"}
    if not isinstance(sizing_strategy_raw, Mapping):
        raise StealthSpanValidationError("sizing_strategy must be an object")
    sizing_strategy = deepcopy(dict(sizing_strategy_raw))
    notes = str(raw.get("notes") or "").strip()
    root_id = str(uuid.uuid5(span_uuid, "rung:0"))
    orders = []

    for index, (price, size) in enumerate(zip(prices, sizes)):
        client_order_id = str(uuid.uuid5(span_uuid, f"rung:{index}"))
        parent_order_id = (
            root_id
            if creation_mode == StealthSpanCreationMode.PARENT_CHILDREN and index > 0
            else None
        )
        condition = deepcopy(base_condition)
        if (
            creation_mode == StealthSpanCreationMode.INDEPENDENT_PARENTS
            and condition["type"] == RevealConditionType.PRICE_THRESHOLD.value
        ):
            threshold_offset = Decimal(str(condition["price_threshold"])) - start_price
            condition["price_threshold"] = float(Decimal(str(price)) + threshold_offset)
            condition["direction"] = (
                Direction.BELOW.value
                if side == OrderSide.BUY
                else Direction.ABOVE.value
            )
            if condition["price_threshold"] <= 0:
                raise StealthSpanValidationError(
                    f"span order {index + 1} has a non-positive reveal price threshold"
                )

        movement_amount = (
            Decimal(str(price)) * target_movement
            if target_movement_type == TargetMovementType.PERCENTAGE
            else target_movement
        )
        follow_up_price = (
            Decimal(str(price)) - movement_amount
            if side == OrderSide.SELL
            else Decimal(str(price)) + movement_amount
        )
        if follow_up_price <= 0:
            raise StealthSpanValidationError(
                f"span order {index + 1} target_movement produces a non-positive follow-up price"
            )

        if creation_mode == StealthSpanCreationMode.INDEPENDENT_PARENTS:
            rung_notes = f"[SPAN #{index + 1}/{count}]"
        elif index == 0:
            rung_notes = f"[SPAN ROOT 1/{count}]"
        else:
            rung_notes = f"[SPAN CHILD {index + 1}/{count}]"
        if notes:
            rung_notes = f"{rung_notes} {notes}"

        orders.append(
            StealthSpanOrderSpec(
                index=index,
                client_order_id=client_order_id,
                product_id=product_id,
                side=side.value,
                total_size=size,
                limit_price=price,
                reveal_condition=condition,
                reveal_pricing_policy=reveal_pricing_policy.value,
                sizing_strategy=deepcopy(sizing_strategy),
                parent_order_id=parent_order_id,
                follow_up_reveal_direction=follow_up_direction.value,
                notes=rung_notes,
                max_order_replacements=max_replacements,
                target_movement=float(target_movement),
                target_movement_type=target_movement_type.value,
                allow_partial_fills=bool(raw.get("allow_partial_fills", False)),
                anchor_repricing_policy=_materialize_anchor_policy(
                    raw.get("anchor_repricing_policy"),
                    index=index,
                    price_step=price_step,
                    start_price=start_price,
                ),
                enable_hotpoint_replication=bool(
                    raw.get("enable_hotpoint_replication", False)
                ),
            )
        )

    return StealthSpanPlan(
        span_id=span_id,
        creation_mode=creation_mode,
        size_distribution=distribution,
        requested_total_size=float(total_size),
        effective_total_size=effective_total_size,
        orders=tuple(orders),
    )
