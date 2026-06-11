from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import yaml
from fastapi.testclient import TestClient

from api.v1.app import create_app
from application.admin_api.auth import actor_has_permission
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
    AdminApiCommandStatus,
    AdminApiErrorCode,
    AdminApiIdempotencyDecision,
    AdminApiPermission,
    AdminApiRole,
)
from tools.generate_admin_api_openapi import generate_openapi_schema


ROOT = Path(__file__).resolve().parents[2]
OPENAPI_PATH = ROOT / "openapi" / "coinbase-admin-api.yaml"
ROUTE_INVENTORY_DOC = ROOT / "docs" / "plans" / "ADMIN_API_ROUTE_INVENTORY.md"


def _headers(
    *,
    idempotency_key: str = "idem-001",
    roles: str = AdminApiRole.TRADER.value,
) -> dict[str, str]:
    return {
        "Authorization": "Bearer test-admin-token",
        "Idempotency-Key": idempotency_key,
        "X-Correlation-Id": "corr-001",
        "X-Operator-Intent": "manual_one_off",
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


@pytest.mark.regression
def test_admin_api_openapi_schema_file_matches_generated_contract():
    generated = generate_openapi_schema(OPENAPI_PATH)
    written = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))

    assert written == generated
    assert "/api/v1/orders" in written["paths"]
    assert "/api/v1/orders/{client_order_id}" in written["paths"]
    assert "/api/v1/orders/{client_order_id}/cancel" in written["paths"]
    assert "/api/v1/spot/campaign/executions" in written["paths"]
    assert "/api/v1/admin/bootstrap" in written["paths"]
    assert "/api/v1/admin/health" in written["paths"]
    assert "/api/v1/admin/session" in written["paths"]
    assert "/api/v1/admin/capabilities" in written["paths"]
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
    for header_name in ("Authorization", "X-Admin-Actor", "X-Admin-Roles"):
        assert header_params[header_name]["required"] is True
    for status_code in ("200", "400", "401", "403", "409", "501"):
        assert status_code in order_operation["responses"]
    cancel_operation = written["paths"]["/api/v1/orders/{client_order_id}/cancel"][
        "post"
    ]
    assert "200" in cancel_operation["responses"]
    assert "501" in cancel_operation["responses"]
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
    route_source = inspect.getsource(__import__("api.v1.routes.orders", fromlist=[""]))
    import dashboard_server

    dashboard_source = inspect.getsource(dashboard_server.handle_client_message)

    route_forbidden_tokens = [
        "REST_CLIENT",
        "CoinbaseRestClient",
        "external.coinbase",
        "create_order(",
        "limit_order_gtc(",
        "cancel_orders(",
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
    release_gate = client.get("/api/v1/admin/release-gate", headers=headers)

    assert bootstrap.status_code == 200
    assert bootstrap.json()["backend_repository"] == "s-aws/coinbase"
    assert bootstrap.json()["mutating_routes_live_disabled"] is True
    assert bootstrap.json()["live_coinbase_orders_ran"] is False
    assert health.status_code == 200
    assert health.json()["failed_route_count"] == 0
    assert health.json()["live_coinbase_orders_ran"] is False
    assert session.status_code == 200
    assert AdminApiPermission.AUDIT_READ.value in session.json()["permissions"]
    assert session.json()["bearer_token_visible_to_browser"] is False
    assert capabilities.status_code == 200
    routes = {item["route"] for item in capabilities.json()["capabilities"]}
    assert "/api/v1/spot/campaign/executions" in routes
    assert "/api/v1/admin/bootstrap" in routes
    assert release_gate.status_code == 200
    assert release_gate.json()["live_coinbase_orders_ran"] is False


@pytest.mark.regression
def test_admin_api_order_read_routes_use_read_service_and_client_order_id(monkeypatch):
    from api.v1.routes import orders as order_routes

    client = _client(monkeypatch)
    service = SimpleNamespace(
        build_order_list=lambda product_id=None, status=None, limit=100: {
            "type": "admin_order_list",
            "filters": {
                "product_id": product_id,
                "status": status,
                "limit": limit,
            },
            "count": 1,
            "items": [
                {
                    "client_order_id": "client-abc",
                    "product_id": "BTC-USDC",
                    "exchange_order_id": "coinbase-evidence-001",
                    "exchange_order_id_evidence_only": True,
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
            },
            "read_only": True,
            "live_coinbase_orders_ran": False,
        },
    )
    client.app.dependency_overrides[order_routes.get_read_service] = lambda: service

    list_response = client.get(
        "/api/v1/orders?product_id=BTC-USDC&order_status=OPEN&limit=10",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    detail_response = client.get(
        "/api/v1/orders/client-abc",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )

    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["client_order_id"] == "client-abc"
    assert list_response.json()["items"][0]["exchange_order_id_evidence_only"] is True
    assert "order_id" not in list_response.json()["items"][0]
    assert detail_response.status_code == 200
    assert detail_response.json()["client_order_id"] == "client-abc"
    assert "order_id" not in detail_response.json()["order"]


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
    assert rows["POST /api/v1/spot/campaign/executions"].shared_method == (
        "execute_spot_campaign"
    )
    assert rows["GET /api/v1/admin/bootstrap"].shared_method == "build_admin_bootstrap"
    assert rows["GET /api/v1/admin/capabilities"].shared_method == (
        "build_admin_capabilities"
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
    assert "build_order_list" in doc
