"""Admin API read-only association, health, RBAC, and fixture routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from application.admin_api.auth import (
    ROLE_PERMISSIONS,
    get_authenticated_actor,
    require_permission,
)
from application.admin_api.models import (
    AdminApiActor,
    AdminApiErrorResponse,
    AdminBootstrapResponse,
    AdminCapabilityRegistryResponse,
    AdminCsrfContractResponse,
    AdminFrontendFixturesResponse,
    AdminGateReadResponse,
    AdminHealthResponse,
    AdminOidcJwtReadinessResponse,
    AdminSessionResponse,
)
from application.admin_api.read_service import AdminApiReadService
from core.enums import AdminApiPermission


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
