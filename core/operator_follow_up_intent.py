"""Fail-closed activation boundary for operator follow-up intent support."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Callable, Mapping

from core.enums import (
    OrderOwnershipProvenance,
    OrderSide,
    OrderStatus,
    ProductType,
)


OPERATOR_FOLLOW_UP_INTENT_ENABLED_ENV = (
    "COINBASE_ADMIN_API_OPERATOR_FOLLOW_UP_INTENT_ENABLED"
)

_SYSTEM_OWNERSHIP = {
    OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value,
    OrderOwnershipProvenance.ADMIN_FILL_FOLLOW_UP.value,
}


@dataclass(frozen=True, slots=True)
class OperatorFollowUpIntentPolicyDecision:
    """Backend-domain decision derived from local authoritative evidence."""

    allowed: bool
    blockers: tuple[str, ...]
    product_type: str
    derived_follow_up_side: str | None
    semantic_intent: str | None


def operator_follow_up_intent_enabled(
    env: Mapping[str, str] | None = None,
) -> bool:
    """Return true only for the exact, explicit local-feature opt-in."""

    source = os.environ if env is None else env
    return source.get(OPERATOR_FOLLOW_UP_INTENT_ENABLED_ENV) == "1"


def evaluate_operator_follow_up_intent_policy(
    *,
    source_status: str,
    source_ownership_provenance: str,
    source_portfolio_matches: bool,
    root_lineage_valid: bool,
    product_id: str,
    source_side: str,
    product_context_resolver: Callable[[str], Mapping[str, Any]],
    spot_policy_evaluator: Callable[..., Any],
    spot_portfolio_configured: bool = True,
) -> OperatorFollowUpIntentPolicyDecision:
    """Evaluate non-persistence eligibility without trusting product fallbacks."""

    blockers: list[str] = []
    normalized_status = str(source_status or "UNKNOWN").upper()
    provenance = str(source_ownership_provenance or "UNKNOWN")
    normalized_side = str(source_side or "").upper()

    if normalized_status != OrderStatus.OPEN.value:
        blockers.append("source_status_not_open")
    if provenance not in _SYSTEM_OWNERSHIP:
        blockers.append("source_not_system_owned")
    if not spot_portfolio_configured:
        blockers.append("spot_portfolio_scope_unconfigured")
    elif not source_portfolio_matches:
        blockers.append("source_portfolio_scope_mismatch")
    if not root_lineage_valid:
        blockers.append("source_root_lineage_invalid")

    product_type = "UNKNOWN"
    catalog_found = False
    try:
        context = dict(product_context_resolver(str(product_id or "")))
        catalog_found = context.get("catalog_found") is True
        if catalog_found:
            product_type = str(context.get("product_type") or "UNKNOWN").upper()
    except Exception:
        catalog_found = False
    if not catalog_found:
        blockers.append("source_product_unknown")
    elif product_type != ProductType.SPOT.value:
        blockers.append("source_product_not_spot")

    follow_up_side: str | None = None
    if normalized_side == OrderSide.BUY.value:
        follow_up_side = OrderSide.SELL.value
    elif normalized_side == OrderSide.SELL.value:
        follow_up_side = OrderSide.BUY.value
    else:
        blockers.append("source_side_unsupported")

    semantic_intent: str | None = None
    if catalog_found and product_type == ProductType.SPOT.value and follow_up_side:
        try:
            policy = spot_policy_evaluator(
                product_id=product_id,
                source_side=normalized_side,
                follow_up_side=follow_up_side,
                trigger="filled",
            )
            raw_intent = getattr(policy, "intent", "")
            semantic_intent = str(getattr(raw_intent, "value", raw_intent) or "").upper()
            if getattr(policy, "allowed", False) is not True:
                blockers.append("source_follow_up_policy_not_allowed")
        except Exception:
            blockers.append("source_follow_up_policy_not_allowed")

    deduplicated = tuple(dict.fromkeys(blockers))
    return OperatorFollowUpIntentPolicyDecision(
        allowed=not deduplicated,
        blockers=deduplicated,
        product_type=product_type,
        derived_follow_up_side=follow_up_side,
        semantic_intent=semantic_intent,
    )


def operator_follow_up_intent_scope_applies(
    *,
    source_ownership_provenance: str,
    spot_portfolio_configured: bool,
    source_portfolio_matches: bool,
    product_id: str,
    product_context_resolver: Callable[[str], Mapping[str, Any]],
) -> bool:
    """Return whether an engine order belongs to the exact protected scope."""

    if str(source_ownership_provenance or "") not in _SYSTEM_OWNERSHIP:
        return False
    if not spot_portfolio_configured or not source_portfolio_matches:
        return False
    try:
        context = dict(product_context_resolver(str(product_id or "")))
    except Exception:
        return False
    return (
        context.get("catalog_found") is True
        and str(context.get("product_type") or "").upper()
        == ProductType.SPOT.value
    )
