"""Automation Admin API routes."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Callable, Mapping
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from application.admin_api.approval import (
    ApprovalSnapshotRequest,
    FileAdminApiApprovalStore,
    resolve_approval_snapshot,
)
from application.admin_api.audit import (
    AdmissionAuditTrailRequest,
    AdminApiAuditEvent,
    FileAdminApiAuditStore,
    resolve_admission_audit_trail,
)
from application.admin_api.auth import get_authenticated_actor, require_permission
from application.admin_api.cap_guard import (
    CapGuardDecisionRequest,
    FileAdminApiCapGuardStore,
    resolve_cap_guard_decision,
)
from application.admin_api.idempotency import (
    FileIdempotencyStore,
    IdempotencyRecord,
    make_payload_hash,
)
from application.admin_api.live_execution import (
    FileAdminApiLiveServiceDecisionStore,
    LIVE_SERVICE_DECISION_SOURCE,
    LiveServiceDecisionRecord,
)
from application.admin_api.models import (
    AdminApiActor,
    AdminApiErrorResponse,
    UsdcPairSnapshotOrderPlanLiveReadinessItem,
    UsdcPairSnapshotOrderPlanLiveReadinessListResponse,
    UsdcPairSnapshotOrderPlanLiveReadinessRequest,
    UsdcPairSnapshotOrderPlanLiveReadinessResponse,
    UsdcPairSnapshotOrderPlanLiveSubmitItem,
    UsdcPairSnapshotOrderPlanLiveSubmitListResponse,
    UsdcPairSnapshotOrderPlanLiveSubmitRequest,
    UsdcPairSnapshotOrderPlanLiveSubmitResponse,
    UsdcPairSnapshotOrderPlanItem,
    UsdcPairSnapshotOrderPlanListResponse,
    UsdcPairSnapshotOrderPlanProofRefreshRequest,
    UsdcPairSnapshotOrderPlanRequest,
    UsdcPairSnapshotOrderPlanResponse,
    UsdcPairSnapshotRunItem,
    UsdcPairSnapshotRunListResponse,
    UsdcPairSnapshotRunRequest,
    UsdcPairSnapshotRunResponse,
)
from application.admin_api.mvp_service import (
    AdminMvpRequestContext,
    AdminMvpService,
    get_admin_mvp_service,
)
from application.admin_api.usdc_pair_snapshot import (
    FileUsdcPairSnapshotOrderPlanLiveReadinessStore,
    FileUsdcPairSnapshotOrderPlanLiveSubmitStore,
    FileUsdcPairSnapshotOrderPlanStore,
    FileUsdcPairSnapshotRunStore,
    UsdcPairSnapshotOrderPlanLiveReadinessRecord,
    UsdcPairSnapshotOrderPlanLiveSubmitRecord,
    UsdcPairSnapshotOrderPlanRecord,
)
from application.admin_api.usdc_pair_snapshot_live_execution import (
    UsdcPairSnapshotLiveExecutionError,
    UsdcPairSnapshotLiveOrderExecutor,
)
from application.admin_api.reconciliation import (
    FileAdminApiReconciliationStore,
    ReconciliationPlanRequest,
    resolve_reconciliation_plan,
)
from application.admin_api.usdc_pair_snapshot_service import (
    AdminApiUsdcPairSnapshotService,
    USDC_PAIR_ORDER_PLAN_LIVE_DISABLED_BLOCKER,
    UsdcPairSnapshotError,
    item_from_record,
    order_plan_item_from_record,
)
from core.enums import (
    AdminApiActionClass,
    AdminApiApprovalLifecycleEventType,
    AdminApiCommandStatus,
    AdminApiGateStatus,
    AdminApiIdempotencyDecision,
    AdminApiLiveExecutionStatus,
    AdminApiPermission,
    OrderSide,
)


router = APIRouter()

USDC_PAIR_SNAPSHOT_ENDPOINT = "POST /api/v1/automation/usdc-pair-snapshot-runs"
USDC_PAIR_SNAPSHOT_SERVICE_METHOD = "record_usdc_pair_snapshot_dry_run"
USDC_PAIR_SNAPSHOT_ORDER_PLAN_ROUTE = (
    "/api/v1/automation/usdc-pair-snapshot-runs/{run_id}/order-plans"
)
USDC_PAIR_SNAPSHOT_ORDER_PLAN_ENDPOINT = f"POST {USDC_PAIR_SNAPSHOT_ORDER_PLAN_ROUTE}"
USDC_PAIR_SNAPSHOT_ORDER_PLAN_SERVICE_METHOD = (
    "record_usdc_pair_snapshot_order_plan"
)
USDC_PAIR_SNAPSHOT_ORDER_PLAN_PROOF_REFRESH_ROUTE = (
    "/api/v1/automation/usdc-pair-snapshot-order-plans/"
    "{plan_id}/proof-chain-refresh"
)
USDC_PAIR_SNAPSHOT_ORDER_PLAN_PROOF_REFRESH_ENDPOINT = (
    f"POST {USDC_PAIR_SNAPSHOT_ORDER_PLAN_PROOF_REFRESH_ROUTE}"
)
USDC_PAIR_SNAPSHOT_ORDER_PLAN_PROOF_REFRESH_SERVICE_METHOD = (
    "refresh_usdc_pair_snapshot_order_plan_proof_chain"
)
USDC_PAIR_SNAPSHOT_ORDER_PLAN_LIVE_READINESS_ROUTE = (
    "/api/v1/automation/usdc-pair-snapshot-order-plans/"
    "{plan_id}/live-readiness"
)
USDC_PAIR_SNAPSHOT_ORDER_PLAN_LIVE_READINESS_ENDPOINT = (
    f"POST {USDC_PAIR_SNAPSHOT_ORDER_PLAN_LIVE_READINESS_ROUTE}"
)
USDC_PAIR_SNAPSHOT_ORDER_PLAN_LIVE_READINESS_SERVICE_METHOD = (
    "record_usdc_pair_snapshot_order_plan_live_readiness"
)
USDC_PAIR_SNAPSHOT_ORDER_PLAN_LIVE_SUBMIT_ROUTE = (
    "/api/v1/automation/usdc-pair-snapshot-order-plans/"
    "{plan_id}/live-submit"
)
USDC_PAIR_SNAPSHOT_ORDER_PLAN_LIVE_SUBMIT_ENDPOINT = (
    f"POST {USDC_PAIR_SNAPSHOT_ORDER_PLAN_LIVE_SUBMIT_ROUTE}"
)
USDC_PAIR_SNAPSHOT_ORDER_PLAN_LIVE_SUBMIT_SERVICE_METHOD = (
    "submit_usdc_pair_snapshot_order_plan_live_order"
)
USDC_PAIR_SNAPSHOT_MODULE_ID = "automation"
USDC_PAIR_SNAPSHOT_PROOF_BLOCKERS = [
    "approval_snapshot_missing",
    "admission_audit_blocked",
    "cap_guard_decision_blocked",
    "reconciliation_plan_blocked",
    "live_service_decision_missing",
]
USDC_PAIR_SNAPSHOT_LIVE_SERVICE_DISABLED_BLOCKER = (
    USDC_PAIR_ORDER_PLAN_LIVE_DISABLED_BLOCKER
)
USDC_PAIR_SNAPSHOT_LIVE_SUBMISSION_MISSING_BLOCKER = "live_submission_missing"
USDC_PAIR_SNAPSHOT_LIVE_SERVICE_ACCOUNT_FAMILY = "coinbase_spot"
USDC_PAIR_SNAPSHOT_LIVE_SERVICE_VENUE_SCOPE = "coinbase_advanced_trade"
USDC_PAIR_SNAPSHOT_LIVE_SERVICE_INTX_APPLICABILITY = "not_applicable"

AUTOMATION_ROUTE_RESPONSES = {
    200: {
        "model": UsdcPairSnapshotRunResponse,
        "description": "USDC pair snapshot dry-run evidence accepted or replayed.",
    },
    400: {
        "model": UsdcPairSnapshotRunResponse,
        "description": "USDC pair snapshot dry-run evidence rejected.",
    },
    401: {
        "model": AdminApiErrorResponse,
        "description": "Missing or invalid Admin API authentication.",
    },
    403: {
        "model": AdminApiErrorResponse,
        "description": "Actor lacks the required Admin API permission.",
    },
    409: {
        "model": UsdcPairSnapshotRunResponse,
        "description": "Idempotency key conflict.",
    },
}

ORDER_PLAN_ROUTE_RESPONSES = {
    200: {
        "model": UsdcPairSnapshotOrderPlanResponse,
        "description": "USDC pair snapshot order-plan evidence accepted or replayed.",
    },
    400: {
        "model": UsdcPairSnapshotOrderPlanResponse,
        "description": "USDC pair snapshot order-plan evidence rejected.",
    },
    401: {
        "model": AdminApiErrorResponse,
        "description": "Missing or invalid Admin API authentication.",
    },
    403: {
        "model": AdminApiErrorResponse,
        "description": "Actor lacks the required Admin API permission.",
    },
    409: {
        "model": UsdcPairSnapshotOrderPlanResponse,
        "description": "Idempotency key conflict.",
    },
}

LIVE_READINESS_ROUTE_RESPONSES = {
    200: {
        "model": UsdcPairSnapshotOrderPlanLiveReadinessResponse,
        "description": (
            "USDC pair snapshot order-plan live-readiness preflight accepted, "
            "rejected, or replayed."
        ),
    },
    401: {
        "model": AdminApiErrorResponse,
        "description": "Missing or invalid Admin API authentication.",
    },
    403: {
        "model": AdminApiErrorResponse,
        "description": "Actor lacks the required Admin API permission.",
    },
    409: {
        "model": UsdcPairSnapshotOrderPlanLiveReadinessResponse,
        "description": "Idempotency key conflict.",
    },
}

LIVE_SUBMIT_ROUTE_RESPONSES = {
    200: {
        "model": UsdcPairSnapshotOrderPlanLiveSubmitResponse,
        "description": (
            "USDC pair snapshot order-plan controlled-live submit/cancel "
            "accepted, rejected, or replayed."
        ),
    },
    401: {
        "model": AdminApiErrorResponse,
        "description": "Missing or invalid Admin API authentication.",
    },
    403: {
        "model": AdminApiErrorResponse,
        "description": "Actor lacks the required Admin API permission.",
    },
    409: {
        "model": UsdcPairSnapshotOrderPlanLiveSubmitResponse,
        "description": "Idempotency key conflict.",
    },
}

READ_ONLY_ROUTE_RESPONSES = {
    401: {
        "model": AdminApiErrorResponse,
        "description": "Missing or invalid Admin API authentication.",
    },
    403: {
        "model": AdminApiErrorResponse,
        "description": "Actor lacks the required Admin API permission.",
    },
}


def get_usdc_pair_snapshot_service() -> AdminApiUsdcPairSnapshotService:
    """Return the backend-owned M58 snapshot service."""

    return AdminApiUsdcPairSnapshotService()


def get_usdc_pair_snapshot_store() -> FileUsdcPairSnapshotRunStore:
    """Return durable M58 snapshot storage."""

    return FileUsdcPairSnapshotRunStore()


def get_usdc_pair_snapshot_order_plan_store() -> FileUsdcPairSnapshotOrderPlanStore:
    """Return durable M58 snapshot order-plan storage."""

    return FileUsdcPairSnapshotOrderPlanStore()


def get_usdc_pair_snapshot_order_plan_live_readiness_store() -> (
    FileUsdcPairSnapshotOrderPlanLiveReadinessStore
):
    """Return durable M58 live-readiness preflight storage."""

    return FileUsdcPairSnapshotOrderPlanLiveReadinessStore()


def get_usdc_pair_snapshot_order_plan_live_submit_store() -> (
    FileUsdcPairSnapshotOrderPlanLiveSubmitStore
):
    """Return durable M58 controlled-live submit/cancel storage."""

    return FileUsdcPairSnapshotOrderPlanLiveSubmitStore()


def get_usdc_pair_snapshot_live_order_executor() -> (
    UsdcPairSnapshotLiveOrderExecutor
):
    """Return the backend-only M58 controlled-live order executor."""

    return UsdcPairSnapshotLiveOrderExecutor()


def get_idempotency_store() -> FileIdempotencyStore:
    """Return durable idempotency storage for automation mutations."""

    return FileIdempotencyStore()


def get_audit_store() -> FileAdminApiAuditStore:
    """Return durable audit storage for automation mutations."""

    return FileAdminApiAuditStore()


def get_usdc_pair_snapshot_proof_chain_service() -> AdminMvpService:
    """Return the backend Admin proof-chain service used for M58 evidence."""

    return get_admin_mvp_service()


def get_usdc_pair_snapshot_approval_store() -> FileAdminApiApprovalStore:
    """Return approval lifecycle storage used to resolve M58 proof snapshots."""

    return FileAdminApiApprovalStore()


def get_usdc_pair_snapshot_cap_guard_store() -> FileAdminApiCapGuardStore:
    """Return cap/guard storage used to resolve M58 proof decisions."""

    return FileAdminApiCapGuardStore()


def get_usdc_pair_snapshot_reconciliation_store() -> (
    FileAdminApiReconciliationStore
):
    """Return reconciliation storage used to resolve M58 proof plans."""

    return FileAdminApiReconciliationStore()


def get_usdc_pair_snapshot_live_service_decision_store() -> (
    FileAdminApiLiveServiceDecisionStore
):
    """Return live-service decision storage used to resolve M58 proof plans."""

    return FileAdminApiLiveServiceDecisionStore()


def _payload_hash(
    *,
    endpoint: str,
    actor: AdminApiActor,
    operator_intent: str,
    body: dict,
) -> str:
    return make_payload_hash({
        "endpoint": endpoint,
        "actor_id": actor.actor_id,
        "roles": [role.value for role in actor.roles],
        "operator_intent": operator_intent,
        "body": body,
    })


def _http_status(response: UsdcPairSnapshotRunResponse) -> int:
    if response.status == AdminApiCommandStatus.CONFLICT:
        return status.HTTP_409_CONFLICT
    if response.status == AdminApiCommandStatus.REJECTED:
        return status.HTTP_400_BAD_REQUEST
    return status.HTTP_200_OK


def _snapshot_response(
    response: UsdcPairSnapshotRunResponse,
    *,
    replayed: bool = False,
) -> JSONResponse:
    headers = {"X-Correlation-Id": response.correlation_id or ""}
    if replayed:
        headers["X-Idempotency-Replayed"] = "true"
    return JSONResponse(
        status_code=_http_status(response),
        content=response.model_dump(mode="json"),
        headers=headers,
    )


def _read_response(payload: object) -> JSONResponse:
    return JSONResponse(content=jsonable_encoder(payload))


def _snapshot_list_response(
    *,
    store: FileUsdcPairSnapshotRunStore,
    limit: int,
) -> UsdcPairSnapshotRunListResponse:
    runs = [item_from_record(record) for record in store.read_recent(limit=limit)]
    return UsdcPairSnapshotRunListResponse(
        runs=runs,
        returned_count=len(runs),
        total_count=store.count_records(),
        latest_run_id=runs[0].run_id if runs else None,
        returned_eligible_count=sum(run.eligible_count for run in runs),
        returned_skipped_count=sum(run.skipped_count for run in runs),
    )


def _order_plan_http_status(response: UsdcPairSnapshotOrderPlanResponse) -> int:
    if response.status == AdminApiCommandStatus.CONFLICT:
        return status.HTTP_409_CONFLICT
    if response.status == AdminApiCommandStatus.REJECTED:
        return status.HTTP_400_BAD_REQUEST
    return status.HTTP_200_OK


def _order_plan_response(
    response: UsdcPairSnapshotOrderPlanResponse,
    *,
    replayed: bool = False,
) -> JSONResponse:
    headers = {"X-Correlation-Id": response.correlation_id or ""}
    if replayed:
        headers["X-Idempotency-Replayed"] = "true"
    return JSONResponse(
        status_code=_order_plan_http_status(response),
        content=response.model_dump(mode="json"),
        headers=headers,
    )


def _order_plan_list_response(
    *,
    store: FileUsdcPairSnapshotOrderPlanStore,
    limit: int,
) -> UsdcPairSnapshotOrderPlanListResponse:
    plans = [
        order_plan_item_from_record(record) for record in store.read_recent(limit=limit)
    ]
    return UsdcPairSnapshotOrderPlanListResponse(
        plans=plans,
        returned_count=len(plans),
        total_count=store.count_records(),
        latest_plan_id=plans[0].plan_id if plans else None,
        returned_planned_count=sum(plan.planned_count for plan in plans),
        returned_skipped_count=sum(plan.skipped_count for plan in plans),
        returned_rejected_count=sum(plan.rejected_count for plan in plans),
        returned_proof_chain_planned_count=sum(
            plan.proof_chain_planned_count for plan in plans
        ),
        returned_proof_chain_blocked_count=sum(
            plan.proof_chain_blocked_count for plan in plans
        ),
        returned_proof_chain_live_disabled_count=sum(
            plan.proof_chain_live_disabled_count for plan in plans
        ),
        returned_proof_chain_missing_evidence_count=sum(
            plan.proof_chain_missing_evidence_count for plan in plans
        ),
        returned_proof_chain_not_applicable_count=sum(
            plan.proof_chain_not_applicable_count for plan in plans
        ),
    )


def _live_readiness_item_from_record(
    record: UsdcPairSnapshotOrderPlanLiveReadinessRecord,
) -> UsdcPairSnapshotOrderPlanLiveReadinessItem:
    return UsdcPairSnapshotOrderPlanLiveReadinessItem(
        readiness_id=record.readiness_id,
        plan_id=record.plan_id,
        snapshot_run_id=record.snapshot_run_id,
        product_id=record.product_id,
        client_order_id=record.client_order_id,
        recorded_at=record.recorded_at,
        side=OrderSide(record.side),
        order_count=record.order_count,
        single_order_only=record.single_order_only,
        minimum_order_size_preferred=record.minimum_order_size_preferred,
        reference_bid_price=record.reference_bid_price,
        last_filled_price=record.last_filled_price,
        intended_limit_price=record.intended_limit_price,
        far_from_bid_status=record.far_from_bid_status,
        snapshot_non_fill_status=record.snapshot_non_fill_status,
        submitted_notional_usdc=record.submitted_notional_usdc,
        max_submitted_notional_usdc=record.max_submitted_notional_usdc,
        max_executed_notional_usdc=record.max_executed_notional_usdc,
        planned_notional_usdc=record.planned_notional_usdc,
        base_size=record.base_size,
        quote_size=record.quote_size,
        min_base_size=record.min_base_size,
        min_quote_size=record.min_quote_size,
        preflight_passed=record.preflight_passed,
        preflight_blockers=record.preflight_blockers,
        submit_route_ready=record.submit_route_ready,
        submit_blockers=record.submit_blockers,
        cancel_before_additional_orders=record.cancel_before_additional_orders,
        cancel_rollback_plan_ref=record.cancel_rollback_plan_ref,
        full_snapshot_fill_test=record.full_snapshot_fill_test,
        approval_snapshot_id=record.approval_snapshot_id,
        admission_audit_id=record.admission_audit_id,
        cap_guard_decision_id=record.cap_guard_decision_id,
        reconciliation_plan_id=record.reconciliation_plan_id,
        live_service_decision_id=record.live_service_decision_id,
        actor_id=record.actor_id,
        operator_intent=record.operator_intent,
        idempotency_key=record.idempotency_key,
        payload_hash=record.payload_hash,
        audit_id=record.audit_id,
        operator_notes=record.operator_notes,
        detail=record.detail,
    )


def _live_readiness_list_response(
    *,
    store: FileUsdcPairSnapshotOrderPlanLiveReadinessStore,
    limit: int,
) -> UsdcPairSnapshotOrderPlanLiveReadinessListResponse:
    readiness = [
        _live_readiness_item_from_record(record)
        for record in store.read_recent(limit=limit)
    ]
    return UsdcPairSnapshotOrderPlanLiveReadinessListResponse(
        readiness=readiness,
        returned_count=len(readiness),
        total_count=store.count_records(),
        latest_readiness_id=readiness[0].readiness_id if readiness else None,
        ready_count=sum(1 for item in readiness if item.preflight_passed),
        submit_route_ready_count=sum(
            1 for item in readiness if item.submit_route_ready
        ),
    )


def _live_submit_item_from_record(
    record: UsdcPairSnapshotOrderPlanLiveSubmitRecord,
) -> UsdcPairSnapshotOrderPlanLiveSubmitItem:
    return UsdcPairSnapshotOrderPlanLiveSubmitItem(
        submission_id=record.submission_id,
        readiness_id=record.readiness_id,
        plan_id=record.plan_id,
        snapshot_run_id=record.snapshot_run_id,
        product_id=record.product_id,
        client_order_id=record.client_order_id,
        recorded_at=record.recorded_at,
        submitted_at=record.submitted_at,
        cancelled_at=record.cancelled_at,
        side=OrderSide(record.side),
        order_count=record.order_count,
        single_order_only=record.single_order_only,
        submitted_notional_usdc=record.submitted_notional_usdc,
        executed_notional_usdc=record.executed_notional_usdc,
        max_executed_notional_usdc=record.max_executed_notional_usdc,
        intended_limit_price=record.intended_limit_price,
        reference_bid_price=record.reference_bid_price,
        last_filled_price=record.last_filled_price,
        cancel_before_additional_orders=record.cancel_before_additional_orders,
        additional_orders_blocked=record.additional_orders_blocked,
        cancel_submitted=record.cancel_submitted,
        cancel_rollback_complete=record.cancel_rollback_complete,
        cancel_rollback_plan_ref=record.cancel_rollback_plan_ref,
        full_snapshot_fill_test=record.full_snapshot_fill_test,
        approval_snapshot_id=record.approval_snapshot_id,
        admission_audit_id=record.admission_audit_id,
        cap_guard_decision_id=record.cap_guard_decision_id,
        reconciliation_plan_id=record.reconciliation_plan_id,
        live_service_decision_id=record.live_service_decision_id,
        coinbase_order_id=record.coinbase_order_id,
        coinbase_order_id_evidence_only=record.coinbase_order_id_evidence_only,
        order_configuration=record.order_configuration,
        submit_result=record.submit_result,
        cancel_result=record.cancel_result,
        operator_stop_conditions=record.operator_stop_conditions,
        actor_id=record.actor_id,
        operator_intent=record.operator_intent,
        idempotency_key=record.idempotency_key,
        payload_hash=record.payload_hash,
        audit_id=record.audit_id,
        operator_notes=record.operator_notes,
        live_exchange_submitted=record.live_exchange_submitted,
        live_coinbase_orders_ran=record.live_coinbase_orders_ran,
        live_coinbase_execution=record.live_coinbase_execution,
        notional_usdc=record.notional_usdc,
        detail=record.detail,
    )


def _live_submit_list_response(
    *,
    store: FileUsdcPairSnapshotOrderPlanLiveSubmitStore,
    limit: int,
) -> UsdcPairSnapshotOrderPlanLiveSubmitListResponse:
    submissions = [
        _live_submit_item_from_record(record)
        for record in store.read_recent(limit=limit)
    ]
    submitted_notional = sum(
        (
            _decimal_value(item.notional_usdc) or Decimal("0")
            for item in submissions
            if item.live_exchange_submitted
        ),
        Decimal("0"),
    )
    return UsdcPairSnapshotOrderPlanLiveSubmitListResponse(
        submissions=submissions,
        returned_count=len(submissions),
        total_count=store.count_records(),
        latest_submission_id=(
            submissions[0].submission_id if submissions else None
        ),
        submitted_count=sum(
            1 for item in submissions if item.live_exchange_submitted
        ),
        cancelled_count=sum(
            1 for item in submissions if item.cancel_rollback_complete
        ),
        live_exchange_submitted=any(
            item.live_exchange_submitted for item in submissions
        ),
        live_coinbase_orders_ran=any(
            item.live_coinbase_orders_ran for item in submissions
        ),
        live_coinbase_execution=(
            "submitted_cancelled"
            if any(
                item.live_coinbase_execution == "submitted_cancelled"
                for item in submissions
            )
            else "not_run"
        ),
        notional_usdc=str(submitted_notional),
    )


def _base_response(
    *,
    status_value: AdminApiCommandStatus,
    message: str,
    correlation_id: str,
    idempotency_key: str,
    run: UsdcPairSnapshotRunItem | None = None,
    audit_id: str | None = None,
    failure_stage: str | None = None,
) -> UsdcPairSnapshotRunResponse:
    return UsdcPairSnapshotRunResponse(
        status=status_value,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        required_permission=AdminApiPermission.CAMPAIGN_EXECUTE,
        service_method=USDC_PAIR_SNAPSHOT_SERVICE_METHOD,
        message=message,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        audit_id=audit_id,
        run=run,
        failure_stage=failure_stage,
    )


def _order_plan_base_response(
    *,
    status_value: AdminApiCommandStatus,
    message: str,
    correlation_id: str,
    idempotency_key: str,
    service_method: str = USDC_PAIR_SNAPSHOT_ORDER_PLAN_SERVICE_METHOD,
    plan: UsdcPairSnapshotOrderPlanItem | None = None,
    audit_id: str | None = None,
    failure_stage: str | None = None,
) -> UsdcPairSnapshotOrderPlanResponse:
    return UsdcPairSnapshotOrderPlanResponse(
        status=status_value,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        required_permission=AdminApiPermission.CAMPAIGN_EXECUTE,
        service_method=service_method,
        message=message,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        audit_id=audit_id,
        plan=plan,
        failure_stage=failure_stage,
    )


def _live_readiness_http_status(
    response: UsdcPairSnapshotOrderPlanLiveReadinessResponse,
) -> int:
    if response.status == AdminApiCommandStatus.CONFLICT:
        return status.HTTP_409_CONFLICT
    return status.HTTP_200_OK


def _live_readiness_response(
    response: UsdcPairSnapshotOrderPlanLiveReadinessResponse,
    *,
    replayed: bool = False,
) -> JSONResponse:
    headers = {"X-Correlation-Id": response.correlation_id or ""}
    if replayed:
        headers["X-Idempotency-Replayed"] = "true"
    return JSONResponse(
        status_code=_live_readiness_http_status(response),
        content=response.model_dump(mode="json"),
        headers=headers,
    )


def _live_readiness_base_response(
    *,
    status_value: AdminApiCommandStatus,
    message: str,
    correlation_id: str,
    idempotency_key: str,
    readiness: UsdcPairSnapshotOrderPlanLiveReadinessItem | None = None,
    audit_id: str | None = None,
    failure_stage: str | None = None,
) -> UsdcPairSnapshotOrderPlanLiveReadinessResponse:
    return UsdcPairSnapshotOrderPlanLiveReadinessResponse(
        status=status_value,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        required_permission=AdminApiPermission.CAMPAIGN_EXECUTE,
        service_method=USDC_PAIR_SNAPSHOT_ORDER_PLAN_LIVE_READINESS_SERVICE_METHOD,
        message=message,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        audit_id=audit_id,
        readiness=readiness,
        failure_stage=failure_stage,
    )


def _live_submit_http_status(
    response: UsdcPairSnapshotOrderPlanLiveSubmitResponse,
) -> int:
    if response.status == AdminApiCommandStatus.CONFLICT:
        return status.HTTP_409_CONFLICT
    return status.HTTP_200_OK


def _live_submit_response(
    response: UsdcPairSnapshotOrderPlanLiveSubmitResponse,
    *,
    replayed: bool = False,
) -> JSONResponse:
    headers = {"X-Correlation-Id": response.correlation_id or ""}
    if replayed:
        headers["X-Idempotency-Replayed"] = "true"
    return JSONResponse(
        status_code=_live_submit_http_status(response),
        content=response.model_dump(mode="json"),
        headers=headers,
    )


def _live_submit_base_response(
    *,
    status_value: AdminApiCommandStatus,
    message: str,
    correlation_id: str,
    idempotency_key: str,
    submission: UsdcPairSnapshotOrderPlanLiveSubmitItem | None = None,
    audit_id: str | None = None,
    failure_stage: str | None = None,
) -> UsdcPairSnapshotOrderPlanLiveSubmitResponse:
    return UsdcPairSnapshotOrderPlanLiveSubmitResponse(
        status=status_value,
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        required_permission=AdminApiPermission.CAMPAIGN_EXECUTE,
        service_method=USDC_PAIR_SNAPSHOT_ORDER_PLAN_LIVE_SUBMIT_SERVICE_METHOD,
        message=message,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        audit_id=audit_id,
        submission=submission,
        live_exchange_submitted=(
            submission.live_exchange_submitted if submission else False
        ),
        live_coinbase_orders_ran=(
            submission.live_coinbase_orders_ran if submission else False
        ),
        live_coinbase_execution=(
            submission.live_coinbase_execution if submission else "not_run"
        ),
        notional_usdc=submission.notional_usdc if submission else "0",
        failure_stage=failure_stage,
    )


def _record_audit(
    *,
    audit_store: FileAdminApiAuditStore,
    actor: AdminApiActor,
    request_id: str,
    operator_intent: str,
    response: UsdcPairSnapshotRunResponse,
    audit_id: str | None = None,
) -> str:
    event_fields = {
        "actor_id": actor.actor_id,
        "action_class": response.action_class,
        "permission": response.required_permission,
        "endpoint": USDC_PAIR_SNAPSHOT_ENDPOINT,
        "request_id": request_id,
        "operator_intent": operator_intent,
        "idempotency_key": response.idempotency_key,
        "status": response.status,
        "failure_stage": response.failure_stage,
        "message": response.message,
        "live_exchange_submitted": False,
        "live_coinbase_orders_ran": False,
    }
    if audit_id is not None:
        event_fields["audit_id"] = audit_id
    return audit_store.append(AdminApiAuditEvent(**event_fields))


def _record_order_plan_audit(
    *,
    audit_store: FileAdminApiAuditStore,
    actor: AdminApiActor,
    endpoint: str,
    request_id: str,
    operator_intent: str,
    response: UsdcPairSnapshotOrderPlanResponse,
    audit_id: str | None = None,
) -> str:
    event_fields = {
        "actor_id": actor.actor_id,
        "action_class": response.action_class,
        "permission": response.required_permission,
        "endpoint": endpoint,
        "request_id": request_id,
        "operator_intent": operator_intent,
        "idempotency_key": response.idempotency_key,
        "status": response.status,
        "failure_stage": response.failure_stage,
        "message": response.message,
        "live_exchange_submitted": False,
        "live_coinbase_orders_ran": False,
    }
    if audit_id is not None:
        event_fields["audit_id"] = audit_id
    return audit_store.append(AdminApiAuditEvent(**event_fields))


def _record_live_readiness_audit(
    *,
    audit_store: FileAdminApiAuditStore,
    actor: AdminApiActor,
    endpoint: str,
    request_id: str,
    operator_intent: str,
    response: UsdcPairSnapshotOrderPlanLiveReadinessResponse,
    audit_id: str | None = None,
) -> str:
    event_fields = {
        "actor_id": actor.actor_id,
        "action_class": response.action_class,
        "permission": response.required_permission,
        "endpoint": endpoint,
        "request_id": request_id,
        "operator_intent": operator_intent,
        "idempotency_key": response.idempotency_key,
        "status": response.status,
        "failure_stage": response.failure_stage,
        "message": response.message,
        "live_exchange_submitted": False,
        "live_coinbase_orders_ran": False,
    }
    if audit_id is not None:
        event_fields["audit_id"] = audit_id
    return audit_store.append(AdminApiAuditEvent(**event_fields))


def _record_live_submit_audit(
    *,
    audit_store: FileAdminApiAuditStore,
    actor: AdminApiActor,
    endpoint: str,
    request_id: str,
    operator_intent: str,
    response: UsdcPairSnapshotOrderPlanLiveSubmitResponse,
    audit_id: str | None = None,
) -> str:
    event_fields = {
        "actor_id": actor.actor_id,
        "action_class": response.action_class,
        "permission": response.required_permission,
        "endpoint": endpoint,
        "request_id": request_id,
        "operator_intent": operator_intent,
        "idempotency_key": response.idempotency_key,
        "status": response.status,
        "failure_stage": response.failure_stage,
        "message": response.message,
        "live_exchange_submitted": response.live_exchange_submitted,
        "live_coinbase_orders_ran": response.live_coinbase_orders_ran,
    }
    if audit_id is not None:
        event_fields["audit_id"] = audit_id
    return audit_store.append(AdminApiAuditEvent(**event_fields))


def _execute_idempotent_snapshot(
    *,
    idempotency_key: str,
    payload_hash: str,
    actor: AdminApiActor,
    request_id: str,
    operator_intent: str,
    idempotency_store: FileIdempotencyStore,
    audit_store: FileAdminApiAuditStore,
    operation: Callable[[str], UsdcPairSnapshotRunItem],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.CAMPAIGN_EXECUTE)
    check = idempotency_store.evaluate(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
    )
    if check.decision == AdminApiIdempotencyDecision.REPLAY and check.record:
        return _snapshot_response(
            UsdcPairSnapshotRunResponse.model_validate(check.record.response),
            replayed=True,
        )
    if check.decision == AdminApiIdempotencyDecision.CONFLICT:
        response = _base_response(
            status_value=AdminApiCommandStatus.CONFLICT,
            message="Idempotency-Key was already used with a different payload.",
            correlation_id=request_id,
            idempotency_key=idempotency_key,
            failure_stage="idempotency",
        )
        response.audit_id = _record_audit(
            audit_store=audit_store,
            actor=actor,
            request_id=request_id,
            operator_intent=operator_intent,
            response=response,
        )
        return _snapshot_response(response)

    try:
        audit_id = str(uuid4())
        run = operation(audit_id)
        response = _base_response(
            status_value=AdminApiCommandStatus.ACCEPTED,
            message="USDC pair snapshot dry-run evidence accepted.",
            correlation_id=request_id,
            idempotency_key=idempotency_key,
            audit_id=audit_id,
            run=run,
        )
    except UsdcPairSnapshotError as exc:
        response = _base_response(
            status_value=AdminApiCommandStatus.REJECTED,
            message=str(exc),
            correlation_id=request_id,
            idempotency_key=idempotency_key,
            failure_stage="usdc_pair_snapshot",
        )
    response.audit_id = _record_audit(
        audit_store=audit_store,
        actor=actor,
        request_id=request_id,
        operator_intent=operator_intent,
        response=response,
        audit_id=response.audit_id,
    )
    if response.status == AdminApiCommandStatus.ACCEPTED:
        idempotency_store.put_record(
            IdempotencyRecord(
                idempotency_key=idempotency_key,
                payload_hash=payload_hash,
                status=response.status,
                response=response.model_dump(mode="json"),
                actor_id=actor.actor_id,
                endpoint=USDC_PAIR_SNAPSHOT_ENDPOINT,
            )
        )
    return _snapshot_response(response)


def _execute_idempotent_order_plan(
    *,
    endpoint: str = USDC_PAIR_SNAPSHOT_ORDER_PLAN_ENDPOINT,
    service_method: str = USDC_PAIR_SNAPSHOT_ORDER_PLAN_SERVICE_METHOD,
    accepted_message: str = "USDC pair snapshot order-plan evidence accepted.",
    failure_stage: str = "usdc_pair_snapshot_order_plan",
    idempotency_key: str,
    payload_hash: str,
    actor: AdminApiActor,
    request_id: str,
    operator_intent: str,
    idempotency_store: FileIdempotencyStore,
    audit_store: FileAdminApiAuditStore,
    operation: Callable[[str], UsdcPairSnapshotOrderPlanItem],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.CAMPAIGN_EXECUTE)
    check = idempotency_store.evaluate(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
    )
    if check.decision == AdminApiIdempotencyDecision.REPLAY and check.record:
        return _order_plan_response(
            UsdcPairSnapshotOrderPlanResponse.model_validate(
                check.record.response
            ),
            replayed=True,
        )
    if check.decision == AdminApiIdempotencyDecision.CONFLICT:
        response = _order_plan_base_response(
            status_value=AdminApiCommandStatus.CONFLICT,
            message="Idempotency-Key was already used with a different payload.",
            correlation_id=request_id,
            idempotency_key=idempotency_key,
            service_method=service_method,
            failure_stage="idempotency",
        )
        response.audit_id = _record_order_plan_audit(
            audit_store=audit_store,
            actor=actor,
            endpoint=endpoint,
            request_id=request_id,
            operator_intent=operator_intent,
            response=response,
        )
        return _order_plan_response(response)

    try:
        audit_id = str(uuid4())
        plan = operation(audit_id)
        response = _order_plan_base_response(
            status_value=AdminApiCommandStatus.ACCEPTED,
            message=accepted_message,
            correlation_id=request_id,
            idempotency_key=idempotency_key,
            service_method=service_method,
            audit_id=audit_id,
            plan=plan,
        )
    except UsdcPairSnapshotError as exc:
        response = _order_plan_base_response(
            status_value=AdminApiCommandStatus.REJECTED,
            message=str(exc),
            correlation_id=request_id,
            idempotency_key=idempotency_key,
            service_method=service_method,
            failure_stage=failure_stage,
        )
    response.audit_id = _record_order_plan_audit(
        audit_store=audit_store,
        actor=actor,
        endpoint=endpoint,
        request_id=request_id,
        operator_intent=operator_intent,
        response=response,
        audit_id=response.audit_id,
    )
    if response.status == AdminApiCommandStatus.ACCEPTED:
        idempotency_store.put_record(
            IdempotencyRecord(
                idempotency_key=idempotency_key,
                payload_hash=payload_hash,
                status=response.status,
                response=response.model_dump(mode="json"),
                actor_id=actor.actor_id,
                endpoint=endpoint,
            )
        )
    return _order_plan_response(response)


def _execute_idempotent_live_readiness(
    *,
    idempotency_key: str,
    payload_hash: str,
    actor: AdminApiActor,
    request_id: str,
    operator_intent: str,
    idempotency_store: FileIdempotencyStore,
    audit_store: FileAdminApiAuditStore,
    operation: Callable[[str], UsdcPairSnapshotOrderPlanLiveReadinessItem],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.CAMPAIGN_EXECUTE)
    check = idempotency_store.evaluate(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
    )
    if check.decision == AdminApiIdempotencyDecision.REPLAY and check.record:
        return _live_readiness_response(
            UsdcPairSnapshotOrderPlanLiveReadinessResponse.model_validate(
                check.record.response
            ),
            replayed=True,
        )
    if check.decision == AdminApiIdempotencyDecision.CONFLICT:
        response = _live_readiness_base_response(
            status_value=AdminApiCommandStatus.CONFLICT,
            message="Idempotency-Key was already used with a different payload.",
            correlation_id=request_id,
            idempotency_key=idempotency_key,
            failure_stage="idempotency",
        )
        response.audit_id = _record_live_readiness_audit(
            audit_store=audit_store,
            actor=actor,
            endpoint=USDC_PAIR_SNAPSHOT_ORDER_PLAN_LIVE_READINESS_ENDPOINT,
            request_id=request_id,
            operator_intent=operator_intent,
            response=response,
        )
        return _live_readiness_response(response)

    try:
        audit_id = str(uuid4())
        readiness = operation(audit_id)
        response = _live_readiness_base_response(
            status_value=AdminApiCommandStatus.ACCEPTED,
            message=(
                "USDC pair snapshot order-plan live-readiness preflight "
                "accepted without Coinbase submission."
            ),
            correlation_id=request_id,
            idempotency_key=idempotency_key,
            audit_id=audit_id,
            readiness=readiness,
        )
    except UsdcPairSnapshotError as exc:
        response = _live_readiness_base_response(
            status_value=AdminApiCommandStatus.REJECTED,
            message=str(exc),
            correlation_id=request_id,
            idempotency_key=idempotency_key,
            failure_stage="usdc_pair_snapshot_order_plan_live_readiness",
        )
    response.audit_id = _record_live_readiness_audit(
        audit_store=audit_store,
        actor=actor,
        endpoint=USDC_PAIR_SNAPSHOT_ORDER_PLAN_LIVE_READINESS_ENDPOINT,
        request_id=request_id,
        operator_intent=operator_intent,
        response=response,
        audit_id=response.audit_id,
    )
    if response.status == AdminApiCommandStatus.ACCEPTED:
        idempotency_store.put_record(
            IdempotencyRecord(
                idempotency_key=idempotency_key,
                payload_hash=payload_hash,
                status=response.status,
                response=response.model_dump(mode="json"),
                actor_id=actor.actor_id,
                endpoint=USDC_PAIR_SNAPSHOT_ORDER_PLAN_LIVE_READINESS_ENDPOINT,
            )
        )
    return _live_readiness_response(response)


def _execute_idempotent_live_submit(
    *,
    idempotency_key: str,
    payload_hash: str,
    actor: AdminApiActor,
    request_id: str,
    operator_intent: str,
    idempotency_store: FileIdempotencyStore,
    audit_store: FileAdminApiAuditStore,
    operation: Callable[[str], UsdcPairSnapshotOrderPlanLiveSubmitItem],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.CAMPAIGN_EXECUTE)
    check = idempotency_store.evaluate(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
    )
    if check.decision == AdminApiIdempotencyDecision.REPLAY and check.record:
        return _live_submit_response(
            UsdcPairSnapshotOrderPlanLiveSubmitResponse.model_validate(
                check.record.response
            ),
            replayed=True,
        )
    if check.decision == AdminApiIdempotencyDecision.CONFLICT:
        response = _live_submit_base_response(
            status_value=AdminApiCommandStatus.CONFLICT,
            message="Idempotency-Key was already used with a different payload.",
            correlation_id=request_id,
            idempotency_key=idempotency_key,
            failure_stage="idempotency",
        )
        response.audit_id = _record_live_submit_audit(
            audit_store=audit_store,
            actor=actor,
            endpoint=USDC_PAIR_SNAPSHOT_ORDER_PLAN_LIVE_SUBMIT_ENDPOINT,
            request_id=request_id,
            operator_intent=operator_intent,
            response=response,
        )
        return _live_submit_response(response)

    try:
        audit_id = str(uuid4())
        submission = operation(audit_id)
        response = _live_submit_base_response(
            status_value=AdminApiCommandStatus.ACCEPTED,
            message=(
                "USDC pair snapshot order-plan controlled-live submit/cancel "
                "accepted for one order."
            ),
            correlation_id=request_id,
            idempotency_key=idempotency_key,
            audit_id=audit_id,
            submission=submission,
        )
    except UsdcPairSnapshotError as exc:
        response = _live_submit_base_response(
            status_value=AdminApiCommandStatus.REJECTED,
            message=str(exc),
            correlation_id=request_id,
            idempotency_key=idempotency_key,
            failure_stage="usdc_pair_snapshot_order_plan_live_submit",
        )
    response.audit_id = _record_live_submit_audit(
        audit_store=audit_store,
        actor=actor,
        endpoint=USDC_PAIR_SNAPSHOT_ORDER_PLAN_LIVE_SUBMIT_ENDPOINT,
        request_id=request_id,
        operator_intent=operator_intent,
        response=response,
        audit_id=response.audit_id,
    )
    if response.status == AdminApiCommandStatus.ACCEPTED:
        idempotency_store.put_record(
            IdempotencyRecord(
                idempotency_key=idempotency_key,
                payload_hash=payload_hash,
                status=response.status,
                response=response.model_dump(mode="json"),
                actor_id=actor.actor_id,
                endpoint=USDC_PAIR_SNAPSHOT_ORDER_PLAN_LIVE_SUBMIT_ENDPOINT,
            )
        )
    return _live_submit_response(response)


@router.get(
    "/automation/usdc-pair-snapshot-runs",
    response_model=UsdcPairSnapshotRunListResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="List backend-owned USDC pair snapshot dry-run evidence",
)
def list_usdc_pair_snapshot_runs(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    snapshot_store: Annotated[
        FileUsdcPairSnapshotRunStore,
        Depends(get_usdc_pair_snapshot_store),
    ],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> JSONResponse:
    """Read durable M58 dry-run snapshot evidence without Coinbase calls."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_response(_snapshot_list_response(store=snapshot_store, limit=limit))


@router.get(
    "/automation/usdc-pair-snapshot-order-plans",
    response_model=UsdcPairSnapshotOrderPlanListResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="List backend-owned USDC pair snapshot order-plan evidence",
)
def list_usdc_pair_snapshot_order_plans(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    order_plan_store: Annotated[
        FileUsdcPairSnapshotOrderPlanStore,
        Depends(get_usdc_pair_snapshot_order_plan_store),
    ],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> JSONResponse:
    """Read durable M58 dry-run order-plan evidence without Coinbase calls."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_response(
        _order_plan_list_response(store=order_plan_store, limit=limit)
    )


@router.get(
    "/automation/usdc-pair-snapshot-order-plan-live-readiness",
    response_model=UsdcPairSnapshotOrderPlanLiveReadinessListResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="List backend-owned USDC pair snapshot live-readiness preflight evidence",
)
def list_usdc_pair_snapshot_order_plan_live_readiness(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    readiness_store: Annotated[
        FileUsdcPairSnapshotOrderPlanLiveReadinessStore,
        Depends(get_usdc_pair_snapshot_order_plan_live_readiness_store),
    ],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> JSONResponse:
    """Read durable M58 no-live live-readiness evidence without Coinbase calls."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_response(
        _live_readiness_list_response(store=readiness_store, limit=limit)
    )


@router.get(
    "/automation/usdc-pair-snapshot-order-plan-live-submissions",
    response_model=UsdcPairSnapshotOrderPlanLiveSubmitListResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="List backend-owned USDC pair snapshot live submit/cancel evidence",
)
def list_usdc_pair_snapshot_order_plan_live_submissions(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    submit_store: Annotated[
        FileUsdcPairSnapshotOrderPlanLiveSubmitStore,
        Depends(get_usdc_pair_snapshot_order_plan_live_submit_store),
    ],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> JSONResponse:
    """Read durable M58 controlled-live submit/cancel evidence."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_response(
        _live_submit_list_response(store=submit_store, limit=limit)
    )


def _proof_phase_context(
    *,
    row_idempotency_key: str,
    phase: str,
    correlation_id: str,
    operator_intent: str,
    actor: AdminApiActor,
) -> AdminMvpRequestContext:
    return AdminMvpRequestContext(
        idempotency_key=f"{row_idempotency_key}:{phase}",
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor_id=actor.actor_id,
        roles=tuple(role.value for role in actor.roles),
    )


def _usdc_pair_order_plan_proof_chain_recorder(
    *,
    proof_chain_service: AdminMvpService,
    correlation_id: str,
    operator_intent: str,
    actor: AdminApiActor,
    payload_hash: str,
) -> Callable[[Any, Mapping[str, Any]], dict[str, Any]]:
    def record(row: Any, proof_scope: Mapping[str, Any]) -> dict[str, Any]:
        client_order_id = str(getattr(row, "client_order_id", "") or "")
        row_idempotency_key = str(getattr(row, "idempotency_key", "") or "")
        if not client_order_id or not row_idempotency_key:
            return {}

        approval_request_id = f"m58-usdc-approval-request-{client_order_id}"
        admission_audit_id = f"m58-usdc-admission-audit-{client_order_id}"
        cap_guard_decision_id = f"m58-usdc-cap-guard-{client_order_id}"
        reconciliation_plan_id = f"m58-usdc-reconciliation-{client_order_id}"
        command_evidence = {
            "route": USDC_PAIR_SNAPSHOT_ORDER_PLAN_ENDPOINT,
            "method": "POST",
            "module_id": USDC_PAIR_SNAPSHOT_MODULE_ID,
            "identity_key": "client_order_id",
            "identity_value": client_order_id,
            "action_class": AdminApiActionClass.LOCAL_STATE_MUTATION.value,
            "required_permission": AdminApiPermission.CAMPAIGN_EXECUTE.value,
            "service_method": USDC_PAIR_SNAPSHOT_ORDER_PLAN_SERVICE_METHOD,
            "operator_intent": operator_intent,
            "command_idempotency_key": row_idempotency_key,
            "payload_hash": payload_hash,
            **_usdc_pair_order_plan_scope_evidence(proof_scope),
        }
        planned_notional = str(getattr(row, "planned_notional_usdc", "") or "0")

        proof_chain_service.create_approval_request(
            {
                **command_evidence,
                "approval_request_id": approval_request_id,
                "request_reason": (
                    "M58 USDC pair order-plan proof-chain readiness request."
                ),
                "cap_guard_decision_ref": cap_guard_decision_id,
                "reconciliation_plan_ref": reconciliation_plan_id,
            },
            _proof_phase_context(
                row_idempotency_key=row_idempotency_key,
                phase="approval-request",
                correlation_id=correlation_id,
                operator_intent=operator_intent,
                actor=actor,
            ),
        )
        proof_chain_service.record_admission_audit(
            {
                **command_evidence,
                "admission_audit_id": admission_audit_id,
                "approval_snapshot_id": None,
                "allowed": False,
                "status": "blocked",
            },
            _proof_phase_context(
                row_idempotency_key=row_idempotency_key,
                phase="admission-audit",
                correlation_id=correlation_id,
                operator_intent=operator_intent,
                actor=actor,
            ),
        )
        proof_chain_service.record_cap_guard_decision(
            {
                **command_evidence,
                "decision_id": cap_guard_decision_id,
                "approval_snapshot_id": None,
                "admission_audit_id": admission_audit_id,
                "allowed": False,
                "status": "blocked",
                "max_submitted_notional_usdc": planned_notional,
                "max_executed_notional_usdc": "0",
                "wallet_check_required": True,
                "wallet_check_source": "m58_usdc_pair_order_plan",
                "wallet_check_status": "blocked",
            },
            _proof_phase_context(
                row_idempotency_key=row_idempotency_key,
                phase="cap-guard",
                correlation_id=correlation_id,
                operator_intent=operator_intent,
                actor=actor,
            ),
        )
        proof_chain_service.record_reconciliation_plan(
            {
                **command_evidence,
                "plan_id": reconciliation_plan_id,
                "approval_snapshot_id": None,
                "admission_audit_id": admission_audit_id,
                "cap_guard_decision_id": cap_guard_decision_id,
                "allowed": False,
                "status": "blocked",
                "exchange_submission_required": False,
                "max_submitted_notional_usdc": planned_notional,
                "max_executed_notional_usdc": "0",
                "reconciliation_reason": (
                    "M58 no-live order-plan proof-chain readiness."
                ),
            },
            _proof_phase_context(
                row_idempotency_key=row_idempotency_key,
                phase="reconciliation",
                correlation_id=correlation_id,
                operator_intent=operator_intent,
                actor=actor,
            ),
        )
        return {
            "proof_chain_status": "blocked",
            "proof_chain_blockers": list(USDC_PAIR_SNAPSHOT_PROOF_BLOCKERS),
            "approval_request_required": True,
            "approval_request_id": approval_request_id,
            "approval_snapshot_required": True,
            "approval_snapshot_id": None,
            "admission_audit_required": True,
            "admission_audit_id": admission_audit_id,
            "cap_guard_decision_required": True,
            "cap_guard_decision_id": cap_guard_decision_id,
            "reconciliation_plan_required": True,
            "reconciliation_plan_id": reconciliation_plan_id,
            "live_service_decision_required": True,
            "live_service_decision_id": None,
        }

    return record


def _usdc_pair_order_plan_scope_evidence(
    proof_scope: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        key: proof_scope.get(key)
        for key in (
            "automation_run_id",
            "order_plan_id",
            "product_id",
            "account_id",
            "portfolio_id",
            "requested_notional_usdc",
            "planned_notional_usdc",
            "max_notional_per_product_usdc",
            "max_total_notional_usdc",
            "snapshot_price",
            "limit_price",
            "price_source",
            "price_freshness_status",
            "price_acceptance_status",
            "run_cap_status",
            "run_cap_remaining_usdc",
            "snapshot_captured_at",
        )
    }


def _approval_request_id_for_snapshot(
    *,
    approval_store: FileAdminApiApprovalStore,
    approval_id: str,
) -> str | None:
    for event in approval_store.read_lifecycle_events(limit=1000):
        if (
            event.approval_id == approval_id
            and event.event_type
            == AdminApiApprovalLifecycleEventType.DECISION_RECORDED
        ):
            return event.approval_request_id
    return None


def _expected_usdc_pair_live_service_decision_id(row: Any) -> str | None:
    client_order_id = str(getattr(row, "client_order_id", "") or "")
    if not client_order_id:
        return None
    return f"m58-usdc-live-service-{client_order_id}"


def _decimal_zero(value: str) -> bool:
    try:
        return Decimal(str(value)) == Decimal("0")
    except (InvalidOperation, ValueError):
        return False


def _decimal_equal(value: str, expected: str) -> bool:
    try:
        return Decimal(str(value)) == Decimal(str(expected))
    except (InvalidOperation, ValueError):
        return False


def _positive_decimal_at_most(value: str, limit: str) -> bool:
    try:
        decimal_value = Decimal(str(value))
        decimal_limit = Decimal(str(limit))
    except (InvalidOperation, ValueError):
        return False
    return Decimal("0") < decimal_value <= decimal_limit


def _decimal_value(value: str | None) -> Decimal | None:
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if decimal_value <= Decimal("0"):
        return None
    return decimal_value


def _find_usdc_pair_order_plan_row(
    plan: UsdcPairSnapshotOrderPlanRecord,
    *,
    product_id: str,
    client_order_id: str,
) -> Any | None:
    normalized_product_id = product_id.upper()
    for row in plan.order_plan_rows:
        if (
            row.product_id.upper() == normalized_product_id
            and row.client_order_id == client_order_id
        ):
            return row
    return None


def _usdc_pair_live_service_product_scope_matches(
    record: LiveServiceDecisionRecord,
    *,
    product_id: str,
) -> bool:
    product_scope = {str(item) for item in record.product_scope if str(item)}
    return product_id in product_scope


def _disabled_usdc_pair_live_service_decision_matches(
    record: LiveServiceDecisionRecord,
    *,
    row: Any,
) -> bool:
    expected_decision_id = _expected_usdc_pair_live_service_decision_id(row)
    product_id = str(getattr(row, "product_id", "") or "")
    return (
        expected_decision_id is not None
        and product_id
        and record.decision_id == expected_decision_id
        and record.source == LIVE_SERVICE_DECISION_SOURCE
        and record.target_module_id == USDC_PAIR_SNAPSHOT_MODULE_ID
        and (
            record.account_family
            == USDC_PAIR_SNAPSHOT_LIVE_SERVICE_ACCOUNT_FAMILY
        )
        and record.venue_scope == USDC_PAIR_SNAPSHOT_LIVE_SERVICE_VENUE_SCOPE
        and (
            record.intx_applicability
            == USDC_PAIR_SNAPSHOT_LIVE_SERVICE_INTX_APPLICABILITY
        )
        and _usdc_pair_live_service_product_scope_matches(
            record,
            product_id=product_id,
        )
        and record.status == AdminApiGateStatus.BLOCKED
        and (
            record.requested_service_status
            == AdminApiLiveExecutionStatus.LIVE_DISABLED
        )
        and not record.service_enabled
        and not record.live_coinbase_execution_approved
        and _decimal_zero(record.max_submitted_notional_usdc)
        and _decimal_zero(record.max_executed_notional_usdc)
    )


def _enabled_usdc_pair_live_service_decision_matches(
    record: LiveServiceDecisionRecord,
    *,
    row: Any,
) -> bool:
    expected_decision_id = _expected_usdc_pair_live_service_decision_id(row)
    product_id = str(getattr(row, "product_id", "") or "")
    planned_notional = str(getattr(row, "planned_notional_usdc", "") or "")
    return (
        expected_decision_id is not None
        and product_id
        and planned_notional
        and record.decision_id == expected_decision_id
        and record.source == LIVE_SERVICE_DECISION_SOURCE
        and record.target_module_id == USDC_PAIR_SNAPSHOT_MODULE_ID
        and (
            record.account_family
            == USDC_PAIR_SNAPSHOT_LIVE_SERVICE_ACCOUNT_FAMILY
        )
        and record.venue_scope == USDC_PAIR_SNAPSHOT_LIVE_SERVICE_VENUE_SCOPE
        and (
            record.intx_applicability
            == USDC_PAIR_SNAPSHOT_LIVE_SERVICE_INTX_APPLICABILITY
        )
        and _usdc_pair_live_service_product_scope_matches(
            record,
            product_id=product_id,
        )
        and record.status == AdminApiGateStatus.PASSED
        and (
            record.requested_service_status
            == AdminApiLiveExecutionStatus.APPROVAL_REQUIRED
        )
        and record.service_enabled
        and record.live_coinbase_execution_approved
        and _decimal_equal(
            record.max_submitted_notional_usdc,
            planned_notional,
        )
        and _positive_decimal_at_most(
            record.max_executed_notional_usdc,
            record.max_submitted_notional_usdc,
        )
    )


def _resolve_disabled_usdc_pair_live_service_decision(
    *,
    store: FileAdminApiLiveServiceDecisionStore,
    row: Any,
) -> LiveServiceDecisionRecord | None:
    try:
        records = store.read_recent(limit=500)
    except OSError:
        return None
    return next(
        (
            record
            for record in records
            if _disabled_usdc_pair_live_service_decision_matches(
                record,
                row=row,
            )
        ),
        None,
    )


def _resolve_enabled_usdc_pair_live_service_decision(
    *,
    store: FileAdminApiLiveServiceDecisionStore,
    row: Any,
) -> LiveServiceDecisionRecord | None:
    try:
        records = store.read_recent(limit=500)
    except OSError:
        return None
    return next(
        (
            record
            for record in records
            if _enabled_usdc_pair_live_service_decision_matches(
                record,
                row=row,
            )
        ),
        None,
    )


def _resolve_usdc_pair_live_submit_record(
    *,
    store: FileUsdcPairSnapshotOrderPlanLiveSubmitStore,
    row: Any,
    live_service_decision: LiveServiceDecisionRecord,
) -> UsdcPairSnapshotOrderPlanLiveSubmitRecord | None:
    product_id = str(getattr(row, "product_id", "") or "")
    client_order_id = str(getattr(row, "client_order_id", "") or "")
    if not product_id or not client_order_id:
        return None
    try:
        records = store.read_recent(limit=500)
    except OSError:
        return None
    return next(
        (
            record
            for record in records
            if record.product_id.upper() == product_id.upper()
            and record.client_order_id == client_order_id
            and record.live_service_decision_id
            == live_service_decision.decision_id
            and record.order_count == 1
            and record.single_order_only
            and record.additional_orders_blocked
            and record.cancel_before_additional_orders
            and record.cancel_rollback_complete
            and record.live_exchange_submitted
            and record.live_coinbase_orders_ran
            and record.live_coinbase_execution == "submitted_cancelled"
        ),
        None,
    )


def _record_usdc_pair_live_readiness_preflight(
    *,
    plan: UsdcPairSnapshotOrderPlanRecord,
    row: Any,
    body: UsdcPairSnapshotOrderPlanLiveReadinessRequest,
    readiness_store: FileUsdcPairSnapshotOrderPlanLiveReadinessStore,
    live_service_decision_store: FileAdminApiLiveServiceDecisionStore,
    actor: AdminApiActor,
    operator_intent: str,
    idempotency_key: str,
    payload_hash: str,
    audit_id: str,
) -> UsdcPairSnapshotOrderPlanLiveReadinessItem:
    blockers: list[str] = []
    if row.plan_status != "planned":
        blockers.append("order_plan_row_not_planned")
    if not body.single_order_only:
        blockers.append("single_order_only_required")
    if body.full_snapshot_fill_test:
        blockers.append("manual_review_required_for_full_snapshot_fill_test")
    if not body.cancel_before_additional_orders:
        blockers.append("cancel_before_additional_orders_required")
    if not body.minimum_order_size_preferred:
        blockers.append("minimum_order_size_preferred_required")
    required_refs = {
        "approval_snapshot_missing": row.approval_snapshot_id,
        "admission_audit_missing": row.admission_audit_id,
        "cap_guard_decision_missing": row.cap_guard_decision_id,
        "reconciliation_plan_missing": row.reconciliation_plan_id,
    }
    blockers.extend(name for name, value in required_refs.items() if not value)
    live_service_decision = _resolve_enabled_usdc_pair_live_service_decision(
        store=live_service_decision_store,
        row=row,
    )
    if live_service_decision is None:
        blockers.append("enabled_live_service_decision_missing")

    intended_price = _decimal_value(body.intended_limit_price)
    reference_bid = _decimal_value(body.reference_bid_price)
    last_filled_price = _decimal_value(body.last_filled_price)
    submitted_notional = _decimal_value(body.submitted_notional_usdc)
    max_executed_notional = _decimal_value(body.max_executed_notional_usdc)
    planned_notional = _decimal_value(row.planned_notional_usdc)
    min_quote_size = _decimal_value(row.min_quote_size)
    base_size = _decimal_value(row.base_size)
    min_base_size = _decimal_value(row.min_base_size)
    far_from_bid_status = "blocked"
    snapshot_non_fill_status = "blocked"
    if intended_price is None:
        blockers.append("intended_limit_price_invalid")
    if reference_bid is None:
        blockers.append("reference_bid_price_invalid")
    if last_filled_price is None:
        blockers.append("last_filled_price_invalid")
    if submitted_notional is None:
        blockers.append("submitted_notional_invalid")
    if max_executed_notional is None:
        blockers.append("max_executed_notional_invalid")
    if planned_notional is None:
        blockers.append("planned_notional_invalid")
    if min_quote_size is None:
        blockers.append("minimum_quote_size_missing")
    if base_size is None or min_base_size is None or base_size < min_base_size:
        blockers.append("minimum_base_size_not_satisfied")
    if (
        submitted_notional is not None
        and planned_notional is not None
        and submitted_notional != planned_notional
    ):
        blockers.append("submitted_notional_must_equal_planned_notional")
    if (
        submitted_notional is not None
        and min_quote_size is not None
        and submitted_notional < min_quote_size
    ):
        blockers.append("minimum_quote_size_not_satisfied")
    if submitted_notional is not None and submitted_notional > Decimal("10"):
        blockers.append("spot_live_test_notional_exceeds_preferred_cap")
    if (
        max_executed_notional is not None
        and submitted_notional is not None
        and max_executed_notional > submitted_notional
    ):
        blockers.append("max_executed_notional_exceeds_submitted")

    if intended_price is not None and reference_bid is not None:
        if OrderSide(plan.side) == OrderSide.BUY:
            far_from_bid_status = (
                "passed"
                if intended_price <= reference_bid * Decimal("0.50")
                else "blocked"
            )
        else:
            far_from_bid_status = (
                "passed"
                if intended_price >= reference_bid * Decimal("1.50")
                else "blocked"
            )
        if far_from_bid_status != "passed":
            blockers.append("far_from_bid_price_required")
    if intended_price is not None and last_filled_price is not None:
        if OrderSide(plan.side) == OrderSide.BUY:
            snapshot_non_fill_status = (
                "passed"
                if intended_price <= last_filled_price * Decimal("0.90")
                else "blocked"
            )
        else:
            snapshot_non_fill_status = (
                "passed"
                if intended_price >= last_filled_price * Decimal("1.10")
                else "blocked"
            )
        if snapshot_non_fill_status != "passed":
            blockers.append("snapshot_non_fill_price_distance_required")

    if blockers:
        raise UsdcPairSnapshotError(
            "USDC pair snapshot live-readiness preflight blocked: "
            + ",".join(dict.fromkeys(blockers))
        )

    record = UsdcPairSnapshotOrderPlanLiveReadinessRecord(
        readiness_id=(
            body.readiness_id or f"m58-usdc-live-readiness-{uuid4()}"
        ),
        plan_id=plan.plan_id,
        snapshot_run_id=plan.snapshot_run_id,
        product_id=row.product_id,
        client_order_id=row.client_order_id,
        side=plan.side,
        order_count=1,
        single_order_only=body.single_order_only,
        minimum_order_size_preferred=body.minimum_order_size_preferred,
        reference_bid_price=body.reference_bid_price,
        last_filled_price=body.last_filled_price,
        intended_limit_price=body.intended_limit_price,
        far_from_bid_status=far_from_bid_status,
        snapshot_non_fill_status=snapshot_non_fill_status,
        submitted_notional_usdc=body.submitted_notional_usdc,
        max_submitted_notional_usdc=body.submitted_notional_usdc,
        max_executed_notional_usdc=body.max_executed_notional_usdc,
        planned_notional_usdc=row.planned_notional_usdc,
        base_size=row.base_size,
        quote_size=row.quote_size,
        min_base_size=row.min_base_size,
        min_quote_size=row.min_quote_size,
        preflight_passed=True,
        preflight_blockers=[],
        submit_route_ready=True,
        submit_blockers=[],
        cancel_before_additional_orders=body.cancel_before_additional_orders,
        cancel_rollback_plan_ref=body.cancel_rollback_plan_ref,
        full_snapshot_fill_test=body.full_snapshot_fill_test,
        approval_snapshot_id=row.approval_snapshot_id,
        admission_audit_id=row.admission_audit_id,
        cap_guard_decision_id=row.cap_guard_decision_id,
        reconciliation_plan_id=row.reconciliation_plan_id,
        live_service_decision_id=live_service_decision.decision_id,
        actor_id=actor.actor_id,
        operator_intent=operator_intent,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        audit_id=audit_id,
        operator_notes=body.operator_notes,
        detail=(
            "M58 Phase E readiness preflight accepted for one backend-owned "
            "USDC spot order-plan row. Coinbase submission is available only "
            "through the separate backend controlled-live submit/cancel route."
        ),
    )
    readiness_store.append(record)
    return _live_readiness_item_from_record(record)


def _find_usdc_pair_live_readiness_record(
    *,
    store: FileUsdcPairSnapshotOrderPlanLiveReadinessStore,
    readiness_id: str,
    product_id: str,
    client_order_id: str,
) -> UsdcPairSnapshotOrderPlanLiveReadinessRecord | None:
    normalized_product_id = product_id.upper()
    return next(
        (
            record
            for record in store.read_recent(limit=500)
            if record.readiness_id == readiness_id
            and record.product_id.upper() == normalized_product_id
            and record.client_order_id == client_order_id
        ),
        None,
    )


def _usdc_pair_live_order_configuration(
    readiness: UsdcPairSnapshotOrderPlanLiveReadinessRecord,
) -> dict[str, Any]:
    side = OrderSide(readiness.side)
    limit_order: dict[str, Any] = {}
    if side == OrderSide.BUY:
        limit_order["quote_size"] = readiness.submitted_notional_usdc
    else:
        if not readiness.base_size:
            raise UsdcPairSnapshotError(
                "USDC pair snapshot live submit blocked: sell base_size missing."
            )
        limit_order["base_size"] = readiness.base_size
    limit_order["limit_price"] = readiness.intended_limit_price
    limit_order["post_only"] = False
    return {"limit_limit_gtc": limit_order}


def _mapping_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _result_success(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, Mapping):
        success = value.get("success")
        if isinstance(success, bool):
            return success
    return bool(value)


def _record_usdc_pair_live_submission(
    *,
    plan: UsdcPairSnapshotOrderPlanRecord,
    row: Any,
    readiness: UsdcPairSnapshotOrderPlanLiveReadinessRecord,
    body: UsdcPairSnapshotOrderPlanLiveSubmitRequest,
    submit_store: FileUsdcPairSnapshotOrderPlanLiveSubmitStore,
    executor: UsdcPairSnapshotLiveOrderExecutor,
    actor: AdminApiActor,
    operator_intent: str,
    idempotency_key: str,
    payload_hash: str,
    audit_id: str,
) -> UsdcPairSnapshotOrderPlanLiveSubmitItem:
    blockers: list[str] = []
    if body.product_id.upper() != readiness.product_id.upper():
        blockers.append("readiness_product_mismatch")
    if body.client_order_id != readiness.client_order_id:
        blockers.append("readiness_client_order_id_mismatch")
    if plan.plan_id != readiness.plan_id:
        blockers.append("readiness_plan_mismatch")
    if row.client_order_id != readiness.client_order_id:
        blockers.append("order_plan_row_mismatch")
    if not body.confirm_live_submit:
        blockers.append("confirm_live_submit_required")
    if not body.confirm_single_order_only:
        blockers.append("confirm_single_order_only_required")
    if not body.confirm_cancel_before_additional_orders:
        blockers.append("confirm_cancel_before_additional_orders_required")
    if not body.confirm_no_additional_orders:
        blockers.append("confirm_no_additional_orders_required")
    if not body.operator_stop_conditions:
        blockers.append("operator_stop_conditions_required")
    if not readiness.preflight_passed:
        blockers.append("readiness_preflight_not_passed")
    if readiness.preflight_blockers:
        blockers.append("readiness_preflight_blockers_present")
    if not readiness.submit_route_ready:
        blockers.append("readiness_submit_route_not_ready")
    if readiness.submit_blockers:
        blockers.append("readiness_submit_blockers_present")
    if not readiness.single_order_only or readiness.order_count != 1:
        blockers.append("single_order_only_required")
    if readiness.full_snapshot_fill_test:
        blockers.append("manual_review_required_for_full_snapshot_fill_test")
    if not readiness.cancel_before_additional_orders:
        blockers.append("cancel_before_additional_orders_required")
    submitted_notional = _decimal_value(readiness.submitted_notional_usdc)
    max_executed_notional = _decimal_value(readiness.max_executed_notional_usdc)
    if submitted_notional is None:
        blockers.append("submitted_notional_invalid")
    elif submitted_notional > Decimal("10"):
        blockers.append("spot_live_test_notional_exceeds_preferred_cap")
    if max_executed_notional is None:
        blockers.append("max_executed_notional_invalid")
    elif submitted_notional is not None and max_executed_notional > submitted_notional:
        blockers.append("max_executed_notional_exceeds_submitted")
    if submit_store.find_latest_for_readiness(
        readiness_id=readiness.readiness_id,
        product_id=readiness.product_id,
        client_order_id=readiness.client_order_id,
    ):
        blockers.append("live_submission_already_recorded")

    if blockers:
        raise UsdcPairSnapshotError(
            "USDC pair snapshot live submit blocked: "
            + ",".join(dict.fromkeys(blockers))
        )

    order_configuration = _usdc_pair_live_order_configuration(readiness)
    try:
        execution = executor.submit_and_cancel(
            client_order_id=readiness.client_order_id,
            product_id=readiness.product_id,
            side=readiness.side,
            order_configuration=order_configuration,
            submitted_notional_usdc=readiness.submitted_notional_usdc,
            max_executed_notional_usdc=readiness.max_executed_notional_usdc,
            cancel_client_order_id=readiness.client_order_id,
        )
    except UsdcPairSnapshotLiveExecutionError as exc:
        raise UsdcPairSnapshotError(
            f"USDC pair snapshot live submit blocked: {exc}"
        ) from exc

    submit_result = _mapping_value(execution.get("submit_result"))
    cancel_result = _mapping_value(execution.get("cancel_result"))
    cancel_submitted = bool(
        execution.get("cancel_submitted", _result_success(cancel_result))
    )
    cancel_complete = bool(
        execution.get("cancel_rollback_complete", cancel_submitted)
    )
    live_exchange_submitted = bool(execution.get("live_exchange_submitted"))
    live_coinbase_orders_ran = bool(execution.get("live_coinbase_orders_ran"))
    live_execution = str(
        execution.get("live_coinbase_execution")
        or (
            "submitted_cancelled"
            if cancel_complete and live_exchange_submitted
            else "submitted_cancel_failed"
        )
    )

    record = UsdcPairSnapshotOrderPlanLiveSubmitRecord(
        submission_id=(
            body.submission_id or f"m58-usdc-live-submit-{uuid4()}"
        ),
        readiness_id=readiness.readiness_id,
        plan_id=plan.plan_id,
        snapshot_run_id=plan.snapshot_run_id,
        product_id=readiness.product_id,
        client_order_id=readiness.client_order_id,
        submitted_at=execution.get("submitted_at"),
        cancelled_at=execution.get("cancelled_at"),
        side=readiness.side,
        order_count=1,
        single_order_only=True,
        submitted_notional_usdc=readiness.submitted_notional_usdc,
        executed_notional_usdc=str(execution.get("executed_notional_usdc") or "0"),
        max_executed_notional_usdc=readiness.max_executed_notional_usdc,
        intended_limit_price=readiness.intended_limit_price,
        reference_bid_price=readiness.reference_bid_price,
        last_filled_price=readiness.last_filled_price,
        cancel_before_additional_orders=True,
        additional_orders_blocked=True,
        cancel_submitted=cancel_submitted,
        cancel_rollback_complete=cancel_complete,
        cancel_rollback_plan_ref=readiness.cancel_rollback_plan_ref,
        full_snapshot_fill_test=readiness.full_snapshot_fill_test,
        approval_snapshot_id=readiness.approval_snapshot_id,
        admission_audit_id=readiness.admission_audit_id,
        cap_guard_decision_id=readiness.cap_guard_decision_id,
        reconciliation_plan_id=readiness.reconciliation_plan_id,
        live_service_decision_id=readiness.live_service_decision_id,
        coinbase_order_id=(
            str(execution["coinbase_order_id"])
            if execution.get("coinbase_order_id")
            else None
        ),
        coinbase_order_id_evidence_only=True,
        order_configuration=dict(execution.get("order_configuration") or order_configuration),
        submit_result=submit_result,
        cancel_result=cancel_result,
        operator_stop_conditions=body.operator_stop_conditions,
        actor_id=actor.actor_id,
        operator_intent=operator_intent,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        audit_id=audit_id,
        operator_notes=body.operator_notes,
        live_exchange_submitted=live_exchange_submitted,
        live_coinbase_orders_ran=live_coinbase_orders_ran,
        live_coinbase_execution=live_execution,
        notional_usdc=(
            readiness.submitted_notional_usdc if live_exchange_submitted else "0"
        ),
        detail=(
            "M58 Phase E controlled-live evidence for one backend-owned USDC "
            "spot order-plan row. The backend submitted one Coinbase limit "
            "order by client_order_id and attempted immediate cancellation "
            "before any additional order."
        ),
    )
    submit_store.append(record)
    return _live_submit_item_from_record(record)


def _usdc_pair_order_plan_proof_chain_refresher(
    *,
    approval_store: FileAdminApiApprovalStore,
    admission_audit_store: FileAdminApiAuditStore,
    cap_guard_store: FileAdminApiCapGuardStore,
    reconciliation_store: FileAdminApiReconciliationStore,
    live_service_decision_store: FileAdminApiLiveServiceDecisionStore,
    live_submit_store: FileUsdcPairSnapshotOrderPlanLiveSubmitStore,
) -> Callable[[Any, Any], dict[str, Any]]:
    def refresh(plan: Any, row: Any) -> dict[str, Any]:
        client_order_id = str(getattr(row, "client_order_id", "") or "")
        row_idempotency_key = str(getattr(row, "idempotency_key", "") or "")
        if not client_order_id or not row_idempotency_key:
            return {}

        approval_snapshot = resolve_approval_snapshot(
            store=approval_store,
            request=ApprovalSnapshotRequest(
                route=USDC_PAIR_SNAPSHOT_ORDER_PLAN_ROUTE,
                method="POST",
                module_id=USDC_PAIR_SNAPSHOT_MODULE_ID,
                identity_key="client_order_id",
                identity_value=client_order_id,
                action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
                required_permission=AdminApiPermission.CAMPAIGN_EXECUTE,
                requested_by_actor_id=str(getattr(plan, "actor_id", "") or ""),
                operator_intent=str(getattr(plan, "operator_intent", "") or ""),
                idempotency_key=row_idempotency_key,
                payload_hash=str(getattr(plan, "payload_hash", "") or ""),
            ),
        )
        if approval_snapshot is None:
            return {}

        blockers = [
            blocker
            for blocker in getattr(row, "proof_chain_blockers", [])
            if blocker != "approval_snapshot_missing"
        ]
        admission_audit = resolve_admission_audit_trail(
            store=admission_audit_store,
            request=AdmissionAuditTrailRequest(
                route=USDC_PAIR_SNAPSHOT_ORDER_PLAN_ROUTE,
                method="POST",
                module_id=USDC_PAIR_SNAPSHOT_MODULE_ID,
                identity_key="client_order_id",
                identity_value=client_order_id,
                action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
                required_permission=AdminApiPermission.CAMPAIGN_EXECUTE,
                service_method=USDC_PAIR_SNAPSHOT_ORDER_PLAN_SERVICE_METHOD,
                actor_id=str(getattr(plan, "actor_id", "") or ""),
                operator_intent=str(getattr(plan, "operator_intent", "") or ""),
                idempotency_key=row_idempotency_key,
                payload_hash=str(getattr(plan, "payload_hash", "") or ""),
                approval_snapshot_id=approval_snapshot.approval_id,
            ),
        )
        if admission_audit is not None:
            blockers = [
                blocker
                for blocker in blockers
                if blocker != "admission_audit_blocked"
            ]
        cap_guard = None
        if admission_audit is not None:
            cap_guard = resolve_cap_guard_decision(
                store=cap_guard_store,
                request=CapGuardDecisionRequest(
                    route=USDC_PAIR_SNAPSHOT_ORDER_PLAN_ROUTE,
                    method="POST",
                    module_id=USDC_PAIR_SNAPSHOT_MODULE_ID,
                    identity_key="client_order_id",
                    identity_value=client_order_id,
                    action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
                    required_permission=AdminApiPermission.CAMPAIGN_EXECUTE,
                    service_method=USDC_PAIR_SNAPSHOT_ORDER_PLAN_SERVICE_METHOD,
                    actor_id=str(getattr(plan, "actor_id", "") or ""),
                    operator_intent=str(
                        getattr(plan, "operator_intent", "") or ""
                    ),
                    idempotency_key=row_idempotency_key,
                    payload_hash=str(getattr(plan, "payload_hash", "") or ""),
                    approval_snapshot_id=approval_snapshot.approval_id,
                    approval_cap_guard_decision_ref=(
                        approval_snapshot.cap_guard_decision_ref
                    ),
                    admission_audit_id=admission_audit.audit_id,
                    max_submitted_notional_usdc=str(
                        getattr(row, "planned_notional_usdc", "") or ""
                    ),
                    max_executed_notional_usdc="0",
                ),
            )
        if cap_guard is not None:
            blockers = [
                blocker
                for blocker in blockers
                if blocker != "cap_guard_decision_blocked"
            ]
        reconciliation = None
        if admission_audit is not None and cap_guard is not None:
            reconciliation = resolve_reconciliation_plan(
                store=reconciliation_store,
                request=ReconciliationPlanRequest(
                    route=USDC_PAIR_SNAPSHOT_ORDER_PLAN_ROUTE,
                    method="POST",
                    module_id=USDC_PAIR_SNAPSHOT_MODULE_ID,
                    identity_key="client_order_id",
                    identity_value=client_order_id,
                    action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
                    required_permission=AdminApiPermission.CAMPAIGN_EXECUTE,
                    service_method=USDC_PAIR_SNAPSHOT_ORDER_PLAN_SERVICE_METHOD,
                    actor_id=str(getattr(plan, "actor_id", "") or ""),
                    operator_intent=str(
                        getattr(plan, "operator_intent", "") or ""
                    ),
                    idempotency_key=row_idempotency_key,
                    payload_hash=str(getattr(plan, "payload_hash", "") or ""),
                    approval_snapshot_id=approval_snapshot.approval_id,
                    approval_reconciliation_plan_ref=(
                        approval_snapshot.reconciliation_plan_ref
                    ),
                    admission_audit_id=admission_audit.audit_id,
                    cap_guard_decision_id=cap_guard.decision_id,
                    exchange_submission_required=False,
                    post_submit_reconciliation_required=False,
                    max_submitted_notional_usdc=str(
                        getattr(row, "planned_notional_usdc", "") or ""
                    ),
                    max_executed_notional_usdc="0",
                ),
            )
        if reconciliation is not None:
            blockers = [
                blocker
                for blocker in blockers
                if blocker != "reconciliation_plan_blocked"
            ]
        live_service_decision = None
        live_submission_record = None
        live_submission_missing = False
        live_service_disabled = False
        if reconciliation is not None:
            live_service_decision = (
                _resolve_disabled_usdc_pair_live_service_decision(
                    store=live_service_decision_store,
                    row=row,
                )
            )
            live_service_disabled = live_service_decision is not None
            if live_service_decision is None:
                live_service_decision = (
                    _resolve_enabled_usdc_pair_live_service_decision(
                        store=live_service_decision_store,
                        row=row,
                    )
                )
                if live_service_decision is not None:
                    live_submission_record = (
                        _resolve_usdc_pair_live_submit_record(
                            store=live_submit_store,
                            row=row,
                            live_service_decision=live_service_decision,
                        )
                    )
                    live_submission_missing = live_submission_record is None
        if live_service_decision is not None:
            blockers = [
                blocker
                for blocker in blockers
                if blocker != "live_service_decision_missing"
            ]
            if live_submission_record is not None:
                blockers = [
                    blocker
                    for blocker in blockers
                    if blocker
                    not in {
                        USDC_PAIR_SNAPSHOT_LIVE_SERVICE_DISABLED_BLOCKER,
                        USDC_PAIR_SNAPSHOT_LIVE_SUBMISSION_MISSING_BLOCKER,
                    }
                ]
            elif live_submission_missing:
                blockers = [
                    blocker
                    for blocker in blockers
                    if blocker
                    != USDC_PAIR_SNAPSHOT_LIVE_SERVICE_DISABLED_BLOCKER
                ]
                if (
                    USDC_PAIR_SNAPSHOT_LIVE_SUBMISSION_MISSING_BLOCKER
                    not in blockers
                ):
                    blockers.append(
                        USDC_PAIR_SNAPSHOT_LIVE_SUBMISSION_MISSING_BLOCKER
                    )
            elif live_service_disabled and (
                USDC_PAIR_SNAPSHOT_LIVE_SERVICE_DISABLED_BLOCKER not in blockers
            ):
                blockers = [
                    blocker
                    for blocker in blockers
                    if blocker
                    != USDC_PAIR_SNAPSHOT_LIVE_SUBMISSION_MISSING_BLOCKER
                ]
                blockers.append(
                    USDC_PAIR_SNAPSHOT_LIVE_SERVICE_DISABLED_BLOCKER
                )
        approval_request_id = _approval_request_id_for_snapshot(
            approval_store=approval_store,
            approval_id=approval_snapshot.approval_id,
        )
        return {
            "proof_chain_status": "blocked" if blockers else "accepted",
            "proof_chain_blockers": list(dict.fromkeys(blockers)),
            "approval_request_required": True,
            "approval_request_id": approval_request_id
            or getattr(row, "approval_request_id", None),
            "approval_snapshot_required": True,
            "approval_snapshot_id": approval_snapshot.approval_id,
            "admission_audit_id": (
                admission_audit.audit_id
                if admission_audit is not None
                else getattr(row, "admission_audit_id", None)
            ),
            "cap_guard_decision_id": (
                cap_guard.decision_id
                if cap_guard is not None
                else getattr(row, "cap_guard_decision_id", None)
            ),
            "reconciliation_plan_id": (
                reconciliation.plan_id
                if reconciliation is not None
                else getattr(row, "reconciliation_plan_id", None)
            ),
            "live_service_decision_id": (
                live_service_decision.decision_id
                if live_service_decision is not None
                else getattr(row, "live_service_decision_id", None)
            ),
            "live_exchange_submitted": (
                live_submission_record.live_exchange_submitted
                if live_submission_record is not None
                else False
            ),
            "live_coinbase_orders_ran": (
                live_submission_record.live_coinbase_orders_ran
                if live_submission_record is not None
                else False
            ),
            "live_coinbase_execution": (
                live_submission_record.live_coinbase_execution
                if live_submission_record is not None
                else "not_run"
            ),
            "notional_usdc": (
                live_submission_record.notional_usdc
                if live_submission_record is not None
                else "0"
            ),
        }

    return refresh


@router.post(
    "/automation/usdc-pair-snapshot-runs",
    response_model=UsdcPairSnapshotRunResponse,
    status_code=status.HTTP_200_OK,
    responses=AUTOMATION_ROUTE_RESPONSES,
    summary="Record backend-owned USDC pair snapshot dry-run evidence",
)
def record_usdc_pair_snapshot_dry_run(
    request: Request,
    body: UsdcPairSnapshotRunRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        AdminApiUsdcPairSnapshotService,
        Depends(get_usdc_pair_snapshot_service),
    ],
    snapshot_store: Annotated[
        FileUsdcPairSnapshotRunStore,
        Depends(get_usdc_pair_snapshot_store),
    ],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
) -> JSONResponse:
    """Record M58 dry-run product snapshot rows without Coinbase order calls."""

    endpoint = f"{request.method} {request.url.path}"
    payload_hash = _payload_hash(
        endpoint=endpoint,
        actor=actor,
        operator_intent=operator_intent,
        body=body.model_dump(mode="json"),
    )
    return _execute_idempotent_snapshot(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        request_id=correlation_id,
        operator_intent=operator_intent,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        operation=lambda audit_id: service.record_snapshot_run(
            store=snapshot_store,
            body=body,
            actor_id=actor.actor_id,
            operator_intent=operator_intent,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            audit_id=audit_id,
        ),
    )


@router.post(
    "/automation/usdc-pair-snapshot-runs/{run_id}/order-plans",
    response_model=UsdcPairSnapshotOrderPlanResponse,
    status_code=status.HTTP_200_OK,
    responses=ORDER_PLAN_ROUTE_RESPONSES,
    summary="Record backend-owned USDC pair snapshot order-plan evidence",
)
def record_usdc_pair_snapshot_order_plan(
    request: Request,
    run_id: str,
    body: UsdcPairSnapshotOrderPlanRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        AdminApiUsdcPairSnapshotService,
        Depends(get_usdc_pair_snapshot_service),
    ],
    snapshot_store: Annotated[
        FileUsdcPairSnapshotRunStore,
        Depends(get_usdc_pair_snapshot_store),
    ],
    order_plan_store: Annotated[
        FileUsdcPairSnapshotOrderPlanStore,
        Depends(get_usdc_pair_snapshot_order_plan_store),
    ],
    proof_chain_service: Annotated[
        AdminMvpService,
        Depends(get_usdc_pair_snapshot_proof_chain_service),
    ],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
) -> JSONResponse:
    """Record M58 dry-run limit-order plan rows without Coinbase order calls."""

    endpoint = f"{request.method} {request.url.path}"
    payload_hash = _payload_hash(
        endpoint=endpoint,
        actor=actor,
        operator_intent=operator_intent,
        body=body.model_dump(mode="json"),
    )
    return _execute_idempotent_order_plan(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        request_id=correlation_id,
        operator_intent=operator_intent,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        operation=lambda audit_id: service.record_order_plan(
            snapshot_store=snapshot_store,
            order_plan_store=order_plan_store,
            run_id=run_id,
            body=body,
            actor_id=actor.actor_id,
            operator_intent=operator_intent,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            audit_id=audit_id,
            proof_chain_recorder=_usdc_pair_order_plan_proof_chain_recorder(
                proof_chain_service=proof_chain_service,
                correlation_id=correlation_id,
                operator_intent=operator_intent,
                actor=actor,
                payload_hash=payload_hash,
            ),
        ),
    )


@router.post(
    "/automation/usdc-pair-snapshot-order-plans/{plan_id}/proof-chain-refresh",
    response_model=UsdcPairSnapshotOrderPlanResponse,
    status_code=status.HTTP_200_OK,
    responses=ORDER_PLAN_ROUTE_RESPONSES,
    summary="Refresh backend-owned USDC pair order-plan proof-chain evidence",
)
def refresh_usdc_pair_snapshot_order_plan_proof_chain(
    request: Request,
    plan_id: str,
    body: UsdcPairSnapshotOrderPlanProofRefreshRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        AdminApiUsdcPairSnapshotService,
        Depends(get_usdc_pair_snapshot_service),
    ],
    order_plan_store: Annotated[
        FileUsdcPairSnapshotOrderPlanStore,
        Depends(get_usdc_pair_snapshot_order_plan_store),
    ],
    approval_store: Annotated[
        FileAdminApiApprovalStore,
        Depends(get_usdc_pair_snapshot_approval_store),
    ],
    cap_guard_store: Annotated[
        FileAdminApiCapGuardStore,
        Depends(get_usdc_pair_snapshot_cap_guard_store),
    ],
    reconciliation_store: Annotated[
        FileAdminApiReconciliationStore,
        Depends(get_usdc_pair_snapshot_reconciliation_store),
    ],
    live_service_decision_store: Annotated[
        FileAdminApiLiveServiceDecisionStore,
        Depends(get_usdc_pair_snapshot_live_service_decision_store),
    ],
    live_submit_store: Annotated[
        FileUsdcPairSnapshotOrderPlanLiveSubmitStore,
        Depends(get_usdc_pair_snapshot_order_plan_live_submit_store),
    ],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
) -> JSONResponse:
    """Refresh M58 order-plan proof refs from backend approval lifecycle state."""

    endpoint = f"{request.method} {request.url.path}"
    payload_hash = _payload_hash(
        endpoint=endpoint,
        actor=actor,
        operator_intent=operator_intent,
        body=body.model_dump(mode="json"),
    )
    return _execute_idempotent_order_plan(
        endpoint=USDC_PAIR_SNAPSHOT_ORDER_PLAN_PROOF_REFRESH_ENDPOINT,
        service_method=(
            USDC_PAIR_SNAPSHOT_ORDER_PLAN_PROOF_REFRESH_SERVICE_METHOD
        ),
        accepted_message=(
            "USDC pair snapshot order-plan proof-chain refresh accepted."
        ),
        failure_stage="usdc_pair_snapshot_order_plan_proof_refresh",
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        request_id=correlation_id,
        operator_intent=operator_intent,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        operation=lambda audit_id: service.refresh_order_plan_proof_chain(
            order_plan_store=order_plan_store,
            plan_id=plan_id,
            body=body,
            audit_id=audit_id,
            proof_chain_refresher=_usdc_pair_order_plan_proof_chain_refresher(
                approval_store=approval_store,
                admission_audit_store=audit_store,
                cap_guard_store=cap_guard_store,
                reconciliation_store=reconciliation_store,
                live_service_decision_store=live_service_decision_store,
                live_submit_store=live_submit_store,
            ),
        ),
    )


@router.post(
    "/automation/usdc-pair-snapshot-order-plans/{plan_id}/live-readiness",
    response_model=UsdcPairSnapshotOrderPlanLiveReadinessResponse,
    status_code=status.HTTP_200_OK,
    responses=LIVE_READINESS_ROUTE_RESPONSES,
    summary="Record backend-owned USDC pair order-plan live-readiness preflight",
)
def record_usdc_pair_snapshot_order_plan_live_readiness(
    request: Request,
    plan_id: str,
    body: UsdcPairSnapshotOrderPlanLiveReadinessRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    order_plan_store: Annotated[
        FileUsdcPairSnapshotOrderPlanStore,
        Depends(get_usdc_pair_snapshot_order_plan_store),
    ],
    readiness_store: Annotated[
        FileUsdcPairSnapshotOrderPlanLiveReadinessStore,
        Depends(get_usdc_pair_snapshot_order_plan_live_readiness_store),
    ],
    live_service_decision_store: Annotated[
        FileAdminApiLiveServiceDecisionStore,
        Depends(get_usdc_pair_snapshot_live_service_decision_store),
    ],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
) -> JSONResponse:
    """Preflight one M58 order-plan row without submitting to Coinbase."""

    endpoint = f"{request.method} {request.url.path}"
    payload_hash = _payload_hash(
        endpoint=endpoint,
        actor=actor,
        operator_intent=operator_intent,
        body=body.model_dump(mode="json"),
    )

    def operation(audit_id: str) -> UsdcPairSnapshotOrderPlanLiveReadinessItem:
        plan = order_plan_store.find_by_plan_id(plan_id)
        if plan is None:
            raise UsdcPairSnapshotError(
                "USDC pair snapshot order-plan not found."
            )
        row = _find_usdc_pair_order_plan_row(
            plan,
            product_id=body.product_id,
            client_order_id=body.client_order_id,
        )
        if row is None:
            raise UsdcPairSnapshotError(
                "USDC pair snapshot order-plan row not found."
            )
        return _record_usdc_pair_live_readiness_preflight(
            plan=plan,
            row=row,
            body=body,
            readiness_store=readiness_store,
            live_service_decision_store=live_service_decision_store,
            actor=actor,
            operator_intent=operator_intent,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            audit_id=audit_id,
        )

    return _execute_idempotent_live_readiness(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        request_id=correlation_id,
        operator_intent=operator_intent,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        operation=operation,
    )


@router.post(
    "/automation/usdc-pair-snapshot-order-plans/{plan_id}/live-submit",
    response_model=UsdcPairSnapshotOrderPlanLiveSubmitResponse,
    status_code=status.HTTP_200_OK,
    responses=LIVE_SUBMIT_ROUTE_RESPONSES,
    summary="Submit and cancel one backend-owned USDC pair snapshot order",
)
def submit_usdc_pair_snapshot_order_plan_live_order(
    request: Request,
    plan_id: str,
    body: UsdcPairSnapshotOrderPlanLiveSubmitRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    order_plan_store: Annotated[
        FileUsdcPairSnapshotOrderPlanStore,
        Depends(get_usdc_pair_snapshot_order_plan_store),
    ],
    readiness_store: Annotated[
        FileUsdcPairSnapshotOrderPlanLiveReadinessStore,
        Depends(get_usdc_pair_snapshot_order_plan_live_readiness_store),
    ],
    submit_store: Annotated[
        FileUsdcPairSnapshotOrderPlanLiveSubmitStore,
        Depends(get_usdc_pair_snapshot_order_plan_live_submit_store),
    ],
    executor: Annotated[
        UsdcPairSnapshotLiveOrderExecutor,
        Depends(get_usdc_pair_snapshot_live_order_executor),
    ],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
) -> JSONResponse:
    """Submit one preflighted M58 order and cancel before any additional order."""

    endpoint = f"{request.method} {request.url.path}"
    payload_hash = _payload_hash(
        endpoint=endpoint,
        actor=actor,
        operator_intent=operator_intent,
        body=body.model_dump(mode="json"),
    )

    def operation(audit_id: str) -> UsdcPairSnapshotOrderPlanLiveSubmitItem:
        plan = order_plan_store.find_by_plan_id(plan_id)
        if plan is None:
            raise UsdcPairSnapshotError(
                "USDC pair snapshot order-plan not found."
            )
        row = _find_usdc_pair_order_plan_row(
            plan,
            product_id=body.product_id,
            client_order_id=body.client_order_id,
        )
        if row is None:
            raise UsdcPairSnapshotError(
                "USDC pair snapshot order-plan row not found."
            )
        readiness = _find_usdc_pair_live_readiness_record(
            store=readiness_store,
            readiness_id=body.readiness_id,
            product_id=body.product_id,
            client_order_id=body.client_order_id,
        )
        if readiness is None:
            raise UsdcPairSnapshotError(
                "USDC pair snapshot live-readiness record not found."
            )
        return _record_usdc_pair_live_submission(
            plan=plan,
            row=row,
            readiness=readiness,
            body=body,
            submit_store=submit_store,
            executor=executor,
            actor=actor,
            operator_intent=operator_intent,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            audit_id=audit_id,
        )

    return _execute_idempotent_live_submit(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        request_id=correlation_id,
        operator_intent=operator_intent,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        operation=operation,
    )
