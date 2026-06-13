"""Reconciliation plan proof routes for the Admin API."""

from __future__ import annotations

from typing import Annotated, Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request, status
from fastapi.responses import JSONResponse

from application.admin_api.audit import AdminApiAuditEvent, FileAdminApiAuditStore
from application.admin_api.auth import get_authenticated_actor, require_permission
from application.admin_api.idempotency import (
    FileIdempotencyStore,
    IdempotencyRecord,
    make_payload_hash,
)
from application.admin_api.models import (
    AdminApiActor,
    AdminApiErrorResponse,
    AdminReconciliationPlanCreateRequest,
    AdminReconciliationPlanItem,
    AdminReconciliationPlanListResponse,
    AdminReconciliationPlanResponse,
)
from application.admin_api.reconciliation import FileAdminApiReconciliationStore
from application.admin_api.reconciliation_service import (
    AdminApiReconciliationPlanService,
    ReconciliationPlanError,
)
from core.enums import (
    AdminApiCommandStatus,
    AdminApiGateStatus,
    AdminApiIdempotencyDecision,
    AdminApiPermission,
)


router = APIRouter()

READ_ROUTE_RESPONSES = {
    401: {
        "model": AdminApiErrorResponse,
        "description": "Missing or invalid Admin API authentication.",
    },
    403: {
        "model": AdminApiErrorResponse,
        "description": "Actor lacks the required Admin API permission.",
    },
    404: {
        "model": AdminApiErrorResponse,
        "description": "Reconciliation plan was not found.",
    },
}

PLAN_ROUTE_RESPONSES = {
    200: {
        "model": AdminReconciliationPlanResponse,
        "description": "Reconciliation plan mutation accepted or replayed.",
    },
    400: {
        "model": AdminReconciliationPlanResponse,
        "description": "Reconciliation plan mutation rejected.",
    },
    401: READ_ROUTE_RESPONSES[401],
    403: READ_ROUTE_RESPONSES[403],
    409: {
        "model": AdminReconciliationPlanResponse,
        "description": "Idempotency key conflict.",
    },
}


def get_reconciliation_store() -> FileAdminApiReconciliationStore:
    """Return durable reconciliation plan storage."""

    return FileAdminApiReconciliationStore()


def get_idempotency_store() -> FileIdempotencyStore:
    """Return durable idempotency storage for reconciliation routes."""

    return FileIdempotencyStore()


def get_audit_store() -> FileAdminApiAuditStore:
    """Return durable audit storage for reconciliation routes."""

    return FileAdminApiAuditStore()


def get_reconciliation_plan_service() -> AdminApiReconciliationPlanService:
    """Return the backend-owned reconciliation plan service."""

    return AdminApiReconciliationPlanService()


def _http_status_for(response: AdminReconciliationPlanResponse) -> int:
    if response.status == AdminApiCommandStatus.CONFLICT:
        return status.HTTP_409_CONFLICT
    if response.status == AdminApiCommandStatus.REJECTED:
        return status.HTTP_400_BAD_REQUEST
    return status.HTTP_200_OK


def _plan_response(
    response: AdminReconciliationPlanResponse,
    *,
    replayed: bool = False,
) -> JSONResponse:
    headers = {"X-Correlation-Id": response.correlation_id or ""}
    if replayed:
        headers["X-Idempotency-Replayed"] = "true"
    return JSONResponse(
        status_code=_http_status_for(response),
        content=response.model_dump(mode="json"),
        headers=headers,
    )


def _reconciliation_payload_hash(
    *,
    endpoint: str,
    actor: AdminApiActor,
    operator_intent: str,
    body: dict,
    path_params: dict | None = None,
) -> str:
    return make_payload_hash({
        "endpoint": endpoint,
        "actor_id": actor.actor_id,
        "roles": [role.value for role in actor.roles],
        "operator_intent": operator_intent,
        "body": body,
        "path_params": path_params or {},
    })


def _record_reconciliation_audit(
    *,
    audit_store: FileAdminApiAuditStore,
    actor: AdminApiActor,
    endpoint: str,
    request_id: str,
    operator_intent: str,
    response: AdminReconciliationPlanResponse,
) -> str:
    return audit_store.append(
        AdminApiAuditEvent(
            actor_id=actor.actor_id,
            action_class=response.action_class,
            permission=response.required_permission,
            endpoint=endpoint,
            request_id=request_id,
            operator_intent=operator_intent,
            idempotency_key=response.idempotency_key,
            approval_id=(
                response.plan.approval_snapshot_id
                if response.plan is not None
                else None
            ),
            status=response.status,
            failure_stage=(
                "idempotency"
                if response.status == AdminApiCommandStatus.CONFLICT
                else (
                    "reconciliation_plan"
                    if response.status == AdminApiCommandStatus.REJECTED
                    else None
                )
            ),
            message=response.message,
        )
    )


def _execute_idempotent_reconciliation_plan(
    *,
    idempotency_key: str,
    payload_hash: str,
    actor: AdminApiActor,
    endpoint: str,
    request_id: str,
    operator_intent: str,
    required_permission: AdminApiPermission,
    service_method: str,
    idempotency_store: FileIdempotencyStore,
    audit_store: FileAdminApiAuditStore,
    operation: Callable[[], AdminReconciliationPlanItem],
) -> JSONResponse:
    require_permission(actor, required_permission)
    check = idempotency_store.evaluate(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
    )
    if check.decision == AdminApiIdempotencyDecision.REPLAY and check.record:
        payload = dict(check.record.response)
        return _plan_response(
            AdminReconciliationPlanResponse.model_validate(payload),
            replayed=True,
        )
    if check.decision == AdminApiIdempotencyDecision.CONFLICT:
        response = AdminReconciliationPlanResponse(
            status=AdminApiCommandStatus.CONFLICT,
            required_permission=required_permission,
            service_method=service_method,
            message="Idempotency-Key was already used with a different payload.",
            correlation_id=request_id,
            idempotency_key=idempotency_key,
        )
        response.audit_id = _record_reconciliation_audit(
            audit_store=audit_store,
            actor=actor,
            endpoint=endpoint,
            request_id=request_id,
            operator_intent=operator_intent,
            response=response,
        )
        return _plan_response(response)

    try:
        plan = operation()
        response = AdminReconciliationPlanResponse(
            status=AdminApiCommandStatus.ACCEPTED,
            required_permission=required_permission,
            service_method=service_method,
            message=f"Reconciliation plan {service_method} accepted.",
            plan=plan,
            correlation_id=request_id,
            idempotency_key=idempotency_key,
        )
    except ReconciliationPlanError as exc:
        response = AdminReconciliationPlanResponse(
            status=AdminApiCommandStatus.REJECTED,
            required_permission=required_permission,
            service_method=service_method,
            message=str(exc),
            correlation_id=request_id,
            idempotency_key=idempotency_key,
        )
    response.audit_id = _record_reconciliation_audit(
        audit_store=audit_store,
        actor=actor,
        endpoint=endpoint,
        request_id=request_id,
        operator_intent=operator_intent,
        response=response,
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
    return _plan_response(response)


@router.get(
    "/admin/reconciliation/plans",
    response_model=AdminReconciliationPlanListResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="List backend-owned reconciliation plan records",
)
def list_admin_reconciliation_plans(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        AdminApiReconciliationPlanService,
        Depends(get_reconciliation_plan_service),
    ],
    reconciliation_store: Annotated[
        FileAdminApiReconciliationStore,
        Depends(get_reconciliation_store),
    ],
    plan_status: AdminApiGateStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.RECONCILIATION_READ)
    plans = service.list_plans(
        store=reconciliation_store,
        status_filter=plan_status,
        limit=limit,
    )
    all_plans = service.list_plans(store=reconciliation_store, limit=500)
    counts = {status_value: 0 for status_value in AdminApiGateStatus}
    for item in all_plans:
        counts[item.status] += 1
    payload = AdminReconciliationPlanListResponse(
        plans=plans,
        returned_count=len(plans),
        total_count=len(all_plans),
        passed_count=counts[AdminApiGateStatus.PASSED],
        blocked_count=counts[AdminApiGateStatus.BLOCKED],
        warning_count=counts[AdminApiGateStatus.WARNING],
        resolver_eligible_count=sum(1 for plan in all_plans if plan.resolver_eligible),
    )
    return JSONResponse(content=payload.model_dump(mode="json"))


@router.get(
    "/admin/reconciliation/plans/{plan_id}",
    response_model=AdminReconciliationPlanResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Read one backend-owned reconciliation plan record",
)
def get_admin_reconciliation_plan(
    plan_id: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        AdminApiReconciliationPlanService,
        Depends(get_reconciliation_plan_service),
    ],
    reconciliation_store: Annotated[
        FileAdminApiReconciliationStore,
        Depends(get_reconciliation_store),
    ],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.RECONCILIATION_READ)
    try:
        plan = service.get_plan(store=reconciliation_store, plan_id=plan_id)
    except ReconciliationPlanError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    payload = AdminReconciliationPlanResponse(
        status=AdminApiCommandStatus.ACCEPTED,
        required_permission=AdminApiPermission.RECONCILIATION_READ,
        service_method="get_reconciliation_plan",
        message="Reconciliation plan detail loaded.",
        plan=plan,
    )
    return JSONResponse(content=payload.model_dump(mode="json"))


@router.post(
    "/admin/reconciliation/plans",
    response_model=AdminReconciliationPlanResponse,
    responses=PLAN_ROUTE_RESPONSES,
    summary="Record a backend-owned reconciliation plan",
)
def record_admin_reconciliation_plan(
    request: Request,
    body: AdminReconciliationPlanCreateRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        AdminApiReconciliationPlanService,
        Depends(get_reconciliation_plan_service),
    ],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    reconciliation_store: Annotated[
        FileAdminApiReconciliationStore,
        Depends(get_reconciliation_store),
    ],
) -> JSONResponse:
    endpoint = f"{request.method} {request.url.path}"
    payload_hash = _reconciliation_payload_hash(
        endpoint=endpoint,
        actor=actor,
        operator_intent=operator_intent,
        body=body.model_dump(mode="json"),
    )
    return _execute_idempotent_reconciliation_plan(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        required_permission=AdminApiPermission.RECONCILIATION_RECORD,
        service_method="record_reconciliation_plan",
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        operation=lambda: service.record_plan(
            store=reconciliation_store,
            body=body,
        ),
    )
