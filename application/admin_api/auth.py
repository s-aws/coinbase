"""Fail-closed Admin API authentication and RBAC helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Annotated, Mapping

from fastapi import Header, HTTPException, status

from core.enums import (
    AdminApiAuthMode,
    AdminApiPermission,
    AdminApiRole,
    AdminApiVerifierReadinessStatus,
)

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

_OIDC_JWT_REQUIRED_ENV_VARS = (
    "COINBASE_ADMIN_API_OIDC_ISSUER",
    "COINBASE_ADMIN_API_OIDC_AUDIENCE",
    "COINBASE_ADMIN_API_OIDC_JWKS_URL",
)

_OIDC_JWT_CLAIMS_CONTRACT = {
    "subject": "sub",
    "email": "email",
    "roles": "roles",
    "issuer": "iss",
    "audience": "aud",
}

_OIDC_JWT_NOT_IMPLEMENTED_REASON = "Admin API OIDC/JWT verifier is not implemented"


@dataclass(frozen=True)
class OidcJwtReadiness:
    """Machine-readable readiness evidence for the future OIDC/JWT verifier."""

    mode: AdminApiAuthMode
    status: AdminApiVerifierReadinessStatus
    verifier_implemented: bool
    required_env_vars: tuple[str, ...]
    missing_env_vars: tuple[str, ...]
    claims_contract: Mapping[str, str]
    failure_reason: str
    live_coinbase_execution: str
    notional_usdc: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe readiness payload for docs and release artifacts."""

        return {
            "mode": self.mode.value,
            "status": self.status.value,
            "verifier_implemented": self.verifier_implemented,
            "required_env_vars": list(self.required_env_vars),
            "missing_env_vars": list(self.missing_env_vars),
            "claims_contract": dict(self.claims_contract),
            "failure_reason": self.failure_reason,
            "live_coinbase_execution": self.live_coinbase_execution,
            "notional_usdc": self.notional_usdc,
        }


def oidc_jwt_required_env_vars() -> tuple[str, ...]:
    """Return the required backend settings for the future OIDC/JWT verifier."""

    return _OIDC_JWT_REQUIRED_ENV_VARS


def build_oidc_jwt_readiness(
    env: Mapping[str, str | None] | None = None,
) -> OidcJwtReadiness:
    """Build fail-closed OIDC/JWT verifier readiness evidence.

    The verifier is intentionally not implemented yet. Supplying all required
    configuration removes env gaps but does not change the blocked status.
    """

    source = os.environ if env is None else env
    missing_env_vars = tuple(
        key for key in _OIDC_JWT_REQUIRED_ENV_VARS if not _read_config_value(source, key)
    )
    return OidcJwtReadiness(
        mode=AdminApiAuthMode.OIDC_JWT,
        status=AdminApiVerifierReadinessStatus.BLOCKED,
        verifier_implemented=False,
        required_env_vars=_OIDC_JWT_REQUIRED_ENV_VARS,
        missing_env_vars=missing_env_vars,
        claims_contract=_OIDC_JWT_CLAIMS_CONTRACT,
        failure_reason=_OIDC_JWT_NOT_IMPLEMENTED_REASON,
        live_coinbase_execution="not_run",
        notional_usdc="0",
    )


def _read_config_value(source: Mapping[str, str | None], key: str) -> str | None:
    value = source.get(key)
    value = value.strip() if value else ""
    return value or None


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
    readiness = build_oidc_jwt_readiness()
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=readiness.failure_reason,
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
