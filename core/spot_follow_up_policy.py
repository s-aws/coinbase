"""Spot follow-up intent classification and admission policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from core.enums import (
    OrderSide,
    ProductCapability,
    ProductType,
    SpotFollowUpIntent,
    SpotFollowUpTrigger,
)
from core.product_capability import evaluate_product_capability, resolve_product_context


_CAPABILITY_BY_TRIGGER = {
    SpotFollowUpTrigger.FILLED: ProductCapability.FILLED_FOLLOW_UP,
    SpotFollowUpTrigger.PARTIAL_FILL: ProductCapability.PARTIAL_FILL_FOLLOW_UP,
    SpotFollowUpTrigger.CANCELLED: ProductCapability.CANCELLED_FOLLOW_UP,
}

_DEFAULT_INTENT_ENABLED = {
    SpotFollowUpIntent.EXIT: True,
    SpotFollowUpIntent.REBUY: False,
    SpotFollowUpIntent.SAME_SIDE_REPLACEMENT: False,
    SpotFollowUpIntent.UNSUPPORTED: False,
}

_LEGACY_INTENT_KEYS = {
    SpotFollowUpIntent.EXIT: "allow_exit",
    SpotFollowUpIntent.REBUY: "allow_rebuy",
    SpotFollowUpIntent.SAME_SIDE_REPLACEMENT: "allow_same_side_replacement",
}


@dataclass(frozen=True)
class SpotFollowUpPolicyDecision:
    """Decision for a spot follow-up request."""

    allowed: bool
    product_id: str
    product_type: str
    source_side: str
    follow_up_side: str
    trigger: str
    intent: str
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "product_id": self.product_id,
            "product_type": self.product_type,
            "source_side": self.source_side,
            "follow_up_side": self.follow_up_side,
            "trigger": self.trigger,
            "intent": self.intent,
            "reason": self.reason,
        }


def get_spot_follow_up_policy(
    override: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return configured spot follow-up policy."""
    if override is not None:
        return override if isinstance(override, dict) else {}
    try:
        from configuration import SPOT_FOLLOW_UP_POLICY
        policy = SPOT_FOLLOW_UP_POLICY
    except Exception:
        policy = {}
    return policy if isinstance(policy, dict) else {}


def _coerce_side(side: Any) -> Optional[OrderSide]:
    if isinstance(side, OrderSide):
        return side
    try:
        return OrderSide(str(side or "").upper())
    except ValueError:
        return None


def _coerce_trigger(trigger: Any) -> SpotFollowUpTrigger:
    if isinstance(trigger, SpotFollowUpTrigger):
        return trigger
    raw = getattr(trigger, "value", trigger)
    try:
        return SpotFollowUpTrigger(str(raw or "").lower())
    except ValueError:
        return SpotFollowUpTrigger.FILLED


def classify_spot_follow_up_intent(
    *,
    source_side: Any,
    follow_up_side: Any,
) -> SpotFollowUpIntent:
    """Classify spot follow-up semantics from source and follow-up sides."""
    source = _coerce_side(source_side)
    follow_up = _coerce_side(follow_up_side)
    if source is None or follow_up is None:
        return SpotFollowUpIntent.UNSUPPORTED

    if source == follow_up:
        return SpotFollowUpIntent.SAME_SIDE_REPLACEMENT
    if source == OrderSide.BUY and follow_up == OrderSide.SELL:
        return SpotFollowUpIntent.EXIT
    if source == OrderSide.SELL and follow_up == OrderSide.BUY:
        return SpotFollowUpIntent.REBUY
    return SpotFollowUpIntent.UNSUPPORTED


def _merge_policy_for_product(
    policy: Dict[str, Any],
    *,
    product_id: str,
    product_type: str,
) -> Dict[str, Any]:
    merged = dict(policy or {})
    type_policy = (policy or {}).get("product_type") or {}
    if isinstance(type_policy, dict) and isinstance(type_policy.get(product_type), dict):
        merged.update(type_policy[product_type])
    product_policy = (policy or {}).get("product_id") or {}
    if isinstance(product_policy, dict) and isinstance(product_policy.get(product_id), dict):
        merged.update(product_policy[product_id])
    return merged


def _intent_enabled(
    policy: Dict[str, Any],
    intent: SpotFollowUpIntent,
) -> bool:
    default = _DEFAULT_INTENT_ENABLED[intent]
    legacy_key = _LEGACY_INTENT_KEYS.get(intent)
    if legacy_key and legacy_key in policy:
        return bool(policy.get(legacy_key))

    intents = policy.get("intents") or {}
    raw = intents.get(intent.value) if isinstance(intents, dict) else None
    if raw is None:
        return default
    if isinstance(raw, dict):
        return bool(raw.get("enabled", default))
    return bool(raw)


def evaluate_spot_follow_up_policy(
    *,
    product_id: str,
    source_side: Any,
    follow_up_side: Any,
    trigger: Any = SpotFollowUpTrigger.FILLED,
    policy: Optional[Dict[str, Any]] = None,
) -> SpotFollowUpPolicyDecision:
    """Evaluate whether a follow-up is admissible for spot semantics."""
    context = resolve_product_context(product_id)
    canonical_product_id = context["product_id"]
    product_type = context["product_type"]
    source = _coerce_side(source_side)
    follow_up = _coerce_side(follow_up_side)
    trigger_value = _coerce_trigger(trigger)

    source_value = source.value if source else str(source_side or "").upper()
    follow_up_value = follow_up.value if follow_up else str(follow_up_side or "").upper()
    intent = classify_spot_follow_up_intent(
        source_side=source,
        follow_up_side=follow_up,
    )

    if product_type != ProductType.SPOT.value:
        return SpotFollowUpPolicyDecision(
            allowed=True,
            product_id=canonical_product_id,
            product_type=product_type,
            source_side=source_value,
            follow_up_side=follow_up_value,
            trigger=trigger_value.value,
            intent=intent.value,
            reason=(
                f"spot follow-up policy does not apply to {product_type} "
                f"product {canonical_product_id}"
            ),
        )

    capability = evaluate_product_capability(
        product_id=canonical_product_id,
        capability=_CAPABILITY_BY_TRIGGER[trigger_value],
        allow_conditional=True,
    )
    if not capability.allowed:
        return SpotFollowUpPolicyDecision(
            allowed=False,
            product_id=canonical_product_id,
            product_type=product_type,
            source_side=source_value,
            follow_up_side=follow_up_value,
            trigger=trigger_value.value,
            intent=intent.value,
            reason=capability.reason,
        )

    configured_policy = _merge_policy_for_product(
        get_spot_follow_up_policy(policy),
        product_id=canonical_product_id,
        product_type=product_type,
    )
    if intent == SpotFollowUpIntent.UNSUPPORTED:
        allowed = False
    else:
        allowed = _intent_enabled(configured_policy, intent)

    if allowed:
        reason = (
            f"spot follow-up intent {intent.value} is enabled for "
            f"{canonical_product_id}"
        )
    else:
        reason = (
            f"spot follow-up intent {intent.value} is not enabled for "
            f"{canonical_product_id}"
        )

    return SpotFollowUpPolicyDecision(
        allowed=allowed,
        product_id=canonical_product_id,
        product_type=product_type,
        source_side=source_value,
        follow_up_side=follow_up_value,
        trigger=trigger_value.value,
        intent=intent.value,
        reason=reason,
    )
