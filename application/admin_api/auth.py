"""Fail-closed Admin API authentication and RBAC helpers."""

from __future__ import annotations

import os
import json
from dataclasses import dataclass
from typing import Annotated, Mapping
from urllib.error import URLError
from urllib.request import urlopen

import jwt
from fastapi import Header, HTTPException, status
from jwt import (
    DecodeError,
    ExpiredSignatureError,
    InvalidAudienceError,
    InvalidIssuerError,
    MissingRequiredClaimError,
    InvalidSignatureError,
    PyJWTError,
)
from jwt.algorithms import RSAAlgorithm

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

_OIDC_JWT_NOT_CONFIGURED_REASON = "Admin API OIDC/JWT verifier is not configured"
_OIDC_JWT_ALGORITHMS = ("RS256",)


class OidcJwtVerificationError(ValueError):
    """Raised when OIDC/JWT verification fails closed."""


@dataclass(frozen=True)
class OidcJwtReadiness:
    """Machine-readable readiness evidence for the OIDC/JWT verifier."""

    mode: AdminApiAuthMode
    status: AdminApiVerifierReadinessStatus
    verifier_implemented: bool
    required_env_vars: tuple[str, ...]
    missing_env_vars: tuple[str, ...]
    claims_contract: Mapping[str, str]
    failure_reason: str | None
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
    """Return the required backend settings for the OIDC/JWT verifier."""

    return _OIDC_JWT_REQUIRED_ENV_VARS


def check_oidc_jwks_reachability(
    env: Mapping[str, str | None] | None = None,
) -> tuple[str, str | None]:
    """Return JWKS reachability evidence for release/readiness checks."""

    source = os.environ if env is None else env
    jwks_url = _read_config_value(source, "COINBASE_ADMIN_API_OIDC_JWKS_URL")
    if not jwks_url:
        return "not_checked", _OIDC_JWT_NOT_CONFIGURED_REASON
    try:
        _fetch_oidc_jwks(jwks_url)
    except OidcJwtVerificationError as exc:
        return "unreachable", str(exc)
    return "reachable", None


def build_oidc_jwt_readiness(
    env: Mapping[str, str | None] | None = None,
) -> OidcJwtReadiness:
    """Build OIDC/JWT verifier readiness evidence."""

    source = os.environ if env is None else env
    missing_env_vars = tuple(
        key for key in _OIDC_JWT_REQUIRED_ENV_VARS if not _read_config_value(source, key)
    )
    status_value = (
        AdminApiVerifierReadinessStatus.BLOCKED
        if missing_env_vars
        else AdminApiVerifierReadinessStatus.READY
    )
    return OidcJwtReadiness(
        mode=AdminApiAuthMode.OIDC_JWT,
        status=status_value,
        verifier_implemented=True,
        required_env_vars=_OIDC_JWT_REQUIRED_ENV_VARS,
        missing_env_vars=missing_env_vars,
        claims_contract=_OIDC_JWT_CLAIMS_CONTRACT,
        failure_reason=_OIDC_JWT_NOT_CONFIGURED_REASON if missing_env_vars else None,
        live_coinbase_execution="not_run",
        notional_usdc="0",
    )


def _read_config_value(source: Mapping[str, str | None], key: str) -> str | None:
    value = source.get(key)
    value = value.strip() if value else ""
    return value or None


def verify_oidc_jwt(
    token: str,
    *,
    env: Mapping[str, str | None] | None = None,
    jwks: Mapping[str, object] | None = None,
) -> AdminApiActor:
    """Verify an OIDC/JWT bearer token and return backend actor evidence."""

    source = os.environ if env is None else env
    readiness = build_oidc_jwt_readiness(source)
    if readiness.status != AdminApiVerifierReadinessStatus.READY:
        raise OidcJwtVerificationError(_OIDC_JWT_NOT_CONFIGURED_REASON)

    issuer = _read_config_value(source, "COINBASE_ADMIN_API_OIDC_ISSUER")
    audience = _read_config_value(source, "COINBASE_ADMIN_API_OIDC_AUDIENCE")
    jwks_url = _read_config_value(source, "COINBASE_ADMIN_API_OIDC_JWKS_URL")
    if not issuer or not audience or not jwks_url:
        raise OidcJwtVerificationError(_OIDC_JWT_NOT_CONFIGURED_REASON)

    try:
        header = jwt.get_unverified_header(token)
    except PyJWTError as exc:
        raise OidcJwtVerificationError("Invalid Admin API OIDC/JWT token") from exc

    kid = str(header.get("kid") or "").strip()
    algorithm = str(header.get("alg") or "").strip()
    if algorithm not in _OIDC_JWT_ALGORITHMS:
        raise OidcJwtVerificationError("Unsupported Admin API OIDC/JWT algorithm")

    jwks_payload = jwks if jwks is not None else _fetch_oidc_jwks(jwks_url)
    signing_key = _select_oidc_signing_key(jwks_payload, kid)
    try:
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=list(_OIDC_JWT_ALGORITHMS),
            audience=audience,
            issuer=issuer,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except ExpiredSignatureError as exc:
        raise OidcJwtVerificationError("Expired Admin API OIDC/JWT token") from exc
    except InvalidIssuerError as exc:
        raise OidcJwtVerificationError("Invalid Admin API OIDC/JWT issuer") from exc
    except InvalidAudienceError as exc:
        raise OidcJwtVerificationError("Invalid Admin API OIDC/JWT audience") from exc
    except InvalidSignatureError as exc:
        raise OidcJwtVerificationError("Invalid Admin API OIDC/JWT token") from exc
    except DecodeError as exc:
        raise OidcJwtVerificationError("Invalid Admin API OIDC/JWT token") from exc
    except MissingRequiredClaimError as exc:
        raise OidcJwtVerificationError(
            "Missing required Admin API OIDC/JWT claim",
        ) from exc
    except PyJWTError as exc:
        raise OidcJwtVerificationError("Invalid Admin API OIDC/JWT token") from exc

    return _actor_from_oidc_claims(claims)


def _fetch_oidc_jwks(jwks_url: str) -> Mapping[str, object]:
    try:
        with urlopen(jwks_url, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError) as exc:
        raise OidcJwtVerificationError(
            "Unable to fetch Admin API OIDC/JWT JWKS",
        ) from exc


def _select_oidc_signing_key(jwks: Mapping[str, object], kid: str):
    keys = jwks.get("keys")
    if not isinstance(keys, list):
        raise OidcJwtVerificationError("Invalid Admin API OIDC/JWT JWKS")
    for jwk in keys:
        if not isinstance(jwk, Mapping):
            continue
        if kid and jwk.get("kid") != kid:
            continue
        try:
            return RSAAlgorithm.from_jwk(json.dumps(jwk))
        except (TypeError, ValueError) as exc:
            raise OidcJwtVerificationError(
                "Invalid Admin API OIDC/JWT signing key",
            ) from exc
    raise OidcJwtVerificationError("Admin API OIDC/JWT signing key not found")


def _actor_from_oidc_claims(claims: Mapping[str, object]) -> AdminApiActor:
    subject = str(claims.get("sub") or "").strip()
    if not subject:
        raise OidcJwtVerificationError("Missing Admin API actor identity")

    raw_roles = claims.get("roles")
    if isinstance(raw_roles, str):
        role_values = [role.strip() for role in raw_roles.split(",")]
    elif isinstance(raw_roles, list):
        role_values = [str(role).strip() for role in raw_roles]
    else:
        role_values = []
    role_values = [role for role in role_values if role]
    if not role_values:
        raise OidcJwtVerificationError("Missing Admin API role evidence")

    roles: list[AdminApiRole] = []
    for role_text in role_values:
        try:
            roles.append(AdminApiRole(role_text))
        except ValueError as exc:
            raise OidcJwtVerificationError(
                f"Unknown Admin API role: {role_text}",
            ) from exc
    return AdminApiActor(actor_id=subject, roles=roles)


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


def _get_oidc_jwt_actor(*, authorization: str | None) -> AdminApiActor:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Admin API OIDC/JWT bearer token",
        )
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Admin API OIDC/JWT bearer token",
        )
    try:
        return verify_oidc_jwt(token)
    except OidcJwtVerificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc


def get_authenticated_actor(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    actor_id: Annotated[str | None, Header(alias="X-Admin-Actor")] = None,
    roles: Annotated[str | None, Header(alias="X-Admin-Roles")] = None,
) -> AdminApiActor:
    """Authenticate an Admin API actor.

    This dependency is the single verifier boundary used by Admin API routes.
    Bootstrap bearer mode is active for local integration. OIDC/JWT mode is
    backed by RS256/JWKS verification and derives actor evidence from claims.
    """

    mode = configured_auth_mode()
    if mode == AdminApiAuthMode.BOOTSTRAP_BEARER:
        return _get_bootstrap_bearer_actor(
            authorization=authorization,
            actor_id=actor_id,
            roles=roles,
        )
    if mode == AdminApiAuthMode.OIDC_JWT:
        return _get_oidc_jwt_actor(authorization=authorization)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Admin API auth verifier is not configured",
    )
