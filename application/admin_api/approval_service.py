"""Backend-owned approval lifecycle service for Admin API live admission."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from core.enums import (
    AdminApiActionClass,
    AdminApiApprovalLifecycleEventType,
    AdminApiApprovalLifecycleStatus,
    AdminApiPermission,
)

from .approval import (
    AdminApiApprovalLifecycleEvent,
    AdminApiApprovalRecord,
    FileAdminApiApprovalStore,
)
from .models import (
    AdminApprovalDecisionRequest,
    AdminApprovalLifecycleItem,
    AdminApprovalRequestCreateRequest,
)
from .route_inventory import ADMIN_API_ROUTE_INVENTORY


class ApprovalLifecycleError(ValueError):
    """Raised when an approval lifecycle transition is invalid."""


class AdminApiApprovalLifecycleService:
    """Service boundary for approval request, decision, revoke, and expiry state."""

    def create_request(
        self,
        *,
        store: FileAdminApiApprovalStore,
        body: AdminApprovalRequestCreateRequest,
        actor_id: str,
        now: datetime | None = None,
    ) -> AdminApprovalLifecycleItem:
        recorded_at = _normalize_now(now)
        self._validate_route_binding(body)
        event = AdminApiApprovalLifecycleEvent(
            event_type=AdminApiApprovalLifecycleEventType.REQUEST_CREATED,
            recorded_at=recorded_at,
            approval_request_id=str(uuid4()),
            status=AdminApiApprovalLifecycleStatus.REQUESTED,
            actor_id=actor_id,
            route=body.route,
            method=body.method.upper(),
            module_id=body.module_id,
            identity_key=body.identity_key,
            identity_value=body.identity_value,
            action_class=body.action_class,
            required_permission=body.required_permission,
            requested_by_actor_id=actor_id,
            operator_intent=body.operator_intent,
            idempotency_key=body.command_idempotency_key,
            payload_hash=body.payload_hash,
            request_reason=body.request_reason,
        )
        store.append_lifecycle_event(event)
        return _item_from_events([event], now=recorded_at)

    def decide_request(
        self,
        *,
        store: FileAdminApiApprovalStore,
        approval_request_id: str,
        body: AdminApprovalDecisionRequest,
        actor_id: str,
        now: datetime | None = None,
    ) -> AdminApprovalLifecycleItem:
        recorded_at = _normalize_now(now)
        if body.decision not in {
            AdminApiApprovalLifecycleStatus.APPROVED,
            AdminApiApprovalLifecycleStatus.REJECTED,
        }:
            raise ApprovalLifecycleError(
                "Approval decisions must be approved or rejected."
            )

        existing = self.get_request(
            store=store,
            approval_request_id=approval_request_id,
            now=recorded_at,
        )
        if existing.status != AdminApiApprovalLifecycleStatus.REQUESTED:
            raise ApprovalLifecycleError(
                f"Approval request is already {existing.status.value}."
            )
        request_event = store.find_lifecycle_request(
            approval_request_id=approval_request_id
        )
        if request_event is None:
            raise ApprovalLifecycleError("Approval request was not found.")

        approval_id: str | None = None
        expires_at: datetime | None = None
        if body.decision == AdminApiApprovalLifecycleStatus.APPROVED:
            expires_at = _parse_required_future_datetime(
                value=body.expires_at,
                now=recorded_at,
                field_name="expires_at",
            )
            if not body.cap_guard_decision_ref:
                raise ApprovalLifecycleError(
                    "Approved decisions require cap_guard_decision_ref."
                )
            if not body.reconciliation_plan_ref:
                raise ApprovalLifecycleError(
                    "Approved decisions require reconciliation_plan_ref."
                )
            approval_record = AdminApiApprovalRecord(
                created_at=recorded_at,
                expires_at=expires_at,
                approved_by_actor_id=actor_id,
                requested_by_actor_id=request_event.requested_by_actor_id,
                route=request_event.route,
                method=request_event.method,
                module_id=request_event.module_id,
                identity_key=request_event.identity_key,
                identity_value=request_event.identity_value,
                action_class=request_event.action_class,
                required_permission=request_event.required_permission,
                operator_intent=request_event.operator_intent,
                idempotency_key=request_event.idempotency_key,
                payload_hash=request_event.payload_hash,
                cap_guard_decision_ref=body.cap_guard_decision_ref,
                reconciliation_plan_ref=body.reconciliation_plan_ref,
                approval_reason=body.decision_reason,
            )
            approval_id = store.append(approval_record)

        decision_event = AdminApiApprovalLifecycleEvent(
            event_type=AdminApiApprovalLifecycleEventType.DECISION_RECORDED,
            recorded_at=recorded_at,
            approval_request_id=approval_request_id,
            approval_id=approval_id,
            status=body.decision,
            actor_id=actor_id,
            route=request_event.route,
            method=request_event.method,
            module_id=request_event.module_id,
            identity_key=request_event.identity_key,
            identity_value=request_event.identity_value,
            action_class=request_event.action_class,
            required_permission=request_event.required_permission,
            requested_by_actor_id=request_event.requested_by_actor_id,
            operator_intent=request_event.operator_intent,
            idempotency_key=request_event.idempotency_key,
            payload_hash=request_event.payload_hash,
            expires_at=expires_at,
            cap_guard_decision_ref=body.cap_guard_decision_ref,
            reconciliation_plan_ref=body.reconciliation_plan_ref,
            request_reason=request_event.request_reason,
            decision_reason=body.decision_reason,
        )
        store.append_lifecycle_event(decision_event)
        return self.get_request(
            store=store,
            approval_request_id=approval_request_id,
            now=recorded_at,
        )

    def revoke_approval(
        self,
        *,
        store: FileAdminApiApprovalStore,
        approval_id: str,
        actor_id: str,
        reason: str | None,
        now: datetime | None = None,
    ) -> AdminApprovalLifecycleItem:
        recorded_at = _normalize_now(now)
        if store.approval_is_revoked(approval_id):
            raise ApprovalLifecycleError("Approval is already revoked.")
        record = store.find_by_approval_id(approval_id)
        if record is None:
            raise ApprovalLifecycleError("Approval snapshot was not found.")

        linked_events = [
            event
            for event in store.read_lifecycle_events(limit=1000)
            if event.approval_id == approval_id
        ]
        approval_request_id = (
            linked_events[0].approval_request_id if linked_events else approval_id
        )
        revoke_event = AdminApiApprovalLifecycleEvent(
            event_type=AdminApiApprovalLifecycleEventType.APPROVAL_REVOKED,
            recorded_at=recorded_at,
            approval_request_id=approval_request_id,
            approval_id=approval_id,
            status=AdminApiApprovalLifecycleStatus.REVOKED,
            actor_id=actor_id,
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
            expires_at=record.expires_at,
            cap_guard_decision_ref=record.cap_guard_decision_ref,
            reconciliation_plan_ref=record.reconciliation_plan_ref,
            revoke_reason=reason,
        )
        store.append_lifecycle_event(revoke_event)
        return self.get_request(
            store=store,
            approval_request_id=approval_request_id,
            now=recorded_at,
        )

    def list_approvals(
        self,
        *,
        store: FileAdminApiApprovalStore,
        status_filter: AdminApiApprovalLifecycleStatus | None = None,
        limit: int = 100,
        now: datetime | None = None,
    ) -> list[AdminApprovalLifecycleItem]:
        check_time = _normalize_now(now)
        events = list(reversed(store.read_lifecycle_events(limit=1000)))
        grouped: dict[str, list[AdminApiApprovalLifecycleEvent]] = {}
        for event in events:
            grouped.setdefault(event.approval_request_id, []).append(event)
        items = [
            _item_from_events(group, now=check_time)
            for group in grouped.values()
            if group
        ]
        if status_filter is not None:
            items = [item for item in items if item.status == status_filter]
        items.sort(key=lambda item: item.requested_at, reverse=True)
        return items[: max(1, min(limit, 500))]

    def get_request(
        self,
        *,
        store: FileAdminApiApprovalStore,
        approval_request_id: str,
        now: datetime | None = None,
    ) -> AdminApprovalLifecycleItem:
        events = [
            event
            for event in reversed(store.read_lifecycle_events(limit=1000))
            if event.approval_request_id == approval_request_id
        ]
        if not events:
            raise ApprovalLifecycleError("Approval request was not found.")
        return _item_from_events(events, now=_normalize_now(now))

    def _validate_route_binding(self, body: AdminApprovalRequestCreateRequest) -> None:
        method = body.method.upper()
        surface = f"{method} {body.route}"
        route = next(
            (
                item
                for item in ADMIN_API_ROUTE_INVENTORY
                if item.surface == surface
            ),
            None,
        )
        if route is None:
            raise ApprovalLifecycleError(
                "Approval requests must target a route-inventory surface."
            )
        if route.module_id != body.module_id:
            raise ApprovalLifecycleError("Approval request module_id does not match route inventory.")
        if _enum_value(route.action_class) != _enum_value(body.action_class):
            raise ApprovalLifecycleError(
                "Approval request action_class does not match route inventory."
            )
        if _enum_value(route.permission) != _enum_value(body.required_permission):
            raise ApprovalLifecycleError(
                "Approval request required_permission does not match route inventory."
            )
        if route.action_class == AdminApiActionClass.READ_ONLY:
            raise ApprovalLifecycleError("Read-only routes do not require approval.")


def _item_from_events(
    events: list[AdminApiApprovalLifecycleEvent],
    *,
    now: datetime,
) -> AdminApprovalLifecycleItem:
    request_event = events[0]
    latest = events[-1]
    approval_id = next((event.approval_id for event in reversed(events) if event.approval_id), None)
    decision_event = next(
        (
            event
            for event in reversed(events)
            if event.event_type == AdminApiApprovalLifecycleEventType.DECISION_RECORDED
        ),
        None,
    )
    revoke_event = next(
        (
            event
            for event in reversed(events)
            if event.event_type == AdminApiApprovalLifecycleEventType.APPROVAL_REVOKED
        ),
        None,
    )
    status = latest.status
    expired = False
    expires_at = decision_event.expires_at if decision_event is not None else latest.expires_at
    if (
        revoke_event is None
        and status == AdminApiApprovalLifecycleStatus.APPROVED
        and expires_at is not None
        and _normalize_datetime(expires_at) <= now
    ):
        status = AdminApiApprovalLifecycleStatus.EXPIRED
        expired = True
    elif expires_at is not None and _normalize_datetime(expires_at) <= now:
        expired = True
    if revoke_event is not None:
        status = AdminApiApprovalLifecycleStatus.REVOKED

    detail = _detail_for_status(status)
    return AdminApprovalLifecycleItem(
        approval_request_id=request_event.approval_request_id,
        approval_id=approval_id,
        status=status,
        requested_at=request_event.recorded_at.isoformat(),
        decided_at=(
            decision_event.recorded_at.isoformat()
            if decision_event is not None
            else None
        ),
        revoked_at=(
            revoke_event.recorded_at.isoformat()
            if revoke_event is not None
            else None
        ),
        expires_at=expires_at.isoformat() if expires_at is not None else None,
        expired=expired,
        route=request_event.route,
        method=request_event.method,
        module_id=request_event.module_id,
        identity_key=request_event.identity_key,
        identity_value=request_event.identity_value,
        action_class=request_event.action_class,
        required_permission=request_event.required_permission,
        requested_by_actor_id=request_event.requested_by_actor_id,
        decision_actor_id=decision_event.actor_id if decision_event is not None else None,
        revoked_by_actor_id=revoke_event.actor_id if revoke_event is not None else None,
        operator_intent=request_event.operator_intent,
        command_idempotency_key=request_event.idempotency_key,
        payload_hash=request_event.payload_hash,
        cap_guard_decision_ref=(
            decision_event.cap_guard_decision_ref
            if decision_event is not None
            else None
        ),
        reconciliation_plan_ref=(
            decision_event.reconciliation_plan_ref
            if decision_event is not None
            else None
        ),
        request_reason=request_event.request_reason,
        decision_reason=decision_event.decision_reason if decision_event is not None else None,
        revoke_reason=revoke_event.revoke_reason if revoke_event is not None else None,
        snapshot_linked=approval_id is not None and revoke_event is None and not expired,
        live_execution_authority=False,
        live_exchange_submitted=False,
        browser_authority="display_only",
        bff_authority="forward_only_no_execution",
        detail=detail,
    )


def _detail_for_status(status: AdminApiApprovalLifecycleStatus) -> str:
    if status == AdminApiApprovalLifecycleStatus.REQUESTED:
        return "Approval request is pending backend decision."
    if status == AdminApiApprovalLifecycleStatus.APPROVED:
        return "Approval snapshot is linked, expiring, and still not sufficient for live execution by itself."
    if status == AdminApiApprovalLifecycleStatus.REJECTED:
        return "Approval request was rejected and no snapshot was linked."
    if status == AdminApiApprovalLifecycleStatus.REVOKED:
        return "Approval snapshot was revoked and cannot resolve command admission."
    return "Approval snapshot is expired and cannot resolve command admission."


def _parse_required_future_datetime(
    *,
    value: str | None,
    now: datetime,
    field_name: str,
) -> datetime:
    if not value:
        raise ApprovalLifecycleError(f"Approved decisions require {field_name}.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApprovalLifecycleError(f"{field_name} must be an ISO datetime.") from exc
    parsed = _normalize_datetime(parsed)
    if parsed <= now:
        raise ApprovalLifecycleError(f"{field_name} must be in the future.")
    return parsed


def _normalize_now(value: datetime | None) -> datetime:
    return _normalize_datetime(value or datetime.now(timezone.utc))


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _enum_value(value: AdminApiActionClass | AdminApiPermission | str) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)
