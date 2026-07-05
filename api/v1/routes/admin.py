"""Admin API read-only association, health, RBAC, and fixture routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Header, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from application.admin_api.auth import (
    ROLE_PERMISSIONS,
    get_authenticated_actor,
    require_permission,
)
from application.admin_api.models import (
    AdminApiActor,
    AdminAccountManagementReadResponse,
    AdminAuditWorkbenchReadResponse,
    AdminFeesReadResponse,
    AdminApiErrorResponse,
    AdminBootstrapResponse,
    AdminCapabilityRegistryResponse,
    AdminCsrfContractResponse,
    AdminEnterpriseReadinessResponse,
    AdminFrontendFixturesResponse,
    AdminGateReadResponse,
    AdminHealthResponse,
    AdminLiveEnablementReadResponse,
    AdminOidcJwtReadinessResponse,
    AdminProductsReadResponse,
    AdminProductsRefreshRequest,
    AdminProductsRefreshResponse,
    AdminWalletReadResponse,
    AdminRiskPolicyReadResponse,
    AdminRuntimeControlRequest,
    AdminRuntimeControlResponse,
    AdminRuntimeStatusResponse,
    AdminSessionResponse,
)
from application.admin_api.mvp_service import AdminMvpRequestContext, get_admin_mvp_service
from application.admin_api.read_service import AdminApiReadService
from core.enums import AdminApiPermission, AdminAuditWorkbenchModule
from core.runtime_controller import get_runtime_controller


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


def get_read_service() -> AdminApiReadService:
    """Return the read-only Admin API status service."""

    return AdminApiReadService()


def _read_response(payload: object) -> JSONResponse:
    return JSONResponse(content=jsonable_encoder(payload))


def _permissions_for_actor(actor: AdminApiActor) -> list[AdminApiPermission]:
    permissions: set[AdminApiPermission] = set()
    for role in actor.roles:
        permissions.update(ROLE_PERMISSIONS.get(role, frozenset()))
    return sorted(permissions, key=lambda permission: permission.value)


def _runtime_status_response() -> AdminRuntimeStatusResponse:
    controller = get_runtime_controller()
    inflight = controller.inflight_snapshot()
    return AdminRuntimeStatusResponse(
        state=controller.state,
        admitting=controller.is_admitting(),
        stopping=controller.is_stopping(),
        total_inflight=sum(inflight.values()),
        inflight=inflight,
    )


def _admin_mvp_context(
    actor: AdminApiActor,
    *,
    idempotency_key: str | None,
    correlation_id: str | None,
    operator_intent: str | None,
) -> AdminMvpRequestContext:
    return AdminMvpRequestContext(
        idempotency_key=(idempotency_key or "admin-api-read").strip() or "admin-api-read",
        correlation_id=(correlation_id or "admin-api-correlation").strip()
        or "admin-api-correlation",
        operator_intent=(operator_intent or "read_admin_api").strip() or "read_admin_api",
        actor_id=actor.actor_id,
        roles=tuple(role.value for role in actor.roles),
    )


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


@router.get(
    "/admin/runtime",
    response_model=AdminRuntimeStatusResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Read backend runtime lifecycle status",
)
def admin_runtime(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _read_response(_runtime_status_response())


@router.post(
    "/admin/runtime/pause",
    response_model=AdminRuntimeControlResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Pause backend runtime admission",
)
def admin_runtime_pause(
    body: Annotated[AdminRuntimeControlRequest, Body(default_factory=AdminRuntimeControlRequest)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.RUNTIME_PAUSE)
    result = get_admin_mvp_service().control_runtime(
        "pause",
        body.model_dump(mode="json", exclude_none=True),
        _admin_mvp_context(
            actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            operator_intent=operator_intent,
        ),
    )
    return JSONResponse(
        status_code=result.status_code,
        content=jsonable_encoder(result.body),
        headers=result.headers,
    )


@router.post(
    "/admin/runtime/resume",
    response_model=AdminRuntimeControlResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Resume backend runtime admission",
)
def admin_runtime_resume(
    body: Annotated[AdminRuntimeControlRequest, Body(default_factory=AdminRuntimeControlRequest)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.RUNTIME_RESUME)
    result = get_admin_mvp_service().control_runtime(
        "resume",
        body.model_dump(mode="json", exclude_none=True),
        _admin_mvp_context(
            actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            operator_intent=operator_intent,
        ),
    )
    return JSONResponse(
        status_code=result.status_code,
        content=jsonable_encoder(result.body),
        headers=result.headers,
    )


@router.post(
    "/admin/runtime/shutdown",
    response_model=AdminRuntimeControlResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Request backend runtime shutdown",
)
def admin_runtime_shutdown(
    body: Annotated[AdminRuntimeControlRequest, Body(default_factory=AdminRuntimeControlRequest)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.RUNTIME_SHUTDOWN)
    result = get_admin_mvp_service().control_runtime(
        "shutdown",
        body.model_dump(mode="json", exclude_none=True),
        _admin_mvp_context(
            actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            operator_intent=operator_intent,
        ),
    )
    return JSONResponse(
        status_code=result.status_code,
        content=jsonable_encoder(result.body),
        headers=result.headers,
    )


@router.get(
    "/admin/account-management",
    response_model=AdminAccountManagementReadResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Read backend-owned Account Management reality",
)
def admin_account_management(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    correlation_id: Annotated[str | None, Header(alias="X-Correlation-Id")] = None,
    operator_intent: Annotated[str | None, Header(alias="X-Operator-Intent")] = None,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    result = get_admin_mvp_service().get_read_response(
        "/api/v1/admin/account-management",
        {},
        _admin_mvp_context(
            actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            operator_intent=operator_intent or "read_account_management",
        ),
    )
    return JSONResponse(
        status_code=result.status_code,
        content=jsonable_encoder(result.body),
        headers=result.headers,
    )


@router.get(
    "/admin/wallet",
    response_model=AdminWalletReadResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Read backend-owned wallet inventory and admission inputs",
)
def admin_wallet(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    correlation_id: Annotated[str | None, Header(alias="X-Correlation-Id")] = None,
    operator_intent: Annotated[str | None, Header(alias="X-Operator-Intent")] = None,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    result = get_admin_mvp_service().get_read_response(
        "/api/v1/admin/wallet",
        {},
        _admin_mvp_context(
            actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            operator_intent=operator_intent or "read_admin_wallet",
        ),
    )
    return JSONResponse(
        status_code=result.status_code,
        content=jsonable_encoder(result.body),
        headers=result.headers,
    )


@router.get(
    "/admin/fees",
    response_model=AdminFeesReadResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Read backend-owned fee evidence",
)
def admin_fees(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    correlation_id: Annotated[str | None, Header(alias="X-Correlation-Id")] = None,
    operator_intent: Annotated[str | None, Header(alias="X-Operator-Intent")] = None,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    result = get_admin_mvp_service().get_read_response(
        "/api/v1/admin/fees",
        {},
        _admin_mvp_context(
            actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            operator_intent=operator_intent or "read_admin_fees",
        ),
    )
    return JSONResponse(
        status_code=result.status_code,
        content=jsonable_encoder(result.body),
        headers=result.headers,
    )


@router.get(
    "/admin/products",
    response_model=AdminProductsReadResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Read backend-owned Coinbase product metadata",
)
def admin_products(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    product_id: Annotated[list[str] | None, Query()] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    correlation_id: Annotated[str | None, Header(alias="X-Correlation-Id")] = None,
    operator_intent: Annotated[str | None, Header(alias="X-Operator-Intent")] = None,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    query = {"product_id": product_id} if product_id else {}
    result = get_admin_mvp_service().get_read_response(
        "/api/v1/admin/products",
        query,
        _admin_mvp_context(
            actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            operator_intent=operator_intent or "read_admin_products",
        ),
    )
    return JSONResponse(
        status_code=result.status_code,
        content=jsonable_encoder(result.body),
        headers=result.headers,
    )


@router.post(
    "/admin/products/refresh",
    response_model=AdminProductsRefreshResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Refresh backend-owned local product metadata",
)
def refresh_admin_products(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    body: Annotated[AdminProductsRefreshRequest, Body(default_factory=AdminProductsRefreshRequest)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    correlation_id: Annotated[str | None, Header(alias="X-Correlation-Id")] = None,
    operator_intent: Annotated[str | None, Header(alias="X-Operator-Intent")] = None,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.CONFIG_UPDATE)
    result = get_admin_mvp_service().refresh_admin_products(
        body.model_dump(mode="json", exclude_none=True),
        _admin_mvp_context(
            actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            operator_intent=operator_intent or "refresh_admin_products",
        ),
    )
    return JSONResponse(
        status_code=result.status_code,
        content=jsonable_encoder(result.body),
        headers=result.headers,
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
