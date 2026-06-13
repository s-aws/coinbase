"""Backend-owned reconciliation plan record service for Admin API admission."""

from __future__ import annotations

from datetime import datetime, timezone

from core.enums import (
    AdminApiActionClass,
    AdminApiGateStatus,
    AdminApiPermission,
)

from .models import (
    AdminReconciliationPlanCreateRequest,
    AdminReconciliationPlanItem,
)
from .reconciliation import (
    FileAdminApiReconciliationStore,
    ReconciliationPlanRecord,
)
from .route_inventory import ADMIN_API_ROUTE_INVENTORY


class ReconciliationPlanError(ValueError):
    """Raised when a reconciliation plan record is invalid."""


class AdminApiReconciliationPlanService:
    """Service boundary for append-only reconciliation plan records."""

    def record_plan(
        self,
        *,
        store: FileAdminApiReconciliationStore,
        body: AdminReconciliationPlanCreateRequest,
        now: datetime | None = None,
    ) -> AdminReconciliationPlanItem:
        recorded_at = _normalize_now(now)
        self._validate_route_binding(body)
        self._validate_plan_consistency(body)
        if store.find_by_plan_id(body.approval_reconciliation_plan_ref) is not None:
            raise ReconciliationPlanError("Reconciliation plan already exists.")

        record = ReconciliationPlanRecord(
            plan_id=body.approval_reconciliation_plan_ref,
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
            cap_guard_decision_id=body.cap_guard_decision_id,
            allowed=body.allowed,
            status=body.status,
            reconciliation_policy_ref=body.reconciliation_policy_ref,
            product_scope=body.product_scope,
            exchange_submission_required=body.exchange_submission_required,
            post_submit_reconciliation_required=(
                body.post_submit_reconciliation_required
            ),
            retained_inventory_required=body.retained_inventory_required,
            max_submitted_notional_usdc=body.max_submitted_notional_usdc,
            max_executed_notional_usdc=body.max_executed_notional_usdc,
            reason=body.reason,
        )
        store.append(record)
        return _item_from_record(record)

    def list_plans(
        self,
        *,
        store: FileAdminApiReconciliationStore,
        status_filter: AdminApiGateStatus | None = None,
        limit: int = 100,
    ) -> list[AdminReconciliationPlanItem]:
        records = store.read_recent(limit=limit)
        items = [_item_from_record(record) for record in records]
        if status_filter is not None:
            items = [item for item in items if item.status == status_filter]
        return items

    def get_plan(
        self,
        *,
        store: FileAdminApiReconciliationStore,
        plan_id: str,
    ) -> AdminReconciliationPlanItem:
        record = store.find_by_plan_id(plan_id)
        if record is None:
            raise ReconciliationPlanError("Reconciliation plan was not found.")
        return _item_from_record(record)

    def _validate_route_binding(
        self,
        body: AdminReconciliationPlanCreateRequest,
    ) -> None:
        method = body.method.upper()
        surface = f"{method} {body.route}"
        route = next(
            (item for item in ADMIN_API_ROUTE_INVENTORY if item.surface == surface),
            None,
        )
        if route is None:
            raise ReconciliationPlanError(
                "Reconciliation plans must target a route-inventory surface."
            )
        if route.module_id != body.module_id:
            raise ReconciliationPlanError(
                "Reconciliation plan module_id does not match route inventory."
            )
        if _enum_value(route.action_class) != _enum_value(body.action_class):
            raise ReconciliationPlanError(
                "Reconciliation plan action_class does not match route inventory."
            )
        if _enum_value(route.permission) != _enum_value(body.required_permission):
            raise ReconciliationPlanError(
                "Reconciliation plan required_permission does not match route inventory."
            )
        if route.shared_method != body.service_method:
            raise ReconciliationPlanError(
                "Reconciliation plan service_method does not match route inventory."
            )
        if route.action_class in {
            AdminApiActionClass.READ_ONLY,
            AdminApiActionClass.LOCAL_STATE_MUTATION,
        }:
            raise ReconciliationPlanError(
                "Reconciliation plans are only valid for live-shaped command routes."
            )

    @staticmethod
    def _validate_plan_consistency(
        body: AdminReconciliationPlanCreateRequest,
    ) -> None:
        resolver_eligible = body.allowed and body.status == AdminApiGateStatus.PASSED
        if resolver_eligible:
            return
        if body.allowed or body.status == AdminApiGateStatus.PASSED:
            raise ReconciliationPlanError(
                "Reconciliation allowed must be true only for passed plans."
            )


def _item_from_record(record: ReconciliationPlanRecord) -> AdminReconciliationPlanItem:
    resolver_eligible = record.allowed and record.status == AdminApiGateStatus.PASSED
    detail = (
        "Reconciliation plan is resolver-eligible for an exact backend admission "
        "match."
        if resolver_eligible
        else "Reconciliation plan is durable evidence only and will fail closed."
    )
    return AdminReconciliationPlanItem(
        plan_id=record.plan_id,
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
        cap_guard_decision_id=record.cap_guard_decision_id,
        allowed=record.allowed,
        status=record.status,
        source=record.source,
        reconciliation_policy_ref=record.reconciliation_policy_ref,
        product_scope=record.product_scope,
        exchange_submission_required=record.exchange_submission_required,
        post_submit_reconciliation_required=(
            record.post_submit_reconciliation_required
        ),
        retained_inventory_required=record.retained_inventory_required,
        max_submitted_notional_usdc=record.max_submitted_notional_usdc,
        max_executed_notional_usdc=record.max_executed_notional_usdc,
        reason=record.reason,
        resolver_eligible=resolver_eligible,
        browser_authority="display_only",
        bff_authority="forward_only_no_execution",
        reconciliation_execution_ran=False,
        order_exchange_state_mutated=False,
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
