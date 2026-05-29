"""Cancel/re-entry policy evaluation.

The policy cancels a resting visible order when the market moves too close to
the order limit, then permits re-entry only after the market moves safely away.
It is intentionally pure: exchange cancellation and re-placement belong to the
lifecycle owner that calls this module.

This module implements the cancel/re-entry policy for no-fill revealed stealth
placements. It evaluates whether a cancel/re-entry action should be taken based
on market conditions and policy configuration.

The policy is designed to prevent orders from being too close to the market
price, which could result in immediate fills or unfavorable execution. It
ensures that after cancellation, the market moves sufficiently away before
re-entering.

Example:
    >>> from business.cancel_reentry_policy import CancelReentryPolicy, evaluate_cancel_reentry
    >>> policy = CancelReentryPolicy(
    ...     enabled=True,
    ...     cancel_distance=10.0,
    ...     reentry_distance=20.0,
    ...     cooldown_seconds=30
    ... )
    >>> order = {
    ...     'status': 'REVEALED',
    ...     'limit_price': 40000.0,
    ...     'side': 'BUY'
    ... }
    >>> market_data = {
    ...     'price': 39990.0,
    ...     'bid': 39985.0,
    ...     'ask': 39995.0
    ... }
    >>> state = CancelReentryRuntimeState(
    ...     state=CancelReentryState.RESTING
    ... )
    >>> result = evaluate_cancel_reentry(order, market_data, policy, state)
    >>> print(result.decision)
    CancelReentryDecision.CANCEL
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
    """Normalized cancel/re-entry policy.

    This policy governs when a revealed order should be cancelled and re-entered
    based on market conditions. It is specifically designed for no-fill revealed
    stealth placements.

    Attributes:
        enabled: Whether the cancel/re-entry policy is enabled.
        reference_price_source: Source of reference price for distance calculation.
        distance_type: How cancel_distance and reentry_distance are interpreted.
        cancel_distance: Distance from reference price at which to cancel.
        reentry_distance: Distance from reference price at which to re-enter.
        cooldown_seconds: Minimum time between cancel/re-entry actions.
        max_reentry_count: Maximum number of re-entries allowed.
        inherit_to_follow_ups: Whether this policy is inherited by follow-up orders.

    Example:
        >>> policy = CancelReentryPolicy(
        ...     enabled=True,
        ...     reference_price_source=RepricingReferenceSource.MIDPOINT,
        ...     distance_type=RepricingDistanceType.ABSOLUTE,
        ...     cancel_distance=10.0,
        ...     reentry_distance=20.0,
        ...     cooldown_seconds=30,
        ...     max_reentry_count=3,
        ...     inherit_to_follow_ups=True
        ... )
    """

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
        """Create a disabled cancel/re-entry policy.

        Returns:
            CancelReentryPolicy: A disabled policy instance.

        Example:
            >>> policy = CancelReentryPolicy.disabled()
            >>> print(policy.enabled)
            False
        """
        return cls(enabled=False)

    @classmethod
    def from_dict(cls, raw: Optional[Dict[str, Any]]) -> "CancelReentryPolicy":
        """Normalize a raw dict into a CancelReentryPolicy.

        This method handles type conversion, default values, and validation
        for creating a policy from a dictionary (typically from configuration).

        Args:
            raw: Raw policy configuration dictionary.

        Returns:
            CancelReentryPolicy: A normalized policy instance.

        Raises:
            ValueError: If cancel_distance is not > 0 or reentry_distance is not
                        greater than cancel_distance.

        Example:
            >>> policy_dict = {
            ...     'enabled': True,
            ...     'cancel_distance': 10.0,
            ...     'reentry_distance': 20.0
            ... }
            >>> policy = CancelReentryPolicy.from_dict(policy_dict)
        """
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
        """Convert policy to dictionary for persistence.

        Returns:
            Dict[str, Any]: Dictionary representation of the policy.

        Example:
            >>> policy = CancelReentryPolicy(enabled=True, cancel_distance=10.0)
            >>> policy_dict = policy.to_dict()
            >>> print(policy_dict['cancel_distance'])
        """
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
    """Mutable state persisted beside the order.

    This class tracks the runtime state of the cancel/re-entry policy for a specific order.
    It stores information about when the last cancel/re-entry occurred and the current state.

    Attributes:
        state: Current state of the cancel/re-entry policy (RESTING or CANCELLED_BY_POLICY).
        last_cancel_at: ISO timestamp of the last cancel operation.
        last_reentry_at: ISO timestamp of the last re-entry operation.
        reentry_count: Number of times the order has been re-entered.
        cancelled_placement_client_order_id: Client order ID of the cancelled placement.
        cancelled_exchange_order_id: Exchange order ID of the cancelled placement.
        last_reason: Reason for the last state change.

    Example:
        >>> state = CancelReentryRuntimeState(
        ...     state=CancelReentryState.CANCELLED_BY_POLICY,
        ...     last_cancel_at="2026-05-01T10:00:00Z",
        ...     reentry_count=1
        ... )
    """

    state: CancelReentryState = CancelReentryState.RESTING
    last_cancel_at: Optional[str] = None
    last_reentry_at: Optional[str] = None
    reentry_count: int = 0
    cancelled_placement_client_order_id: Optional[str] = None
    cancelled_exchange_order_id: Optional[str] = None
    last_reason: Optional[str] = None

    @classmethod
    def from_dict(cls, raw: Optional[Dict[str, Any]]) -> "CancelReentryRuntimeState":
        """Create CancelReentryRuntimeState from dictionary.

        Args:
            raw: Dictionary containing runtime state data.

        Returns:
            CancelReentryRuntimeState: A new instance populated from the dict.

        Example:
            >>> state_dict = {
            ...     'state': 'cancelled_by_policy',
            ...     'last_cancel_at': '2026-05-01T10:00:00Z',
            ...     'reentry_count': 1
            ... }
            >>> state = CancelReentryRuntimeState.from_dict(state_dict)
        """
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
        """Convert state to dictionary for persistence.

        Returns:
            Dict[str, Any]: Dictionary representation of the runtime state.

        Example:
            >>> state = CancelReentryRuntimeState(...)
            >>> state_dict = state.to_dict()
            >>> print(state_dict['state'])
        """
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
    """Result of cancel/re-entry policy evaluation.

    This class encapsulates the result of evaluating whether a cancel/re-entry
    action should be taken for an order.

    Attributes:
        decision: The decision (HOLD, CANCEL, or REENTER).
        reason: Human-readable reason for the decision.
        reference_price: Reference price used in the evaluation (optional).
        distance: Distance from reference price (optional).

    Example:
        >>> evaluation = CancelReentryEvaluation(
        ...     decision=CancelReentryDecision.CANCEL,
        ...     reason="distance 5.0 <= cancel_distance 10.0",
        ...     reference_price=40000.0,
        ...     distance=5.0
        ... )
    """
    decision: CancelReentryDecision
    reason: str
    reference_price: Optional[float] = None
    distance: Optional[float] = None


def resolve_reference_price(
    side: str,
    market_data: Dict[str, Any],
    policy: CancelReentryPolicy,
) -> Optional[float]:
    """Resolve the policy reference price from ticker market data.

    This function determines the reference price based on the policy's
    reference_price_source setting and the available market data.

    Args:
        side: Order side ('BUY' or 'SELL').
        market_data: Dictionary containing market data (bid, ask, price).
        policy: CancelReentryPolicy instance with reference price configuration.

    Returns:
        Optional[float]: The resolved reference price, or None if unavailable.

    Example:
        >>> policy = CancelReentryPolicy(reference_price_source=RepricingReferenceSource.MIDPOINT)
        >>> market_data = {'bid': 39995.0, 'ask': 40005.0, 'price': 40000.0}
        >>> price = resolve_reference_price('BUY', market_data, policy)
        >>> print(price)
        40000.0
    """

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
    """Compute distance between the order limit and market reference.

    Calculates the distance between the order's limit price and the reference
    price based on the policy's distance_type setting.

    Args:
        side: Order side ('BUY' or 'SELL').
        limit_price: The order's limit price.
        reference_price: The reference price for comparison.
        policy: CancelReentryPolicy instance with distance type configuration.

    Returns:
        Optional[float]: The computed distance, or None if calculation fails.

    Example:
        >>> policy = CancelReentryPolicy(distance_type=RepricingDistanceType.ABSOLUTE)
        >>> distance = compute_distance('BUY', 40000.0, 40010.0, policy)
        >>> print(distance)
        10.0
    """

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
    """Return the next cancel/re-entry decision for an order.

    This is the main evaluation function that determines whether a cancel/re-entry
    action should be taken based on the current market conditions, order state,
    and policy configuration.

    Args:
        order: Dictionary containing order information.
        market_data: Dictionary containing current market data.
        policy: CancelReentryPolicy instance with configuration.
        state: CancelReentryRuntimeState instance with current state.
        now: Current datetime for cooldown calculations (optional).

    Returns:
        CancelReentryEvaluation: The evaluation result with decision and reason.

    Example:
        >>> order = {'status': 'REVEALED', 'limit_price': 40000.0, 'side': 'BUY'}
        >>> market_data = {'bid': 39995.0, 'ask': 40005.0}
        >>> policy = CancelReentryPolicy(enabled=True, cancel_distance=10.0)
        >>> state = CancelReentryRuntimeState()
        >>> result = evaluate_cancel_reentry(order, market_data, policy, state)
        >>> print(result.decision)
        CancelReentryDecision.CANCEL
    """

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
