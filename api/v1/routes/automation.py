"""Automation Admin API routes."""

from __future__ import annotations

from datetime import datetime, timezone
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
    UsdcPairSnapshotAllowlistRunStateItem,
    UsdcPairSnapshotAllowlistRunStateListResponse,
    UsdcPairSnapshotAllowlistRunStateProductItem,
    UsdcPairSnapshotAllowlistRunStateRequest,
    UsdcPairSnapshotAllowlistRunStateResponse,
    UsdcPairSnapshotOrderPlanAllowlistReadinessItem,
    UsdcPairSnapshotOrderPlanAllowlistReadinessListResponse,
    UsdcPairSnapshotOrderPlanAllowlistReadinessProductItem,
    UsdcPairSnapshotOrderPlanAllowlistReadinessRequest,
    UsdcPairSnapshotOrderPlanAllowlistReadinessResponse,
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
    FileUsdcPairSnapshotAllowlistRunStateStore,
    FileUsdcPairSnapshotLiveWalletReservationStore,
    FileUsdcPairSnapshotOrderPlanAllowlistReadinessStore,
    FileUsdcPairSnapshotOrderPlanLiveReadinessStore,
    FileUsdcPairSnapshotOrderPlanLiveSubmitStore,
    FileUsdcPairSnapshotOrderPlanStore,
    FileUsdcPairSnapshotRunStore,
    UsdcPairSnapshotAllowlistRunStateRecord,
    UsdcPairSnapshotLiveWalletReservationRecord,
    UsdcPairSnapshotOrderPlanAllowlistReadinessRecord,
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
USDC_PAIR_LIVE_REFERENCE_MAX_AGE_SECONDS = 300
USDC_PAIR_LIVE_REFERENCE_FUTURE_TOLERANCE_SECONDS = 5

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
USDC_PAIR_SNAPSHOT_ORDER_PLAN_ALLOWLIST_READINESS_ROUTE = (
    "/api/v1/automation/usdc-pair-snapshot-order-plans/"
    "{plan_id}/allowlist-readiness"
)
USDC_PAIR_SNAPSHOT_ORDER_PLAN_ALLOWLIST_READINESS_ENDPOINT = (
    f"POST {USDC_PAIR_SNAPSHOT_ORDER_PLAN_ALLOWLIST_READINESS_ROUTE}"
)
USDC_PAIR_SNAPSHOT_ORDER_PLAN_ALLOWLIST_READINESS_SERVICE_METHOD = (
    "record_usdc_pair_snapshot_order_plan_allowlist_readiness"
)
USDC_PAIR_SNAPSHOT_ALLOWLIST_RUN_STATE_ROUTE = (
    "/api/v1/automation/usdc-pair-snapshot-order-plan-allowlist-readiness/"
    "{readiness_id}/run-state"
)
USDC_PAIR_SNAPSHOT_ALLOWLIST_RUN_STATE_ENDPOINT = (
    f"POST {USDC_PAIR_SNAPSHOT_ALLOWLIST_RUN_STATE_ROUTE}"
)
USDC_PAIR_SNAPSHOT_ALLOWLIST_RUN_STATE_SERVICE_METHOD = (
    "record_usdc_pair_snapshot_allowlist_run_state"
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
USDC_PAIR_SNAPSHOT_ALLOWLIST_RUN_STATE_LIVE_SUBMIT_ROUTE = (
    "/api/v1/automation/usdc-pair-snapshot-allowlist-run-states/"
    "{run_state_id}/live-submit"
)
USDC_PAIR_SNAPSHOT_ALLOWLIST_RUN_STATE_LIVE_SUBMIT_ENDPOINT = (
    f"POST {USDC_PAIR_SNAPSHOT_ALLOWLIST_RUN_STATE_LIVE_SUBMIT_ROUTE}"
)
USDC_PAIR_SNAPSHOT_ALLOWLIST_RUN_STATE_LIVE_SUBMIT_SERVICE_METHOD = (
    "submit_usdc_pair_snapshot_allowlist_run_state_live_order"
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
USDC_PAIR_SNAPSHOT_LIVE_WALLET_RESERVATION_BLOCKERS = [
    "live_wallet_reservation_missing",
    "live_wallet_debit_missing",
    "live_wallet_release_missing",
]
USDC_PAIR_SNAPSHOT_LIVE_WALLET_RESERVATION_REF_CONFLICT_BLOCKER = (
    "live_wallet_reservation_ref_conflict"
)
USDC_PAIR_SNAPSHOT_LIVE_WALLET_DEBIT_REF_CONFLICT_BLOCKER = (
    "live_wallet_debit_ref_conflict"
)
USDC_PAIR_SNAPSHOT_LIVE_WALLET_RELEASE_REF_CONFLICT_BLOCKER = (
    "live_wallet_release_ref_conflict"
)
USDC_PAIR_SNAPSHOT_RUN_LOCK_MISSING_BLOCKER = "run_lock_ref_missing"
USDC_PAIR_SNAPSHOT_RUN_LOCK_CONFLICT_BLOCKER = "run_lock_ref_conflict"
USDC_PAIR_SNAPSHOT_RATE_LIMIT_WINDOW_MISSING_BLOCKER = (
    "rate_limit_window_ref_missing"
)
USDC_PAIR_SNAPSHOT_RATE_LIMIT_WINDOW_CONFLICT_BLOCKER = (
    "rate_limit_window_ref_conflict"
)
USDC_PAIR_SNAPSHOT_RATE_LIMIT_WINDOW_CAPACITY_BLOCKER = (
    "rate_limit_window_capacity_exceeded"
)
USDC_PAIR_SNAPSHOT_DEFAULT_RATE_LIMIT_WINDOW_ORDER_CAP = 5
USDC_PAIR_SNAPSHOT_RETRY_BUDGET_EXHAUSTED_BLOCKER = "retry_budget_exhausted"
USDC_PAIR_SNAPSHOT_RETRY_BACKOFF_MISSING_BLOCKER = "retry_backoff_ref_missing"
USDC_PAIR_SNAPSHOT_RETRY_BACKOFF_CONFLICT_BLOCKER = "retry_backoff_ref_conflict"
USDC_PAIR_SNAPSHOT_RUN_PAUSED_BLOCKER = "run_paused_no_live"
USDC_PAIR_SNAPSHOT_RUN_ABORTED_BLOCKER = "run_aborted_no_live"
USDC_PAIR_SNAPSHOT_RUN_STATE_LIVE_SUBMIT_ALLOWED_FANOUT_BLOCKERS = {
    "fanout_execution_not_approved",
    "scheduler_blocked",
}
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

ALLOWLIST_READINESS_ROUTE_RESPONSES = {
    200: {
        "model": UsdcPairSnapshotOrderPlanAllowlistReadinessResponse,
        "description": (
            "USDC pair snapshot order-plan allowlist-readiness evidence "
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
        "model": UsdcPairSnapshotOrderPlanAllowlistReadinessResponse,
        "description": "Idempotency key conflict.",
    },
}

ALLOWLIST_RUN_STATE_ROUTE_RESPONSES = {
    200: {
        "model": UsdcPairSnapshotAllowlistRunStateResponse,
        "description": (
            "USDC pair snapshot allowlist run-state evidence accepted, "
            "rejected, or replayed without Coinbase submission."
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
        "model": UsdcPairSnapshotAllowlistRunStateResponse,
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


def get_usdc_pair_snapshot_order_plan_allowlist_readiness_store() -> (
    FileUsdcPairSnapshotOrderPlanAllowlistReadinessStore
):
    """Return durable M58 allowlist-readiness evidence storage."""

    return FileUsdcPairSnapshotOrderPlanAllowlistReadinessStore()


def get_usdc_pair_snapshot_allowlist_run_state_store() -> (
    FileUsdcPairSnapshotAllowlistRunStateStore
):
    """Return durable M58 allowlist run-state evidence storage."""

    return FileUsdcPairSnapshotAllowlistRunStateStore()


def get_usdc_pair_snapshot_live_wallet_reservation_store() -> (
    FileUsdcPairSnapshotLiveWalletReservationStore
):
    """Return durable M58 live-wallet reservation evidence storage."""

    return FileUsdcPairSnapshotLiveWalletReservationStore()


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


def _allowlist_readiness_item_from_record(
    record: UsdcPairSnapshotOrderPlanAllowlistReadinessRecord,
) -> UsdcPairSnapshotOrderPlanAllowlistReadinessItem:
    return UsdcPairSnapshotOrderPlanAllowlistReadinessItem(
        readiness_id=record.readiness_id,
        plan_id=record.plan_id,
        snapshot_run_id=record.snapshot_run_id,
        recorded_at=record.recorded_at,
        product_ids=record.product_ids,
        selected_product_count=record.selected_product_count,
        max_products=record.max_products,
        candidate_product_ids=record.candidate_product_ids,
        blocked_product_ids=record.blocked_product_ids,
        cap_exhausted_product_ids=record.cap_exhausted_product_ids,
        missing_product_ids=record.missing_product_ids,
        retryable_product_ids=record.retryable_product_ids,
        recovery_required_product_ids=record.recovery_required_product_ids,
        partial_success_status=record.partial_success_status,
        failure_isolation_status=record.failure_isolation_status,
        run_rate_limit_status=record.run_rate_limit_status,
        retry_budget_status=record.retry_budget_status,
        recovery_readiness_status=record.recovery_readiness_status,
        retry_budget_per_product=record.retry_budget_per_product,
        run_rate_limit_budget_ref=record.run_rate_limit_budget_ref,
        cancel_recovery_plan_ref=record.cancel_recovery_plan_ref,
        fanout_readiness_status=record.fanout_readiness_status,
        fanout_blockers=record.fanout_blockers,
        product_readiness_rows=record.product_readiness_rows,
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


def _allowlist_readiness_list_response(
    *,
    store: FileUsdcPairSnapshotOrderPlanAllowlistReadinessStore,
    limit: int,
) -> UsdcPairSnapshotOrderPlanAllowlistReadinessListResponse:
    readiness = [
        _allowlist_readiness_item_from_record(record)
        for record in store.read_recent(limit=limit)
    ]
    return UsdcPairSnapshotOrderPlanAllowlistReadinessListResponse(
        readiness=readiness,
        returned_count=len(readiness),
        total_count=store.count_records(),
        latest_readiness_id=readiness[0].readiness_id if readiness else None,
        blocked_count=sum(
            1 for item in readiness if item.fanout_readiness_status == "blocked"
        ),
        candidate_product_count=sum(
            len(item.candidate_product_ids) for item in readiness
        ),
        cap_exhausted_product_count=sum(
            len(item.cap_exhausted_product_ids) for item in readiness
        ),
        retryable_product_count=sum(
            len(item.retryable_product_ids) for item in readiness
        ),
        recovery_required_product_count=sum(
            len(item.recovery_required_product_ids) for item in readiness
        ),
    )


def _allowlist_run_state_item_from_record(
    record: UsdcPairSnapshotAllowlistRunStateRecord,
) -> UsdcPairSnapshotAllowlistRunStateItem:
    return UsdcPairSnapshotAllowlistRunStateItem(
        run_state_id=record.run_state_id,
        readiness_id=record.readiness_id,
        plan_id=record.plan_id,
        snapshot_run_id=record.snapshot_run_id,
        recorded_at=record.recorded_at,
        execution_mode=record.execution_mode,
        max_fanout_notional_usdc=record.max_fanout_notional_usdc,
        planned_fanout_notional_usdc=record.planned_fanout_notional_usdc,
        allocated_fanout_notional_usdc=record.allocated_fanout_notional_usdc,
        fanout_cap_remaining_usdc=record.fanout_cap_remaining_usdc,
        fanout_cap_overage_usdc=record.fanout_cap_overage_usdc,
        fanout_cap_allocation_status=record.fanout_cap_allocation_status,
        wallet_allocation_status=record.wallet_allocation_status,
        wallet_available_notional_usdc=record.wallet_available_notional_usdc,
        wallet_allocated_notional_usdc=record.wallet_allocated_notional_usdc,
        wallet_remaining_usdc=record.wallet_remaining_usdc,
        wallet_allocation_blockers=record.wallet_allocation_blockers,
        live_wallet_reservation_status=record.live_wallet_reservation_status,
        live_wallet_reservation_ids=record.live_wallet_reservation_ids,
        live_wallet_reserved_notional_usdc=(
            record.live_wallet_reserved_notional_usdc
        ),
        live_wallet_debit_ids=record.live_wallet_debit_ids,
        live_wallet_debited_notional_usdc=(
            record.live_wallet_debited_notional_usdc
        ),
        live_wallet_release_ids=record.live_wallet_release_ids,
        live_wallet_released_notional_usdc=(
            record.live_wallet_released_notional_usdc
        ),
        live_wallet_reservation_blockers=(
            record.live_wallet_reservation_blockers
        ),
        live_readiness_status=record.live_readiness_status,
        live_ready_product_ids=record.live_ready_product_ids,
        live_readiness_missing_product_ids=(
            record.live_readiness_missing_product_ids
        ),
        live_readiness_blocked_product_ids=(
            record.live_readiness_blocked_product_ids
        ),
        live_readiness_blockers=record.live_readiness_blockers,
        fanout_notional_status=record.fanout_notional_status,
        product_ids=record.product_ids,
        queued_product_ids=record.queued_product_ids,
        blocked_product_ids=record.blocked_product_ids,
        retryable_product_ids=record.retryable_product_ids,
        recovery_required_product_ids=record.recovery_required_product_ids,
        queued_product_count=record.queued_product_count,
        blocked_product_count=record.blocked_product_count,
        retryable_product_count=record.retryable_product_count,
        recovery_required_product_count=record.recovery_required_product_count,
        run_lock_status=record.run_lock_status,
        run_lock_ref=record.run_lock_ref,
        pause_resume_status=record.pause_resume_status,
        abort_status=record.abort_status,
        rate_limit_status=record.rate_limit_status,
        rate_limit_window_ref=record.rate_limit_window_ref,
        retry_budget_status=record.retry_budget_status,
        retry_backoff_status=record.retry_backoff_status,
        retry_backoff_ref=record.retry_backoff_ref,
        recovery_status=record.recovery_status,
        partial_success_status=record.partial_success_status,
        fanout_execution_status=record.fanout_execution_status,
        run_state_status=record.run_state_status,
        fanout_blockers=record.fanout_blockers,
        product_states=record.product_states,
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


def _allowlist_run_state_list_response(
    *,
    store: FileUsdcPairSnapshotAllowlistRunStateStore,
    limit: int,
) -> UsdcPairSnapshotAllowlistRunStateListResponse:
    run_states = [
        _allowlist_run_state_item_from_record(record)
        for record in store.read_recent(limit=limit)
    ]
    return UsdcPairSnapshotAllowlistRunStateListResponse(
        run_states=run_states,
        returned_count=len(run_states),
        total_count=store.count_records(),
        latest_run_state_id=(
            run_states[0].run_state_id if run_states else None
        ),
        queued_product_count=sum(
            item.queued_product_count for item in run_states
        ),
        blocked_product_count=sum(
            item.blocked_product_count for item in run_states
        ),
        retryable_product_count=sum(
            item.retryable_product_count for item in run_states
        ),
        recovery_required_product_count=sum(
            item.recovery_required_product_count for item in run_states
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
        reference_bid_price_source=record.reference_bid_price_source,
        reference_bid_price_captured_at=record.reference_bid_price_captured_at,
        reference_bid_price_freshness_status=(
            record.reference_bid_price_freshness_status
        ),
        last_filled_price=record.last_filled_price,
        last_filled_price_source=record.last_filled_price_source,
        last_filled_price_captured_at=record.last_filled_price_captured_at,
        last_filled_price_freshness_status=(
            record.last_filled_price_freshness_status
        ),
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
        cap_guard_max_submitted_notional_usdc=(
            record.cap_guard_max_submitted_notional_usdc
        ),
        cap_guard_wallet_check_status=record.cap_guard_wallet_check_status,
        cap_guard_wallet_available_notional_usdc=(
            record.cap_guard_wallet_available_notional_usdc
        ),
        cap_guard_wallet_check_source=record.cap_guard_wallet_check_source,
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


def _allowlist_readiness_http_status(
    response: UsdcPairSnapshotOrderPlanAllowlistReadinessResponse,
) -> int:
    if response.status == AdminApiCommandStatus.CONFLICT:
        return status.HTTP_409_CONFLICT
    return status.HTTP_200_OK


def _allowlist_readiness_response(
    response: UsdcPairSnapshotOrderPlanAllowlistReadinessResponse,
    *,
    replayed: bool = False,
) -> JSONResponse:
    headers = {"X-Correlation-Id": response.correlation_id or ""}
    if replayed:
        headers["X-Idempotency-Replayed"] = "true"
    return JSONResponse(
        status_code=_allowlist_readiness_http_status(response),
        content=response.model_dump(mode="json"),
        headers=headers,
    )


def _allowlist_readiness_base_response(
    *,
    status_value: AdminApiCommandStatus,
    message: str,
    correlation_id: str,
    idempotency_key: str,
    readiness: UsdcPairSnapshotOrderPlanAllowlistReadinessItem | None = None,
    audit_id: str | None = None,
    failure_stage: str | None = None,
) -> UsdcPairSnapshotOrderPlanAllowlistReadinessResponse:
    return UsdcPairSnapshotOrderPlanAllowlistReadinessResponse(
        status=status_value,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        required_permission=AdminApiPermission.CAMPAIGN_EXECUTE,
        service_method=(
            USDC_PAIR_SNAPSHOT_ORDER_PLAN_ALLOWLIST_READINESS_SERVICE_METHOD
        ),
        message=message,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        audit_id=audit_id,
        readiness=readiness,
        failure_stage=failure_stage,
    )


def _allowlist_run_state_http_status(
    response: UsdcPairSnapshotAllowlistRunStateResponse,
) -> int:
    if response.status == AdminApiCommandStatus.CONFLICT:
        return status.HTTP_409_CONFLICT
    return status.HTTP_200_OK


def _allowlist_run_state_response(
    response: UsdcPairSnapshotAllowlistRunStateResponse,
    *,
    replayed: bool = False,
) -> JSONResponse:
    headers = {"X-Correlation-Id": response.correlation_id or ""}
    if replayed:
        headers["X-Idempotency-Replayed"] = "true"
    return JSONResponse(
        status_code=_allowlist_run_state_http_status(response),
        content=response.model_dump(mode="json"),
        headers=headers,
    )


def _allowlist_run_state_base_response(
    *,
    status_value: AdminApiCommandStatus,
    message: str,
    correlation_id: str,
    idempotency_key: str,
    run_state: UsdcPairSnapshotAllowlistRunStateItem | None = None,
    audit_id: str | None = None,
    failure_stage: str | None = None,
) -> UsdcPairSnapshotAllowlistRunStateResponse:
    return UsdcPairSnapshotAllowlistRunStateResponse(
        status=status_value,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        required_permission=AdminApiPermission.CAMPAIGN_EXECUTE,
        service_method=USDC_PAIR_SNAPSHOT_ALLOWLIST_RUN_STATE_SERVICE_METHOD,
        message=message,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        audit_id=audit_id,
        run_state=run_state,
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
    service_method: str = USDC_PAIR_SNAPSHOT_ORDER_PLAN_LIVE_SUBMIT_SERVICE_METHOD,
) -> UsdcPairSnapshotOrderPlanLiveSubmitResponse:
    return UsdcPairSnapshotOrderPlanLiveSubmitResponse(
        status=status_value,
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        required_permission=AdminApiPermission.CAMPAIGN_EXECUTE,
        service_method=service_method,
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


def _record_allowlist_readiness_audit(
    *,
    audit_store: FileAdminApiAuditStore,
    actor: AdminApiActor,
    endpoint: str,
    request_id: str,
    operator_intent: str,
    response: UsdcPairSnapshotOrderPlanAllowlistReadinessResponse,
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


def _record_allowlist_run_state_audit(
    *,
    audit_store: FileAdminApiAuditStore,
    actor: AdminApiActor,
    endpoint: str,
    request_id: str,
    operator_intent: str,
    response: UsdcPairSnapshotAllowlistRunStateResponse,
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


def _execute_idempotent_allowlist_readiness(
    *,
    idempotency_key: str,
    payload_hash: str,
    actor: AdminApiActor,
    request_id: str,
    operator_intent: str,
    idempotency_store: FileIdempotencyStore,
    audit_store: FileAdminApiAuditStore,
    operation: Callable[[str], UsdcPairSnapshotOrderPlanAllowlistReadinessItem],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.CAMPAIGN_EXECUTE)
    check = idempotency_store.evaluate(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
    )
    if check.decision == AdminApiIdempotencyDecision.REPLAY and check.record:
        return _allowlist_readiness_response(
            UsdcPairSnapshotOrderPlanAllowlistReadinessResponse.model_validate(
                check.record.response
            ),
            replayed=True,
        )
    if check.decision == AdminApiIdempotencyDecision.CONFLICT:
        response = _allowlist_readiness_base_response(
            status_value=AdminApiCommandStatus.CONFLICT,
            message="Idempotency-Key was already used with a different payload.",
            correlation_id=request_id,
            idempotency_key=idempotency_key,
            failure_stage="idempotency",
        )
        response.audit_id = _record_allowlist_readiness_audit(
            audit_store=audit_store,
            actor=actor,
            endpoint=USDC_PAIR_SNAPSHOT_ORDER_PLAN_ALLOWLIST_READINESS_ENDPOINT,
            request_id=request_id,
            operator_intent=operator_intent,
            response=response,
        )
        return _allowlist_readiness_response(response)

    try:
        audit_id = str(uuid4())
        readiness = operation(audit_id)
        response = _allowlist_readiness_base_response(
            status_value=AdminApiCommandStatus.ACCEPTED,
            message=(
                "USDC pair snapshot order-plan allowlist-readiness evidence "
                "accepted without Coinbase submission."
            ),
            correlation_id=request_id,
            idempotency_key=idempotency_key,
            audit_id=audit_id,
            readiness=readiness,
        )
    except UsdcPairSnapshotError as exc:
        response = _allowlist_readiness_base_response(
            status_value=AdminApiCommandStatus.REJECTED,
            message=str(exc),
            correlation_id=request_id,
            idempotency_key=idempotency_key,
            failure_stage="usdc_pair_snapshot_order_plan_allowlist_readiness",
        )
    response.audit_id = _record_allowlist_readiness_audit(
        audit_store=audit_store,
        actor=actor,
        endpoint=USDC_PAIR_SNAPSHOT_ORDER_PLAN_ALLOWLIST_READINESS_ENDPOINT,
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
                endpoint=USDC_PAIR_SNAPSHOT_ORDER_PLAN_ALLOWLIST_READINESS_ENDPOINT,
            )
        )
    return _allowlist_readiness_response(response)


def _execute_idempotent_allowlist_run_state(
    *,
    idempotency_key: str,
    payload_hash: str,
    actor: AdminApiActor,
    request_id: str,
    operator_intent: str,
    idempotency_store: FileIdempotencyStore,
    audit_store: FileAdminApiAuditStore,
    operation: Callable[[str], UsdcPairSnapshotAllowlistRunStateItem],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.CAMPAIGN_EXECUTE)
    check = idempotency_store.evaluate(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
    )
    if check.decision == AdminApiIdempotencyDecision.REPLAY and check.record:
        return _allowlist_run_state_response(
            UsdcPairSnapshotAllowlistRunStateResponse.model_validate(
                check.record.response
            ),
            replayed=True,
        )
    if check.decision == AdminApiIdempotencyDecision.CONFLICT:
        response = _allowlist_run_state_base_response(
            status_value=AdminApiCommandStatus.CONFLICT,
            message="Idempotency-Key was already used with a different payload.",
            correlation_id=request_id,
            idempotency_key=idempotency_key,
            failure_stage="idempotency",
        )
        response.audit_id = _record_allowlist_run_state_audit(
            audit_store=audit_store,
            actor=actor,
            endpoint=USDC_PAIR_SNAPSHOT_ALLOWLIST_RUN_STATE_ENDPOINT,
            request_id=request_id,
            operator_intent=operator_intent,
            response=response,
        )
        return _allowlist_run_state_response(response)

    try:
        audit_id = str(uuid4())
        run_state = operation(audit_id)
        response = _allowlist_run_state_base_response(
            status_value=AdminApiCommandStatus.ACCEPTED,
            message=(
                "USDC pair snapshot allowlist run-state evidence accepted "
                "without Coinbase submission."
            ),
            correlation_id=request_id,
            idempotency_key=idempotency_key,
            audit_id=audit_id,
            run_state=run_state,
        )
    except UsdcPairSnapshotError as exc:
        response = _allowlist_run_state_base_response(
            status_value=AdminApiCommandStatus.REJECTED,
            message=str(exc),
            correlation_id=request_id,
            idempotency_key=idempotency_key,
            failure_stage="usdc_pair_snapshot_allowlist_run_state",
        )
    response.audit_id = _record_allowlist_run_state_audit(
        audit_store=audit_store,
        actor=actor,
        endpoint=USDC_PAIR_SNAPSHOT_ALLOWLIST_RUN_STATE_ENDPOINT,
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
                endpoint=USDC_PAIR_SNAPSHOT_ALLOWLIST_RUN_STATE_ENDPOINT,
            )
        )
    return _allowlist_run_state_response(response)


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
    endpoint: str = USDC_PAIR_SNAPSHOT_ORDER_PLAN_LIVE_SUBMIT_ENDPOINT,
    service_method: str = USDC_PAIR_SNAPSHOT_ORDER_PLAN_LIVE_SUBMIT_SERVICE_METHOD,
    failure_stage: str = "usdc_pair_snapshot_order_plan_live_submit",
    accepted_message: str = (
        "USDC pair snapshot order-plan controlled-live submit/cancel "
        "accepted for one order."
    ),
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
            service_method=service_method,
        )
        response.audit_id = _record_live_submit_audit(
            audit_store=audit_store,
            actor=actor,
            endpoint=endpoint,
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
            message=accepted_message,
            correlation_id=request_id,
            idempotency_key=idempotency_key,
            audit_id=audit_id,
            submission=submission,
            service_method=service_method,
        )
    except UsdcPairSnapshotError as exc:
        response = _live_submit_base_response(
            status_value=AdminApiCommandStatus.REJECTED,
            message=str(exc),
            correlation_id=request_id,
            idempotency_key=idempotency_key,
            failure_stage=failure_stage,
            service_method=service_method,
        )
    response.audit_id = _record_live_submit_audit(
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
    "/automation/usdc-pair-snapshot-order-plan-allowlist-readiness",
    response_model=UsdcPairSnapshotOrderPlanAllowlistReadinessListResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="List backend-owned USDC pair snapshot allowlist-readiness evidence",
)
def list_usdc_pair_snapshot_order_plan_allowlist_readiness(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    readiness_store: Annotated[
        FileUsdcPairSnapshotOrderPlanAllowlistReadinessStore,
        Depends(get_usdc_pair_snapshot_order_plan_allowlist_readiness_store),
    ],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> JSONResponse:
    """Read durable M58 no-live allowlist-readiness evidence."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_response(
        _allowlist_readiness_list_response(
            store=readiness_store,
            limit=limit,
        )
    )


@router.get(
    "/automation/usdc-pair-snapshot-allowlist-run-states",
    response_model=UsdcPairSnapshotAllowlistRunStateListResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="List backend-owned USDC pair snapshot allowlist run-state evidence",
)
def list_usdc_pair_snapshot_allowlist_run_states(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    run_state_store: Annotated[
        FileUsdcPairSnapshotAllowlistRunStateStore,
        Depends(get_usdc_pair_snapshot_allowlist_run_state_store),
    ],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> JSONResponse:
    """Read durable M58 no-live allowlist run-state evidence."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_response(
        _allowlist_run_state_list_response(
            store=run_state_store,
            limit=limit,
        )
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


def _non_negative_decimal_value(value: str | None) -> Decimal | None:
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if decimal_value < Decimal("0"):
        return None
    return decimal_value


def _decimal_string(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def _non_empty_text(value: str | None) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_reference_timestamp(value: str | None) -> datetime | None:
    text = _non_empty_text(value)
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _live_reference_freshness_status(value: str | None) -> str:
    captured_at = _parse_reference_timestamp(value)
    if captured_at is None:
        return "missing_timestamp" if not _non_empty_text(value) else "invalid_timestamp"
    age_seconds = (datetime.now(timezone.utc) - captured_at).total_seconds()
    if age_seconds < -USDC_PAIR_LIVE_REFERENCE_FUTURE_TOLERANCE_SECONDS:
        return "future_timestamp"
    if age_seconds > USDC_PAIR_LIVE_REFERENCE_MAX_AGE_SECONDS:
        return "stale"
    return "fresh"


def _enum_text(value: Any) -> str:
    enum_value = getattr(value, "value", value)
    return str(enum_value)


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


def _usdc_pair_live_readiness_cap_guard_evidence(
    *,
    store: FileAdminApiCapGuardStore,
    row: Any,
    submitted_notional: Decimal | None,
) -> tuple[dict[str, str], list[str]]:
    decision_id = str(getattr(row, "cap_guard_decision_id", "") or "")
    evidence = {
        "cap_guard_max_submitted_notional_usdc": "0",
        "cap_guard_wallet_check_status": "missing",
        "cap_guard_wallet_available_notional_usdc": "0",
        "cap_guard_wallet_check_source": "missing",
    }
    if not decision_id:
        return evidence, ["cap_guard_decision_missing"]
    record = store.find_by_decision_id(decision_id)
    if record is None:
        return evidence, ["cap_guard_decision_missing"]

    evidence = {
        "cap_guard_max_submitted_notional_usdc": record.max_submitted_notional_usdc,
        "cap_guard_wallet_check_status": _enum_text(record.wallet_check_status),
        "cap_guard_wallet_available_notional_usdc": (
            record.wallet_available_notional_usdc
        ),
        "cap_guard_wallet_check_source": record.wallet_check_source,
    }
    blockers: list[str] = []
    if not record.allowed or record.status != AdminApiGateStatus.PASSED:
        blockers.append("cap_guard_decision_not_passed")
    cap_notional = _non_negative_decimal_value(record.max_submitted_notional_usdc)
    wallet_available = _non_negative_decimal_value(
        record.wallet_available_notional_usdc
    )
    if submitted_notional is not None:
        if cap_notional is None or cap_notional < submitted_notional:
            blockers.append("cap_guard_submitted_notional_exceeded")
        if (
            record.wallet_check_required
            and record.wallet_check_status != AdminApiGateStatus.PASSED
        ):
            blockers.append("cap_guard_wallet_check_not_passed")
        if record.wallet_check_required and (
            wallet_available is None or wallet_available < submitted_notional
        ):
            blockers.append("cap_guard_wallet_available_notional_exceeded")
    return evidence, blockers


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


def _normalized_allowlist_product_ids(product_ids: list[str]) -> list[str]:
    return list(
        dict.fromkeys(
            product_id.strip().upper()
            for product_id in product_ids
            if product_id.strip()
        )
    )


def _order_plan_rows_by_product(
    plan: UsdcPairSnapshotOrderPlanRecord,
) -> dict[str, Any]:
    return {
        str(row.product_id).upper(): row
        for row in plan.order_plan_rows
        if str(row.product_id).strip()
    }


def _allowlist_product_readiness_row(
    *,
    product_id: str,
    row: Any | None,
    retry_budget_per_product: int,
    run_rate_limit_budget_ref: str | None,
    cancel_recovery_plan_ref: str | None,
) -> UsdcPairSnapshotOrderPlanAllowlistReadinessProductItem:
    if row is None:
        return UsdcPairSnapshotOrderPlanAllowlistReadinessProductItem(
            product_id=product_id,
            readiness_status="blocked",
            retry_status="blocked",
            failure_isolation_status="blocked",
            rate_limit_status="not_applicable",
            retry_budget_status="blocked",
            retry_attempts_available=0,
            cancel_recovery_status="not_required",
            blockers=["order_plan_row_missing"],
        )

    blockers: list[str] = []
    plan_status = str(getattr(row, "plan_status", "") or "")
    proof_chain_status = str(getattr(row, "proof_chain_status", "") or "")
    proof_chain_blockers = list(getattr(row, "proof_chain_blockers", []) or [])
    run_cap_status = str(getattr(row, "run_cap_status", "") or "")
    pending_single_live_submission = (
        proof_chain_status == "blocked"
        and proof_chain_blockers == [USDC_PAIR_SNAPSHOT_LIVE_SUBMISSION_MISSING_BLOCKER]
    )
    if plan_status != "planned":
        blockers.append("order_plan_row_not_planned")
        if run_cap_status == "exceeded":
            blockers.append("run_cap_exhausted")
    elif proof_chain_status != "accepted" and not pending_single_live_submission:
        blockers.append("proof_chain_not_accepted")

    if not blockers:
        if not run_rate_limit_budget_ref:
            blockers.append("run_rate_limit_budget_missing")
        if retry_budget_per_product < 1:
            blockers.append("retry_budget_missing")
        if not cancel_recovery_plan_ref:
            blockers.append("cancel_recovery_plan_missing")

    readiness_status = "blocked" if blockers else "candidate"
    retry_status = "blocked" if blockers else "ready_no_live"
    ready = not blockers
    recovery_state_ref = (
        f"{cancel_recovery_plan_ref}:{product_id}"
        if ready and cancel_recovery_plan_ref
        else str(getattr(row, "reconciliation_plan_id", "") or "") or None
    )
    return UsdcPairSnapshotOrderPlanAllowlistReadinessProductItem(
        product_id=product_id,
        client_order_id=str(getattr(row, "client_order_id", "") or "") or None,
        plan_status=plan_status or None,
        proof_chain_status=proof_chain_status or None,
        run_cap_status=run_cap_status or None,
        cap_guard_decision_id=(
            str(getattr(row, "cap_guard_decision_id", "") or "") or None
        ),
        skip_reason=str(getattr(row, "skip_reason", "") or "") or None,
        planned_notional_usdc=str(
            getattr(row, "planned_notional_usdc", "") or "0"
        ),
        readiness_status=readiness_status,
        retry_status=retry_status,
        failure_isolation_status="ready_no_live" if ready else "blocked",
        rate_limit_status="ready_no_live" if ready else "blocked",
        retry_budget_status="ready_no_live" if ready else "blocked",
        retry_attempts_available=retry_budget_per_product if ready else 0,
        cancel_recovery_status="ready_no_live" if ready else "not_required",
        blockers=blockers,
        recovery_state_ref=recovery_state_ref,
    )


def _record_usdc_pair_allowlist_readiness(
    *,
    plan: UsdcPairSnapshotOrderPlanRecord,
    body: UsdcPairSnapshotOrderPlanAllowlistReadinessRequest,
    readiness_store: FileUsdcPairSnapshotOrderPlanAllowlistReadinessStore,
    actor: AdminApiActor,
    operator_intent: str,
    idempotency_key: str,
    payload_hash: str,
    audit_id: str,
) -> UsdcPairSnapshotOrderPlanAllowlistReadinessItem:
    product_ids = _normalized_allowlist_product_ids(body.product_ids)
    if not product_ids:
        raise UsdcPairSnapshotError(
            "USDC pair snapshot allowlist-readiness requires product_ids."
        )

    rows_by_product = _order_plan_rows_by_product(plan)
    product_rows = [
        _allowlist_product_readiness_row(
            product_id=product_id,
            row=rows_by_product.get(product_id),
            retry_budget_per_product=body.retry_budget_per_product,
            run_rate_limit_budget_ref=body.run_rate_limit_budget_ref,
            cancel_recovery_plan_ref=body.cancel_recovery_plan_ref,
        )
        for product_id in product_ids
    ]
    candidate_product_ids = [
        item.product_id
        for item in product_rows
        if item.plan_status == "planned"
    ]
    blocked_product_ids = [
        item.product_id for item in product_rows if item.blockers
    ]
    cap_exhausted_product_ids = [
        item.product_id
        for item in product_rows
        if "run_cap_exhausted" in item.blockers
    ]
    missing_product_ids = [
        item.product_id
        for item in product_rows
        if "order_plan_row_missing" in item.blockers
    ]
    retryable_product_ids = [
        item.product_id
        for item in product_rows
        if item.retry_status == "ready_no_live"
    ]
    recovery_required_product_ids = [
        item.product_id
        for item in product_rows
        if item.cancel_recovery_status == "ready_no_live"
    ]

    fanout_blockers: list[str] = []
    if len(product_ids) > body.max_products:
        fanout_blockers.append("allowlist_product_count_exceeds_max")
    fanout_blockers.extend([
        "fanout_execution_not_approved",
        "scheduler_blocked",
    ])
    if blocked_product_ids:
        fanout_blockers.append("product_evidence_blocked")
    failure_isolation_status = (
        "ready_no_live"
        if product_ids and not missing_product_ids and len(product_ids) <= body.max_products
        else "blocked"
    )
    run_rate_limit_status = (
        "ready_no_live"
        if body.run_rate_limit_budget_ref
        and len(product_ids) <= body.max_products
        and not blocked_product_ids
        else "blocked"
    )
    retry_budget_status = (
        "ready_no_live"
        if body.retry_budget_per_product > 0 and not blocked_product_ids
        else "blocked"
    )
    recovery_readiness_status = (
        "ready_no_live"
        if body.cancel_recovery_plan_ref and not blocked_product_ids
        else "blocked"
    )
    partial_success_status = (
        "ready_no_live"
        if candidate_product_ids and not blocked_product_ids
        else "blocked"
    )

    record = UsdcPairSnapshotOrderPlanAllowlistReadinessRecord(
        readiness_id=(
            body.readiness_id or f"m58-usdc-allowlist-readiness-{uuid4()}"
        ),
        plan_id=plan.plan_id,
        snapshot_run_id=plan.snapshot_run_id,
        product_ids=product_ids,
        selected_product_count=len(product_ids),
        max_products=body.max_products,
        candidate_product_ids=candidate_product_ids,
        blocked_product_ids=blocked_product_ids,
        cap_exhausted_product_ids=cap_exhausted_product_ids,
        missing_product_ids=missing_product_ids,
        retryable_product_ids=retryable_product_ids,
        recovery_required_product_ids=recovery_required_product_ids,
        partial_success_status=partial_success_status,
        failure_isolation_status=failure_isolation_status,
        run_rate_limit_status=run_rate_limit_status,
        retry_budget_status=retry_budget_status,
        recovery_readiness_status=recovery_readiness_status,
        retry_budget_per_product=body.retry_budget_per_product,
        run_rate_limit_budget_ref=body.run_rate_limit_budget_ref,
        cancel_recovery_plan_ref=body.cancel_recovery_plan_ref,
        fanout_readiness_status="blocked",
        fanout_blockers=fanout_blockers,
        product_readiness_rows=product_rows,
        actor_id=actor.actor_id,
        operator_intent=operator_intent,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        audit_id=audit_id,
        operator_notes=body.operator_notes,
        detail=(
            "M58 Phase F no-live allowlist-readiness evidence summarized "
            "candidate, blocked, cap-exhausted, and missing products for an "
            "existing backend-owned USDC spot order plan. Fan-out execution "
            "and scheduling remain blocked."
        ),
    )
    readiness_store.append(record)
    return _allowlist_readiness_item_from_record(record)


def _matching_allowlist_live_readiness_record(
    *,
    store: FileUsdcPairSnapshotOrderPlanLiveReadinessStore,
    plan_id: str,
    product_id: str,
    client_order_id: str | None,
) -> UsdcPairSnapshotOrderPlanLiveReadinessRecord | None:
    normalized_product_id = product_id.strip().upper()
    normalized_client_order_id = str(client_order_id or "").strip()
    for record in store.read_recent(limit=500):
        if record.plan_id != plan_id:
            continue
        if record.product_id.strip().upper() != normalized_product_id:
            continue
        if record.client_order_id.strip() != normalized_client_order_id:
            continue
        return record
    return None


def _allowlist_live_readiness_evidence(
    *,
    store: FileUsdcPairSnapshotOrderPlanLiveReadinessStore,
    plan_id: str,
    product_id: str,
    client_order_id: str | None,
) -> tuple[str, str | None, str | None, list[str]]:
    record = _matching_allowlist_live_readiness_record(
        store=store,
        plan_id=plan_id,
        product_id=product_id,
        client_order_id=client_order_id,
    )
    if record is None:
        return "missing", None, None, ["live_readiness_missing"]

    blockers: list[str] = []
    freshness_checks = (
        (
            "reference_bid_price",
            record.reference_bid_price_freshness_status,
            _live_reference_freshness_status(record.reference_bid_price_captured_at),
        ),
        (
            "last_filled_price",
            record.last_filled_price_freshness_status,
            _live_reference_freshness_status(record.last_filled_price_captured_at),
        ),
    )
    for field_name, recorded_status, current_status in freshness_checks:
        if recorded_status != "fresh":
            blockers.append(f"live_readiness_{field_name}_{recorded_status}")
        if current_status != "fresh":
            blockers.append(f"live_readiness_{field_name}_{current_status}")
    blockers.extend(_allowlist_live_readiness_non_fill_blockers(record))
    if not record.preflight_passed:
        blockers.extend(record.preflight_blockers or [])
        if not record.preflight_blockers:
            blockers.append("live_readiness_preflight_blocked")
    if not record.submit_route_ready:
        blockers.extend(record.submit_blockers or [])
        if not record.submit_blockers:
            blockers.append("live_readiness_submit_route_blocked")
    if (
        record.live_exchange_submitted
        or record.live_coinbase_orders_ran
        or record.live_coinbase_execution != "not_run"
        or record.notional_usdc != "0"
    ):
        blockers.append("live_readiness_not_no_live")

    source = record.source
    if blockers:
        return "blocked", record.readiness_id, source, _dedupe(blockers)
    return "ready_no_live", record.readiness_id, source, []


def _allowlist_live_readiness_non_fill_blockers(
    record: UsdcPairSnapshotOrderPlanLiveReadinessRecord,
) -> list[str]:
    blockers: list[str] = []
    intended_price = _decimal_value(record.intended_limit_price)
    reference_bid = _decimal_value(record.reference_bid_price)
    last_filled_price = _decimal_value(record.last_filled_price)
    try:
        side = OrderSide(record.side)
    except ValueError:
        blockers.append("live_readiness_side_invalid")
        side = None

    far_from_bid_blocker = "live_readiness_far_from_bid_price_required"
    snapshot_non_fill_blocker = (
        "live_readiness_snapshot_non_fill_price_distance_required"
    )
    if record.far_from_bid_status != "passed":
        blockers.append(far_from_bid_blocker)
    if record.snapshot_non_fill_status != "passed":
        blockers.append(snapshot_non_fill_blocker)

    if intended_price is None or reference_bid is None or last_filled_price is None:
        blockers.append("live_readiness_price_reference_invalid")
        return _dedupe(blockers)
    if side is None:
        return _dedupe(blockers)

    if side == OrderSide.BUY:
        far_from_bid_passed = intended_price <= reference_bid * Decimal("0.50")
        non_fill_passed = intended_price <= last_filled_price * Decimal("0.90")
    else:
        far_from_bid_passed = intended_price >= reference_bid * Decimal("1.50")
        non_fill_passed = intended_price >= last_filled_price * Decimal("1.10")
    if not far_from_bid_passed:
        blockers.append(far_from_bid_blocker)
    if not non_fill_passed:
        blockers.append(snapshot_non_fill_blocker)
    return _dedupe(blockers)


def _allowlist_run_state_product_item(
    row: UsdcPairSnapshotOrderPlanAllowlistReadinessProductItem,
    *,
    plan_id: str,
    live_readiness_store: FileUsdcPairSnapshotOrderPlanLiveReadinessStore,
) -> UsdcPairSnapshotAllowlistRunStateProductItem:
    blockers = list(row.blockers or [])
    live_readiness_status = "not_queued"
    live_readiness_id = None
    live_readiness_source = None
    if row.readiness_status == "candidate" and not blockers:
        (
            live_readiness_status,
            live_readiness_id,
            live_readiness_source,
            live_readiness_blockers,
        ) = _allowlist_live_readiness_evidence(
            store=live_readiness_store,
            plan_id=plan_id,
            product_id=row.product_id,
            client_order_id=row.client_order_id,
        )
        blockers = _dedupe(blockers + live_readiness_blockers)
    queued = row.readiness_status == "candidate" and not blockers
    execution_state = "queued_no_live" if queued else "blocked"
    return UsdcPairSnapshotAllowlistRunStateProductItem(
        product_id=row.product_id,
        client_order_id=row.client_order_id,
        cap_guard_decision_id=row.cap_guard_decision_id,
        readiness_status=row.readiness_status,
        execution_state=execution_state,
        retry_state=row.retry_status if queued else "blocked",
        rate_limit_state=row.rate_limit_status if queued else "blocked",
        retry_backoff_status="not_required",
        recovery_state=row.cancel_recovery_status if queued else "not_required",
        retry_attempts_available=row.retry_attempts_available if queued else 0,
        planned_notional_usdc=row.planned_notional_usdc,
        recovery_state_ref=(
            row.recovery_state_ref
            if queued or row.readiness_status != "candidate"
            else None
        ),
        live_readiness_status=live_readiness_status,
        live_readiness_id=live_readiness_id,
        live_readiness_source=live_readiness_source,
        blockers=blockers,
    )


def _allowlist_run_state_run_lock_conflict_blocker(
    *,
    run_state_store: FileUsdcPairSnapshotAllowlistRunStateStore,
    run_lock_ref: str | None,
    run_state_id: str | None,
) -> str | None:
    if not run_lock_ref:
        return None
    requested_run_state_id = str(run_state_id or "")
    return next(
        (
            USDC_PAIR_SNAPSHOT_RUN_LOCK_CONFLICT_BLOCKER
            for record in run_state_store.read_recent(limit=500)
            if record.run_lock_ref == run_lock_ref
            and record.run_state_id != requested_run_state_id
        ),
        None,
    )


def _allowlist_run_state_rate_limit_window_conflict_blocker(
    *,
    run_state_store: FileUsdcPairSnapshotAllowlistRunStateStore,
    rate_limit_window_ref: str | None,
    run_state_id: str | None,
) -> str | None:
    if not rate_limit_window_ref:
        return None
    requested_run_state_id = str(run_state_id or "")
    return next(
        (
            USDC_PAIR_SNAPSHOT_RATE_LIMIT_WINDOW_CONFLICT_BLOCKER
            for record in run_state_store.read_recent(limit=500)
            if record.rate_limit_window_ref == rate_limit_window_ref
            and record.run_state_id != requested_run_state_id
        ),
        None,
    )


def _apply_allowlist_run_state_runtime_controls(
    *,
    product_states: list[UsdcPairSnapshotAllowlistRunStateProductItem],
    run_lock_ref: str | None,
    run_lock_conflict_blocker: str | None,
    rate_limit_window_ref: str | None,
    rate_limit_window_conflict_blocker: str | None,
    pause_requested: bool,
    abort_requested: bool,
) -> tuple[list[UsdcPairSnapshotAllowlistRunStateProductItem], list[str]]:
    runtime_blocker = None
    if abort_requested:
        runtime_blocker = USDC_PAIR_SNAPSHOT_RUN_ABORTED_BLOCKER
    elif pause_requested:
        runtime_blocker = USDC_PAIR_SNAPSHOT_RUN_PAUSED_BLOCKER
    elif not run_lock_ref:
        runtime_blocker = USDC_PAIR_SNAPSHOT_RUN_LOCK_MISSING_BLOCKER
    elif run_lock_conflict_blocker:
        runtime_blocker = run_lock_conflict_blocker
    elif not rate_limit_window_ref:
        runtime_blocker = USDC_PAIR_SNAPSHOT_RATE_LIMIT_WINDOW_MISSING_BLOCKER
    elif rate_limit_window_conflict_blocker:
        runtime_blocker = rate_limit_window_conflict_blocker
    elif (
        sum(
            1
            for item in product_states
            if item.execution_state == "queued_no_live"
        )
        > USDC_PAIR_SNAPSHOT_DEFAULT_RATE_LIMIT_WINDOW_ORDER_CAP
    ):
        runtime_blocker = USDC_PAIR_SNAPSHOT_RATE_LIMIT_WINDOW_CAPACITY_BLOCKER
    if runtime_blocker is None:
        return product_states, []

    updated: list[UsdcPairSnapshotAllowlistRunStateProductItem] = []
    for item in product_states:
        if item.execution_state != "queued_no_live":
            updated.append(item)
            continue
        updated.append(
            item.model_copy(
                update={
                    "execution_state": "blocked",
                    "retry_state": "blocked",
                    "rate_limit_state": "blocked",
                    "recovery_state": "not_required",
                    "recovery_state_ref": None,
                    "retry_attempts_available": 0,
                    "blockers": _dedupe(list(item.blockers) + [runtime_blocker]),
                }
            )
        )
    return updated, [runtime_blocker]


def _allowlist_run_state_prior_retry_attempt_count(
    *,
    run_state_store: FileUsdcPairSnapshotAllowlistRunStateStore,
    readiness_id: str,
    run_state_id: str | None,
    item: UsdcPairSnapshotAllowlistRunStateProductItem,
) -> int:
    requested_run_state_id = str(run_state_id or "")
    product_id = item.product_id.strip().upper()
    client_order_id = str(item.client_order_id or "").strip()
    return sum(
        1
        for record in run_state_store.read_recent(limit=500)
        if record.readiness_id == readiness_id
        and record.run_state_id != requested_run_state_id
        and any(
            product_state.product_id.strip().upper() == product_id
            and str(product_state.client_order_id or "").strip() == client_order_id
            and product_state.execution_state == "queued_no_live"
            for product_state in record.product_states
        )
    )


def _apply_allowlist_run_state_retry_budget(
    *,
    product_states: list[UsdcPairSnapshotAllowlistRunStateProductItem],
    run_state_store: FileUsdcPairSnapshotAllowlistRunStateStore,
    readiness_id: str,
    run_state_id: str | None,
) -> tuple[list[UsdcPairSnapshotAllowlistRunStateProductItem], list[str]]:
    updated: list[UsdcPairSnapshotAllowlistRunStateProductItem] = []
    blockers: list[str] = []
    for item in product_states:
        if item.execution_state != "queued_no_live":
            updated.append(item)
            continue
        prior_attempts = _allowlist_run_state_prior_retry_attempt_count(
            run_state_store=run_state_store,
            readiness_id=readiness_id,
            run_state_id=run_state_id,
            item=item,
        )
        remaining_attempts = max(item.retry_attempts_available - prior_attempts, 0)
        if prior_attempts < item.retry_attempts_available:
            updated.append(
                item.model_copy(
                    update={"retry_attempts_available": remaining_attempts}
                )
            )
            continue

        blockers.append(USDC_PAIR_SNAPSHOT_RETRY_BUDGET_EXHAUSTED_BLOCKER)
        updated.append(
            item.model_copy(
                update={
                    "execution_state": "blocked",
                    "retry_state": "blocked",
                    "rate_limit_state": "blocked",
                    "recovery_state": "not_required",
                    "recovery_state_ref": None,
                    "retry_attempts_available": 0,
                    "blockers": _dedupe(
                        list(item.blockers)
                        + [USDC_PAIR_SNAPSHOT_RETRY_BUDGET_EXHAUSTED_BLOCKER]
                    ),
                }
            )
        )
    return updated, _dedupe(blockers)


def _allowlist_run_state_retry_backoff_conflict_blocker(
    *,
    run_state_store: FileUsdcPairSnapshotAllowlistRunStateStore,
    retry_backoff_ref: str | None,
    run_state_id: str | None,
) -> str | None:
    if not retry_backoff_ref:
        return None
    requested_run_state_id = str(run_state_id or "")
    return next(
        (
            USDC_PAIR_SNAPSHOT_RETRY_BACKOFF_CONFLICT_BLOCKER
            for record in run_state_store.read_recent(limit=500)
            if record.retry_backoff_ref == retry_backoff_ref
            and record.run_state_id != requested_run_state_id
        ),
        None,
    )


def _apply_allowlist_run_state_retry_backoff(
    *,
    product_states: list[UsdcPairSnapshotAllowlistRunStateProductItem],
    run_state_store: FileUsdcPairSnapshotAllowlistRunStateStore,
    readiness_id: str,
    run_state_id: str | None,
    retry_backoff_ref: str | None,
    retry_backoff_conflict_blocker: str | None,
) -> tuple[list[UsdcPairSnapshotAllowlistRunStateProductItem], list[str]]:
    updated: list[UsdcPairSnapshotAllowlistRunStateProductItem] = []
    blockers: list[str] = []
    for item in product_states:
        if item.execution_state != "queued_no_live":
            updated.append(item)
            continue
        prior_attempts = _allowlist_run_state_prior_retry_attempt_count(
            run_state_store=run_state_store,
            readiness_id=readiness_id,
            run_state_id=run_state_id,
            item=item,
        )
        if prior_attempts == 0:
            updated.append(
                item.model_copy(
                    update={
                        "retry_backoff_status": "not_required",
                        "retry_backoff_ref": None,
                    }
                )
            )
            continue

        blocker = (
            retry_backoff_conflict_blocker
            or (
                USDC_PAIR_SNAPSHOT_RETRY_BACKOFF_MISSING_BLOCKER
                if not retry_backoff_ref
                else None
            )
        )
        if blocker:
            blockers.append(blocker)
            updated.append(
                item.model_copy(
                    update={
                        "execution_state": "blocked",
                        "retry_state": "blocked",
                        "rate_limit_state": "blocked",
                        "retry_backoff_status": "blocked",
                        "retry_backoff_ref": retry_backoff_ref,
                        "recovery_state": "not_required",
                        "recovery_state_ref": None,
                        "retry_attempts_available": 0,
                        "blockers": _dedupe(list(item.blockers) + [blocker]),
                    }
                )
            )
            continue

        updated.append(
            item.model_copy(
                update={
                    "retry_backoff_status": "ready_no_live",
                    "retry_backoff_ref": retry_backoff_ref,
                }
            )
        )
    return updated, _dedupe(blockers)


def _apply_allowlist_run_state_cap_allocation(
    *,
    product_states: list[UsdcPairSnapshotAllowlistRunStateProductItem],
    max_fanout_notional: Decimal,
) -> tuple[list[UsdcPairSnapshotAllowlistRunStateProductItem], dict[str, str]]:
    planned_total = sum(
        (
            _decimal_value(item.planned_notional_usdc) or Decimal("0")
            for item in product_states
            if item.execution_state == "queued_no_live"
        ),
        Decimal("0"),
    )
    allocated_total = Decimal("0")
    updated: list[UsdcPairSnapshotAllowlistRunStateProductItem] = []

    for item in product_states:
        remaining = max_fanout_notional - allocated_total
        if item.execution_state != "queued_no_live":
            updated.append(
                item.model_copy(
                    update={
                        "allocated_notional_usdc": _decimal_string(Decimal("0")),
                        "fanout_cap_allocation_status": "not_queued",
                        "fanout_cap_remaining_after_usdc": _decimal_string(
                            remaining
                        ),
                    }
                )
            )
            continue

        planned_notional = _decimal_value(item.planned_notional_usdc) or Decimal("0")
        projected_total = allocated_total + planned_notional
        if projected_total <= max_fanout_notional:
            allocated_total = projected_total
            updated.append(
                item.model_copy(
                    update={
                        "allocated_notional_usdc": _decimal_string(planned_notional),
                        "fanout_cap_allocation_status": "allocated_no_live",
                        "fanout_cap_remaining_after_usdc": _decimal_string(
                            max_fanout_notional - allocated_total
                        ),
                    }
                )
            )
            continue

        updated.append(
            item.model_copy(
                update={
                    "execution_state": "blocked",
                    "retry_state": "blocked",
                    "rate_limit_state": "blocked",
                    "recovery_state": "not_required",
                    "recovery_state_ref": None,
                    "retry_attempts_available": 0,
                    "allocated_notional_usdc": _decimal_string(Decimal("0")),
                    "fanout_cap_allocation_status": "cap_exceeded_no_live",
                    "fanout_cap_remaining_after_usdc": _decimal_string(remaining),
                    "blockers": _dedupe(
                        list(item.blockers) + ["fanout_notional_cap_exceeded"]
                    ),
                }
            )
        )

    overage = max(planned_total - max_fanout_notional, Decimal("0"))
    return updated, {
        "planned_fanout_notional_usdc": _decimal_string(planned_total),
        "allocated_fanout_notional_usdc": _decimal_string(allocated_total),
        "fanout_cap_remaining_usdc": _decimal_string(
            max_fanout_notional - allocated_total
        ),
        "fanout_cap_overage_usdc": _decimal_string(overage),
        "fanout_cap_allocation_status": (
            "exceeded" if overage > Decimal("0") else "passed"
        ),
    }


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _live_wallet_reservation_evidence(
    *,
    queued_for_no_live: bool,
    item: UsdcPairSnapshotAllowlistRunStateProductItem | None = None,
    run_state_id: str | None = None,
    readiness: UsdcPairSnapshotOrderPlanAllowlistReadinessRecord | None = None,
    reservation_store: FileUsdcPairSnapshotLiveWalletReservationStore | None = None,
    reservation_ids: list[str] | None = None,
) -> dict[str, Any]:
    if not queued_for_no_live:
        return {
            "live_wallet_reservation_status": "not_queued",
            "live_wallet_reservation_id": None,
            "live_wallet_reserved_notional_usdc": "0.00",
            "live_wallet_debit_id": None,
            "live_wallet_debited_notional_usdc": "0.00",
            "live_wallet_release_id": None,
            "live_wallet_released_notional_usdc": "0.00",
            "live_wallet_reservation_blockers": [],
        }
    normalized_reservation_ids = [
        reservation_id.strip()
        for reservation_id in (reservation_ids or [])
        if reservation_id.strip()
    ]
    if (
        item is None
        or readiness is None
        or reservation_store is None
        or not run_state_id
        or not normalized_reservation_ids
    ):
        return {
            "live_wallet_reservation_status": "missing_no_live",
            "live_wallet_reservation_id": None,
            "live_wallet_reserved_notional_usdc": "0.00",
            "live_wallet_debit_id": None,
            "live_wallet_debited_notional_usdc": "0.00",
            "live_wallet_release_id": None,
            "live_wallet_released_notional_usdc": "0.00",
            "live_wallet_reservation_blockers": list(
                USDC_PAIR_SNAPSHOT_LIVE_WALLET_RESERVATION_BLOCKERS
            ),
        }

    planned_notional = _decimal_value(item.planned_notional_usdc)
    mismatch_blockers: list[str] = []
    for reservation_id in normalized_reservation_ids:
        record = reservation_store.find_by_reservation_id(reservation_id)
        if record is None:
            mismatch_blockers.append("live_wallet_reservation_missing")
            continue

        record_blockers = _live_wallet_reservation_record_blockers(
            record=record,
            item=item,
            run_state_id=run_state_id,
            readiness=readiness,
            planned_notional=planned_notional,
        )
        if record_blockers:
            mismatch_blockers.extend(record_blockers)
            continue

        debit_blockers = _live_wallet_debit_evidence_blockers(
            record=record,
            planned_notional=planned_notional,
        )
        release_blockers = _live_wallet_release_evidence_blockers(
            record=record,
            planned_notional=planned_notional,
        )
        reference_conflict_blockers = _live_wallet_historical_reference_blockers(
            record=record,
            reservation_store=reservation_store,
        )
        blockers = debit_blockers + release_blockers + reference_conflict_blockers
        reservation_status = (
            "ready_no_live"
            if not blockers
            else "missing_no_live"
            if USDC_PAIR_SNAPSHOT_LIVE_WALLET_RESERVATION_REF_CONFLICT_BLOCKER
            in blockers
            else "reserved_no_live"
        )
        return {
            "live_wallet_reservation_status": reservation_status,
            "live_wallet_reservation_id": record.reservation_id,
            "live_wallet_reserved_notional_usdc": _decimal_string(
                planned_notional or Decimal("0")
            ),
            "live_wallet_debit_id": record.debit_id,
            "live_wallet_debited_notional_usdc": _decimal_string(
                _non_negative_decimal_value(record.debited_notional_usdc)
                or Decimal("0")
            ),
            "live_wallet_release_id": record.release_id,
            "live_wallet_released_notional_usdc": _decimal_string(
                _non_negative_decimal_value(record.released_notional_usdc)
                or Decimal("0")
            ),
            "live_wallet_reservation_blockers": blockers,
        }

    return {
        "live_wallet_reservation_status": "missing_no_live",
        "live_wallet_reservation_id": None,
        "live_wallet_reserved_notional_usdc": "0.00",
        "live_wallet_debit_id": None,
        "live_wallet_debited_notional_usdc": "0.00",
        "live_wallet_release_id": None,
        "live_wallet_released_notional_usdc": "0.00",
        "live_wallet_reservation_blockers": _dedupe(
            mismatch_blockers
            or list(USDC_PAIR_SNAPSHOT_LIVE_WALLET_RESERVATION_BLOCKERS)
        ),
    }


def _live_wallet_reservation_record_blockers(
    *,
    record: UsdcPairSnapshotLiveWalletReservationRecord,
    item: UsdcPairSnapshotAllowlistRunStateProductItem,
    run_state_id: str,
    readiness: UsdcPairSnapshotOrderPlanAllowlistReadinessRecord,
    planned_notional: Decimal | None,
) -> list[str]:
    blockers: list[str] = []
    if record.run_state_id != run_state_id:
        blockers.append("live_wallet_reservation_run_state_mismatch")
    if record.readiness_id != readiness.readiness_id:
        blockers.append("live_wallet_reservation_readiness_mismatch")
    if record.plan_id != readiness.plan_id:
        blockers.append("live_wallet_reservation_plan_mismatch")
    if record.snapshot_run_id != readiness.snapshot_run_id:
        blockers.append("live_wallet_reservation_snapshot_mismatch")
    if record.product_id.strip().upper() != item.product_id.strip().upper():
        blockers.append("live_wallet_reservation_product_mismatch")
    if record.client_order_id.strip() != str(item.client_order_id or "").strip():
        blockers.append("live_wallet_reservation_client_order_mismatch")
    reserved_notional = _non_negative_decimal_value(record.reserved_notional_usdc)
    if (
        reserved_notional is None
        or planned_notional is None
        or reserved_notional != planned_notional
    ):
        blockers.append("live_wallet_reservation_notional_mismatch")
    if record.reservation_status != "reserved_no_live":
        blockers.append("live_wallet_reservation_not_reserved")
    if (
        record.live_exchange_submitted
        or record.live_coinbase_orders_ran
        or record.live_coinbase_execution != "not_run"
        or record.notional_usdc != "0"
    ):
        blockers.append("live_wallet_reservation_not_no_live")
    return blockers


def _live_wallet_debit_evidence_blockers(
    *,
    record: UsdcPairSnapshotLiveWalletReservationRecord,
    planned_notional: Decimal | None,
) -> list[str]:
    if record.debit_status != "debited_no_live" or not record.debit_id:
        return ["live_wallet_debit_missing"]

    debited_notional = _non_negative_decimal_value(record.debited_notional_usdc)
    if (
        debited_notional is None
        or planned_notional is None
        or debited_notional != planned_notional
    ):
        return ["live_wallet_debit_notional_mismatch"]
    return []


def _live_wallet_release_evidence_blockers(
    *,
    record: UsdcPairSnapshotLiveWalletReservationRecord,
    planned_notional: Decimal | None,
) -> list[str]:
    if (
        record.release_status != "released_no_live"
        or not record.release_id
        or not record.release_reason
    ):
        return ["live_wallet_release_missing"]

    released_notional = _non_negative_decimal_value(record.released_notional_usdc)
    if (
        released_notional is None
        or planned_notional is None
        or released_notional != planned_notional
    ):
        return ["live_wallet_release_notional_mismatch"]
    return []


def _live_wallet_reservation_ref_conflicts(
    *,
    record: UsdcPairSnapshotLiveWalletReservationRecord,
    existing: UsdcPairSnapshotLiveWalletReservationRecord,
) -> bool:
    record_notional = _non_negative_decimal_value(record.reserved_notional_usdc)
    existing_notional = _non_negative_decimal_value(existing.reserved_notional_usdc)
    return (
        existing.run_state_id != record.run_state_id
        or existing.readiness_id != record.readiness_id
        or existing.plan_id != record.plan_id
        or existing.snapshot_run_id != record.snapshot_run_id
        or existing.product_id.strip().upper()
        != record.product_id.strip().upper()
        or existing.client_order_id.strip() != record.client_order_id.strip()
        or existing_notional != record_notional
    )


def _live_wallet_historical_reference_blockers(
    *,
    record: UsdcPairSnapshotLiveWalletReservationRecord,
    reservation_store: FileUsdcPairSnapshotLiveWalletReservationStore,
) -> list[str]:
    blockers: list[str] = []
    for existing in reservation_store.read_recent(limit=500):
        if existing.reservation_id == record.reservation_id:
            if _live_wallet_reservation_ref_conflicts(
                record=record,
                existing=existing,
            ):
                blockers.append(
                    USDC_PAIR_SNAPSHOT_LIVE_WALLET_RESERVATION_REF_CONFLICT_BLOCKER
                )
            continue
        if record.debit_id and existing.debit_id == record.debit_id:
            blockers.append(
                USDC_PAIR_SNAPSHOT_LIVE_WALLET_DEBIT_REF_CONFLICT_BLOCKER
            )
        if record.release_id and existing.release_id == record.release_id:
            blockers.append(
                USDC_PAIR_SNAPSHOT_LIVE_WALLET_RELEASE_REF_CONFLICT_BLOCKER
            )
        if len(set(blockers)) == 2:
            break
    return _dedupe(blockers)


def _live_wallet_reference_conflict_blockers_by_product(
    *,
    product_states: list[UsdcPairSnapshotAllowlistRunStateProductItem],
) -> dict[str, list[str]]:
    debit_counts: dict[str, int] = {}
    release_counts: dict[str, int] = {}
    for item in product_states:
        if item.execution_state != "queued_no_live":
            continue
        if item.live_wallet_debit_id:
            debit_counts[item.live_wallet_debit_id] = (
                debit_counts.get(item.live_wallet_debit_id, 0) + 1
            )
        if item.live_wallet_release_id:
            release_counts[item.live_wallet_release_id] = (
                release_counts.get(item.live_wallet_release_id, 0) + 1
            )

    blockers_by_product: dict[str, list[str]] = {}
    conflict_blocker_values = {
        USDC_PAIR_SNAPSHOT_LIVE_WALLET_RESERVATION_REF_CONFLICT_BLOCKER,
        USDC_PAIR_SNAPSHOT_LIVE_WALLET_DEBIT_REF_CONFLICT_BLOCKER,
        USDC_PAIR_SNAPSHOT_LIVE_WALLET_RELEASE_REF_CONFLICT_BLOCKER,
    }
    for item in product_states:
        if item.execution_state != "queued_no_live":
            continue
        blockers: list[str] = [
            blocker
            for blocker in item.live_wallet_reservation_blockers
            if blocker in conflict_blocker_values
        ]
        if (
            item.live_wallet_debit_id
            and debit_counts.get(item.live_wallet_debit_id, 0) > 1
        ):
            blockers.append(
                USDC_PAIR_SNAPSHOT_LIVE_WALLET_DEBIT_REF_CONFLICT_BLOCKER
            )
        if (
            item.live_wallet_release_id
            and release_counts.get(item.live_wallet_release_id, 0) > 1
        ):
            blockers.append(
                USDC_PAIR_SNAPSHOT_LIVE_WALLET_RELEASE_REF_CONFLICT_BLOCKER
            )
        if blockers:
            blockers_by_product[item.product_id] = blockers
    return blockers_by_product


def _apply_live_wallet_reference_conflict_blockers(
    *,
    product_states: list[UsdcPairSnapshotAllowlistRunStateProductItem],
    wallet_available: Decimal,
) -> tuple[list[UsdcPairSnapshotAllowlistRunStateProductItem], list[str], Decimal]:
    blockers_by_product = _live_wallet_reference_conflict_blockers_by_product(
        product_states=product_states
    )
    if not blockers_by_product:
        allocated_total = sum(
            (
                _decimal_value(item.wallet_allocated_notional_usdc)
                or Decimal("0")
                for item in product_states
                if item.execution_state == "queued_no_live"
            ),
            Decimal("0"),
        )
        return product_states, [], allocated_total

    updated: list[UsdcPairSnapshotAllowlistRunStateProductItem] = []
    allocated_total = Decimal("0")
    for item in product_states:
        conflict_blockers = blockers_by_product.get(item.product_id, [])
        remaining = wallet_available - allocated_total
        if conflict_blockers:
            reservation_status = (
                "missing_no_live"
                if USDC_PAIR_SNAPSHOT_LIVE_WALLET_RESERVATION_REF_CONFLICT_BLOCKER
                in conflict_blockers
                else "reserved_no_live"
            )
            updated.append(
                item.model_copy(
                    update={
                        "execution_state": "blocked",
                        "retry_state": "blocked",
                        "rate_limit_state": "blocked",
                        "recovery_state": "not_required",
                        "recovery_state_ref": None,
                        "retry_attempts_available": 0,
                        "wallet_allocation_status": (
                            "live_wallet_reference_conflict"
                        ),
                        "wallet_allocated_notional_usdc": _decimal_string(
                            Decimal("0")
                        ),
                        "wallet_remaining_after_usdc": _decimal_string(remaining),
                        "live_wallet_reservation_status": reservation_status,
                        "live_wallet_reservation_blockers": _dedupe(
                            list(item.live_wallet_reservation_blockers)
                            + conflict_blockers
                        ),
                        "blockers": _dedupe(
                            list(item.blockers) + conflict_blockers
                        ),
                    }
                )
            )
            continue

        if item.execution_state == "queued_no_live":
            allocated_total += (
                _decimal_value(item.wallet_allocated_notional_usdc)
                or Decimal("0")
            )
        updated.append(
            item.model_copy(
                update={
                    "wallet_remaining_after_usdc": _decimal_string(
                        wallet_available - allocated_total
                    )
                }
            )
        )

    return updated, _dedupe(
        [
            blocker
            for blockers in blockers_by_product.values()
            for blocker in blockers
        ]
    ), allocated_total


def _live_wallet_reservation_aggregate_status(
    *,
    blockers: list[str],
    reserved_ids: list[str],
) -> str:
    if not blockers and reserved_ids:
        return "ready_no_live"
    if any(
        blocker.startswith("live_wallet_reservation_")
        for blocker in blockers
    ):
        return "missing_no_live"
    if blockers and reserved_ids:
        return "reserved_no_live"
    if blockers:
        return "missing_no_live"
    return "not_queued"


def _allowlist_run_state_cap_guard_record_blockers(
    *,
    record: Any,
    item: UsdcPairSnapshotAllowlistRunStateProductItem,
) -> list[str]:
    blockers: list[str] = []
    planned_notional = _decimal_value(item.planned_notional_usdc)
    cap_notional = _non_negative_decimal_value(record.max_submitted_notional_usdc)
    wallet_available = _non_negative_decimal_value(
        record.wallet_available_notional_usdc
    )
    if record.route != USDC_PAIR_SNAPSHOT_ALLOWLIST_RUN_STATE_ROUTE:
        blockers.append("cap_guard_route_mismatch")
    if record.method != "POST":
        blockers.append("cap_guard_method_mismatch")
    if record.module_id != USDC_PAIR_SNAPSHOT_MODULE_ID:
        blockers.append("cap_guard_module_mismatch")
    if (
        record.identity_key != "client_order_id"
        or record.identity_value != (item.client_order_id or "")
    ):
        blockers.append("cap_guard_identity_mismatch")
    if (
        _enum_text(record.action_class)
        != AdminApiActionClass.LOCAL_STATE_MUTATION.value
    ):
        blockers.append("cap_guard_action_class_mismatch")
    if (
        _enum_text(record.required_permission)
        != AdminApiPermission.CAMPAIGN_EXECUTE.value
    ):
        blockers.append("cap_guard_permission_mismatch")
    if record.service_method != USDC_PAIR_SNAPSHOT_ALLOWLIST_RUN_STATE_SERVICE_METHOD:
        blockers.append("cap_guard_service_method_mismatch")
    if str(record.product_scope).upper() != item.product_id.upper():
        blockers.append("cap_guard_product_scope_mismatch")
    if (
        planned_notional is None
        or cap_notional is None
        or cap_notional < planned_notional
    ):
        blockers.append("cap_guard_submitted_notional_exceeded")
    if (
        planned_notional is None
        or wallet_available is None
        or wallet_available < planned_notional
    ):
        blockers.append("cap_guard_wallet_available_notional_exceeded")
    return blockers


def _apply_allowlist_run_state_wallet_allocation(
    *,
    product_states: list[UsdcPairSnapshotAllowlistRunStateProductItem],
    cap_guard_store: FileAdminApiCapGuardStore,
    run_state_id: str | None = None,
    readiness: UsdcPairSnapshotOrderPlanAllowlistReadinessRecord | None = None,
    live_wallet_reservation_store: (
        FileUsdcPairSnapshotLiveWalletReservationStore | None
    ) = None,
    live_wallet_reservation_ids: list[str] | None = None,
) -> tuple[list[UsdcPairSnapshotAllowlistRunStateProductItem], dict[str, Any]]:
    wallet_proofs: dict[str, Any] = {}
    wallet_proof_records: dict[str, Any] = {}
    wallet_proof_blockers: dict[str, list[str]] = {}
    wallet_available_values: list[Decimal] = []
    blockers: list[str] = []

    for item in product_states:
        if item.execution_state != "queued_no_live":
            continue
        decision_id = item.cap_guard_decision_id
        if not decision_id:
            blockers.append("cap_guard_decision_missing")
            continue
        record = cap_guard_store.find_by_decision_id(decision_id)
        if record is None:
            blockers.append("cap_guard_decision_missing")
            continue
        wallet_proof_records[item.product_id] = record
        wallet_available = _non_negative_decimal_value(
            record.wallet_available_notional_usdc
        )
        record_blockers = _allowlist_run_state_cap_guard_record_blockers(
            record=record,
            item=item,
        )
        if not record.allowed or record.status != AdminApiGateStatus.PASSED:
            record_blockers.append("cap_guard_decision_not_passed")
        if not record.wallet_check_required:
            record_blockers.append("cap_guard_wallet_check_not_required")
        if (
            record.wallet_check_required
            and record.wallet_check_status != AdminApiGateStatus.PASSED
        ):
            record_blockers.append("cap_guard_wallet_check_not_passed")
        if wallet_available is None:
            record_blockers.append("cap_guard_wallet_available_notional_invalid")
        if record_blockers:
            wallet_proof_blockers[item.product_id] = record_blockers
            blockers.extend(record_blockers)
            continue
        wallet_proofs[item.product_id] = record
        wallet_available_values.append(wallet_available)

    wallet_available = (
        min(wallet_available_values)
        if wallet_available_values
        else Decimal("0")
    )
    allocated_total = Decimal("0")
    updated: list[UsdcPairSnapshotAllowlistRunStateProductItem] = []

    for item in product_states:
        remaining = wallet_available - allocated_total
        if item.execution_state != "queued_no_live":
            updated.append(
                item.model_copy(
                    update={
                        "wallet_allocation_status": "not_queued",
                        "wallet_available_notional_usdc": _decimal_string(
                            Decimal("0")
                        ),
                        "wallet_allocated_notional_usdc": _decimal_string(
                            Decimal("0")
                        ),
                        "wallet_remaining_after_usdc": _decimal_string(remaining),
                        **_live_wallet_reservation_evidence(
                            queued_for_no_live=False
                        ),
                    }
                )
            )
            continue

        record = wallet_proofs.get(item.product_id)
        proof_blockers = wallet_proof_blockers.get(item.product_id, [])
        if proof_blockers:
            blocked_record = wallet_proof_records.get(item.product_id)
            updated.append(
                item.model_copy(
                    update={
                        "execution_state": "blocked",
                        "retry_state": "blocked",
                        "rate_limit_state": "blocked",
                        "recovery_state": "not_required",
                        "recovery_state_ref": None,
                        "retry_attempts_available": 0,
                        "wallet_allocation_status": "cap_guard_wallet_proof_blocked",
                        "wallet_available_notional_usdc": _decimal_string(
                            wallet_available
                        ),
                        "wallet_allocated_notional_usdc": _decimal_string(
                            Decimal("0")
                        ),
                        "wallet_remaining_after_usdc": _decimal_string(remaining),
                        "wallet_check_source": (
                            blocked_record.wallet_check_source
                            if blocked_record is not None
                            else None
                        ),
                        **_live_wallet_reservation_evidence(
                            queued_for_no_live=False
                        ),
                        "blockers": _dedupe(list(item.blockers) + proof_blockers),
                    }
                )
            )
            continue

        if record is None:
            updated.append(
                item.model_copy(
                    update={
                        "execution_state": "blocked",
                        "retry_state": "blocked",
                        "rate_limit_state": "blocked",
                        "recovery_state": "not_required",
                        "recovery_state_ref": None,
                        "retry_attempts_available": 0,
                        "wallet_allocation_status": "missing_cap_guard_proof",
                        "wallet_available_notional_usdc": _decimal_string(
                            wallet_available
                        ),
                        "wallet_allocated_notional_usdc": _decimal_string(
                            Decimal("0")
                        ),
                        "wallet_remaining_after_usdc": _decimal_string(remaining),
                        **_live_wallet_reservation_evidence(
                            queued_for_no_live=False
                        ),
                        "blockers": _dedupe(
                            list(item.blockers) + ["cap_guard_decision_missing"]
                        ),
                    }
                )
            )
            continue

        planned_notional = _decimal_value(item.planned_notional_usdc) or Decimal("0")
        projected_total = allocated_total + planned_notional
        if projected_total <= wallet_available:
            allocated_total = projected_total
            updated.append(
                item.model_copy(
                    update={
                        "wallet_allocation_status": "allocated_no_live",
                        "wallet_available_notional_usdc": _decimal_string(
                            wallet_available
                        ),
                        "wallet_allocated_notional_usdc": _decimal_string(
                            planned_notional
                        ),
                        "wallet_remaining_after_usdc": _decimal_string(
                            wallet_available - allocated_total
                        ),
                        "wallet_check_source": record.wallet_check_source,
                        **_live_wallet_reservation_evidence(
                            queued_for_no_live=True,
                            item=item,
                            run_state_id=run_state_id,
                            readiness=readiness,
                            reservation_store=live_wallet_reservation_store,
                            reservation_ids=live_wallet_reservation_ids,
                        ),
                    }
                )
            )
            continue

        blockers.append("wallet_available_notional_exceeded")
        updated.append(
            item.model_copy(
                update={
                    "execution_state": "blocked",
                    "retry_state": "blocked",
                    "rate_limit_state": "blocked",
                    "recovery_state": "not_required",
                    "recovery_state_ref": None,
                    "retry_attempts_available": 0,
                    "wallet_allocation_status": "wallet_exceeded_no_live",
                    "wallet_available_notional_usdc": _decimal_string(
                        wallet_available
                    ),
                    "wallet_allocated_notional_usdc": _decimal_string(Decimal("0")),
                    "wallet_remaining_after_usdc": _decimal_string(remaining),
                    "wallet_check_source": record.wallet_check_source,
                    **_live_wallet_reservation_evidence(queued_for_no_live=False),
                    "blockers": _dedupe(
                        list(item.blockers) + ["wallet_available_notional_exceeded"]
                    ),
                }
            )
        )

    updated, live_wallet_reference_blockers, allocated_total = (
        _apply_live_wallet_reference_conflict_blockers(
            product_states=updated,
            wallet_available=wallet_available,
        )
    )
    blockers.extend(live_wallet_reference_blockers)
    wallet_blockers = _dedupe(blockers)
    live_wallet_reservation_blockers = _dedupe(
        [
            blocker
            for item in updated
            for blocker in item.live_wallet_reservation_blockers
        ]
    )
    live_wallet_reservation_ids = _dedupe(
        [
            item.live_wallet_reservation_id
            for item in updated
            if item.live_wallet_reservation_id
        ]
    )
    live_wallet_reserved_notional = sum(
        (
            _decimal_value(item.live_wallet_reserved_notional_usdc)
            or Decimal("0")
        )
        for item in updated
    )
    live_wallet_debit_ids = _dedupe(
        [item.live_wallet_debit_id for item in updated if item.live_wallet_debit_id]
    )
    live_wallet_debited_notional = sum(
        (
            _decimal_value(item.live_wallet_debited_notional_usdc)
            or Decimal("0")
        )
        for item in updated
    )
    live_wallet_release_ids = _dedupe(
        [
            item.live_wallet_release_id
            for item in updated
            if item.live_wallet_release_id
        ]
    )
    live_wallet_released_notional = sum(
        (
            _decimal_value(item.live_wallet_released_notional_usdc)
            or Decimal("0")
        )
        for item in updated
    )
    return updated, {
        "wallet_allocation_status": (
            "passed" if not wallet_blockers else "blocked"
        ),
        "wallet_available_notional_usdc": _decimal_string(wallet_available),
        "wallet_allocated_notional_usdc": _decimal_string(allocated_total),
        "wallet_remaining_usdc": _decimal_string(wallet_available - allocated_total),
        "wallet_allocation_blockers": wallet_blockers,
        "live_wallet_reservation_status": _live_wallet_reservation_aggregate_status(
            blockers=live_wallet_reservation_blockers,
            reserved_ids=live_wallet_reservation_ids,
        ),
        "live_wallet_reservation_ids": live_wallet_reservation_ids,
        "live_wallet_reserved_notional_usdc": _decimal_string(
            live_wallet_reserved_notional
        ),
        "live_wallet_debit_ids": live_wallet_debit_ids,
        "live_wallet_debited_notional_usdc": _decimal_string(
            live_wallet_debited_notional
        ),
        "live_wallet_release_ids": live_wallet_release_ids,
        "live_wallet_released_notional_usdc": _decimal_string(
            live_wallet_released_notional
        ),
        "live_wallet_reservation_blockers": live_wallet_reservation_blockers,
    }


def _allowlist_run_state_status(
    *,
    blocked_product_ids: list[str],
    fanout_notional_status: str,
    live_wallet_reservation_status: str,
    pause_requested: bool,
    abort_requested: bool,
) -> str:
    if abort_requested:
        return "aborted_no_live"
    if pause_requested:
        return "paused_no_live"
    if fanout_notional_status == "exceeded":
        return "blocked"
    if blocked_product_ids:
        return "blocked"
    if live_wallet_reservation_status not in {"not_queued", "ready_no_live"}:
        return "blocked"
    return "ready_no_live"


def _allowlist_run_state_runtime_statuses(
    *,
    readiness: UsdcPairSnapshotOrderPlanAllowlistReadinessRecord,
    product_states: list[UsdcPairSnapshotAllowlistRunStateProductItem],
) -> dict[str, str]:
    queued = any(item.execution_state == "queued_no_live" for item in product_states)
    blocked = any(item.execution_state == "blocked" for item in product_states)
    retryable = any(item.retry_state == "ready_no_live" for item in product_states)
    retry_backoff_ready = any(
        item.retry_backoff_status == "ready_no_live" for item in product_states
    )
    retry_backoff_blocked = any(
        item.retry_backoff_status == "blocked" for item in product_states
    )
    recovery_required = any(
        item.recovery_state == "ready_no_live" for item in product_states
    )
    if not queued:
        return {
            "rate_limit_status": "blocked",
            "retry_budget_status": "blocked",
            "retry_backoff_status": "blocked",
            "recovery_status": "blocked",
            "partial_success_status": "blocked",
        }
    return {
        "rate_limit_status": readiness.run_rate_limit_status,
        "retry_budget_status": (
            readiness.retry_budget_status if retryable else "blocked"
        ),
        "retry_backoff_status": (
            "blocked"
            if retry_backoff_blocked
            else "ready_no_live"
            if retry_backoff_ready
            else "not_required"
        ),
        "recovery_status": (
            readiness.recovery_readiness_status if recovery_required else "blocked"
        ),
        "partial_success_status": (
            "partial_ready_no_live" if blocked else "ready_no_live"
        ),
    }


def _record_usdc_pair_allowlist_run_state(
    *,
    readiness: UsdcPairSnapshotOrderPlanAllowlistReadinessRecord,
    body: UsdcPairSnapshotAllowlistRunStateRequest,
    run_state_store: FileUsdcPairSnapshotAllowlistRunStateStore,
    cap_guard_store: FileAdminApiCapGuardStore,
    live_readiness_store: FileUsdcPairSnapshotOrderPlanLiveReadinessStore,
    live_wallet_reservation_store: FileUsdcPairSnapshotLiveWalletReservationStore,
    actor: AdminApiActor,
    operator_intent: str,
    idempotency_key: str,
    payload_hash: str,
    audit_id: str,
) -> UsdcPairSnapshotAllowlistRunStateItem:
    if body.execution_mode != "no_live_rehearsal":
        raise UsdcPairSnapshotError(
            "USDC pair snapshot allowlist run-state only supports no_live_rehearsal."
        )
    max_fanout_notional = _decimal_value(body.max_fanout_notional_usdc)
    if max_fanout_notional is None:
        raise UsdcPairSnapshotError(
            "USDC pair snapshot allowlist run-state requires positive max_fanout_notional_usdc."
        )
    if max_fanout_notional > Decimal("100"):
        raise UsdcPairSnapshotError(
            "USDC pair snapshot allowlist run-state max_fanout_notional_usdc cannot exceed 100."
        )

    product_states = [
        _allowlist_run_state_product_item(
            row,
            plan_id=readiness.plan_id,
            live_readiness_store=live_readiness_store,
        )
        for row in readiness.product_readiness_rows
    ]
    run_lock_conflict_blocker = _allowlist_run_state_run_lock_conflict_blocker(
        run_state_store=run_state_store,
        run_lock_ref=body.run_lock_ref,
        run_state_id=body.run_state_id,
    )
    rate_limit_window_conflict_blocker = (
        _allowlist_run_state_rate_limit_window_conflict_blocker(
            run_state_store=run_state_store,
            rate_limit_window_ref=body.rate_limit_window_ref,
            run_state_id=body.run_state_id,
        )
    )
    retry_backoff_conflict_blocker = (
        _allowlist_run_state_retry_backoff_conflict_blocker(
            run_state_store=run_state_store,
            retry_backoff_ref=body.retry_backoff_ref,
            run_state_id=body.run_state_id,
        )
    )
    product_states, runtime_control_blockers = (
        _apply_allowlist_run_state_runtime_controls(
            product_states=product_states,
            run_lock_ref=body.run_lock_ref,
            run_lock_conflict_blocker=run_lock_conflict_blocker,
            rate_limit_window_ref=body.rate_limit_window_ref,
            rate_limit_window_conflict_blocker=rate_limit_window_conflict_blocker,
            pause_requested=body.pause_requested,
            abort_requested=body.abort_requested,
        )
    )
    product_states, retry_budget_blockers = _apply_allowlist_run_state_retry_budget(
        product_states=product_states,
        run_state_store=run_state_store,
        readiness_id=readiness.readiness_id,
        run_state_id=body.run_state_id,
    )
    product_states, retry_backoff_blockers = (
        _apply_allowlist_run_state_retry_backoff(
            product_states=product_states,
            run_state_store=run_state_store,
            readiness_id=readiness.readiness_id,
            run_state_id=body.run_state_id,
            retry_backoff_ref=body.retry_backoff_ref,
            retry_backoff_conflict_blocker=retry_backoff_conflict_blocker,
        )
    )
    product_states, cap_allocation = (
        _apply_allowlist_run_state_cap_allocation(
            product_states=product_states,
            max_fanout_notional=max_fanout_notional,
        )
    )
    product_states, wallet_allocation = (
        _apply_allowlist_run_state_wallet_allocation(
            product_states=product_states,
            cap_guard_store=cap_guard_store,
            run_state_id=body.run_state_id,
            readiness=readiness,
            live_wallet_reservation_store=live_wallet_reservation_store,
            live_wallet_reservation_ids=body.live_wallet_reservation_ids,
        )
    )
    queued_product_ids = [
        item.product_id
        for item in product_states
        if item.execution_state == "queued_no_live"
    ]
    planned_fanout_notional = _decimal_value(
        cap_allocation["planned_fanout_notional_usdc"]
    ) or Decimal("0")
    fanout_notional_status = (
        cap_allocation["fanout_cap_allocation_status"]
    )
    blocked_product_ids = [
        item.product_id
        for item in product_states
        if item.execution_state == "blocked"
    ]
    retryable_product_ids = [
        item.product_id
        for item in product_states
        if item.retry_state == "ready_no_live"
    ]
    recovery_required_product_ids = [
        item.product_id
        for item in product_states
        if item.recovery_state == "ready_no_live"
    ]
    live_ready_product_ids = [
        item.product_id
        for item in product_states
        if item.live_readiness_status == "ready_no_live"
    ]
    live_readiness_missing_product_ids = [
        item.product_id
        for item in product_states
        if item.live_readiness_status == "missing"
    ]
    live_readiness_blocked_product_ids = [
        item.product_id
        for item in product_states
        if item.live_readiness_status in {"missing", "blocked"}
    ]
    live_readiness_blockers = _dedupe(
        [
            blocker
            for item in product_states
            for blocker in item.blockers
            if blocker.startswith("live_readiness_")
        ]
    )
    if live_readiness_blocked_product_ids:
        live_readiness_status = "blocked"
    elif live_ready_product_ids:
        live_readiness_status = "ready_no_live"
    else:
        live_readiness_status = "not_required"
    fanout_blockers = _dedupe(
        list(readiness.fanout_blockers)
        + runtime_control_blockers
        + retry_budget_blockers
        + retry_backoff_blockers
        + wallet_allocation["live_wallet_reservation_blockers"]
        + (
            ["product_evidence_blocked"]
            if any(
                item.execution_state == "blocked"
                and "fanout_notional_cap_exceeded" not in item.blockers
                for item in product_states
            )
            else []
        )
        + (
            ["fanout_notional_cap_exceeded"]
            if fanout_notional_status == "exceeded"
            else []
        )
    )
    run_state_status = _allowlist_run_state_status(
        blocked_product_ids=blocked_product_ids,
        fanout_notional_status=fanout_notional_status,
        live_wallet_reservation_status=wallet_allocation[
            "live_wallet_reservation_status"
        ],
        pause_requested=body.pause_requested,
        abort_requested=body.abort_requested,
    )
    runtime_statuses = _allowlist_run_state_runtime_statuses(
        readiness=readiness,
        product_states=product_states,
    )
    record = UsdcPairSnapshotAllowlistRunStateRecord(
        run_state_id=body.run_state_id
        or f"m58-usdc-allowlist-run-state-{uuid4()}",
        readiness_id=readiness.readiness_id,
        plan_id=readiness.plan_id,
        snapshot_run_id=readiness.snapshot_run_id,
        execution_mode=body.execution_mode,
        max_fanout_notional_usdc=str(body.max_fanout_notional_usdc),
        planned_fanout_notional_usdc=_decimal_string(planned_fanout_notional),
        allocated_fanout_notional_usdc=(
            cap_allocation["allocated_fanout_notional_usdc"]
        ),
        fanout_cap_remaining_usdc=cap_allocation["fanout_cap_remaining_usdc"],
        fanout_cap_overage_usdc=cap_allocation["fanout_cap_overage_usdc"],
        fanout_cap_allocation_status=(
            cap_allocation["fanout_cap_allocation_status"]
        ),
        wallet_allocation_status=wallet_allocation["wallet_allocation_status"],
        wallet_available_notional_usdc=(
            wallet_allocation["wallet_available_notional_usdc"]
        ),
        wallet_allocated_notional_usdc=(
            wallet_allocation["wallet_allocated_notional_usdc"]
        ),
        wallet_remaining_usdc=wallet_allocation["wallet_remaining_usdc"],
        wallet_allocation_blockers=wallet_allocation["wallet_allocation_blockers"],
        live_wallet_reservation_status=(
            wallet_allocation["live_wallet_reservation_status"]
        ),
        live_wallet_reservation_ids=(
            wallet_allocation["live_wallet_reservation_ids"]
        ),
        live_wallet_reserved_notional_usdc=(
            wallet_allocation["live_wallet_reserved_notional_usdc"]
        ),
        live_wallet_debit_ids=wallet_allocation["live_wallet_debit_ids"],
        live_wallet_debited_notional_usdc=(
            wallet_allocation["live_wallet_debited_notional_usdc"]
        ),
        live_wallet_release_ids=wallet_allocation["live_wallet_release_ids"],
        live_wallet_released_notional_usdc=(
            wallet_allocation["live_wallet_released_notional_usdc"]
        ),
        live_wallet_reservation_blockers=(
            wallet_allocation["live_wallet_reservation_blockers"]
        ),
        live_readiness_status=live_readiness_status,
        live_ready_product_ids=live_ready_product_ids,
        live_readiness_missing_product_ids=live_readiness_missing_product_ids,
        live_readiness_blocked_product_ids=live_readiness_blocked_product_ids,
        live_readiness_blockers=live_readiness_blockers,
        fanout_notional_status=fanout_notional_status,
        product_ids=readiness.product_ids,
        queued_product_ids=queued_product_ids,
        blocked_product_ids=blocked_product_ids,
        retryable_product_ids=retryable_product_ids,
        recovery_required_product_ids=recovery_required_product_ids,
        queued_product_count=len(queued_product_ids),
        blocked_product_count=len(blocked_product_ids),
        retryable_product_count=len(retryable_product_ids),
        recovery_required_product_count=len(recovery_required_product_ids),
        run_lock_status=(
            "missing_run_lock_ref"
            if not body.run_lock_ref
            else "conflict_no_live"
            if run_lock_conflict_blocker
            else "recorded_no_live"
        ),
        run_lock_ref=body.run_lock_ref,
        pause_resume_status=(
            "paused_no_live" if body.pause_requested else "running_no_live"
        ),
        abort_status="aborted_no_live" if body.abort_requested else "not_requested",
        rate_limit_status=runtime_statuses["rate_limit_status"],
        rate_limit_window_ref=body.rate_limit_window_ref,
        retry_budget_status=runtime_statuses["retry_budget_status"],
        retry_backoff_status=runtime_statuses["retry_backoff_status"],
        retry_backoff_ref=body.retry_backoff_ref,
        recovery_status=runtime_statuses["recovery_status"],
        partial_success_status=runtime_statuses["partial_success_status"],
        fanout_execution_status="blocked",
        run_state_status=run_state_status,
        fanout_blockers=fanout_blockers,
        product_states=product_states,
        actor_id=actor.actor_id,
        operator_intent=operator_intent,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        audit_id=audit_id,
        operator_notes=body.operator_notes,
        detail=(
            "M58 Phase F no-live allowlist run-state rehearsal recorded "
            "queued, blocked, retryable, and recovery-required products from "
            "existing backend allowlist-readiness evidence. Fan-out execution "
            "and scheduling remain blocked."
        ),
    )
    run_state_store.append(record)
    return _allowlist_run_state_item_from_record(record)


def _record_usdc_pair_live_readiness_preflight(
    *,
    plan: UsdcPairSnapshotOrderPlanRecord,
    row: Any,
    body: UsdcPairSnapshotOrderPlanLiveReadinessRequest,
    readiness_store: FileUsdcPairSnapshotOrderPlanLiveReadinessStore,
    cap_guard_store: FileAdminApiCapGuardStore,
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
    reference_bid_freshness_status = _live_reference_freshness_status(
        body.reference_bid_price_captured_at
    )
    last_filled_freshness_status = _live_reference_freshness_status(
        body.last_filled_price_captured_at
    )
    submitted_notional = _decimal_value(body.submitted_notional_usdc)
    cap_guard_evidence, cap_guard_blockers = (
        _usdc_pair_live_readiness_cap_guard_evidence(
            store=cap_guard_store,
            row=row,
            submitted_notional=submitted_notional,
        )
    )
    blockers.extend(cap_guard_blockers)
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
    if not _non_empty_text(body.reference_bid_price_source):
        blockers.append("reference_bid_price_source_missing")
    if reference_bid_freshness_status != "fresh":
        blockers.append(f"reference_bid_price_{reference_bid_freshness_status}")
    if last_filled_price is None:
        blockers.append("last_filled_price_invalid")
    if not _non_empty_text(body.last_filled_price_source):
        blockers.append("last_filled_price_source_missing")
    if last_filled_freshness_status != "fresh":
        blockers.append(f"last_filled_price_{last_filled_freshness_status}")
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
        reference_bid_price_source=body.reference_bid_price_source,
        reference_bid_price_captured_at=body.reference_bid_price_captured_at,
        reference_bid_price_freshness_status=reference_bid_freshness_status,
        last_filled_price=body.last_filled_price,
        last_filled_price_source=body.last_filled_price_source,
        last_filled_price_captured_at=body.last_filled_price_captured_at,
        last_filled_price_freshness_status=last_filled_freshness_status,
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
        **cap_guard_evidence,
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


def _find_usdc_pair_allowlist_run_state_product(
    run_state: UsdcPairSnapshotAllowlistRunStateRecord,
    *,
    product_id: str,
    client_order_id: str,
) -> UsdcPairSnapshotAllowlistRunStateProductItem | None:
    normalized_product_id = product_id.strip().upper()
    normalized_client_order_id = client_order_id.strip()
    return next(
        (
            row
            for row in run_state.product_states
            if row.product_id.strip().upper() == normalized_product_id
            and str(row.client_order_id or "").strip() == normalized_client_order_id
        ),
        None,
    )


def _validate_usdc_pair_allowlist_run_state_live_submit(
    *,
    run_state: UsdcPairSnapshotAllowlistRunStateRecord,
    body: UsdcPairSnapshotOrderPlanLiveSubmitRequest,
) -> UsdcPairSnapshotAllowlistRunStateProductItem:
    blockers: list[str] = []
    product_row = _find_usdc_pair_allowlist_run_state_product(
        run_state,
        product_id=body.product_id,
        client_order_id=body.client_order_id,
    )
    if product_row is None:
        blockers.append("run_state_product_not_found")
    else:
        normalized_body_product_id = body.product_id.strip().upper()
        queued_product_ids = {
            product_id.strip().upper()
            for product_id in run_state.queued_product_ids
        }
        retryable_product_ids = {
            product_id.strip().upper()
            for product_id in run_state.retryable_product_ids
        }
        recovery_required_product_ids = {
            product_id.strip().upper()
            for product_id in run_state.recovery_required_product_ids
        }
        if (
            product_row.execution_state != "queued_no_live"
            or normalized_body_product_id not in queued_product_ids
        ):
            blockers.append("run_state_product_not_queued")
        if product_row.readiness_status != "candidate":
            blockers.append("run_state_product_readiness_not_candidate")
        if not product_row.cap_guard_decision_id:
            blockers.append("run_state_product_cap_guard_ref_missing")
        if normalized_body_product_id not in retryable_product_ids:
            blockers.append("run_state_product_not_retryable")
        if normalized_body_product_id not in recovery_required_product_ids:
            blockers.append("run_state_product_recovery_not_required")
        if product_row.live_readiness_status != "ready_no_live":
            blockers.append("run_state_live_readiness_not_ready")
        if product_row.live_readiness_id != body.readiness_id:
            blockers.append("run_state_live_readiness_id_mismatch")
        if product_row.retry_state != "ready_no_live":
            blockers.append("run_state_product_retry_not_ready")
        if product_row.rate_limit_state != "ready_no_live":
            blockers.append("run_state_product_rate_limit_not_ready")
        if product_row.retry_backoff_status not in {"not_required", "ready_no_live"}:
            blockers.append("run_state_product_retry_backoff_not_ready")
        if product_row.recovery_state != "ready_no_live":
            blockers.append("run_state_product_recovery_not_ready")
        if product_row.retry_attempts_available < 1:
            blockers.append("run_state_product_retry_attempts_missing")
        if product_row.fanout_cap_allocation_status != "allocated_no_live":
            blockers.append("run_state_product_fanout_cap_not_allocated")
        if product_row.wallet_allocation_status != "allocated_no_live":
            blockers.append("run_state_product_wallet_allocation_not_allocated")
        if product_row.allocated_notional_usdc != product_row.planned_notional_usdc:
            blockers.append("run_state_product_allocation_notional_mismatch")
        if (
            product_row.wallet_allocated_notional_usdc
            != product_row.planned_notional_usdc
        ):
            blockers.append("run_state_product_wallet_notional_mismatch")
        if product_row.blockers:
            blockers.append("run_state_product_blockers_present")
        if product_row.live_wallet_reservation_status != "ready_no_live":
            blockers.append("run_state_product_live_wallet_reservation_not_ready")
        if not product_row.live_wallet_reservation_id:
            blockers.append("run_state_product_live_wallet_reservation_id_missing")
        if not product_row.live_wallet_debit_id:
            blockers.append("run_state_product_live_wallet_debit_id_missing")
        if not product_row.live_wallet_release_id:
            blockers.append("run_state_product_live_wallet_release_id_missing")
        if product_row.live_wallet_reservation_blockers:
            blockers.append("run_state_product_live_wallet_blockers_present")
        if str(product_row.client_order_id or "").strip() != body.client_order_id:
            blockers.append("run_state_client_order_id_mismatch")
        if product_row.live_coinbase_execution != "not_run":
            blockers.append("run_state_product_not_no_live")
        if product_row.notional_usdc != "0":
            blockers.append("run_state_product_notional_not_zero")
    if run_state.live_coinbase_execution != "not_run":
        blockers.append("run_state_not_no_live")
    if run_state.live_exchange_submitted or run_state.live_coinbase_orders_ran:
        blockers.append("run_state_live_exchange_already_submitted")
    if run_state.notional_usdc != "0":
        blockers.append("run_state_notional_not_zero")
    if run_state.run_state_status != "ready_no_live":
        blockers.append("run_state_not_ready")
    if run_state.fanout_cap_allocation_status != "passed":
        blockers.append("run_state_fanout_cap_not_passed")
    if run_state.wallet_allocation_status != "passed":
        blockers.append("run_state_wallet_allocation_not_passed")
    if run_state.live_readiness_status != "ready_no_live":
        blockers.append("run_state_parent_live_readiness_not_ready")
    if run_state.fanout_notional_status != "passed":
        blockers.append("run_state_fanout_notional_not_passed")
    if run_state.partial_success_status != "ready_no_live":
        blockers.append("run_state_partial_success_not_ready")
    unexpected_fanout_blockers = [
        blocker
        for blocker in run_state.fanout_blockers
        if blocker
        not in USDC_PAIR_SNAPSHOT_RUN_STATE_LIVE_SUBMIT_ALLOWED_FANOUT_BLOCKERS
    ]
    if unexpected_fanout_blockers:
        blockers.append("run_state_parent_fanout_blockers_present")
    if run_state.run_lock_status != "recorded_no_live":
        blockers.append("run_state_run_lock_not_recorded")
    if not run_state.run_lock_ref:
        blockers.append("run_state_run_lock_ref_missing")
    if run_state.pause_resume_status != "running_no_live":
        blockers.append("run_state_not_running")
    if run_state.abort_status != "not_requested":
        blockers.append("run_state_abort_requested")
    if run_state.rate_limit_status != "ready_no_live":
        blockers.append("run_state_rate_limit_not_ready")
    if not run_state.rate_limit_window_ref:
        blockers.append("run_state_rate_limit_window_ref_missing")
    if run_state.retry_budget_status != "ready_no_live":
        blockers.append("run_state_retry_budget_not_ready")
    if run_state.retry_backoff_status not in {"not_required", "ready_no_live"}:
        blockers.append("run_state_retry_backoff_not_ready")
    if run_state.recovery_status != "ready_no_live":
        blockers.append("run_state_recovery_not_ready")
    if run_state.live_wallet_reservation_status != "ready_no_live":
        blockers.append("run_state_live_wallet_reservation_not_ready")
    if not run_state.live_wallet_reservation_ids:
        blockers.append("run_state_live_wallet_reservation_ids_missing")
    if not run_state.live_wallet_debit_ids:
        blockers.append("run_state_live_wallet_debit_ids_missing")
    if not run_state.live_wallet_release_ids:
        blockers.append("run_state_live_wallet_release_ids_missing")
    if run_state.live_wallet_reservation_blockers:
        blockers.append("run_state_live_wallet_blockers_present")

    if blockers:
        raise UsdcPairSnapshotError(
            "USDC pair snapshot allowlist run-state live submit blocked: "
            + ",".join(_dedupe(blockers))
        )
    if product_row is None:
        raise UsdcPairSnapshotError(
            "USDC pair snapshot allowlist run-state live submit blocked: "
            "run_state_product_not_found"
        )
    return product_row


def _validate_usdc_pair_allowlist_run_state_live_submit_association(
    *,
    run_state: UsdcPairSnapshotAllowlistRunStateRecord,
    plan: UsdcPairSnapshotOrderPlanRecord,
    readiness: UsdcPairSnapshotOrderPlanLiveReadinessRecord,
) -> None:
    blockers: list[str] = []
    if run_state.plan_id != plan.plan_id:
        blockers.append("run_state_plan_id_mismatch")
    if run_state.snapshot_run_id != plan.snapshot_run_id:
        blockers.append("run_state_plan_snapshot_mismatch")
    if run_state.plan_id != readiness.plan_id:
        blockers.append("run_state_readiness_plan_mismatch")
    if run_state.snapshot_run_id != readiness.snapshot_run_id:
        blockers.append("run_state_readiness_snapshot_mismatch")

    if blockers:
        raise UsdcPairSnapshotError(
            "USDC pair snapshot allowlist run-state live submit blocked: "
            + ",".join(_dedupe(blockers))
        )


def _validate_usdc_pair_allowlist_run_state_live_submit_wallet_evidence(
    *,
    run_state: UsdcPairSnapshotAllowlistRunStateRecord,
    product_row: UsdcPairSnapshotAllowlistRunStateProductItem,
    reservation_store: FileUsdcPairSnapshotLiveWalletReservationStore,
) -> None:
    blockers: list[str] = []
    reservation_id = str(product_row.live_wallet_reservation_id or "").strip()
    if not reservation_id:
        blockers.append("run_state_live_wallet_reservation_id_missing")
    elif reservation_id not in run_state.live_wallet_reservation_ids:
        blockers.append("run_state_live_wallet_reservation_parent_id_missing")

    record = (
        reservation_store.find_by_reservation_id(reservation_id)
        if reservation_id
        else None
    )
    if record is None:
        blockers.append("run_state_live_wallet_reservation_record_missing")
    else:
        planned_notional = _decimal_value(product_row.planned_notional_usdc)
        reserved_notional = _non_negative_decimal_value(
            record.reserved_notional_usdc
        )
        debited_notional = _non_negative_decimal_value(
            record.debited_notional_usdc
        )
        released_notional = _non_negative_decimal_value(
            record.released_notional_usdc
        )
        if record.run_state_id != run_state.run_state_id:
            blockers.append("run_state_live_wallet_reservation_run_state_mismatch")
        if record.readiness_id != run_state.readiness_id:
            blockers.append("run_state_live_wallet_reservation_readiness_mismatch")
        if record.plan_id != run_state.plan_id:
            blockers.append("run_state_live_wallet_reservation_plan_mismatch")
        if record.snapshot_run_id != run_state.snapshot_run_id:
            blockers.append("run_state_live_wallet_reservation_snapshot_mismatch")
        if (
            record.product_id.strip().upper()
            != product_row.product_id.strip().upper()
        ):
            blockers.append("run_state_live_wallet_reservation_product_mismatch")
        if record.client_order_id.strip() != str(
            product_row.client_order_id or ""
        ).strip():
            blockers.append("run_state_live_wallet_reservation_client_order_mismatch")
        if (
            reserved_notional is None
            or planned_notional is None
            or reserved_notional != planned_notional
        ):
            blockers.append("run_state_live_wallet_reservation_notional_mismatch")
        if record.reservation_status != "reserved_no_live":
            blockers.append("run_state_live_wallet_reservation_not_reserved")
        if (
            record.live_exchange_submitted
            or record.live_coinbase_orders_ran
            or record.live_coinbase_execution != "not_run"
            or record.notional_usdc != "0"
        ):
            blockers.append("run_state_live_wallet_reservation_not_no_live")
        if record.debit_status != "debited_no_live":
            blockers.append("run_state_live_wallet_debit_not_debited")
        if not record.debit_id:
            blockers.append("run_state_live_wallet_debit_id_missing")
        elif record.debit_id != product_row.live_wallet_debit_id:
            blockers.append("run_state_live_wallet_debit_id_mismatch")
        if (
            record.debit_id
            and record.debit_id not in run_state.live_wallet_debit_ids
        ):
            blockers.append("run_state_live_wallet_debit_parent_id_missing")
        if (
            debited_notional is None
            or planned_notional is None
            or debited_notional != planned_notional
        ):
            blockers.append("run_state_live_wallet_debit_notional_mismatch")
        if record.release_status != "released_no_live":
            blockers.append("run_state_live_wallet_release_not_released")
        if not record.release_id:
            blockers.append("run_state_live_wallet_release_id_missing")
        elif record.release_id != product_row.live_wallet_release_id:
            blockers.append("run_state_live_wallet_release_id_mismatch")
        if (
            record.release_id
            and record.release_id not in run_state.live_wallet_release_ids
        ):
            blockers.append("run_state_live_wallet_release_parent_id_missing")
        if not record.release_reason:
            blockers.append("run_state_live_wallet_release_reason_missing")
        if (
            released_notional is None
            or planned_notional is None
            or released_notional != planned_notional
        ):
            blockers.append("run_state_live_wallet_release_notional_mismatch")
        blockers.extend(
            f"run_state_{blocker}"
            for blocker in _live_wallet_historical_reference_blockers(
                record=record,
                reservation_store=reservation_store,
            )
        )

    if blockers:
        raise UsdcPairSnapshotError(
            "USDC pair snapshot allowlist run-state live submit blocked: "
            + ",".join(_dedupe(blockers))
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
    cap_guard_store: FileAdminApiCapGuardStore,
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
    if readiness.reference_bid_price_freshness_status != "fresh":
        blockers.append("readiness_reference_bid_price_not_fresh")
    if readiness.last_filled_price_freshness_status != "fresh":
        blockers.append("readiness_last_filled_price_not_fresh")
    reference_bid_current_freshness = _live_reference_freshness_status(
        readiness.reference_bid_price_captured_at
    )
    if reference_bid_current_freshness != "fresh":
        blockers.append(
            f"readiness_reference_bid_price_{reference_bid_current_freshness}"
        )
    last_filled_current_freshness = _live_reference_freshness_status(
        readiness.last_filled_price_captured_at
    )
    if last_filled_current_freshness != "fresh":
        blockers.append(
            f"readiness_last_filled_price_{last_filled_current_freshness}"
        )
    if readiness.far_from_bid_status != "passed":
        blockers.append("readiness_far_from_bid_status_not_passed")
    if readiness.snapshot_non_fill_status != "passed":
        blockers.append("readiness_snapshot_non_fill_status_not_passed")
    blockers.extend(
        f"readiness_{blocker.removeprefix('live_readiness_')}"
        for blocker in _allowlist_live_readiness_non_fill_blockers(readiness)
    )
    if not readiness.single_order_only or readiness.order_count != 1:
        blockers.append("single_order_only_required")
    if readiness.full_snapshot_fill_test:
        blockers.append("manual_review_required_for_full_snapshot_fill_test")
    if not readiness.cancel_before_additional_orders:
        blockers.append("cancel_before_additional_orders_required")
    submitted_notional = _decimal_value(readiness.submitted_notional_usdc)
    max_executed_notional = _decimal_value(readiness.max_executed_notional_usdc)
    _, cap_guard_blockers = _usdc_pair_live_readiness_cap_guard_evidence(
        store=cap_guard_store,
        row=row,
        submitted_notional=submitted_notional,
    )
    blockers.extend(f"readiness_{blocker}" for blocker in cap_guard_blockers)
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
    "/automation/usdc-pair-snapshot-order-plans/{plan_id}/allowlist-readiness",
    response_model=UsdcPairSnapshotOrderPlanAllowlistReadinessResponse,
    status_code=status.HTTP_200_OK,
    responses=ALLOWLIST_READINESS_ROUTE_RESPONSES,
    summary="Record backend-owned USDC pair order-plan allowlist readiness",
)
def record_usdc_pair_snapshot_order_plan_allowlist_readiness(
    request: Request,
    plan_id: str,
    body: UsdcPairSnapshotOrderPlanAllowlistReadinessRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    order_plan_store: Annotated[
        FileUsdcPairSnapshotOrderPlanStore,
        Depends(get_usdc_pair_snapshot_order_plan_store),
    ],
    readiness_store: Annotated[
        FileUsdcPairSnapshotOrderPlanAllowlistReadinessStore,
        Depends(get_usdc_pair_snapshot_order_plan_allowlist_readiness_store),
    ],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
) -> JSONResponse:
    """Record no-live M58 allowlist readiness without fan-out execution."""

    endpoint = f"{request.method} {request.url.path}"
    payload_hash = _payload_hash(
        endpoint=endpoint,
        actor=actor,
        operator_intent=operator_intent,
        body=body.model_dump(mode="json"),
    )

    def operation(audit_id: str) -> UsdcPairSnapshotOrderPlanAllowlistReadinessItem:
        plan = order_plan_store.find_by_plan_id(plan_id)
        if plan is None:
            raise UsdcPairSnapshotError(
                "USDC pair snapshot order-plan not found."
            )
        return _record_usdc_pair_allowlist_readiness(
            plan=plan,
            body=body,
            readiness_store=readiness_store,
            actor=actor,
            operator_intent=operator_intent,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            audit_id=audit_id,
        )

    return _execute_idempotent_allowlist_readiness(
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
    (
        "/automation/usdc-pair-snapshot-order-plan-allowlist-readiness/"
        "{readiness_id}/run-state"
    ),
    response_model=UsdcPairSnapshotAllowlistRunStateResponse,
    status_code=status.HTTP_200_OK,
    responses=ALLOWLIST_RUN_STATE_ROUTE_RESPONSES,
    summary="Record backend-owned USDC pair allowlist run-state rehearsal",
)
def record_usdc_pair_snapshot_allowlist_run_state(
    request: Request,
    readiness_id: str,
    body: UsdcPairSnapshotAllowlistRunStateRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    readiness_store: Annotated[
        FileUsdcPairSnapshotOrderPlanAllowlistReadinessStore,
        Depends(get_usdc_pair_snapshot_order_plan_allowlist_readiness_store),
    ],
    run_state_store: Annotated[
        FileUsdcPairSnapshotAllowlistRunStateStore,
        Depends(get_usdc_pair_snapshot_allowlist_run_state_store),
    ],
    cap_guard_store: Annotated[
        FileAdminApiCapGuardStore,
        Depends(get_usdc_pair_snapshot_cap_guard_store),
    ],
    live_readiness_store: Annotated[
        FileUsdcPairSnapshotOrderPlanLiveReadinessStore,
        Depends(get_usdc_pair_snapshot_order_plan_live_readiness_store),
    ],
    live_wallet_reservation_store: Annotated[
        FileUsdcPairSnapshotLiveWalletReservationStore,
        Depends(get_usdc_pair_snapshot_live_wallet_reservation_store),
    ],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
) -> JSONResponse:
    """Record no-live M58 allowlist run-state evidence without fan-out."""

    endpoint = f"{request.method} {request.url.path}"
    payload_hash = _payload_hash(
        endpoint=endpoint,
        actor=actor,
        operator_intent=operator_intent,
        body=body.model_dump(mode="json"),
    )

    def operation(audit_id: str) -> UsdcPairSnapshotAllowlistRunStateItem:
        readiness = readiness_store.find_by_readiness_id(readiness_id)
        if readiness is None:
            raise UsdcPairSnapshotError(
                "USDC pair snapshot allowlist readiness was not found."
            )
        return _record_usdc_pair_allowlist_run_state(
            readiness=readiness,
            body=body,
            run_state_store=run_state_store,
            cap_guard_store=cap_guard_store,
            live_readiness_store=live_readiness_store,
            live_wallet_reservation_store=live_wallet_reservation_store,
            actor=actor,
            operator_intent=operator_intent,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            audit_id=audit_id,
        )

    return _execute_idempotent_allowlist_run_state(
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
    cap_guard_store: Annotated[
        FileAdminApiCapGuardStore,
        Depends(get_usdc_pair_snapshot_cap_guard_store),
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
            cap_guard_store=cap_guard_store,
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
    cap_guard_store: Annotated[
        FileAdminApiCapGuardStore,
        Depends(get_usdc_pair_snapshot_cap_guard_store),
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
            cap_guard_store=cap_guard_store,
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


@router.post(
    "/automation/usdc-pair-snapshot-allowlist-run-states/{run_state_id}/live-submit",
    response_model=UsdcPairSnapshotOrderPlanLiveSubmitResponse,
    status_code=status.HTTP_200_OK,
    responses=LIVE_SUBMIT_ROUTE_RESPONSES,
    summary="Submit and cancel one USDC pair snapshot order from run-state evidence",
)
def submit_usdc_pair_snapshot_allowlist_run_state_live_order(
    request: Request,
    run_state_id: str,
    body: UsdcPairSnapshotOrderPlanLiveSubmitRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    run_state_store: Annotated[
        FileUsdcPairSnapshotAllowlistRunStateStore,
        Depends(get_usdc_pair_snapshot_allowlist_run_state_store),
    ],
    order_plan_store: Annotated[
        FileUsdcPairSnapshotOrderPlanStore,
        Depends(get_usdc_pair_snapshot_order_plan_store),
    ],
    readiness_store: Annotated[
        FileUsdcPairSnapshotOrderPlanLiveReadinessStore,
        Depends(get_usdc_pair_snapshot_order_plan_live_readiness_store),
    ],
    cap_guard_store: Annotated[
        FileAdminApiCapGuardStore,
        Depends(get_usdc_pair_snapshot_cap_guard_store),
    ],
    live_wallet_reservation_store: Annotated[
        FileUsdcPairSnapshotLiveWalletReservationStore,
        Depends(get_usdc_pair_snapshot_live_wallet_reservation_store),
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
    """Submit one run-state-selected M58 order and cancel before any additional order."""

    endpoint = f"{request.method} {request.url.path}"
    payload_hash = _payload_hash(
        endpoint=endpoint,
        actor=actor,
        operator_intent=operator_intent,
        body=body.model_dump(mode="json"),
    )

    def operation(audit_id: str) -> UsdcPairSnapshotOrderPlanLiveSubmitItem:
        run_state = run_state_store.find_by_run_state_id(run_state_id)
        if run_state is None:
            raise UsdcPairSnapshotError(
                "USDC pair snapshot allowlist run-state was not found."
            )
        product_row = _validate_usdc_pair_allowlist_run_state_live_submit(
            run_state=run_state,
            body=body,
        )
        plan = order_plan_store.find_by_plan_id(run_state.plan_id)
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
        _validate_usdc_pair_allowlist_run_state_live_submit_association(
            run_state=run_state,
            plan=plan,
            readiness=readiness,
        )
        _validate_usdc_pair_allowlist_run_state_live_submit_wallet_evidence(
            run_state=run_state,
            product_row=product_row,
            reservation_store=live_wallet_reservation_store,
        )
        return _record_usdc_pair_live_submission(
            plan=plan,
            row=row,
            readiness=readiness,
            body=body,
            cap_guard_store=cap_guard_store,
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
        endpoint=USDC_PAIR_SNAPSHOT_ALLOWLIST_RUN_STATE_LIVE_SUBMIT_ENDPOINT,
        service_method=(
            USDC_PAIR_SNAPSHOT_ALLOWLIST_RUN_STATE_LIVE_SUBMIT_SERVICE_METHOD
        ),
        failure_stage="usdc_pair_snapshot_allowlist_run_state_live_submit",
        accepted_message=(
            "USDC pair snapshot allowlist run-state controlled-live "
            "submit/cancel accepted for one selected order."
        ),
    )
