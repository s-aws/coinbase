"""Shared product-type capability policy.

This module answers whether a product supports a trading action. It keeps spot
limitations explicit without introducing a spot-only order path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from core.enums import ProductCapability, ProductCapabilityMode, ProductType


_SPOT_DEFAULTS: Dict[ProductCapability, ProductCapabilityMode] = {
    ProductCapability.DIRECT_PLACEMENT: ProductCapabilityMode.ENABLED,
    ProductCapability.STEALTH_PLANNING: ProductCapabilityMode.ENABLED,
    ProductCapability.STEALTH_REVEAL: ProductCapabilityMode.ENABLED,
    ProductCapability.SIZE_VALIDATION: ProductCapabilityMode.ENABLED,
    ProductCapability.PROFITABILITY: ProductCapabilityMode.ENABLED,
    ProductCapability.FILLED_FOLLOW_UP: ProductCapabilityMode.CONDITIONAL,
    ProductCapability.PARTIAL_FILL_FOLLOW_UP: ProductCapabilityMode.CONDITIONAL,
    ProductCapability.CANCELLED_FOLLOW_UP: ProductCapabilityMode.CONDITIONAL,
    ProductCapability.SAME_SIDE_POST_FILL_RETREAT: ProductCapabilityMode.CONDITIONAL,
    ProductCapability.MOVE_REVEALED: ProductCapabilityMode.DISABLED,
    ProductCapability.REPRICE_REVEALED: ProductCapabilityMode.DISABLED,
    ProductCapability.CANCEL_REENTRY: ProductCapabilityMode.DISABLED,
    ProductCapability.HOTPOINT_AUTO_PLACEMENT: ProductCapabilityMode.DISABLED,
    ProductCapability.FUTURES_POSITION_FLIP: ProductCapabilityMode.NOT_APPLICABLE,
    ProductCapability.MARGIN_VALIDATION: ProductCapabilityMode.NOT_APPLICABLE,
    ProductCapability.LIQUIDATION_CHECK: ProductCapabilityMode.NOT_APPLICABLE,
    ProductCapability.FUNDING_CHECK: ProductCapabilityMode.NOT_APPLICABLE,
}

_FUTURE_DEFAULTS: Dict[ProductCapability, ProductCapabilityMode] = {
    capability: ProductCapabilityMode.ENABLED for capability in ProductCapability
}


@dataclass(frozen=True)
class ProductCapabilityDecision:
    """Result of evaluating one product capability."""

    allowed: bool
    product_id: str
    product_type: str
    capability: str
    mode: str
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "product_id": self.product_id,
            "product_type": self.product_type,
            "capability": self.capability,
            "mode": self.mode,
            "reason": self.reason,
        }


def get_product_capability_policy(
    override: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return optional product capability overrides.

    ``override`` is primarily for tests. Runtime config comes from
    ``configuration.PRODUCT_CAPABILITIES``.
    """
    if override is not None:
        return override if isinstance(override, dict) else {}
    try:
        from configuration import PRODUCT_CAPABILITIES
        policy = PRODUCT_CAPABILITIES
    except Exception:
        policy = {}
    return policy if isinstance(policy, dict) else {}


def coerce_product_capability(value: Any) -> ProductCapability:
    if isinstance(value, ProductCapability):
        return value
    return ProductCapability(str(value or ""))


def coerce_product_capability_mode(value: Any) -> ProductCapabilityMode:
    if isinstance(value, ProductCapabilityMode):
        return value
    raw = getattr(value, "value", value)
    return ProductCapabilityMode(str(raw or "").lower())


def resolve_product_context(product_id: str) -> Dict[str, Any]:
    """Resolve product id and canonical product type from existing config."""
    try:
        from configuration import (
            DERIVATIVES_PRODUCT_IDS,
            PRODUCT_METADATA,
            SPOT_PRODUCT_IDS,
            get_trading_product_id,
            normalize_product_type,
        )
        trading_product_id = get_trading_product_id(str(product_id or ""))
        configured_product_ids = {
            *map(str, DERIVATIVES_PRODUCT_IDS),
            *map(str, SPOT_PRODUCT_IDS),
            *map(str, PRODUCT_METADATA),
        }
        catalog_found = trading_product_id in configured_product_ids
        product_type = normalize_product_type(
            {"product_id": trading_product_id},
            products=PRODUCT_METADATA,
        )
    except Exception:
        trading_product_id = str(product_id or "")
        product_type = ProductType.SPOT.value
        catalog_found = False
    return {
        "product_id": trading_product_id,
        "requested_product_id": product_id,
        "product_type": product_type,
        "catalog_found": catalog_found,
    }


def _default_mode(product_type: str, capability: ProductCapability) -> ProductCapabilityMode:
    if product_type == ProductType.SPOT.value:
        return _SPOT_DEFAULTS.get(capability, ProductCapabilityMode.DISABLED)
    return _FUTURE_DEFAULTS.get(capability, ProductCapabilityMode.ENABLED)


def _lookup_override(
    policy: Dict[str, Any],
    *,
    product_id: str,
    product_type: str,
    capability: ProductCapability,
) -> Optional[ProductCapabilityMode]:
    """Find an override by product id, then product type."""
    capability_key = capability.value
    candidates = []
    product_overrides = policy.get("product_id") or {}
    if isinstance(product_overrides, dict):
        candidates.append(product_overrides.get(product_id))

    type_overrides = policy.get("product_type") or {}
    if isinstance(type_overrides, dict):
        candidates.append(type_overrides.get(product_type))

    # Back-compatible shorthand:
    # {"SPOT": {"move_revealed": "enabled"}}
    candidates.append(policy.get(product_type))

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        raw_mode = candidate.get(capability_key)
        if raw_mode is None:
            continue
        try:
            return coerce_product_capability_mode(raw_mode)
        except ValueError:
            continue
    return None


def evaluate_product_capability(
    *,
    product_id: str,
    capability: ProductCapability,
    allow_conditional: bool = False,
    policy: Optional[Dict[str, Any]] = None,
) -> ProductCapabilityDecision:
    """Evaluate whether a product supports an action capability."""
    capability_value = coerce_product_capability(capability)
    context = resolve_product_context(product_id)
    product_type = context["product_type"]
    canonical_product_id = context["product_id"]
    configured_policy = get_product_capability_policy(policy)
    mode = _lookup_override(
        configured_policy,
        product_id=canonical_product_id,
        product_type=product_type,
        capability=capability_value,
    ) or _default_mode(product_type, capability_value)

    allowed = mode == ProductCapabilityMode.ENABLED or (
        allow_conditional and mode == ProductCapabilityMode.CONDITIONAL
    )
    if allowed:
        reason = (
            f"{capability_value.value} is {mode.value} for "
            f"{product_type} product {canonical_product_id}"
        )
    else:
        reason = (
            f"{capability_value.value} is {mode.value} for "
            f"{product_type} product {canonical_product_id}"
        )

    return ProductCapabilityDecision(
        allowed=allowed,
        product_id=canonical_product_id,
        product_type=product_type,
        capability=capability_value.value,
        mode=mode.value,
        reason=reason,
    )


def product_capability_allows(
    *,
    product_id: str,
    capability: ProductCapability,
    allow_conditional: bool = False,
    policy: Optional[Dict[str, Any]] = None,
) -> bool:
    return evaluate_product_capability(
        product_id=product_id,
        capability=capability,
        allow_conditional=allow_conditional,
        policy=policy,
    ).allowed
