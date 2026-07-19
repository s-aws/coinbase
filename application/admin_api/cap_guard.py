"""Durable cap/guard decision proof helpers for Admin API admission."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
import os
from pathlib import Path
from threading import RLock
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from core.enums import AdminApiActionClass, AdminApiGateStatus, AdminApiPermission

from .operator_mvp_policy import (
    OPERATOR_MVP_CANCEL_ORDER_ROUTE,
    OPERATOR_MVP_CANCEL_PRODUCT_SCOPE,
    OPERATOR_MVP_MANUAL_ORDER_ROUTE,
    OPERATOR_MVP_MAX_EXECUTED_NOTIONAL_USDC,
    OPERATOR_MVP_MAX_SUBMITTED_NOTIONAL_USDC,
    OPERATOR_MVP_SPOT_MODULE_ID,
    OPERATOR_MVP_WALLET_EVIDENCE_SOURCES,
)


class CapGuardDecisionRequest(BaseModel):
    """Exact command shape a cap/guard decision proof must match."""

    model_config = ConfigDict(extra="forbid")

    route: str = Field(min_length=1)
    method: str = Field(min_length=1)
    module_id: str = Field(min_length=1)
    identity_key: str = Field(min_length=1)
    identity_value: str = Field(min_length=1)
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    service_method: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    operator_intent: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    payload_hash: str = Field(min_length=64, max_length=64)
    approval_snapshot_id: str = Field(min_length=1)
    approval_cap_guard_decision_ref: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    max_submitted_notional_usdc: str | None = None
    max_executed_notional_usdc: str | None = None
    product_scope: str | None = None


class CapGuardDecisionRecord(BaseModel):
    """Append-only backend cap/guard decision evidence."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    recorded_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    route: str = Field(min_length=1)
    method: str = Field(min_length=1)
    module_id: str = Field(min_length=1)
    identity_key: str = Field(min_length=1)
    identity_value: str = Field(min_length=1)
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    service_method: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    operator_intent: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    payload_hash: str = Field(min_length=64, max_length=64)
    approval_snapshot_id: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    allowed: bool
    status: AdminApiGateStatus
    source: str = "admin_api_cap_guard_log"
    cap_policy_ref: str = Field(min_length=1)
    guard_policy_ref: str = Field(min_length=1)
    product_scope: str = Field(min_length=1)
    max_submitted_notional_usdc: str = Field(min_length=1)
    max_executed_notional_usdc: str = Field(min_length=1)
    wallet_check_required: bool = True
    wallet_check_status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    wallet_available_notional_usdc: str = Field(default="0", min_length=1)
    wallet_check_source: str = Field(default="missing", min_length=1)
    reason: str


class CapGuardDecisionProof(BaseModel):
    """Immutable evidence that a backend cap/guard decision matches admission."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(min_length=1)
    recorded_at: str = Field(min_length=1)
    source: str = "admin_api_cap_guard_log"
    approval_snapshot_id: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_policy_ref: str = Field(min_length=1)
    guard_policy_ref: str = Field(min_length=1)
    product_scope: str = Field(min_length=1)
    max_submitted_notional_usdc: str = Field(min_length=1)
    max_executed_notional_usdc: str = Field(min_length=1)


class FileAdminApiCapGuardStore:
    """Append-only JSONL cap/guard decision store for future live admission."""

    def __init__(self, path: Path | str | None = None) -> None:
        configured_path = (
            path
            or os.environ.get("COINBASE_ADMIN_API_CAP_GUARD_LOG_PATH")
            or Path("runtime_state") / "admin_api_cap_guard.jsonl"
        )
        self.path = Path(configured_path)
        self._lock = RLock()

    def append(self, record: CapGuardDecisionRecord) -> str:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
            return record.decision_id

    def read_recent(self, *, limit: int = 100) -> list[CapGuardDecisionRecord]:
        normalized_limit = max(1, min(limit, 500))
        with self._lock:
            if not self.path.exists():
                return []
            lines = self.path.read_text(encoding="utf-8").splitlines()
        records: list[CapGuardDecisionRecord] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                records.append(CapGuardDecisionRecord.model_validate_json(line))
            except ValueError:
                continue
            if len(records) >= normalized_limit:
                break
        return records

    def find_by_decision_id(self, decision_id: str) -> CapGuardDecisionRecord | None:
        """Return the latest record with the given decision id, if present."""

        for record in self.read_recent(limit=500):
            if record.decision_id == decision_id:
                return record
        return None

    def find_matching_decision(
        self,
        *,
        request: CapGuardDecisionRequest,
    ) -> CapGuardDecisionRecord | None:
        """Return an exact allowed cap/guard decision if one exists."""

        for record in self.read_recent(limit=500):
            if not record.allowed or record.status != AdminApiGateStatus.PASSED:
                continue
            if record.decision_id != request.approval_cap_guard_decision_ref:
                continue
            if operator_mvp_cap_guard_policy_error(
                record,
                expected_product_scope=request.product_scope,
            ) is not None:
                continue
            if (
                record.route == request.route
                and record.method == request.method
                and record.module_id == request.module_id
                and record.identity_key == request.identity_key
                and record.identity_value == request.identity_value
                and _enum_value(record.action_class)
                == _enum_value(request.action_class)
                and _enum_value(record.required_permission)
                == _enum_value(request.required_permission)
                and record.service_method == request.service_method
                and record.actor_id == request.actor_id
                and record.operator_intent == request.operator_intent
                and record.idempotency_key == request.idempotency_key
                and record.payload_hash == request.payload_hash
                and record.approval_snapshot_id == request.approval_snapshot_id
                and record.admission_audit_id == request.admission_audit_id
                and _optional_decimal_matches(
                    record.max_submitted_notional_usdc,
                    request.max_submitted_notional_usdc,
                )
                and _optional_decimal_matches(
                    record.max_executed_notional_usdc,
                    request.max_executed_notional_usdc,
                )
            ):
                return record
        return None


def resolve_cap_guard_decision(
    *,
    store: FileAdminApiCapGuardStore,
    request: CapGuardDecisionRequest,
) -> CapGuardDecisionProof | None:
    """Resolve exact backend-owned cap/guard proof for command admission.

    This does not evaluate guards, write approval records, reconcile, call
    Coinbase, or make browser evidence authoritative.
    """

    record = store.find_matching_decision(request=request)
    if record is None:
        return None
    return CapGuardDecisionProof(
        decision_id=record.decision_id,
        recorded_at=record.recorded_at,
        approval_snapshot_id=record.approval_snapshot_id,
        admission_audit_id=record.admission_audit_id,
        cap_policy_ref=record.cap_policy_ref,
        guard_policy_ref=record.guard_policy_ref,
        product_scope=record.product_scope,
        max_submitted_notional_usdc=record.max_submitted_notional_usdc,
        max_executed_notional_usdc=record.max_executed_notional_usdc,
    )


def _enum_value(value: AdminApiActionClass | AdminApiPermission | str) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return value


def _optional_decimal_matches(record_value: str, expected_value: str | None) -> bool:
    """Return whether a record stays within an optional backend ceiling."""

    if expected_value is None:
        return True
    try:
        record_decimal = Decimal(str(record_value))
        ceiling_decimal = Decimal(str(expected_value))
        return bool(
            record_decimal.is_finite()
            and ceiling_decimal.is_finite()
            and record_decimal <= ceiling_decimal
        )
    except (InvalidOperation, TypeError, ValueError):
        return False


def operator_mvp_cap_guard_policy_error(
    value: object,
    *,
    expected_product_scope: str | None = None,
    verify_wallet_fields: bool = True,
) -> str | None:
    """Return a fixed blocker for an unsafe installed-MVP cap decision."""

    route = str(getattr(value, "route", "") or "")
    module_id = str(getattr(value, "module_id", "") or "")
    if module_id != OPERATOR_MVP_SPOT_MODULE_ID or route not in {
        OPERATOR_MVP_MANUAL_ORDER_ROUTE,
        OPERATOR_MVP_CANCEL_ORDER_ROUTE,
    }:
        return None

    allowed = getattr(value, "allowed", False) is True
    status = getattr(value, "status", None)
    if not allowed or status != AdminApiGateStatus.PASSED:
        return None

    submitted = _finite_decimal(
        getattr(value, "max_submitted_notional_usdc", None)
    )
    executed = _finite_decimal(
        getattr(value, "max_executed_notional_usdc", None)
    )
    product_scope = str(getattr(value, "product_scope", "") or "")

    if route == OPERATOR_MVP_CANCEL_ORDER_ROUTE:
        if submitted != Decimal("0") or executed != Decimal("0"):
            return "operator_mvp_cancel_notional_must_be_zero"
        if product_scope != OPERATOR_MVP_CANCEL_PRODUCT_SCOPE:
            return "operator_mvp_cancel_product_scope_invalid"
        if getattr(value, "wallet_check_required", True) is not False:
            return "operator_mvp_cancel_wallet_check_must_be_not_required"
        if str(getattr(value, "wallet_check_source", "") or "") != (
            "not_applicable:cancel_order"
        ):
            return "operator_mvp_cancel_wallet_source_invalid"
        return None

    if not is_concrete_usdc_spot_product(product_scope):
        return "operator_mvp_manual_product_scope_invalid"
    if expected_product_scope is not None and product_scope != expected_product_scope:
        return "operator_mvp_manual_product_scope_mismatch"
    if submitted is None or submitted <= 0:
        return "operator_mvp_submitted_notional_invalid"
    if submitted > OPERATOR_MVP_MAX_SUBMITTED_NOTIONAL_USDC:
        return "operator_mvp_submitted_notional_ceiling_exceeded"
    if executed is None or executed <= 0 or executed > submitted:
        return "operator_mvp_executed_notional_invalid"
    if executed > OPERATOR_MVP_MAX_EXECUTED_NOTIONAL_USDC:
        return "operator_mvp_executed_notional_ceiling_exceeded"
    if getattr(value, "wallet_check_required", False) is not True:
        return "operator_mvp_wallet_check_required"
    if not verify_wallet_fields:
        return None
    if getattr(value, "wallet_check_status", None) != AdminApiGateStatus.PASSED:
        return "operator_mvp_wallet_check_not_passed"
    wallet_available = _finite_decimal(
        getattr(value, "wallet_available_notional_usdc", None)
    )
    if wallet_available is None or wallet_available < submitted:
        return "operator_mvp_wallet_evidence_insufficient"
    if str(getattr(value, "wallet_check_source", "") or "") not in (
        OPERATOR_MVP_WALLET_EVIDENCE_SOURCES
    ):
        return "operator_mvp_wallet_source_invalid"
    return None


def _finite_decimal(value: object) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def is_concrete_usdc_spot_product(value: str) -> bool:
    """Return whether one product is the installed MVP's concrete USDC Spot scope."""

    return bool(
        value
        and value == value.upper()
        and value.endswith("-USDC")
        and value[:-5]
        and all(character.isalnum() or character in {"-", "."} for character in value)
    )
