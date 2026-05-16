"""Cancel/re-entry policy evaluation.

The policy cancels a resting visible order when the market moves too close to
the order limit, then permits re-entry only after the market moves safely away.
It is intentionally pure: exchange cancellation and re-placement belong to the
lifecycle owner that calls this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from configuration import safe_float
from core.enums import (
    CancelReentryDecision,
    CancelReentryState,
    OrderSide,
    RepricingDistanceType,
    RepricingReferenceSource,
    StealthOrderStatus,
)


@dataclass(frozen=True)
class CancelReentryPolicy:
    """Normalized cancel/re-entry policy."""

    enabled: bool = False
    reference_price_source: RepricingReferenceSource = RepricingReferenceSource.MIDPOINT
    distance_type: RepricingDistanceType = RepricingDistanceType.ABSOLUTE
    cancel_distance: float = 0.0
    reentry_distance: float = 0.0
    cooldown_seconds: int = 0
    max_reentry_count: int = 0
    inherit_to_follow_ups: bool = True

    @classmethod
    def disabled(cls) -> "CancelReentryPolicy":
        return cls(enabled=False)

    @classmethod
    def from_dict(cls, raw: Optional[Dict[str, Any]]) -> "CancelReentryPolicy":
        config = dict(raw or {})
        if not bool(config.get("enabled")):
            return cls.disabled()

        ref_raw = str(
            config.get("reference_price_source")
            or config.get("reference_price")
            or RepricingReferenceSource.MIDPOINT.value
        ).strip().lower()
        if ref_raw == "mid":
            ref_raw = RepricingReferenceSource.MIDPOINT.value
        try:
            reference_price_source = RepricingReferenceSource(ref_raw)
        except ValueError:
            reference_price_source = RepricingReferenceSource.MIDPOINT

        dist_raw = str(
            config.get("distance_type") or RepricingDistanceType.ABSOLUTE.value
        ).strip().upper()
        try:
            distance_type = RepricingDistanceType(dist_raw)
        except ValueError:
            distance_type = RepricingDistanceType.ABSOLUTE

        cancel_distance = safe_float(config.get("cancel_distance"), default=0.0)
        reentry_distance = safe_float(config.get("reentry_distance"), default=0.0)
        if cancel_distance <= 0:
            raise ValueError("cancel_distance must be > 0")
        if reentry_distance <= cancel_distance:
            raise ValueError("reentry_distance must be greater than cancel_distance")

        cooldown_seconds = max(
            int(safe_float(config.get("cooldown_seconds"), default=0.0)),
            0,
        )
        max_reentry_count = max(
            int(safe_float(config.get("max_reentry_count"), default=0.0)),
            0,
        )

        return cls(
            enabled=True,
            reference_price_source=reference_price_source,
            distance_type=distance_type,
            cancel_distance=cancel_distance,
            reentry_distance=reentry_distance,
            cooldown_seconds=cooldown_seconds,
            max_reentry_count=max_reentry_count,
            inherit_to_follow_ups=bool(config.get("inherit_to_follow_ups", True)),
        )

    def to_dict(self) -> Dict[str, Any]:
        if not self.enabled:
            return {"enabled": False}
        return {
            "enabled": True,
            "reference_price_source": self.reference_price_source.value,
            "distance_type": self.distance_type.value,
            "cancel_distance": self.cancel_distance,
            "reentry_distance": self.reentry_distance,
            "cooldown_seconds": self.cooldown_seconds,
            "max_reentry_count": self.max_reentry_count,
            "inherit_to_follow_ups": self.inherit_to_follow_ups,
        }


@dataclass(frozen=True)
class CancelReentryRuntimeState:
    """Mutable state persisted beside the order."""

    state: CancelReentryState = CancelReentryState.RESTING
    last_cancel_at: Optional[str] = None
    last_reentry_at: Optional[str] = None
    reentry_count: int = 0
    cancelled_placement_client_order_id: Optional[str] = None
    cancelled_exchange_order_id: Optional[str] = None
    last_reason: Optional[str] = None

    @classmethod
    def from_dict(cls, raw: Optional[Dict[str, Any]]) -> "CancelReentryRuntimeState":
        state_dict = dict(raw or {})
        state_raw = str(
            state_dict.get("state") or CancelReentryState.RESTING.value
        ).strip().lower()
        try:
            state = CancelReentryState(state_raw)
        except ValueError:
            state = CancelReentryState.RESTING

        return cls(
            state=state,
            last_cancel_at=state_dict.get("last_cancel_at"),
            last_reentry_at=state_dict.get("last_reentry_at"),
            reentry_count=max(
                int(safe_float(state_dict.get("reentry_count"), default=0.0)),
                0,
            ),
            cancelled_placement_client_order_id=state_dict.get(
                "cancelled_placement_client_order_id"
            ),
            cancelled_exchange_order_id=state_dict.get("cancelled_exchange_order_id"),
            last_reason=state_dict.get("last_reason"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "last_cancel_at": self.last_cancel_at,
            "last_reentry_at": self.last_reentry_at,
            "reentry_count": self.reentry_count,
            "cancelled_placement_client_order_id": self.cancelled_placement_client_order_id,
            "cancelled_exchange_order_id": self.cancelled_exchange_order_id,
            "last_reason": self.last_reason,
        }


@dataclass(frozen=True)
class CancelReentryEvaluation:
    decision: CancelReentryDecision
    reason: str
    reference_price: Optional[float] = None
    distance: Optional[float] = None


def resolve_reference_price(
    side: str,
    market_data: Dict[str, Any],
    policy: CancelReentryPolicy,
) -> Optional[float]:
    """Resolve the policy reference price from ticker market data."""

    if policy.reference_price_source == RepricingReferenceSource.MIDPOINT:
        bid = safe_float(market_data.get("bid"), default=0.0)
        ask = safe_float(market_data.get("ask"), default=0.0)
        if bid > 0 and ask > 0:
            return (bid + ask) / 2.0
        return None

    if policy.reference_price_source == RepricingReferenceSource.TOP_OF_BOOK:
        normalized_side = str(side or "").upper()
        if normalized_side == OrderSide.BUY.value:
            return safe_float(market_data.get("bid"), default=None)
        return safe_float(market_data.get("ask"), default=None)

    return safe_float(market_data.get("price"), default=None)


def compute_distance(
    side: str,
    limit_price: float,
    reference_price: float,
    policy: CancelReentryPolicy,
) -> Optional[float]:
    """Compute distance between the order limit and market reference."""

    normalized_side = str(side or "").upper()
    if normalized_side == OrderSide.SELL.value:
        raw_distance = limit_price - reference_price
    elif normalized_side == OrderSide.BUY.value:
        raw_distance = reference_price - limit_price
    else:
        return None

    if policy.distance_type == RepricingDistanceType.PERCENT:
        if reference_price <= 0:
            return None
        return raw_distance / reference_price
    return raw_distance


def _cooldown_elapsed(
    state: CancelReentryRuntimeState,
    policy: CancelReentryPolicy,
    now: datetime,
) -> bool:
    if policy.cooldown_seconds <= 0 or not state.last_cancel_at:
        return True
    try:
        last_cancel = datetime.fromisoformat(str(state.last_cancel_at))
    except ValueError:
        return True
    return (now - last_cancel).total_seconds() >= policy.cooldown_seconds


def evaluate_cancel_reentry(
    order: Dict[str, Any],
    market_data: Dict[str, Any],
    policy: CancelReentryPolicy,
    state: CancelReentryRuntimeState,
    now: Optional[datetime] = None,
) -> CancelReentryEvaluation:
    """Return the next cancel/re-entry decision for an order."""

    if not policy.enabled:
        return CancelReentryEvaluation(CancelReentryDecision.HOLD, "policy_disabled")

    if safe_float(order.get("executed_size"), default=0.0) > 0:
        return CancelReentryEvaluation(CancelReentryDecision.HOLD, "order_has_fill")

    reference_price = resolve_reference_price(order.get("side"), market_data, policy)
    if reference_price is None or reference_price <= 0:
        return CancelReentryEvaluation(
            CancelReentryDecision.HOLD,
            "reference_price_unavailable",
        )

    limit_price = safe_float(order.get("limit_price"), default=0.0)
    if limit_price <= 0:
        return CancelReentryEvaluation(
            CancelReentryDecision.HOLD,
            "limit_price_unavailable",
            reference_price=reference_price,
        )

    distance = compute_distance(order.get("side"), limit_price, reference_price, policy)
    if distance is None:
        return CancelReentryEvaluation(
            CancelReentryDecision.HOLD,
            "side_unavailable",
            reference_price=reference_price,
        )

    status = str(order.get("status") or "").upper()
    if status == StealthOrderStatus.REVEALED.value:
        if distance <= policy.cancel_distance:
            return CancelReentryEvaluation(
                CancelReentryDecision.CANCEL,
                f"distance {distance:.8f} <= cancel_distance {policy.cancel_distance:.8f}",
                reference_price=reference_price,
                distance=distance,
            )
        return CancelReentryEvaluation(
            CancelReentryDecision.HOLD,
            f"distance {distance:.8f} > cancel_distance {policy.cancel_distance:.8f}",
            reference_price=reference_price,
            distance=distance,
        )

    if state.state == CancelReentryState.CANCELLED_BY_POLICY:
        if policy.max_reentry_count > 0 and state.reentry_count >= policy.max_reentry_count:
            return CancelReentryEvaluation(
                CancelReentryDecision.HOLD,
                "max_reentry_count_reached",
                reference_price=reference_price,
                distance=distance,
            )
        if not _cooldown_elapsed(state, policy, now or datetime.utcnow()):
            return CancelReentryEvaluation(
                CancelReentryDecision.HOLD,
                "cooldown_active",
                reference_price=reference_price,
                distance=distance,
            )
        if distance >= policy.reentry_distance:
            return CancelReentryEvaluation(
                CancelReentryDecision.REENTER,
                f"distance {distance:.8f} >= reentry_distance {policy.reentry_distance:.8f}",
                reference_price=reference_price,
                distance=distance,
            )
        return CancelReentryEvaluation(
            CancelReentryDecision.HOLD,
            f"distance {distance:.8f} < reentry_distance {policy.reentry_distance:.8f}",
            reference_price=reference_price,
            distance=distance,
        )

    return CancelReentryEvaluation(
        CancelReentryDecision.HOLD,
        "state_not_eligible",
        reference_price=reference_price,
        distance=distance,
    )
