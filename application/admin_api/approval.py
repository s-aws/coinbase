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
    AdminApiApprovalLifecycleEventType,
    AdminApiApprovalLifecycleStatus,
    AdminApiGateStatus,
    AdminApiLiveAdmissionBlocker,
    AdminApiLiveExecutionStatus,
    AdminApiPermission,
)

from .idempotency import make_payload_hash
from .audit import (
    AdmissionAuditTrailRequest,
    FileAdminApiAuditStore,
    resolve_admission_audit_trail,
)
from .cap_guard import (
    CapGuardDecisionRequest,
    FileAdminApiCapGuardStore,
    resolve_cap_guard_decision,
)
from .reconciliation import (
    FileAdminApiReconciliationStore,
    ReconciliationPlanRequest,
    resolve_reconciliation_plan,
)
from .live_execution import (
    AdminApiLiveExecutionService,
    AdminApiLiveExecutionServiceState,
    build_disabled_live_execution_intent,
)
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


class AdminApiApprovalLifecycleEvent(BaseModel):
    """Append-only event for backend-owned approval request and decision state."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    event_type: AdminApiApprovalLifecycleEventType
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    approval_request_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    approval_id: str | None = None
    status: AdminApiApprovalLifecycleStatus
    actor_id: str = Field(min_length=1)
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
    expires_at: datetime | None = None
    cap_guard_decision_ref: str | None = None
    reconciliation_plan_ref: str | None = None
    request_reason: str | None = None
    decision_reason: str | None = None
    revoke_reason: str | None = None
    live_exchange_submitted: bool = False
    browser_authority: str = "display_only"


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

    def append_lifecycle_event(self, event: AdminApiApprovalLifecycleEvent) -> str:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(event.model_dump_json() + "\n")
            return event.event_id

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

    def read_lifecycle_events(
        self,
        *,
        limit: int = 500,
    ) -> list[AdminApiApprovalLifecycleEvent]:
        """Return recent approval lifecycle events, newest first."""

        normalized_limit = max(1, min(limit, 1000))
        with self._lock:
            if not self.path.exists():
                return []
            lines = self.path.read_text(encoding="utf-8").splitlines()
        events: list[AdminApiApprovalLifecycleEvent] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                events.append(AdminApiApprovalLifecycleEvent.model_validate_json(line))
            except ValueError:
                continue
            if len(events) >= normalized_limit:
                break
        return events

    def find_lifecycle_request(
        self,
        *,
        approval_request_id: str,
    ) -> AdminApiApprovalLifecycleEvent | None:
        for event in self.read_lifecycle_events(limit=1000):
            if (
                event.approval_request_id == approval_request_id
                and event.event_type == AdminApiApprovalLifecycleEventType.REQUEST_CREATED
            ):
                return event
        return None

    def find_by_approval_id(
        self,
        approval_id: str,
    ) -> AdminApiApprovalRecord | None:
        for record in self.read_recent(limit=1000):
            if record.approval_id == approval_id:
                return record
        return None

    def approval_is_revoked(self, approval_id: str) -> bool:
        for event in self.read_lifecycle_events(limit=1000):
            if (
                event.approval_id == approval_id
                and event.event_type == AdminApiApprovalLifecycleEventType.APPROVAL_REVOKED
            ):
                return True
        return False

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
            if self.approval_is_revoked(record.approval_id):
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

    The enterprise HTTP surface is no-live by default. Route-scoped manual
    Spot order/cancel exceptions can reach live only after their exact backend
    approval, cap/guard, audit, reconciliation, acknowledgement, live-service,
    REST-client, and event-stream gates pass.
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
    audit_store: FileAdminApiAuditStore | None = None,
    cap_guard_store: FileAdminApiCapGuardStore | None = None,
    reconciliation_store: FileAdminApiReconciliationStore | None = None,
    live_execution_service: AdminApiLiveExecutionService | None = None,
    manual_live_acknowledgement: bool = False,
    now: datetime | None = None,
) -> AdminLiveAdmissionDecisionEvidence:
    """Return route-bound live admission evidence for one command attempt.

    This is decision evidence only. The function does not call Coinbase and
    does not mutate command state. HTTP command routes are no-live by default;
    manual Spot order/cancel can use this evidence only as one prerequisite in
    their route-scoped configured live path. Other command routes remain
    blocked/fail-closed unless they receive their own explicit live contract.
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

    admission_audit = None
    admission_audit_missing_reason = "audit_store_not_checked"
    if audit_store is None:
        admission_audit_missing_reason = "audit_store_dependency_missing"
    elif not identity_value:
        admission_audit_missing_reason = "identity_value_missing"
    elif approval_snapshot is None:
        admission_audit_missing_reason = "approval_snapshot_missing"
    else:
        admission_audit = resolve_admission_audit_trail(
            store=audit_store,
            request=AdmissionAuditTrailRequest(
                route=route,
                method=method,
                module_id=module_id,
                identity_key=identity_key,
                identity_value=identity_value,
                action_class=action_class,
                required_permission=required_permission,
                service_method=service_method,
                actor_id=actor_id,
                operator_intent=operator_intent,
                idempotency_key=idempotency_key,
                payload_hash=payload_hash,
                approval_snapshot_id=approval_snapshot.approval_id,
            ),
        )
        if admission_audit is None:
            admission_audit_missing_reason = "no_matching_admission_audit"

    cap_guard = None
    cap_guard_missing_reason = "cap_guard_store_not_checked"
    if cap_guard_store is None:
        cap_guard_missing_reason = "cap_guard_store_dependency_missing"
    elif not identity_value:
        cap_guard_missing_reason = "identity_value_missing"
    elif approval_snapshot is None:
        cap_guard_missing_reason = "approval_snapshot_missing"
    elif admission_audit is None:
        cap_guard_missing_reason = "admission_audit_missing"
    else:
        cap_guard = resolve_cap_guard_decision(
            store=cap_guard_store,
            request=CapGuardDecisionRequest(
                route=route,
                method=method,
                module_id=module_id,
                identity_key=identity_key,
                identity_value=identity_value,
                action_class=action_class,
                required_permission=required_permission,
                service_method=service_method,
                actor_id=actor_id,
                operator_intent=operator_intent,
                idempotency_key=idempotency_key,
                payload_hash=payload_hash,
                approval_snapshot_id=approval_snapshot.approval_id,
                approval_cap_guard_decision_ref=(
                    approval_snapshot.cap_guard_decision_ref
                ),
                admission_audit_id=admission_audit.audit_id,
            ),
        )
        if cap_guard is None:
            cap_guard_missing_reason = "no_matching_cap_guard_decision"

    live_execution_state = (
        live_execution_service.admission_state()
        if live_execution_service is not None
        else AdminApiLiveExecutionServiceState()
    )
    live_execution_enabled = (
        live_execution_state.present
        and _enum_value(live_execution_state.status)
        == AdminApiLiveExecutionStatus.COMPLETED.value
        and live_execution_state.missing_reason is None
    )

    blockers: list[AdminApiLiveAdmissionBlocker] = []
    if not live_execution_enabled:
        blockers.append(AdminApiLiveAdmissionBlocker.LIVE_EXECUTION_DISABLED)
    evidence = [
        "existing Admin API command route",
        "durable idempotency payload hash",
        "operator intent header",
        "shared command service boundary",
        "durable approval store contract",
    ]
    if approval_snapshot is None:
        blockers.append(AdminApiLiveAdmissionBlocker.APPROVAL_SNAPSHOT_MISSING)
        evidence.append(
            f"missing route-specific approval snapshot: {approval_snapshot_missing_reason}"
        )
    else:
        evidence.append("route-specific approval snapshot resolved")
    if admission_audit is None:
        blockers.append(AdminApiLiveAdmissionBlocker.ADMISSION_AUDIT_MISSING)
        evidence.append(
            f"missing admission audit trail: {admission_audit_missing_reason}"
        )
    else:
        evidence.append("route-specific admission audit resolved")
    if cap_guard is None:
        blockers.append(AdminApiLiveAdmissionBlocker.CAP_GUARD_MISSING)
        evidence.append(
            f"missing route-specific cap/guard decision: {cap_guard_missing_reason}"
        )
    else:
        evidence.append("route-specific cap/guard decision resolved")

    reconciliation_plan = None
    reconciliation_plan_missing_reason = "reconciliation_store_not_checked"
    if reconciliation_store is None:
        reconciliation_plan_missing_reason = "reconciliation_store_dependency_missing"
    elif not identity_value:
        reconciliation_plan_missing_reason = "identity_value_missing"
    elif approval_snapshot is None:
        reconciliation_plan_missing_reason = "approval_snapshot_missing"
    elif admission_audit is None:
        reconciliation_plan_missing_reason = "admission_audit_missing"
    elif cap_guard is None:
        reconciliation_plan_missing_reason = "cap_guard_missing"
    else:
        reconciliation_plan = resolve_reconciliation_plan(
            store=reconciliation_store,
            request=ReconciliationPlanRequest(
                route=route,
                method=method,
                module_id=module_id,
                identity_key=identity_key,
                identity_value=identity_value,
                action_class=action_class,
                required_permission=required_permission,
                service_method=service_method,
                actor_id=actor_id,
                operator_intent=operator_intent,
                idempotency_key=idempotency_key,
                payload_hash=payload_hash,
                approval_snapshot_id=approval_snapshot.approval_id,
                approval_reconciliation_plan_ref=(
                    approval_snapshot.reconciliation_plan_ref
                ),
                admission_audit_id=admission_audit.audit_id,
                cap_guard_decision_id=cap_guard.decision_id,
            ),
        )
        if reconciliation_plan is None:
            reconciliation_plan_missing_reason = "no_matching_reconciliation_plan"

    if reconciliation_plan is None:
        blockers.append(AdminApiLiveAdmissionBlocker.RECONCILIATION_PLAN_MISSING)
        evidence.append(
            "missing route-specific reconciliation plan: "
            f"{reconciliation_plan_missing_reason}"
        )
    else:
        evidence.append("route-specific reconciliation plan resolved")
    if not live_execution_enabled or not manual_live_acknowledgement:
        blockers.append(AdminApiLiveAdmissionBlocker.BROWSER_AUTHORITY_REJECTED)
    if live_execution_enabled:
        evidence.append(
            f"live execution service {live_execution_state.source} admitted"
        )
    else:
        evidence.append(
            f"live execution service {live_execution_state.source} disabled"
        )
    if manual_live_acknowledgement:
        evidence.append("manual live acknowledgement present")
    else:
        evidence.append("manual live acknowledgement missing")
    if AdminApiLiveAdmissionBlocker.BROWSER_AUTHORITY_REJECTED in blockers:
        evidence.append("browser authority rejected")
    allowed = not blockers
    decision_status = (
        AdminApiGateStatus.PASSED if allowed else AdminApiGateStatus.BLOCKED
    )
    live_execution_intent = build_disabled_live_execution_intent(
        method=method,
        route=route,
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
        blockers=blockers,
        live_execution_state=live_execution_state,
    )

    return AdminLiveAdmissionDecisionEvidence(
        status=decision_status,
        allowed=allowed,
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
        admission_audit_present=admission_audit is not None,
        admission_audit_id=(
            admission_audit.audit_id if admission_audit is not None else None
        ),
        admission_audit_source=(
            admission_audit.source if admission_audit is not None else "missing"
        ),
        admission_audit_recorded_at=(
            admission_audit.recorded_at if admission_audit is not None else None
        ),
        admission_audit_missing_reason=(
            None if admission_audit is not None else admission_audit_missing_reason
        ),
        cap_guard_present=cap_guard is not None,
        cap_guard_decision_id=(
            cap_guard.decision_id if cap_guard is not None else None
        ),
        cap_guard_source=(
            cap_guard.source if cap_guard is not None else "missing"
        ),
        cap_guard_recorded_at=(
            cap_guard.recorded_at if cap_guard is not None else None
        ),
        cap_guard_missing_reason=(
            None if cap_guard is not None else cap_guard_missing_reason
        ),
        reconciliation_plan_present=reconciliation_plan is not None,
        reconciliation_plan_id=(
            reconciliation_plan.plan_id if reconciliation_plan is not None else None
        ),
        reconciliation_plan_source=(
            reconciliation_plan.source if reconciliation_plan is not None else "missing"
        ),
        reconciliation_plan_recorded_at=(
            reconciliation_plan.recorded_at
            if reconciliation_plan is not None
            else None
        ),
        reconciliation_plan_missing_reason=(
            None
            if reconciliation_plan is not None
            else reconciliation_plan_missing_reason
        ),
        live_execution_service_required=live_execution_state.required,
        live_execution_service_present=live_execution_state.present,
        live_execution_service_status=live_execution_state.status,
        live_execution_service_source=live_execution_state.source,
        live_execution_service_missing_reason=live_execution_state.missing_reason,
        browser_authority="display_only" if allowed else "rejected",
        live_exchange_submitted=False,
        live_execution_intent=live_execution_intent,
        blockers=blockers,
        evidence=evidence,
        detail=(
            (
                "HTTP live execution is admitted by backend-owned approval, "
                "admission-audit, cap/guard, reconciliation, manual "
                "acknowledgement, and live-service gates for this exact route, "
                "identity, payload hash, idempotency key, and operator intent."
            )
            if allowed
            else (
                "HTTP live execution is blocked until a backend-owned approval "
                "snapshot, cap/guard, admission-audit, reconciliation, manual "
                "acknowledgement, and live-service gates admit this exact route, "
                "identity, payload hash, idempotency key, and operator intent."
            )
        ),
    )
