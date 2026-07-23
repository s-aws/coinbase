from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.v1.app import app as _APP
from api.v1.routes import operator_product_catalog as catalog_routes
from application.admin_api.operator_product_catalog_service import (
    ProductCatalogMutationResponse,
)


pytestmark = [pytest.mark.regression, pytest.mark.serial]

REVISION_ID = "0d756620-2ce5-4fd3-a24a-a14c4d8bf3c1"
TARGET_REVISION_ID = "4a61b585-3f75-48fd-b1cb-a4ef77176ae4"


def _revision(
    *,
    revision_id: str = REVISION_ID,
    state: str = "APPROVED",
    active: bool = True,
) -> dict[str, Any]:
    return {
        "revision_id": revision_id,
        "sequence_number": 1,
        "revision": 2 if state == "APPROVED" else 1,
        "state": state,
        "source": "COINBASE_CATALOG",
        "source_cycle_id": None,
        "parent_revision_id": None,
        "rollback_of_revision_id": None,
        "snapshot_sha256": "a" * 64,
        "diff_sha256": "b" * 64,
        "product_count": 1,
        "added_count": 1,
        "changed_count": 0,
        "removed_count": 0,
        "unchanged_count": 0,
        "active": active,
        "trading_authority_granted": False,
        "portfolio_scope_expanded": False,
        "exchange_mutation_count": 0,
        "created_at": "2026-07-23T12:00:00+00:00",
        "updated_at": "2026-07-23T12:00:00+00:00",
    }


def _product() -> dict[str, Any]:
    return {
        "product_id": "BTC-USDC",
        "product_type": "SPOT",
        "base_currency": "BTC",
        "quote_currency": "USDC",
        "base_increment": "0.00000001",
        "quote_increment": "0.01",
        "price_increment": "0.01",
        "base_min_size": "0.00001",
        "base_max_size": "10",
        "quote_min_size": "1",
        "quote_max_size": "1000000",
        "display_name": "BTC-USDC",
        "exchange_status": "ONLINE",
        "exchange_disabled": False,
        "cancel_only": False,
        "limit_only": False,
        "post_only": False,
        "view_only": False,
        "lifecycle": "ENABLED",
        "change_type": "ADDED",
        "allowed_actions": ["DISABLE", "RETIRE"],
    }


@dataclass
class _Service:
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def list_catalog(self, **kwargs):
        self.calls.append(("list_catalog", kwargs))
        return {
            "type": "operator_product_catalog",
            "status": "ready",
            "items": [_revision()],
            "total_count": 1,
            "returned_count": 1,
            "limit": kwargs["limit"],
            "offset": kwargs["offset"],
            "next_offset": None,
            "active_revision_id": REVISION_ID,
            "active_revision": _revision(),
            "cycles": [],
            "events": [],
            "event_total_count": 0,
            "event_returned_count": 0,
            "event_limit": kwargs["event_limit"],
            "event_offset": kwargs["event_offset"],
            "event_next_offset": None,
            "goal_budget": {
                "cycle_count": 0,
                "cycle_limit": 10,
                "logical_read_count": 0,
                "page_count": 0,
                "trading_authority_granted": False,
                "portfolio_scope_expanded": False,
                "exchange_mutation_count": 0,
            },
            "allowed_actions": ["REFRESH"],
            "live_coinbase_read_ran": False,
            "live_coinbase_orders_ran": False,
            "live_coinbase_execution": "not_run",
            "notional_usdc": "0",
        }

    def get_revision(self, **kwargs):
        self.calls.append(("get_revision", kwargs))
        return {
            "type": "operator_product_catalog_revision",
            "status": "ready",
            "revision": _revision(),
            "products": [_product()],
            "events": [],
            "goal_budget": self.list_catalog(
                limit=1,
                offset=0,
                event_limit=1,
                event_offset=0,
            )[
                "goal_budget"
            ],
            "live_coinbase_read_ran": False,
            "live_coinbase_orders_ran": False,
            "live_coinbase_execution": "not_run",
            "notional_usdc": "0",
        }

    def _mutation(self, method: str, kwargs: dict[str, Any]):
        self.calls.append((method, kwargs))
        return ProductCatalogMutationResponse(
            status="accepted",
            message=f"product_catalog_{method}_accepted",
            service_method=method,
            required_permission="config:update",
            revision=_revision(
                state="PROPOSED" if method == "refresh_catalog" else "APPROVED"
            ),
            correlation_id=kwargs["correlation_id"],
            idempotency_key=kwargs["idempotency_key"],
            coinbase_read_state=(
                "RETURNED" if method == "refresh_catalog" else "NOT_RUN"
            ),
            live_coinbase_read_ran=method == "refresh_catalog",
        )

    def refresh_catalog(self, **kwargs):
        return self._mutation("refresh_catalog", kwargs)

    def approve_revision(self, **kwargs):
        return self._mutation("approve_revision", kwargs)

    def change_product_lifecycle(self, **kwargs):
        return self._mutation("change_product_lifecycle", kwargs)

    def rollback_revision(self, **kwargs):
        return self._mutation("rollback_revision", kwargs)


@pytest.fixture
def route_client(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, _Service]:
    monkeypatch.setenv("COINBASE_ADMIN_API_AUTH_MODE", "bootstrap_bearer")
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_BEARER_TOKEN",
        "local-admin-token",
    )
    service = _Service()
    _APP.dependency_overrides[
        catalog_routes.get_operator_product_catalog_service
    ] = lambda: service
    with TestClient(_APP) as client:
        yield client, service
    _APP.dependency_overrides.pop(
        catalog_routes.get_operator_product_catalog_service,
        None,
    )


def _headers(
    *,
    key: str,
    roles: str = "admin,trader",
    intent: str = "refresh_operator_product_catalog",
) -> dict[str, str]:
    return {
        "Authorization": "Bearer local-admin-token",
        "X-Admin-Actor": "catalog-operator",
        "X-Admin-Roles": roles,
        "Idempotency-Key": key,
        "X-Correlation-Id": f"{key}-correlation",
        "X-Operator-Intent": intent,
    }


def test_catalog_routes_are_authenticated_and_paginated(
    route_client: tuple[TestClient, _Service],
) -> None:
    client, service = route_client

    assert client.get("/api/v1/product-catalog").status_code == 401
    response = client.get(
        "/api/v1/product-catalog?limit=25&offset=0",
        headers=_headers(key="catalog-read"),
    )

    assert response.status_code == 200
    assert response.json()["active_revision_id"] == REVISION_ID
    assert response.json()["allowed_actions"] == ["REFRESH"]
    assert response.json()["goal_budget"]["cycle_limit"] == 10
    assert service.calls == [
        (
            "list_catalog",
            {
                "limit": 25,
                "offset": 0,
                "event_limit": 25,
                "event_offset": 0,
            },
        )
    ]


def test_revision_detail_exposes_reviewed_metadata_and_no_trade_authority(
    route_client: tuple[TestClient, _Service],
) -> None:
    client, _ = route_client
    response = client.get(
        f"/api/v1/product-catalog/revisions/{REVISION_ID}",
        headers=_headers(key="catalog-detail"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["products"][0]["allowed_actions"] == ["DISABLE", "RETIRE"]
    assert body["products"][0]["change_type"] == "ADDED"
    assert body["revision"]["trading_authority_granted"] is False
    assert body["revision"]["portfolio_scope_expanded"] is False
    assert "private" not in response.text.lower()


def test_refresh_approve_lifecycle_and_rollback_forward_exact_operator_intent(
    route_client: tuple[TestClient, _Service],
) -> None:
    client, service = route_client
    refresh = client.post(
        "/api/v1/product-catalog/refresh",
        headers=_headers(
            key="catalog-refresh",
            intent="refresh_operator_product_catalog",
        ),
        json={
            "expected_active_revision_id": REVISION_ID,
            "operator_reason": "refresh documented catalog",
            "confirm_one_no_retry_product_catalog_read": True,
        },
    )
    approve = client.post(
        f"/api/v1/product-catalog/revisions/{REVISION_ID}/approve",
        headers=_headers(
            key="catalog-approve",
            intent="approve_operator_product_catalog_revision",
        ),
        json={
            "expected_revision": 1,
            "snapshot_sha256": "a" * 64,
            "operator_reason": "approve reviewed diff",
            "confirm_catalog_approval": True,
        },
    )
    disable = client.post(
        "/api/v1/product-catalog/products/BTC-USDC/disable",
        headers=_headers(
            key="catalog-disable",
            intent="disable_operator_product_catalog_product",
        ),
        json={
            "expected_active_revision_id": REVISION_ID,
            "expected_active_revision": 2,
            "operator_reason": "disable reviewed product",
            "confirm_product_lifecycle_change": True,
        },
    )
    rollback = client.post(
        f"/api/v1/product-catalog/revisions/{TARGET_REVISION_ID}/rollback",
        headers=_headers(
            key="catalog-rollback",
            intent="rollback_operator_product_catalog_revision",
        ),
        json={
            "expected_active_revision_id": REVISION_ID,
            "expected_active_revision": 2,
            "target_snapshot_sha256": "a" * 64,
            "operator_reason": "restore reviewed revision",
            "confirm_exact_catalog_rollback": True,
        },
    )

    assert [result.status_code for result in (refresh, approve, disable, rollback)] == [
        200,
        200,
        200,
        200,
    ]
    assert refresh.json()["coinbase_read_state"] == "RETURNED"
    assert refresh.json()["live_coinbase_read_ran"] is True
    assert approve.json()["live_coinbase_read_ran"] is False
    assert disable.json()["live_coinbase_orders_ran"] is False
    assert rollback.json()["exchange_mutation_count"] == 0
    assert [name for name, _ in service.calls] == [
        "refresh_catalog",
        "approve_revision",
        "change_product_lifecycle",
        "rollback_revision",
    ]
    assert service.calls[2][1]["action"] == "DISABLE"
    assert service.calls[3][1]["target_revision_id"] == TARGET_REVISION_ID


def test_catalog_mutations_require_backend_config_authority(
    route_client: tuple[TestClient, _Service],
) -> None:
    client, service = route_client
    response = client.post(
        "/api/v1/product-catalog/refresh",
        headers=_headers(key="catalog-viewer", roles="viewer"),
        json={
            "expected_active_revision_id": None,
            "operator_reason": "unauthorized refresh",
            "confirm_one_no_retry_product_catalog_read": True,
        },
    )

    assert response.status_code == 403
    assert service.calls == []


def test_catalog_mutations_reject_mismatched_operator_intent(
    route_client: tuple[TestClient, _Service],
) -> None:
    client, service = route_client
    response = client.post(
        f"/api/v1/product-catalog/revisions/{REVISION_ID}/approve",
        headers=_headers(
            key="catalog-wrong-intent",
            intent="refresh_operator_product_catalog",
        ),
        json={
            "expected_revision": 1,
            "snapshot_sha256": "a" * 64,
            "operator_reason": "attempt mismatched intent",
            "confirm_catalog_approval": True,
        },
    )

    assert response.status_code == 422
    assert service.calls == []
