"""Approval snapshot contract helpers for future live Admin API commands."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from core.enums import (
    AdminApiActionClass,
    AdminApiGateStatus,
    AdminApiLiveAdmissionBlocker,
    AdminApiPermission,
)

from .idempotency import make_payload_hash
from .models import AdminLiveAdmissionDecisionEvidence


class ApprovalSnapshotRequest(BaseModel):
    """Route-bound command shape a future approval snapshot must match."""

    model_config = ConfigDict(extra="forbid")

    route: str = Field(min_length=1)
    method: str = Field(min_length=1)
    module_id: str = Field(min_length=1)
    identity_key: str = Field(min_length=1)
    identity_value: str = Field(min_length=1)
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    requested_by_actor_id: str = Field(min_length=1)
    operator_intent: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    payload_hash: str = Field(min_length=64, max_length=64)


class ApprovalSnapshot(BaseModel):
    """Immutable backend approval evidence an execution request must match."""

    model_config = ConfigDict(extra="forbid")

    approval_id: str = Field(min_length=1)
    created_at: datetime
    expires_at: datetime
    route: str = Field(min_length=1)
    method: str = Field(min_length=1)
    module_id: str = Field(min_length=1)
    identity_key: str = Field(min_length=1)
    identity_value: str = Field(min_length=1)
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    requested_by_actor_id: str = Field(min_length=1)
    operator_intent: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    payload_hash: str = Field(min_length=64, max_length=64)
    approved_by_actor_id: str = Field(min_length=1)
    cap_guard_decision_ref: str = Field(min_length=1)
    reconciliation_plan_ref: str = Field(min_length=1)

    @property
    def actor_id(self) -> str:
        """Compatibility alias for older internal approval checks."""

        return self.approved_by_actor_id

    @property
    def client_order_id(self) -> str | None:
        """Return the client order id only when that is the route identity."""

        if self.identity_key == "client_order_id":
            return self.identity_value
        return None


class AdminApiApprovalRecord(BaseModel):
    """Durable approval record shape for future live Admin API commands."""

    model_config = ConfigDict(extra="forbid")

    approval_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime
    approved_by_actor_id: str = Field(min_length=1)
    requested_by_actor_id: str = Field(min_length=1)
    route: str = Field(min_length=1)
    method: str = Field(min_length=1)
    module_id: str = Field(min_length=1)
    identity_key: str = Field(min_length=1)
    identity_value: str = Field(min_length=1)
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    operator_intent: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    payload_hash: str = Field(min_length=64, max_length=64)
    cap_guard_decision_ref: str = Field(min_length=1)
    reconciliation_plan_ref: str = Field(min_length=1)
    approval_reason: str | None = None

    def is_expired(self, now: datetime | None = None) -> bool:
        check_time = now or datetime.now(timezone.utc)
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at <= check_time


class FileAdminApiApprovalStore:
    """Append-only JSONL approval store for future live Admin API commands."""

    def __init__(self, path: Path | str | None = None) -> None:
        configured_path = (
            path
            or os.environ.get("COINBASE_ADMIN_API_APPROVAL_LOG_PATH")
            or Path("runtime_state") / "admin_api_approvals.jsonl"
        )
        self.path = Path(configured_path)
        self._lock = RLock()

    def append(self, record: AdminApiApprovalRecord) -> str:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
            return record.approval_id

    def read_recent(self, *, limit: int = 100) -> list[AdminApiApprovalRecord]:
        normalized_limit = max(1, min(limit, 500))
        with self._lock:
            if not self.path.exists():
                return []
            lines = self.path.read_text(encoding="utf-8").splitlines()
        records: list[AdminApiApprovalRecord] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                records.append(AdminApiApprovalRecord.model_validate_json(line))
            except ValueError:
                continue
            if len(records) >= normalized_limit:
                break
        return records

    def find_matching(
        self,
        *,
        route: str,
        method: str,
        module_id: str,
        identity_key: str,
        identity_value: str,
        action_class: AdminApiActionClass,
        required_permission: AdminApiPermission | str,
        requested_by_actor_id: str,
        operator_intent: str,
        idempotency_key: str,
        payload_hash: str,
        now: datetime | None = None,
    ) -> AdminApiApprovalRecord | None:
        for record in self.read_recent(limit=500):
            if record.is_expired(now):
                continue
            if (
                record.route == route
                and record.method == method
                and record.module_id == module_id
                and record.identity_key == identity_key
                and record.identity_value == identity_value
                and _enum_value(record.action_class) == _enum_value(action_class)
                and _enum_value(record.required_permission)
                == _enum_value(required_permission)
                and record.requested_by_actor_id == requested_by_actor_id
                and record.operator_intent == operator_intent
                and record.idempotency_key == idempotency_key
                and record.payload_hash == payload_hash
            ):
                return record
        return None


class LiveExecutionGateDecision(BaseModel):
    """Service-level decision for live HTTP execution readiness."""

    model_config = ConfigDict(extra="forbid")

    allowed: bool
    reason: str
    live_execution_enabled: bool
    approval_snapshot_required: bool
    cap_evaluation_required: bool
    durable_audit_required: bool


def make_approval_snapshot_hash(payload: Any) -> str:
    """Hash the command fields that future approval gates will bind."""

    return make_payload_hash(payload)


def approval_matches_payload(snapshot: ApprovalSnapshot, payload: Any) -> bool:
    """Return whether a command still matches its approved snapshot."""

    return snapshot.payload_hash == make_approval_snapshot_hash(payload)


def _enum_value(value: AdminApiActionClass | AdminApiPermission | str) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return value


def approval_snapshot_from_record(record: AdminApiApprovalRecord) -> ApprovalSnapshot:
    """Build immutable approval snapshot evidence from a durable record."""

    return ApprovalSnapshot(
        approval_id=record.approval_id,
        created_at=record.created_at,
        expires_at=record.expires_at,
        route=record.route,
        method=record.method,
        module_id=record.module_id,
        identity_key=record.identity_key,
        identity_value=record.identity_value,
        action_class=record.action_class,
        required_permission=record.required_permission,
        requested_by_actor_id=record.requested_by_actor_id,
        operator_intent=record.operator_intent,
        idempotency_key=record.idempotency_key,
        payload_hash=record.payload_hash,
        approved_by_actor_id=record.approved_by_actor_id,
        cap_guard_decision_ref=record.cap_guard_decision_ref,
        reconciliation_plan_ref=record.reconciliation_plan_ref,
    )


def resolve_approval_snapshot(
    *,
    store: FileAdminApiApprovalStore,
    request: ApprovalSnapshotRequest,
    now: datetime | None = None,
) -> ApprovalSnapshot | None:
    """Resolve an exact, unexpired backend approval snapshot if one exists.

    This helper is infrastructure only. It does not approve commands, call
    Coinbase, write audit records, or alter command admission state.
    """

    record = store.find_matching(
        route=request.route,
        method=request.method,
        module_id=request.module_id,
        identity_key=request.identity_key,
        identity_value=request.identity_value,
        action_class=request.action_class,
        required_permission=request.required_permission,
        requested_by_actor_id=request.requested_by_actor_id,
        operator_intent=request.operator_intent,
        idempotency_key=request.idempotency_key,
        payload_hash=request.payload_hash,
        now=now,
    )
    if record is None:
        return None
    return approval_snapshot_from_record(record)


def evaluate_live_execution_gate(
    *,
    allow_live_execution: bool,
    cap_evaluation_required: bool = True,
) -> LiveExecutionGateDecision:
    """Return the current live-command gate decision.

    The enterprise HTTP surface is intentionally fail-closed until approval
    snapshots, cap evaluation, and audit enforcement are wired end to end.
    """

    if allow_live_execution:
        return LiveExecutionGateDecision(
            allowed=True,
            reason="live execution enabled by trusted compatibility adapter",
            live_execution_enabled=True,
            approval_snapshot_required=False,
            cap_evaluation_required=cap_evaluation_required,
            durable_audit_required=True,
        )
    return LiveExecutionGateDecision(
        allowed=False,
        reason=(
            "live execution disabled until approval snapshot and cap gates "
            "are enforced"
        ),
        live_execution_enabled=False,
        approval_snapshot_required=True,
        cap_evaluation_required=cap_evaluation_required,
        durable_audit_required=True,
    )


def evaluate_command_live_admission(
    *,
    route: str,
    method: str,
    module_id: str,
    identity_key: str,
    identity_value: str | None,
    action_class: AdminApiActionClass,
    required_permission: AdminApiPermission | str,
    service_method: str,
    actor_id: str,
    idempotency_key: str,
    operator_intent: str,
    payload_hash: str,
    approval_store: FileAdminApiApprovalStore | None = None,
    now: datetime | None = None,
) -> AdminLiveAdmissionDecisionEvidence:
    """Return route-bound live admission evidence for one command attempt.

    This is decision evidence only. The function does not call Coinbase and
    does not mutate command state. Current HTTP command routes remain blocked
    until approval store, admission audit, cap/guard, and reconciliation
    contracts are implemented end to end.
    """

    approval_snapshot = None
    approval_snapshot_missing_reason = "approval_store_not_checked"
    if approval_store is None:
        approval_snapshot_missing_reason = "approval_store_dependency_missing"
    elif not identity_value:
        approval_snapshot_missing_reason = "identity_value_missing"
    else:
        request = ApprovalSnapshotRequest(
            route=route,
            method=method,
            module_id=module_id,
            identity_key=identity_key,
            identity_value=identity_value,
            action_class=action_class,
            required_permission=required_permission,
            requested_by_actor_id=actor_id,
            operator_intent=operator_intent,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
        )
        approval_snapshot = resolve_approval_snapshot(
            store=approval_store,
            request=request,
            now=now,
        )
        if approval_snapshot is None:
            approval_snapshot_missing_reason = "no_matching_unexpired_snapshot"

    blockers = [
        AdminApiLiveAdmissionBlocker.LIVE_EXECUTION_DISABLED,
        AdminApiLiveAdmissionBlocker.ADMISSION_AUDIT_MISSING,
        AdminApiLiveAdmissionBlocker.CAP_GUARD_MISSING,
        AdminApiLiveAdmissionBlocker.RECONCILIATION_PLAN_MISSING,
        AdminApiLiveAdmissionBlocker.BROWSER_AUTHORITY_REJECTED,
    ]
    evidence = [
        "existing Admin API command route",
        "durable idempotency payload hash",
        "operator intent header",
        "shared command service boundary",
        "durable approval store contract",
    ]
    if approval_snapshot is None:
        blockers.insert(1, AdminApiLiveAdmissionBlocker.APPROVAL_SNAPSHOT_MISSING)
        evidence.append(
            f"missing route-specific approval snapshot: {approval_snapshot_missing_reason}"
        )
    else:
        evidence.append(
            "route-specific approval snapshot resolved but live execution remains blocked"
        )
    evidence.extend([
        "missing admission audit trail",
        "missing route-specific cap/guard decision",
        "browser authority rejected",
    ])

    return AdminLiveAdmissionDecisionEvidence(
        status=AdminApiGateStatus.BLOCKED,
        allowed=False,
        route=route,
        method=method,
        module_id=module_id,
        identity_key=identity_key,
        identity_value=identity_value,
        action_class=action_class,
        required_permission=required_permission,
        service_method=service_method,
        actor_id=actor_id,
        idempotency_key=idempotency_key,
        operator_intent=operator_intent,
        payload_hash=payload_hash,
        approval_snapshot_required=True,
        approval_store_required=True,
        admission_audit_required=True,
        cap_guard_required=True,
        reconciliation_required=True,
        approval_snapshot_present=approval_snapshot is not None,
        approval_snapshot_id=(
            approval_snapshot.approval_id if approval_snapshot is not None else None
        ),
        approval_snapshot_source=(
            "approval_store" if approval_snapshot is not None else "missing"
        ),
        approval_snapshot_approved_by_actor_id=(
            approval_snapshot.approved_by_actor_id
            if approval_snapshot is not None
            else None
        ),
        approval_snapshot_requested_by_actor_id=(
            approval_snapshot.requested_by_actor_id
            if approval_snapshot is not None
            else None
        ),
        approval_snapshot_expires_at=(
            approval_snapshot.expires_at.isoformat()
            if approval_snapshot is not None
            else None
        ),
        approval_snapshot_missing_reason=(
            None if approval_snapshot is not None else approval_snapshot_missing_reason
        ),
        browser_authority="rejected",
        live_exchange_submitted=False,
        blockers=blockers,
        evidence=evidence,
        detail=(
            "HTTP live execution is blocked until a backend-owned approval "
            "snapshot, cap/guard, admission-audit, and reconciliation gates "
            "admit this exact route, identity, payload hash, idempotency key, "
            "and operator intent."
        ),
    )
