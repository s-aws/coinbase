from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from api.v1.routes import spot as spot_routes
from application.admin_api.auth import get_authenticated_actor
from application.admin_api.models import (
    AdminApiActor,
    AdminProductReadItem,
    SpotReadinessResponse,
)
from application.admin_api.read_service import AdminApiReadService
from application.admin_api.mvp_service import (
    AdminMvpDependencies,
    AdminMvpService,
    AdminMvpStore,
)
from core.enums import AdminApiRole
from tests.unit.test_admin_api_account_reality_refresh import (
    PRIVATE_PORTFOLIO_UUID,
    _StrictReadClient,
    _context,
    _service,
)


def test_installed_spot_readiness_projects_durable_refresh_without_new_calls(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID",
        PRIVATE_PORTFOLIO_UUID,
    )
    client = _StrictReadClient()
    mvp_service = _service(tmp_path, client)
    refresh = mvp_service.refresh_account_reality(
        {"reason": "synthetic route contract fixture"},
        _context(idempotency_key="spot-readiness-route-refresh"),
    )
    calls_after_refresh = list(client.calls)
    assert refresh.body["status"] == "ready"
    assert refresh.body["products"][0]["status"] == "ONLINE"

    product_read = mvp_service.get_read_response(
        "/api/v1/admin/products",
        {"product_id": ["BTC-USDC"]},
        _context(idempotency_key="spot-readiness-product-read"),
    ).body
    assert product_read["products"][0]["status"] == "ONLINE"
    assert client.calls == calls_after_refresh

    app = FastAPI()
    app.include_router(spot_routes.router, prefix="/api/v1")
    app.dependency_overrides[get_authenticated_actor] = lambda: AdminApiActor(
        actor_id="spot-readiness-viewer",
        roles=[AdminApiRole.VIEWER],
    )
    app.dependency_overrides[spot_routes.get_read_service] = lambda: (
        AdminApiReadService(mvp_service=mvp_service)
    )

    response = TestClient(app).get(
        "/api/v1/spot/readiness?product_id=BTC-USDC"
    )

    assert response.status_code == 200
    assert client.calls == calls_after_refresh
    body = response.json()
    assert body["type"] == "spot_readiness"
    assert body["status"] == "ready"
    assert body["account_reality"]["status"] == "ready"
    assert body["account_reality"]["source"] == "backend_rest_client"
    assert body["account_reality"]["coinbase_read_ran"] is False
    assert body["account_reality"]["proof_origin_coinbase_read_ran"] is True
    assert "BTC-USDC" in body["account_scope"]["configured_product_scope"]
    assert body["portfolio_scope"]["portfolio_name"] == "Test"
    assert body["portfolio_scope"]["portfolio_id"] == "withheld"
    assert body["spot_admission_input"]["status"] == "ready"
    assert body["wallet_snapshot"]["available"] is True
    assert body["wallet_snapshot"]["backend_owned"] is True
    assert body["products"] == [
        {
            **body["products"][0],
            "product_id": "BTC-USDC",
            "product_type": "SPOT",
            "product_family": "spot",
            "product_read_status": "ready",
            "backend_owned": True,
        }
    ]
    assert (
        body["products"][0]["capabilities"]["product_capability_contract"][
            "mode"
        ]
        == "enabled"
    )
    assert body["live_coinbase_read_ran"] is False
    assert PRIVATE_PORTFOLIO_UUID not in json.dumps(body, sort_keys=True)
    SpotReadinessResponse.model_validate(body)


def test_spot_readiness_openapi_model_declares_operator_projection() -> None:
    properties = SpotReadinessResponse.model_json_schema()["properties"]

    assert {
        "account_reality",
        "account_scope",
        "portfolio_scope",
        "account_readiness",
        "spot_admission_input",
        "products",
        "configured_product_scope",
        "captured_at",
        "fresh_until",
        "wallet_snapshot",
        "action_guard_summary",
        "coinbase_read_enabled",
        "live_coinbase_read_ran",
        "external_state_refresh_available",
        "external_state_refresh_route",
    } <= set(properties)

    product_status_schema = AdminProductReadItem.model_json_schema()[
        "properties"
    ]["status"]
    status_enums = [
        set(branch.get("enum", []))
        for branch in product_status_schema["anyOf"]
    ]
    assert {"ONLINE", "OFFLINE", "DELISTED", "UNKNOWN"} in status_enums
    AdminProductReadItem.model_validate(
        {"product_id": "BTC-USDC", "status": "ONLINE"}
    )
    with pytest.raises(ValueError):
        AdminProductReadItem.model_validate(
            {"product_id": "BTC-USDC", "status": "online"}
        )


def test_installed_spot_readiness_preserves_empty_discovered_scope_call_free() -> None:
    class _PoisonClient:
        def __getattr__(self, name: str):
            raise AssertionError(f"ordinary Spot readiness called {name}")

    mvp_service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=_PoisonClient(),
            rest_client_available=True,
            now_factory=lambda: datetime(
                2026,
                7,
                20,
                12,
                0,
                tzinfo=timezone.utc,
            ),
        ),
        store=AdminMvpStore(),
    )
    app = FastAPI()
    app.include_router(spot_routes.router, prefix="/api/v1")
    app.dependency_overrides[get_authenticated_actor] = lambda: AdminApiActor(
        actor_id="spot-readiness-viewer",
        roles=[AdminApiRole.VIEWER],
    )
    app.dependency_overrides[spot_routes.get_read_service] = lambda: (
        AdminApiReadService(mvp_service=mvp_service)
    )

    response = TestClient(app).get("/api/v1/spot/readiness")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "blocked"
    assert body["products"] == []
    assert body["account_reality"]["status"] == "blocked"
    assert body["account_reality"]["source"] == (
        "backend_admin_api_local_evidence"
    )
    assert body["account_reality"]["fresh_until"] is None
    assert body["account_scope"]["freshness_status"] == (
        "local_sanitized_evidence"
    )
    assert body["portfolio_scope"]["portfolio_name"] == "Test"
    assert body["portfolio_scope"]["portfolio_id"] == "withheld"
    assert body["portfolio_scope"]["freshness_status"] == (
        "local_sanitized_evidence"
    )
    assert body["spot_admission_input"]["status"] == "blocked"
    assert body["wallet_snapshot"]["available"] is False
    assert body["wallet_snapshot"]["backend_owned"] is True
    assert body["live_coinbase_read_ran"] is False
    SpotReadinessResponse.model_validate(body)


def test_installed_spot_readiness_projects_stale_durable_evidence_call_free(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID",
        PRIVATE_PORTFOLIO_UUID,
    )
    captured_at = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
    client = _StrictReadClient()
    writer = _service(tmp_path, client, now=captured_at)
    refresh = writer.refresh_account_reality(
        {"reason": "synthetic stale route fixture"},
        _context(idempotency_key="spot-readiness-stale-refresh"),
    )
    assert refresh.body["status"] == "ready"
    calls_after_refresh = list(client.calls)
    reader = _service(
        tmp_path,
        client,
        now=captured_at + timedelta(minutes=5),
    )
    app = FastAPI()
    app.include_router(spot_routes.router, prefix="/api/v1")
    app.dependency_overrides[get_authenticated_actor] = lambda: AdminApiActor(
        actor_id="spot-readiness-viewer",
        roles=[AdminApiRole.VIEWER],
    )
    app.dependency_overrides[spot_routes.get_read_service] = lambda: (
        AdminApiReadService(mvp_service=reader)
    )

    response = TestClient(app).get("/api/v1/spot/readiness")

    assert response.status_code == 200
    assert client.calls == calls_after_refresh
    body = response.json()
    assert {
        "type": body["type"],
        "status": body["status"],
        "account_reality": {
            "status": body["account_reality"]["status"],
            "source": body["account_reality"]["source"],
            "generated_at": body["account_reality"]["generated_at"],
            "fresh_until": body["account_reality"]["fresh_until"],
            "coinbase_read_ran": body["account_reality"][
                "coinbase_read_ran"
            ],
            "proof_origin_coinbase_read_ran": body["account_reality"][
                "proof_origin_coinbase_read_ran"
            ],
            "read_error": body["account_reality"]["read_error"],
        },
        "account_scope": {
            "freshness_status": body["account_scope"]["freshness_status"],
            "configured_product_scope": body["account_scope"][
                "configured_product_scope"
            ],
        },
        "portfolio_scope": body["portfolio_scope"],
        "spot_admission_input": {
            "status": body["spot_admission_input"]["status"],
            "first_blocker": body["spot_admission_input"]["first_blocker"],
        },
        "products": body["products"],
        "wallet_available": body["wallet_snapshot"]["available"],
        "live_coinbase_read_ran": body["live_coinbase_read_ran"],
    } == {
        "type": "spot_readiness",
        "status": "warning",
        "account_reality": {
            "status": "blocked",
            "source": "backend_rest_client",
            "generated_at": "2026-07-20T12:00:00+00:00",
            "fresh_until": "2026-07-20T12:01:00+00:00",
            "coinbase_read_ran": False,
            "proof_origin_coinbase_read_ran": True,
            "read_error": "account_reality_snapshot_stale",
        },
        "account_scope": {
            "freshness_status": "stale",
            "configured_product_scope": ["BTC-USDC"],
        },
        "portfolio_scope": {
            "portfolio_id": "withheld",
            "portfolio_name": "Test",
            "source": "backend_rest_client",
            "freshness_status": "stale",
        },
        "spot_admission_input": {
            "status": "blocked",
            "first_blocker": "account_reality_snapshot_stale",
        },
        "products": [],
        "wallet_available": False,
        "live_coinbase_read_ran": False,
    }
    assert PRIVATE_PORTFOLIO_UUID not in json.dumps(body, sort_keys=True)
    SpotReadinessResponse.model_validate(body)
