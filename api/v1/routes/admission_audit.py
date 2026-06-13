"""Admission audit writer routes for the Admin API."""

from __future__ import annotations

from typing import Annotated, Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request, status
from fastapi.responses import JSONResponse

from application.admin_api.admission_audit_service import (
    AdminApiAdmissionAuditService,
    AdmissionAuditError,
)
from application.admin_api.audit import AdminApiAuditEvent, FileAdminApiAuditStore
from application.admin_api.auth import get_authenticated_actor, require_permission
from application.admin_api.idempotency import (
    FileIdempotencyStore,
    IdempotencyRecord,
    make_payload_hash,
)
from application.admin_api.models import (
    AdminAdmissionAuditCreateRequest,
    AdminAdmissionAuditItem,
    AdminAdmissionAuditListResponse,
    AdminAdmissionAuditResponse,
    AdminApiActor,
    AdminApiErrorResponse,
)
from core.enums import (
    AdminApiActionClass,
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
        "description": "Admission audit was not found.",
    },
}

AUDIT_ROUTE_RESPONSES = {
    200: {
        "model": AdminAdmissionAuditResponse,
        "description": "Admission audit mutation accepted or replayed.",
    },
    400: {
        "model": AdminAdmissionAuditResponse,
        "description": "Admission audit mutation rejected.",
    },
    401: READ_ROUTE_RESPONSES[401],
    403: READ_ROUTE_RESPONSES[403],
    409: {
        "model": AdminAdmissionAuditResponse,
        "description": "Idempotency key conflict.",
    },
}


def get_audit_store() -> FileAdminApiAuditStore:
    """Return durable audit storage for admission audit routes."""

    return FileAdminApiAuditStore()


def get_idempotency_store() -> FileIdempotencyStore:
    """Return durable idempotency storage for admission audit routes."""

    return FileIdempotencyStore()


def get_admission_audit_service() -> AdminApiAdmissionAuditService:
    """Return the backend-owned admission audit service."""

    return AdminApiAdmissionAuditService()


def _http_status_for(response: AdminAdmissionAuditResponse) -> int:
    if response.status == AdminApiCommandStatus.CONFLICT:
        return status.HTTP_409_CONFLICT
    if response.status == AdminApiCommandStatus.REJECTED:
        return status.HTTP_400_BAD_REQUEST
    return status.HTTP_200_OK


def _audit_response(
    response: AdminAdmissionAuditResponse,
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


def _admission_audit_payload_hash(
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


def _record_writer_audit(
    *,
    audit_store: FileAdminApiAuditStore,
    actor: AdminApiActor,
    endpoint: str,
    request_id: str,
    operator_intent: str,
    response: AdminAdmissionAuditResponse,
) -> str:
    return audit_store.append(
        AdminApiAuditEvent(
            actor_id=actor.actor_id,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            permission=AdminApiPermission.ADMISSION_AUDIT_RECORD,
            endpoint=endpoint,
            request_id=request_id,
            operator_intent=operator_intent,
            idempotency_key=response.idempotency_key,
            approval_id=(
                response.admission_audit.approval_snapshot_id
                if response.admission_audit is not None
                else None
            ),
            status=response.status,
            failure_stage=(
                "idempotency"
                if response.status == AdminApiCommandStatus.CONFLICT
                else (
                    "admission_audit"
                    if response.status == AdminApiCommandStatus.REJECTED
                    else None
                )
            ),
            message=response.message,
        )
    )


def _execute_idempotent_admission_audit(
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
    operation: Callable[[], AdminAdmissionAuditItem],
) -> JSONResponse:
    require_permission(actor, required_permission)
    check = idempotency_store.evaluate(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
    )
    if check.decision == AdminApiIdempotencyDecision.REPLAY and check.record:
        payload = dict(check.record.response)
        return _audit_response(
            AdminAdmissionAuditResponse.model_validate(payload),
            replayed=True,
        )
    if check.decision == AdminApiIdempotencyDecision.CONFLICT:
        response = AdminAdmissionAuditResponse(
            status=AdminApiCommandStatus.CONFLICT,
            required_permission=required_permission,
            service_method=service_method,
            message="Idempotency-Key was already used with a different payload.",
            correlation_id=request_id,
            idempotency_key=idempotency_key,
        )
        response.audit_id = _record_writer_audit(
            audit_store=audit_store,
            actor=actor,
            endpoint=endpoint,
            request_id=request_id,
            operator_intent=operator_intent,
            response=response,
        )
        return _audit_response(response)

    try:
        admission_audit = operation()
        response = AdminAdmissionAuditResponse(
            status=AdminApiCommandStatus.ACCEPTED,
            required_permission=required_permission,
            service_method=service_method,
            message=f"Admission audit {service_method} accepted.",
            admission_audit=admission_audit,
            correlation_id=request_id,
            idempotency_key=idempotency_key,
            audit_id=admission_audit.admission_audit_id,
        )
    except AdmissionAuditError as exc:
        response = AdminAdmissionAuditResponse(
            status=AdminApiCommandStatus.REJECTED,
            required_permission=required_permission,
            service_method=service_method,
            message=str(exc),
            correlation_id=request_id,
            idempotency_key=idempotency_key,
        )
        response.audit_id = _record_writer_audit(
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
    return _audit_response(response)


@router.get(
    "/admin/admission-audits",
    response_model=AdminAdmissionAuditListResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="List backend-owned admission audit records",
)
def list_admin_admission_audits(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        AdminApiAdmissionAuditService,
        Depends(get_admission_audit_service),
    ],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    admission_status: AdminApiGateStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.ADMISSION_AUDIT_READ)
    admission_audits = service.list_admission_audits(
        store=audit_store,
        status_filter=admission_status,
        limit=limit,
    )
    all_admission_audits = service.list_admission_audits(
        store=audit_store,
        limit=500,
    )
    payload = AdminAdmissionAuditListResponse(
        admission_audits=admission_audits,
        returned_count=len(admission_audits),
        total_count=len(all_admission_audits),
        blocked_count=sum(
            1
            for item in all_admission_audits
            if item.status == AdminApiGateStatus.BLOCKED
        ),
        passed_count=sum(
            1
            for item in all_admission_audits
            if item.status == AdminApiGateStatus.PASSED
        ),
        resolver_eligible_count=sum(
            1 for item in all_admission_audits if item.resolver_eligible
        ),
    )
    return JSONResponse(content=payload.model_dump(mode="json"))


@router.get(
    "/admin/admission-audits/{admission_audit_id}",
    response_model=AdminAdmissionAuditResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Read one backend-owned admission audit record",
)
def get_admin_admission_audit(
    admission_audit_id: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        AdminApiAdmissionAuditService,
        Depends(get_admission_audit_service),
    ],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.ADMISSION_AUDIT_READ)
    try:
        admission_audit = service.get_admission_audit(
            store=audit_store,
            admission_audit_id=admission_audit_id,
        )
    except AdmissionAuditError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    payload = AdminAdmissionAuditResponse(
        status=AdminApiCommandStatus.ACCEPTED,
        required_permission=AdminApiPermission.ADMISSION_AUDIT_READ,
        service_method="get_admission_audit",
        message="Admission audit detail loaded.",
        admission_audit=admission_audit,
    )
    return JSONResponse(content=payload.model_dump(mode="json"))


@router.post(
    "/admin/admission-audits",
    response_model=AdminAdmissionAuditResponse,
    responses=AUDIT_ROUTE_RESPONSES,
    summary="Record a backend-owned admission audit",
)
def record_admin_admission_audit(
    request: Request,
    body: AdminAdmissionAuditCreateRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        AdminApiAdmissionAuditService,
        Depends(get_admission_audit_service),
    ],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
) -> JSONResponse:
    endpoint = f"{request.method} {request.url.path}"
    payload_hash = _admission_audit_payload_hash(
        endpoint=endpoint,
        actor=actor,
        operator_intent=operator_intent,
        body=body.model_dump(mode="json"),
    )
    return _execute_idempotent_admission_audit(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        required_permission=AdminApiPermission.ADMISSION_AUDIT_RECORD,
        service_method="record_admission_audit",
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        operation=lambda: service.record_admission_audit(
            store=audit_store,
            body=body,
            request_id=correlation_id,
        ),
    )
