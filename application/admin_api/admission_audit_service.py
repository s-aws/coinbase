"""Backend-owned admission audit writer for Admin API command admission."""

from __future__ import annotations

from datetime import datetime, timezone

from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiGateStatus,
    AdminApiLiveAdmissionBlocker,
    AdminApiPermission,
)

from .audit import AdminApiAuditEvent, FileAdminApiAuditStore
from .live_execution import (
    build_disabled_live_execution_intent,
    get_disabled_live_execution_service,
)
from .models import (
    AdminAdmissionAuditCreateRequest,
    AdminAdmissionAuditItem,
    AdminLiveAdmissionDecisionEvidence,
)
from .route_inventory import ADMIN_API_ROUTE_INVENTORY


class AdmissionAuditError(ValueError):
    """Raised when an admission audit record is invalid."""


class AdminApiAdmissionAuditService:
    """Service boundary for append-only admission audit records."""

    def record_admission_audit(
        self,
        *,
        store: FileAdminApiAuditStore,
        body: AdminAdmissionAuditCreateRequest,
        request_id: str,
        now: datetime | None = None,
    ) -> AdminAdmissionAuditItem:
        recorded_at = _normalize_now(now)
        self._validate_route_binding(body)
        self._validate_no_live_authority(body)
        event = _event_from_body(
            body=body,
            request_id=request_id,
            recorded_at=recorded_at,
        )
        store.append(event)
        return _item_from_event(event)

    def list_admission_audits(
        self,
        *,
        store: FileAdminApiAuditStore,
        status_filter: AdminApiGateStatus | None = None,
        limit: int = 100,
    ) -> list[AdminAdmissionAuditItem]:
        items = [
            _item_from_event(event)
            for event in store.read_recent(limit=limit)
            if _is_admission_audit_record(event)
        ]
        if status_filter is not None:
            items = [item for item in items if item.status == status_filter]
        return items

    def get_admission_audit(
        self,
        *,
        store: FileAdminApiAuditStore,
        admission_audit_id: str,
    ) -> AdminAdmissionAuditItem:
        event = store.find_by_audit_id(admission_audit_id)
        if event is None or not _is_admission_audit_record(event):
            raise AdmissionAuditError("Admission audit was not found.")
        return _item_from_event(event)

    def _validate_route_binding(
        self,
        body: AdminAdmissionAuditCreateRequest,
    ) -> None:
        method = body.method.upper()
        surface = f"{method} {body.route}"
        route = next(
            (item for item in ADMIN_API_ROUTE_INVENTORY if item.surface == surface),
            None,
        )
        if route is None:
            raise AdmissionAuditError(
                "Admission audits must target a route-inventory surface."
            )
        if route.module_id != body.module_id:
            raise AdmissionAuditError(
                "Admission audit module_id does not match route inventory."
            )
        if _enum_value(route.action_class) != _enum_value(body.action_class):
            raise AdmissionAuditError(
                "Admission audit action_class does not match route inventory."
            )
        if _enum_value(route.permission) != _enum_value(body.required_permission):
            raise AdmissionAuditError(
                "Admission audit required_permission does not match route inventory."
            )
        if route.shared_method != body.service_method:
            raise AdmissionAuditError(
                "Admission audit service_method does not match route inventory."
            )
        if route.action_class not in {
            AdminApiActionClass.LIVE_EXCHANGE_PLACE,
            AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
            AdminApiActionClass.LOCAL_STATE_MUTATION,
        }:
            raise AdmissionAuditError(
                "Admission audits are only valid for live-shaped command routes."
            )
        if (
            route.action_class == AdminApiActionClass.LOCAL_STATE_MUTATION
            and route.permission != AdminApiPermission.SPOT_RECOVERY_RECORD
        ):
            raise AdmissionAuditError(
                "Local-state admission audits are only valid for spot recovery "
                "proof record routes."
            )

    @staticmethod
    def _validate_no_live_authority(
        body: AdminAdmissionAuditCreateRequest,
    ) -> None:
        if body.allowed or body.status != AdminApiGateStatus.BLOCKED:
            raise AdmissionAuditError(
                "Admission audit writer cannot mark live admission allowed."
            )


def _event_from_body(
    *,
    body: AdminAdmissionAuditCreateRequest,
    request_id: str,
    recorded_at: datetime,
) -> AdminApiAuditEvent:
    method = body.method.upper()
    blockers = [
        AdminApiLiveAdmissionBlocker.LIVE_EXECUTION_DISABLED,
        AdminApiLiveAdmissionBlocker.ADMISSION_AUDIT_MISSING,
        AdminApiLiveAdmissionBlocker.CAP_GUARD_MISSING,
        AdminApiLiveAdmissionBlocker.RECONCILIATION_PLAN_MISSING,
        AdminApiLiveAdmissionBlocker.BROWSER_AUTHORITY_REJECTED,
    ]
    live_execution_state = get_disabled_live_execution_service().admission_state()
    live_execution_intent = build_disabled_live_execution_intent(
        method=method,
        route=body.route,
        module_id=body.module_id,
        identity_key=body.identity_key,
        identity_value=body.identity_value,
        action_class=body.action_class,
        required_permission=body.required_permission,
        service_method=body.service_method,
        actor_id=body.actor_id,
        idempotency_key=body.command_idempotency_key,
        operator_intent=body.operator_intent,
        payload_hash=body.payload_hash,
        blockers=blockers,
        live_execution_state=live_execution_state,
    )
    live_execution_intent_ref = f"AdminApiCommandService.{body.service_method}"
    decision = AdminLiveAdmissionDecisionEvidence(
        status=body.status,
        allowed=body.allowed,
        route=body.route,
        method=method,
        module_id=body.module_id,
        identity_key=body.identity_key,
        identity_value=body.identity_value,
        action_class=body.action_class,
        required_permission=body.required_permission,
        service_method=body.service_method,
        actor_id=body.actor_id,
        idempotency_key=body.command_idempotency_key,
        operator_intent=body.operator_intent,
        payload_hash=body.payload_hash,
        approval_snapshot_required=True,
        approval_store_required=True,
        admission_audit_required=True,
        cap_guard_required=True,
        reconciliation_required=True,
        approval_snapshot_present=True,
        approval_snapshot_id=body.approval_snapshot_id,
        approval_snapshot_source="approval_store",
        approval_snapshot_approved_by_actor_id=body.approval_snapshot_approved_by_actor_id,
        approval_snapshot_requested_by_actor_id=body.approval_snapshot_requested_by_actor_id,
        approval_snapshot_expires_at=body.approval_snapshot_expires_at,
        cap_guard_missing_reason="admission_audit_missing",
        reconciliation_plan_missing_reason="admission_audit_missing",
        live_execution_service_required=live_execution_state.required,
        live_execution_service_present=live_execution_state.present,
        live_execution_service_status=live_execution_state.status,
        live_execution_service_source=live_execution_state.source,
        live_execution_service_missing_reason=live_execution_state.missing_reason,
        browser_authority="rejected",
        live_exchange_submitted=False,
        live_execution_intent=live_execution_intent,
        blockers=blockers,
        evidence=[
            "append-only admission audit writer",
            f"approval snapshot linked: {body.approval_snapshot_id}",
            f"cap/guard decision ref linked: {body.approval_cap_guard_decision_ref}",
            f"reconciliation plan ref linked: {body.approval_reconciliation_plan_ref}",
            f"disabled live execution intent linked: {live_execution_intent_ref}",
            "browser authority rejected",
        ],
        detail=(
            "Backend admission audit proof was recorded for this exact route, "
            "identity, payload hash, idempotency key, and operator intent. "
            "Live execution remains disabled until cap/guard, reconciliation, "
            "and live adapter gates also resolve."
        ),
    )
    return AdminApiAuditEvent(
        recorded_at=recorded_at.isoformat(),
        actor_id=body.actor_id,
        action_class=body.action_class,
        permission=body.required_permission,
        endpoint=f"{method} {body.route}",
        request_id=request_id,
        operator_intent=body.operator_intent,
        idempotency_key=body.command_idempotency_key,
        approval_id=body.approval_snapshot_id,
        client_order_id=(
            body.identity_value if body.identity_key == "client_order_id" else None
        ),
        stealth_order_id=(
            body.identity_value if body.identity_key == "stealth_order_id" else None
        ),
        status=AdminApiCommandStatus.NOT_IMPLEMENTED,
        failure_stage="admission_audit",
        message=body.reason,
        admission_decision=decision,
        approval_cap_guard_decision_ref=body.approval_cap_guard_decision_ref,
        approval_reconciliation_plan_ref=body.approval_reconciliation_plan_ref,
        live_execution_intent_ref=live_execution_intent_ref,
    )


def _is_admission_audit_record(event: AdminApiAuditEvent) -> bool:
    return (
        event.admission_decision is not None
        and event.approval_cap_guard_decision_ref is not None
        and event.approval_reconciliation_plan_ref is not None
        and event.live_execution_intent_ref is not None
    )


def _item_from_event(event: AdminApiAuditEvent) -> AdminAdmissionAuditItem:
    decision = event.admission_decision
    if decision is None:
        raise AdmissionAuditError("Audit event does not contain admission evidence.")
    if (
        event.approval_cap_guard_decision_ref is None
        or event.approval_reconciliation_plan_ref is None
        or event.live_execution_intent_ref is None
    ):
        raise AdmissionAuditError("Audit event is missing admission linkage evidence.")
    if decision.approval_snapshot_id is None:
        raise AdmissionAuditError("Audit event is missing approval snapshot evidence.")
    resolver_eligible = (
        decision.approval_snapshot_present
        and decision.approval_snapshot_id is not None
        and decision.identity_value is not None
        and event.status == AdminApiCommandStatus.NOT_IMPLEMENTED
    )
    return AdminAdmissionAuditItem(
        admission_audit_id=event.audit_id,
        recorded_at=event.recorded_at,
        route=decision.route,
        method=decision.method,
        module_id=decision.module_id,
        identity_key=decision.identity_key,
        identity_value=decision.identity_value or "",
        action_class=decision.action_class,
        required_permission=decision.required_permission,
        service_method=decision.service_method,
        actor_id=decision.actor_id,
        operator_intent=decision.operator_intent,
        command_idempotency_key=decision.idempotency_key,
        payload_hash=decision.payload_hash,
        approval_snapshot_id=decision.approval_snapshot_id,
        approval_snapshot_approved_by_actor_id=(
            decision.approval_snapshot_approved_by_actor_id
        ),
        approval_snapshot_requested_by_actor_id=(
            decision.approval_snapshot_requested_by_actor_id
        ),
        approval_snapshot_expires_at=decision.approval_snapshot_expires_at,
        approval_cap_guard_decision_ref=event.approval_cap_guard_decision_ref,
        approval_reconciliation_plan_ref=event.approval_reconciliation_plan_ref,
        live_execution_intent_ref=event.live_execution_intent_ref,
        allowed=decision.allowed,
        status=decision.status,
        resolver_eligible=resolver_eligible,
        admission_decision=decision,
        detail=(
            "Admission audit is resolver-eligible for an exact backend "
            "command-admission match, but it does not authorize live execution."
            if resolver_eligible
            else "Admission audit is durable evidence only and will fail closed."
        ),
    )


def _normalize_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _enum_value(value: AdminApiActionClass | AdminApiPermission | str) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return value
