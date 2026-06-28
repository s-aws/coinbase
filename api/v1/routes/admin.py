"""Admin API association, health, RBAC, lifecycle, and fixture routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from application.admin_api.audit import AdminApiAuditEvent, FileAdminApiAuditStore
from application.admin_api.auth import (
    ROLE_PERMISSIONS,
    get_authenticated_actor,
    require_permission,
)
from application.admin_api.command_service import AdminApiCommandService
from application.admin_api.idempotency import FileIdempotencyStore, IdempotencyRecord, make_payload_hash
from application.admin_api.models import (
    AdminAccountMarketInventoryResponse,
    AdminApiActor,
    AdminApiCommandResponse,
    AdminAuditWorkbenchReadResponse,
    AdminApiErrorResponse,
    AdminBootstrapResponse,
    AdminCapabilityRegistryResponse,
    AdminCsrfContractResponse,
    AdminEnterpriseReadinessResponse,
    AdminFrontendFixturesResponse,
    AdminGateReadResponse,
    AdminHealthResponse,
    AdminLifecycleCommandRequest,
    AdminLiveEnablementReadResponse,
    AdminOidcJwtReadinessResponse,
    AdminRiskPolicyReadResponse,
    AdminSessionResponse,
)
from application.admin_api.read_service import AdminApiReadService
from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiIdempotencyDecision,
    AdminApiLifecycleAction,
    AdminApiPermission,
    AdminAuditWorkbenchModule,
)
from core.runtime_controller import RuntimeController, get_runtime_controller

from .orders import get_command_service


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

COMMAND_ROUTE_RESPONSES = {
    200: {
        "model": AdminApiCommandResponse,
        "description": "Lifecycle command accepted or idempotently replayed.",
    },
    400: {
        "model": AdminApiCommandResponse,
        "description": "Lifecycle command rejected before runtime transition.",
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
        "model": AdminApiCommandResponse,
        "description": "Idempotency key conflict.",
    },
}


def get_read_service() -> AdminApiReadService:
    """Return the read-only Admin API status service."""

    return AdminApiReadService()


def get_idempotency_store() -> FileIdempotencyStore:
    """Return durable Admin API idempotency storage."""

    return FileIdempotencyStore()


def get_audit_store() -> FileAdminApiAuditStore:
    """Return durable Admin API audit storage."""

    return FileAdminApiAuditStore()


def _read_response(payload: object) -> JSONResponse:
    return JSONResponse(content=jsonable_encoder(payload))


def _http_status_for(response: AdminApiCommandResponse) -> int:
    if response.status == AdminApiCommandStatus.CONFLICT:
        return status.HTTP_409_CONFLICT
    if response.status == AdminApiCommandStatus.REJECTED:
        return status.HTTP_400_BAD_REQUEST
    if response.status == AdminApiCommandStatus.NOT_IMPLEMENTED:
        return status.HTTP_501_NOT_IMPLEMENTED
    return status.HTTP_200_OK


def _command_response(
    response: AdminApiCommandResponse,
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


def _record_lifecycle_audit(
    *,
    audit_store: FileAdminApiAuditStore,
    actor: AdminApiActor,
    endpoint: str,
    request_id: str,
    operator_intent: str,
    response: AdminApiCommandResponse,
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
            status=response.status,
            failure_stage=response.failure_stage,
            message=response.message,
        )
    )


def _execute_lifecycle_command(
    *,
    action: AdminApiLifecycleAction,
    request: Request,
    body: AdminLifecycleCommandRequest,
    idempotency_key: str,
    correlation_id: str,
    operator_intent: str,
    actor: AdminApiActor,
    idempotency_store: FileIdempotencyStore,
    audit_store: FileAdminApiAuditStore,
    controller: RuntimeController,
    service: AdminApiCommandService,
) -> JSONResponse:
    endpoint = f"{request.method} {request.url.path}"
    permission = (
        AdminApiPermission.RUNTIME_PAUSE
        if action == AdminApiLifecycleAction.PAUSE
        else AdminApiPermission.RUNTIME_RESUME
    )
    service_method = (
        "pause_runtime"
        if action == AdminApiLifecycleAction.PAUSE
        else "resume_runtime"
    )
    require_permission(actor, permission)
    payload_hash = make_payload_hash(
        {
            "endpoint": endpoint,
            "actor_id": actor.actor_id,
            "operator_intent": operator_intent,
            "body": body.model_dump(mode="json"),
        }
    )
    check = idempotency_store.evaluate(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
    )
    if check.decision == AdminApiIdempotencyDecision.REPLAY and check.record:
        return _command_response(
            AdminApiCommandResponse.model_validate(dict(check.record.response)),
            replayed=True,
        )
    if check.decision == AdminApiIdempotencyDecision.CONFLICT:
        response = AdminApiCommandResponse(
            status=AdminApiCommandStatus.CONFLICT,
            action_class=AdminApiActionClass.ADMIN_RUNTIME,
            required_permission=permission,
            service_method=service_method,
            message="Idempotency-Key was already used with a different payload.",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            failure_stage="idempotency",
        )
        response.audit_id = _record_lifecycle_audit(
            audit_store=audit_store,
            actor=actor,
            endpoint=endpoint,
            request_id=correlation_id,
            operator_intent=operator_intent,
            response=response,
        )
        return _command_response(response)

    service_command = (
        service.pause_runtime
        if action == AdminApiLifecycleAction.PAUSE
        else service.resume_runtime
    )
    response = service_command(
        body,
        controller=controller,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
    )
    response.audit_id = _record_lifecycle_audit(
        audit_store=audit_store,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        response=response,
    )
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
    return _command_response(response)


def _permissions_for_actor(actor: AdminApiActor) -> list[AdminApiPermission]:
    permissions: set[AdminApiPermission] = set()
    for role in actor.roles:
        permissions.update(ROLE_PERMISSIONS.get(role, frozenset()))
    return sorted(permissions, key=lambda permission: permission.value)


@router.get(
    "/admin/bootstrap",
    response_model=AdminBootstrapResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Read backend association and live-action posture",
)
def admin_bootstrap(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _read_response(service.build_admin_bootstrap())


@router.get(
    "/admin/health",
    response_model=AdminHealthResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Read backend health and route diagnostics",
)
def admin_health(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _read_response(service.build_admin_health())


@router.post(
    "/admin/lifecycle/pause",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Pause runtime order admission through the backend controller",
)
def admin_lifecycle_pause(
    request: Request,
    body: AdminLifecycleCommandRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    idempotency_store: Annotated[
        FileIdempotencyStore,
        Depends(get_idempotency_store),
    ],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    controller: Annotated[RuntimeController, Depends(get_runtime_controller)],
    service: Annotated[AdminApiCommandService, Depends(get_command_service)],
) -> JSONResponse:
    """Pause new runtime order admission without dashboard fallback."""

    return _execute_lifecycle_command(
        action=AdminApiLifecycleAction.PAUSE,
        request=request,
        body=body,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor=actor,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        controller=controller,
        service=service,
    )


@router.post(
    "/admin/lifecycle/resume",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Resume runtime order admission through the backend controller",
)
def admin_lifecycle_resume(
    request: Request,
    body: AdminLifecycleCommandRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    idempotency_store: Annotated[
        FileIdempotencyStore,
        Depends(get_idempotency_store),
    ],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    controller: Annotated[RuntimeController, Depends(get_runtime_controller)],
    service: Annotated[AdminApiCommandService, Depends(get_command_service)],
) -> JSONResponse:
    """Resume runtime order admission without dashboard fallback."""

    return _execute_lifecycle_command(
        action=AdminApiLifecycleAction.RESUME,
        request=request,
        body=body,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor=actor,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        controller=controller,
        service=service,
    )


@router.get(
    "/admin/session",
    response_model=AdminSessionResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Read authenticated actor and RBAC evidence",
)
def admin_session(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    return _read_response(
        service.build_admin_session(
            actor=actor,
            permissions=_permissions_for_actor(actor),
        )
    )


@router.get(
    "/admin/oidc-readiness",
    response_model=AdminOidcJwtReadinessResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Read backend OIDC/JWT verifier readiness evidence",
)
def admin_oidc_readiness(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _read_response(service.build_oidc_jwt_readiness())


@router.get(
    "/admin/capabilities",
    response_model=AdminCapabilityRegistryResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Read backend-owned Admin API capability registry",
)
def admin_capabilities(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _read_response(service.build_admin_capabilities())


@router.get(
    "/admin/csrf",
    response_model=AdminCsrfContractResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Read Admin API CSRF contract without disclosing token values",
)
def admin_csrf_contract(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _read_response(service.build_csrf_contract())


@router.get(
    "/admin/live-enablement",
    response_model=AdminLiveEnablementReadResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Read controlled live-enablement readiness without enabling live execution",
)
def admin_live_enablement(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _read_response(service.build_live_enablement())


@router.get(
    "/admin/account-market-inventory",
    response_model=AdminAccountMarketInventoryResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Read account and market inventory coverage and Release 0.1 gaps",
)
def admin_account_market_inventory(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _read_response(service.build_account_market_inventory())


@router.get(
    "/admin/enterprise-readiness",
    response_model=AdminEnterpriseReadinessResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Read enterprise admin module and release-candidate readiness evidence",
)
def admin_enterprise_readiness(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _read_response(service.build_enterprise_readiness())


@router.get(
    "/admin/guard-risk-policy",
    response_model=AdminRiskPolicyReadResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Read backend-owned guard and risk policy evidence",
)
def admin_guard_risk_policy(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
    product_id: str | None = None,
) -> JSONResponse:
    """Read guard/risk posture without Coinbase reads or command execution."""

    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _read_response(service.build_guard_risk_policy(product_id=product_id))


@router.get(
    "/admin/audit-workbench",
    response_model=AdminAuditWorkbenchReadResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Read cross-module audit and correlation evidence",
)
def admin_audit_workbench(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
    module: AdminAuditWorkbenchModule | None = None,
    product_id: str | None = None,
    client_order_id: str | None = None,
    correlation_id: str | None = None,
    audit_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> JSONResponse:
    """Read normalized audit evidence without Coinbase reads or mutations."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_response(
        service.build_audit_workbench(
            module=module,
            product_id=product_id,
            client_order_id=client_order_id,
            correlation_id=correlation_id,
            audit_id=audit_id,
            limit=limit,
            offset=offset,
        )
    )


@router.get(
    "/admin/release-gate",
    response_model=AdminGateReadResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Read release-gate posture without running tests from the browser",
)
def admin_release_gate(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _read_response(service.build_release_gate())


@router.get(
    "/admin/recovery-gate",
    response_model=AdminGateReadResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Read recovery readiness posture",
)
def admin_recovery_gate(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_response(service.build_recovery_gate())


@router.get(
    "/admin/fill-ledger-health",
    response_model=AdminGateReadResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Read fill-ledger health posture",
)
def admin_fill_ledger_health(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_response(service.build_fill_ledger_health())


@router.get(
    "/admin/frontend-fixtures",
    response_model=AdminFrontendFixturesResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Read backend-owned fixtures for frontend mock synchronization",
)
def admin_frontend_fixtures(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _read_response(service.build_frontend_fixtures())
