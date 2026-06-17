"""Live execution service decision evidence routes for the Admin API."""

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
from application.admin_api.live_execution import FileAdminApiLiveServiceDecisionStore
from application.admin_api.live_service_decision_service import (
    AdminApiLiveServiceDecisionService,
    LiveServiceDecisionError,
)
from application.admin_api.models import (
    AdminApiActor,
    AdminApiErrorResponse,
    AdminLiveServiceDecisionCreateRequest,
    AdminLiveServiceDecisionItem,
    AdminLiveServiceDecisionListResponse,
    AdminLiveServiceDecisionResponse,
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
        "description": "Live-service decision was not found.",
    },
}

DECISION_ROUTE_RESPONSES = {
    200: {
        "model": AdminLiveServiceDecisionResponse,
        "description": "Live-service decision mutation accepted or replayed.",
    },
    400: {
        "model": AdminLiveServiceDecisionResponse,
        "description": "Live-service decision mutation rejected.",
    },
    401: READ_ROUTE_RESPONSES[401],
    403: READ_ROUTE_RESPONSES[403],
    409: {
        "model": AdminLiveServiceDecisionResponse,
        "description": "Idempotency key conflict.",
    },
}


def get_live_service_decision_store() -> FileAdminApiLiveServiceDecisionStore:
    """Return durable live-service decision storage."""

    return FileAdminApiLiveServiceDecisionStore()


def get_idempotency_store() -> FileIdempotencyStore:
    """Return durable idempotency storage for live-service decision routes."""

    return FileIdempotencyStore()


def get_audit_store() -> FileAdminApiAuditStore:
    """Return durable audit storage for live-service decision routes."""

    return FileAdminApiAuditStore()


def get_live_service_decision_service() -> AdminApiLiveServiceDecisionService:
    """Return the backend-owned live-service decision service."""

    return AdminApiLiveServiceDecisionService()


def _http_status_for(response: AdminLiveServiceDecisionResponse) -> int:
    if response.status == AdminApiCommandStatus.CONFLICT:
        return status.HTTP_409_CONFLICT
    if response.status == AdminApiCommandStatus.REJECTED:
        return status.HTTP_400_BAD_REQUEST
    return status.HTTP_200_OK


def _decision_response(
    response: AdminLiveServiceDecisionResponse,
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


def _live_service_decision_payload_hash(
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


def _record_live_service_decision_audit(
    *,
    audit_store: FileAdminApiAuditStore,
    actor: AdminApiActor,
    endpoint: str,
    request_id: str,
    operator_intent: str,
    response: AdminLiveServiceDecisionResponse,
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
            approval_id=None,
            status=response.status,
            failure_stage=(
                "idempotency"
                if response.status == AdminApiCommandStatus.CONFLICT
                else (
                    "live_service_decision"
                    if response.status == AdminApiCommandStatus.REJECTED
                    else None
                )
            ),
            message=response.message,
        )
    )


def _execute_idempotent_live_service_decision(
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
    operation: Callable[[], AdminLiveServiceDecisionItem],
) -> JSONResponse:
    require_permission(actor, required_permission)
    check = idempotency_store.evaluate(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
    )
    if check.decision == AdminApiIdempotencyDecision.REPLAY and check.record:
        payload = dict(check.record.response)
        return _decision_response(
            AdminLiveServiceDecisionResponse.model_validate(payload),
            replayed=True,
        )
    if check.decision == AdminApiIdempotencyDecision.CONFLICT:
        response = AdminLiveServiceDecisionResponse(
            status=AdminApiCommandStatus.CONFLICT,
            required_permission=required_permission,
            service_method=service_method,
            message="Idempotency-Key was already used with a different payload.",
            correlation_id=request_id,
            idempotency_key=idempotency_key,
        )
        response.audit_id = _record_live_service_decision_audit(
            audit_store=audit_store,
            actor=actor,
            endpoint=endpoint,
            request_id=request_id,
            operator_intent=operator_intent,
            response=response,
        )
        return _decision_response(response)

    try:
        decision = operation()
        response = AdminLiveServiceDecisionResponse(
            status=AdminApiCommandStatus.ACCEPTED,
            required_permission=required_permission,
            service_method=service_method,
            message=f"Live-service decision {service_method} accepted.",
            decision=decision,
            correlation_id=request_id,
            idempotency_key=idempotency_key,
        )
    except LiveServiceDecisionError as exc:
        response = AdminLiveServiceDecisionResponse(
            status=AdminApiCommandStatus.REJECTED,
            required_permission=required_permission,
            service_method=service_method,
            message=str(exc),
            correlation_id=request_id,
            idempotency_key=idempotency_key,
        )
    response.audit_id = _record_live_service_decision_audit(
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
    return _decision_response(response)


@router.get(
    "/admin/live-execution/service-decisions",
    response_model=AdminLiveServiceDecisionListResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="List backend-owned live-service decision records",
)
def list_admin_live_service_decisions(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        AdminApiLiveServiceDecisionService,
        Depends(get_live_service_decision_service),
    ],
    decision_store: Annotated[
        FileAdminApiLiveServiceDecisionStore,
        Depends(get_live_service_decision_store),
    ],
    decision_status: AdminApiGateStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    decisions = service.list_decisions(
        store=decision_store,
        status_filter=decision_status,
        limit=limit,
    )
    all_decisions = service.list_decisions(store=decision_store, limit=500)
    counts = {status_value: 0 for status_value in AdminApiGateStatus}
    for item in all_decisions:
        counts[item.status] += 1
    payload = AdminLiveServiceDecisionListResponse(
        decisions=decisions,
        returned_count=len(decisions),
        total_count=len(all_decisions),
        passed_count=counts[AdminApiGateStatus.PASSED],
        blocked_count=counts[AdminApiGateStatus.BLOCKED],
        warning_count=counts[AdminApiGateStatus.WARNING],
        resolver_eligible_count=sum(
            1 for decision in all_decisions if decision.resolver_eligible
        ),
    )
    return JSONResponse(content=payload.model_dump(mode="json"))


@router.get(
    "/admin/live-execution/service-decisions/{decision_id}",
    response_model=AdminLiveServiceDecisionResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Read one backend-owned live-service decision record",
)
def get_admin_live_service_decision(
    decision_id: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        AdminApiLiveServiceDecisionService,
        Depends(get_live_service_decision_service),
    ],
    decision_store: Annotated[
        FileAdminApiLiveServiceDecisionStore,
        Depends(get_live_service_decision_store),
    ],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    try:
        decision = service.get_decision(
            store=decision_store,
            decision_id=decision_id,
        )
    except LiveServiceDecisionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    payload = AdminLiveServiceDecisionResponse(
        status=AdminApiCommandStatus.ACCEPTED,
        required_permission=AdminApiPermission.ANALYTICS_READ,
        service_method="get_live_service_decision",
        message="Live-service decision detail loaded.",
        decision=decision,
    )
    return JSONResponse(content=payload.model_dump(mode="json"))


@router.post(
    "/admin/live-execution/service-decisions",
    response_model=AdminLiveServiceDecisionResponse,
    responses=DECISION_ROUTE_RESPONSES,
    summary="Record a backend-owned live-service decision",
)
def record_admin_live_service_decision(
    request: Request,
    body: AdminLiveServiceDecisionCreateRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        AdminApiLiveServiceDecisionService,
        Depends(get_live_service_decision_service),
    ],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    decision_store: Annotated[
        FileAdminApiLiveServiceDecisionStore,
        Depends(get_live_service_decision_store),
    ],
) -> JSONResponse:
    endpoint = f"{request.method} {request.url.path}"
    payload_hash = _live_service_decision_payload_hash(
        endpoint=endpoint,
        actor=actor,
        operator_intent=operator_intent,
        body=body.model_dump(mode="json"),
    )
    return _execute_idempotent_live_service_decision(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        required_permission=AdminApiPermission.CONFIG_UPDATE,
        service_method="record_live_service_decision",
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        operation=lambda: service.record_decision(
            store=decision_store,
            body=body,
        ),
    )

