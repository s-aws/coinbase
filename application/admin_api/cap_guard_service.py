"""Backend-owned cap/guard decision record service for Admin API admission."""

from __future__ import annotations

from datetime import datetime, timezone

from core.enums import (
    AdminApiActionClass,
    AdminApiGateStatus,
    AdminApiPermission,
)

from .cap_guard import CapGuardDecisionRecord, FileAdminApiCapGuardStore
from .models import AdminCapGuardDecisionCreateRequest, AdminCapGuardDecisionItem
from .route_inventory import ADMIN_API_ROUTE_INVENTORY


class CapGuardDecisionError(ValueError):
    """Raised when a cap/guard decision record is invalid."""


class AdminApiCapGuardDecisionService:
    """Service boundary for append-only cap/guard decision records."""

    def record_decision(
        self,
        *,
        store: FileAdminApiCapGuardStore,
        body: AdminCapGuardDecisionCreateRequest,
        now: datetime | None = None,
    ) -> AdminCapGuardDecisionItem:
        recorded_at = _normalize_now(now)
        self._validate_route_binding(body)
        self._validate_decision_consistency(body)
        if store.find_by_decision_id(body.approval_cap_guard_decision_ref) is not None:
            raise CapGuardDecisionError("Cap/guard decision already exists.")

        record = CapGuardDecisionRecord(
            decision_id=body.approval_cap_guard_decision_ref,
            recorded_at=recorded_at.isoformat(),
            route=body.route,
            method=body.method.upper(),
            module_id=body.module_id,
            identity_key=body.identity_key,
            identity_value=body.identity_value,
            action_class=body.action_class,
            required_permission=body.required_permission,
            service_method=body.service_method,
            actor_id=body.actor_id,
            operator_intent=body.operator_intent,
            idempotency_key=body.command_idempotency_key,
            payload_hash=body.payload_hash,
            approval_snapshot_id=body.approval_snapshot_id,
            admission_audit_id=body.admission_audit_id,
            allowed=body.allowed,
            status=body.status,
            cap_policy_ref=body.cap_policy_ref,
            guard_policy_ref=body.guard_policy_ref,
            product_scope=body.product_scope,
            max_submitted_notional_usdc=body.max_submitted_notional_usdc,
            max_executed_notional_usdc=body.max_executed_notional_usdc,
            reason=body.reason,
        )
        store.append(record)
        return _item_from_record(record)

    def list_decisions(
        self,
        *,
        store: FileAdminApiCapGuardStore,
        status_filter: AdminApiGateStatus | None = None,
        limit: int = 100,
    ) -> list[AdminCapGuardDecisionItem]:
        records = store.read_recent(limit=limit)
        items = [_item_from_record(record) for record in records]
        if status_filter is not None:
            items = [item for item in items if item.status == status_filter]
        return items

    def get_decision(
        self,
        *,
        store: FileAdminApiCapGuardStore,
        decision_id: str,
    ) -> AdminCapGuardDecisionItem:
        record = store.find_by_decision_id(decision_id)
        if record is None:
            raise CapGuardDecisionError("Cap/guard decision was not found.")
        return _item_from_record(record)

    def _validate_route_binding(
        self,
        body: AdminCapGuardDecisionCreateRequest,
    ) -> None:
        method = body.method.upper()
        surface = f"{method} {body.route}"
        route = next(
            (item for item in ADMIN_API_ROUTE_INVENTORY if item.surface == surface),
            None,
        )
        if route is None:
            raise CapGuardDecisionError(
                "Cap/guard decisions must target a route-inventory surface."
            )
        if route.module_id != body.module_id:
            raise CapGuardDecisionError(
                "Cap/guard decision module_id does not match route inventory."
            )
        if _enum_value(route.action_class) != _enum_value(body.action_class):
            raise CapGuardDecisionError(
                "Cap/guard decision action_class does not match route inventory."
            )
        if _enum_value(route.permission) != _enum_value(body.required_permission):
            raise CapGuardDecisionError(
                "Cap/guard decision required_permission does not match route inventory."
            )
        if route.shared_method != body.service_method:
            raise CapGuardDecisionError(
                "Cap/guard decision service_method does not match route inventory."
            )
        if route.action_class == AdminApiActionClass.READ_ONLY:
            raise CapGuardDecisionError(
                "Read-only routes do not require cap/guard decisions."
            )
        if route.caps == "not applicable":
            raise CapGuardDecisionError(
                "Route inventory marks cap/guard decisions as not applicable."
            )

    @staticmethod
    def _validate_decision_consistency(
        body: AdminCapGuardDecisionCreateRequest,
    ) -> None:
        resolver_eligible = body.allowed and body.status == AdminApiGateStatus.PASSED
        if resolver_eligible:
            return
        if body.allowed or body.status == AdminApiGateStatus.PASSED:
            raise CapGuardDecisionError(
                "Cap/guard allowed must be true only for passed decisions."
            )


def _item_from_record(record: CapGuardDecisionRecord) -> AdminCapGuardDecisionItem:
    resolver_eligible = record.allowed and record.status == AdminApiGateStatus.PASSED
    detail = (
        "Cap/guard decision is resolver-eligible for an exact backend admission "
        "match."
        if resolver_eligible
        else "Cap/guard decision is durable evidence only and will fail closed."
    )
    return AdminCapGuardDecisionItem(
        decision_id=record.decision_id,
        recorded_at=record.recorded_at,
        route=record.route,
        method=record.method,
        module_id=record.module_id,
        identity_key=record.identity_key,
        identity_value=record.identity_value,
        action_class=record.action_class,
        required_permission=record.required_permission,
        service_method=record.service_method,
        actor_id=record.actor_id,
        operator_intent=record.operator_intent,
        command_idempotency_key=record.idempotency_key,
        payload_hash=record.payload_hash,
        approval_snapshot_id=record.approval_snapshot_id,
        admission_audit_id=record.admission_audit_id,
        allowed=record.allowed,
        status=record.status,
        source=record.source,
        cap_policy_ref=record.cap_policy_ref,
        guard_policy_ref=record.guard_policy_ref,
        product_scope=record.product_scope,
        max_submitted_notional_usdc=record.max_submitted_notional_usdc,
        max_executed_notional_usdc=record.max_executed_notional_usdc,
        reason=record.reason,
        resolver_eligible=resolver_eligible,
        browser_authority="display_only",
        bff_authority="forward_only_no_execution",
        live_exchange_submitted=False,
        live_coinbase_orders_ran=False,
        detail=detail,
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
