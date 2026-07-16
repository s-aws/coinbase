"""Dormant Slice 3 Futures terminal-roundtrip safety primitives.

This module is backend-only preparation.  It registers no route, imports no
Coinbase client, constructs no live adapter, and performs no read or mutation
on its own.  A later, separately audited runner may inject the narrow
``Slice3MutationPort`` only after an exact sealed plan has been approved.

The design deliberately does not restore the legacy direct execution paths
inspected side-by-side in ``origin/prod``:

* ``dashboard_server.py:610-770`` accepted browser create/cancel parameters and
  logged exchange results.
* ``external/coinbase_client.py:193-305,501-524,579-621`` exposed broad create,
  cancel, and position wrappers without Preview binding.
* ``core/order_engine.py:2396-2963,3809+`` mixed exchange events with local
  lifecycle mutation and automatic follow-up behavior.

Slice 3 instead uses one fixed plan, finite read slots, a pure branch decision,
and owner-only action claims.  Create, conditional Cancel, and exact-delta
Close are all reserved before an injected port can be constructed.  Each
exchange boundary is fsynced before its one allowed call.  An exception after
that boundary becomes a sanitized, consumed unknown outcome and is never
retried by this module.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from threading import RLock
from typing import Any, Protocol
from uuid import UUID

from core.enums import (
    AdminFuturesPositionSide,
    OrderSide,
    OrderStatus,
    TimeInForce,
)


SLICE3_PRODUCT_ID = "AVP-20DEC30-CDE"
SLICE3_CONTRACT_SIZE = Decimal("10")
SLICE3_MAX_PREVIEW_TTL = timedelta(minutes=120)
SLICE3_MAX_RISK_OFF_TTL = timedelta(minutes=15)
SLICE3_MAX_READ_AGE = timedelta(seconds=30)
SLICE3_OPENING_CAP_USDC = Decimal("100")
SLICE3_EXPOSURE_CAP_USDC = Decimal("150")
SLICE3_TURNOVER_CAP_USDC = Decimal("300")
SLICE3_CLOSE_BUFFER = Decimal("1.20")
SLICE3_ACTOR_ID = "operator-controlled-futures-proof"
SLICE3_ROLES = ("trader",)
SLICE3_ROUTE = "backend_tool_only_no_http_route"
SLICE3_METHOD = "CLI"
SLICE3_SERVICE_METHOD = "Slice3TerminalRoundtripOrchestrator.run"
SLICE3_PERMISSION = "operator_explicit_attachment_authority"
SLICE3_MAX_CLAIM_FILE_BYTES = 1_048_576
SLICE3_ACTION_RECORD_SCHEMA_VERSION = "slice3-action-claim-record-v4"
SLICE3_ACTION_GENESIS_SHA256 = "0" * 64

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SAFE_REASON_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]{0,127}$")


class Slice3PolicyError(ValueError):
    """Raised when Slice 3 policy evidence is outside the exact allowlist."""


class Slice3PlanError(ValueError):
    """Raised when an immutable Slice 3 plan binding is invalid."""


class Slice3ClaimError(RuntimeError):
    """Raised when a durable Slice 3 action claim is unsafe or consumed."""


class Slice3MutationBlocked(RuntimeError):
    """Raised before client construction when a Slice 3 action is blocked."""


def _canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise Slice3PlanError("slice3_canonical_json_invalid") from exc


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _private_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _require_sha256(value: str, reason: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise Slice3PlanError(reason)
    return value


def _require_safe_reason(value: str) -> str:
    if not isinstance(value, str) or _SAFE_REASON_PATTERN.fullmatch(value) is None:
        raise Slice3PlanError("slice3_reason_code_invalid")
    return value


def _require_aware(value: datetime, reason: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise Slice3PlanError(reason)
    return value.astimezone(timezone.utc)


def _require_fresh(
    observed_at: datetime,
    *,
    now: datetime,
    stale_reason: str,
) -> None:
    observed = _require_aware(observed_at, f"{stale_reason}_timestamp_invalid")
    current = _require_aware(now, "slice3_now_invalid")
    age = current - observed
    if age < timedelta(0) or age > SLICE3_MAX_READ_AGE:
        raise Slice3PlanError(stale_reason)


def _decimal(value: Decimal | str | int, reason: str) -> Decimal:
    if isinstance(value, bool):
        raise Slice3PlanError(reason)
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise Slice3PlanError(reason) from exc
    if not normalized.is_finite():
        raise Slice3PlanError(reason)
    return normalized


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    text = format(normalized, "f")
    return "0" if text in {"-0", ""} else text


def _require_uuid(value: str, reason: str) -> str:
    try:
        parsed = UUID(value)
    except (TypeError, ValueError, AttributeError) as exc:
        raise Slice3PlanError(reason) from exc
    if str(parsed) != value.lower():
        raise Slice3PlanError(reason)
    return value


def _require_uuid4(value: str, reason: str) -> str:
    normalized = _require_uuid(value, reason)
    if UUID(normalized).version != 4:
        raise Slice3PlanError(reason)
    return normalized


def _require_private_identifier(value: str, reason: str) -> str:
    if not (
        isinstance(value, str)
        and value == value.strip()
        and value.isprintable()
        and 0 < len(value) <= 256
    ):
        raise Slice3PlanError(reason)
    return value


class Slice3ActionKind(str, Enum):
    """The only exchange mutation classes sealed by Slice 3."""

    CREATE = "create"
    CANCEL = "cancel"
    CLOSE = "close"


class Slice3MutationOutcome(str, Enum):
    """Sanitized terminal classification for one exchange boundary."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class Slice3DirectiveKind(str, Enum):
    """Pure state-machine directives; only three values permit mutation."""

    CANCEL_OPEN = "cancel_open"
    CANCEL_RESIDUAL = "cancel_residual"
    CLOSE_EXACT_DELTA = "close_exact_delta"
    READ_ONLY_RECONCILE = "read_only_reconcile"
    COMPLETE_REJECTED = "complete_rejected"
    COMPLETE_FLAT = "complete_flat"
    HALT_SAFETY = "halt_safety"


class Slice3OrderResolutionSource(str, Enum):
    """Finite authoritative source used to resolve the opening order."""

    AUTHORITATIVE_ORDER_READ = "authoritative_order_read"
    EXACT_CLIENT_ORDER_ID_LOOKUP = "exact_client_order_id_lookup"


class Slice3ReadSlot(str, Enum):
    """Sealed at-most-once reads; there is no polling or pagination loop."""

    PRE_CREATE_OPEN_ORDERS = "pre_create_open_orders"
    PRE_CREATE_POSITION = "pre_create_position"
    PRE_CREATE_MARGIN = "pre_create_margin"
    POST_CREATE_ORDER = "post_create_order_or_exact_client_lookup"
    POST_CREATE_POSITION = "post_create_position"
    POST_CANCEL_TERMINAL_ORDER = "post_cancel_terminal_order"
    PRE_CLOSE_POSITION = "pre_close_position"
    PRE_CLOSE_MARKET = "pre_close_market"
    PRE_CLOSE_OPEN_ORDERS = "pre_close_open_orders"
    POST_CLOSE_ORDER = "post_close_order"
    FINAL_POSITION = "final_position"
    FINAL_OPEN_ORDERS = "final_open_orders"
    FINAL_MARGIN = "final_margin"
    RECOVERY_OPENING_ORDER_BY_CLIENT_ID = "recovery_opening_order_by_client_id"
    RECOVERY_POSITION = "recovery_position"
    RECOVERY_POST_CANCEL_TERMINAL_ORDER = "recovery_post_cancel_terminal_order"
    RECOVERY_POST_CANCEL_POSITION = "recovery_post_cancel_position"
    RECOVERY_MARKET = "recovery_market"
    RECOVERY_PRE_CLOSE_OPEN_ORDERS = "recovery_pre_close_open_orders"
    RECOVERY_CLOSE_ORDER_BY_CLIENT_ID = "recovery_close_order_by_client_id"
    RECOVERY_FINAL_POSITION = "recovery_final_position"
    RECOVERY_FINAL_OPEN_ORDERS = "recovery_final_open_orders"
    RECOVERY_FINAL_MARGIN = "recovery_final_margin"


class Slice3ClaimEvent(str, Enum):
    """Append-only durable action-claim events."""

    CLAIM = "claim"
    EVIDENCE_BOUND = "evidence_bound"
    EXCHANGE_BOUNDARY = "exchange_boundary"
    OUTCOME = "outcome"
    RETIRED = "retired_not_required"


class Slice3ClaimDecision(str, Enum):
    """Result of atomically reserving an action semantic key."""

    CLAIMED = "claimed"
    EXISTS = "exists"


@dataclass(frozen=True)
class Slice3MarginWindowEvidence:
    """Exact operator-defined profile/state pair carried into Slice 3."""

    retail_regular: str
    retail_intraday_margin_1: str
    intraday_margin_setting: str = "INTRADAY_MARGIN_SETTING_STANDARD"
    intraday_margin_killswitch_enabled: bool = False
    intraday_margin_enrollment_killswitch_enabled: bool = False

    def sanitized_evidence(self) -> dict[str, str]:
        return {
            "retail_regular": self.retail_regular,
            "retail_intraday_margin_1": self.retail_intraday_margin_1,
            "intraday_margin_setting": self.intraday_margin_setting,
            "intraday_margin_killswitch_enabled": (
                self.intraday_margin_killswitch_enabled
            ),
            "intraday_margin_enrollment_killswitch_enabled": (
                self.intraday_margin_enrollment_killswitch_enabled
            ),
        }


@dataclass(frozen=True)
class Slice3Policy:
    """Separately versioned Slice 3 policy; it does not reinterpret V3."""

    schema_version: str = "slice3-terminal-roundtrip-policy-v1"
    authority: str = "operator_defined_slice_3_only_not_coinbase_documented"
    expected_retail_regular: str = "MARGIN_WINDOW_TYPE_UNSPECIFIED"
    expected_retail_intraday_margin_1: str = "MARGIN_WINDOW_TYPE_INTRADAY"
    live_adapter_bound: bool = False
    route_registered: bool = False

    def validate_margin_windows(
        self,
        evidence: Slice3MarginWindowEvidence,
    ) -> None:
        if not isinstance(evidence, Slice3MarginWindowEvidence) or (
            evidence.retail_regular != self.expected_retail_regular
            or evidence.retail_intraday_margin_1
            != self.expected_retail_intraday_margin_1
            or evidence.intraday_margin_setting
            not in {
                "INTRADAY_MARGIN_SETTING_STANDARD",
                "INTRADAY_MARGIN_SETTING_INTRADAY",
            }
            or evidence.intraday_margin_killswitch_enabled is not False
            or evidence.intraday_margin_enrollment_killswitch_enabled is not False
        ):
            raise Slice3PolicyError("slice3_margin_window_pair_invalid")

    def sanitized_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "authority": self.authority,
            "expected_margin_windows": {
                "retail_regular": self.expected_retail_regular,
                "retail_intraday_margin_1": (self.expected_retail_intraday_margin_1),
            },
            "live_adapter_bound": self.live_adapter_bound,
            "route_registered": self.route_registered,
            "attempt_limits": {
                "create": 1,
                "cancel": 1,
                "close": 1,
                "retry": 0,
                "fallback": 0,
                "redirect": 0,
            },
            "read_limits": {slot.value: 1 for slot in Slice3ReadSlot},
            "polling_allowed": False,
            "pagination_allowed": False,
        }


SLICE3_POLICY = Slice3Policy()
SLICE3_LIVE_POLICY = Slice3Policy(live_adapter_bound=True)


@dataclass(frozen=True)
class Slice3ExecutionAuthority:
    """Exact operator, trace, control, and evidence bindings for Slice 3."""

    actor_id: str
    roles: tuple[str, ...]
    correlation_id: str = field(repr=False)
    preview_idempotency_key: str = field(repr=False)
    authorization_sha256: str
    route: str
    method: str
    service_method: str
    permission: str
    approval_evidence_sha256: str
    admission_evidence_sha256: str
    cap_guard_evidence_sha256: str
    reconciliation_evidence_sha256: str
    live_service_evidence_sha256: str
    adapter_evidence_sha256: str
    product_evidence_sha256: str
    market_evidence_sha256: str
    margin_collateral_evidence_sha256: str
    liquidation_evidence_sha256: str
    fee_funding_evidence_sha256: str
    observed_at: datetime
    schema_version: str = "slice3-execution-authority-v1"

    def validate(self, *, now: datetime) -> None:
        if self.actor_id != SLICE3_ACTOR_ID:
            raise Slice3PlanError("slice3_execution_authority_actor_invalid")
        if self.roles != SLICE3_ROLES:
            raise Slice3PlanError("slice3_execution_authority_roles_invalid")
        _require_uuid4(
            self.correlation_id,
            "slice3_execution_authority_correlation_id_invalid",
        )
        _require_uuid4(
            self.preview_idempotency_key,
            "slice3_execution_authority_preview_idempotency_key_invalid",
        )
        if self.correlation_id == self.preview_idempotency_key:
            raise Slice3PlanError("slice3_execution_authority_identifier_collision")
        exact_controls = {
            "route": (self.route, SLICE3_ROUTE),
            "method": (self.method, SLICE3_METHOD),
            "service_method": (self.service_method, SLICE3_SERVICE_METHOD),
            "permission": (self.permission, SLICE3_PERMISSION),
        }
        for field_name, (value, expected) in exact_controls.items():
            if value != expected:
                raise Slice3PlanError(
                    f"slice3_execution_authority_{field_name}_invalid"
                )
        hashes = {
            "authorization_sha256": self.authorization_sha256,
            "approval_evidence_sha256": self.approval_evidence_sha256,
            "admission_evidence_sha256": self.admission_evidence_sha256,
            "cap_guard_evidence_sha256": self.cap_guard_evidence_sha256,
            "reconciliation_evidence_sha256": (self.reconciliation_evidence_sha256),
            "live_service_evidence_sha256": (self.live_service_evidence_sha256),
            "adapter_evidence_sha256": self.adapter_evidence_sha256,
            "product_evidence_sha256": self.product_evidence_sha256,
            "market_evidence_sha256": self.market_evidence_sha256,
            "margin_collateral_evidence_sha256": (
                self.margin_collateral_evidence_sha256
            ),
            "liquidation_evidence_sha256": (self.liquidation_evidence_sha256),
            "fee_funding_evidence_sha256": self.fee_funding_evidence_sha256,
        }
        for field_name, value in hashes.items():
            _require_sha256(
                value,
                f"slice3_execution_authority_{field_name}_invalid",
            )
        _require_fresh(
            self.observed_at,
            now=now,
            stale_reason="slice3_execution_authority_stale",
        )

    def sanitized_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "actor_id": self.actor_id,
            "roles": list(self.roles),
            "correlation_id_sha256": _private_sha256(self.correlation_id),
            "preview_idempotency_key_sha256": _private_sha256(
                self.preview_idempotency_key
            ),
            "authorization_sha256": self.authorization_sha256,
            "route": self.route,
            "method": self.method,
            "service_method": self.service_method,
            "permission": self.permission,
            "approval_evidence_sha256": self.approval_evidence_sha256,
            "admission_evidence_sha256": self.admission_evidence_sha256,
            "cap_guard_evidence_sha256": self.cap_guard_evidence_sha256,
            "reconciliation_evidence_sha256": (self.reconciliation_evidence_sha256),
            "live_service_evidence_sha256": (self.live_service_evidence_sha256),
            "adapter_evidence_sha256": self.adapter_evidence_sha256,
            "product_evidence_sha256": self.product_evidence_sha256,
            "market_evidence_sha256": self.market_evidence_sha256,
            "margin_collateral_evidence_sha256": (
                self.margin_collateral_evidence_sha256
            ),
            "liquidation_evidence_sha256": (self.liquidation_evidence_sha256),
            "fee_funding_evidence_sha256": self.fee_funding_evidence_sha256,
            "observed_at": self.observed_at.astimezone(timezone.utc).isoformat(),
        }


@dataclass(frozen=True)
class Slice3PortfolioBinding:
    """Permission-selected Default US CFM portfolio evidence."""

    portfolio_id: str = field(repr=False)
    portfolio_name: str
    portfolio_type: str
    can_view: bool
    can_trade: bool
    product_family: str
    intx_excluded: bool
    request_override_allowed: bool
    read_authorized: bool
    exact_match_count: int
    selection_authority: str
    observed_at: datetime
    permission_evidence_sha256: str
    portfolio_catalog_sha256: str

    @property
    def portfolio_id_sha256(self) -> str:
        return _private_sha256(self.portfolio_id)

    def validate(self, *, now: datetime) -> None:
        _require_private_identifier(
            self.portfolio_id,
            "slice3_portfolio_id_invalid",
        )
        if not (
            self.portfolio_name == "Default"
            and self.portfolio_type == "DEFAULT"
            and self.can_view is True
            and self.can_trade is True
            and self.product_family == "US_CFM"
            and self.intx_excluded is True
            and self.request_override_allowed is False
            and self.read_authorized is True
            and self.exact_match_count == 1
            and self.selection_authority == "cdp_api_key_permissioned_portfolio"
        ):
            raise Slice3PlanError("slice3_default_portfolio_binding_invalid")
        _require_sha256(
            self.permission_evidence_sha256,
            "slice3_portfolio_permission_evidence_sha256_invalid",
        )
        _require_sha256(
            self.portfolio_catalog_sha256,
            "slice3_portfolio_catalog_sha256_invalid",
        )
        _require_fresh(
            self.observed_at,
            now=now,
            stale_reason="slice3_portfolio_stale",
        )

    def sanitized_evidence(self) -> dict[str, Any]:
        return {
            "portfolio_id_sha256": self.portfolio_id_sha256,
            "portfolio_name": self.portfolio_name,
            "portfolio_type": self.portfolio_type,
            "can_view": self.can_view,
            "can_trade": self.can_trade,
            "product_family": self.product_family,
            "intx_excluded": self.intx_excluded,
            "request_override_allowed": self.request_override_allowed,
            "read_authorized": self.read_authorized,
            "exact_match_count": self.exact_match_count,
            "selection_authority": self.selection_authority,
            "observed_at": self.observed_at.astimezone(timezone.utc).isoformat(),
            "permission_evidence_sha256": self.permission_evidence_sha256,
            "portfolio_catalog_sha256": self.portfolio_catalog_sha256,
        }


@dataclass(frozen=True)
class Slice3CreateRequest:
    """The sole fixed Create request shape for the terminal roundtrip."""

    client_order_id: str = field(repr=False)
    preview_id: str = field(repr=False)
    product_id: str
    side: OrderSide
    base_size: str
    limit_price: str
    post_only: bool
    time_in_force: TimeInForce

    def validate(self) -> None:
        _require_uuid(
            self.client_order_id,
            "slice3_create_client_order_id_invalid",
        )
        _require_private_identifier(
            self.preview_id,
            "slice3_preview_id_invalid",
        )
        if self.product_id != SLICE3_PRODUCT_ID:
            raise Slice3PlanError("slice3_create_product_invalid")
        if self.side is not OrderSide.BUY:
            raise Slice3PlanError("slice3_create_side_invalid")
        if self.base_size != "1":
            raise Slice3PlanError("slice3_create_contract_count_invalid")
        if _decimal(self.limit_price, "slice3_limit_price_invalid") <= 0:
            raise Slice3PlanError("slice3_limit_price_invalid")
        if self.post_only is not True:
            raise Slice3PlanError("slice3_post_only_required")
        if self.time_in_force is not TimeInForce.GTC:
            raise Slice3PlanError("slice3_time_in_force_invalid")

    def preview_request(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "side": self.side.value,
            "order_configuration": {
                "limit_limit_gtc": {
                    "base_size": self.base_size,
                    "limit_price": self.limit_price,
                    "post_only": self.post_only,
                }
            },
        }

    def create_payload(self) -> dict[str, Any]:
        payload = self.preview_request()
        return {
            "client_order_id_sha256": _private_sha256(self.client_order_id),
            **payload,
            "preview_id": self.preview_id,
        }

    @property
    def preview_request_sha256(self) -> str:
        return _canonical_sha256(self.preview_request())

    @property
    def create_payload_sha256(self) -> str:
        return _canonical_sha256(self.create_payload())

    def sanitized_evidence(self) -> dict[str, Any]:
        return {
            "client_order_id_sha256": _private_sha256(self.client_order_id),
            "product_id": self.product_id,
            "side": self.side.value,
            "base_size": self.base_size,
            "limit_price": self.limit_price,
            "post_only": self.post_only,
            "time_in_force": self.time_in_force.value,
            "preview_request_sha256": self.preview_request_sha256,
            "create_payload_sha256": self.create_payload_sha256,
            "preview_id_sha256": _private_sha256(self.preview_id),
        }


@dataclass(frozen=True)
class Slice3AcceptedPreview:
    """Accepted Preview with authoritative expiry bound to the exact Create."""

    accepted: bool
    preview_id: str = field(repr=False)
    preview_request_json: str = field(repr=False)
    accepted_at: datetime
    expires_at: datetime
    evidence_sha256: str
    expiry_source: str
    expiry_evidence_sha256: str
    candidate_contract_size: str
    candidate_limit_price: str
    candidate_reference_price: str
    candidate_opening_reference_usdc: str
    commission_total: str
    order_margin_total: str
    available_margin_usdc: str

    @classmethod
    def from_request(
        cls,
        *,
        accepted: bool,
        preview_id: str,
        preview_request: Mapping[str, Any],
        accepted_at: datetime,
        expires_at: datetime,
        evidence_sha256: str,
        expiry_source: str,
        expiry_evidence_sha256: str,
        candidate_contract_size: str = "10",
        candidate_limit_price: str | None = None,
        candidate_reference_price: str,
        commission_total: str,
        order_margin_total: str,
        available_margin_usdc: str,
        candidate_opening_reference_usdc: str | None = None,
    ) -> Slice3AcceptedPreview:
        request = json.loads(_canonical_json(preview_request))
        if candidate_limit_price is None:
            try:
                candidate_limit_price = request["order_configuration"][
                    "limit_limit_gtc"
                ]["limit_price"]
            except (KeyError, TypeError) as exc:
                raise Slice3PlanError("slice3_preview_request_shape_invalid") from exc
        if candidate_opening_reference_usdc is None:
            candidate_opening_reference_usdc = _decimal_text(
                _decimal(
                    candidate_reference_price,
                    "slice3_candidate_reference_price_invalid",
                )
                * _decimal(
                    candidate_contract_size,
                    "slice3_candidate_contract_size_invalid",
                )
            )
        return cls(
            accepted=accepted,
            preview_id=preview_id,
            preview_request_json=_canonical_json(request),
            accepted_at=accepted_at,
            expires_at=expires_at,
            evidence_sha256=evidence_sha256,
            expiry_source=expiry_source,
            expiry_evidence_sha256=expiry_evidence_sha256,
            candidate_contract_size=candidate_contract_size,
            candidate_limit_price=candidate_limit_price,
            candidate_reference_price=candidate_reference_price,
            candidate_opening_reference_usdc=(candidate_opening_reference_usdc),
            commission_total=commission_total,
            order_margin_total=order_margin_total,
            available_margin_usdc=available_margin_usdc,
        )

    @property
    def preview_id_sha256(self) -> str:
        return _private_sha256(self.preview_id)

    def preview_request(self) -> dict[str, Any]:
        try:
            value = json.loads(self.preview_request_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise Slice3PlanError("slice3_preview_request_invalid") from exc
        if not isinstance(value, dict):
            raise Slice3PlanError("slice3_preview_request_invalid")
        return value

    @property
    def preview_request_sha256(self) -> str:
        return _canonical_sha256(self.preview_request())

    def validate(self, *, now: datetime) -> None:
        if self.accepted is not True:
            raise Slice3PlanError("slice3_preview_not_accepted")
        _require_private_identifier(
            self.preview_id,
            "slice3_preview_id_invalid",
        )
        _require_sha256(
            self.evidence_sha256,
            "slice3_preview_evidence_sha256_invalid",
        )
        if self.expiry_source != "coinbase_documented_preview_response":
            raise Slice3PlanError("slice3_preview_expiry_source_invalid")
        _require_sha256(
            self.expiry_evidence_sha256,
            "slice3_preview_expiry_evidence_sha256_invalid",
        )
        accepted_at = _require_aware(
            self.accepted_at,
            "slice3_preview_accepted_at_invalid",
        )
        expires_at = _require_aware(
            self.expires_at,
            "slice3_preview_expires_at_invalid",
        )
        current = _require_aware(now, "slice3_now_invalid")
        if accepted_at > current:
            raise Slice3PlanError("slice3_preview_acceptance_in_future")
        if expires_at <= current:
            raise Slice3PlanError("slice3_preview_expired")
        if expires_at <= accepted_at or (
            expires_at - accepted_at > SLICE3_MAX_PREVIEW_TTL
        ):
            raise Slice3PlanError("slice3_preview_ttl_invalid")
        if (
            _decimal(
                self.candidate_contract_size,
                "slice3_candidate_contract_size_invalid",
            )
            != SLICE3_CONTRACT_SIZE
        ):
            raise Slice3PlanError("slice3_candidate_contract_size_invalid")
        limit_price = _decimal(
            self.candidate_limit_price,
            "slice3_candidate_limit_price_invalid",
        )
        if limit_price <= 0:
            raise Slice3PlanError("slice3_candidate_limit_price_invalid")
        reference_price = _decimal(
            self.candidate_reference_price,
            "slice3_candidate_reference_price_invalid",
        )
        if reference_price <= 0 or reference_price < limit_price:
            raise Slice3PlanError("slice3_candidate_reference_price_invalid")
        opening_reference = _decimal(
            self.candidate_opening_reference_usdc,
            "slice3_candidate_opening_reference_invalid",
        )
        if opening_reference <= 0 or opening_reference != (
            reference_price * SLICE3_CONTRACT_SIZE
        ):
            raise Slice3PlanError("slice3_candidate_opening_reference_invalid")
        commission = _decimal(
            self.commission_total,
            "slice3_preview_commission_invalid",
        )
        order_margin = _decimal(
            self.order_margin_total,
            "slice3_preview_order_margin_invalid",
        )
        available_margin = _decimal(
            self.available_margin_usdc,
            "slice3_preview_available_margin_invalid",
        )
        if (
            commission < 0
            or order_margin <= 0
            or available_margin <= order_margin + commission
        ):
            raise Slice3PlanError("slice3_preview_available_margin_invalid")
        self.preview_request()

    def sanitized_evidence(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "preview_id_sha256": self.preview_id_sha256,
            "preview_request_sha256": self.preview_request_sha256,
            "accepted_at": self.accepted_at.astimezone(timezone.utc).isoformat(),
            "expires_at": self.expires_at.astimezone(timezone.utc).isoformat(),
            "evidence_sha256": self.evidence_sha256,
            "expiry_source": self.expiry_source,
            "expiry_evidence_sha256": self.expiry_evidence_sha256,
            "candidate_contract_size": self.candidate_contract_size,
            "candidate_limit_price": self.candidate_limit_price,
            "candidate_reference_price": self.candidate_reference_price,
            "candidate_opening_reference_usdc": (self.candidate_opening_reference_usdc),
            "commission_total": self.commission_total,
            "order_margin_total": self.order_margin_total,
            "available_margin_usdc": self.available_margin_usdc,
        }


@dataclass(frozen=True)
class Slice3CapEvidence:
    """Strict Slice 3 cap values; equality with any cap is rejected."""

    opening_reference_usdc: str
    maximum_concurrent_exposure_usdc: str
    conservative_close_usdc: str
    branch_turnover_usdc: str

    @property
    def opening(self) -> Decimal:
        return _decimal(
            self.opening_reference_usdc,
            "slice3_opening_cap_value_invalid",
        )

    @property
    def exposure(self) -> Decimal:
        return _decimal(
            self.maximum_concurrent_exposure_usdc,
            "slice3_exposure_cap_value_invalid",
        )

    @property
    def close(self) -> Decimal:
        return _decimal(
            self.conservative_close_usdc,
            "slice3_close_cap_value_invalid",
        )

    @property
    def turnover(self) -> Decimal:
        return _decimal(
            self.branch_turnover_usdc,
            "slice3_turnover_cap_value_invalid",
        )

    def validate(self) -> None:
        if self.opening <= 0 or self.opening >= SLICE3_OPENING_CAP_USDC:
            raise Slice3PlanError("slice3_opening_cap_invalid")
        if self.exposure >= SLICE3_EXPOSURE_CAP_USDC:
            raise Slice3PlanError("slice3_exposure_cap_invalid")
        if self.exposure != self.opening:
            raise Slice3PlanError("slice3_exposure_binding_invalid")
        if self.close <= 0 or self.close >= SLICE3_EXPOSURE_CAP_USDC:
            raise Slice3PlanError("slice3_close_cap_invalid")
        if self.close != self.exposure * SLICE3_CLOSE_BUFFER:
            raise Slice3PlanError("slice3_close_binding_invalid")
        if self.turnover != self.opening + self.close or (
            self.turnover >= SLICE3_TURNOVER_CAP_USDC
        ):
            raise Slice3PlanError("slice3_turnover_cap_invalid")

    def sanitized_evidence(self) -> dict[str, str]:
        return {
            "opening_reference_usdc": self.opening_reference_usdc,
            "maximum_concurrent_exposure_usdc": (self.maximum_concurrent_exposure_usdc),
            "conservative_close_usdc": self.conservative_close_usdc,
            "branch_turnover_usdc": self.branch_turnover_usdc,
            "opening_cap": "<100",
            "exposure_and_buffered_close_cap": "<150",
            "branch_turnover_cap": "<300",
        }


@dataclass(frozen=True)
class Slice3Plan:
    """Immutable in-memory plan whose public form contains hashes only."""

    policy: Slice3Policy
    execution_authority: Slice3ExecutionAuthority
    margin_windows: Slice3MarginWindowEvidence
    portfolio: Slice3PortfolioBinding = field(repr=False)
    preview: Slice3AcceptedPreview = field(repr=False)
    create: Slice3CreateRequest
    caps: Slice3CapEvidence
    close_client_order_id: str = field(repr=False)
    baseline_position_contracts: Decimal
    baseline_position_sha256: str
    backend_revision: str
    openapi_revision: str
    contract_size: Decimal
    expires_at: datetime
    risk_off_expires_at: datetime

    @classmethod
    def build(
        cls,
        *,
        policy: Slice3Policy,
        execution_authority: Slice3ExecutionAuthority,
        margin_windows: Slice3MarginWindowEvidence,
        portfolio: Slice3PortfolioBinding,
        preview: Slice3AcceptedPreview,
        create: Slice3CreateRequest,
        caps: Slice3CapEvidence,
        close_client_order_id: str,
        baseline_position_contracts: Decimal | str,
        baseline_position_sha256: str,
        backend_revision: str,
        openapi_revision: str,
        now: datetime,
        risk_off_expires_at: datetime | None = None,
    ) -> Slice3Plan:
        if policy not in {SLICE3_POLICY, SLICE3_LIVE_POLICY}:
            raise Slice3PolicyError("slice3_policy_version_invalid")
        if not isinstance(execution_authority, Slice3ExecutionAuthority):
            raise Slice3PlanError("slice3_execution_authority_invalid")
        execution_authority.validate(now=now)
        policy.validate_margin_windows(margin_windows)
        portfolio.validate(now=now)
        create.validate()
        preview.validate(now=now)
        if create.preview_id != preview.preview_id:
            raise Slice3PlanError("slice3_preview_id_mismatch")
        if _canonical_json(create.preview_request()) != (
            _canonical_json(preview.preview_request())
        ):
            raise Slice3PlanError("slice3_preview_create_payload_mismatch")
        if (
            _decimal(
                preview.candidate_contract_size,
                "slice3_candidate_contract_size_invalid",
            )
            != SLICE3_CONTRACT_SIZE
        ):
            raise Slice3PlanError("slice3_candidate_contract_size_invalid")
        if _decimal(
            preview.candidate_limit_price,
            "slice3_candidate_limit_price_invalid",
        ) != _decimal(create.limit_price, "slice3_limit_price_invalid"):
            raise Slice3PlanError("slice3_candidate_limit_price_mismatch")
        caps.validate()
        if (
            _decimal(
                preview.candidate_opening_reference_usdc,
                "slice3_candidate_opening_reference_invalid",
            )
            != caps.opening
        ):
            raise Slice3PlanError("slice3_candidate_opening_reference_mismatch")
        baseline = _decimal(
            baseline_position_contracts,
            "slice3_baseline_position_invalid",
        )
        if baseline != 0:
            raise Slice3PlanError("slice3_baseline_position_not_flat")
        _require_sha256(
            baseline_position_sha256,
            "slice3_baseline_position_sha256_invalid",
        )
        _require_uuid(
            close_client_order_id,
            "slice3_close_client_order_id_invalid",
        )
        if close_client_order_id == create.client_order_id:
            raise Slice3PlanError("slice3_close_client_order_id_reused")
        if (
            len(
                {
                    execution_authority.correlation_id,
                    execution_authority.preview_idempotency_key,
                    create.client_order_id,
                    close_client_order_id,
                }
            )
            != 4
        ):
            raise Slice3PlanError("slice3_execution_authority_identifier_collision")
        if not isinstance(backend_revision, str) or not backend_revision.strip():
            raise Slice3PlanError("slice3_backend_revision_invalid")
        if not isinstance(openapi_revision, str) or not openapi_revision.strip():
            raise Slice3PlanError("slice3_openapi_revision_invalid")
        accepted_at = _require_aware(
            preview.accepted_at,
            "slice3_preview_accepted_at_invalid",
        )
        create_expiry = _require_aware(
            preview.expires_at,
            "slice3_preview_expires_at_invalid",
        )
        risk_off_expiry = _require_aware(
            risk_off_expires_at
            if risk_off_expires_at is not None
            else accepted_at + SLICE3_MAX_RISK_OFF_TTL,
            "slice3_risk_off_expiry_invalid",
        )
        if (
            risk_off_expiry <= create_expiry
            or risk_off_expiry > accepted_at + SLICE3_MAX_RISK_OFF_TTL
        ):
            raise Slice3PlanError("slice3_risk_off_expiry_invalid")
        return cls(
            policy=policy,
            execution_authority=execution_authority,
            margin_windows=margin_windows,
            portfolio=portfolio,
            preview=preview,
            create=create,
            caps=caps,
            close_client_order_id=close_client_order_id,
            baseline_position_contracts=baseline,
            baseline_position_sha256=baseline_position_sha256,
            backend_revision=backend_revision,
            openapi_revision=openapi_revision,
            contract_size=SLICE3_CONTRACT_SIZE,
            expires_at=create_expiry,
            risk_off_expires_at=risk_off_expiry,
        )

    def validate_at(self, now: datetime) -> None:
        rebuilt = Slice3Plan.build(
            policy=self.policy,
            execution_authority=self.execution_authority,
            margin_windows=self.margin_windows,
            portfolio=self.portfolio,
            preview=self.preview,
            create=self.create,
            caps=self.caps,
            close_client_order_id=self.close_client_order_id,
            baseline_position_contracts=self.baseline_position_contracts,
            baseline_position_sha256=self.baseline_position_sha256,
            backend_revision=self.backend_revision,
            openapi_revision=self.openapi_revision,
            now=now,
            risk_off_expires_at=self.risk_off_expires_at,
        )
        if self.contract_size != rebuilt.contract_size:
            raise Slice3PlanError("slice3_contract_size_invalid")
        if self.expires_at != rebuilt.expires_at:
            raise Slice3PlanError("slice3_expiry_binding_invalid")
        if self.risk_off_expires_at != rebuilt.risk_off_expires_at:
            raise Slice3PlanError("slice3_risk_off_expiry_binding_invalid")
        if self != rebuilt:
            raise Slice3PlanError("slice3_plan_binding_invalid")
        if _require_aware(now, "slice3_now_invalid") >= self.expires_at:
            raise Slice3PlanError("slice3_plan_expired")

    def validate_risk_off_at(self, now: datetime) -> None:
        """Revalidate immutable bindings without reauthorizing Create."""

        current = _require_aware(now, "slice3_now_invalid")
        if current >= self.risk_off_expires_at:
            raise Slice3PlanError("slice3_risk_off_expired")
        structural_now = max(
            _require_aware(
                self.preview.accepted_at,
                "slice3_preview_accepted_at_invalid",
            ),
            _require_aware(
                self.execution_authority.observed_at,
                "slice3_execution_authority_stale_timestamp_invalid",
            ),
            _require_aware(
                self.portfolio.observed_at,
                "slice3_portfolio_stale_timestamp_invalid",
            ),
        )
        rebuilt = Slice3Plan.build(
            policy=self.policy,
            execution_authority=self.execution_authority,
            margin_windows=self.margin_windows,
            portfolio=self.portfolio,
            preview=self.preview,
            create=self.create,
            caps=self.caps,
            close_client_order_id=self.close_client_order_id,
            baseline_position_contracts=self.baseline_position_contracts,
            baseline_position_sha256=self.baseline_position_sha256,
            backend_revision=self.backend_revision,
            openapi_revision=self.openapi_revision,
            now=structural_now,
            risk_off_expires_at=self.risk_off_expires_at,
        )
        if self != rebuilt:
            raise Slice3PlanError("slice3_plan_binding_invalid")

    def sanitized_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": "slice3-terminal-roundtrip-plan-v4",
            "policy": self.policy.sanitized_evidence(),
            "execution_authority": (self.execution_authority.sanitized_evidence()),
            "margin_windows": self.margin_windows.sanitized_evidence(),
            "portfolio": self.portfolio.sanitized_evidence(),
            "preview": self.preview.sanitized_evidence(),
            "create": self.create.sanitized_evidence(),
            "caps": self.caps.sanitized_evidence(),
            "close_client_order_id_sha256": _private_sha256(self.close_client_order_id),
            "baseline_position_contracts": _decimal_text(
                self.baseline_position_contracts
            ),
            "baseline_position_sha256": self.baseline_position_sha256,
            "backend_revision": self.backend_revision,
            "openapi_revision": self.openapi_revision,
            "contract_size": _decimal_text(self.contract_size),
            "expires_at": self.expires_at.isoformat(),
            "risk_off_expires_at": self.risk_off_expires_at.isoformat(),
            "action_order": [
                Slice3ActionKind.CREATE.value,
                Slice3ActionKind.CANCEL.value,
                Slice3ActionKind.CLOSE.value,
            ],
            "client_order_id_is_operator_identity": True,
            "exchange_order_id_evidence_only": True,
        }

    @property
    def plan_sha256(self) -> str:
        return _canonical_sha256(self.sanitized_evidence())

    def action_claim(self, action: Slice3ActionKind) -> Slice3ActionClaim:
        indices = {
            Slice3ActionKind.CREATE: 1,
            Slice3ActionKind.CANCEL: 2,
            Slice3ActionKind.CLOSE: 3,
        }
        operator_identity = (
            self.close_client_order_id
            if action is Slice3ActionKind.CLOSE
            else self.create.client_order_id
        )
        return Slice3ActionClaim(
            plan_sha256=self.plan_sha256,
            action_index=indices[action],
            action=action,
            portfolio_id_sha256=self.portfolio.portfolio_id_sha256,
            product_id=SLICE3_PRODUCT_ID,
            operator_identity=operator_identity,
        )


@dataclass(frozen=True)
class Slice3PositionObservation:
    """Sanitized exact-product position evidence."""

    authoritative: bool
    product_id: str
    side: AdminFuturesPositionSide
    contracts: Decimal | str
    reference_price: Decimal | str | None
    contract_size: Decimal | str
    observed_at: datetime
    snapshot_sha256: str

    @property
    def contract_delta(self) -> Decimal:
        return _decimal(self.contracts, "slice3_position_contracts_invalid")

    @property
    def reference(self) -> Decimal | None:
        if self.reference_price is None:
            return None
        return _decimal(
            self.reference_price,
            "slice3_position_reference_invalid",
        )

    def validate(
        self,
        plan: Slice3Plan,
        *,
        now: datetime,
        require_fresh: bool = True,
    ) -> None:
        if self.authoritative is not True:
            raise Slice3PlanError("slice3_position_not_authoritative")
        if self.product_id != plan.create.product_id:
            raise Slice3PlanError("slice3_position_product_invalid")
        if (
            _decimal(
                self.contract_size,
                "slice3_position_contract_size_invalid",
            )
            != plan.contract_size
        ):
            raise Slice3PlanError("slice3_position_contract_size_invalid")
        _require_sha256(
            self.snapshot_sha256,
            "slice3_position_snapshot_sha256_invalid",
        )
        if require_fresh:
            _require_fresh(
                self.observed_at,
                now=now,
                stale_reason="slice3_position_stale",
            )
        delta = self.contract_delta
        if delta < 0:
            raise Slice3PlanError("slice3_position_delta_invalid")
        if delta > 1:
            raise Slice3PlanError("slice3_position_delta_exceeds_scope")
        if self.side is AdminFuturesPositionSide.FLAT:
            if delta != 0:
                raise Slice3PlanError("slice3_flat_position_delta_invalid")
            return
        if self.side is not AdminFuturesPositionSide.LONG:
            raise Slice3PlanError("slice3_position_side_invalid")
        if delta <= 0:
            raise Slice3PlanError("slice3_long_position_delta_invalid")
        if self.reference is None or self.reference <= 0:
            raise Slice3PlanError("slice3_position_reference_invalid")

    def sanitized_evidence(self) -> dict[str, Any]:
        return {
            "authoritative": self.authoritative,
            "product_id": self.product_id,
            "side": self.side.value,
            "contracts": _decimal_text(self.contract_delta),
            "reference_price": (
                None if self.reference is None else _decimal_text(self.reference)
            ),
            "contract_size": _decimal_text(
                _decimal(
                    self.contract_size,
                    "slice3_position_contract_size_invalid",
                )
            ),
            "observed_at": self.observed_at.astimezone(timezone.utc).isoformat(),
            "snapshot_sha256": self.snapshot_sha256,
        }


@dataclass(frozen=True)
class Slice3MarketReference:
    """Fresh exact-product market reference required before Close."""

    authoritative: bool
    product_id: str
    reference_price: Decimal | str
    observed_at: datetime
    snapshot_sha256: str

    @property
    def reference(self) -> Decimal:
        return _decimal(
            self.reference_price,
            "slice3_market_reference_invalid",
        )

    def validate(self, plan: Slice3Plan, *, now: datetime) -> None:
        if self.authoritative is not True:
            raise Slice3MutationBlocked("slice3_market_not_authoritative")
        if self.product_id != plan.create.product_id:
            raise Slice3MutationBlocked("slice3_market_product_invalid")
        if self.reference <= 0:
            raise Slice3MutationBlocked("slice3_market_reference_invalid")
        try:
            _require_sha256(
                self.snapshot_sha256,
                "slice3_market_snapshot_sha256_invalid",
            )
            _require_fresh(
                self.observed_at,
                now=now,
                stale_reason="slice3_market_stale",
            )
        except Slice3PlanError as exc:
            raise Slice3MutationBlocked(str(exc)) from None

    def sanitized_evidence(self) -> dict[str, Any]:
        return {
            "authoritative": self.authoritative,
            "product_id": self.product_id,
            "reference_price": _decimal_text(self.reference),
            "observed_at": self.observed_at.astimezone(timezone.utc).isoformat(),
            "snapshot_sha256": self.snapshot_sha256,
        }


@dataclass(frozen=True)
class Slice3PreCreateEvidence:
    """Fresh zero-order and zero-position proof required before Create."""

    open_orders_authoritative: bool
    open_orders_pagination_complete: bool
    open_orders_scope: str
    exact_product_active_order_count: int
    open_orders_snapshot_sha256: str
    open_orders_observed_at: datetime
    position: Slice3PositionObservation
    margin_authoritative: bool
    margin_status: str
    margin_account_family: str
    margin_available_usdc: Decimal | str
    margin_windows: Slice3MarginWindowEvidence
    margin_observed_at: datetime
    margin_snapshot_sha256: str

    def validate(self, plan: Slice3Plan, *, now: datetime) -> None:
        if self.open_orders_authoritative is not True:
            raise Slice3MutationBlocked(
                "slice3_pre_create_open_orders_not_authoritative"
            )
        if self.open_orders_pagination_complete is not True:
            raise Slice3MutationBlocked("slice3_pre_create_open_orders_incomplete")
        if self.open_orders_scope != "exact_product_active_transitional_orders":
            raise Slice3MutationBlocked("slice3_pre_create_open_orders_scope_invalid")
        if self.exact_product_active_order_count != 0:
            raise Slice3MutationBlocked("slice3_pre_create_active_orders")
        try:
            _require_sha256(
                self.open_orders_snapshot_sha256,
                "slice3_pre_create_open_orders_sha256_invalid",
            )
            _require_fresh(
                self.open_orders_observed_at,
                now=now,
                stale_reason="slice3_pre_create_open_orders_stale",
            )
            self.position.validate(plan, now=now)
        except Slice3PlanError as exc:
            raise Slice3MutationBlocked(str(exc)) from None
        if not (
            self.position.side is AdminFuturesPositionSide.FLAT
            and self.position.contract_delta == plan.baseline_position_contracts
        ):
            raise Slice3MutationBlocked("slice3_pre_create_position_not_flat")
        if not (
            self.margin_authoritative is True
            and self.margin_status == "ready"
            and self.margin_account_family == "coinbase_futures_us_cfm"
        ):
            raise Slice3MutationBlocked("slice3_pre_create_margin_invalid")
        try:
            plan.policy.validate_margin_windows(self.margin_windows)
            _require_sha256(
                self.margin_snapshot_sha256,
                "slice3_pre_create_margin_sha256_invalid",
            )
            _require_fresh(
                self.margin_observed_at,
                now=now,
                stale_reason="slice3_pre_create_margin_stale",
            )
            available = _decimal(
                self.margin_available_usdc,
                "slice3_pre_create_margin_invalid",
            )
            required = _decimal(
                plan.preview.order_margin_total,
                "slice3_preview_order_margin_invalid",
            ) + _decimal(
                plan.preview.commission_total,
                "slice3_preview_commission_invalid",
            )
        except (Slice3PlanError, Slice3PolicyError) as exc:
            raise Slice3MutationBlocked(str(exc)) from None
        if available <= required:
            raise Slice3MutationBlocked("slice3_pre_create_margin_insufficient")


@dataclass(frozen=True)
class Slice3OpenOrderZeroProof:
    """Fresh product-wide absence proof required immediately before Close."""

    authoritative: bool
    pagination_complete: bool
    scope: str
    product_id: str
    exact_product_active_order_count: int
    observed_at: datetime
    snapshot_sha256: str
    raw_response_included: bool = False
    identifier_values_included: bool = False

    def validate(self, plan: Slice3Plan, *, now: datetime) -> None:
        if self.authoritative is not True:
            raise Slice3MutationBlocked(
                "slice3_pre_close_open_orders_not_authoritative"
            )
        if self.pagination_complete is not True:
            raise Slice3MutationBlocked("slice3_pre_close_open_orders_incomplete")
        if self.scope != "exact_product_active_transitional_orders":
            raise Slice3MutationBlocked("slice3_pre_close_open_orders_scope_invalid")
        if self.product_id != plan.create.product_id:
            raise Slice3MutationBlocked("slice3_pre_close_open_orders_product_invalid")
        if (
            type(self.exact_product_active_order_count) is not int
            or self.exact_product_active_order_count != 0
        ):
            raise Slice3MutationBlocked("slice3_pre_close_active_orders")
        if (
            self.raw_response_included is not False
            or self.identifier_values_included is not False
        ):
            raise Slice3MutationBlocked("slice3_pre_close_open_orders_private")
        try:
            _require_sha256(
                self.snapshot_sha256,
                "slice3_pre_close_open_orders_sha256_invalid",
            )
            _require_fresh(
                self.observed_at,
                now=now,
                stale_reason="slice3_pre_close_open_orders_stale",
            )
        except Slice3PlanError as exc:
            raise Slice3MutationBlocked(str(exc)) from None

    def sanitized_evidence(self) -> dict[str, object]:
        return {
            "schema_version": "slice3-open-order-zero-proof-v1",
            "authoritative": self.authoritative,
            "pagination_complete": self.pagination_complete,
            "scope": self.scope,
            "product_id": self.product_id,
            "exact_product_active_order_count": (
                self.exact_product_active_order_count
            ),
            "observed_at": self.observed_at.astimezone(timezone.utc).isoformat(),
            "snapshot_sha256": self.snapshot_sha256,
            "raw_response_included": self.raw_response_included,
            "identifier_values_included": self.identifier_values_included,
        }


@dataclass(frozen=True)
class Slice3OrderObservation:
    """Sanitized authoritative state of the one opening order."""

    authoritative: bool
    pagination_complete: bool
    product_id: str
    client_order_id: str = field(repr=False)
    exchange_order_id: str | None = field(repr=False)
    status: OrderStatus
    filled_contracts: Decimal | str
    remaining_contracts: Decimal | str
    active_order_count: int
    observed_at: datetime
    resolution_source: Slice3OrderResolutionSource
    exact_client_order_match_count: int | None = None

    @property
    def filled(self) -> Decimal:
        return _decimal(
            self.filled_contracts,
            "slice3_order_filled_contracts_invalid",
        )

    @property
    def remaining(self) -> Decimal:
        return _decimal(
            self.remaining_contracts,
            "slice3_order_remaining_contracts_invalid",
        )

    def sanitized_evidence(self) -> dict[str, Any]:
        return {
            "authoritative": self.authoritative,
            "pagination_complete": self.pagination_complete,
            "product_id": self.product_id,
            "client_order_id_sha256": _private_sha256(self.client_order_id),
            "exchange_order_id_sha256": (
                None
                if self.exchange_order_id is None
                else _private_sha256(self.exchange_order_id)
            ),
            "status": self.status.value,
            "filled_contracts": _decimal_text(self.filled),
            "remaining_contracts": _decimal_text(self.remaining),
            "active_order_count": self.active_order_count,
            "observed_at": self.observed_at.astimezone(timezone.utc).isoformat(),
            "resolution_source": self.resolution_source.value,
            "exact_client_order_match_count": (self.exact_client_order_match_count),
        }


@dataclass(frozen=True)
class Slice3Directive:
    """One pure decision. Private exchange identity is never serialized raw."""

    kind: Slice3DirectiveKind
    reason_code: str
    exchange_order_id: str | None = field(default=None, repr=False)
    close_contracts: Decimal | None = None

    def __post_init__(self) -> None:
        _require_safe_reason(self.reason_code)

    def sanitized_evidence(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "reason_code": self.reason_code,
            "exchange_order_id_sha256": (
                None
                if self.exchange_order_id is None
                else _private_sha256(self.exchange_order_id)
            ),
            "close_contracts": (
                None
                if self.close_contracts is None
                else _decimal_text(self.close_contracts)
            ),
        }


@dataclass(frozen=True)
class Slice3MutationResult:
    """Only value an injected adapter may return across the mutation seam."""

    outcome: Slice3MutationOutcome
    reason_code: str
    exchange_order_id: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, Slice3MutationOutcome):
            raise Slice3PlanError("slice3_mutation_outcome_invalid")
        _require_safe_reason(self.reason_code)
        if self.exchange_order_id is not None:
            _require_private_identifier(
                self.exchange_order_id,
                "slice3_exchange_order_id_invalid",
            )

    @property
    def exchange_order_id_sha256(self) -> str | None:
        if self.exchange_order_id is None:
            return None
        return _private_sha256(self.exchange_order_id)

    def sanitized_evidence(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "reason_code": self.reason_code,
            "exchange_order_id_sha256": self.exchange_order_id_sha256,
        }


def initial_slice3_directive(result: Slice3MutationResult) -> Slice3Directive:
    """Classify Create return without treating it as authoritative readback."""

    if result.outcome is Slice3MutationOutcome.REJECTED:
        return Slice3Directive(
            kind=Slice3DirectiveKind.COMPLETE_REJECTED,
            reason_code="create_explicitly_rejected",
        )
    if result.outcome is Slice3MutationOutcome.UNKNOWN:
        return Slice3Directive(
            kind=Slice3DirectiveKind.READ_ONLY_RECONCILE,
            reason_code="unknown_create_exact_client_lookup_required",
        )
    return Slice3Directive(
        kind=Slice3DirectiveKind.READ_ONLY_RECONCILE,
        reason_code="post_create_reads_required",
    )


def _read_only(reason: str) -> Slice3Directive:
    return Slice3Directive(
        kind=Slice3DirectiveKind.READ_ONLY_RECONCILE,
        reason_code=reason,
    )


def _halt(reason: str) -> Slice3Directive:
    return Slice3Directive(
        kind=Slice3DirectiveKind.HALT_SAFETY,
        reason_code=reason,
    )


def decide_slice3_next_action(
    plan: Slice3Plan,
    *,
    order: Slice3OrderObservation,
    position: Slice3PositionObservation,
    now: datetime,
    create_outcome: Slice3MutationOutcome = Slice3MutationOutcome.ACCEPTED,
) -> Slice3Directive:
    """Return the only safe next action from sanitized finite read evidence.

    A Close is impossible while the opening order is active or transitional,
    while any exact-product order remains active, or while an unknown Create
    has not resolved to exactly one row for the sealed ``client_order_id``.
    """

    plan.validate_risk_off_at(now)
    if create_outcome is Slice3MutationOutcome.REJECTED:
        return Slice3Directive(
            kind=Slice3DirectiveKind.COMPLETE_REJECTED,
            reason_code="create_explicitly_rejected",
        )
    if create_outcome is Slice3MutationOutcome.UNKNOWN and not (
        order.resolution_source
        is Slice3OrderResolutionSource.EXACT_CLIENT_ORDER_ID_LOOKUP
        and order.exact_client_order_match_count == 1
    ):
        return _read_only("unknown_create_not_uniquely_resolved")
    if order.authoritative is not True:
        return _read_only("order_not_authoritative")
    if order.pagination_complete is not True:
        return _read_only("order_read_incomplete")
    if order.product_id != plan.create.product_id:
        return _halt("order_product_mismatch")
    if order.client_order_id != plan.create.client_order_id:
        return _halt("order_client_identity_mismatch")
    try:
        _require_fresh(
            order.observed_at,
            now=now,
            stale_reason="slice3_order_stale",
        )
        filled = order.filled
        remaining = order.remaining
    except Slice3PlanError:
        return _read_only("order_evidence_invalid")
    if (
        filled < 0
        or remaining < 0
        or filled > 1
        or remaining > 1
        or not isinstance(order.active_order_count, int)
        or isinstance(order.active_order_count, bool)
        or order.active_order_count < 0
    ):
        return _halt("order_quantity_or_active_count_invalid")
    try:
        position.validate(plan, now=now)
    except Slice3PlanError as exc:
        reason = str(exc)
        if reason == "slice3_position_stale":
            return _read_only("position_refresh_required")
        return _halt("position_evidence_outside_scope")
    position_delta = position.contract_delta

    if order.status is OrderStatus.CANCEL_QUEUED:
        if order.active_order_count != 1:
            return _read_only("cancel_queued_active_count_not_exact")
        if filled + remaining != 1:
            return _halt("cancel_queued_contract_conservation_invalid")
        if filled == 0:
            if not (
                position.side is AdminFuturesPositionSide.FLAT and position_delta == 0
            ):
                return _halt("cancel_queued_position_mismatch")
        elif not (
            Decimal("0") < filled <= Decimal("1")
            and position.side is AdminFuturesPositionSide.LONG
            and position_delta == filled
        ):
            return _halt("cancel_queued_position_mismatch")
        return _read_only("cancel_queued_final_reconciliation_required")

    if order.status in {
        OrderStatus.PENDING,
        OrderStatus.QUEUED,
        OrderStatus.EDIT_QUEUED,
    }:
        if order.active_order_count != 1:
            return _read_only("transitional_order_active_count_not_exact")
        if filled + remaining != 1:
            return _halt("transitional_order_contract_conservation_invalid")
        if filled == 0:
            if not (
                position.side is AdminFuturesPositionSide.FLAT and position_delta == 0
            ):
                return _halt("transitional_zero_fill_position_mismatch")
        elif not (
            Decimal("0") < filled < Decimal("1")
            and position.side is AdminFuturesPositionSide.LONG
            and position_delta == filled
        ):
            return _halt("transitional_partial_position_mismatch")
        return _read_only("transitional_order_mutation_not_authorized")

    if order.status is OrderStatus.OPEN:
        if order.active_order_count != 1:
            return _read_only("open_order_active_count_not_exact")
        if order.exchange_order_id is None:
            return _read_only("open_order_exchange_identity_missing")
        try:
            _require_private_identifier(
                order.exchange_order_id,
                "slice3_exchange_order_id_invalid",
            )
        except Slice3PlanError:
            return _halt("open_order_exchange_identity_invalid")
        if filled + remaining != 1:
            return _halt("open_order_contract_conservation_invalid")
        if filled == 0:
            if not (
                position.side is AdminFuturesPositionSide.FLAT and position_delta == 0
            ):
                return _halt("open_zero_fill_position_mismatch")
            return Slice3Directive(
                kind=Slice3DirectiveKind.CANCEL_OPEN,
                reason_code="authoritative_open_zero_fill",
                exchange_order_id=order.exchange_order_id,
            )
        if not (
            Decimal("0") < filled < Decimal("1")
            and position.side is AdminFuturesPositionSide.LONG
            and position_delta == filled
        ):
            return _halt("partial_fill_position_mismatch")
        return Slice3Directive(
            kind=Slice3DirectiveKind.CANCEL_RESIDUAL,
            reason_code="authoritative_partial_residual_active",
            exchange_order_id=order.exchange_order_id,
        )

    if order.status is OrderStatus.FILLED:
        if order.active_order_count != 0:
            return _read_only("filled_order_residual_active")
        if not (
            filled == 1
            and remaining == 0
            and position.side is AdminFuturesPositionSide.LONG
            and position_delta == 1
        ):
            return _halt("filled_order_position_mismatch")
        return Slice3Directive(
            kind=Slice3DirectiveKind.CLOSE_EXACT_DELTA,
            reason_code="filled_order_terminal_close_exact_delta",
            close_contracts=position_delta,
        )

    if order.status in {OrderStatus.CANCELLED, OrderStatus.EXPIRED}:
        if order.active_order_count != 0:
            return _read_only("terminal_order_residual_active")
        if filled == 0:
            if not (
                position.side is AdminFuturesPositionSide.FLAT and position_delta == 0
            ):
                return _halt("cancelled_zero_fill_position_mismatch")
            return Slice3Directive(
                kind=Slice3DirectiveKind.COMPLETE_FLAT,
                reason_code="terminal_cancelled_flat",
            )
        if not (
            Decimal("0") < filled <= Decimal("1")
            and position.side is AdminFuturesPositionSide.LONG
            and position_delta == filled
        ):
            return _halt("terminal_partial_position_mismatch")
        return Slice3Directive(
            kind=Slice3DirectiveKind.CLOSE_EXACT_DELTA,
            reason_code="residual_cancel_terminal_close_exact_delta",
            close_contracts=position_delta,
        )

    if order.status is OrderStatus.FAILED:
        if order.active_order_count == 0 and position_delta == 0:
            return Slice3Directive(
                kind=Slice3DirectiveKind.COMPLETE_REJECTED,
                reason_code="opening_order_failed_without_exposure",
            )
        return _read_only("failed_order_exposure_requires_reconciliation")
    return _read_only("order_status_not_terminally_classified")


class Slice3ReadBudget:
    """In-memory finite slot ledger for a later sealed orchestrator."""

    def __init__(self) -> None:
        self._counts = {slot: 0 for slot in Slice3ReadSlot}
        self._lock = RLock()

    def consume(self, slot: Slice3ReadSlot) -> None:
        if not isinstance(slot, Slice3ReadSlot):
            raise Slice3MutationBlocked("slice3_read_slot_invalid")
        with self._lock:
            if self._counts[slot] != 0:
                raise Slice3MutationBlocked(f"slice3_read_slot_consumed_{slot.value}")
            self._counts[slot] = 1

    @property
    def total(self) -> int:
        with self._lock:
            return sum(self._counts.values())

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {slot.value: self._counts[slot] for slot in Slice3ReadSlot}


@dataclass(frozen=True)
class Slice3TerminalEvidence:
    """Final, separately fresh proof that the pre-order baseline is restored."""

    post_close_order: Slice3OrderObservation
    final_position: Slice3PositionObservation
    final_open_orders_authoritative: bool
    final_open_orders_pagination_complete: bool
    final_exact_product_active_order_count: int
    final_open_orders_snapshot_sha256: str
    margin_authoritative: bool
    margin_observed_at: datetime
    margin_snapshot_sha256: str

    def validate(self, plan: Slice3Plan, *, now: datetime) -> None:
        order = self.post_close_order
        if not (
            order.authoritative is True
            and order.pagination_complete is True
            and order.product_id == plan.create.product_id
            and order.client_order_id == plan.create.client_order_id
            and order.status
            in {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.EXPIRED}
            and order.active_order_count == 0
        ):
            raise Slice3PlanError("slice3_post_close_order_not_terminal")
        _require_fresh(
            order.observed_at,
            now=now,
            stale_reason="slice3_post_close_order_stale",
        )
        self.final_position.validate(plan, now=now)
        if not (
            self.final_position.side is AdminFuturesPositionSide.FLAT
            and self.final_position.contract_delta == plan.baseline_position_contracts
        ):
            raise Slice3PlanError("slice3_final_position_not_flat")
        if not (
            self.final_open_orders_authoritative is True
            and self.final_open_orders_pagination_complete is True
        ):
            raise Slice3PlanError("slice3_final_open_orders_incomplete")
        if self.final_exact_product_active_order_count != 0:
            raise Slice3PlanError("slice3_final_active_orders_present")
        _require_sha256(
            self.final_open_orders_snapshot_sha256,
            "slice3_final_open_orders_sha256_invalid",
        )
        if self.margin_authoritative is not True:
            raise Slice3PlanError("slice3_final_margin_not_authoritative")
        _require_sha256(
            self.margin_snapshot_sha256,
            "slice3_final_margin_sha256_invalid",
        )
        _require_fresh(
            self.margin_observed_at,
            now=now,
            stale_reason="slice3_final_margin_stale",
        )

    def sanitized_evidence(self) -> dict[str, Any]:
        return {
            "post_close_order": self.post_close_order.sanitized_evidence(),
            "final_position": self.final_position.sanitized_evidence(),
            "final_open_orders": {
                "authoritative": self.final_open_orders_authoritative,
                "pagination_complete": self.final_open_orders_pagination_complete,
                "exact_product_active_order_count": (
                    self.final_exact_product_active_order_count
                ),
                "snapshot_sha256": self.final_open_orders_snapshot_sha256,
            },
            "final_margin": {
                "authoritative": self.margin_authoritative,
                "observed_at": self.margin_observed_at.astimezone(
                    timezone.utc
                ).isoformat(),
                "snapshot_sha256": self.margin_snapshot_sha256,
            },
        }


@dataclass(frozen=True)
class Slice3ActionClaim:
    """Semantic action identity reserved before any client access."""

    plan_sha256: str
    action_index: int
    action: Slice3ActionKind
    portfolio_id_sha256: str
    product_id: str
    operator_identity: str = field(repr=False)
    schema_version: str = "slice3-action-claim-v1"

    def validate(self) -> None:
        _require_sha256(self.plan_sha256, "slice3_claim_plan_sha256_invalid")
        if self.action_index not in {1, 2, 3}:
            raise Slice3ClaimError("slice3_claim_action_index_invalid")
        if not isinstance(self.action, Slice3ActionKind):
            raise Slice3ClaimError("slice3_claim_action_invalid")
        try:
            _require_sha256(
                self.portfolio_id_sha256,
                "slice3_claim_portfolio_sha256_invalid",
            )
        except Slice3PlanError as exc:
            raise Slice3ClaimError(str(exc)) from None
        if self.product_id != SLICE3_PRODUCT_ID:
            raise Slice3ClaimError("slice3_claim_product_invalid")
        try:
            _require_uuid(
                self.operator_identity,
                "slice3_claim_operator_identity_invalid",
            )
        except Slice3PlanError as exc:
            raise Slice3ClaimError(str(exc)) from None

    @property
    def semantic_key(self) -> str:
        return _canonical_sha256(
            {
                "schema_version": self.schema_version,
                "plan_sha256": self.plan_sha256,
                "action_index": self.action_index,
                "action": self.action.value,
                "portfolio_id_sha256": self.portfolio_id_sha256,
                "product_id": self.product_id,
                "operator_identity": self.operator_identity,
            }
        )

    @property
    def operator_identity_sha256(self) -> str:
        """Persistence-safe binding to the in-memory operator identity."""

        return _private_sha256(self.operator_identity)


@dataclass(frozen=True)
class Slice3ClaimRecord:
    """One sanitized append-only claim event."""

    event: Slice3ClaimEvent
    recorded_at: str
    semantic_key: str
    plan_sha256: str
    action_index: int
    action: Slice3ActionKind
    portfolio_id_sha256: str
    product_id: str
    operator_identity_sha256: str
    previous_record_sha256: str
    record_sha256: str
    position_snapshot_sha256: str | None = None
    market_snapshot_sha256: str | None = None
    dependency_evidence_sha256: str | None = None
    outcome: Slice3MutationOutcome | None = None
    reason_code: str | None = None
    exchange_order_id_sha256: str | None = None
    schema_version: str = SLICE3_ACTION_RECORD_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event": self.event.value,
            "recorded_at": self.recorded_at,
            "semantic_key": self.semantic_key,
            "plan_sha256": self.plan_sha256,
            "action_index": self.action_index,
            "action": self.action.value,
            "portfolio_id_sha256": self.portfolio_id_sha256,
            "product_id": self.product_id,
            "operator_identity_sha256": self.operator_identity_sha256,
            "previous_record_sha256": self.previous_record_sha256,
            "record_sha256": self.record_sha256,
            "position_snapshot_sha256": self.position_snapshot_sha256,
            "market_snapshot_sha256": self.market_snapshot_sha256,
            "dependency_evidence_sha256": self.dependency_evidence_sha256,
            "outcome": None if self.outcome is None else self.outcome.value,
            "reason_code": self.reason_code,
            "exchange_order_id_sha256": self.exchange_order_id_sha256,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Slice3ClaimRecord:
        expected = {
            "schema_version",
            "event",
            "recorded_at",
            "semantic_key",
            "plan_sha256",
            "action_index",
            "action",
            "portfolio_id_sha256",
            "product_id",
            "operator_identity_sha256",
            "previous_record_sha256",
            "record_sha256",
            "position_snapshot_sha256",
            "market_snapshot_sha256",
            "dependency_evidence_sha256",
            "outcome",
            "reason_code",
            "exchange_order_id_sha256",
        }
        if set(value) != expected:
            raise Slice3ClaimError("slice3_claim_record_shape_invalid")
        outcome_value = value["outcome"]
        if (
            not isinstance(value["schema_version"], str)
            or not isinstance(value["event"], str)
            or not isinstance(value["recorded_at"], str)
            or not isinstance(value["semantic_key"], str)
            or not isinstance(value["plan_sha256"], str)
            or type(value["action_index"]) is not int
            or not isinstance(value["action"], str)
            or not isinstance(value["portfolio_id_sha256"], str)
            or not isinstance(value["product_id"], str)
            or not isinstance(value["operator_identity_sha256"], str)
            or not isinstance(value["previous_record_sha256"], str)
            or not isinstance(value["record_sha256"], str)
            or any(
                item is not None and not isinstance(item, str)
                for item in (
                    value["position_snapshot_sha256"],
                    value["market_snapshot_sha256"],
                    value["dependency_evidence_sha256"],
                    outcome_value,
                    value["reason_code"],
                    value["exchange_order_id_sha256"],
                )
            )
        ):
            raise Slice3ClaimError("slice3_claim_record_invalid")
        record: Slice3ClaimRecord | None = None
        try:
            record = cls(
                schema_version=value["schema_version"],
                event=Slice3ClaimEvent(value["event"]),
                recorded_at=value["recorded_at"],
                semantic_key=value["semantic_key"],
                plan_sha256=value["plan_sha256"],
                action_index=value["action_index"],
                action=Slice3ActionKind(value["action"]),
                portfolio_id_sha256=value["portfolio_id_sha256"],
                product_id=value["product_id"],
                operator_identity_sha256=value["operator_identity_sha256"],
                previous_record_sha256=value["previous_record_sha256"],
                record_sha256=value["record_sha256"],
                position_snapshot_sha256=value["position_snapshot_sha256"],
                market_snapshot_sha256=value["market_snapshot_sha256"],
                dependency_evidence_sha256=value["dependency_evidence_sha256"],
                outcome=(
                    None
                    if outcome_value is None
                    else Slice3MutationOutcome(outcome_value)
                ),
                reason_code=value["reason_code"],
                exchange_order_id_sha256=value["exchange_order_id_sha256"],
            )
        except (TypeError, ValueError, KeyError):
            pass
        if record is None:
            raise Slice3ClaimError("slice3_claim_record_invalid")
        return record


class FileSlice3ActionClaimStore:
    """Owner-only JSONL log with process-safe, fsynced action boundaries."""

    def __init__(self, path: Path | str | None = None) -> None:
        configured = (
            path
            or os.environ.get("COINBASE_SLICE3_ACTION_CLAIM_LOG_PATH")
            or Path("runtime_state") / "futures_slice3_action_claims.jsonl"
        )
        self.path = Path(configured)
        self._lock = RLock()

    @staticmethod
    def _identity(record: Slice3ClaimRecord) -> tuple[Any, ...]:
        return (
            record.semantic_key,
            record.plan_sha256,
            record.action_index,
            record.action,
            record.portfolio_id_sha256,
            record.product_id,
            record.operator_identity_sha256,
        )

    @staticmethod
    def _record_for_claim(
        claim: Slice3ActionClaim,
        *,
        previous_record_sha256: str,
        event: Slice3ClaimEvent,
        position_snapshot_sha256: str | None = None,
        market_snapshot_sha256: str | None = None,
        dependency_evidence_sha256: str | None = None,
        outcome: Slice3MutationOutcome | None = None,
        reason_code: str | None = None,
        exchange_order_id_sha256: str | None = None,
    ) -> Slice3ClaimRecord:
        provisional = Slice3ClaimRecord(
            event=event,
            recorded_at=datetime.now(timezone.utc).isoformat(),
            semantic_key=claim.semantic_key,
            plan_sha256=claim.plan_sha256,
            action_index=claim.action_index,
            action=claim.action,
            portfolio_id_sha256=claim.portfolio_id_sha256,
            product_id=claim.product_id,
            operator_identity_sha256=claim.operator_identity_sha256,
            previous_record_sha256=previous_record_sha256,
            record_sha256=SLICE3_ACTION_GENESIS_SHA256,
            position_snapshot_sha256=position_snapshot_sha256,
            market_snapshot_sha256=market_snapshot_sha256,
            dependency_evidence_sha256=dependency_evidence_sha256,
            outcome=outcome,
            reason_code=reason_code,
            exchange_order_id_sha256=exchange_order_id_sha256,
        )
        payload = provisional.to_dict()
        del payload["record_sha256"]
        return Slice3ClaimRecord(
            **{
                **provisional.__dict__,
                "record_sha256": _canonical_sha256(payload),
            }
        )

    @staticmethod
    def _validate_records(records: list[Slice3ClaimRecord]) -> None:
        latest: dict[str, Slice3ClaimRecord] = {}
        action_keys: dict[tuple[str, int, Slice3ActionKind], str] = {}
        previous_record_sha256 = SLICE3_ACTION_GENESIS_SHA256
        for record in records:
            if record.schema_version != SLICE3_ACTION_RECORD_SCHEMA_VERSION:
                raise Slice3ClaimError("slice3_claim_record_version_invalid")
            recorded_at: datetime | None = None
            try:
                recorded_at = datetime.fromisoformat(record.recorded_at)
            except (TypeError, ValueError):
                pass
            if recorded_at is None:
                raise Slice3ClaimError("slice3_claim_record_time_invalid")
            validation_error: str | None = None
            try:
                _require_aware(recorded_at, "slice3_claim_record_time_invalid")
                _require_sha256(
                    record.semantic_key,
                    "slice3_claim_semantic_key_invalid",
                )
                _require_sha256(
                    record.plan_sha256,
                    "slice3_claim_plan_sha256_invalid",
                )
                _require_sha256(
                    record.portfolio_id_sha256,
                    "slice3_claim_portfolio_sha256_invalid",
                )
                _require_sha256(
                    record.operator_identity_sha256,
                    "slice3_claim_operator_identity_sha256_invalid",
                )
                _require_sha256(
                    record.previous_record_sha256,
                    "slice3_claim_record_hash_invalid",
                )
                _require_sha256(
                    record.record_sha256,
                    "slice3_claim_record_hash_invalid",
                )
                if record.position_snapshot_sha256 is not None:
                    _require_sha256(
                        record.position_snapshot_sha256,
                        "slice3_claim_position_sha256_invalid",
                    )
                if record.market_snapshot_sha256 is not None:
                    _require_sha256(
                        record.market_snapshot_sha256,
                        "slice3_claim_market_sha256_invalid",
                    )
                if record.dependency_evidence_sha256 is not None:
                    _require_sha256(
                        record.dependency_evidence_sha256,
                        "slice3_claim_dependency_sha256_invalid",
                    )
                if record.exchange_order_id_sha256 is not None:
                    _require_sha256(
                        record.exchange_order_id_sha256,
                        "slice3_claim_exchange_id_sha256_invalid",
                    )
                if record.reason_code is not None:
                    _require_safe_reason(record.reason_code)
            except Slice3PlanError as exc:
                validation_error = str(exc)
            if validation_error is not None:
                raise Slice3ClaimError(validation_error)
            expected_action_index = {
                Slice3ActionKind.CREATE: 1,
                Slice3ActionKind.CANCEL: 2,
                Slice3ActionKind.CLOSE: 3,
            }[record.action]
            if (
                record.action_index != expected_action_index
                or record.product_id != SLICE3_PRODUCT_ID
            ):
                raise Slice3ClaimError("slice3_claim_record_binding_invalid")
            payload = record.to_dict()
            del payload["record_sha256"]
            if (
                record.previous_record_sha256 != previous_record_sha256
                or record.record_sha256 != _canonical_sha256(payload)
            ):
                raise Slice3ClaimError("slice3_claim_record_hash_invalid")
            previous_record_sha256 = record.record_sha256
            identity = (
                record.plan_sha256,
                record.action_index,
                record.action,
            )
            existing_key = action_keys.setdefault(identity, record.semantic_key)
            if existing_key != record.semantic_key:
                raise Slice3ClaimError("slice3_claim_semantic_conflict")
            previous = latest.get(record.semantic_key)
            if previous is not None and (
                FileSlice3ActionClaimStore._identity(previous)
                != FileSlice3ActionClaimStore._identity(record)
            ):
                raise Slice3ClaimError("slice3_claim_identity_drift")

            if record.event is Slice3ClaimEvent.CLAIM:
                valid = bool(
                    previous is None
                    and record.position_snapshot_sha256 is None
                    and record.market_snapshot_sha256 is None
                    and record.dependency_evidence_sha256 is None
                    and record.outcome is None
                    and record.reason_code is None
                    and record.exchange_order_id_sha256 is None
                )
            elif record.event is Slice3ClaimEvent.EVIDENCE_BOUND:
                cancel_binding = bool(
                    record.action is Slice3ActionKind.CANCEL
                    and record.position_snapshot_sha256 is None
                    and record.market_snapshot_sha256 is None
                    and record.exchange_order_id_sha256 is not None
                )
                close_binding = bool(
                    record.action is Slice3ActionKind.CLOSE
                    and record.position_snapshot_sha256 is not None
                    and record.market_snapshot_sha256 is not None
                    and record.exchange_order_id_sha256 is None
                )
                valid = bool(
                    previous is not None
                    and previous.event is Slice3ClaimEvent.CLAIM
                    and record.dependency_evidence_sha256 is not None
                    and record.outcome is None
                    and record.reason_code is None
                    and (cancel_binding or close_binding)
                )
            elif record.event is Slice3ClaimEvent.RETIRED:
                valid = bool(
                    previous is not None
                    and previous.event is Slice3ClaimEvent.CLAIM
                    and record.position_snapshot_sha256 is None
                    and record.market_snapshot_sha256 is None
                    and record.dependency_evidence_sha256 is not None
                    and record.outcome is None
                    and record.reason_code is not None
                    and record.exchange_order_id_sha256 is None
                )
            elif record.event is Slice3ClaimEvent.EXCHANGE_BOUNDARY:
                expected_previous = (
                    Slice3ClaimEvent.CLAIM
                    if record.action is Slice3ActionKind.CREATE
                    else Slice3ClaimEvent.CLAIM
                )
                if record.action is not Slice3ActionKind.CREATE:
                    expected_previous = Slice3ClaimEvent.EVIDENCE_BOUND
                valid = bool(
                    previous is not None
                    and previous.event is expected_previous
                    and record.position_snapshot_sha256
                    == previous.position_snapshot_sha256
                    and record.market_snapshot_sha256 == previous.market_snapshot_sha256
                    and record.dependency_evidence_sha256
                    == previous.dependency_evidence_sha256
                    and record.outcome is Slice3MutationOutcome.UNKNOWN
                    and record.reason_code
                    == (f"{record.action.value}_exchange_boundary")
                    and record.exchange_order_id_sha256
                    == previous.exchange_order_id_sha256
                )
            else:
                before_boundary_rejection = bool(
                    previous is not None
                    and previous.event
                    in {Slice3ClaimEvent.CLAIM, Slice3ClaimEvent.EVIDENCE_BOUND}
                    and record.outcome is Slice3MutationOutcome.REJECTED
                )
                after_boundary = bool(
                    previous is not None
                    and previous.event is Slice3ClaimEvent.EXCHANGE_BOUNDARY
                )
                valid = bool(
                    (before_boundary_rejection or after_boundary)
                    and record.position_snapshot_sha256
                    == previous.position_snapshot_sha256
                    and record.market_snapshot_sha256 == previous.market_snapshot_sha256
                    and record.dependency_evidence_sha256
                    == previous.dependency_evidence_sha256
                    and record.outcome is not None
                    and record.reason_code is not None
                )
            if not valid:
                raise Slice3ClaimError("slice3_claim_sequence_invalid")
            latest[record.semantic_key] = record

    @staticmethod
    def _unique_json_object(
        pairs: list[tuple[str, Any]],
    ) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise Slice3ClaimError("slice3_claim_log_duplicate_key")
            value[key] = item
        return value

    @staticmethod
    def _parse(raw: bytes) -> list[Slice3ClaimRecord]:
        if raw and not raw.endswith(b"\n"):
            raise Slice3ClaimError("slice3_claim_log_truncated")
        decoded: str | None = None
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError:
            pass
        if decoded is None:
            raise Slice3ClaimError("slice3_claim_log_not_utf8")
        records: list[Slice3ClaimRecord] = []
        for line in decoded.splitlines():
            if not line:
                raise Slice3ClaimError("slice3_claim_log_blank_row")
            value: Any = None
            malformed = False
            try:
                value = json.loads(
                    line,
                    object_pairs_hook=(FileSlice3ActionClaimStore._unique_json_object),
                )
            except (ValueError, RecursionError):
                malformed = True
            if malformed:
                raise Slice3ClaimError("slice3_claim_log_malformed")
            if not isinstance(value, dict):
                raise Slice3ClaimError("slice3_claim_log_row_invalid")
            records.append(Slice3ClaimRecord.from_dict(value))
        FileSlice3ActionClaimStore._validate_records(records)
        return records

    def _ensure_safe_parent(self, *, create_missing: bool) -> bool:
        parent = Path(os.path.abspath(self.path.parent))
        components = list(reversed((parent, *parent.parents)))
        for component in components:
            metadata: os.stat_result | None = None
            lstat_failed = False
            try:
                metadata = os.lstat(component)
            except FileNotFoundError:
                pass
            except (OSError, ValueError):
                lstat_failed = True
            if lstat_failed:
                raise Slice3ClaimError("slice3_claim_log_unsafe")
            if metadata is None:
                if not create_missing:
                    return False
                mkdir_failed = False
                try:
                    os.mkdir(component, 0o700)
                except FileExistsError:
                    pass
                except (OSError, ValueError):
                    mkdir_failed = True
                if mkdir_failed:
                    raise Slice3ClaimError("slice3_claim_log_unsafe")
                lstat_failed = False
                try:
                    metadata = os.lstat(component)
                except (OSError, ValueError):
                    lstat_failed = True
                if lstat_failed:
                    raise Slice3ClaimError("slice3_claim_log_unsafe")
            if metadata is None or not stat.S_ISDIR(metadata.st_mode):
                raise Slice3ClaimError("slice3_claim_log_unsafe")
        return True

    @staticmethod
    def _metadata_is_safe(metadata: os.stat_result) -> bool:
        return bool(
            stat.S_ISREG(metadata.st_mode)
            and metadata.st_uid == os.getuid()
            and stat.S_IMODE(metadata.st_mode) == 0o600
            and metadata.st_nlink == 1
            and metadata.st_size <= SLICE3_MAX_CLAIM_FILE_BYTES
        )

    def _existing_path_metadata(self) -> os.stat_result | None:
        failed = False
        try:
            return os.lstat(self.path)
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            failed = True
        if failed:
            raise Slice3ClaimError("slice3_claim_log_unsafe")
        return None

    @staticmethod
    def _descriptor_metadata(descriptor: int) -> os.stat_result:
        metadata: os.stat_result | None = None
        try:
            metadata = os.fstat(descriptor)
        except OSError:
            pass
        if metadata is None:
            raise Slice3ClaimError("slice3_claim_log_unsafe")
        return metadata

    def _assert_descriptor_path_safe(self, descriptor: int) -> None:
        descriptor_metadata = self._descriptor_metadata(descriptor)
        path_metadata = self._existing_path_metadata()
        if (
            path_metadata is None
            or not self._metadata_is_safe(descriptor_metadata)
            or not self._metadata_is_safe(path_metadata)
            or descriptor_metadata.st_dev != path_metadata.st_dev
            or descriptor_metadata.st_ino != path_metadata.st_ino
        ):
            raise Slice3ClaimError("slice3_claim_log_unsafe")

    def _open(self) -> int:
        self._ensure_safe_parent(create_missing=True)
        existing = self._existing_path_metadata()
        if existing is not None and not self._metadata_is_safe(existing):
            raise Slice3ClaimError("slice3_claim_log_unsafe")
        flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor: int | None = None
        try:
            descriptor = os.open(self.path, flags, 0o600)
        except (OSError, ValueError):
            pass
        if descriptor is None:
            raise Slice3ClaimError("slice3_claim_log_unsafe")
        try:
            self._assert_descriptor_path_safe(descriptor)
        except Slice3ClaimError:
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise
        return descriptor

    def _read_locked(self, descriptor: int) -> list[Slice3ClaimRecord]:
        self._assert_descriptor_path_safe(descriptor)
        before = self._descriptor_metadata(descriptor)
        if before.st_size > SLICE3_MAX_CLAIM_FILE_BYTES:
            raise Slice3ClaimError("slice3_claim_log_too_large")
        chunks: list[bytes] = []
        read_failed = False
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            remaining = before.st_size
            while remaining:
                chunk = os.read(descriptor, min(remaining, 131_072))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
        except OSError:
            read_failed = True
        if read_failed:
            raise Slice3ClaimError("slice3_claim_log_read_failed")
        raw = b"".join(chunks)
        after = self._descriptor_metadata(descriptor)
        self._assert_descriptor_path_safe(descriptor)
        if (
            len(raw) != before.st_size
            or after.st_size != before.st_size
            or after.st_dev != before.st_dev
            or after.st_ino != before.st_ino
        ):
            raise Slice3ClaimError("slice3_claim_log_size_changed")
        return self._parse(raw)

    def _append_locked(
        self,
        descriptor: int,
        record: Slice3ClaimRecord,
    ) -> None:
        self._assert_descriptor_path_safe(descriptor)
        encoded = (
            json.dumps(
                record.to_dict(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            )
            + "\n"
        ).encode("utf-8")
        metadata = self._descriptor_metadata(descriptor)
        if metadata.st_size + len(encoded) > SLICE3_MAX_CLAIM_FILE_BYTES:
            raise Slice3ClaimError("slice3_claim_log_too_large")
        offset = 0
        write_failed = False
        try:
            while offset < len(encoded):
                written = os.write(descriptor, encoded[offset:])
                if written <= 0:
                    break
                offset += written
        except OSError:
            write_failed = True
        if write_failed:
            raise Slice3ClaimError("slice3_claim_log_write_failed")
        if offset != len(encoded):
            raise Slice3ClaimError("slice3_claim_log_short_write")
        fsync_failed = False
        try:
            os.fsync(descriptor)
        except OSError:
            fsync_failed = True
        if fsync_failed:
            raise Slice3ClaimError("slice3_claim_log_write_failed")
        self._assert_descriptor_path_safe(descriptor)
        if not self._ensure_safe_parent(create_missing=False):
            raise Slice3ClaimError("slice3_claim_log_unsafe")
        directory_flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_DIRECTORY"):
            directory_flags |= os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            directory_flags |= os.O_NOFOLLOW
        directory: int | None = None
        try:
            directory = os.open(self.path.parent, directory_flags)
        except (OSError, ValueError):
            pass
        if directory is None:
            raise Slice3ClaimError("slice3_claim_log_unsafe")
        directory_fsync_failed = False
        try:
            os.fsync(directory)
        except OSError:
            directory_fsync_failed = True
        finally:
            try:
                os.close(directory)
            except OSError:
                pass
        if directory_fsync_failed:
            raise Slice3ClaimError("slice3_claim_log_write_failed")
        self._assert_descriptor_path_safe(descriptor)

    @staticmethod
    def _flock_descriptor(descriptor: int, operation: int) -> None:
        failed = False
        try:
            fcntl.flock(descriptor, operation)
        except OSError:
            failed = True
        if failed:
            raise Slice3ClaimError("slice3_claim_log_lock_failed")

    @staticmethod
    def _unlock_and_close(descriptor: int, *, locked: bool) -> None:
        if locked:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
        try:
            os.close(descriptor)
        except OSError:
            pass

    def _with_exclusive(
        self,
        operation: Callable[
            [int, list[Slice3ClaimRecord]],
            Slice3ClaimRecord | tuple[Slice3ClaimDecision, Slice3ClaimRecord],
        ],
    ) -> Slice3ClaimRecord | tuple[Slice3ClaimDecision, Slice3ClaimRecord]:
        with self._lock:
            descriptor = self._open()
            locked = False
            try:
                self._flock_descriptor(descriptor, fcntl.LOCK_EX)
                locked = True
                self._assert_descriptor_path_safe(descriptor)
                records = self._read_locked(descriptor)
                self._assert_descriptor_path_safe(descriptor)
                result = operation(descriptor, records)
                self._assert_descriptor_path_safe(descriptor)
                return result
            finally:
                self._unlock_and_close(descriptor, locked=locked)

    def claim(
        self,
        claim: Slice3ActionClaim,
    ) -> tuple[Slice3ClaimDecision, Slice3ClaimRecord]:
        claim.validate()

        def operation(
            descriptor: int,
            records: list[Slice3ClaimRecord],
        ) -> tuple[Slice3ClaimDecision, Slice3ClaimRecord]:
            matching = [
                record
                for record in records
                if record.semantic_key == claim.semantic_key
            ]
            if matching:
                return Slice3ClaimDecision.EXISTS, matching[-1]
            for record in records:
                if (
                    record.plan_sha256 == claim.plan_sha256
                    and record.action_index == claim.action_index
                    and record.action is claim.action
                ):
                    raise Slice3ClaimError("slice3_claim_semantic_conflict")
            record = self._record_for_claim(
                claim,
                previous_record_sha256=(
                    records[-1].record_sha256
                    if records
                    else SLICE3_ACTION_GENESIS_SHA256
                ),
                event=Slice3ClaimEvent.CLAIM,
            )
            self._append_locked(descriptor, record)
            return Slice3ClaimDecision.CLAIMED, record

        result = self._with_exclusive(operation)
        assert isinstance(result, tuple)
        return result

    def inspect(self, claim: Slice3ActionClaim) -> Slice3ClaimRecord | None:
        claim.validate()
        matching = [
            record
            for record in self.read_all()
            if record.semantic_key == claim.semantic_key
        ]
        return matching[-1] if matching else None

    def bind_cancel_evidence(
        self,
        claim: Slice3ActionClaim,
        *,
        exchange_order_id_sha256: str,
        dependency_evidence_sha256: str,
    ) -> Slice3ClaimRecord:
        if claim.action is not Slice3ActionKind.CANCEL:
            raise Slice3ClaimError("slice3_cancel_binding_non_cancel")
        try:
            _require_sha256(
                exchange_order_id_sha256,
                "slice3_claim_exchange_id_sha256_invalid",
            )
            _require_sha256(
                dependency_evidence_sha256,
                "slice3_claim_dependency_sha256_invalid",
            )
        except Slice3PlanError as exc:
            raise Slice3ClaimError(str(exc)) from None

        def operation(
            descriptor: int,
            records: list[Slice3ClaimRecord],
        ) -> Slice3ClaimRecord:
            matching = [
                record
                for record in records
                if record.semantic_key == claim.semantic_key
            ]
            if not matching or matching[-1].event is not Slice3ClaimEvent.CLAIM:
                raise Slice3ClaimError(
                    "slice3_cancel_claim_missing_or_already_consumed"
                )
            record = self._record_for_claim(
                claim,
                previous_record_sha256=(
                    records[-1].record_sha256
                    if records
                    else SLICE3_ACTION_GENESIS_SHA256
                ),
                event=Slice3ClaimEvent.EVIDENCE_BOUND,
                exchange_order_id_sha256=exchange_order_id_sha256,
                dependency_evidence_sha256=dependency_evidence_sha256,
            )
            self._append_locked(descriptor, record)
            return record

        result = self._with_exclusive(operation)
        assert isinstance(result, Slice3ClaimRecord)
        return result

    def bind_close_evidence(
        self,
        claim: Slice3ActionClaim,
        *,
        position_snapshot_sha256: str,
        market_snapshot_sha256: str,
        dependency_evidence_sha256: str,
    ) -> Slice3ClaimRecord:
        if claim.action is not Slice3ActionKind.CLOSE:
            raise Slice3ClaimError("slice3_close_binding_non_close")
        try:
            _require_sha256(
                position_snapshot_sha256,
                "slice3_claim_position_sha256_invalid",
            )
            _require_sha256(
                market_snapshot_sha256,
                "slice3_claim_market_sha256_invalid",
            )
            _require_sha256(
                dependency_evidence_sha256,
                "slice3_claim_dependency_sha256_invalid",
            )
        except Slice3PlanError as exc:
            raise Slice3ClaimError(str(exc)) from None

        def operation(
            descriptor: int,
            records: list[Slice3ClaimRecord],
        ) -> Slice3ClaimRecord:
            matching = [
                record
                for record in records
                if record.semantic_key == claim.semantic_key
            ]
            if not matching or matching[-1].event is not Slice3ClaimEvent.CLAIM:
                raise Slice3ClaimError("slice3_close_claim_missing_or_already_consumed")
            record = self._record_for_claim(
                claim,
                previous_record_sha256=(
                    records[-1].record_sha256
                    if records
                    else SLICE3_ACTION_GENESIS_SHA256
                ),
                event=Slice3ClaimEvent.EVIDENCE_BOUND,
                position_snapshot_sha256=position_snapshot_sha256,
                market_snapshot_sha256=market_snapshot_sha256,
                dependency_evidence_sha256=dependency_evidence_sha256,
            )
            self._append_locked(descriptor, record)
            return record

        result = self._with_exclusive(operation)
        assert isinstance(result, Slice3ClaimRecord)
        return result

    def mark_exchange_boundary(
        self,
        claim: Slice3ActionClaim,
    ) -> Slice3ClaimRecord:
        def operation(
            descriptor: int,
            records: list[Slice3ClaimRecord],
        ) -> Slice3ClaimRecord:
            matching = [
                record
                for record in records
                if record.semantic_key == claim.semantic_key
            ]
            expected = (
                Slice3ClaimEvent.CLAIM
                if claim.action is Slice3ActionKind.CREATE
                else Slice3ClaimEvent.EVIDENCE_BOUND
            )
            if not matching or matching[-1].event is not expected:
                raise Slice3ClaimError("slice3_claim_already_consumed")
            previous = matching[-1]
            record = self._record_for_claim(
                claim,
                previous_record_sha256=(
                    records[-1].record_sha256
                    if records
                    else SLICE3_ACTION_GENESIS_SHA256
                ),
                event=Slice3ClaimEvent.EXCHANGE_BOUNDARY,
                position_snapshot_sha256=previous.position_snapshot_sha256,
                market_snapshot_sha256=previous.market_snapshot_sha256,
                dependency_evidence_sha256=(previous.dependency_evidence_sha256),
                outcome=Slice3MutationOutcome.UNKNOWN,
                reason_code=f"{claim.action.value}_exchange_boundary",
                exchange_order_id_sha256=(previous.exchange_order_id_sha256),
            )
            self._append_locked(descriptor, record)
            return record

        result = self._with_exclusive(operation)
        assert isinstance(result, Slice3ClaimRecord)
        return result

    def recover_boundary_as_unknown(
        self,
        claim: Slice3ActionClaim,
    ) -> Slice3ClaimRecord:
        """Terminalize a crash-left exchange boundary without another call."""

        claim.validate()
        reason_code = f"{claim.action.value}_process_interrupted"

        def operation(
            descriptor: int,
            records: list[Slice3ClaimRecord],
        ) -> Slice3ClaimRecord:
            matching = [
                record
                for record in records
                if record.semantic_key == claim.semantic_key
            ]
            if not matching:
                raise Slice3ClaimError("slice3_claim_boundary_missing")
            previous = matching[-1]
            if previous.event is Slice3ClaimEvent.OUTCOME:
                if (
                    previous.outcome is Slice3MutationOutcome.UNKNOWN
                    and previous.reason_code == reason_code
                ):
                    return previous
                raise Slice3ClaimError("slice3_claim_already_consumed")
            if not (
                previous.event is Slice3ClaimEvent.EXCHANGE_BOUNDARY
                and previous.outcome is Slice3MutationOutcome.UNKNOWN
            ):
                raise Slice3ClaimError("slice3_claim_boundary_missing")
            record = self._record_for_claim(
                claim,
                previous_record_sha256=records[-1].record_sha256,
                event=Slice3ClaimEvent.OUTCOME,
                position_snapshot_sha256=previous.position_snapshot_sha256,
                market_snapshot_sha256=previous.market_snapshot_sha256,
                dependency_evidence_sha256=(previous.dependency_evidence_sha256),
                outcome=Slice3MutationOutcome.UNKNOWN,
                reason_code=reason_code,
                exchange_order_id_sha256=None,
            )
            self._append_locked(descriptor, record)
            return record

        result = self._with_exclusive(operation)
        assert isinstance(result, Slice3ClaimRecord)
        return result

    def retire_unused(
        self,
        claim: Slice3ActionClaim,
        *,
        reason_code: str,
        dependency_evidence_sha256: str,
    ) -> Slice3ClaimRecord:
        """Terminally consume an action proved unnecessary before boundary."""

        _require_safe_reason(reason_code)
        try:
            _require_sha256(
                dependency_evidence_sha256,
                "slice3_claim_dependency_sha256_invalid",
            )
        except Slice3PlanError as exc:
            raise Slice3ClaimError(str(exc)) from None

        def operation(
            descriptor: int,
            records: list[Slice3ClaimRecord],
        ) -> Slice3ClaimRecord:
            matching = [
                record
                for record in records
                if record.semantic_key == claim.semantic_key
            ]
            if not matching or matching[-1].event is not Slice3ClaimEvent.CLAIM:
                raise Slice3ClaimError("slice3_claim_already_consumed")
            record = self._record_for_claim(
                claim,
                previous_record_sha256=(
                    records[-1].record_sha256
                    if records
                    else SLICE3_ACTION_GENESIS_SHA256
                ),
                event=Slice3ClaimEvent.RETIRED,
                dependency_evidence_sha256=dependency_evidence_sha256,
                reason_code=reason_code,
            )
            self._append_locked(descriptor, record)
            return record

        result = self._with_exclusive(operation)
        assert isinstance(result, Slice3ClaimRecord)
        return result

    def reject_before_boundary(
        self,
        claim: Slice3ActionClaim,
        *,
        reason_code: str,
    ) -> Slice3ClaimRecord:
        _require_safe_reason(reason_code)

        def operation(
            descriptor: int,
            records: list[Slice3ClaimRecord],
        ) -> Slice3ClaimRecord:
            matching = [
                record
                for record in records
                if record.semantic_key == claim.semantic_key
            ]
            if not matching or matching[-1].event not in {
                Slice3ClaimEvent.CLAIM,
                Slice3ClaimEvent.EVIDENCE_BOUND,
            }:
                raise Slice3ClaimError("slice3_claim_already_consumed")
            previous = matching[-1]
            record = self._record_for_claim(
                claim,
                previous_record_sha256=(
                    records[-1].record_sha256
                    if records
                    else SLICE3_ACTION_GENESIS_SHA256
                ),
                event=Slice3ClaimEvent.OUTCOME,
                position_snapshot_sha256=previous.position_snapshot_sha256,
                market_snapshot_sha256=previous.market_snapshot_sha256,
                dependency_evidence_sha256=(previous.dependency_evidence_sha256),
                outcome=Slice3MutationOutcome.REJECTED,
                reason_code=reason_code,
                exchange_order_id_sha256=(previous.exchange_order_id_sha256),
            )
            self._append_locked(descriptor, record)
            return record

        result = self._with_exclusive(operation)
        assert isinstance(result, Slice3ClaimRecord)
        return result

    def complete(
        self,
        claim: Slice3ActionClaim,
        result: Slice3MutationResult,
    ) -> Slice3ClaimRecord:
        if not isinstance(result, Slice3MutationResult):
            raise Slice3ClaimError("slice3_claim_result_invalid")

        def operation(
            descriptor: int,
            records: list[Slice3ClaimRecord],
        ) -> Slice3ClaimRecord:
            matching = [
                record
                for record in records
                if record.semantic_key == claim.semantic_key
            ]
            if not matching or (
                matching[-1].event is not Slice3ClaimEvent.EXCHANGE_BOUNDARY
            ):
                raise Slice3ClaimError("slice3_claim_boundary_missing")
            previous = matching[-1]
            record = self._record_for_claim(
                claim,
                previous_record_sha256=(
                    records[-1].record_sha256
                    if records
                    else SLICE3_ACTION_GENESIS_SHA256
                ),
                event=Slice3ClaimEvent.OUTCOME,
                position_snapshot_sha256=previous.position_snapshot_sha256,
                market_snapshot_sha256=previous.market_snapshot_sha256,
                dependency_evidence_sha256=(previous.dependency_evidence_sha256),
                outcome=result.outcome,
                reason_code=result.reason_code,
                exchange_order_id_sha256=result.exchange_order_id_sha256,
            )
            self._append_locked(descriptor, record)
            return record

        completed = self._with_exclusive(operation)
        assert isinstance(completed, Slice3ClaimRecord)
        return completed

    def read_all(self) -> list[Slice3ClaimRecord]:
        with self._lock:
            if not self._ensure_safe_parent(create_missing=False):
                return []
            if self._existing_path_metadata() is None:
                return []
            descriptor = self._open()
            locked = False
            try:
                self._flock_descriptor(descriptor, fcntl.LOCK_SH)
                locked = True
                self._assert_descriptor_path_safe(descriptor)
                records = self._read_locked(descriptor)
                self._assert_descriptor_path_safe(descriptor)
                return records
            finally:
                self._unlock_and_close(descriptor, locked=locked)


class Slice3MutationPort(Protocol):
    """Narrow injected capability; implementations live outside this module."""

    def create_order(self, **kwargs: object) -> Slice3MutationResult:
        """Submit the one exact Preview-bound Create."""

    def cancel_order(self, **kwargs: object) -> Slice3MutationResult:
        """Submit one cancellation using a verified exchange identifier."""

    def close_position(self, **kwargs: object) -> Slice3MutationResult:
        """Submit one exact-delta close from fresh position evidence."""


class Slice3MutationGate:
    """Claimed one-call seam; no actual Coinbase implementation is included."""

    def __init__(self, store: FileSlice3ActionClaimStore) -> None:
        self.store = store

    @staticmethod
    def _require_live_policy(plan: Slice3Plan) -> None:
        if plan.policy != SLICE3_LIVE_POLICY:
            raise Slice3MutationBlocked("slice3_live_policy_not_bound")

    def reserve_action_claims(
        self,
        plan: Slice3Plan,
        *,
        now: datetime,
    ) -> dict[Slice3ActionKind, Slice3ClaimRecord]:
        """Reserve Close, conditional Cancel, and Create before client access."""

        self._require_live_policy(plan)
        plan.validate_at(now)
        reserved: dict[Slice3ActionKind, Slice3ClaimRecord] = {}
        for action in (
            Slice3ActionKind.CLOSE,
            Slice3ActionKind.CANCEL,
            Slice3ActionKind.CREATE,
        ):
            claim = plan.action_claim(action)
            decision, record = self.store.claim(claim)
            if decision is Slice3ClaimDecision.EXISTS and (
                record.event is not Slice3ClaimEvent.CLAIM
            ):
                raise Slice3MutationBlocked(f"slice3_{action.value}_claim_consumed")
            reserved[action] = record
        return reserved

    def _require_reserved(
        self,
        plan: Slice3Plan,
        action: Slice3ActionKind,
    ) -> Slice3ActionClaim:
        claim = plan.action_claim(action)
        record = self.store.inspect(claim)
        if record is None or record.event is not Slice3ClaimEvent.CLAIM:
            if action is Slice3ActionKind.CLOSE:
                raise Slice3MutationBlocked("slice3_close_claim_not_preclaimed")
            raise Slice3MutationBlocked(f"slice3_{action.value}_claim_consumed")
        return claim

    def _construct_port(
        self,
        *,
        claim: Slice3ActionClaim,
        port_factory: Callable[[], Slice3MutationPort],
    ) -> Slice3MutationPort:
        try:
            return port_factory()
        except Exception:
            self.store.reject_before_boundary(
                claim,
                reason_code=(f"{claim.action.value}_client_construction_failed"),
            )
            raise Slice3MutationBlocked(
                f"slice3_{claim.action.value}_client_construction_failed"
            ) from None

    def _require_terminal_action(
        self,
        plan: Slice3Plan,
        action: Slice3ActionKind,
    ) -> Slice3ClaimRecord:
        record = self.store.inspect(plan.action_claim(action))
        if (
            record is None
            or record.event is not Slice3ClaimEvent.OUTCOME
            or record.outcome is None
        ):
            raise Slice3MutationBlocked(
                f"slice3_{action.value}_terminal_dependency_missing"
            )
        return record

    @staticmethod
    def _validate_opening_order_identity(
        record: Slice3ClaimRecord,
        order: Slice3OrderObservation,
    ) -> None:
        if record.exchange_order_id_sha256 is None:
            return
        if (
            order.exchange_order_id is None
            or _private_sha256(order.exchange_order_id)
            != record.exchange_order_id_sha256
        ):
            raise Slice3MutationBlocked(
                "slice3_opening_order_exchange_identity_mismatch"
            )

    def _invoke_after_boundary(
        self,
        *,
        claim: Slice3ActionClaim,
        invoke: Callable[[], Slice3MutationResult],
    ) -> Slice3MutationResult:
        self.store.mark_exchange_boundary(claim)
        try:
            result = invoke()
            if not isinstance(result, Slice3MutationResult):
                raise TypeError("sanitized Slice3MutationResult required")
        except Exception:
            result = Slice3MutationResult(
                outcome=Slice3MutationOutcome.UNKNOWN,
                reason_code=f"{claim.action.value}_outcome_unknown",
            )
        self.store.complete(claim, result)
        return result

    def execute_create(
        self,
        plan: Slice3Plan,
        *,
        pre_create: Slice3PreCreateEvidence,
        port_factory: Callable[[], Slice3MutationPort],
        now: datetime,
    ) -> Slice3MutationResult:
        self._require_live_policy(plan)
        plan.validate_at(now)
        pre_create.validate(plan, now=now)
        for action in (
            Slice3ActionKind.CLOSE,
            Slice3ActionKind.CANCEL,
            Slice3ActionKind.CREATE,
        ):
            self._require_reserved(plan, action)
        claim = plan.action_claim(Slice3ActionKind.CREATE)
        port = self._construct_port(claim=claim, port_factory=port_factory)
        return self._invoke_after_boundary(
            claim=claim,
            invoke=lambda: port.create_order(
                client_order_id=plan.create.client_order_id,
                product_id=plan.create.product_id,
                side=plan.create.side.value,
                order_configuration=plan.create.preview_request()[
                    "order_configuration"
                ],
                preview_id=plan.create.preview_id,
            ),
        )

    def execute_cancel(
        self,
        plan: Slice3Plan,
        *,
        order: Slice3OrderObservation,
        position: Slice3PositionObservation,
        port_factory: Callable[[], Slice3MutationPort],
        now: datetime,
    ) -> Slice3MutationResult:
        self._require_live_policy(plan)
        plan.validate_risk_off_at(now)
        create_record = self._require_terminal_action(
            plan,
            Slice3ActionKind.CREATE,
        )
        self._validate_opening_order_identity(create_record, order)
        directive = decide_slice3_next_action(
            plan,
            order=order,
            position=position,
            now=now,
            create_outcome=create_record.outcome,
        )
        if directive.kind not in {
            Slice3DirectiveKind.CANCEL_OPEN,
            Slice3DirectiveKind.CANCEL_RESIDUAL,
        }:
            raise Slice3MutationBlocked("slice3_cancel_directive_invalid")
        if directive.exchange_order_id is None:
            raise Slice3MutationBlocked("slice3_cancel_exchange_identity_missing")
        try:
            _require_private_identifier(
                directive.exchange_order_id,
                "slice3_cancel_exchange_identity_invalid",
            )
        except Slice3PlanError as exc:
            raise Slice3MutationBlocked(str(exc)) from None
        claim = self._require_reserved(plan, Slice3ActionKind.CANCEL)
        dependency_evidence_sha256 = _canonical_sha256(
            {
                "schema_version": "slice3-cancel-dependency-v1",
                "plan_sha256": plan.plan_sha256,
                "create_claim_outcome": create_record.to_dict(),
                "order": order.sanitized_evidence(),
                "position": position.sanitized_evidence(),
                "directive": directive.sanitized_evidence(),
            }
        )
        self.store.bind_cancel_evidence(
            claim,
            exchange_order_id_sha256=_private_sha256(directive.exchange_order_id),
            dependency_evidence_sha256=dependency_evidence_sha256,
        )
        port = self._construct_port(claim=claim, port_factory=port_factory)
        return self._invoke_after_boundary(
            claim=claim,
            invoke=lambda: port.cancel_order(
                client_order_id=plan.create.client_order_id,
                verified_exchange_order_id=directive.exchange_order_id,
            ),
        )

    def _validate_close_caps(
        self,
        plan: Slice3Plan,
        *,
        directive: Slice3Directive,
        position: Slice3PositionObservation,
        market: Slice3MarketReference,
        now: datetime,
    ) -> Decimal:
        try:
            position.validate(plan, now=now)
        except Slice3PlanError as exc:
            raise Slice3MutationBlocked(str(exc)) from None
        market.validate(plan, now=now)
        if directive.kind is not Slice3DirectiveKind.CLOSE_EXACT_DELTA:
            raise Slice3MutationBlocked("slice3_close_directive_invalid")
        if directive.close_contracts is None or (
            directive.close_contracts != position.contract_delta
        ):
            raise Slice3MutationBlocked("slice3_close_delta_mismatch")
        reference = max(position.reference or Decimal("0"), market.reference)
        exposure = reference * plan.contract_size * position.contract_delta
        buffered_close = exposure * SLICE3_CLOSE_BUFFER
        turnover = plan.caps.opening + buffered_close
        if exposure >= SLICE3_EXPOSURE_CAP_USDC:
            raise Slice3MutationBlocked("slice3_exposure_cap_invalid")
        if buffered_close >= SLICE3_EXPOSURE_CAP_USDC:
            raise Slice3MutationBlocked("slice3_close_cap_invalid")
        if turnover >= SLICE3_TURNOVER_CAP_USDC:
            raise Slice3MutationBlocked("slice3_turnover_cap_invalid")
        return position.contract_delta

    def execute_close(
        self,
        plan: Slice3Plan,
        *,
        order: Slice3OrderObservation,
        position: Slice3PositionObservation,
        market: Slice3MarketReference,
        open_orders: Slice3OpenOrderZeroProof,
        port_factory: Callable[[], Slice3MutationPort],
        now: datetime,
    ) -> Slice3MutationResult:
        self._require_live_policy(plan)
        plan.validate_risk_off_at(now)
        create_record = self._require_terminal_action(
            plan,
            Slice3ActionKind.CREATE,
        )
        self._validate_opening_order_identity(create_record, order)
        directive = decide_slice3_next_action(
            plan,
            order=order,
            position=position,
            now=now,
            create_outcome=create_record.outcome,
        )
        cancel_record = self.store.inspect(plan.action_claim(Slice3ActionKind.CANCEL))
        if order.status in {OrderStatus.CANCELLED, OrderStatus.EXPIRED}:
            if (
                cancel_record is None
                or cancel_record.event is not Slice3ClaimEvent.OUTCOME
                or cancel_record.outcome is None
            ):
                raise Slice3MutationBlocked("slice3_cancel_terminal_dependency_missing")
        elif cancel_record is not None and cancel_record.event not in {
            Slice3ClaimEvent.CLAIM,
            Slice3ClaimEvent.OUTCOME,
        }:
            raise Slice3MutationBlocked("slice3_cancel_terminal_dependency_incomplete")
        open_orders.validate(plan, now=now)
        delta = self._validate_close_caps(
            plan,
            directive=directive,
            position=position,
            market=market,
            now=now,
        )
        claim = self._require_reserved(plan, Slice3ActionKind.CLOSE)
        dependency_evidence_sha256 = _canonical_sha256(
            {
                "schema_version": "slice3-close-dependency-v1",
                "plan_sha256": plan.plan_sha256,
                "create_claim_outcome": create_record.to_dict(),
                "cancel_claim_outcome": (
                    cancel_record.to_dict()
                    if cancel_record is not None
                    and cancel_record.event is Slice3ClaimEvent.OUTCOME
                    else None
                ),
                "order": order.sanitized_evidence(),
                "position": position.sanitized_evidence(),
                "market": market.sanitized_evidence(),
                "open_orders": open_orders.sanitized_evidence(),
                "directive": directive.sanitized_evidence(),
            }
        )
        self.store.bind_close_evidence(
            claim,
            position_snapshot_sha256=position.snapshot_sha256,
            market_snapshot_sha256=market.snapshot_sha256,
            dependency_evidence_sha256=dependency_evidence_sha256,
        )
        port = self._construct_port(claim=claim, port_factory=port_factory)
        return self._invoke_after_boundary(
            claim=claim,
            invoke=lambda: port.close_position(
                client_order_id=plan.close_client_order_id,
                product_id=plan.create.product_id,
                size=_decimal_text(delta),
            ),
        )


__all__ = [
    "SLICE3_LIVE_POLICY",
    "SLICE3_POLICY",
    "SLICE3_PRODUCT_ID",
    "FileSlice3ActionClaimStore",
    "Slice3AcceptedPreview",
    "Slice3ActionKind",
    "Slice3CapEvidence",
    "Slice3ClaimDecision",
    "Slice3ClaimError",
    "Slice3ClaimEvent",
    "Slice3CreateRequest",
    "Slice3Directive",
    "Slice3DirectiveKind",
    "Slice3ExecutionAuthority",
    "Slice3MarginWindowEvidence",
    "Slice3MarketReference",
    "Slice3MutationBlocked",
    "Slice3MutationGate",
    "Slice3MutationOutcome",
    "Slice3MutationPort",
    "Slice3MutationResult",
    "Slice3OrderObservation",
    "Slice3OrderResolutionSource",
    "Slice3OpenOrderZeroProof",
    "Slice3Plan",
    "Slice3PlanError",
    "Slice3PolicyError",
    "Slice3PortfolioBinding",
    "Slice3PositionObservation",
    "Slice3PreCreateEvidence",
    "Slice3ReadBudget",
    "Slice3ReadSlot",
    "Slice3TerminalEvidence",
    "decide_slice3_next_action",
    "initial_slice3_directive",
]
