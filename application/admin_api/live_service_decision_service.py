"""Backend-owned live-service enablement decision evidence service."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from core.enums import (
    AdminApiActionClass,
    AdminApiGateStatus,
    AdminApiLiveExecutionStatus,
    AdminApiPermission,
)

from .live_execution import (
    FileAdminApiLiveServiceDecisionStore,
    LIVE_EXECUTION_SERVICE_REQUIRED_ENABLEMENT_ARTIFACTS,
    LIVE_EXECUTION_SERVICE_ENABLEMENT_AUTHORITY,
    LIVE_SERVICE_DECISION_METHOD,
    LIVE_SERVICE_DECISION_MODULE_ID,
    LIVE_SERVICE_DECISION_REQUIRED_PERMISSION,
    LIVE_SERVICE_DECISION_ROUTE,
    LIVE_SERVICE_DECISION_SERVICE_METHOD,
    LIVE_SERVICE_DECISION_SOURCE,
    LiveServiceDecisionRecord,
)
from .models import (
    AdminLiveServiceDecisionCreateRequest,
    AdminLiveServiceDecisionItem,
)
from .route_inventory import ADMIN_API_ROUTE_INVENTORY


class LiveServiceDecisionError(ValueError):
    """Raised when a live-service decision record is invalid."""


class AdminApiLiveServiceDecisionService:
    """Service boundary for append-only live-service decision records."""

    def record_decision(
        self,
        *,
        store: FileAdminApiLiveServiceDecisionStore,
        body: AdminLiveServiceDecisionCreateRequest,
        now: datetime | None = None,
    ) -> AdminLiveServiceDecisionItem:
        recorded_at = _normalize_now(now)
        self._validate_route_binding()
        self._validate_decision_consistency(body)
        if store.find_by_decision_id(body.decision_id) is not None:
            raise LiveServiceDecisionError("Live-service decision already exists.")

        record = LiveServiceDecisionRecord(
            decision_id=body.decision_id,
            recorded_at=recorded_at.isoformat(),
            status=body.status,
            requested_service_status=body.requested_service_status,
            service_enabled=body.service_enabled,
            deployment_ref=body.deployment_ref,
            runtime_configuration_ref=body.runtime_configuration_ref,
            decision_reason=body.decision_reason,
            live_coinbase_execution_approved=body.live_coinbase_execution_approved,
            max_submitted_notional_usdc=body.max_submitted_notional_usdc,
            max_executed_notional_usdc=body.max_executed_notional_usdc,
        )
        store.append(record)
        return _item_from_record(record)

    def list_decisions(
        self,
        *,
        store: FileAdminApiLiveServiceDecisionStore,
        status_filter: AdminApiGateStatus | None = None,
        limit: int = 100,
    ) -> list[AdminLiveServiceDecisionItem]:
        records = store.read_recent(limit=limit)
        items = [_item_from_record(record) for record in records]
        if status_filter is not None:
            items = [item for item in items if item.status == status_filter]
        return items

    def get_decision(
        self,
        *,
        store: FileAdminApiLiveServiceDecisionStore,
        decision_id: str,
    ) -> AdminLiveServiceDecisionItem:
        record = store.find_by_decision_id(decision_id)
        if record is None:
            raise LiveServiceDecisionError("Live-service decision was not found.")
        return _item_from_record(record)

    @staticmethod
    def _validate_route_binding() -> None:
        surface = f"{LIVE_SERVICE_DECISION_METHOD} {LIVE_SERVICE_DECISION_ROUTE}"
        route = next(
            (item for item in ADMIN_API_ROUTE_INVENTORY if item.surface == surface),
            None,
        )
        if route is None:
            raise LiveServiceDecisionError(
                "Live-service decisions must target a route-inventory surface."
            )
        if route.module_id != LIVE_SERVICE_DECISION_MODULE_ID:
            raise LiveServiceDecisionError(
                "Live-service decision module_id does not match route inventory."
            )
        if route.action_class != AdminApiActionClass.LOCAL_STATE_MUTATION:
            raise LiveServiceDecisionError(
                "Live-service decision action_class does not match route inventory."
            )
        if route.permission != LIVE_SERVICE_DECISION_REQUIRED_PERMISSION:
            raise LiveServiceDecisionError(
                "Live-service decision permission does not match route inventory."
            )
        if route.shared_method != LIVE_SERVICE_DECISION_SERVICE_METHOD:
            raise LiveServiceDecisionError(
                "Live-service decision service_method does not match route inventory."
            )

    @staticmethod
    def _validate_decision_consistency(
        body: AdminLiveServiceDecisionCreateRequest,
    ) -> None:
        if body.service_enabled:
            raise LiveServiceDecisionError(
                "This phase cannot record enabled live-service decisions."
            )
        if body.live_coinbase_execution_approved:
            raise LiveServiceDecisionError(
                "This phase cannot approve live Coinbase execution."
            )
        if body.status == AdminApiGateStatus.PASSED:
            raise LiveServiceDecisionError(
                "This phase cannot record passed live-service decisions."
            )
        if body.requested_service_status != AdminApiLiveExecutionStatus.LIVE_DISABLED:
            raise LiveServiceDecisionError(
                "This phase can only record live-disabled service decisions."
            )
        if _decimal_value(body.max_submitted_notional_usdc) != Decimal("0"):
            raise LiveServiceDecisionError(
                "This phase cannot record submitted live Coinbase notional."
            )
        if _decimal_value(body.max_executed_notional_usdc) != Decimal("0"):
            raise LiveServiceDecisionError(
                "This phase cannot record executed live Coinbase notional."
            )


def _item_from_record(
    record: LiveServiceDecisionRecord,
) -> AdminLiveServiceDecisionItem:
    required_artifacts = list(LIVE_EXECUTION_SERVICE_REQUIRED_ENABLEMENT_ARTIFACTS)
    recorded_artifacts = ["explicit_backend_live_enablement_decision"]
    detail = (
        "Live-service decision evidence is recorded as fail-closed local state; "
        "it does not resolve live-service enablement or permit Coinbase execution."
    )
    return AdminLiveServiceDecisionItem(
        decision_id=record.decision_id,
        recorded_at=record.recorded_at,
        route=LIVE_SERVICE_DECISION_ROUTE,
        method=LIVE_SERVICE_DECISION_METHOD,
        module_id=LIVE_SERVICE_DECISION_MODULE_ID,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        required_permission=LIVE_SERVICE_DECISION_REQUIRED_PERMISSION,
        service_method=LIVE_SERVICE_DECISION_SERVICE_METHOD,
        status=record.status,
        requested_service_status=record.requested_service_status,
        live_execution_service_status=AdminApiLiveExecutionStatus.LIVE_DISABLED,
        service_enabled=record.service_enabled,
        source=LIVE_SERVICE_DECISION_SOURCE,
        deployment_ref=record.deployment_ref,
        runtime_configuration_ref=record.runtime_configuration_ref,
        decision_reason=record.decision_reason,
        live_coinbase_execution_approved=record.live_coinbase_execution_approved,
        max_submitted_notional_usdc=record.max_submitted_notional_usdc,
        max_executed_notional_usdc=record.max_executed_notional_usdc,
        enablement_precondition_required=True,
        enablement_precondition_resolved=False,
        enablement_precondition_authority=LIVE_EXECUTION_SERVICE_ENABLEMENT_AUTHORITY,
        required_enablement_artifacts=required_artifacts,
        recorded_enablement_artifacts=recorded_artifacts,
        missing_enablement_artifacts=required_artifacts,
        resolver_eligible=False,
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


def _decimal_value(value: str) -> Decimal:
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise LiveServiceDecisionError("Notional fields must be decimal strings.") from exc

