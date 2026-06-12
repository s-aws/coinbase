from __future__ import annotations

import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm

from api.v1.app import create_app
from application.admin_api.auth import (
    OidcJwtVerificationError,
    actor_has_permission,
    build_oidc_jwt_readiness,
    oidc_jwt_required_env_vars,
    verify_oidc_jwt,
)
from application.admin_api import command_service
from application.admin_api.audit import FileAdminApiAuditStore
from application.admin_api.idempotency import (
    FileIdempotencyStore,
    IdempotencyRecord,
    evaluate_idempotency,
    make_payload_hash,
)
from application.admin_api.models import AdminApiActor
from application.admin_api.route_inventory import ADMIN_API_ROUTE_INVENTORY
from core.enums import (
    AdminApiActionClass,
    AdminApiAuthMode,
    AdminAuditEvidenceSource,
    AdminAuditWorkbenchModule,
    AdminApiCommandRoutesMode,
    AdminApiCommandStatus,
    AdminApiErrorCode,
    AdminApiGateStatus,
    AdminApiIdempotencyDecision,
    AdminApiModuleSupportStatus,
    AdminApiPermission,
    AdminApiRole,
    AdminApiVerifierReadinessStatus,
)
from tools.generate_admin_api_openapi import generate_openapi_schema
from tools.run_admin_oidc_readiness_smoke import (
    SUMMARY_PREFIX as ADMIN_OIDC_READINESS_SMOKE_SUMMARY_PREFIX,
    build_admin_oidc_readiness_smoke_summary,
    build_parser as build_admin_oidc_readiness_smoke_parser,
)


ROOT = Path(__file__).resolve().parents[2]
OPENAPI_PATH = ROOT / "openapi" / "coinbase-admin-api.yaml"
ROUTE_INVENTORY_DOC = ROOT / "docs" / "plans" / "ADMIN_API_ROUTE_INVENTORY.md"


def _headers(
    *,
    idempotency_key: str = "idem-001",
    operator_intent: str = "manual_one_off",
    roles: str = AdminApiRole.TRADER.value,
) -> dict[str, str]:
    return {
        "Authorization": "Bearer test-admin-token",
        "Idempotency-Key": idempotency_key,
        "X-Correlation-Id": "corr-001",
        "X-Operator-Intent": operator_intent,
        "X-Admin-Actor": "operator-001",
        "X-Admin-Roles": roles,
    }


def _store_dir() -> Path:
    path = ROOT / "runtime_state" / "test_admin_api_contract" / str(uuid4())
    path.mkdir(parents=True, exist_ok=True)
    return path


def _client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from api.v1.routes import orders as order_routes

    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "test-admin-token")
    app = create_app()
    store_dir = _store_dir()
    idempotency_store = FileIdempotencyStore(store_dir / "idempotency.jsonl")
    audit_store = FileAdminApiAuditStore(store_dir / "audit.jsonl")
    app.dependency_overrides[order_routes.get_idempotency_store] = (
        lambda: idempotency_store
    )
    app.dependency_overrides[order_routes.get_audit_store] = lambda: audit_store
    client = TestClient(app)
    client.admin_api_test_store_dir = store_dir
    return client


def _manual_order_payload(quote_size: str = "1.00") -> dict:
    return {
        "product_id": "BTC-USDC",
        "side": "BUY",
        "order_type": "LIMIT",
        "quote_size": quote_size,
        "limit_price": "65000.00",
        "manual_live_acknowledgement": True,
    }


def _oidc_env() -> dict[str, str]:
    return {
        "COINBASE_ADMIN_API_OIDC_ISSUER": "https://issuer.example.test",
        "COINBASE_ADMIN_API_OIDC_AUDIENCE": "coinbase-admin-api",
        "COINBASE_ADMIN_API_OIDC_JWKS_URL": "https://issuer.example.test/jwks.json",
    }


def _oidc_keypair(kid: str = "test-key-1"):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk["kid"] = kid
    jwk["alg"] = "RS256"
    jwk["use"] = "sig"
    return private_key, {"keys": [jwk]}


def _oidc_token(
    private_key,
    *,
    kid: str = "test-key-1",
    issuer: str = "https://issuer.example.test",
    audience: str = "coinbase-admin-api",
    subject: str = "user-oidc-001",
    roles: list[str] | str | None = None,
    expires_delta: timedelta | None = timedelta(minutes=5),
) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": subject,
        "email": f"{subject}@example.test",
        "iss": issuer,
        "aud": audience,
        "iat": now,
    }
    if expires_delta is not None:
        claims["exp"] = now + expires_delta
    if roles is not None:
        claims["roles"] = roles
    return jwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )


@pytest.mark.regression
def test_admin_api_openapi_schema_file_matches_generated_contract():
    generated = generate_openapi_schema(OPENAPI_PATH)
    written = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))

    assert written == generated
    assert "/api/v1/orders" in written["paths"]
    assert "/api/v1/orders/{client_order_id}" in written["paths"]
    assert "/api/v1/orders/{client_order_id}/cancel" in written["paths"]
    assert "/api/v1/stealth/orders" in written["paths"]
    assert "/api/v1/stealth/orders/{stealth_order_id}" in written["paths"]
    assert "/api/v1/stealth/orders/{stealth_order_id}/cancel" in written["paths"]
    assert "/api/v1/movement-repricing/evidence" in written["paths"]
    assert "/api/v1/movement-repricing/orders/{client_order_id}" in written["paths"]
    assert "/api/v1/movement-repricing/stealth/{stealth_order_id}" in written["paths"]
    assert (
        "/api/v1/movement-repricing/stealth/{stealth_order_id}/reprice"
        in written["paths"]
    )
    assert "/api/v1/futures/account" in written["paths"]
    assert "/api/v1/futures/positions" in written["paths"]
    assert "/api/v1/futures/positions/{position_key}" in written["paths"]
    assert "/api/v1/admin/guard-risk-policy" in written["paths"]
    assert "/api/v1/admin/audit-workbench" in written["paths"]
    assert "/api/v1/spot/campaign/executions" in written["paths"]
    assert "/api/v1/admin/bootstrap" in written["paths"]
    assert "/api/v1/admin/health" in written["paths"]
    assert "/api/v1/admin/session" in written["paths"]
    assert "/api/v1/admin/oidc-readiness" in written["paths"]
    assert "/api/v1/admin/capabilities" in written["paths"]
    assert "/api/v1/admin/csrf" in written["paths"]
    assert "/api/v1/admin/live-enablement" in written["paths"]
    assert "/api/v1/admin/enterprise-readiness" in written["paths"]
    assert "/api/v1/admin/release-gate" in written["paths"]
    assert "/api/v1/admin/recovery-gate" in written["paths"]
    assert "/api/v1/admin/fill-ledger-health" in written["paths"]
    assert "/api/v1/admin/frontend-fixtures" in written["paths"]
    assert "/api/v1/spot/readiness" in written["paths"]
    assert "/api/v1/spot/direct-orders/{client_order_id}/audit" in written["paths"]
    assert written["info"]["title"] == "Coinbase Admin API"
    order_operation = written["paths"]["/api/v1/orders"]["post"]
    header_params = {
        param["name"]: param
        for param in order_operation["parameters"]
        if param["in"] == "header"
    }
    assert header_params["Authorization"]["required"] is True
    for header_name in ("X-Admin-Actor", "X-Admin-Roles"):
        assert header_params[header_name]["required"] is False
        assert "bootstrap_bearer" in header_params[header_name]["description"]
        assert "oidc_jwt" in header_params[header_name]["description"]
    for status_code in ("200", "400", "401", "403", "409", "501"):
        assert status_code in order_operation["responses"]
    cancel_operation = written["paths"]["/api/v1/orders/{client_order_id}/cancel"][
        "post"
    ]
    assert "200" in cancel_operation["responses"]
    assert "501" in cancel_operation["responses"]
    stealth_cancel_operation = written["paths"][
        "/api/v1/stealth/orders/{stealth_order_id}/cancel"
    ]["post"]
    assert "200" in stealth_cancel_operation["responses"]
    assert "501" in stealth_cancel_operation["responses"]
    movement_reprice_operation = written["paths"][
        "/api/v1/movement-repricing/stealth/{stealth_order_id}/reprice"
    ]["post"]
    assert "200" in movement_reprice_operation["responses"]
    assert "501" in movement_reprice_operation["responses"]
    campaign_operation = written["paths"]["/api/v1/spot/campaign/executions"]["post"]
    assert "200" in campaign_operation["responses"]
    assert "501" in campaign_operation["responses"]
    spot_readiness_operation = written["paths"]["/api/v1/spot/readiness"]["get"]
    assert "200" in spot_readiness_operation["responses"]
    assert "content" in spot_readiness_operation["responses"]["200"]
    assert "401" in spot_readiness_operation["responses"]
    assert "403" in spot_readiness_operation["responses"]
    order_item_schema = written["components"]["schemas"]["AdminOrderReadItem"]
    assert "client_order_id" in order_item_schema["properties"]
    assert "order_id" not in order_item_schema["properties"]
    assert "exchange_order_id" in order_item_schema["properties"]
    assert "correlation_id" in order_item_schema["properties"]
    assert "audit_id" in order_item_schema["properties"]
    order_list_schema = written["components"]["schemas"]["AdminOrderListResponse"]
    assert "pagination" in order_list_schema["properties"]
    stealth_item_schema = written["components"]["schemas"]["AdminStealthOrderReadItem"]
    assert "stealth_order_id" in stealth_item_schema["properties"]
    assert "active_placement_client_order_id" in stealth_item_schema["properties"]
    assert "active_exchange_order_id" in stealth_item_schema["properties"]
    assert "exchange_order_id_evidence_only" in stealth_item_schema["properties"]
    assert "order_id" not in stealth_item_schema["properties"]
    command_response_schema = written["components"]["schemas"]["AdminApiCommandResponse"]
    assert "stealth_order_id" in command_response_schema["properties"]
    stealth_list_schema = written["components"]["schemas"]["AdminStealthOrderListResponse"]
    assert "pagination" in stealth_list_schema["properties"]
    assert "command_routes_mode" in stealth_list_schema["properties"]
    movement_item_schema = written["components"]["schemas"][
        "AdminMovementRepricingEvidenceItem"
    ]
    assert "client_order_id" in movement_item_schema["properties"]
    assert "original_parent_client_order_id" in movement_item_schema["properties"]
    assert "stealth_order_id" in movement_item_schema["properties"]
    assert "mutation_claims" in movement_item_schema["properties"]
    assert "replacement_slots" in movement_item_schema["properties"]
    assert "active_placement_client_order_id" in movement_item_schema["properties"]
    assert "active_exchange_order_id" in movement_item_schema["properties"]
    assert "exchange_order_id_evidence_only" in movement_item_schema["properties"]
    assert "order_id" not in movement_item_schema["properties"]
    movement_list_schema = written["components"]["schemas"][
        "AdminMovementRepricingListResponse"
    ]
    assert "command_routes_mode" in movement_list_schema["properties"]
    futures_position_schema = written["components"]["schemas"][
        "AdminFuturesPositionReadItem"
    ]
    assert "position_key" in futures_position_schema["properties"]
    assert "product_id" in futures_position_schema["properties"]
    assert "client_order_id" not in futures_position_schema["properties"]
    assert "order_id" not in futures_position_schema["properties"]
    assert "cost_basis" not in futures_position_schema["properties"]
    futures_account_schema = written["components"]["schemas"][
        "AdminFuturesAccountReadResponse"
    ]
    assert "collateral" in futures_account_schema["properties"]
    assert "margin" in futures_account_schema["properties"]
    assert "funding" in futures_account_schema["properties"]
    assert "liquidation" in futures_account_schema["properties"]
    assert "command_routes_mode" in futures_account_schema["properties"]
    risk_policy_schema = written["components"]["schemas"][
        "AdminRiskPolicyReadResponse"
    ]
    assert "action_condition_policy" in risk_policy_schema["properties"]
    assert "configured_limit_rules" in risk_policy_schema["properties"]
    assert "live_execution_gate" in risk_policy_schema["properties"]
    assert "product_capability_policy" in risk_policy_schema["properties"]
    assert "product_capability_decisions" in risk_policy_schema["properties"]
    assert "profitability_policy" in risk_policy_schema["properties"]
    assert "authority_sources" in risk_policy_schema["properties"]
    assert "rejection_categories" in risk_policy_schema["properties"]
    audit_workbench_schema = written["components"]["schemas"][
        "AdminAuditWorkbenchReadResponse"
    ]
    assert "module_summary" in audit_workbench_schema["properties"]
    assert "events" in audit_workbench_schema["properties"]
    audit_event_schema = written["components"]["schemas"][
        "AdminAuditWorkbenchEventItem"
    ]
    assert "client_order_id" in audit_event_schema["properties"]
    assert "exchange_order_id" in audit_event_schema["properties"]
    assert "exchange_order_id_evidence_only" in audit_event_schema["properties"]
    assert "operator_intent" in audit_event_schema["properties"]
    assert "order_id" not in audit_event_schema["properties"]
    spot_readiness_schema = written["components"]["schemas"]["SpotReadinessResponse"]
    assert "products" in spot_readiness_schema["properties"]
    assert "wallet_snapshot" in spot_readiness_schema["properties"]
    spot_pnl_schema = written["components"]["schemas"]["SpotSweepPnlResponse"]
    assert "pnl_report" in spot_pnl_schema["properties"]
    for schema_name, component_schema in written["components"]["schemas"].items():
        enum_values = component_schema.get("enum")
        if enum_values is not None:
            assert len(enum_values) == len(set(enum_values)), schema_name


@pytest.mark.regression
def test_admin_api_mutating_routes_fail_closed_without_auth(monkeypatch):
    monkeypatch.delenv("COINBASE_ADMIN_API_BEARER_TOKEN", raising=False)
    client = _client(monkeypatch)
    monkeypatch.delenv("COINBASE_ADMIN_API_BEARER_TOKEN", raising=False)

    response = client.post(
        "/api/v1/orders",
        headers={k: v for k, v in _headers().items() if k != "Authorization"},
        json=_manual_order_payload(),
    )

    assert response.status_code == 401
    assert response.json()["code"] == AdminApiErrorCode.AUTH_REQUIRED.value
    assert response.headers["x-live-execution-enabled"] == "false"
    assert response.headers["x-correlation-id"]


@pytest.mark.regression
def test_admin_api_oidc_auth_mode_fails_closed_without_required_config(monkeypatch):
    monkeypatch.setenv("COINBASE_ADMIN_API_AUTH_MODE", AdminApiAuthMode.OIDC_JWT.value)
    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "test-admin-token")
    for key in oidc_jwt_required_env_vars():
        monkeypatch.delenv(key, raising=False)
    client = TestClient(create_app())

    response = client.get(
        "/api/v1/admin/bootstrap",
        headers={"Authorization": "Bearer invalid-unverified-token"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == AdminApiErrorCode.AUTH_REQUIRED.value
    assert "OIDC/JWT verifier is not configured" in response.json()["message"]
    assert response.headers["x-live-execution-enabled"] == "false"


@pytest.mark.regression
def test_admin_api_oidc_auth_mode_accepts_valid_jwt_and_uses_claim_roles(
    monkeypatch,
):
    from application.admin_api import auth as auth_module

    private_key, jwks = _oidc_keypair()
    token = _oidc_token(private_key, roles=[AdminApiRole.VIEWER.value])
    monkeypatch.setenv("COINBASE_ADMIN_API_AUTH_MODE", AdminApiAuthMode.OIDC_JWT.value)
    for key, value in _oidc_env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(auth_module, "_fetch_oidc_jwks", lambda _: jwks)
    client = TestClient(create_app())

    response = client.get(
        "/api/v1/admin/session",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Admin-Actor": "forged-browser-actor",
            "X-Admin-Roles": AdminApiRole.ADMIN.value,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["actor"] == {
        "actor_id": "user-oidc-001",
        "roles": [AdminApiRole.VIEWER.value],
    }
    assert payload["auth_mode"] == AdminApiAuthMode.OIDC_JWT.value
    assert payload["bearer_token_visible_to_browser"] is False
    assert AdminApiPermission.ANALYTICS_READ.value in payload["permissions"]
    assert AdminApiPermission.ORDER_CREATE.value not in payload["permissions"]


@pytest.mark.regression
def test_admin_api_oidc_readiness_reports_required_env_and_no_live_boundary(monkeypatch):
    for key in oidc_jwt_required_env_vars():
        monkeypatch.delenv(key, raising=False)

    readiness = build_oidc_jwt_readiness()

    assert readiness.mode == AdminApiAuthMode.OIDC_JWT
    assert readiness.status == AdminApiVerifierReadinessStatus.BLOCKED
    assert readiness.verifier_implemented is True
    assert readiness.required_env_vars == (
        "COINBASE_ADMIN_API_OIDC_ISSUER",
        "COINBASE_ADMIN_API_OIDC_AUDIENCE",
        "COINBASE_ADMIN_API_OIDC_JWKS_URL",
    )
    assert readiness.missing_env_vars == readiness.required_env_vars
    assert readiness.live_coinbase_execution == "not_run"
    assert readiness.notional_usdc == "0"
    assert readiness.to_dict() == {
        "mode": "oidc_jwt",
        "status": "blocked",
        "verifier_implemented": True,
        "required_env_vars": [
            "COINBASE_ADMIN_API_OIDC_ISSUER",
            "COINBASE_ADMIN_API_OIDC_AUDIENCE",
            "COINBASE_ADMIN_API_OIDC_JWKS_URL",
        ],
        "missing_env_vars": [
            "COINBASE_ADMIN_API_OIDC_ISSUER",
            "COINBASE_ADMIN_API_OIDC_AUDIENCE",
            "COINBASE_ADMIN_API_OIDC_JWKS_URL",
        ],
        "claims_contract": {
            "subject": "sub",
            "email": "email",
            "roles": "roles",
            "issuer": "iss",
            "audience": "aud",
        },
        "failure_reason": "Admin API OIDC/JWT verifier is not configured",
        "live_coinbase_execution": "not_run",
        "notional_usdc": "0",
    }

    monkeypatch.setenv("COINBASE_ADMIN_API_OIDC_ISSUER", "https://issuer.example.test")
    monkeypatch.setenv("COINBASE_ADMIN_API_OIDC_AUDIENCE", "coinbase-admin-api")
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OIDC_JWKS_URL",
        "https://issuer.example.test/.well-known/jwks.json",
    )

    configured_readiness = build_oidc_jwt_readiness()

    assert configured_readiness.status == AdminApiVerifierReadinessStatus.READY
    assert configured_readiness.missing_env_vars == ()
    assert configured_readiness.failure_reason is None


@pytest.mark.regression
def test_admin_api_oidc_readiness_route_reports_env_jwks_and_no_live(monkeypatch):
    from application.admin_api import auth as auth_module

    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "test-admin-token")
    for key in oidc_jwt_required_env_vars():
        monkeypatch.delenv(key, raising=False)
    client = TestClient(create_app())

    missing_response = client.get(
        "/api/v1/admin/oidc-readiness",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )

    assert missing_response.status_code == 200
    missing_payload = missing_response.json()
    assert missing_payload["type"] == "admin_oidc_jwt_readiness"
    assert missing_payload["active_auth_mode"] == AdminApiAuthMode.BOOTSTRAP_BEARER.value
    assert missing_payload["mode"] == AdminApiAuthMode.OIDC_JWT.value
    assert missing_payload["status"] == AdminApiVerifierReadinessStatus.BLOCKED.value
    assert missing_payload["verifier_implemented"] is True
    assert missing_payload["missing_env_vars"] == list(oidc_jwt_required_env_vars())
    assert missing_payload["jwks_reachability"] == "not_checked"
    assert missing_payload["live_coinbase_execution"] == "not_run"
    assert missing_payload["notional_usdc"] == "0"
    assert missing_payload["live_coinbase_orders_ran"] is False

    for key, value in _oidc_env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(auth_module, "_fetch_oidc_jwks", lambda _: {"keys": []})

    ready_response = client.get(
        "/api/v1/admin/oidc-readiness",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )

    assert ready_response.status_code == 200
    ready_payload = ready_response.json()
    assert ready_payload["status"] == AdminApiVerifierReadinessStatus.READY.value
    assert ready_payload["missing_env_vars"] == []
    assert ready_payload["failure_reason"] is None
    assert ready_payload["jwks_reachability"] == "reachable"
    assert ready_payload["jwks_failure_reason"] is None


@pytest.mark.regression
def test_admin_api_oidc_verifier_maps_roles_from_jwt_claims():
    private_key, jwks = _oidc_keypair()
    token = _oidc_token(private_key, roles="viewer,trader")

    actor = verify_oidc_jwt(token, env=_oidc_env(), jwks=jwks)

    assert actor.actor_id == "user-oidc-001"
    assert actor.roles == [AdminApiRole.VIEWER, AdminApiRole.TRADER]


@pytest.mark.regression
@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda key: _oidc_token(
                rsa.generate_private_key(public_exponent=65537, key_size=2048),
                roles=[AdminApiRole.VIEWER.value],
            ),
            "Invalid Admin API OIDC/JWT token",
        ),
        (
            lambda key: _oidc_token(
                key,
                issuer="https://wrong-issuer.example.test",
                roles=[AdminApiRole.VIEWER.value],
            ),
            "Invalid Admin API OIDC/JWT issuer",
        ),
        (
            lambda key: _oidc_token(
                key,
                audience="wrong-audience",
                roles=[AdminApiRole.VIEWER.value],
            ),
            "Invalid Admin API OIDC/JWT audience",
        ),
        (
            lambda key: _oidc_token(
                key,
                roles=[AdminApiRole.VIEWER.value],
                expires_delta=timedelta(minutes=-1),
            ),
            "Expired Admin API OIDC/JWT token",
        ),
        (
            lambda key: _oidc_token(key, roles=None),
            "Missing Admin API role evidence",
        ),
        (
            lambda key: _oidc_token(
                key,
                roles=[AdminApiRole.VIEWER.value],
                expires_delta=None,
            ),
            "Missing required Admin API OIDC/JWT claim",
        ),
    ],
)
def test_admin_api_oidc_verifier_fails_closed_for_invalid_tokens(mutator, message):
    private_key, jwks = _oidc_keypair()
    token = mutator(private_key)

    with pytest.raises(OidcJwtVerificationError, match=message):
        verify_oidc_jwt(token, env=_oidc_env(), jwks=jwks)


@pytest.mark.regression
def test_admin_api_oidc_route_fails_closed_when_jwks_fetch_fails(monkeypatch):
    from application.admin_api import auth as auth_module

    private_key, _jwks = _oidc_keypair()
    token = _oidc_token(private_key, roles=[AdminApiRole.VIEWER.value])
    monkeypatch.setenv("COINBASE_ADMIN_API_AUTH_MODE", AdminApiAuthMode.OIDC_JWT.value)
    for key, value in _oidc_env().items():
        monkeypatch.setenv(key, value)

    def _raise_fetch_error(_url: str):
        raise OidcJwtVerificationError("Unable to fetch Admin API OIDC/JWT JWKS")

    monkeypatch.setattr(auth_module, "_fetch_oidc_jwks", _raise_fetch_error)
    client = TestClient(create_app())

    response = client.get(
        "/api/v1/admin/session",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == AdminApiErrorCode.AUTH_REQUIRED.value
    assert "Unable to fetch Admin API OIDC/JWT JWKS" in response.json()["message"]
    assert response.headers["x-live-execution-enabled"] == "false"


@pytest.mark.regression
def test_admin_api_oidc_readiness_smoke_is_no_live_and_covers_required_steps():
    args = build_admin_oidc_readiness_smoke_parser().parse_args(["--summary-only"])

    assert args.summary_only is True
    assert ADMIN_OIDC_READINESS_SMOKE_SUMMARY_PREFIX == (
        "ADMIN_OIDC_READINESS_SMOKE_SUMMARY "
    )

    summary = build_admin_oidc_readiness_smoke_summary()

    assert summary["status"] == AdminApiGateStatus.PASSED.value
    assert summary["live_coinbase_orders_ran"] is False
    assert summary["live_order_notional_usdc"] == "0"
    assert {step["name"] for step in summary["steps"]} == {
        "missing_config_readiness_blocks",
        "configured_readiness_reports_reachable_jwks",
        "oidc_session_uses_verified_claim_roles",
    }
    assert all(step["passed"] is True for step in summary["steps"])


@pytest.mark.regression
def test_admin_api_mutating_routes_fail_closed_on_rbac_denial(monkeypatch):
    client = _client(monkeypatch)

    response = client.post(
        "/api/v1/orders",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
        json=_manual_order_payload(),
    )

    assert response.status_code == 403


@pytest.mark.regression
def test_admin_api_cors_is_limited_to_configured_frontend_origins(monkeypatch):
    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "test-admin-token")
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_CORS_ORIGINS",
        "http://127.0.0.1:3000,https://admin.example.test",
    )
    client = TestClient(create_app())

    allowed = client.options(
        "/api/v1/admin/bootstrap",
        headers={
            "Origin": "http://127.0.0.1:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": (
                "Authorization,X-Admin-Actor,X-Admin-Roles,X-CSRF-Token"
            ),
        },
    )
    denied = client.options(
        "/api/v1/admin/bootstrap",
        headers={
            "Origin": "https://unapproved.example.test",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"
    assert "X-CSRF-Token" in allowed.headers["access-control-allow-headers"]
    assert "access-control-allow-origin" not in denied.headers


@pytest.mark.regression
def test_admin_api_csrf_is_enforced_for_mutations_when_configured(monkeypatch):
    monkeypatch.setenv("COINBASE_ADMIN_API_CSRF_REQUIRED", "true")
    monkeypatch.setenv("COINBASE_ADMIN_API_CSRF_TOKEN", "csrf-test-token")
    client = _client(monkeypatch)

    read_response = client.get(
        "/api/v1/admin/bootstrap",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    missing_csrf = client.post(
        "/api/v1/orders",
        headers=_headers(),
        json=_manual_order_payload(),
    )
    accepted_csrf = client.post(
        "/api/v1/orders",
        headers={**_headers(idempotency_key="idem-csrf-ok"), "X-CSRF-Token": "csrf-test-token"},
        json=_manual_order_payload(),
    )

    assert read_response.status_code == 200
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["code"] == AdminApiErrorCode.PERMISSION_DENIED.value
    assert missing_csrf.headers["x-live-execution-enabled"] == "false"
    assert accepted_csrf.status_code == 501
    assert accepted_csrf.json()["live_exchange_submitted"] is False


@pytest.mark.regression
def test_admin_api_create_manual_order_contract_is_not_implemented_and_not_live(
    monkeypatch,
):
    client = _client(monkeypatch)

    response = client.post(
        "/api/v1/orders",
        headers=_headers(),
        json=_manual_order_payload(),
    )

    assert response.status_code == 501
    payload = response.json()
    assert payload["status"] == AdminApiCommandStatus.NOT_IMPLEMENTED.value
    assert payload["action_class"] == AdminApiActionClass.LIVE_EXCHANGE_PLACE.value
    assert payload["required_permission"] == AdminApiPermission.ORDER_CREATE.value
    assert payload["service_method"] == "place_manual_order"
    assert payload["live_exchange_submitted"] is False
    assert payload["failure_stage"] == "approval"
    assert payload["guard"]["approval_snapshot_required"] is True
    assert payload["guard"]["cap_evaluation_required"] is True
    assert payload["guard"]["live_execution_enabled"] is False
    assert payload["audit_id"]
    assert response.headers["x-correlation-id"] == "corr-001"


@pytest.mark.regression
def test_admin_api_cancel_contract_is_keyed_by_client_order_id(monkeypatch):
    client = _client(monkeypatch)

    response = client.post(
        "/api/v1/orders/client-abc/cancel",
        headers=_headers(),
        json={"reason": "operator_request"},
    )

    assert response.status_code == 501
    payload = response.json()
    assert payload["status"] == AdminApiCommandStatus.NOT_IMPLEMENTED.value
    assert payload["action_class"] == AdminApiActionClass.LIVE_EXCHANGE_CANCEL.value
    assert payload["required_permission"] == AdminApiPermission.ORDER_CANCEL.value
    assert payload["service_method"] == "cancel_order_by_client_order_id"
    assert payload["client_order_id"] == "client-abc"
    assert payload["live_exchange_submitted"] is False
    assert payload["failure_stage"] == "approval"
    assert payload["guard"]["approval_snapshot_required"] is True
    assert payload["guard"]["cap_evaluation_required"] is True


@pytest.mark.regression
def test_admin_api_stealth_cancel_contract_is_keyed_by_stealth_order_id(monkeypatch):
    client = _client(monkeypatch)

    response = client.post(
        "/api/v1/stealth/orders/stealth-abc/cancel",
        headers=_headers(idempotency_key="idem-stealth-cancel"),
        json={"reason": "operator_request"},
    )

    assert response.status_code == 501
    payload = response.json()
    assert payload["status"] == AdminApiCommandStatus.NOT_IMPLEMENTED.value
    assert payload["action_class"] == AdminApiActionClass.LIVE_EXCHANGE_CANCEL.value
    assert payload["required_permission"] == AdminApiPermission.ORDER_CANCEL.value
    assert payload["service_method"] == "cancel_stealth_order_by_stealth_order_id"
    assert payload["client_order_id"] is None
    assert payload["stealth_order_id"] == "stealth-abc"
    assert payload["coinbase_order_id"] is None
    assert payload["live_exchange_submitted"] is False
    assert payload["failure_stage"] == "approval"
    assert payload["guard"]["approval_snapshot_required"] is True
    assert payload["guard"]["cap_evaluation_required"] is True
    assert payload["data"]["identity_key"] == "stealth_order_id"
    assert payload["data"]["active_placement_client_order_id"] is None
    assert payload["data"]["exchange_order_id_evidence_only"] is True


@pytest.mark.regression
def test_admin_api_movement_reprice_contract_is_keyed_by_stealth_order_id(monkeypatch):
    client = _client(monkeypatch)

    response = client.post(
        "/api/v1/movement-repricing/stealth/stealth-abc/reprice",
        headers=_headers(idempotency_key="idem-movement-reprice"),
        json={"reason": "operator_requested_reprice"},
    )

    assert response.status_code == 501
    payload = response.json()
    assert payload["status"] == AdminApiCommandStatus.NOT_IMPLEMENTED.value
    assert payload["action_class"] == AdminApiActionClass.LIVE_EXCHANGE_CANCEL.value
    assert payload["required_permission"] == AdminApiPermission.ORDER_CANCEL.value
    assert payload["service_method"] == "reprice_stealth_order_by_stealth_order_id"
    assert payload["client_order_id"] is None
    assert payload["stealth_order_id"] == "stealth-abc"
    assert payload["coinbase_order_id"] is None
    assert payload["live_exchange_submitted"] is False
    assert payload["failure_stage"] == "approval"
    assert payload["guard"]["approval_snapshot_required"] is True
    assert payload["guard"]["cap_evaluation_required"] is True
    assert payload["data"]["identity_key"] == "stealth_order_id"
    assert payload["data"]["mutation_kind"] == "reprice"
    assert payload["data"]["active_placement_client_order_id"] is None
    assert payload["data"]["exchange_order_id_evidence_only"] is True
    assert payload["data"]["cooldown_cleared"] is False
    assert payload["data"]["stealth_manager_invoked"] is False


@pytest.mark.regression
def test_admin_api_campaign_execution_contract_is_not_implemented_and_not_live(
    monkeypatch,
):
    client = _client(monkeypatch)

    response = client.post(
        "/api/v1/spot/campaign/executions",
        headers=_headers(idempotency_key="idem-campaign"),
        json={
            "campaign_id": "usdc-sweep-001",
            "side": "BUY",
            "quote_notional_per_product": "1.00",
            "product_ids": ["BTC-USDC", "ETH-USDC"],
            "dry_run": False,
            "manual_live_acknowledgement": True,
        },
    )

    assert response.status_code == 501
    payload = response.json()
    assert payload["status"] == AdminApiCommandStatus.NOT_IMPLEMENTED.value
    assert payload["required_permission"] == AdminApiPermission.CAMPAIGN_EXECUTE.value
    assert payload["service_method"] == "execute_spot_campaign"
    assert payload["live_exchange_submitted"] is False
    assert payload["failure_stage"] == "approval"
    assert payload["data"]["campaign_id"] == "usdc-sweep-001"
    assert payload["data"]["product_count"] == 2
    assert payload["audit_id"]


@pytest.mark.regression
def test_admin_api_idempotency_replays_same_response(monkeypatch):
    client = _client(monkeypatch)
    headers = _headers(idempotency_key="idem-replay")

    first = client.post("/api/v1/orders", headers=headers, json=_manual_order_payload())
    second = client.post("/api/v1/orders", headers=headers, json=_manual_order_payload())

    assert first.status_code == 501
    assert second.status_code == 501
    assert second.headers["x-idempotency-replayed"] == "true"
    assert second.json() == first.json()


@pytest.mark.regression
def test_admin_api_idempotency_conflicts_on_payload_drift(monkeypatch):
    client = _client(monkeypatch)
    headers = _headers(idempotency_key="idem-conflict")

    first = client.post("/api/v1/orders", headers=headers, json=_manual_order_payload("1.00"))
    second = client.post("/api/v1/orders", headers=headers, json=_manual_order_payload("2.00"))

    assert first.status_code == 501
    assert second.status_code == 409
    assert second.json()["status"] == AdminApiCommandStatus.CONFLICT.value

    stealth_headers = _headers(idempotency_key="idem-stealth-conflict")
    stealth_first = client.post(
        "/api/v1/stealth/orders/stealth-abc/cancel",
        headers=stealth_headers,
        json={"reason": "operator_request"},
    )
    stealth_second = client.post(
        "/api/v1/stealth/orders/stealth-abc/cancel",
        headers=stealth_headers,
        json={"reason": "operator_request_changed"},
    )

    assert stealth_first.status_code == 501
    assert stealth_second.status_code == 409
    stealth_conflict = stealth_second.json()
    assert stealth_conflict["status"] == AdminApiCommandStatus.CONFLICT.value
    assert stealth_conflict["stealth_order_id"] == "stealth-abc"
    assert stealth_conflict["client_order_id"] is None
    audit_rows = [
        json.loads(line)
        for line in (client.admin_api_test_store_dir / "audit.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    assert audit_rows[-1]["stealth_order_id"] == "stealth-abc"
    assert audit_rows[-1]["client_order_id"] is None
    assert audit_rows[-1]["operator_intent"] == "manual_one_off"

    movement_headers = _headers(idempotency_key="idem-movement-conflict")
    movement_first = client.post(
        "/api/v1/movement-repricing/stealth/stealth-abc/reprice",
        headers=movement_headers,
        json={"reason": "operator_request"},
    )
    movement_second = client.post(
        "/api/v1/movement-repricing/stealth/stealth-abc/reprice",
        headers=movement_headers,
        json={"reason": "operator_request_changed"},
    )

    assert movement_first.status_code == 501
    assert movement_second.status_code == 409
    movement_conflict = movement_second.json()
    assert movement_conflict["status"] == AdminApiCommandStatus.CONFLICT.value
    assert movement_conflict["stealth_order_id"] == "stealth-abc"
    assert movement_conflict["client_order_id"] is None
    audit_rows = [
        json.loads(line)
        for line in (client.admin_api_test_store_dir / "audit.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    assert audit_rows[-1]["stealth_order_id"] == "stealth-abc"
    assert audit_rows[-1]["client_order_id"] is None
    assert audit_rows[-1]["operator_intent"] == "manual_one_off"


@pytest.mark.regression
def test_admin_api_idempotency_conflicts_on_operator_intent_drift(monkeypatch):
    client = _client(monkeypatch)
    first_headers = _headers(
        idempotency_key="idem-intent-conflict",
        operator_intent="manual_one_off",
    )
    second_headers = _headers(
        idempotency_key="idem-intent-conflict",
        operator_intent="changed_operator_intent",
    )

    first = client.post(
        "/api/v1/movement-repricing/stealth/stealth-abc/reprice",
        headers=first_headers,
        json={"reason": "operator_request"},
    )
    second = client.post(
        "/api/v1/movement-repricing/stealth/stealth-abc/reprice",
        headers=second_headers,
        json={"reason": "operator_request"},
    )

    assert first.status_code == 501
    assert second.status_code == 409
    payload = second.json()
    assert payload["status"] == AdminApiCommandStatus.CONFLICT.value
    assert payload["stealth_order_id"] == "stealth-abc"
    audit_rows = [
        json.loads(line)
        for line in (client.admin_api_test_store_dir / "audit.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    assert audit_rows[-1]["operator_intent"] == "changed_operator_intent"


@pytest.mark.regression
def test_admin_api_command_audit_is_durable(monkeypatch):
    client = _client(monkeypatch)

    response = client.post(
        "/api/v1/orders/client-abc/cancel",
        headers=_headers(idempotency_key="idem-audit"),
        json={"reason": "operator_request"},
    )

    assert response.status_code == 501
    audit_rows = [
        json.loads(line)
        for line in (client.admin_api_test_store_dir / "audit.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    assert audit_rows
    assert audit_rows[-1]["actor_id"] == "operator-001"
    assert audit_rows[-1]["client_order_id"] == "client-abc"
    assert audit_rows[-1]["permission"] == AdminApiPermission.ORDER_CANCEL.value
    assert audit_rows[-1]["operator_intent"] == "manual_one_off"

    stealth_response = client.post(
        "/api/v1/stealth/orders/stealth-abc/cancel",
        headers=_headers(idempotency_key="idem-stealth-audit"),
        json={"reason": "operator_request"},
    )

    assert stealth_response.status_code == 501
    audit_rows = [
        json.loads(line)
        for line in (client.admin_api_test_store_dir / "audit.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    assert audit_rows[-1]["endpoint"] == "POST /api/v1/stealth/orders/stealth-abc/cancel"
    assert audit_rows[-1]["stealth_order_id"] == "stealth-abc"
    assert audit_rows[-1]["client_order_id"] is None
    assert audit_rows[-1]["permission"] == AdminApiPermission.ORDER_CANCEL.value
    assert audit_rows[-1]["operator_intent"] == "manual_one_off"
    idempotency_rows = [
        json.loads(line)
        for line in (client.admin_api_test_store_dir / "idempotency.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    assert idempotency_rows[-1]["stealth_order_id"] == "stealth-abc"
    assert idempotency_rows[-1]["client_order_id"] is None

    movement_response = client.post(
        "/api/v1/movement-repricing/stealth/stealth-abc/reprice",
        headers=_headers(idempotency_key="idem-movement-audit"),
        json={"reason": "operator_requested_reprice"},
    )

    assert movement_response.status_code == 501
    audit_rows = [
        json.loads(line)
        for line in (client.admin_api_test_store_dir / "audit.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    assert audit_rows[-1]["endpoint"] == (
        "POST /api/v1/movement-repricing/stealth/stealth-abc/reprice"
    )
    assert audit_rows[-1]["stealth_order_id"] == "stealth-abc"
    assert audit_rows[-1]["client_order_id"] is None
    assert audit_rows[-1]["permission"] == AdminApiPermission.ORDER_CANCEL.value
    assert audit_rows[-1]["operator_intent"] == "manual_one_off"
    idempotency_rows = [
        json.loads(line)
        for line in (client.admin_api_test_store_dir / "idempotency.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    assert idempotency_rows[-1]["stealth_order_id"] == "stealth-abc"
    assert idempotency_rows[-1]["client_order_id"] is None


@pytest.mark.regression
def test_admin_api_openapi_cancel_request_does_not_accept_order_id():
    schema = create_app().openapi()
    cancel_body_ref = schema["paths"]["/api/v1/orders/{client_order_id}/cancel"][
        "post"
    ]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    model_name = cancel_body_ref.rsplit("/", 1)[-1]
    cancel_schema = schema["components"]["schemas"][model_name]

    assert "client_order_id" not in cancel_schema.get("properties", {})
    assert "order_id" not in cancel_schema.get("properties", {})
    assert "client_order_id" in str(
        schema["paths"]["/api/v1/orders/{client_order_id}/cancel"]["post"]["parameters"]
    )

    stealth_cancel_body_ref = schema["paths"][
        "/api/v1/stealth/orders/{stealth_order_id}/cancel"
    ]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    stealth_model_name = stealth_cancel_body_ref.rsplit("/", 1)[-1]
    stealth_cancel_schema = schema["components"]["schemas"][stealth_model_name]
    assert "stealth_order_id" not in stealth_cancel_schema.get("properties", {})
    assert "client_order_id" not in stealth_cancel_schema.get("properties", {})
    assert "order_id" not in stealth_cancel_schema.get("properties", {})
    assert "stealth_order_id" in str(
        schema["paths"]["/api/v1/stealth/orders/{stealth_order_id}/cancel"]["post"]["parameters"]
    )

    movement_reprice_body_ref = schema["paths"][
        "/api/v1/movement-repricing/stealth/{stealth_order_id}/reprice"
    ]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    movement_reprice_model_name = movement_reprice_body_ref.rsplit("/", 1)[-1]
    movement_reprice_schema = schema["components"]["schemas"][
        movement_reprice_model_name
    ]
    assert "stealth_order_id" not in movement_reprice_schema.get("properties", {})
    assert "client_order_id" not in movement_reprice_schema.get("properties", {})
    assert "order_id" not in movement_reprice_schema.get("properties", {})
    assert "stealth_order_id" in str(
        schema["paths"][
            "/api/v1/movement-repricing/stealth/{stealth_order_id}/reprice"
        ]["post"]["parameters"]
    )


@pytest.mark.regression
def test_admin_api_examples_keep_operator_intent_in_headers():
    doc = (ROOT / "docs" / "examples" / "admin-api.md").read_text(encoding="utf-8")
    assert "X-Operator-Intent: manual_one_off" in doc
    assert '"operator_intent"' not in doc


@pytest.mark.regression
def test_admin_api_idempotency_contract_replays_same_hash_and_conflicts_on_drift():
    payload_hash = make_payload_hash({"product_id": "BTC-USDC", "quote_size": "1.00"})
    record = IdempotencyRecord(
        idempotency_key="idem-001",
        payload_hash=payload_hash,
        client_order_id="client-001",
        status=AdminApiCommandStatus.NOT_IMPLEMENTED,
        response={"status": "not_implemented"},
    )

    assert evaluate_idempotency(
        existing=None,
        idempotency_key="idem-001",
        payload_hash=payload_hash,
    ).decision == AdminApiIdempotencyDecision.NEW
    assert evaluate_idempotency(
        existing=record,
        idempotency_key="idem-001",
        payload_hash=payload_hash,
    ).decision == AdminApiIdempotencyDecision.REPLAY
    assert evaluate_idempotency(
        existing=record,
        idempotency_key="idem-001",
        payload_hash=make_payload_hash({"product_id": "BTC-USDC", "quote_size": "2.00"}),
    ).decision == AdminApiIdempotencyDecision.CONFLICT


@pytest.mark.regression
def test_admin_api_routes_have_no_direct_coinbase_path_and_dashboard_delegates():
    service_source = inspect.getsource(command_service)
    route_source = "\n".join(
        [
            inspect.getsource(__import__("api.v1.routes.orders", fromlist=[""])),
            inspect.getsource(__import__("api.v1.routes.stealth", fromlist=[""])),
            inspect.getsource(
                __import__("api.v1.routes.movement_repricing", fromlist=[""])
            ),
        ]
    )
    import dashboard_server

    dashboard_source = inspect.getsource(dashboard_server.handle_client_message)

    route_forbidden_tokens = [
        "REST_CLIENT",
        "CoinbaseRestClient",
        "external.coinbase",
        "create_order(",
        "limit_order_gtc(",
        "cancel_orders(",
        "process_anchor_repricing_for_product(",
    ]
    for token in route_forbidden_tokens:
        assert token not in route_source
    assert "dashboard_server" not in service_source
    assert "cancel_orders(" not in service_source
    assert "_dashboard_command_service().place_manual_order" in dashboard_source
    assert "_dashboard_command_service().cancel_order_by_client_order_id" in dashboard_source
    assert "_dashboard_command_service().place_hotpoint_test_order" in dashboard_source
    assert "REST_CLIENT.limit_order_gtc" not in dashboard_source
    assert "_coinbase_order_response_to_dict" not in dashboard_source


@pytest.mark.regression
def test_admin_api_read_only_spot_routes_are_auth_gated(monkeypatch):
    client = _client(monkeypatch)

    response = client.get("/api/v1/spot/readiness")

    assert response.status_code == 401


@pytest.mark.regression
def test_admin_api_read_only_spot_readiness_uses_read_service(monkeypatch):
    from api.v1.routes import spot as spot_routes

    client = _client(monkeypatch)
    service = SimpleNamespace(
        build_spot_readiness=lambda product_ids=None: {
            "type": "spot_readiness",
            "status": "success",
            "products": product_ids or [],
        }
    )
    client.app.dependency_overrides[spot_routes.get_read_service] = lambda: service

    response = client.get(
        "/api/v1/spot/readiness?product_id=BTC-USDC",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )

    assert response.status_code == 200
    assert response.json()["products"] == ["BTC-USDC"]


@pytest.mark.regression
def test_admin_api_spot_routes_preserve_typed_read_payload_fields(monkeypatch):
    from api.v1.routes import spot as spot_routes

    client = _client(monkeypatch)
    service = SimpleNamespace(
        build_spot_sweep_pnl=lambda product_ids=None, include_coinbase_average_cost=False: {
            "type": "spot_sweep_pnl",
            "status": "success",
            "pnl_report": {
                "snapshot": {
                    "products": [{"product_id": "BTC-USDC", "total_pnl": "1.23"}],
                    "portfolio": {"total_pnl": "1.23"},
                }
            },
            "read_only_coinbase_requests": ["accounts"],
            "backend_extra_evidence": {"kept": True},
            "live_coinbase_orders_ran": False,
        },
        build_spot_direct_order_audit=lambda **kwargs: {
            "type": "spot_direct_order_audit",
            "status": "success",
            "client_order_id": kwargs["client_order_id"],
            "audit": {"audit_is_read_only": True},
            "events": [{"event_type": "order_submitted"}],
            "fills": [{"fill_id": "fill-001"}],
            "live_coinbase_orders_ran": False,
        },
    )
    client.app.dependency_overrides[spot_routes.get_read_service] = lambda: service

    pnl_response = client.get(
        "/api/v1/spot/sweep/pnl?product_id=BTC-USDC&include_coinbase_average_cost=true",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    audit_response = client.get(
        "/api/v1/spot/direct-orders/client-abc/audit",
        headers=_headers(roles=AdminApiRole.AUDITOR.value),
    )

    assert pnl_response.status_code == 200
    assert pnl_response.json()["pnl_report"]["snapshot"]["products"][0]["product_id"] == "BTC-USDC"
    assert pnl_response.json()["read_only_coinbase_requests"] == ["accounts"]
    assert pnl_response.json()["backend_extra_evidence"] == {"kept": True}
    assert audit_response.status_code == 200
    assert audit_response.json()["client_order_id"] == "client-abc"
    assert audit_response.json()["audit"]["audit_is_read_only"] is True
    assert audit_response.json()["events"][0]["event_type"] == "order_submitted"


@pytest.mark.regression
def test_admin_api_backend_rbac_matches_frontend_role_hints():
    viewer = AdminApiActor(actor_id="viewer-001", roles=[AdminApiRole.VIEWER])
    operator = AdminApiActor(actor_id="operator-001", roles=[AdminApiRole.OPERATOR])
    trader = AdminApiActor(actor_id="trader-001", roles=[AdminApiRole.TRADER])
    emergency = AdminApiActor(actor_id="emergency-001", roles=[AdminApiRole.EMERGENCY])

    assert actor_has_permission(viewer, AdminApiPermission.ANALYTICS_READ)
    assert actor_has_permission(viewer, AdminApiPermission.AUDIT_READ)
    assert actor_has_permission(viewer, AdminApiPermission.CAMPAIGN_READ)
    assert not actor_has_permission(viewer, AdminApiPermission.ORDER_CREATE)
    assert actor_has_permission(operator, AdminApiPermission.RUNTIME_PAUSE)
    assert actor_has_permission(operator, AdminApiPermission.RUNTIME_RESUME)
    assert not actor_has_permission(operator, AdminApiPermission.ORDER_CANCEL)
    assert actor_has_permission(trader, AdminApiPermission.CAMPAIGN_EXECUTE)
    assert not actor_has_permission(emergency, AdminApiPermission.ORDER_CANCEL)
    assert actor_has_permission(emergency, AdminApiPermission.RUNTIME_SHUTDOWN)


@pytest.mark.regression
def test_admin_api_admin_read_routes_return_backend_contracts(monkeypatch):
    client = _client(monkeypatch)
    headers = _headers(roles=AdminApiRole.VIEWER.value)

    bootstrap = client.get("/api/v1/admin/bootstrap", headers=headers)
    health = client.get("/api/v1/admin/health", headers=headers)
    session = client.get("/api/v1/admin/session", headers=headers)
    capabilities = client.get("/api/v1/admin/capabilities", headers=headers)
    csrf = client.get("/api/v1/admin/csrf", headers=headers)
    live_enablement = client.get("/api/v1/admin/live-enablement", headers=headers)
    enterprise_readiness = client.get(
        "/api/v1/admin/enterprise-readiness",
        headers=headers,
    )
    release_gate = client.get("/api/v1/admin/release-gate", headers=headers)
    recovery_gate = client.get("/api/v1/admin/recovery-gate", headers=headers)
    fill_ledger_health = client.get(
        "/api/v1/admin/fill-ledger-health",
        headers=headers,
    )
    frontend_fixtures = client.get(
        "/api/v1/admin/frontend-fixtures",
        headers=headers,
    )

    assert bootstrap.status_code == 200
    assert bootstrap.json()["backend_repository"] == "s-aws/coinbase"
    assert bootstrap.json()["mutating_routes_live_disabled"] is True
    assert bootstrap.json()["live_coinbase_orders_ran"] is False
    assert bootstrap.json()["auth_mode"] == AdminApiAuthMode.BOOTSTRAP_BEARER.value
    assert health.status_code == 200
    assert health.json()["failed_route_count"] == 0
    assert health.json()["live_coinbase_orders_ran"] is False
    assert session.status_code == 200
    assert AdminApiPermission.AUDIT_READ.value in session.json()["permissions"]
    assert session.json()["auth_mode"] == AdminApiAuthMode.BOOTSTRAP_BEARER.value
    assert session.json()["bearer_token_visible_to_browser"] is False
    assert capabilities.status_code == 200
    routes = {item["route"] for item in capabilities.json()["capabilities"]}
    assert "/api/v1/spot/campaign/executions" in routes
    assert "/api/v1/admin/bootstrap" in routes
    assert "/api/v1/admin/csrf" in routes
    assert "/api/v1/admin/live-enablement" in routes
    assert "/api/v1/admin/enterprise-readiness" in routes
    assert csrf.status_code == 200
    assert csrf.json() == {
        "type": "admin_csrf_contract",
        "csrf_required": False,
        "csrf_header_name": "X-CSRF-Token",
        "token_issued_by_backend": False,
        "token_visible_to_browser": False,
        "token_source": "session_or_bff_boundary",
        "rotation_policy": "rotate_on_session_or_deploy_secret_change",
        "live_coinbase_orders_ran": False,
    }
    assert live_enablement.status_code == 200
    live_payload = live_enablement.json()
    assert live_payload["type"] == "admin_live_enablement"
    assert live_payload["status"] == "live_disabled"
    assert live_payload["approved_phase_range"] == "761-780"
    assert live_payload["default_live_coinbase_execution"] == "not_run"
    assert live_payload["submitted_notional_usdc"] == "0"
    assert live_payload["executed_notional_usdc"] == "0"
    assert live_payload["max_submitted_notional_usdc"] == "3.10"
    assert live_payload["max_executed_notional_usdc"] == "1.00"
    assert live_payload["live_enabled_path_count"] == 0
    assert live_payload["live_eligible_path_count"] == 0
    assert live_payload["live_coinbase_orders_ran"] is False
    live_routes = {item["route"]: item for item in live_payload["paths"]}
    assert "/api/v1/orders" in live_routes
    assert "/api/v1/orders/{client_order_id}/cancel" in live_routes
    assert "/api/v1/stealth/orders/{stealth_order_id}/cancel" in live_routes
    assert (
        "/api/v1/movement-repricing/stealth/{stealth_order_id}/reprice"
        in live_routes
    )
    assert "/api/v1/spot/campaign/executions" in live_routes
    assert all(item["live_enabled"] is False for item in live_routes.values())
    assert all(item["status"] == "live_disabled" for item in live_routes.values())
    assert enterprise_readiness.status_code == 200
    enterprise_payload = enterprise_readiness.json()
    assert enterprise_payload["type"] == "admin_enterprise_readiness"
    assert enterprise_payload["candidate"] == "enterprise_admin_m9"
    assert enterprise_payload["approved_phase_range"] == "761-780"
    assert enterprise_payload["status"] == AdminApiGateStatus.WARNING.value
    assert enterprise_payload["frontend_authority"] == "backend_contract_only"
    assert enterprise_payload["live_posture"] == "live_disabled"
    assert enterprise_payload["default_live_coinbase_execution"] == "not_run"
    assert enterprise_payload["submitted_notional_usdc"] == "0"
    assert enterprise_payload["executed_notional_usdc"] == "0"
    assert enterprise_payload["read_only"] is True
    assert enterprise_payload["live_coinbase_orders_ran"] is False
    module_statuses = {
        item["module"]: item["support_status"]
        for item in enterprise_payload["modules"]
    }
    assert module_statuses["Admin / System Health"] == (
        AdminApiModuleSupportStatus.PLATFORM_READY.value
    )
    assert module_statuses["Spot Operations"] == (
        AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED.value
    )
    assert module_statuses["Futures / Perpetuals"] == (
        AdminApiModuleSupportStatus.READ_ONLY_READY.value
    )
    assert module_statuses["Legacy Dashboard WebSocket"] == (
        AdminApiModuleSupportStatus.UNSUPPORTED.value
    )
    assert enterprise_payload["supported_module_count"] >= 7
    assert enterprise_payload["unsupported_module_count"] == 1
    spot_module = next(
        item
        for item in enterprise_payload["modules"]
        if item["module"] == "Spot Operations"
    )
    assert "spot short selling" in spot_module["unsupported_actions"]
    assert "client_order_id" in spot_module["identity_keys"]
    assert "POST /api/v1/orders" in spot_module["command_routes"]
    assert all(check["status"] == "passed" for check in enterprise_payload["security_checks"])
    browser_boundary = next(
        check
        for check in enterprise_payload["security_checks"]
        if check["name"] == "browser_authority_boundary"
    )
    assert "Enterprise admin frontend/Admin HTTP" in browser_boundary["detail"]
    assert "docs/LIVE_ORDER_SURFACES.md" in browser_boundary["detail"]
    assert {
        check["name"]
        for check in enterprise_payload["release_checks"]
        if check["status"] == "warning"
    } >= {
        "backend_regression_gate",
        "frontend_release_gate",
        "contextless_review_gate",
    }
    assert release_gate.status_code == 200
    release_payload = release_gate.json()
    assert release_payload["type"] == "admin_release_gate"
    assert release_payload["status"] == AdminApiGateStatus.PASSED.value
    assert release_payload["read_only"] is True
    assert release_payload["live_coinbase_orders_ran"] is False
    assert {check["name"] for check in release_payload["checks"]} >= {
        "openapi_schema_artifact",
        "backend_regression_gate",
        "live_coinbase_execution",
    }
    assert recovery_gate.status_code == 200
    recovery_payload = recovery_gate.json()
    assert recovery_payload["type"] == "admin_recovery_gate"
    assert recovery_payload["status"] == AdminApiGateStatus.PASSED.value
    assert recovery_payload["read_only"] is True
    assert recovery_payload["live_coinbase_orders_ran"] is False
    recovery_checks = {check["name"]: check for check in recovery_payload["checks"]}
    assert "spot_direct_order_audit_route" in recovery_checks
    assert "non_spot_recovery_scope" in recovery_checks
    assert recovery_checks["non_spot_recovery_scope"]["status"] == (
        AdminApiGateStatus.NOT_APPLICABLE.value
    )
    assert "spot/direct-order recovery readiness only" in (
        recovery_checks["non_spot_recovery_scope"]["detail"]
    )
    assert fill_ledger_health.status_code == 200
    fill_ledger_payload = fill_ledger_health.json()
    assert fill_ledger_payload["type"] == "admin_fill_ledger_health"
    assert fill_ledger_payload["status"] == AdminApiGateStatus.PASSED.value
    assert fill_ledger_payload["read_only"] is True
    assert fill_ledger_payload["live_coinbase_orders_ran"] is False
    assert {check["name"] for check in fill_ledger_payload["checks"]} >= {
        "read_surface",
        "repair_surface",
        "observed_at",
    }
    assert frontend_fixtures.status_code == 200
    frontend_fixture_payload = frontend_fixtures.json()
    assert frontend_fixture_payload["live_coinbase_orders_ran"] is False
    fixture_keys = set(frontend_fixture_payload["fixtures"])
    assert {
        "admin.releaseGate",
        "admin.recoveryGate",
        "admin.fillLedgerHealth",
    } <= fixture_keys
    assert "release.gate" not in fixture_keys
    assert "recovery.gate" not in fixture_keys
    assert "fillLedger.health" not in fixture_keys


@pytest.mark.regression
def test_admin_api_order_read_routes_use_read_service_and_client_order_id(monkeypatch):
    from api.v1.routes import orders as order_routes

    client = _client(monkeypatch)
    service = SimpleNamespace(
        build_order_list=lambda product_id=None, status=None, limit=100, offset=0: {
            "type": "admin_order_list",
            "filters": {
                "product_id": product_id,
                "status": status,
                "limit": limit,
                "offset": offset,
            },
            "count": 1,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "returned_count": 1,
                "total_matching_count": 2,
                "next_offset": offset + 1,
                "has_more": True,
            },
            "items": [
                {
                    "client_order_id": "client-abc",
                    "product_id": "BTC-USDC",
                    "exchange_order_id": "coinbase-evidence-001",
                    "exchange_order_id_evidence_only": True,
                    "correlation_id": "corr-order-read",
                    "audit_id": "audit-order-read",
                }
            ],
            "read_only": True,
            "live_coinbase_orders_ran": False,
        },
        build_order_detail=lambda client_order_id: {
            "type": "admin_order_detail",
            "client_order_id": client_order_id,
            "found": True,
            "order": {
                "client_order_id": client_order_id,
                "exchange_order_id": "coinbase-evidence-001",
                "exchange_order_id_evidence_only": True,
                "correlation_id": "corr-order-detail",
                "audit_id": "audit-order-detail",
            },
            "read_only": True,
            "live_coinbase_orders_ran": False,
        },
    )
    client.app.dependency_overrides[order_routes.get_read_service] = lambda: service

    list_response = client.get(
        "/api/v1/orders?product_id=BTC-USDC&order_status=OPEN&limit=10&offset=20",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    detail_response = client.get(
        "/api/v1/orders/client-abc",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )

    assert list_response.status_code == 200
    assert list_response.json()["filters"]["offset"] == 20
    assert list_response.json()["pagination"]["next_offset"] == 21
    assert list_response.json()["items"][0]["client_order_id"] == "client-abc"
    assert list_response.json()["items"][0]["exchange_order_id_evidence_only"] is True
    assert list_response.json()["items"][0]["correlation_id"] == "corr-order-read"
    assert list_response.json()["items"][0]["audit_id"] == "audit-order-read"
    assert "order_id" not in list_response.json()["items"][0]
    assert detail_response.status_code == 200
    assert detail_response.json()["client_order_id"] == "client-abc"
    assert detail_response.json()["order"]["correlation_id"] == "corr-order-detail"
    assert detail_response.json()["order"]["audit_id"] == "audit-order-detail"
    assert "order_id" not in detail_response.json()["order"]


@pytest.mark.regression
def test_admin_api_order_list_read_service_returns_pagination_metadata(monkeypatch):
    import database.order as order_module

    from application.admin_api.read_service import AdminApiReadService

    rows = [
        {
            "client_order_id": f"client-{index}",
            "product_id": "BTC-USDC",
            "status": "OPEN",
            "correlation_id": f"corr-{index}",
            "audit_id": f"audit-{index}",
        }
        for index in range(5)
    ]
    monkeypatch.setattr(order_module, "get_parent_orders", lambda: rows)

    response = AdminApiReadService().build_order_list(
        product_id="BTC-USDC",
        status="OPEN",
        limit=2,
        offset=1,
    )

    assert response.count == 2
    assert [item.client_order_id for item in response.items] == ["client-1", "client-2"]
    assert response.items[0].correlation_id == "corr-1"
    assert response.items[0].audit_id == "audit-1"
    assert response.pagination.limit == 2
    assert response.pagination.offset == 1
    assert response.pagination.returned_count == 2
    assert response.pagination.total_matching_count == 5
    assert response.pagination.next_offset == 3
    assert response.pagination.has_more is True


@pytest.mark.regression
def test_admin_api_stealth_read_routes_use_read_service_without_commands(monkeypatch):
    from api.v1.routes import stealth as stealth_routes

    client = _client(monkeypatch)
    service = SimpleNamespace(
        build_stealth_order_list=lambda product_id=None, status=None, limit=100, offset=0: {
            "type": "admin_stealth_order_list",
            "filters": {
                "product_id": product_id,
                "status": status,
                "limit": limit,
                "offset": offset,
            },
            "count": 1,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "returned_count": 1,
                "total_matching_count": 1,
                "next_offset": None,
                "has_more": False,
            },
            "items": [
                {
                    "stealth_order_id": "stealth-abc",
                    "product_id": "BTC-USDC",
                    "status": "REVEALED",
                    "active_placement_client_order_id": "placement-client-1",
                    "active_exchange_order_id": "exchange-evidence-1",
                    "exchange_order_id_evidence_only": True,
                }
            ],
            "read_only": True,
            "command_routes_mode": AdminApiCommandRoutesMode.LIVE_DISABLED.value,
            "live_coinbase_orders_ran": False,
        },
        build_stealth_order_detail=lambda stealth_order_id: {
            "type": "admin_stealth_order_detail",
            "stealth_order_id": stealth_order_id,
            "found": True,
            "order": {
                "stealth_order_id": stealth_order_id,
                "active_placement_client_order_id": "placement-client-1",
                "active_exchange_order_id": "exchange-evidence-1",
                "exchange_order_id_evidence_only": True,
            },
            "read_only": True,
            "command_routes_mode": AdminApiCommandRoutesMode.LIVE_DISABLED.value,
            "live_coinbase_orders_ran": False,
        },
    )
    client.app.dependency_overrides[stealth_routes.get_read_service] = lambda: service

    list_response = client.get(
        "/api/v1/stealth/orders?product_id=BTC-USDC&stealth_status=REVEALED&limit=10&offset=0",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    detail_response = client.get(
        "/api/v1/stealth/orders/stealth-abc",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )

    assert list_response.status_code == 200
    assert list_response.json()["filters"]["status"] == "REVEALED"
    assert list_response.json()["command_routes_mode"] == (
        AdminApiCommandRoutesMode.LIVE_DISABLED.value
    )
    assert list_response.json()["items"][0]["stealth_order_id"] == "stealth-abc"
    assert list_response.json()["items"][0]["active_placement_client_order_id"] == (
        "placement-client-1"
    )
    assert list_response.json()["items"][0]["active_exchange_order_id"] == (
        "exchange-evidence-1"
    )
    assert list_response.json()["items"][0]["exchange_order_id_evidence_only"] is True
    assert "order_id" not in list_response.json()["items"][0]
    assert detail_response.status_code == 200
    assert detail_response.json()["order"]["stealth_order_id"] == "stealth-abc"
    assert detail_response.json()["command_routes_mode"] == (
        AdminApiCommandRoutesMode.LIVE_DISABLED.value
    )
    assert detail_response.json()["live_coinbase_orders_ran"] is False


@pytest.mark.regression
def test_admin_api_stealth_read_service_maps_placement_and_exchange_evidence(monkeypatch):
    import database.order as order_module

    from application.admin_api.read_service import AdminApiReadService

    rows = [
        {
            "stealth_order_id": "stealth-root",
            "parent_order_id": None,
            "product_id": "BTC-USDC",
            "side": "BUY",
            "status": "REVEALED",
            "total_size": "2.00",
            "revealed_size": "1.00",
            "remaining_size": "1.00",
            "executed_size": "0.25",
            "limit_price": "65000.00",
            "visibility_score": "0.42",
            "reveal_condition_type": "price",
            "reveal_condition_json": {"price_threshold": "65000.00"},
            "sizing_strategy_json": {"type": "tranche"},
            "revealed_orders": [
                {
                    "placed_order_id": "placement-client-old",
                    "exchange_order_id": "exchange-old",
                },
                {
                    "placed_order_id": "placement-client-latest",
                    "exchange_order_id": "exchange-latest",
                },
            ],
            "anchor_repricing_policy_json": {"enabled": True},
            "anchor_repricing_state_json": {
                "active_placement_client_order_id": "placement-client-active",
                "active_exchange_order_id": "exchange-active",
            },
            "cancel_reentry_policy_json": {"enabled": True},
            "cancel_reentry_state_json": {"state": "watching"},
            "post_fill_retreat_policy_json": {"enabled": False},
            "last_lifecycle_event": "revealed",
            "failure_reason": None,
            "created_at": "2026-06-11T10:00:00Z",
            "updated_at": "2026-06-11T10:05:00Z",
        },
        {
            "stealth_order_id": "stealth-other",
            "product_id": "ETH-USDC",
            "status": "HIDDEN",
        },
    ]
    monkeypatch.setattr(
        order_module,
        "DB_CLIENT",
        SimpleNamespace(execute_query=lambda _query: rows),
    )
    monkeypatch.setattr(
        order_module,
        "get_stealth_order_by_id",
        lambda stealth_order_id: rows[0] if stealth_order_id == "stealth-root" else None,
    )

    service = AdminApiReadService()
    list_response = service.build_stealth_order_list(
        product_id="BTC-USDC",
        status="REVEALED",
        limit=10,
        offset=0,
    )
    detail_response = service.build_stealth_order_detail(stealth_order_id="stealth-root")

    assert list_response.type == "admin_stealth_order_list"
    assert list_response.count == 1
    assert list_response.pagination.total_matching_count == 1
    assert list_response.command_routes_mode == AdminApiCommandRoutesMode.LIVE_DISABLED
    item = list_response.items[0]
    assert item.stealth_order_id == "stealth-root"
    assert item.active_placement_client_order_id == "placement-client-active"
    assert item.active_exchange_order_id == "exchange-active"
    assert item.exchange_order_id_evidence_only is True
    assert item.revealed_orders[-1]["placed_order_id"] == "placement-client-latest"
    assert item.anchor_repricing_policy == {"enabled": True}
    assert item.cancel_reentry_state == {"state": "watching"}
    assert item.source == "stealth_orders"
    assert detail_response.found is True
    assert detail_response.order is not None
    assert detail_response.order.stealth_order_id == "stealth-root"
    assert detail_response.live_coinbase_orders_ran is False


@pytest.mark.regression
def test_admin_api_stealth_read_service_does_not_promote_historical_reveals_to_active(monkeypatch):
    import database.order as order_module

    from application.admin_api.read_service import AdminApiReadService

    rows = [
        {
            "stealth_order_id": "stealth-terminal",
            "product_id": "BTC-USDC",
            "status": "FILLED",
            "revealed_orders": [
                {
                    "placed_order_id": "historical-placement-client",
                    "exchange_order_id": "historical-exchange-evidence",
                }
            ],
            "anchor_repricing_state_json": {},
            "last_lifecycle_event": "filled",
        }
    ]
    monkeypatch.setattr(
        order_module,
        "DB_CLIENT",
        SimpleNamespace(execute_query=lambda _query: rows),
    )
    monkeypatch.setattr(
        order_module,
        "get_stealth_order_by_id",
        lambda stealth_order_id: rows[0] if stealth_order_id == "stealth-terminal" else None,
    )

    service = AdminApiReadService()
    list_response = service.build_stealth_order_list(limit=10, offset=0)
    detail_response = service.build_stealth_order_detail(
        stealth_order_id="stealth-terminal"
    )

    item = list_response.items[0]
    assert item.stealth_order_id == "stealth-terminal"
    assert item.revealed_orders[0]["placed_order_id"] == "historical-placement-client"
    assert item.active_placement_client_order_id is None
    assert item.active_exchange_order_id is None
    assert detail_response.order is not None
    assert detail_response.order.active_placement_client_order_id is None
    assert detail_response.order.active_exchange_order_id is None


@pytest.mark.regression
def test_admin_api_movement_repricing_read_routes_use_read_service_without_commands(
    monkeypatch,
):
    from api.v1.routes import movement_repricing as movement_routes

    client = _client(monkeypatch)
    service = SimpleNamespace(
        build_movement_repricing_evidence=lambda **kwargs: {
            "type": "admin_movement_repricing_evidence",
            "filters": kwargs,
            "count": 1,
            "pagination": {
                "limit": kwargs["limit"],
                "offset": kwargs["offset"],
                "returned_count": 1,
                "total_matching_count": 1,
                "next_offset": None,
                "has_more": False,
            },
            "items": [
                {
                    "evidence_id": "stealth_repricing_state:stealth-abc",
                    "evidence_type": "stealth_repricing_state",
                    "stealth_order_id": "stealth-abc",
                    "client_order_id": "placement-client-1",
                    "active_placement_client_order_id": "placement-client-1",
                    "active_exchange_order_id": "exchange-evidence-1",
                    "exchange_order_id_evidence_only": True,
                    "mutation_claims": [
                        {
                            "kind": "move",
                            "state": "processing",
                            "runtime_observed": True,
                            "source": "stealth_manager._mutation_claims",
                        }
                    ],
                    "replacement_slots": [
                        {
                            "client_order_id": "parent-1",
                            "max_order_replacement": 3,
                            "current_order_replacement": 1,
                            "pending_replacement_claims": 0,
                            "pending_claims_runtime_observed": True,
                            "source": "order_parent",
                        }
                    ],
                    "source": "stealth_orders",
                }
            ],
            "read_only": True,
            "command_routes_mode": "live_disabled",
            "live_coinbase_orders_ran": False,
        },
        build_movement_repricing_order_detail=lambda client_order_id: {
            "type": "admin_movement_repricing_detail",
            "scope": "client_order_id",
            "client_order_id": client_order_id,
            "stealth_order_id": None,
            "found": True,
            "items": [
                {
                    "evidence_id": "parent_move:1",
                    "evidence_type": "parent_move",
                    "client_order_id": client_order_id,
                    "original_parent_client_order_id": client_order_id,
                    "exchange_order_id_evidence_only": True,
                    "source": "order_moves",
                }
            ],
            "read_only": True,
            "command_routes_mode": "live_disabled",
            "live_coinbase_orders_ran": False,
        },
        build_movement_repricing_stealth_detail=lambda stealth_order_id: {
            "type": "admin_movement_repricing_detail",
            "scope": "stealth_order_id",
            "client_order_id": None,
            "stealth_order_id": stealth_order_id,
            "found": True,
            "items": [
                {
                    "evidence_id": "stealth_move:2",
                    "evidence_type": "stealth_move",
                    "stealth_order_id": stealth_order_id,
                    "old_exchange_order_id": "old-exchange-evidence",
                    "new_exchange_order_id": "new-exchange-evidence",
                    "exchange_order_id_evidence_only": True,
                    "source": "stealth_order_moves",
                }
            ],
            "read_only": True,
            "command_routes_mode": "live_disabled",
            "live_coinbase_orders_ran": False,
        },
    )
    client.app.dependency_overrides[movement_routes.get_read_service] = lambda: service

    list_response = client.get(
        (
            "/api/v1/movement-repricing/evidence"
            "?product_id=BTC-USDC&stealth_order_id=stealth-abc"
            "&client_order_id=placement-client-1&evidence_type=stealth_repricing_state"
            "&limit=10&offset=0"
        ),
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    order_response = client.get(
        "/api/v1/movement-repricing/orders/parent-1",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    stealth_response = client.get(
        "/api/v1/movement-repricing/stealth/stealth-abc",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )

    assert list_response.status_code == 200
    assert list_response.json()["command_routes_mode"] == "live_disabled"
    assert list_response.json()["items"][0]["stealth_order_id"] == "stealth-abc"
    assert list_response.json()["items"][0]["mutation_claims"][0]["kind"] == "move"
    assert list_response.json()["items"][0]["replacement_slots"][0][
        "client_order_id"
    ] == "parent-1"
    assert "order_id" not in list_response.json()["items"][0]
    assert order_response.status_code == 200
    assert order_response.json()["client_order_id"] == "parent-1"
    assert order_response.json()["items"][0]["evidence_type"] == "parent_move"
    assert stealth_response.status_code == 200
    assert stealth_response.json()["stealth_order_id"] == "stealth-abc"
    assert stealth_response.json()["items"][0]["evidence_type"] == "stealth_move"
    assert stealth_response.json()["live_coinbase_orders_ran"] is False


@pytest.mark.regression
def test_admin_api_movement_repricing_read_service_maps_durable_and_runtime_evidence(
    monkeypatch,
):
    import database.order as order_module

    from application.admin_api.read_service import AdminApiReadService
    from core.enums import StealthMutationKind

    parent_rows = {
        "parent-old": {
            "client_order_id": "parent-old",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "max_order_replacement": 4,
            "current_order_replacement": 2,
        },
        "parent-new": {
            "client_order_id": "parent-new",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "max_order_replacement": 4,
            "current_order_replacement": 0,
        },
    }
    order_move_rows = [
        {
            "id": 1,
            "original_parent_client_order_id": "parent-old",
            "new_parent_client_order_id": "parent-new",
            "move_on_cancel": False,
            "moved_at": "2026-06-11T10:00:00Z",
            "reason": "user_move",
            "notes": "operator move",
            "created_at": "2026-06-11T09:59:00Z",
        }
    ]
    stealth_move_rows = [
        {
            "id": 2,
            "stealth_order_id": "stealth-root",
            "old_placement_client_order_id": "placement-old",
            "old_exchange_order_id": "exchange-old",
            "old_submitted_price": "100.00",
            "new_placement_client_order_id": "placement-new",
            "new_exchange_order_id": "exchange-new",
            "new_submitted_price": "101.00",
            "reason": "manual_user_move",
            "status": "completed",
            "market_bid": "100.90",
            "market_ask": "101.10",
            "moved_at": "2026-06-11T10:05:00Z",
        }
    ]
    stealth_rows = [
        {
            "stealth_order_id": "stealth-root",
            "parent_order_id": "parent-old",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "status": "REVEALED",
            "target_movement": "0.005",
            "target_movement_type": "P",
            "anchor_repricing_policy_json": {"enabled": True},
            "anchor_repricing_state_json": {
                "active_placement_client_order_id": "placement-new",
                "active_exchange_order_id": "exchange-new",
                "active_exchange_price": "101.00",
                "last_reprice_at": "2026-06-11T10:05:00Z",
                "next_reprice_at": "2026-06-11T10:06:00Z",
                "reprice_reason": "reference_price_updated",
                "reprice_history": ["2026-06-11T10:05:00Z"],
                "post_fill_retreat_offset": "0.25",
            },
            "updated_at": "2026-06-11T10:05:00Z",
        }
    ]

    def execute_query(query, params=None):
        if "FROM order_moves" in query:
            return order_move_rows
        if "FROM stealth_order_moves" in query:
            return stealth_move_rows
        if "FROM stealth_orders" in query:
            return stealth_rows
        return []

    class ClaimSnapshot:
        def state(self, kind, stealth_order_id):
            if kind == StealthMutationKind.REPRICE and stealth_order_id == "stealth-root":
                return "processing"
            return None

    runtime_manager = SimpleNamespace(_mutation_claims=ClaimSnapshot())
    class RuntimeLock:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return None

    runtime_engine = SimpleNamespace(
        orderbook_lock=RuntimeLock(),
        _pending_replacement_claims={"parent-old": 1},
    )
    runtime_bridge = SimpleNamespace(
        stealth_manager=runtime_manager,
        order_engine=runtime_engine,
    )
    monkeypatch.setattr(
        order_module,
        "DB_CLIENT",
        SimpleNamespace(execute_query=execute_query),
    )
    monkeypatch.setattr(
        order_module,
        "get_parent_order",
        lambda client_order_id: parent_rows.get(client_order_id),
    )
    monkeypatch.setattr(
        order_module,
        "get_stealth_order_by_id",
        lambda stealth_order_id: stealth_rows[0]
        if stealth_order_id == "stealth-root"
        else None,
    )
    import dashboard_server

    monkeypatch.setattr(dashboard_server, "stealth_order_bridge", runtime_bridge)

    response = AdminApiReadService().build_movement_repricing_evidence(
        product_id="BTC-USDC",
        limit=10,
        offset=0,
    )

    assert response.type == "admin_movement_repricing_evidence"
    assert response.command_routes_mode == AdminApiCommandRoutesMode.LIVE_DISABLED
    assert response.live_coinbase_orders_ran is False
    evidence_by_type = {item.evidence_type.value: item for item in response.items}
    parent_move = evidence_by_type["parent_move"]
    assert parent_move.original_parent_client_order_id == "parent-old"
    assert parent_move.new_parent_client_order_id == "parent-new"
    assert parent_move.replacement_slots[0].client_order_id == "parent-old"
    assert parent_move.replacement_slots[0].pending_replacement_claims == 1
    stealth_move = evidence_by_type["stealth_move"]
    assert stealth_move.old_exchange_order_id == "exchange-old"
    assert stealth_move.new_exchange_order_id == "exchange-new"
    assert stealth_move.exchange_order_id_evidence_only is True
    reprice_state = evidence_by_type["stealth_repricing_state"]
    assert reprice_state.client_order_id == "placement-new"
    assert reprice_state.active_placement_client_order_id == "placement-new"
    assert reprice_state.active_exchange_order_id == "exchange-new"
    assert reprice_state.reprice_history == ["2026-06-11T10:05:00Z"]
    assert reprice_state.mutation_claims[1].kind == StealthMutationKind.REPRICE
    assert reprice_state.mutation_claims[1].state == "processing"
    assert reprice_state.exchange_order_id_evidence_only is True


@pytest.mark.regression
def test_admin_api_futures_read_routes_use_read_service_without_commands(monkeypatch):
    from api.v1.routes import futures as futures_routes

    client = _client(monkeypatch)
    service = SimpleNamespace(
        build_futures_account=lambda: {
            "type": "admin_futures_account",
            "configured_product_scope": ["BIP-20DEC30-CDE"],
            "observed_position_scope": ["BIP-20DEC30-CDE"],
            "collateral": {
                "name": "collateral",
                "status": "unavailable",
                "source": "runtime_unavailable",
                "detail": "No futures balance summary has been observed.",
            },
            "margin": {
                "name": "margin",
                "status": "observed",
                "source": "fee_manager",
                "value": {
                    "margin_window_type": "FCM_MARGIN_WINDOW_TYPE_OVERNIGHT",
                    "overnight_margin_active": True,
                },
            },
            "funding": {
                "name": "funding",
                "status": "not_modeled",
                "source": "backend_contract",
            },
            "liquidation": {
                "name": "liquidation",
                "status": "unavailable",
                "source": "runtime_unavailable",
            },
            "reduce_only_close_only": {
                "name": "reduce_only_close_only",
                "status": "observed",
                "source": "position_side_derivation",
            },
            "position_pnl": {
                "name": "position_pnl",
                "status": "observed",
                "source": "runtime_positions",
            },
            "position_count": 1,
            "read_only": True,
            "command_routes_mode": "not_modeled",
            "live_coinbase_orders_ran": False,
        },
        build_futures_positions=lambda **kwargs: {
            "type": "admin_futures_positions",
            "filters": kwargs,
            "count": 1,
            "pagination": {
                "limit": kwargs["limit"],
                "offset": kwargs["offset"],
                "returned_count": 1,
                "total_matching_count": 1,
                "next_offset": None,
                "has_more": False,
            },
            "items": [
                {
                    "position_key": "futures_position:runtime:BIP-20DEC30-CDE",
                    "product_id": "BIP-20DEC30-CDE",
                    "product_type": "FUTURE",
                    "position_side": "LONG",
                    "number_of_contracts": "2",
                    "open_order_side": "BUY",
                    "close_order_side": "SELL",
                    "reduce_only_order_side": "SELL",
                    "close_only_order_side": "SELL",
                    "source": "runtime_orderbook",
                }
            ],
            "read_only": True,
            "command_routes_mode": "not_modeled",
            "live_coinbase_orders_ran": False,
        },
        build_futures_position_detail=lambda position_key: {
            "type": "admin_futures_position_detail",
            "position_key": position_key,
            "found": True,
            "position": {
                "position_key": position_key,
                "product_id": "BIP-20DEC30-CDE",
                "product_type": "FUTURE",
                "position_side": "LONG",
                "number_of_contracts": "2",
                "open_order_side": "BUY",
                "close_order_side": "SELL",
                "reduce_only_order_side": "SELL",
                "close_only_order_side": "SELL",
                "source": "runtime_orderbook",
            },
            "read_only": True,
            "command_routes_mode": "not_modeled",
            "live_coinbase_orders_ran": False,
        },
    )
    client.app.dependency_overrides[futures_routes.get_read_service] = lambda: service

    account_response = client.get(
        "/api/v1/futures/account",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    positions_response = client.get(
        "/api/v1/futures/positions?product_id=BIP-20DEC30-CDE&position_side=LONG&limit=10&offset=0",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    detail_response = client.get(
        "/api/v1/futures/positions/futures_position%3Aruntime%3ABIP-20DEC30-CDE",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )

    assert account_response.status_code == 200
    assert account_response.json()["command_routes_mode"] == "not_modeled"
    assert account_response.json()["margin"]["status"] == "observed"
    assert positions_response.status_code == 200
    position = positions_response.json()["items"][0]
    assert position["position_key"] == "futures_position:runtime:BIP-20DEC30-CDE"
    assert position["close_order_side"] == "SELL"
    assert "client_order_id" not in position
    assert "cost_basis" not in position
    assert detail_response.status_code == 200
    assert detail_response.json()["position_key"] == (
        "futures_position:runtime:BIP-20DEC30-CDE"
    )
    assert detail_response.json()["live_coinbase_orders_ran"] is False


@pytest.mark.regression
def test_admin_api_futures_read_service_maps_runtime_positions_without_spot_rules(
    monkeypatch,
):
    from application.admin_api.read_service import AdminApiReadService

    class FakeOrderBook:
        products = {
            "BIP-20DEC30-CDE": {
                "product_id": "BIP-20DEC30-CDE",
                "product_type": "FUTURE",
                "display_name": "BTC PERP",
                "price_increment": "5",
                "base_increment": "1",
                "future_product_details": {"contract_size": "0.01"},
            },
            "BTC-USDC": {
                "product_id": "BTC-USDC",
                "product_type": "SPOT",
            },
        }
        mandatory_fee_per_contract = {
            "BIP-20DEC30-CDE": {"mandatory_fee_per_contract": "0.34"}
        }

        def snapshot_positions(self):
            return {
                "FUTURE": {
                    "BIP-20DEC30-CDE": {
                        "product_id": "BIP-20DEC30-CDE",
                        "side": "LONG",
                        "number_of_contracts": "2",
                        "entry_price": "100000.00",
                        "current_price": "100250.00",
                        "unrealized_pnl": {"value": "5.00", "currency": "USD"},
                    }
                }
            }

    class FakeFeeManager:
        def get_fee_info(self, product_id=None):
            return {
                "margin_window_type": "FCM_MARGIN_WINDOW_TYPE_OVERNIGHT",
                "overnight_margin_active": True,
                "profit_validation_fee_rate": 0.001,
                "target_movement_factor": 0.85,
            }

    import dashboard_server

    monkeypatch.setattr(
        dashboard_server,
        "stealth_order_bridge",
        SimpleNamespace(
            order_engine=SimpleNamespace(
                orderbook=FakeOrderBook(),
                fee_manager=FakeFeeManager(),
            )
        ),
    )

    service = AdminApiReadService()
    account = service.build_futures_account()
    positions = service.build_futures_positions(limit=10, offset=0)
    detail = service.build_futures_position_detail(
        position_key="futures_position:runtime:BIP-20DEC30-CDE"
    )

    assert account.type == "admin_futures_account"
    assert account.command_routes_mode == "not_modeled"
    assert "BIP-20DEC30-CDE" in account.configured_product_scope
    assert "BTC-USDC" not in account.configured_product_scope
    assert account.observed_position_scope == ["BIP-20DEC30-CDE"]
    assert account.margin.status.value == "observed"
    assert account.margin.value["margin_window_type"] == (
        "FCM_MARGIN_WINDOW_TYPE_OVERNIGHT"
    )
    assert account.collateral.status.value == "unavailable"
    assert account.funding.status.value == "not_modeled"
    assert account.live_coinbase_orders_ran is False

    assert positions.count == 1
    item = positions.items[0]
    assert item.position_key == "futures_position:runtime:BIP-20DEC30-CDE"
    assert item.product_id == "BIP-20DEC30-CDE"
    assert item.product_type == "FUTURE"
    assert item.position_side == "LONG"
    assert item.open_order_side == "BUY"
    assert item.close_order_side == "SELL"
    assert item.reduce_only_order_side == "SELL"
    assert item.close_only_order_side == "SELL"
    assert item.position_pnl == {"unrealized_pnl": {"value": "5.00", "currency": "USD"}}
    dumped = item.model_dump(mode="json")
    assert "client_order_id" not in dumped
    assert "cost_basis" not in dumped
    assert detail.found is True
    assert detail.position is not None
    assert detail.position.position_key == item.position_key


@pytest.mark.regression
def test_admin_api_futures_dashboard_fallback_does_not_promote_unknown_spot_rows(
    monkeypatch,
):
    from application.admin_api.read_service import AdminApiReadService

    import dashboard_server

    monkeypatch.setattr(dashboard_server, "stealth_order_bridge", None)
    with dashboard_server.state_lock:
        previous_positions = dashboard_server.engine_state.get("positions")
        dashboard_server.engine_state["positions"] = {
            "BTC-USDC": {
                "product_id": "BTC-USDC",
                "side": "LONG",
                "number_of_contracts": "2",
            },
            "BIP-20DEC30-CDE": {
                "product_id": "BIP-20DEC30-CDE",
                "product_type": "FUTURE",
                "side": "LONG",
                "number_of_contracts": "1",
            },
        }

    try:
        response = AdminApiReadService().build_futures_positions(limit=10, offset=0)
    finally:
        with dashboard_server.state_lock:
            if previous_positions is None:
                dashboard_server.engine_state.pop("positions", None)
            else:
                dashboard_server.engine_state["positions"] = previous_positions

    assert response.count == 1
    assert response.items[0].product_id == "BIP-20DEC30-CDE"
    assert response.items[0].product_type.value == "FUTURE"
    dumped = response.model_dump(mode="json")
    assert "BTC-USDC" not in str(dumped)


@pytest.mark.regression
def test_admin_api_guard_risk_policy_route_uses_read_service_without_commands(
    monkeypatch,
):
    from api.v1.routes import admin as admin_routes

    client = _client(monkeypatch)
    captured: dict[str, str | None] = {}

    def build_guard_risk_policy(product_id=None):
        captured["product_id"] = product_id
        return {
            "type": "admin_guard_risk_policy",
            "filters": {"product_id": product_id},
            "action_condition_policy": {
                "name": "action_condition_policy",
                "status": "observed",
                "source": "action_condition_guard",
                "value": {"policy_configured": True},
            },
            "configured_limit_rules": [
                {
                    "policy_id": "spot_cap",
                    "enabled": True,
                    "product_type": "SPOT",
                    "side": "BUY",
                    "phases": ["planning"],
                    "max_notional": "25",
                    "raw_rule": {"name": "spot_cap"},
                }
            ],
            "live_execution_gate": {
                "name": "live_execution_gate",
                "status": "fail_closed",
                "source": "live_execution_gate",
                "value": {"allowed": False},
            },
            "product_capability_policy": {
                "name": "product_capability_policy",
                "status": "observed",
                "source": "product_capability_policy",
                "value": {"decision_product_id": product_id},
            },
            "product_capability_decisions": [
                {
                    "product_id": "BTC-USDC",
                    "product_type": "SPOT",
                    "capability": "direct_placement",
                    "mode": "enabled",
                    "allowed": True,
                    "reason": "direct placement enabled",
                }
            ],
            "profitability_policy": {
                "name": "profitability_policy",
                "status": "observed",
                "source": "profit_validator",
                "value": {"browser_calculation_allowed": False},
            },
            "authority_sources": [
                {
                    "name": "wallet_authority",
                    "status": "observed",
                    "source": "action_condition_guard",
                    "value": {"coinbase_wallet_fetch_performed": False},
                }
            ],
            "rejection_categories": [
                {
                    "condition": "wallet_available",
                    "source": "action_condition_guard",
                    "applies_to_product_type": "SPOT",
                    "blocks_before_exchange": True,
                    "detail": "backend wallet guard",
                }
            ],
            "read_only": True,
            "command_routes_mode": "not_modeled",
            "live_coinbase_orders_ran": False,
            "live_coinbase_read_ran": False,
        }

    service = SimpleNamespace(build_guard_risk_policy=build_guard_risk_policy)
    client.app.dependency_overrides[admin_routes.get_read_service] = lambda: service

    response = client.get(
        "/api/v1/admin/guard-risk-policy?product_id=BTC-USDC",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )

    assert response.status_code == 200
    payload = response.json()
    assert captured["product_id"] == "BTC-USDC"
    assert payload["read_only"] is True
    assert payload["command_routes_mode"] == "not_modeled"
    assert payload["live_coinbase_orders_ran"] is False
    assert payload["live_coinbase_read_ran"] is False
    assert payload["live_execution_gate"]["status"] == "fail_closed"
    assert payload["configured_limit_rules"][0]["policy_id"] == "spot_cap"
    assert payload["product_capability_decisions"][0]["capability"] == (
        "direct_placement"
    )


@pytest.mark.regression
def test_admin_api_guard_risk_policy_read_service_reports_backend_authority_without_wallet_fetch(
    monkeypatch,
):
    import configuration
    import core.action_condition_guard as guard_module
    from application.admin_api.read_service import AdminApiReadService

    monkeypatch.setattr(
        configuration,
        "ACTION_CONDITION_GUARDS",
        {
            "wallet_available": {"enabled": True, "block_without_credentials": True},
            "known_inventory_available": {
                "enabled": True,
                "phases": ["planning"],
            },
            "limits": [
                {
                    "name": "spot_buy_cap",
                    "product_type": "SPOT",
                    "side": "BUY",
                    "max_notional": "25",
                    "phases": ["planning"],
                },
                {
                    "name": "future_contract_cap",
                    "product_type": "FUTURE",
                    "max_base_size": "10",
                    "phases": ["planning", "reveal"],
                },
            ],
        },
        raising=False,
    )
    monkeypatch.setattr(
        configuration,
        "PRODUCT_CAPABILITIES",
        {"product_type": {"SPOT": {"move_revealed": "disabled"}}},
        raising=False,
    )
    monkeypatch.setattr(
        guard_module,
        "fetch_account_wallets",
        lambda: (_ for _ in ()).throw(AssertionError("wallet fetch not allowed")),
    )

    response = AdminApiReadService().build_guard_risk_policy(
        product_id="BTC-USDC"
    )

    assert response.type == "admin_guard_risk_policy"
    assert response.read_only is True
    assert response.live_coinbase_orders_ran is False
    assert response.live_coinbase_read_ran is False
    assert response.action_condition_policy.source == "action_condition_guard"
    assert response.action_condition_policy.value["policy_configured"] is True
    assert response.action_condition_policy.value["coinbase_wallet_fetch_performed"] is False
    assert response.live_execution_gate.status == "fail_closed"
    assert response.live_execution_gate.value["allowed"] is False
    assert response.live_execution_gate.value["cap_evaluation_required"] is True
    assert {rule.policy_id for rule in response.configured_limit_rules} == {
        "spot_buy_cap",
        "future_contract_cap",
    }
    assert any(
        decision.capability == "direct_placement"
        for decision in response.product_capability_decisions
    )
    assert response.profitability_policy.value["browser_calculation_allowed"] is False
    assert "futures_margin_validation" in (
        response.profitability_policy.value["known_contract_gaps"]
    )
    authority = {item.name: item for item in response.authority_sources}
    assert authority["wallet_authority"].value["coinbase_wallet_fetch_performed"] is False
    assert authority["spot_known_inventory_authority"].source == (
        "spot_inventory_authority"
    )
    rejection_conditions = {item.condition for item in response.rejection_categories}
    assert "wallet_available" in rejection_conditions
    assert "known_inventory_available" in rejection_conditions


@pytest.mark.regression
def test_admin_api_guard_risk_policy_surfaces_capability_evaluation_errors(
    monkeypatch,
):
    import core.product_capability as capability_module
    from application.admin_api.read_service import AdminApiReadService

    def fail_evaluate_product_capability(*args, **kwargs):
        raise RuntimeError("capability evaluator unavailable")

    monkeypatch.setattr(
        capability_module,
        "evaluate_product_capability",
        fail_evaluate_product_capability,
    )

    response = AdminApiReadService().build_guard_risk_policy(
        product_id="BTC-USDC"
    )

    assert response.product_capability_decisions == []
    assert response.product_capability_policy.status == "unavailable"
    assert response.product_capability_policy.value["decision_count"] == 0
    assert response.product_capability_policy.value["decision_error_count"] >= 1
    assert any(
        "capability evaluator unavailable" in error
        for error in response.product_capability_policy.value["decision_errors"]
    )
    assert response.live_coinbase_orders_ran is False
    assert response.live_coinbase_read_ran is False


@pytest.mark.regression
def test_admin_api_audit_workbench_route_uses_read_service_without_commands(
    monkeypatch,
):
    from api.v1.routes import admin as admin_routes

    client = _client(monkeypatch)
    captured: dict[str, object] = {}

    def build_audit_workbench(**kwargs):
        captured.update(kwargs)
        return {
            "type": "admin_audit_workbench",
            "filters": kwargs,
            "module_summary": [
                {
                    "module": "orders",
                    "read_route_count": 2,
                    "command_route_count": 2,
                    "live_enabled": False,
                    "primary_identity": "client_order_id",
                    "evidence_sources": ["route_inventory", "order_parent"],
                    "routes": ["/api/v1/orders"],
                    "notes": "Order audit links use client_order_id.",
                }
            ],
            "events": [
                {
                    "event_id": "audit-001",
                    "module": "orders",
                    "source": "admin_api_audit_log",
                    "action_class": "live_exchange_cancel",
                    "endpoint": "/api/v1/orders/client-abc/cancel",
                    "status": "not_implemented",
                    "actor_id": "operator-001",
                    "permission": "order:cancel",
                    "client_order_id": "client-abc",
                    "correlation_id": "corr-001",
                    "audit_id": "audit-001",
                    "request_id": "corr-001",
                    "exchange_order_id_evidence_only": True,
                    "live_coinbase_orders_ran": False,
                    "raw_event": {},
                }
            ],
            "pagination": {
                "limit": kwargs["limit"],
                "offset": kwargs["offset"],
                "returned_count": 1,
                "total_matching_count": 1,
                "next_offset": None,
                "has_more": False,
            },
            "read_only": True,
            "command_routes_mode": "evidence_only",
            "live_coinbase_orders_ran": False,
            "live_coinbase_read_ran": False,
        }

    service = SimpleNamespace(build_audit_workbench=build_audit_workbench)
    client.app.dependency_overrides[admin_routes.get_read_service] = lambda: service

    response = client.get(
        "/api/v1/admin/audit-workbench"
        "?module=orders&product_id=BTC-USDC&client_order_id=client-abc"
        "&correlation_id=corr-001&audit_id=audit-001&limit=10&offset=5",
        headers=_headers(roles=AdminApiRole.AUDITOR.value),
    )

    assert response.status_code == 200
    assert captured == {
        "module": AdminAuditWorkbenchModule.ORDERS,
        "product_id": "BTC-USDC",
        "client_order_id": "client-abc",
        "correlation_id": "corr-001",
        "audit_id": "audit-001",
        "limit": 10,
        "offset": 5,
    }
    payload = response.json()
    assert payload["read_only"] is True
    assert payload["command_routes_mode"] == "evidence_only"
    assert payload["live_coinbase_orders_ran"] is False
    assert payload["live_coinbase_read_ran"] is False
    assert payload["events"][0]["client_order_id"] == "client-abc"
    assert "order_id" not in payload["events"][0]


@pytest.mark.regression
def test_admin_api_audit_workbench_read_service_normalizes_cross_module_evidence(
    monkeypatch,
):
    import database.order as order_module
    from application.admin_api.audit import AdminApiAuditEvent, FileAdminApiAuditStore
    from application.admin_api.read_service import AdminApiReadService

    audit_path = _store_dir() / "audit.jsonl"
    audit_store = FileAdminApiAuditStore(audit_path)
    audit_store.append(
        AdminApiAuditEvent(
            actor_id="operator-001",
            action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
            permission=AdminApiPermission.ORDER_CANCEL,
            endpoint="/api/v1/orders/client-abc/cancel",
            request_id="corr-001",
            operator_intent="manual_one_off",
            idempotency_key="idem-001",
            client_order_id="client-abc",
            coinbase_order_id="exchange-evidence-001",
            status=AdminApiCommandStatus.NOT_IMPLEMENTED,
            failure_stage="approval",
            message="cancel live disabled",
        )
    )
    monkeypatch.setenv("COINBASE_ADMIN_API_AUDIT_LOG_PATH", str(audit_path))
    monkeypatch.setattr(
        order_module,
        "get_parent_orders",
        lambda: [
            {
                "client_order_id": "client-abc",
                "product_id": "BTC-USDC",
                "status": "OPEN",
                "exchange_order_id": "exchange-evidence-001",
                "correlation_id": "corr-001",
                "audit_id": "audit-order-001",
                "updated_at": "2026-06-11T12:00:00Z",
            }
        ],
    )

    response = AdminApiReadService().build_audit_workbench(
        module=AdminAuditWorkbenchModule.ORDERS,
        client_order_id="client-abc",
        correlation_id="corr-001",
        limit=10,
        offset=0,
    )

    assert response.type == "admin_audit_workbench"
    assert response.read_only is True
    assert response.live_coinbase_orders_ran is False
    assert response.live_coinbase_read_ran is False
    assert response.pagination.total_matching_count == 2
    modules = {item.module for item in response.module_summary}
    assert AdminAuditWorkbenchModule.ORDERS in modules
    assert AdminAuditWorkbenchModule.FUTURES_PERPETUALS in modules
    events_by_source = {item.source: item for item in response.events}
    assert events_by_source[AdminAuditEvidenceSource.ADMIN_API_AUDIT_LOG].audit_id
    assert events_by_source[AdminAuditEvidenceSource.ADMIN_API_AUDIT_LOG].request_id == (
        "corr-001"
    )
    assert (
        events_by_source[AdminAuditEvidenceSource.ADMIN_API_AUDIT_LOG].operator_intent
        == "manual_one_off"
    )
    assert events_by_source[AdminAuditEvidenceSource.ORDER_PARENT].client_order_id == (
        "client-abc"
    )
    for event in response.events:
        assert event.exchange_order_id_evidence_only is True
        assert event.live_coinbase_orders_ran is False
        assert "order_id" not in event.model_dump(mode="json")


@pytest.mark.regression
def test_admin_api_audit_workbench_preserves_movement_client_alias_filters(
    monkeypatch,
):
    from application.admin_api import read_service as read_service_module
    from application.admin_api.read_service import AdminApiReadService

    def fake_query(query, params=None):
        if "FROM order_moves" in query:
            return [
                {
                    "id": 1,
                    "original_parent_client_order_id": "parent-old",
                    "new_parent_client_order_id": "parent-new",
                    "move_on_cancel": False,
                    "created_at": "2026-06-11T11:00:00Z",
                    "moved_at": "2026-06-11T11:01:00Z",
                }
            ], None
        if "FROM stealth_order_moves" in query:
            return [], None
        if "FROM stealth_orders" in query:
            return [], None
        return [], None

    monkeypatch.setattr(read_service_module, "_query_admin_rows", fake_query)
    monkeypatch.setattr(read_service_module, "_parent_order_row", lambda client_order_id: {
        "client_order_id": client_order_id,
        "product_id": "BTC-USDC",
        "side": "BUY",
    })

    response = AdminApiReadService().build_audit_workbench(
        module=AdminAuditWorkbenchModule.MOVEMENT_REPRICING,
        client_order_id="parent-new",
        limit=10,
        offset=0,
    )

    assert response.pagination.total_matching_count == 1
    event = response.events[0]
    assert event.module == AdminAuditWorkbenchModule.MOVEMENT_REPRICING
    assert event.client_order_id == "parent-old"
    assert event.raw_event["new_parent_client_order_id"] == "parent-new"
    assert event.exchange_order_id_evidence_only is True
    assert "order_id" not in event.model_dump(mode="json")


@pytest.mark.regression
def test_admin_api_route_inventory_names_required_shared_methods_and_doc():
    rows = {item.surface: item for item in ADMIN_API_ROUTE_INVENTORY}
    doc = ROUTE_INVENTORY_DOC.read_text(encoding="utf-8")

    assert rows["POST /api/v1/orders"].shared_method == "place_manual_order"
    assert rows["POST /api/v1/orders"].action_class == AdminApiActionClass.LIVE_EXCHANGE_PLACE
    assert rows["POST /api/v1/orders/{client_order_id}/cancel"].shared_method == (
        "cancel_order_by_client_order_id"
    )
    assert rows["POST /api/v1/orders/{client_order_id}/cancel"].action_class == (
        AdminApiActionClass.LIVE_EXCHANGE_CANCEL
    )
    assert rows["GET /api/v1/orders"].shared_method == "build_order_list"
    assert rows["GET /api/v1/orders/{client_order_id}"].shared_method == (
        "build_order_detail"
    )
    assert rows["GET /api/v1/stealth/orders"].shared_method == (
        "build_stealth_order_list"
    )
    assert rows["GET /api/v1/stealth/orders/{stealth_order_id}"].shared_method == (
        "build_stealth_order_detail"
    )
    assert rows["POST /api/v1/stealth/orders/{stealth_order_id}/cancel"].shared_method == (
        "cancel_stealth_order_by_stealth_order_id"
    )
    assert rows["POST /api/v1/stealth/orders/{stealth_order_id}/cancel"].action_class == (
        AdminApiActionClass.LIVE_EXCHANGE_CANCEL
    )
    assert rows["GET /api/v1/movement-repricing/evidence"].shared_method == (
        "build_movement_repricing_evidence"
    )
    assert rows[
        "GET /api/v1/movement-repricing/orders/{client_order_id}"
    ].shared_method == "build_movement_repricing_order_detail"
    assert rows[
        "GET /api/v1/movement-repricing/stealth/{stealth_order_id}"
    ].shared_method == "build_movement_repricing_stealth_detail"
    assert rows[
        "POST /api/v1/movement-repricing/stealth/{stealth_order_id}/reprice"
    ].shared_method == "reprice_stealth_order_by_stealth_order_id"
    assert rows[
        "POST /api/v1/movement-repricing/stealth/{stealth_order_id}/reprice"
    ].action_class == AdminApiActionClass.LIVE_EXCHANGE_CANCEL
    assert rows["GET /api/v1/futures/account"].shared_method == (
        "build_futures_account"
    )
    assert rows["GET /api/v1/futures/positions"].shared_method == (
        "build_futures_positions"
    )
    assert rows["GET /api/v1/futures/positions/{position_key}"].shared_method == (
        "build_futures_position_detail"
    )
    assert rows["GET /api/v1/admin/guard-risk-policy"].shared_method == (
        "build_guard_risk_policy"
    )
    assert rows["GET /api/v1/admin/audit-workbench"].shared_method == (
        "build_audit_workbench"
    )
    assert rows["GET /api/v1/admin/audit-workbench"].permission == (
        AdminApiPermission.AUDIT_READ
    )
    assert rows["POST /api/v1/spot/campaign/executions"].shared_method == (
        "execute_spot_campaign"
    )
    assert rows["GET /api/v1/admin/bootstrap"].shared_method == "build_admin_bootstrap"
    assert rows["GET /api/v1/admin/oidc-readiness"].shared_method == (
        "build_oidc_jwt_readiness"
    )
    assert rows["GET /api/v1/admin/capabilities"].shared_method == (
        "build_admin_capabilities"
    )
    assert rows["GET /api/v1/admin/csrf"].shared_method == "build_csrf_contract"
    assert rows["GET /api/v1/admin/live-enablement"].shared_method == (
        "build_live_enablement"
    )
    assert rows["GET /api/v1/admin/enterprise-readiness"].shared_method == (
        "build_enterprise_readiness"
    )
    assert rows["place_hotpoint_test_order WebSocket"].shared_method == (
        "place_hotpoint_test_order"
    )
    assert rows["place_hotpoint_test_order WebSocket"].action_class == (
        AdminApiActionClass.LIVE_EXCHANGE_PLACE
    )
    assert "compatibility_only" in doc
    assert "cancel_order_by_client_order_id" in doc
    assert "place_manual_order" in doc
    assert "place_hotpoint_test_order" in doc
    assert "execute_spot_campaign" in doc
    assert "build_admin_bootstrap" in doc
    assert "build_oidc_jwt_readiness" in doc
    assert "build_csrf_contract" in doc
    assert "build_live_enablement" in doc
    assert "build_enterprise_readiness" in doc
    assert "build_order_list" in doc
    assert "build_stealth_order_list" in doc
    assert "build_stealth_order_detail" in doc
    assert "cancel_stealth_order_by_stealth_order_id" in doc
    assert "build_movement_repricing_evidence" in doc
    assert "build_movement_repricing_order_detail" in doc
    assert "build_movement_repricing_stealth_detail" in doc
    assert "reprice_stealth_order_by_stealth_order_id" in doc
    assert "build_futures_account" in doc
    assert "build_futures_positions" in doc
    assert "build_futures_position_detail" in doc
    assert "build_guard_risk_policy" in doc
    assert "build_audit_workbench" in doc


@pytest.mark.regression
def test_admin_api_route_inventory_and_openapi_paths_stay_in_sync():
    schema = generate_openapi_schema(OPENAPI_PATH)
    inventory_http_surfaces = {
        item.surface
        for item in ADMIN_API_ROUTE_INVENTORY
        if item.surface.split(" ", 1)[0] in {"GET", "POST", "PUT", "PATCH", "DELETE"}
    }
    schema_http_surfaces = {
        f"{method.upper()} {path}"
        for path, operations in schema["paths"].items()
        for method in operations
        if method in {"get", "post", "put", "patch", "delete"}
    }

    assert "GET /api/v1/admin/oidc-readiness" in inventory_http_surfaces
    assert "GET /api/v1/admin/oidc-readiness" in schema_http_surfaces
    assert "GET /api/v1/stealth/orders" in inventory_http_surfaces
    assert "GET /api/v1/stealth/orders" in schema_http_surfaces
    assert "GET /api/v1/movement-repricing/evidence" in inventory_http_surfaces
    assert "GET /api/v1/movement-repricing/evidence" in schema_http_surfaces
    assert (
        "POST /api/v1/movement-repricing/stealth/{stealth_order_id}/reprice"
        in inventory_http_surfaces
    )
    assert (
        "POST /api/v1/movement-repricing/stealth/{stealth_order_id}/reprice"
        in schema_http_surfaces
    )
    assert "GET /api/v1/futures/account" in inventory_http_surfaces
    assert "GET /api/v1/futures/account" in schema_http_surfaces
    assert "GET /api/v1/futures/positions" in inventory_http_surfaces
    assert "GET /api/v1/futures/positions" in schema_http_surfaces
    assert "GET /api/v1/futures/positions/{position_key}" in inventory_http_surfaces
    assert "GET /api/v1/futures/positions/{position_key}" in schema_http_surfaces
    assert "GET /api/v1/admin/guard-risk-policy" in inventory_http_surfaces
    assert "GET /api/v1/admin/guard-risk-policy" in schema_http_surfaces
    assert "GET /api/v1/admin/audit-workbench" in inventory_http_surfaces
    assert "GET /api/v1/admin/audit-workbench" in schema_http_surfaces
    assert "GET /api/v1/admin/enterprise-readiness" in inventory_http_surfaces
    assert "GET /api/v1/admin/enterprise-readiness" in schema_http_surfaces
    assert schema_http_surfaces == inventory_http_surfaces
