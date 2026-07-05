"""Backend-owned live-adapter construction decision evidence service."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from core.enums import (
    AdminApiActionClass,
    AdminApiGateStatus,
    AdminApiLiveExecutionStatus,
    AdminApiPermission,
)

from .command_service import AdminApiCommandService
from .live_execution import (
    FileAdminApiLiveAdapterDecisionStore,
    LIVE_ADAPTER_DECISION_METHOD,
    LIVE_ADAPTER_DECISION_MODULE_ID,
    LIVE_ADAPTER_DECISION_REQUIRED_PERMISSION,
    LIVE_ADAPTER_DECISION_ROUTE,
    LIVE_ADAPTER_DECISION_SERVICE_METHOD,
    LIVE_ADAPTER_DECISION_SOURCE,
    LIVE_EXECUTION_ADAPTER_CONSTRUCTION_AUTHORITY,
    LIVE_EXECUTION_ADAPTER_REQUIRED_CONSTRUCTION_ARTIFACTS,
    LiveAdapterDecisionRecord,
)
from .models import (
    AdminLiveAdapterDecisionCreateRequest,
    AdminLiveAdapterDecisionItem,
)
from .route_inventory import ADMIN_API_ROUTE_INVENTORY


class LiveAdapterDecisionError(ValueError):
    """Raised when a live-adapter decision record is invalid."""


class AdminApiLiveAdapterDecisionService:
    """Service boundary for append-only live-adapter decision records."""

    def record_decision(
        self,
        *,
        store: FileAdminApiLiveAdapterDecisionStore,
        body: AdminLiveAdapterDecisionCreateRequest,
        now: datetime | None = None,
    ) -> AdminLiveAdapterDecisionItem:
        recorded_at = _normalize_now(now)
        self._validate_route_binding()
        self._validate_target_binding(body)
        self._validate_decision_consistency(body)

        record = LiveAdapterDecisionRecord(
            decision_id=body.decision_id,
            recorded_at=recorded_at.isoformat(),
            status=body.status,
            requested_adapter_status=body.requested_adapter_status,
            target_route=body.target_route,
            target_method=body.target_method,
            target_module_id=body.target_module_id,
            target_service_method=body.target_service_method,
            account_family=body.account_family,
            venue_scope=body.venue_scope,
            intx_applicability=body.intx_applicability,
            product_scope=body.product_scope,
            adapter_reference=body.adapter_reference,
            adapter_constructed=body.adapter_constructed,
            adapter_enabled=body.adapter_enabled,
            construction_review_ref=body.construction_review_ref,
            decision_reason=body.decision_reason,
            live_coinbase_execution_approved=body.live_coinbase_execution_approved,
            max_submitted_notional_usdc=body.max_submitted_notional_usdc,
            max_executed_notional_usdc=body.max_executed_notional_usdc,
        )
        if not store.append_if_decision_id_absent(record):
            raise LiveAdapterDecisionError("Live-adapter decision already exists.")
        return _item_from_record(record)

    def list_decisions(
        self,
        *,
        store: FileAdminApiLiveAdapterDecisionStore,
        status_filter: AdminApiGateStatus | None = None,
        limit: int = 100,
    ) -> list[AdminLiveAdapterDecisionItem]:
        records = store.read_recent(limit=limit)
        items = [_item_from_record(record) for record in records]
        if status_filter is not None:
            items = [item for item in items if item.status == status_filter]
        return items

    def get_decision(
        self,
        *,
        store: FileAdminApiLiveAdapterDecisionStore,
        decision_id: str,
    ) -> AdminLiveAdapterDecisionItem:
        record = store.find_by_decision_id(decision_id)
        if record is None:
            raise LiveAdapterDecisionError("Live-adapter decision was not found.")
        return _item_from_record(record)

    @staticmethod
    def _validate_route_binding() -> None:
        surface = f"{LIVE_ADAPTER_DECISION_METHOD} {LIVE_ADAPTER_DECISION_ROUTE}"
        route = next(
            (item for item in ADMIN_API_ROUTE_INVENTORY if item.surface == surface),
            None,
        )
        if route is None:
            raise LiveAdapterDecisionError(
                "Live-adapter decisions must target a route-inventory surface."
            )
        if route.module_id != LIVE_ADAPTER_DECISION_MODULE_ID:
            raise LiveAdapterDecisionError(
                "Live-adapter decision module_id does not match route inventory."
            )
        if route.action_class != AdminApiActionClass.LOCAL_STATE_MUTATION:
            raise LiveAdapterDecisionError(
                "Live-adapter decision action_class does not match route inventory."
            )
        if route.permission != LIVE_ADAPTER_DECISION_REQUIRED_PERMISSION:
            raise LiveAdapterDecisionError(
                "Live-adapter decision permission does not match route inventory."
            )
        if route.shared_method != LIVE_ADAPTER_DECISION_SERVICE_METHOD:
            raise LiveAdapterDecisionError(
                "Live-adapter decision service_method does not match route inventory."
            )

    @staticmethod
    def _validate_target_binding(body: AdminLiveAdapterDecisionCreateRequest) -> None:
        surface = f"{body.target_method} {body.target_route}"
        route = next(
            (item for item in ADMIN_API_ROUTE_INVENTORY if item.surface == surface),
            None,
        )
        if route is None:
            raise LiveAdapterDecisionError(
                "Live-adapter decision target route is not in route inventory."
            )
        if route.module_id != body.target_module_id:
            raise LiveAdapterDecisionError(
                "Live-adapter decision target module_id does not match route inventory."
            )
        if body.target_method.upper() != "POST":
            raise LiveAdapterDecisionError(
                "Live-adapter decision target must be a POST command surface."
            )
        if route.action_class == AdminApiActionClass.READ_ONLY:
            raise LiveAdapterDecisionError(
                "Live-adapter decision target cannot be a read-only surface."
            )
        if route.shared_method != body.target_service_method:
            raise LiveAdapterDecisionError(
                "Live-adapter decision target service_method does not match route inventory."
            )
        if not hasattr(AdminApiCommandService, body.target_service_method):
            raise LiveAdapterDecisionError(
                "Live-adapter decision target service_method is not on AdminApiCommandService."
            )
        expected_adapter_reference = (
            f"AdminApiCommandService.{body.target_service_method}"
        )
        if body.adapter_reference != expected_adapter_reference:
            raise LiveAdapterDecisionError(
                "Live-adapter decision adapter_reference does not match target service."
            )

    @staticmethod
    def _validate_decision_consistency(
        body: AdminLiveAdapterDecisionCreateRequest,
    ) -> None:
        if body.adapter_constructed:
            raise LiveAdapterDecisionError(
                "This phase cannot record constructed live-adapter decisions."
            )
        if body.adapter_enabled:
            raise LiveAdapterDecisionError(
                "This phase cannot record enabled live-adapter decisions."
            )
        if body.live_coinbase_execution_approved:
            raise LiveAdapterDecisionError(
                "This phase cannot approve live Coinbase execution."
            )
        if body.status == AdminApiGateStatus.PASSED:
            raise LiveAdapterDecisionError(
                "This phase cannot record passed live-adapter decisions."
            )
        if body.requested_adapter_status != AdminApiLiveExecutionStatus.LIVE_DISABLED:
            raise LiveAdapterDecisionError(
                "This phase can only record live-disabled adapter decisions."
            )
        if _decimal_value(body.max_submitted_notional_usdc) != Decimal("0"):
            raise LiveAdapterDecisionError(
                "This phase cannot record submitted live Coinbase notional."
            )
        if _decimal_value(body.max_executed_notional_usdc) != Decimal("0"):
            raise LiveAdapterDecisionError(
                "This phase cannot record executed live Coinbase notional."
            )


def _item_from_record(
    record: LiveAdapterDecisionRecord,
) -> AdminLiveAdapterDecisionItem:
    required_artifacts = list(LIVE_EXECUTION_ADAPTER_REQUIRED_CONSTRUCTION_ARTIFACTS)
    recorded_artifacts = ["explicit_backend_live_adapter_construction_decision"]
    detail = (
        "Live-adapter decision evidence is recorded as fail-closed local state; "
        "it does not construct an adapter, resolve construction, or permit "
        "Coinbase execution."
    )
    return AdminLiveAdapterDecisionItem(
        decision_id=record.decision_id,
        recorded_at=record.recorded_at,
        route=LIVE_ADAPTER_DECISION_ROUTE,
        method=LIVE_ADAPTER_DECISION_METHOD,
        module_id=LIVE_ADAPTER_DECISION_MODULE_ID,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        required_permission=LIVE_ADAPTER_DECISION_REQUIRED_PERMISSION,
        service_method=LIVE_ADAPTER_DECISION_SERVICE_METHOD,
        status=record.status,
        requested_adapter_status=record.requested_adapter_status,
        live_execution_adapter_status=AdminApiLiveExecutionStatus.LIVE_DISABLED,
        target_route=record.target_route,
        target_method=record.target_method,
        target_module_id=record.target_module_id,
        target_service_method=record.target_service_method,
        account_family=record.account_family,
        venue_scope=record.venue_scope,
        intx_applicability=record.intx_applicability,
        product_scope=record.product_scope,
        adapter_reference=record.adapter_reference,
        adapter_constructed=record.adapter_constructed,
        adapter_enabled=record.adapter_enabled,
        source=LIVE_ADAPTER_DECISION_SOURCE,
        construction_review_ref=record.construction_review_ref,
        decision_reason=record.decision_reason,
        live_coinbase_execution_approved=record.live_coinbase_execution_approved,
        max_submitted_notional_usdc=record.max_submitted_notional_usdc,
        max_executed_notional_usdc=record.max_executed_notional_usdc,
        construction_precondition_required=True,
        construction_precondition_resolved=False,
        construction_precondition_authority=(
            LIVE_EXECUTION_ADAPTER_CONSTRUCTION_AUTHORITY
        ),
        required_construction_artifacts=required_artifacts,
        recorded_construction_artifacts=recorded_artifacts,
        missing_construction_artifacts=required_artifacts,
        route_mapping_satisfies_construction=False,
        adapter_configuration_satisfies_construction=False,
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
        raise LiveAdapterDecisionError(
            "Notional fields must be decimal strings."
        ) from exc
