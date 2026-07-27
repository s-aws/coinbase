"""Pure fail-closed policy for one reviewed direct-parent move premark.

This module deliberately has no persistence or exchange dependency.  It
normalizes only allowlisted local order evidence and produces the immutable
terms that a separate durable coordinator may persist.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
import hashlib
import json
import re
from typing import Any, Mapping
import uuid

from application.admin_api.operator_mvp_policy import (
    OPERATOR_MVP_MAX_EXECUTED_NOTIONAL_TEXT,
    OPERATOR_MVP_MAX_EXECUTED_NOTIONAL_USDC,
    OPERATOR_MVP_MAX_SUBMITTED_NOTIONAL_TEXT,
    OPERATOR_MVP_MAX_SUBMITTED_NOTIONAL_USDC,
)
from core.enums import (
    OrderOwnershipProvenance,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)


GOAL_ID = "operator_parent_move_premark_lifecycle_v1"
POLICY_REVISION = "PARENT_MOVE_PREMARK_V1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PRODUCT_RE = re.compile(r"^[A-Z0-9]{1,32}(?:-[A-Z0-9]{1,32}){1,3}$")
_ACTIVE_SOURCE_STATUSES = frozenset(
    {
        OrderStatus.OPEN.value,
        OrderStatus.PENDING.value,
        OrderStatus.SUBMITTED.value,
        OrderStatus.QUEUED.value,
    }
)


class ParentMovePremarkPolicyError(ValueError):
    """A value-blind, fixed-code parent-move policy rejection."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ParentMovePremarkPolicyTerms:
    """Explicitly injected authority terms.

    Defaults are intentionally unusable.  Merely constructing the policy does
    not grant a product, portfolio, price increment, or live authority.
    """

    terms_complete: bool = False
    policy_revision: str | None = None
    portfolio_scope_sha256: str | None = None
    approved_product_id: str | None = None
    price_increment: str | None = None
    base_increment: str | None = None
    base_min_size: str | None = None
    quote_min_size: str | None = None
    max_submitted_notional_usdc: str = (
        OPERATOR_MVP_MAX_SUBMITTED_NOTIONAL_TEXT
    )
    max_possible_execution_notional_usdc: str = (
        OPERATOR_MVP_MAX_EXECUTED_NOTIONAL_TEXT
    )


@dataclass(frozen=True, slots=True)
class ParentMovePremarkPlan:
    """Immutable, sanitized parent-move plan persisted by the Goal 14 ledger."""

    goal_id: str
    policy_revision: str
    source_client_order_id: str
    reserved_successor_client_order_id: str
    portfolio_scope_sha256: str
    product_id: str
    side: str
    base_size: str
    source_limit_price: str
    requested_limit_price: str
    replacement_limit_price: str
    price_increment: str
    base_increment: str
    base_min_size: str
    quote_min_size: str
    source_status: str
    source_filled_size: str
    source_order_type: str
    source_time_in_force: str
    source_ownership_provenance: str
    post_only: bool
    submitted_notional: str
    possible_execution_notional: str
    submitted_notional_cap: str
    possible_execution_notional_cap: str
    zero_fill_proven: bool
    system_owned: bool
    source_evidence_sha256: str
    plan_sha256: str

    def to_persisted_payload(self) -> dict[str, Any]:
        """Return only the allowlisted immutable Goal 14 payload."""

        payload = asdict(self)
        payload.pop("plan_sha256")
        return payload

    @property
    def successor_client_order_id(self) -> str:
        return self.reserved_successor_client_order_id

    @property
    def size(self) -> str:
        return self.base_size

    @property
    def successor_limit_price(self) -> str:
        return self.replacement_limit_price

    @property
    def submitted_notional_usdc(self) -> str:
        return self.submitted_notional

    @property
    def possible_execution_notional_usdc(self) -> str:
        return self.possible_execution_notional


def _fail(code: str) -> None:
    raise ParentMovePremarkPolicyError(code)


def _canonical_uuid(value: Any, *, code: str) -> str:
    try:
        parsed = uuid.UUID(str(value or "").strip())
    except (AttributeError, TypeError, ValueError):
        _fail(code)
    canonical = str(parsed)
    if canonical != str(value or "").strip():
        _fail(code)
    return canonical


def _decimal(value: Any, *, code: str, allow_zero: bool = False) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        _fail(code)
    if not number.is_finite() or number < 0 or (not allow_zero and number == 0):
        _fail(code)
    return number


def _text(number: Decimal) -> str:
    rendered = format(number, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _hash_payload(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _validated_terms(
    terms: ParentMovePremarkPolicyTerms,
) -> tuple[str, str, Decimal, Decimal, Decimal, Decimal]:
    if (
        terms.terms_complete is not True
        or terms.policy_revision != POLICY_REVISION
        or not isinstance(terms.portfolio_scope_sha256, str)
        or _SHA256_RE.fullmatch(terms.portfolio_scope_sha256) is None
        or not isinstance(terms.approved_product_id, str)
        or _PRODUCT_RE.fullmatch(terms.approved_product_id) is None
        or not isinstance(terms.price_increment, str)
        or not isinstance(terms.base_increment, str)
        or not isinstance(terms.base_min_size, str)
        or not isinstance(terms.quote_min_size, str)
        or terms.max_submitted_notional_usdc
        != OPERATOR_MVP_MAX_SUBMITTED_NOTIONAL_TEXT
        or terms.max_possible_execution_notional_usdc
        != OPERATOR_MVP_MAX_EXECUTED_NOTIONAL_TEXT
    ):
        _fail("operator_parent_move_authority_terms_incomplete")
    increment = _decimal(
        terms.price_increment,
        code="operator_parent_move_authority_terms_incomplete",
    )
    base_increment = _decimal(
        terms.base_increment,
        code="operator_parent_move_authority_terms_incomplete",
    )
    base_min_size = _decimal(
        terms.base_min_size,
        code="operator_parent_move_authority_terms_incomplete",
    )
    quote_min_size = _decimal(
        terms.quote_min_size,
        code="operator_parent_move_authority_terms_incomplete",
    )
    return (
        terms.portfolio_scope_sha256,
        terms.approved_product_id,
        increment,
        base_increment,
        base_min_size,
        quote_min_size,
    )


def require_parent_move_premark_policy_terms(
    terms: ParentMovePremarkPolicyTerms,
) -> None:
    """Fail closed without requiring any order or repository read."""

    _validated_terms(terms)


def build_parent_move_premark_plan(
    *,
    source: Mapping[str, Any],
    requested_limit_price: str,
    reserved_successor_client_order_id: str,
    policy_terms: ParentMovePremarkPolicyTerms,
    legacy_pending_move: bool,
) -> ParentMovePremarkPlan:
    """Validate one direct root and freeze its one permitted successor.

    The authority terms are validated first.  This is intentional: an
    unconfigured deployment must fail without reading or classifying local
    orders and without reserving an actionable plan.
    """

    (
        portfolio_scope_sha256,
        approved_product_id,
        increment,
        base_increment,
        base_min_size,
        quote_min_size,
    ) = _validated_terms(policy_terms)
    source_id = _canonical_uuid(
        source.get("client_order_id"),
        code="operator_parent_move_source_identity_invalid",
    )
    successor_id = _canonical_uuid(
        reserved_successor_client_order_id,
        code="operator_parent_move_successor_identity_invalid",
    )
    if source_id == successor_id:
        _fail("operator_parent_move_successor_identity_invalid")
    parent_id = source.get("parent_order_id")
    if parent_id not in (None, ""):
        _fail("operator_parent_move_source_not_direct_root")
    provenance = str(source.get("ownership_provenance") or "").strip().upper()
    if provenance != OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value:
        _fail("operator_parent_move_source_not_system_owned")
    source_portfolio_hash = str(
        source.get("portfolio_scope_sha256") or ""
    ).strip()
    if source_portfolio_hash != portfolio_scope_sha256:
        _fail("operator_parent_move_source_portfolio_scope_mismatch")
    product_id = str(source.get("product_id") or "").strip().upper()
    if product_id != approved_product_id:
        _fail("operator_parent_move_source_product_not_approved")
    side = str(source.get("side") or "").strip().upper()
    if side not in {OrderSide.BUY.value, OrderSide.SELL.value}:
        _fail("operator_parent_move_source_configuration_invalid")
    filled_size = _decimal(
        source.get("filled_size"),
        code="operator_parent_move_source_not_zero_fill",
        allow_zero=True,
    )
    if filled_size != 0:
        _fail("operator_parent_move_source_not_zero_fill")
    if source.get("authoritatively_nonterminal") is not True:
        _fail(
            "operator_parent_move_source_not_authoritatively_nonterminal"
        )
    if source.get("cancel_eligible") is not True:
        _fail("operator_parent_move_source_not_cancel_eligible")
    status = str(source.get("status") or "").strip().upper()
    if status not in _ACTIVE_SOURCE_STATUSES:
        _fail("operator_parent_move_source_terminal")
    order_type = str(source.get("order_type") or "").strip().upper()
    time_in_force = str(source.get("time_in_force") or "").strip().upper()
    if (
        order_type != OrderType.LIMIT.value
        or time_in_force != TimeInForce.GOOD_UNTIL_CANCELLED.value
        or source.get("post_only_compatible") is not True
    ):
        _fail("operator_parent_move_source_configuration_invalid")
    if legacy_pending_move is True:
        _fail("operator_parent_move_legacy_pending")
    size = _decimal(
        source.get("size"),
        code="operator_parent_move_source_configuration_invalid",
    )
    if size < base_min_size or size % base_increment != 0:
        _fail("operator_parent_move_source_configuration_invalid")
    source_limit_price = _decimal(
        source.get("limit_price"),
        code="operator_parent_move_source_configuration_invalid",
    )
    requested = _decimal(
        requested_limit_price,
        code="operator_parent_move_requested_price_invalid",
    )
    rounding = ROUND_FLOOR if side == OrderSide.BUY.value else ROUND_CEILING
    quantized = (
        (requested / increment).to_integral_value(rounding=rounding)
        * increment
    )
    if quantized <= 0 or not quantized.is_finite():
        _fail("operator_parent_move_requested_price_invalid")
    notional = size * quantized
    if (
        notional <= 0
        or notional < quote_min_size
        or notional > OPERATOR_MVP_MAX_SUBMITTED_NOTIONAL_USDC
        or notional > OPERATOR_MVP_MAX_EXECUTED_NOTIONAL_USDC
    ):
        _fail("operator_parent_move_cap_exceeded")
    source_payload = {
        "client_order_id": source_id,
        "parent_order_id": None,
        "ownership_provenance": provenance,
        "portfolio_scope_sha256": portfolio_scope_sha256,
        "product_id": product_id,
        "side": side,
        "size": _text(size),
        "limit_price": _text(source_limit_price),
        "filled_size": _text(filled_size),
        "status": status,
        "order_type": order_type,
        "time_in_force": time_in_force,
        "authoritatively_nonterminal": True,
        "cancel_eligible": True,
        "post_only_compatible": True,
    }
    source_evidence_sha256 = _hash_payload(source_payload)
    plan_payload = {
        "goal_id": GOAL_ID,
        "policy_revision": POLICY_REVISION,
        "source_client_order_id": source_id,
        "reserved_successor_client_order_id": successor_id,
        "portfolio_scope_sha256": portfolio_scope_sha256,
        "product_id": product_id,
        "side": side,
        "base_size": _text(size),
        "source_limit_price": _text(source_limit_price),
        "requested_limit_price": _text(requested),
        "replacement_limit_price": _text(quantized),
        "price_increment": _text(increment),
        "base_increment": _text(base_increment),
        "base_min_size": _text(base_min_size),
        "quote_min_size": _text(quote_min_size),
        "source_status": status,
        "source_filled_size": _text(filled_size),
        "source_order_type": order_type,
        "source_time_in_force": time_in_force,
        "source_ownership_provenance": provenance,
        "post_only": True,
        "submitted_notional": _text(notional),
        "possible_execution_notional": _text(notional),
        "submitted_notional_cap": (
            OPERATOR_MVP_MAX_SUBMITTED_NOTIONAL_TEXT
        ),
        "possible_execution_notional_cap": (
            OPERATOR_MVP_MAX_EXECUTED_NOTIONAL_TEXT
        ),
        "zero_fill_proven": True,
        "system_owned": True,
        "source_evidence_sha256": source_evidence_sha256,
    }
    return ParentMovePremarkPlan(
        **plan_payload,
        plan_sha256=_hash_payload(plan_payload),
    )


__all__ = [
    "GOAL_ID",
    "POLICY_REVISION",
    "ParentMovePremarkPlan",
    "ParentMovePremarkPolicyError",
    "ParentMovePremarkPolicyTerms",
    "build_parent_move_premark_plan",
    "require_parent_move_premark_policy_terms",
]
