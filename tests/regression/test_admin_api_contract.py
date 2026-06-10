from __future__ import annotations

import inspect
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from api.v1.app import create_app
from application.admin_api import command_service
from application.admin_api.idempotency import (
    IdempotencyRecord,
    evaluate_idempotency,
    make_payload_hash,
)
from application.admin_api.route_inventory import ADMIN_API_ROUTE_INVENTORY
from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiIdempotencyDecision,
    AdminApiPermission,
)
from tools.generate_admin_api_openapi import generate_openapi_schema


ROOT = Path(__file__).resolve().parents[2]
OPENAPI_PATH = ROOT / "openapi" / "coinbase-admin-api.yaml"
ROUTE_INVENTORY_DOC = ROOT / "docs" / "plans" / "ADMIN_API_ROUTE_INVENTORY.md"


def _headers() -> dict[str, str]:
    return {
        "Idempotency-Key": "idem-001",
        "X-Correlation-Id": "corr-001",
        "X-Operator-Intent": "manual_one_off",
        "X-Admin-Actor": "operator-001",
    }


@pytest.mark.regression
def test_admin_api_openapi_schema_file_matches_generated_contract():
    generated = generate_openapi_schema(OPENAPI_PATH)
    written = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))

    assert written == generated
    assert "/api/v1/orders" in written["paths"]
    assert "/api/v1/orders/{client_order_id}/cancel" in written["paths"]
    assert written["info"]["title"] == "Coinbase Admin API"


@pytest.mark.regression
def test_admin_api_create_manual_order_contract_is_not_implemented_and_not_live():
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/orders",
        headers=_headers(),
        json={
            "product_id": "BTC-USDC",
            "side": "BUY",
            "order_type": "LIMIT",
            "quote_size": "1.00",
            "limit_price": "65000.00",
            "manual_live_acknowledgement": True,
        },
    )

    assert response.status_code == 501
    payload = response.json()
    assert payload["status"] == AdminApiCommandStatus.NOT_IMPLEMENTED.value
    assert payload["action_class"] == AdminApiActionClass.LIVE_EXCHANGE_PLACE.value
    assert payload["required_permission"] == AdminApiPermission.ORDER_CREATE.value
    assert payload["service_method"] == "place_manual_order"
    assert payload["live_exchange_submitted"] is False
    assert response.headers["x-correlation-id"] == "corr-001"


@pytest.mark.regression
def test_admin_api_cancel_contract_is_keyed_by_client_order_id():
    client = TestClient(create_app())

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
def test_admin_api_skeleton_has_no_direct_dashboard_or_coinbase_path():
    service_source = inspect.getsource(command_service)
    route_source = inspect.getsource(__import__("api.v1.routes.orders", fromlist=[""]))

    forbidden_tokens = [
        "dashboard_server",
        "REST_CLIENT",
        "CoinbaseRestClient",
        "external.coinbase",
        "create_order(",
        "limit_order_gtc(",
        "cancel_orders(",
    ]
    for token in forbidden_tokens:
        assert token not in service_source
        assert token not in route_source


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
    assert "compatibility_only" in doc
    assert "cancel_order_by_client_order_id" in doc
    assert "place_manual_order" in doc
