"""Fail-closed Admin API authentication and RBAC helpers."""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import Header, HTTPException, status

from core.enums import AdminApiAuthMode, AdminApiPermission, AdminApiRole

from .models import AdminApiActor


ROLE_PERMISSIONS: dict[AdminApiRole, frozenset[AdminApiPermission]] = {
    AdminApiRole.VIEWER: frozenset({
        AdminApiPermission.ANALYTICS_READ,
        AdminApiPermission.AUDIT_READ,
        AdminApiPermission.CAMPAIGN_READ,
    }),
    AdminApiRole.OPERATOR: frozenset({
        AdminApiPermission.ANALYTICS_READ,
        AdminApiPermission.AUDIT_READ,
        AdminApiPermission.CAMPAIGN_READ,
        AdminApiPermission.RUNTIME_PAUSE,
        AdminApiPermission.RUNTIME_RESUME,
    }),
    AdminApiRole.TRADER: frozenset({
        AdminApiPermission.ANALYTICS_READ,
        AdminApiPermission.AUDIT_READ,
        AdminApiPermission.ORDER_CREATE,
        AdminApiPermission.ORDER_CANCEL,
        AdminApiPermission.CAMPAIGN_READ,
        AdminApiPermission.CAMPAIGN_EXECUTE,
        AdminApiPermission.RUNTIME_PAUSE,
        AdminApiPermission.RUNTIME_RESUME,
    }),
    AdminApiRole.ADMIN: frozenset(AdminApiPermission),
    AdminApiRole.AUDITOR: frozenset({
        AdminApiPermission.ANALYTICS_READ,
        AdminApiPermission.AUDIT_READ,
        AdminApiPermission.CAMPAIGN_READ,
    }),
    AdminApiRole.EMERGENCY: frozenset({
        AdminApiPermission.ANALYTICS_READ,
        AdminApiPermission.AUDIT_READ,
        AdminApiPermission.RUNTIME_PAUSE,
        AdminApiPermission.RUNTIME_SHUTDOWN,
    }),
}


def _configured_bearer_token() -> str | None:
    token = os.environ.get("COINBASE_ADMIN_API_BEARER_TOKEN")
    token = token.strip() if token else ""
    return token or None


def configured_auth_mode() -> AdminApiAuthMode:
    """Return the configured Admin API auth verifier mode."""

    raw_mode = os.environ.get(
        "COINBASE_ADMIN_API_AUTH_MODE",
        AdminApiAuthMode.BOOTSTRAP_BEARER.value,
    )
    mode = raw_mode.strip() if raw_mode else AdminApiAuthMode.BOOTSTRAP_BEARER.value
    try:
        return AdminApiAuthMode(mode)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Unsupported Admin API auth mode: {mode}",
        ) from exc


def _parse_roles(raw_roles: str | None) -> list[AdminApiRole]:
    roles: list[AdminApiRole] = []
    for raw_role in (raw_roles or "").split(","):
        role_text = raw_role.strip()
        if not role_text:
            continue
        try:
            roles.append(AdminApiRole(role_text))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Unknown Admin API role: {role_text}",
            ) from exc
    return roles


def actor_has_permission(actor: AdminApiActor, permission: AdminApiPermission) -> bool:
    """Return whether any backend-recognized role grants ``permission``."""

    granted: set[AdminApiPermission] = set()
    for role in actor.roles:
        granted.update(ROLE_PERMISSIONS.get(role, frozenset()))
    return permission in granted


def require_permission(actor: AdminApiActor, permission: AdminApiPermission) -> None:
    """Raise a 403 when ``actor`` lacks ``permission``."""

    if actor_has_permission(actor, permission):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Missing required permission: {permission.value}",
    )


def _get_bootstrap_bearer_actor(
    *,
    authorization: str | None,
    actor_id: str | None,
    roles: str | None,
) -> AdminApiActor:
    configured_token = _configured_bearer_token()
    if configured_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin API auth verifier is not configured",
        )

    expected = f"Bearer {configured_token}"
    if authorization != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Admin API bearer token",
        )

    actor_text = (actor_id or "").strip()
    if not actor_text:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Admin API actor identity",
        )

    parsed_roles = _parse_roles(roles)
    if not parsed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing Admin API role evidence",
        )

    return AdminApiActor(actor_id=actor_text, roles=parsed_roles)


def _get_oidc_jwt_actor() -> AdminApiActor:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Admin API OIDC/JWT verifier is not implemented",
    )


def get_authenticated_actor(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    actor_id: Annotated[str | None, Header(alias="X-Admin-Actor")] = None,
    roles: Annotated[str | None, Header(alias="X-Admin-Roles")] = None,
) -> AdminApiActor:
    """Authenticate an Admin API actor.

    This dependency is the single verifier boundary used by Admin API routes.
    Bootstrap bearer mode is active for local integration. OIDC/JWT mode is
    modeled as a fail-closed adapter until production verification is wired.
    """

    mode = configured_auth_mode()
    if mode == AdminApiAuthMode.BOOTSTRAP_BEARER:
        return _get_bootstrap_bearer_actor(
            authorization=authorization,
            actor_id=actor_id,
            roles=roles,
        )
    if mode == AdminApiAuthMode.OIDC_JWT:
        return _get_oidc_jwt_actor()
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Admin API auth verifier is not configured",
    )
