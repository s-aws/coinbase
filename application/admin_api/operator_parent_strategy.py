"""Pure policy for operator-managed parent-strategy definitions.

This module deliberately has no exchange client dependency.  A parent strategy
is local configuration and does not itself reserve, preview, create, cancel, or
otherwise mutate a Coinbase order.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


_PRODUCT_ID = re.compile(r"^[A-Z0-9]{1,32}(?:-[A-Z0-9]{1,32}){1,3}$")
_SIDES = frozenset({"BUY", "SELL"})
_MOVEMENT_TYPES = frozenset({"P", "A"})
_CHILD_ORDER_TYPE = "LIMIT"
_CHILD_TIME_IN_FORCE = "GOOD_UNTIL_CANCELLED"


class OperatorParentStrategyError(ValueError):
    """Fixed-code failure safe for operator readback."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ParentStrategyTerms:
    product_id: str
    side: str
    reference_size: Decimal
    reference_price: Decimal
    target_movement: Decimal
    target_movement_type: str
    max_order_replacement: int
    allow_partial_fills: bool
    child_order_type: str
    child_time_in_force: str
    child_post_only: bool


@dataclass(frozen=True)
class ParentStrategyDeleteDecision:
    allowed: bool
    blockers: tuple[str, ...]


def _positive_decimal(value: Any, code: str) -> Decimal:
    if isinstance(value, bool):
        raise OperatorParentStrategyError(code)
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise OperatorParentStrategyError(code) from None
    if not normalized.is_finite() or normalized <= 0:
        raise OperatorParentStrategyError(code)
    return normalized.normalize()


def normalize_parent_strategy_terms(
    *,
    product_id: Any,
    side: Any,
    reference_size: Any,
    reference_price: Any,
    target_movement: Any,
    target_movement_type: Any,
    max_order_replacement: Any,
    allow_partial_fills: Any,
    child_order_type: Any,
    child_time_in_force: Any,
    child_post_only: Any,
) -> ParentStrategyTerms:
    """Validate the exact local parent/child policy allowlist."""

    normalized_product = str(product_id or "").strip()
    if _PRODUCT_ID.fullmatch(normalized_product) is None:
        raise OperatorParentStrategyError("parent_strategy_product_invalid")
    normalized_side = str(side or "").strip().upper()
    if normalized_side not in _SIDES:
        raise OperatorParentStrategyError("parent_strategy_side_invalid")
    normalized_movement_type = str(target_movement_type or "").strip().upper()
    if normalized_movement_type not in _MOVEMENT_TYPES:
        raise OperatorParentStrategyError(
            "parent_strategy_movement_type_invalid"
        )
    if (
        type(max_order_replacement) is not int
        or max_order_replacement < 0
        or max_order_replacement > 100
    ):
        raise OperatorParentStrategyError(
            "parent_strategy_replacement_limit_invalid"
        )
    if type(allow_partial_fills) is not bool:
        raise OperatorParentStrategyError(
            "parent_strategy_partial_fill_policy_invalid"
        )
    if (
        str(child_order_type or "").strip().upper() != _CHILD_ORDER_TYPE
        or str(child_time_in_force or "").strip().upper()
        != _CHILD_TIME_IN_FORCE
        or child_post_only is not True
    ):
        raise OperatorParentStrategyError(
            "parent_strategy_child_policy_invalid"
        )
    return ParentStrategyTerms(
        product_id=normalized_product,
        side=normalized_side,
        reference_size=_positive_decimal(
            reference_size,
            "parent_strategy_reference_size_invalid",
        ),
        reference_price=_positive_decimal(
            reference_price,
            "parent_strategy_reference_price_invalid",
        ),
        target_movement=_positive_decimal(
            target_movement,
            "parent_strategy_target_movement_invalid",
        ),
        target_movement_type=normalized_movement_type,
        max_order_replacement=max_order_replacement,
        allow_partial_fills=allow_partial_fills,
        child_order_type=_CHILD_ORDER_TYPE,
        child_time_in_force=_CHILD_TIME_IN_FORCE,
        child_post_only=True,
    )


def evaluate_parent_strategy_delete(
    *,
    lifecycle_state: str,
    unused_or_terminal: bool,
    active_placement_count: int,
    child_count: int,
    unresolved_claim_count: int,
    reconciliation_required: bool,
) -> ParentStrategyDeleteDecision:
    """Return fixed, value-blind blockers for one local tombstone command."""

    blockers: list[str] = []
    if lifecycle_state != "DEACTIVATED":
        blockers.append("parent_strategy_not_deactivated")
    if not unused_or_terminal:
        blockers.append("parent_strategy_parent_not_unused_or_terminal")
    if active_placement_count:
        blockers.append("parent_strategy_active_placement_present")
    if child_count:
        blockers.append("parent_strategy_child_present")
    if unresolved_claim_count:
        blockers.append("parent_strategy_unresolved_claim_present")
    if reconciliation_required:
        blockers.append("parent_strategy_reconciliation_required")
    return ParentStrategyDeleteDecision(
        allowed=not blockers,
        blockers=tuple(blockers),
    )
