"""Approval lifecycle routes for the Admin API."""

from __future__ import annotations

from typing import Annotated, Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request, status
from fastapi.responses import JSONResponse

from application.admin_api.approval import FileAdminApiApprovalStore
from application.admin_api.approval_service import (
    AdminApiApprovalLifecycleService,
    ApprovalLifecycleError,
)
from application.admin_api.audit import AdminApiAuditEvent, FileAdminApiAuditStore
from application.admin_api.auth import (
    actor_has_permission,
    get_authenticated_actor,
    require_permission,
)
from application.admin_api.idempotency import (
    FileIdempotencyStore,
    IdempotencyRecord,
    make_payload_hash,
)
from application.admin_api.models import (
    AdminApiActor,
    AdminApiErrorResponse,
    AdminApprovalDecisionRequest,
    AdminApprovalLifecycleItem,
    AdminApprovalLifecycleResponse,
    AdminApprovalListResponse,
    AdminApprovalRequestCreateRequest,
    AdminApprovalRevokeRequest,
)
from core.enums import (
    AdminApiActionClass,
    AdminApiApprovalLifecycleStatus,
    AdminApiCommandStatus,
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
}

LIFECYCLE_ROUTE_RESPONSES = {
    200: {
        "model": AdminApprovalLifecycleResponse,
        "description": "Approval lifecycle mutation accepted or replayed.",
    },
    400: {
        "model": AdminApprovalLifecycleResponse,
        "description": "Approval lifecycle mutation rejected.",
    },
    401: READ_ROUTE_RESPONSES[401],
    403: READ_ROUTE_RESPONSES[403],
    409: {
        "model": AdminApprovalLifecycleResponse,
        "description": "Idempotency key conflict.",
    },
}


def get_approval_store() -> FileAdminApiApprovalStore:
    """Return durable approval lifecycle storage."""

    return FileAdminApiApprovalStore()


def get_idempotency_store() -> FileIdempotencyStore:
    """Return durable idempotency storage for approval lifecycle routes."""

    return FileIdempotencyStore()


def get_audit_store() -> FileAdminApiAuditStore:
    """Return durable audit storage for approval lifecycle routes."""

    return FileAdminApiAuditStore()


def get_approval_lifecycle_service() -> AdminApiApprovalLifecycleService:
    """Return the backend-owned approval lifecycle service."""

    return AdminApiApprovalLifecycleService()


def _http_status_for(response: AdminApprovalLifecycleResponse) -> int:
    if response.status == AdminApiCommandStatus.CONFLICT:
        return status.HTTP_409_CONFLICT
    if response.status == AdminApiCommandStatus.REJECTED:
        return status.HTTP_400_BAD_REQUEST
    return status.HTTP_200_OK


def _lifecycle_response(
    response: AdminApprovalLifecycleResponse,
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


def _approval_payload_hash(
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


def _record_lifecycle_audit(
    *,
    audit_store: FileAdminApiAuditStore,
    actor: AdminApiActor,
    endpoint: str,
    request_id: str,
    operator_intent: str,
    response: AdminApprovalLifecycleResponse,
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
                response.approval.approval_id
                if response.approval is not None
                else None
            ),
            status=response.status,
            failure_stage=(
                "idempotency"
                if response.status == AdminApiCommandStatus.CONFLICT
                else None
            ),
            message=response.message,
        )
    )


def _execute_idempotent_lifecycle(
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
    operation: Callable[[], AdminApprovalLifecycleItem],
) -> JSONResponse:
    require_permission(actor, required_permission)
    check = idempotency_store.evaluate(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
    )
    if check.decision == AdminApiIdempotencyDecision.REPLAY and check.record:
        payload = dict(check.record.response)
        return _lifecycle_response(
            AdminApprovalLifecycleResponse.model_validate(payload),
            replayed=True,
        )
    if check.decision == AdminApiIdempotencyDecision.CONFLICT:
        response = AdminApprovalLifecycleResponse(
            status=AdminApiCommandStatus.CONFLICT,
            required_permission=required_permission,
            service_method=service_method,
            message="Idempotency-Key was already used with a different payload.",
            correlation_id=request_id,
            idempotency_key=idempotency_key,
        )
        response.audit_id = _record_lifecycle_audit(
            audit_store=audit_store,
            actor=actor,
            endpoint=endpoint,
            request_id=request_id,
            operator_intent=operator_intent,
            response=response,
        )
        return _lifecycle_response(response)

    try:
        approval = operation()
        response = AdminApprovalLifecycleResponse(
            status=AdminApiCommandStatus.ACCEPTED,
            required_permission=required_permission,
            service_method=service_method,
            message=f"Approval lifecycle {service_method} accepted.",
            approval=approval,
            correlation_id=request_id,
            idempotency_key=idempotency_key,
        )
    except ApprovalLifecycleError as exc:
        response = AdminApprovalLifecycleResponse(
            status=AdminApiCommandStatus.REJECTED,
            required_permission=required_permission,
            service_method=service_method,
            message=str(exc),
            correlation_id=request_id,
            idempotency_key=idempotency_key,
        )
    response.audit_id = _record_lifecycle_audit(
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
    return _lifecycle_response(response)


def _assert_underlying_permission(
    actor: AdminApiActor,
    permission: AdminApiPermission | str,
) -> None:
    try:
        permission_enum = (
            permission
            if isinstance(permission, AdminApiPermission)
            else AdminApiPermission(permission)
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Approval requests must target an Admin API permission.",
        ) from exc
    if actor_has_permission(actor, permission_enum):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            "Actor cannot request approval for missing permission: "
            f"{permission_enum.value}"
        ),
    )


@router.get(
    "/admin/approvals",
    response_model=AdminApprovalListResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="List backend-owned approval lifecycle records",
)
def list_admin_approvals(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        AdminApiApprovalLifecycleService,
        Depends(get_approval_lifecycle_service),
    ],
    approval_store: Annotated[FileAdminApiApprovalStore, Depends(get_approval_store)],
    lifecycle_status: AdminApiApprovalLifecycleStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.APPROVAL_READ)
    approvals = service.list_approvals(
        store=approval_store,
        status_filter=lifecycle_status,
        limit=limit,
    )
    counts = {status_value: 0 for status_value in AdminApiApprovalLifecycleStatus}
    for item in service.list_approvals(store=approval_store, limit=500):
        counts[item.status] += 1
    payload = AdminApprovalListResponse(
        approvals=approvals,
        returned_count=len(approvals),
        total_count=sum(counts.values()),
        pending_count=counts[AdminApiApprovalLifecycleStatus.REQUESTED],
        approved_count=counts[AdminApiApprovalLifecycleStatus.APPROVED],
        rejected_count=counts[AdminApiApprovalLifecycleStatus.REJECTED],
        revoked_count=counts[AdminApiApprovalLifecycleStatus.REVOKED],
        expired_count=counts[AdminApiApprovalLifecycleStatus.EXPIRED],
    )
    return JSONResponse(content=payload.model_dump(mode="json"))


@router.get(
    "/admin/approvals/requests/{approval_request_id}",
    response_model=AdminApprovalLifecycleResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Read one backend-owned approval request lifecycle",
)
def get_admin_approval_request(
    approval_request_id: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        AdminApiApprovalLifecycleService,
        Depends(get_approval_lifecycle_service),
    ],
    approval_store: Annotated[FileAdminApiApprovalStore, Depends(get_approval_store)],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.APPROVAL_READ)
    try:
        approval = service.get_request(
            store=approval_store,
            approval_request_id=approval_request_id,
        )
    except ApprovalLifecycleError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    payload = AdminApprovalLifecycleResponse(
        status=AdminApiCommandStatus.ACCEPTED,
        required_permission=AdminApiPermission.APPROVAL_READ,
        service_method="get_approval_request",
        message="Approval lifecycle detail loaded.",
        approval=approval,
    )
    return JSONResponse(content=payload.model_dump(mode="json"))


@router.post(
    "/admin/approvals/requests",
    response_model=AdminApprovalLifecycleResponse,
    responses=LIFECYCLE_ROUTE_RESPONSES,
    summary="Create a backend-owned approval request",
)
def create_admin_approval_request(
    request: Request,
    body: AdminApprovalRequestCreateRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        AdminApiApprovalLifecycleService,
        Depends(get_approval_lifecycle_service),
    ],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    approval_store: Annotated[FileAdminApiApprovalStore, Depends(get_approval_store)],
) -> JSONResponse:
    _assert_underlying_permission(actor, body.required_permission)
    endpoint = f"{request.method} {request.url.path}"
    payload_hash = _approval_payload_hash(
        endpoint=endpoint,
        actor=actor,
        operator_intent=operator_intent,
        body=body.model_dump(mode="json"),
    )
    return _execute_idempotent_lifecycle(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        required_permission=AdminApiPermission.APPROVAL_REQUEST,
        service_method="create_approval_request",
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        operation=lambda: service.create_request(
            store=approval_store,
            body=body,
            actor_id=actor.actor_id,
        ),
    )


@router.post(
    "/admin/approvals/requests/{approval_request_id}/decisions",
    response_model=AdminApprovalLifecycleResponse,
    responses=LIFECYCLE_ROUTE_RESPONSES,
    summary="Approve or reject a backend-owned approval request",
)
def decide_admin_approval_request(
    request: Request,
    approval_request_id: Annotated[str, Path(min_length=1)],
    body: AdminApprovalDecisionRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        AdminApiApprovalLifecycleService,
        Depends(get_approval_lifecycle_service),
    ],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    approval_store: Annotated[FileAdminApiApprovalStore, Depends(get_approval_store)],
) -> JSONResponse:
    endpoint = f"{request.method} {request.url.path}"
    payload_hash = _approval_payload_hash(
        endpoint=endpoint,
        actor=actor,
        operator_intent=operator_intent,
        body=body.model_dump(mode="json"),
        path_params={"approval_request_id": approval_request_id},
    )
    return _execute_idempotent_lifecycle(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        required_permission=AdminApiPermission.APPROVAL_MANAGE,
        service_method="decide_approval_request",
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        operation=lambda: service.decide_request(
            store=approval_store,
            approval_request_id=approval_request_id,
            body=body,
            actor_id=actor.actor_id,
        ),
    )


@router.post(
    "/admin/approvals/{approval_id}/revoke",
    response_model=AdminApprovalLifecycleResponse,
    responses=LIFECYCLE_ROUTE_RESPONSES,
    summary="Revoke a backend-owned approval snapshot",
)
def revoke_admin_approval(
    request: Request,
    approval_id: Annotated[str, Path(min_length=1)],
    body: AdminApprovalRevokeRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        AdminApiApprovalLifecycleService,
        Depends(get_approval_lifecycle_service),
    ],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    approval_store: Annotated[FileAdminApiApprovalStore, Depends(get_approval_store)],
) -> JSONResponse:
    endpoint = f"{request.method} {request.url.path}"
    payload_hash = _approval_payload_hash(
        endpoint=endpoint,
        actor=actor,
        operator_intent=operator_intent,
        body=body.model_dump(mode="json"),
        path_params={"approval_id": approval_id},
    )
    return _execute_idempotent_lifecycle(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        required_permission=AdminApiPermission.APPROVAL_MANAGE,
        service_method="revoke_approval",
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        operation=lambda: service.revoke_approval(
            store=approval_store,
            approval_id=approval_id,
            actor_id=actor.actor_id,
            reason=body.revoke_reason,
        ),
    )
