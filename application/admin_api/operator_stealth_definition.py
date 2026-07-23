"""Pure policy for local operator-managed stealth definitions.

A definition is deliberately pre-runtime.  This module has no exchange,
runtime, bridge, or ``StealthOrderManager`` dependency.  Materialization into
the canonical stealth lifecycle is a separate operator action and authority.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal


_PRODUCT_ID = re.compile(r"^[A-Z0-9]{1,32}(?:-[A-Z0-9]{1,32}){1,3}$")
_SIDES = frozenset({"BUY", "SELL"})
_CONDITION_TYPES = frozenset({"PRICE", "TIME_DELAY"})
_DIRECTIONS = frozenset({"ABOVE", "BELOW"})
_PRICING_POLICIES = frozenset(
    {"CONFIGURED_LIMIT", "TOP_OF_BOOK", "MIDPOINT"}
)
_FOLLOW_UP_DIRECTIONS = frozenset({"SAME", "OPPOSITE"})
_MOVEMENT_TYPES = frozenset({"P", "A"})
_ACTIVE_RUNTIME_STATUSES = frozenset({"HIDDEN", "PENDING", "TRIGGERED"})
_TERMINAL_RUNTIME_STATUSES = frozenset({"EXECUTED", "CANCELLED"})


class OperatorStealthDefinitionError(ValueError):
    """Fixed-code failure safe for operator readback."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class StealthDefinitionTerms:
    name: str
    product_id: str
    side: str
    total_size: Decimal
    limit_price: Decimal
    reveal_condition_type: str
    reveal_price_threshold: Decimal | None
    reveal_direction: str | None
    hold_duration_seconds: int
    delay_seconds: int | None
    reveal_pricing_policy: str
    sizing_mode: Literal["FIXED"]
    follow_up_reveal_direction: str
    target_movement: Decimal
    target_movement_type: str
    max_order_replacements: int
    allow_partial_fills: bool
    post_only: Literal[True]


@dataclass(frozen=True)
class StealthDefinitionRuntimeDecision:
    classification: Literal[
        "UNMATERIALIZED", "ACTIVE", "REVEALED", "TERMINAL", "UNKNOWN"
    ]
    local_mutation_allowed: bool
    blocked_navigation: (
        Literal["REVEAL_CLOSEOUT", "MOVEMENT_REPRICING"] | None
    )


def _positive_decimal(value: Any, code: str) -> Decimal:
    if isinstance(value, bool):
        raise OperatorStealthDefinitionError(code)
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise OperatorStealthDefinitionError(code) from None
    if not normalized.is_finite() or normalized <= 0:
        raise OperatorStealthDefinitionError(code)
    return normalized.normalize()


def _bounded_int(
    value: Any,
    *,
    minimum: int,
    maximum: int,
    code: str,
) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise OperatorStealthDefinitionError(code)
    return value


def normalize_stealth_definition_terms(
    *,
    name: Any,
    product_id: Any,
    side: Any,
    total_size: Any,
    limit_price: Any,
    reveal_condition_type: Any,
    reveal_price_threshold: Any,
    reveal_direction: Any,
    hold_duration_seconds: Any,
    delay_seconds: Any,
    reveal_pricing_policy: Any,
    sizing_mode: Any,
    follow_up_reveal_direction: Any,
    target_movement: Any,
    target_movement_type: Any,
    max_order_replacements: Any,
    allow_partial_fills: Any,
    post_only: Any,
) -> StealthDefinitionTerms:
    """Validate and normalize the local v1 definition allowlist."""

    normalized_name = str(name or "").strip()
    if not 1 <= len(normalized_name) <= 80:
        raise OperatorStealthDefinitionError(
            "stealth_definition_name_invalid"
        )
    normalized_product = str(product_id or "").strip()
    if _PRODUCT_ID.fullmatch(normalized_product) is None:
        raise OperatorStealthDefinitionError(
            "stealth_definition_product_invalid"
        )
    normalized_side = str(side or "").strip().upper()
    if normalized_side not in _SIDES:
        raise OperatorStealthDefinitionError(
            "stealth_definition_side_invalid"
        )
    normalized_condition = str(reveal_condition_type or "").strip().upper()
    if normalized_condition not in _CONDITION_TYPES:
        raise OperatorStealthDefinitionError(
            "stealth_definition_reveal_condition_invalid"
        )
    hold_seconds = _bounded_int(
        hold_duration_seconds,
        minimum=0,
        maximum=86_400,
        code="stealth_definition_hold_duration_invalid",
    )
    threshold: Decimal | None = None
    direction: str | None = None
    normalized_delay: int | None = None
    if normalized_condition == "PRICE":
        if delay_seconds is not None:
            raise OperatorStealthDefinitionError(
                "stealth_definition_price_condition_invalid"
            )
        threshold = _positive_decimal(
            reveal_price_threshold,
            "stealth_definition_price_condition_invalid",
        )
        direction = str(reveal_direction or "").strip().upper()
        if direction not in _DIRECTIONS:
            raise OperatorStealthDefinitionError(
                "stealth_definition_price_condition_invalid"
            )
    else:
        if reveal_price_threshold is not None or reveal_direction is not None:
            raise OperatorStealthDefinitionError(
                "stealth_definition_time_condition_invalid"
            )
        normalized_delay = _bounded_int(
            delay_seconds,
            minimum=0,
            maximum=604_800,
            code="stealth_definition_time_condition_invalid",
        )
        if hold_seconds != 0:
            raise OperatorStealthDefinitionError(
                "stealth_definition_time_condition_invalid"
            )
    pricing_policy = str(reveal_pricing_policy or "").strip().upper()
    if pricing_policy not in _PRICING_POLICIES:
        raise OperatorStealthDefinitionError(
            "stealth_definition_pricing_policy_invalid"
        )
    if str(sizing_mode or "").strip().upper() != "FIXED":
        raise OperatorStealthDefinitionError(
            "stealth_definition_sizing_mode_invalid"
        )
    follow_up_direction = str(
        follow_up_reveal_direction or ""
    ).strip().upper()
    if follow_up_direction not in _FOLLOW_UP_DIRECTIONS:
        raise OperatorStealthDefinitionError(
            "stealth_definition_follow_up_direction_invalid"
        )
    movement_type = str(target_movement_type or "").strip().upper()
    if movement_type not in _MOVEMENT_TYPES:
        raise OperatorStealthDefinitionError(
            "stealth_definition_movement_type_invalid"
        )
    replacements = _bounded_int(
        max_order_replacements,
        minimum=0,
        maximum=100,
        code="stealth_definition_replacement_limit_invalid",
    )
    if type(allow_partial_fills) is not bool:
        raise OperatorStealthDefinitionError(
            "stealth_definition_partial_fill_policy_invalid"
        )
    if post_only is not True:
        raise OperatorStealthDefinitionError(
            "stealth_definition_post_only_required"
        )
    return StealthDefinitionTerms(
        name=normalized_name,
        product_id=normalized_product,
        side=normalized_side,
        total_size=_positive_decimal(
            total_size,
            "stealth_definition_total_size_invalid",
        ),
        limit_price=_positive_decimal(
            limit_price,
            "stealth_definition_limit_price_invalid",
        ),
        reveal_condition_type=normalized_condition,
        reveal_price_threshold=threshold,
        reveal_direction=direction,
        hold_duration_seconds=hold_seconds,
        delay_seconds=normalized_delay,
        reveal_pricing_policy=pricing_policy,
        sizing_mode="FIXED",
        follow_up_reveal_direction=follow_up_direction,
        target_movement=_positive_decimal(
            target_movement,
            "stealth_definition_target_movement_invalid",
        ),
        target_movement_type=movement_type,
        max_order_replacements=replacements,
        allow_partial_fills=allow_partial_fills,
        post_only=True,
    )


def classify_stealth_definition_runtime(
    runtime_status: str | None,
) -> StealthDefinitionRuntimeDecision:
    """Classify canonical runtime presence without inferring exchange truth."""

    if runtime_status is None:
        return StealthDefinitionRuntimeDecision(
            classification="UNMATERIALIZED",
            local_mutation_allowed=True,
            blocked_navigation=None,
        )
    normalized = str(runtime_status).strip().upper()
    if normalized in _ACTIVE_RUNTIME_STATUSES:
        classification = "ACTIVE"
        navigation = "REVEAL_CLOSEOUT"
    elif normalized == "REVEALED":
        classification = "REVEALED"
        navigation = "MOVEMENT_REPRICING"
    elif normalized in _TERMINAL_RUNTIME_STATUSES:
        classification = "TERMINAL"
        navigation = "REVEAL_CLOSEOUT"
    else:
        classification = "UNKNOWN"
        navigation = "REVEAL_CLOSEOUT"
    return StealthDefinitionRuntimeDecision(
        classification=classification,
        local_mutation_allowed=False,
        blocked_navigation=navigation,
    )
