"""Run no-live Admin API OIDC/JWT readiness smoke checks."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Iterator, MutableMapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT_PATH = str(PROJECT_ROOT)
sys.path = [path for path in sys.path if path != PROJECT_ROOT_PATH]
sys.path.insert(0, PROJECT_ROOT_PATH)

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm

from api.v1.app import create_app
from application.admin_api.auth import oidc_jwt_required_env_vars
from core.enums import (
    AdminApiAuthMode,
    AdminApiGateStatus,
    AdminApiRole,
    AdminApiVerifierReadinessStatus,
)


SUMMARY_PREFIX = "ADMIN_OIDC_READINESS_SMOKE_SUMMARY "
BOOTSTRAP_TOKEN = "admin-oidc-readiness-smoke-token"
OIDC_ISSUER = "https://issuer.admin-smoke.example.test"
OIDC_AUDIENCE = "coinbase-admin-api"
OIDC_SUBJECT = "oidc-smoke-viewer"


@dataclass(frozen=True)
class SmokeStep:
    """One smoke check result."""

    name: str
    passed: bool
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "evidence": self.evidence,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run no-live Admin API OIDC/JWT readiness checks with local "
            "TestClient and temporary JWKS evidence."
        )
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print only the machine-readable summary line.",
    )
    return parser


def build_admin_oidc_readiness_smoke_summary() -> dict[str, Any]:
    """Return a no-live OIDC readiness smoke summary."""

    with tempfile.TemporaryDirectory(prefix="admin-oidc-smoke-") as tmpdir:
        private_key, jwks = _oidc_keypair()
        jwks_path = Path(tmpdir) / "jwks.json"
        jwks_path.write_text(json.dumps(jwks), encoding="utf-8")
        jwks_url = jwks_path.resolve().as_uri()

        steps = [
            _run_missing_config_readiness_step(),
            _run_configured_readiness_step(jwks_url=jwks_url),
            _run_oidc_claim_session_step(
                jwks_url=jwks_url,
                token=_oidc_token(private_key),
            ),
        ]

    passed = all(step.passed for step in steps)
    return {
        "status": (
            AdminApiGateStatus.PASSED.value
            if passed
            else AdminApiGateStatus.BLOCKED.value
        ),
        "live_coinbase_orders_ran": False,
        "live_order_notional_usdc": "0",
        "step_count": len(steps),
        "steps": [step.to_dict() for step in steps],
    }


def _run_missing_config_readiness_step() -> SmokeStep:
    with _patched_environment(_bootstrap_env(clear_oidc=True)):
        client = TestClient(create_app())
        response = client.get(
            "/api/v1/admin/oidc-readiness",
            headers=_bootstrap_headers(),
        )
        payload = response.json()
    passed = (
        response.status_code == 200
        and payload.get("status") == AdminApiVerifierReadinessStatus.BLOCKED.value
        and payload.get("missing_env_vars") == list(oidc_jwt_required_env_vars())
        and payload.get("live_coinbase_orders_ran") is False
        and payload.get("notional_usdc") == "0"
    )
    return SmokeStep(
        name="missing_config_readiness_blocks",
        passed=passed,
        evidence={
            "http_status": response.status_code,
            "readiness_status": payload.get("status"),
            "missing_env_vars": payload.get("missing_env_vars"),
            "live_coinbase_orders_ran": payload.get("live_coinbase_orders_ran"),
            "notional_usdc": payload.get("notional_usdc"),
        },
    )


def _run_configured_readiness_step(*, jwks_url: str) -> SmokeStep:
    with _patched_environment(_bootstrap_env(jwks_url=jwks_url)):
        client = TestClient(create_app())
        response = client.get(
            "/api/v1/admin/oidc-readiness",
            headers=_bootstrap_headers(),
        )
        payload = response.json()
    passed = (
        response.status_code == 200
        and payload.get("status") == AdminApiVerifierReadinessStatus.READY.value
        and payload.get("missing_env_vars") == []
        and payload.get("jwks_reachability") == "reachable"
        and payload.get("live_coinbase_orders_ran") is False
        and payload.get("notional_usdc") == "0"
    )
    return SmokeStep(
        name="configured_readiness_reports_reachable_jwks",
        passed=passed,
        evidence={
            "http_status": response.status_code,
            "readiness_status": payload.get("status"),
            "jwks_reachability": payload.get("jwks_reachability"),
            "live_coinbase_orders_ran": payload.get("live_coinbase_orders_ran"),
            "notional_usdc": payload.get("notional_usdc"),
        },
    )


def _run_oidc_claim_session_step(*, jwks_url: str, token: str) -> SmokeStep:
    with _patched_environment(_oidc_env(jwks_url=jwks_url)):
        client = TestClient(create_app())
        response = client.get(
            "/api/v1/admin/session",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Admin-Actor": "forged-browser-actor",
                "X-Admin-Roles": AdminApiRole.ADMIN.value,
            },
        )
        payload = response.json()
    actor = payload.get("actor") if isinstance(payload, dict) else {}
    passed = (
        response.status_code == 200
        and actor.get("actor_id") == OIDC_SUBJECT
        and actor.get("roles") == [AdminApiRole.VIEWER.value]
        and payload.get("auth_mode") == AdminApiAuthMode.OIDC_JWT.value
        and payload.get("live_coinbase_orders_ran") is False
    )
    return SmokeStep(
        name="oidc_session_uses_verified_claim_roles",
        passed=passed,
        evidence={
            "http_status": response.status_code,
            "actor_id": actor.get("actor_id"),
            "roles": actor.get("roles"),
            "auth_mode": payload.get("auth_mode") if isinstance(payload, dict) else None,
            "live_coinbase_orders_ran": (
                payload.get("live_coinbase_orders_ran")
                if isinstance(payload, dict)
                else None
            ),
        },
    )


def _bootstrap_env(
    *,
    jwks_url: str | None = None,
    clear_oidc: bool = False,
) -> dict[str, str | None]:
    env: dict[str, str | None] = {
        "COINBASE_ADMIN_API_AUTH_MODE": AdminApiAuthMode.BOOTSTRAP_BEARER.value,
        "COINBASE_ADMIN_API_BEARER_TOKEN": BOOTSTRAP_TOKEN,
    }
    if clear_oidc:
        env.update({key: None for key in oidc_jwt_required_env_vars()})
    if jwks_url is not None:
        env.update({
            "COINBASE_ADMIN_API_OIDC_ISSUER": OIDC_ISSUER,
            "COINBASE_ADMIN_API_OIDC_AUDIENCE": OIDC_AUDIENCE,
            "COINBASE_ADMIN_API_OIDC_JWKS_URL": jwks_url,
        })
    return env


def _oidc_env(*, jwks_url: str) -> dict[str, str | None]:
    return {
        "COINBASE_ADMIN_API_AUTH_MODE": AdminApiAuthMode.OIDC_JWT.value,
        "COINBASE_ADMIN_API_BEARER_TOKEN": None,
        "COINBASE_ADMIN_API_OIDC_ISSUER": OIDC_ISSUER,
        "COINBASE_ADMIN_API_OIDC_AUDIENCE": OIDC_AUDIENCE,
        "COINBASE_ADMIN_API_OIDC_JWKS_URL": jwks_url,
    }


def _bootstrap_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {BOOTSTRAP_TOKEN}",
        "X-Admin-Actor": "admin-oidc-smoke",
        "X-Admin-Roles": AdminApiRole.VIEWER.value,
    }


def _oidc_keypair(kid: str = "admin-oidc-smoke-key") -> tuple[Any, dict[str, Any]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk["kid"] = kid
    jwk["alg"] = "RS256"
    jwk["use"] = "sig"
    return private_key, {"keys": [jwk]}


def _oidc_token(private_key: Any, kid: str = "admin-oidc-smoke-key") -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": OIDC_SUBJECT,
            "email": f"{OIDC_SUBJECT}@example.test",
            "roles": [AdminApiRole.VIEWER.value],
            "iss": OIDC_ISSUER,
            "aud": OIDC_AUDIENCE,
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )


@contextmanager
def _patched_environment(
    updates: MutableMapping[str, str | None],
) -> Iterator[None]:
    original = {key: os.environ.get(key) for key in updates}
    try:
        for key, value in updates.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = build_admin_oidc_readiness_smoke_summary()
    if not args.summary_only:
        print("Admin API OIDC/JWT readiness smoke complete")
        print("Live Coinbase execution: not run; notional $0")
    print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
    return 0 if summary["status"] == AdminApiGateStatus.PASSED.value else 1


if __name__ == "__main__":
    raise SystemExit(main())
