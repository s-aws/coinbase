"""Backend-owned Spot recovery policy and operator workflow contracts.

The policy in this module consumes only sanitized exact-order and fill
evidence.  Coinbase response objects, response bodies, exception messages, and
exchange-native identifiers are intentionally outside these contracts.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.enums import (
    AdminApiCommandStatus,
    AdminApiPermission,
    OrderOwnershipProvenance,
    OrderStatus,
    SpotRecoveryAction,
    SpotRecoveryCaseState,
    SpotRecoveryPlanKind,
)


_SYSTEM_OWNED_PROVENANCE = frozenset(
    {
        OrderOwnershipProvenance.ADMIN_MANUAL_ROOT,
        OrderOwnershipProvenance.ADMIN_AUTOMATION_ROOT,
        OrderOwnershipProvenance.ADMIN_FILL_FOLLOW_UP,
    }
)
_TERMINAL_STATUSES = frozenset(
    {
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.EXPIRED,
        OrderStatus.FAILED,
    }
)
_ACTIVE_STATUSES = frozenset(
    {
        OrderStatus.PENDING,
        OrderStatus.SUBMITTED,
        OrderStatus.OPEN,
        OrderStatus.QUEUED,
        OrderStatus.CANCEL_QUEUED,
        OrderStatus.EDIT_QUEUED,
    }
)
_UNKNOWN_STATUSES = frozenset(
    {
        OrderStatus.SUBMISSION_UNKNOWN,
        OrderStatus.CANCELLATION_UNKNOWN,
    }
)
_PUBLIC_EVENT_TYPES = frozenset(
    {
        "CASE_CREATED",
        "REFRESH_CLAIMED",
        "FILL_READ_CLAIMED",
        "REFRESH_COMPLETED",
        "REFRESH_FAILED",
        "PLAN_APPLIED",
        "PLAN_ROLLED_BACK",
        "CANCEL_CLAIMED",
        "CANCEL_TERMINAL",
        "CANCEL_RELEASED_PREBOUNDARY",
    }
)
_PUBLIC_EVENT_EVIDENCE_KEYS = frozenset(
    {
        "revision",
        "refresh_count",
        "order_read_logical_count",
        "fill_read_logical_count",
        "order_read_page_count",
        "fill_read_page_count",
        "state",
        "plan_kind",
        "plan_sha256",
        "diagnostic_code",
        "from_status",
        "to_status",
        "restored_status",
        "cancel_call_count",
        "order_state_mutated",
        "exchange_state_mutated",
        "exchange_mutation_attempted",
        "exchange_mutation_accepted",
    }
)
_PUBLIC_FIXED_VALUE = re.compile(r"^[A-Za-z][A-Za-z0-9._:-]{0,127}$")
_SHA256_VALUE = re.compile(r"^[0-9a-f]{64}$")
_ORDER_READ_DIAGNOSTICS = frozenset(
    {
        "order_read_unavailable",
        "order_read_pagination_limit",
        "order_read_failed",
        "order_read_malformed",
        "order_read_malformed_pagination",
    }
)
_FILL_READ_DIAGNOSTICS = frozenset(
    {
        "fill_read_identity_missing",
        "fill_read_unavailable",
        "fill_read_pagination_limit",
        "fill_read_pagination_incomplete",
        "fill_read_failed",
        "fill_read_normalization_failed",
        "fill_read_malformed",
        "fill_read_malformed_pagination",
        "fill_read_order_identity_mismatch",
        "fill_read_product_identity_mismatch",
    }
)


class OperatorSpotRecoveryError(ValueError):
    """Fixed-code recovery failure that never carries private response text."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class SpotRecoveryLocalOrderEvidence(BaseModel):
    """Allowlisted local ownership and lifecycle evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    client_order_id: str = Field(min_length=1, max_length=40)
    product_id: str = Field(min_length=1, max_length=255)
    side: str = Field(pattern=r"^(BUY|SELL)$")
    status: OrderStatus
    ownership_provenance: OrderOwnershipProvenance
    portfolio_id_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    exchange_order_id_present: bool


class SpotRecoveryOrderEvidence(BaseModel):
    """Value-blind exact-order truth returned by the canonical reader."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    exact_identity_match: bool
    authoritative: bool
    confirmed_absent: bool
    status: OrderStatus | None = None
    page_count: int = Field(ge=1, le=100)


class SpotRecoveryFillEvidence(BaseModel):
    """Sanitized logical fill-catalog result for the selected order."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    authoritative: bool
    fill_count: int = Field(ge=0)
    page_count: int = Field(ge=1, le=200)
    pagination_complete: bool


class SpotRecoveryPlan(BaseModel):
    """Immutable backend disposition for one exact local/exchange snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: SpotRecoveryPlanKind
    client_order_id: str = Field(min_length=1, max_length=40)
    product_id: str = Field(min_length=1, max_length=255)
    from_status: OrderStatus
    to_status: OrderStatus | None = None
    fill_count: int | None = Field(default=None, ge=0)
    apply_available: bool = False
    cancel_available: bool = False
    rollback_after_apply_available: bool = False
    blockers: list[str] = Field(default_factory=list)
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class OperatorSpotRecoveryCaseCreateRequest(BaseModel):
    """Create one local recovery case keyed only by ``client_order_id``."""

    model_config = ConfigDict(extra="forbid")

    client_order_id: str = Field(
        min_length=36,
        max_length=36,
        pattern=(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
            r"[0-9a-f]{4}-[0-9a-f]{12}$"
        ),
    )
    operator_reason: str = Field(min_length=1, max_length=240)


class OperatorSpotRecoveryRefreshRequest(BaseModel):
    """Explicit request for one no-retry logical order/fill refresh cycle."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    manual_live_acknowledgement: bool = False


class OperatorSpotRecoveryLocalActionRequest(BaseModel):
    """Explicit local apply or rollback request."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    operator_reason: str = Field(min_length=1, max_length=240)
    operator_acknowledgement: bool = False


class OperatorSpotRecoveryEventItem(BaseModel):
    """Fixed, sanitized audit readback for one recovery transition."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    case_id: str
    event_type: str
    actor_id: str
    correlation_id: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    recorded_at: str

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, value: str) -> str:
        if value not in _PUBLIC_EVENT_TYPES:
            raise ValueError("recovery_event_type_not_allowlisted")
        return value

    @field_validator("evidence")
    @classmethod
    def validate_evidence(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not set(value).issubset(_PUBLIC_EVENT_EVIDENCE_KEYS):
            raise ValueError("recovery_event_evidence_not_allowlisted")
        for item in value.values():
            if isinstance(item, bool):
                continue
            if isinstance(item, int) and 0 <= item <= 100:
                continue
            if isinstance(item, str) and (
                _PUBLIC_FIXED_VALUE.fullmatch(item)
                or _SHA256_VALUE.fullmatch(item)
            ):
                continue
            raise ValueError("recovery_event_evidence_value_invalid")
        return value


class OperatorSpotRecoveryCaseItem(BaseModel):
    """Normal operator readback for one durable recovery case."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    client_order_id: str
    product_id: str
    portfolio_scope: str = "approved_test_portfolio"
    portfolio_binding_verified: bool = True
    state: SpotRecoveryCaseState
    revision: int = Field(ge=1)
    refresh_count: int = Field(ge=0, le=10)
    refresh_limit: int = 10
    order_read_logical_count: int = Field(ge=0, le=10)
    fill_read_logical_count: int = Field(ge=0, le=10)
    cancel_call_count: int = Field(ge=0, le=1)
    cancel_allowance_consumed: bool
    plan: SpotRecoveryPlan | None = None
    diagnostic_code: str
    correlation_id: str
    created_at: str
    updated_at: str
    allowed_actions: list[SpotRecoveryAction] = Field(default_factory=list)
    rollback_safety_detail: str | None = None
    events: list[OperatorSpotRecoveryEventItem] = Field(default_factory=list)
    browser_authority: str = "display_and_forward_only"
    backend_authority: str = "authoritative"
    raw_coinbase_response_exposed: bool = False
    exchange_identifier_exposed: bool = False
    exception_message_exposed: bool = False


class OperatorSpotRecoveryCaseResponse(BaseModel):
    """Accepted, replayed, or rejected recovery command response."""

    model_config = ConfigDict(extra="forbid")

    status: AdminApiCommandStatus
    required_permission: AdminApiPermission
    service_method: str
    message: str
    case: OperatorSpotRecoveryCaseItem | None = None
    correlation_id: str | None = None
    audit_id: str | None = None
    idempotency_key: str | None = None
    replayed: bool = False
    live_coinbase_read_ran: bool = False
    live_coinbase_orders_ran: bool = False
    live_exchange_submitted: bool = False


class OperatorSpotRecoveryCaseListResponse(BaseModel):
    """Paginated backend-owned recovery case list."""

    model_config = ConfigDict(extra="forbid")

    items: list[OperatorSpotRecoveryCaseItem]
    total_count: int = Field(ge=0)
    returned_count: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    next_offset: int | None = Field(default=None, ge=0)
    live_coinbase_read_ran: bool = False
    live_coinbase_orders_ran: bool = False


def build_spot_recovery_plan(
    *,
    local: SpotRecoveryLocalOrderEvidence,
    order: SpotRecoveryOrderEvidence,
    fills: SpotRecoveryFillEvidence | None,
) -> SpotRecoveryPlan:
    """Derive one immutable, fail-closed recovery plan.

    An exchange order that is absent, ambiguous, or backed by incomplete fill
    pagination is never treated as terminal truth.  Cancellation is classified
    as a safe recovery action only for a system-owned row that is terminal
    locally, active at Coinbase, and has no fill evidence.
    """

    kind = SpotRecoveryPlanKind.BLOCKED
    to_status: OrderStatus | None = None
    apply_available = False
    cancel_available = False
    rollback_after_apply_available = False
    blockers: list[str] = []

    if local.ownership_provenance not in _SYSTEM_OWNED_PROVENANCE:
        blockers.append("order_not_system_owned")
    elif not order.authoritative or not order.exact_identity_match:
        blockers.append(
            "exact_order_truth_absent"
            if order.confirmed_absent
            else "exact_order_truth_ambiguous"
        )
    elif order.status is None:
        blockers.append("exact_order_status_missing")
    elif fills is None:
        blockers.append("exact_fill_truth_missing")
    elif not fills.authoritative or not fills.pagination_complete:
        blockers.append("exact_fill_truth_incomplete")
    elif local.status in _UNKNOWN_STATUSES and order.status not in _TERMINAL_STATUSES:
        blockers.append("unknown_local_outcome_requires_terminal_truth")
    elif local.status == order.status:
        kind = SpotRecoveryPlanKind.NO_CHANGE
    elif order.status in _TERMINAL_STATUSES:
        kind = SpotRecoveryPlanKind.SET_LOCAL_STATUS
        to_status = order.status
        apply_available = True
        rollback_after_apply_available = local.status in _TERMINAL_STATUSES
    elif order.status in _ACTIVE_STATUSES and local.status in _TERMINAL_STATUSES:
        if fills.fill_count:
            blockers.append("active_exchange_order_has_fill_evidence")
        else:
            kind = SpotRecoveryPlanKind.CANCEL_ACTIVE_ORPHAN
            cancel_available = True
    elif order.status in _ACTIVE_STATUSES and local.status in _ACTIVE_STATUSES:
        kind = SpotRecoveryPlanKind.SET_LOCAL_STATUS
        to_status = order.status
        apply_available = True
        rollback_after_apply_available = False
    else:
        blockers.append("unsupported_status_transition")

    payload: dict[str, Any] = {
        "kind": kind.value,
        "client_order_id": local.client_order_id,
        "product_id": local.product_id,
        "from_status": local.status.value,
        "to_status": to_status.value if to_status is not None else None,
        "fill_count": fills.fill_count if fills is not None else None,
        "apply_available": apply_available,
        "cancel_available": cancel_available,
        "rollback_after_apply_available": rollback_after_apply_available,
        "blockers": blockers,
    }
    plan_sha256 = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return SpotRecoveryPlan(**payload, plan_sha256=plan_sha256)


class OperatorSpotRecoveryService:
    """Application coordinator for one exact operator-selected recovery case."""

    def __init__(
        self,
        *,
        repository: Any,
        rest_client: Any,
        rest_client_available: bool,
        configured_portfolio_id: str | None,
    ) -> None:
        self.repository = repository
        self.rest_client = rest_client
        self.rest_client_available = rest_client_available
        self.configured_portfolio_id = str(configured_portfolio_id or "").strip()

    def get_case(self, case_id: str) -> dict[str, Any]:
        case = self.repository.get_case(case_id)
        if not isinstance(case, dict):
            raise OperatorSpotRecoveryError("recovery_case_not_found")
        return case

    def list_cases(
        self,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        return self.repository.list_cases(limit=limit, offset=offset)

    def portfolio_binding_verified(self, case: dict[str, Any]) -> bool:
        configured_id = self.configured_portfolio_id
        return bool(
            configured_id
            and hashlib.sha256(configured_id.encode("utf-8")).hexdigest()
            == str(case.get("portfolio_id_sha256") or "")
        )

    def create_case(
        self,
        *,
        client_order_id: str,
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        local = self.repository.read_local_order(client_order_id)
        if not isinstance(local, dict):
            raise OperatorSpotRecoveryError("recovery_local_order_not_found")
        if str(local.get("client_order_id") or "") != client_order_id:
            raise OperatorSpotRecoveryError(
                "recovery_local_order_identity_mismatch"
            )
        try:
            provenance = OrderOwnershipProvenance(
                str(local.get("ownership_provenance") or "")
            )
        except ValueError:
            raise OperatorSpotRecoveryError(
                "recovery_order_not_system_owned"
            ) from None
        if provenance not in _SYSTEM_OWNED_PROVENANCE:
            raise OperatorSpotRecoveryError("recovery_order_not_system_owned")
        observed_portfolio_id = str(local.get("retail_portfolio_id") or "").strip()
        if (
            not self.configured_portfolio_id
            or observed_portfolio_id != self.configured_portfolio_id
        ):
            raise OperatorSpotRecoveryError(
                "recovery_portfolio_scope_mismatch"
            )
        product_id = str(local.get("product_id") or "").strip()
        if not product_id or "-" not in product_id:
            raise OperatorSpotRecoveryError("recovery_product_scope_invalid")
        return self.repository.create_case(
            client_order_id=client_order_id,
            product_id=product_id,
            portfolio_id_sha256=hashlib.sha256(
                observed_portfolio_id.encode("utf-8")
            ).hexdigest(),
            actor_id=actor_id,
            operator_reason=operator_reason,
            correlation_id=correlation_id,
        )

    def refresh_case(
        self,
        *,
        case_id: str,
        expected_revision: int,
        actor_id: str,
        correlation_id: str,
        manual_live_acknowledgement: bool,
    ) -> dict[str, Any]:
        if manual_live_acknowledgement is not True:
            raise OperatorSpotRecoveryError(
                "recovery_refresh_acknowledgement_required"
            )
        if not self.rest_client_available or self.rest_client is None:
            raise OperatorSpotRecoveryError(
                "recovery_rest_client_unavailable"
            )
        case = self.repository.get_case(case_id)
        if not isinstance(case, dict):
            raise OperatorSpotRecoveryError("recovery_case_not_found")
        local = self.repository.read_local_order(case["client_order_id"])
        if not isinstance(local, dict):
            raise OperatorSpotRecoveryError("recovery_local_order_not_found")
        self._validate_case_binding(case=case, local=local)

        claimed = self.repository.begin_refresh(
            case_id=case_id,
            expected_revision=expected_revision,
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        claimed_revision = int(claimed["revision"])
        from application.admin_api.command_service import (
            CoinbaseFillReadbackError,
            CoinbaseOrderReadbackError,
            exact_coinbase_order_readback,
            read_authoritative_coinbase_fills,
        )

        try:
            readback = exact_coinbase_order_readback(
                self.rest_client,
                client_order_id=case["client_order_id"],
                exchange_order_id=(
                    str(local.get("exchange_order_id") or "").strip() or None
                ),
                product_id=case["product_id"],
                expected_retail_portfolio_id=self.configured_portfolio_id,
            )
        except CoinbaseOrderReadbackError as exc:
            return self.repository.fail_refresh(
                case_id=case_id,
                expected_revision=claimed_revision,
                diagnostic_code=_fixed_diagnostic(
                    exc.blocker,
                    allowed=_ORDER_READ_DIAGNOSTICS,
                    fallback="order_read_unknown",
                ),
                actor_id=actor_id,
                correlation_id=correlation_id,
            )
        except Exception:
            return self.repository.fail_refresh(
                case_id=case_id,
                expected_revision=claimed_revision,
                diagnostic_code="order_read_unknown",
                actor_id=actor_id,
                correlation_id=correlation_id,
            )

        try:
            status_value = readback.get("authoritative_status")
            order_status = OrderStatus(status_value) if status_value else None
        except ValueError:
            order_status = None
        order_evidence = SpotRecoveryOrderEvidence(
            exact_identity_match=bool(readback.get("exact_identity_match")),
            authoritative=bool(readback.get("authoritative")),
            confirmed_absent=bool(readback.get("confirmed_absent")),
            status=order_status,
            page_count=int(readback.get("page_count") or 1),
        )

        fill_evidence: SpotRecoveryFillEvidence | None = None
        fill_page_count: int | None = None
        exchange_order_id = str(readback.get("exchange_order_id") or "").strip()
        if (
            order_evidence.exact_identity_match
            and readback.get("retail_portfolio_id_matches_expected") is not True
        ):
            return self.repository.fail_refresh(
                case_id=case_id,
                expected_revision=claimed_revision,
                diagnostic_code="order_portfolio_scope_mismatch",
                actor_id=actor_id,
                correlation_id=correlation_id,
            )
        if order_evidence.exact_identity_match and exchange_order_id:
            self.repository.record_fill_read_claim(
                case_id=case_id,
                expected_revision=claimed_revision,
                actor_id=actor_id,
                correlation_id=correlation_id,
            )
            try:
                fill_summary = read_authoritative_coinbase_fills(
                    self.rest_client,
                    exchange_order_id=exchange_order_id,
                    product_id=case["product_id"],
                )
            except CoinbaseFillReadbackError as exc:
                return self.repository.fail_refresh(
                    case_id=case_id,
                    expected_revision=claimed_revision,
                    diagnostic_code=_fixed_diagnostic(
                        exc.blocker,
                        allowed=_FILL_READ_DIAGNOSTICS,
                        fallback="fill_read_unknown",
                    ),
                    actor_id=actor_id,
                    correlation_id=correlation_id,
                )
            except Exception:
                return self.repository.fail_refresh(
                    case_id=case_id,
                    expected_revision=claimed_revision,
                    diagnostic_code="fill_read_unknown",
                    actor_id=actor_id,
                    correlation_id=correlation_id,
                )
            fill_evidence = SpotRecoveryFillEvidence.model_validate(fill_summary)
            fill_page_count = fill_evidence.page_count

        try:
            local_evidence = SpotRecoveryLocalOrderEvidence(
                client_order_id=case["client_order_id"],
                product_id=case["product_id"],
                side=str(local.get("side") or "").upper(),
                status=OrderStatus(str(local.get("status") or "").upper()),
                ownership_provenance=OrderOwnershipProvenance(
                    str(local.get("ownership_provenance") or "")
                ),
                portfolio_id_sha256=case["portfolio_id_sha256"],
                exchange_order_id_present=bool(
                    str(local.get("exchange_order_id") or "").strip()
                ),
            )
            plan = build_spot_recovery_plan(
                local=local_evidence,
                order=order_evidence,
                fills=fill_evidence,
            )
        except (TypeError, ValueError):
            return self.repository.fail_refresh(
                case_id=case_id,
                expected_revision=claimed_revision,
                diagnostic_code="recovery_evidence_validation_failed",
                actor_id=actor_id,
                correlation_id=correlation_id,
            )
        diagnostic_code = {
            SpotRecoveryPlanKind.NO_CHANGE: "recovery_no_change",
            SpotRecoveryPlanKind.SET_LOCAL_STATUS: "recovery_plan_ready",
            SpotRecoveryPlanKind.CANCEL_ACTIVE_ORPHAN: (
                "recovery_cancel_active_orphan_ready"
            ),
            SpotRecoveryPlanKind.BLOCKED: "recovery_plan_blocked",
        }[plan.kind]
        return self.repository.complete_refresh(
            case_id=case_id,
            expected_revision=claimed_revision,
            plan=plan,
            order_read_page_count=order_evidence.page_count,
            fill_read_page_count=fill_page_count,
            diagnostic_code=diagnostic_code,
            actor_id=actor_id,
            correlation_id=correlation_id,
        )

    def apply_case(
        self,
        *,
        case_id: str,
        expected_revision: int,
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
        operator_acknowledgement: bool,
    ) -> dict[str, Any]:
        if operator_acknowledgement is not True:
            raise OperatorSpotRecoveryError(
                "recovery_apply_acknowledgement_required"
            )
        return self.repository.apply_plan(
            case_id=case_id,
            expected_revision=expected_revision,
            actor_id=actor_id,
            operator_reason=operator_reason,
            correlation_id=correlation_id,
        )

    def rollback_case(
        self,
        *,
        case_id: str,
        expected_revision: int,
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
        operator_acknowledgement: bool,
    ) -> dict[str, Any]:
        if operator_acknowledgement is not True:
            raise OperatorSpotRecoveryError(
                "recovery_rollback_acknowledgement_required"
            )
        return self.repository.rollback_plan(
            case_id=case_id,
            expected_revision=expected_revision,
            actor_id=actor_id,
            operator_reason=operator_reason,
            correlation_id=correlation_id,
        )

    def _validate_case_binding(
        self,
        *,
        case: dict[str, Any],
        local: dict[str, Any],
    ) -> None:
        observed_portfolio_id = str(local.get("retail_portfolio_id") or "").strip()
        observed_hash = hashlib.sha256(
            observed_portfolio_id.encode("utf-8")
        ).hexdigest()
        if (
            str(local.get("client_order_id") or "") != case["client_order_id"]
            or str(local.get("product_id") or "") != case["product_id"]
            or not self.configured_portfolio_id
            or observed_portfolio_id != self.configured_portfolio_id
            or observed_hash != case["portfolio_id_sha256"]
        ):
            raise OperatorSpotRecoveryError(
                "recovery_case_binding_mismatch"
            )


def _fixed_diagnostic(
    value: Any,
    *,
    allowed: frozenset[str],
    fallback: str,
) -> str:
    normalized = str(value or "")
    return normalized if normalized in allowed else fallback


def build_operator_spot_recovery_case_item(
    record: dict[str, Any],
    *,
    events: list[dict[str, Any]] | None = None,
    portfolio_binding_verified: bool,
) -> OperatorSpotRecoveryCaseItem:
    """Project one repository row without raw exchange or exception values."""

    plan = (
        SpotRecoveryPlan.model_validate(record["plan"])
        if isinstance(record.get("plan"), dict)
        else None
    )
    state = SpotRecoveryCaseState(record["state"])
    allowed_actions: list[SpotRecoveryAction] = []
    rollback_detail: str | None = None
    if (
        portfolio_binding_verified
        and state in {
            SpotRecoveryCaseState.OPEN,
            SpotRecoveryCaseState.BLOCKED,
            SpotRecoveryCaseState.ROLLED_BACK,
        }
        and int(record.get("refresh_count") or 0) < 10
    ):
        allowed_actions.append(SpotRecoveryAction.REFRESH)
    if (
        portfolio_binding_verified
        and state is SpotRecoveryCaseState.PLAN_READY
        and plan is not None
        and plan.apply_available
    ):
        allowed_actions.append(SpotRecoveryAction.APPLY)
    if (
        portfolio_binding_verified
        and state is SpotRecoveryCaseState.PLAN_READY
        and plan is not None
        and plan.cancel_available
    ):
        allowed_actions.append(SpotRecoveryAction.CANCEL)
    if (
        portfolio_binding_verified
        and state is SpotRecoveryCaseState.APPLIED
        and plan is not None
    ):
        if plan.rollback_after_apply_available:
            allowed_actions.append(SpotRecoveryAction.ROLLBACK)
        else:
            rollback_detail = (
                "Rollback is blocked because restoring a nonterminal local "
                "status would contradict terminal Coinbase truth."
            )
    return OperatorSpotRecoveryCaseItem(
        case_id=str(record["case_id"]),
        client_order_id=str(record["client_order_id"]),
        product_id=str(record["product_id"]),
        portfolio_binding_verified=portfolio_binding_verified,
        state=state,
        revision=int(record["revision"]),
        refresh_count=int(record.get("refresh_count") or 0),
        order_read_logical_count=int(
            record.get("order_read_logical_count") or 0
        ),
        fill_read_logical_count=int(record.get("fill_read_logical_count") or 0),
        cancel_call_count=int(record.get("cancel_call_count") or 0),
        cancel_allowance_consumed=bool(
            record.get("cancel_allowance_consumed")
        ),
        plan=plan,
        diagnostic_code=str(record["diagnostic_code"]),
        correlation_id=str(record["correlation_id"]),
        created_at=str(record["created_at"]),
        updated_at=str(record["updated_at"]),
        allowed_actions=allowed_actions,
        rollback_safety_detail=rollback_detail,
        events=[
            OperatorSpotRecoveryEventItem.model_validate(
                {**event, "actor_id": "withheld"}
            )
            for event in (events or [])
        ],
    )
