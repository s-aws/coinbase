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
    live_service_decision_allows_backend_admission,
)
from .models import (
    AdminLiveServiceDecisionCreateRequest,
    AdminLiveServiceDecisionItem,
)
from .operator_mvp_policy import (
    OPERATOR_MVP_MAX_EXECUTED_NOTIONAL_USDC,
    OPERATOR_MVP_MAX_SUBMITTED_NOTIONAL_USDC,
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
            target_module_id=body.target_module_id,
            account_family=body.account_family,
            venue_scope=body.venue_scope,
            intx_applicability=body.intx_applicability,
            product_scope=body.product_scope,
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
        if body.target_module_id == "futures_perpetuals":
            raise LiveServiceDecisionError(
                "Futures command service is source-disabled; live-service "
                "decision records cannot enable or authorize it."
            )
        submitted_notional = _decimal_value(body.max_submitted_notional_usdc)
        executed_notional = _decimal_value(body.max_executed_notional_usdc)
        if not body.service_enabled:
            if body.live_coinbase_execution_approved:
                raise LiveServiceDecisionError(
                    "Disabled live-service decisions cannot approve live Coinbase execution."
                )
            if body.status == AdminApiGateStatus.PASSED:
                raise LiveServiceDecisionError(
                    "Disabled live-service decisions cannot record passed status."
                )
            if body.requested_service_status != AdminApiLiveExecutionStatus.LIVE_DISABLED:
                raise LiveServiceDecisionError(
                    "Disabled live-service decisions must request live-disabled status."
                )
            if submitted_notional != Decimal("0"):
                raise LiveServiceDecisionError(
                    "Disabled live-service decisions cannot record submitted live Coinbase notional."
                )
            if executed_notional != Decimal("0"):
                raise LiveServiceDecisionError(
                    "Disabled live-service decisions cannot record executed live Coinbase notional."
                )
            return

        if body.status != AdminApiGateStatus.PASSED:
            raise LiveServiceDecisionError(
                "Enabled live-service decisions must record passed status."
            )
        if body.requested_service_status == AdminApiLiveExecutionStatus.LIVE_DISABLED:
            raise LiveServiceDecisionError(
                "Enabled live-service decisions must request a non-disabled service status."
            )
        if not body.live_coinbase_execution_approved:
            raise LiveServiceDecisionError(
                "Enabled live-service decisions must explicitly approve live Coinbase execution."
            )
        if submitted_notional <= Decimal("0"):
            raise LiveServiceDecisionError(
                "Enabled live-service decisions require a positive submitted notional cap."
            )
        if executed_notional <= Decimal("0"):
            raise LiveServiceDecisionError(
                "Enabled live-service decisions require a positive executed notional cap."
            )
        if executed_notional > submitted_notional:
            raise LiveServiceDecisionError(
                "Enabled live-service decisions cannot execute more notional than submitted."
            )
        if submitted_notional > OPERATOR_MVP_MAX_SUBMITTED_NOTIONAL_USDC:
            raise LiveServiceDecisionError(
                "Live-service decision exceeds the installed MVP submitted-notional ceiling."
            )
        if executed_notional > OPERATOR_MVP_MAX_EXECUTED_NOTIONAL_USDC:
            raise LiveServiceDecisionError(
                "Live-service decision exceeds the installed MVP executed-notional ceiling."
            )


def _item_from_record(
    record: LiveServiceDecisionRecord,
) -> AdminLiveServiceDecisionItem:
    source_disabled_futures_record = (
        record.target_module_id == "futures_perpetuals"
    )
    required_artifacts = list(LIVE_EXECUTION_SERVICE_REQUIRED_ENABLEMENT_ARTIFACTS)
    resolver_eligible = bool(
        not source_disabled_futures_record
        and live_service_decision_allows_backend_admission(record)
    )
    recorded_artifacts = (
        required_artifacts
        if resolver_eligible
        else ["explicit_backend_live_enablement_decision"]
    )
    missing_artifacts = [] if resolver_eligible else required_artifacts
    detail = (
        "Persisted predecessor Futures live-service evidence is historical and "
        "source-disabled; it cannot enable or authorize execution."
        if source_disabled_futures_record
        else
        "Live-service decision is resolver-eligible for backend runtime admission; "
        "browser and BFF layers still cannot execute Coinbase orders."
        if resolver_eligible
        else (
            "Live-service decision evidence is recorded as fail-closed local state; "
            "it does not resolve live-service enablement or permit Coinbase execution."
        )
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
        status=(
            AdminApiGateStatus.BLOCKED
            if source_disabled_futures_record
            else record.status
        ),
        requested_service_status=record.requested_service_status,
        live_execution_service_status=(
            record.requested_service_status
            if resolver_eligible
            else AdminApiLiveExecutionStatus.LIVE_DISABLED
        ),
        service_enabled=(
            False if source_disabled_futures_record else record.service_enabled
        ),
        target_module_id=record.target_module_id,
        account_family=record.account_family,
        venue_scope=record.venue_scope,
        intx_applicability=record.intx_applicability,
        product_scope=record.product_scope,
        source=LIVE_SERVICE_DECISION_SOURCE,
        deployment_ref=record.deployment_ref,
        runtime_configuration_ref=record.runtime_configuration_ref,
        decision_reason=record.decision_reason,
        live_coinbase_execution_approved=(
            False
            if source_disabled_futures_record
            else record.live_coinbase_execution_approved
        ),
        max_submitted_notional_usdc=(
            "0"
            if source_disabled_futures_record
            else record.max_submitted_notional_usdc
        ),
        max_executed_notional_usdc=(
            "0"
            if source_disabled_futures_record
            else record.max_executed_notional_usdc
        ),
        enablement_precondition_required=True,
        enablement_precondition_resolved=resolver_eligible,
        enablement_precondition_authority=LIVE_EXECUTION_SERVICE_ENABLEMENT_AUTHORITY,
        required_enablement_artifacts=required_artifacts,
        recorded_enablement_artifacts=recorded_artifacts,
        missing_enablement_artifacts=missing_artifacts,
        resolver_eligible=resolver_eligible,
        browser_authority="display_only",
        bff_authority=(
            "source_disabled_not_forwarded"
            if source_disabled_futures_record
            else "forward_only_no_execution"
        ),
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
