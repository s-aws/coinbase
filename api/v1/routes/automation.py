"""Automation Admin API routes."""

from __future__ import annotations

from typing import Annotated, Any, Callable
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
from application.admin_api.models import (
    AdminApiActor,
    AdminApiErrorResponse,
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
    FileUsdcPairSnapshotOrderPlanStore,
    FileUsdcPairSnapshotRunStore,
)
from application.admin_api.usdc_pair_snapshot_service import (
    AdminApiUsdcPairSnapshotService,
    UsdcPairSnapshotError,
    item_from_record,
    order_plan_item_from_record,
)
from core.enums import (
    AdminApiActionClass,
    AdminApiApprovalLifecycleEventType,
    AdminApiCommandStatus,
    AdminApiIdempotencyDecision,
    AdminApiPermission,
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
USDC_PAIR_SNAPSHOT_MODULE_ID = "automation"
USDC_PAIR_SNAPSHOT_PROOF_BLOCKERS = [
    "approval_snapshot_missing",
    "admission_audit_blocked",
    "cap_guard_decision_blocked",
    "reconciliation_plan_blocked",
    "live_service_decision_missing",
]

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
) -> Callable[[Any], dict[str, Any]]:
    def record(row: Any) -> dict[str, Any]:
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


def _usdc_pair_order_plan_proof_chain_refresher(
    *,
    approval_store: FileAdminApiApprovalStore,
    admission_audit_store: FileAdminApiAuditStore,
    cap_guard_store: FileAdminApiCapGuardStore,
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
                ),
            )
        if cap_guard is not None:
            blockers = [
                blocker
                for blocker in blockers
                if blocker != "cap_guard_decision_blocked"
            ]
        approval_request_id = _approval_request_id_for_snapshot(
            approval_store=approval_store,
            approval_id=approval_snapshot.approval_id,
        )
        return {
            "proof_chain_status": "blocked",
            "proof_chain_blockers": blockers,
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
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
            "live_coinbase_execution": "not_run",
            "notional_usdc": "0",
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
            ),
        ),
    )
