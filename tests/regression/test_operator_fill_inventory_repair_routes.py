from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.v1.app import app as _APP
from api.v1.routes import operator_fill_inventory_repair as repair_routes
from application.admin_api.audit import FileAdminApiAuditStore
from application.admin_api.idempotency import FileIdempotencyStore


pytestmark = [pytest.mark.regression, pytest.mark.serial]

CASE_ID = "0d756620-2ce5-4fd3-a24a-a14c4d8bf3c1"
CLIENT_ORDER_ID = "8f1bf38c-90ad-4a7c-90fb-87cb56c72a80"


def _plan_sha256(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _projection() -> dict[str, Any]:
    return {
        "product_id": "BTC-USDC",
        "fill_count": 1,
        "open_lot_count": 1,
        "open_quantity": "0.01",
        "average_cost_basis": "101",
        "remaining_cost_basis": "1.01",
        "realized_operational_pnl": "0",
        "total_fees": "0.01",
        "lots": [
            {
                "lot_identity_sha256": "c" * 64,
                "product_id": "BTC-USDC",
                "remaining_quantity": "0.01",
                "unit_cost_basis": "101",
                "remaining_cost_basis": "1.01",
                "acquired_at": "2026-07-22T01:00:00Z",
            }
        ],
    }


def _case(
    *,
    state: str = "OPEN",
    revision: int = 1,
    plan: bool = False,
) -> dict[str, Any]:
    plan_value = (
        {
            "selector_type": "EXACT_ORDER",
            "catalog_fill_count": 1,
            "missing_fill_count": 1,
            "existing_fill_count": 0,
            "unmatched_fill_count": 0,
            "affected_product_count": 1,
            "apply_available": True,
            "candidates": [
                {
                    "fill_identity_sha256": "must-remain-internal",
                }
            ],
            "projection": _projection(),
            "diagnostic_code": "fill_inventory_plan_ready",
        }
        if plan
        else None
    )
    return {
        "case_id": CASE_ID,
        "selector_type": "EXACT_ORDER",
        "selector_sha256": "a" * 64,
        "client_order_id": CLIENT_ORDER_ID,
        "product_id": "BTC-USDC",
        "window_start": None,
        "window_end": None,
        "portfolio_id_sha256": "b" * 64,
        "state": state,
        "revision": revision,
        "cycle_count": 1 if revision > 1 else 0,
        "goal_cycle_count": 1 if revision > 1 else 0,
        "goal_cycle_limit": 10,
        "goal_fill_read_logical_count": 1 if revision > 1 else 0,
        "goal_fill_read_page_count": 1 if revision > 1 else 0,
        "fill_read_logical_count": 1 if revision > 1 else 0,
        "fill_read_page_count": 1 if revision > 1 else 0,
        "last_cycle_fill_read_page_count": 1 if revision > 1 else 0,
        "last_refresh_coinbase_read_state": (
            "RETURNED" if revision > 1 else "NOT_RUN"
        ),
        "catalog_fill_count": 1 if plan else 0,
        "missing_fill_count": 1 if plan else 0,
        "existing_fill_count": 0,
        "unmatched_fill_count": 0,
        "affected_product_count": 1 if plan else 0,
        "imported_fill_count": 1 if state == "APPLIED" else 0,
        "rolled_back_fill_count": 1 if state == "ROLLED_BACK" else 0,
        "plan_sha256": _plan_sha256(plan_value) if plan_value else None,
        "plan": plan_value,
        "diagnostic_code": (
            "fill_inventory_import_applied"
            if state == "APPLIED"
            else "fill_inventory_import_rolled_back"
            if state == "ROLLED_BACK"
            else "fill_inventory_plan_ready"
            if plan
            else "fill_inventory_case_created"
        ),
        "created_by": "route-operator",
        "correlation_id": "fill-inventory-correlation",
        "created_at": "2026-07-23T08:00:00+00:00",
        "updated_at": "2026-07-23T08:00:00+00:00",
    }


@dataclass
class _Repository:
    def list_events(self, case_id: str, *, limit: int = 100):
        assert case_id == CASE_ID
        assert limit == 100
        return []

    def get_goal_budget(self):
        return {
            "goal_cycle_count": 1,
            "goal_cycle_limit": 10,
            "goal_fill_read_logical_count": 1,
            "goal_fill_read_page_count": 1,
        }


@dataclass
class _Service:
    repository: _Repository = field(default_factory=_Repository)
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def portfolio_binding_verified(self, _case_record):
        return True

    def list_cases(self, *, limit: int, offset: int):
        self.calls.append(("list_cases", {"limit": limit, "offset": offset}))
        return [_case()], 1

    def get_case(self, case_id: str):
        self.calls.append(("get_case", {"case_id": case_id}))
        return _case()

    def create_case(self, **kwargs):
        self.calls.append(("create_case", kwargs))
        return _case()

    def refresh_case(self, **kwargs):
        self.calls.append(("refresh_case", kwargs))
        return _case(state="PLAN_READY", revision=3, plan=True)

    def apply_case(self, **kwargs):
        self.calls.append(("apply_case", kwargs))
        return _case(state="APPLIED", revision=4, plan=True)

    def rollback_case(self, **kwargs):
        self.calls.append(("rollback_case", kwargs))
        return _case(state="ROLLED_BACK", revision=5, plan=True)


@pytest.fixture
def route_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, _Service]:
    monkeypatch.setenv("COINBASE_ADMIN_API_AUTH_MODE", "bootstrap_bearer")
    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "local-admin-token")
    service = _Service()
    _APP.dependency_overrides[
        repair_routes.get_operator_fill_inventory_repair_service
    ] = lambda: service
    _APP.dependency_overrides[
        repair_routes.get_idempotency_store
    ] = lambda: FileIdempotencyStore(tmp_path / "fill-repair-idempotency.jsonl")
    _APP.dependency_overrides[
        repair_routes.get_audit_store
    ] = lambda: FileAdminApiAuditStore(tmp_path / "fill-repair-audit.jsonl")
    with TestClient(_APP) as client:
        yield client, service
    _APP.dependency_overrides.pop(
        repair_routes.get_operator_fill_inventory_repair_service,
        None,
    )
    _APP.dependency_overrides.pop(repair_routes.get_idempotency_store, None)
    _APP.dependency_overrides.pop(repair_routes.get_audit_store, None)


def _headers(*, key: str) -> dict[str, str]:
    return {
        "Authorization": "Bearer local-admin-token",
        "X-Admin-Actor": "route-operator",
        "X-Admin-Roles": "trader",
        "Idempotency-Key": key,
        "X-Correlation-Id": "fill-inventory-correlation",
        "X-Operator-Intent": "operator_fill_inventory_repair",
    }


def test_routes_are_authenticated_paginated_and_withhold_internal_candidates(
    route_client: tuple[TestClient, _Service],
) -> None:
    client, service = route_client
    response = client.get(
        "/api/v1/spot/fill-inventory-repair/cases?limit=25&offset=0",
        headers={
            "Authorization": "Bearer local-admin-token",
            "X-Admin-Actor": "route-operator",
            "X-Admin-Roles": "trader",
        },
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["allowed_actions"] == ["REFRESH"]
    assert "candidates" not in response.text
    assert service.calls == [("list_cases", {"limit": 25, "offset": 0})]


def test_create_refresh_apply_and_rollback_are_idempotent_operator_actions(
    route_client: tuple[TestClient, _Service],
) -> None:
    client, service = route_client
    created = client.post(
        "/api/v1/spot/fill-inventory-repair/cases",
        headers=_headers(key="fill-repair-create"),
        json={
            "selector_type": "EXACT_ORDER",
            "client_order_id": CLIENT_ORDER_ID,
            "operator_reason": "repair exact order",
        },
    )
    refreshed = client.post(
        f"/api/v1/spot/fill-inventory-repair/cases/{CASE_ID}/refresh",
        headers=_headers(key="fill-repair-refresh"),
        json={
            "expected_revision": 1,
            "manual_live_acknowledgement": True,
        },
    )
    replay = client.post(
        f"/api/v1/spot/fill-inventory-repair/cases/{CASE_ID}/refresh",
        headers=_headers(key="fill-repair-refresh"),
        json={
            "expected_revision": 1,
            "manual_live_acknowledgement": True,
        },
    )
    applied = client.post(
        f"/api/v1/spot/fill-inventory-repair/cases/{CASE_ID}/apply",
        headers=_headers(key="fill-repair-apply"),
        json={
            "expected_revision": 3,
            "plan_sha256": "d" * 64,
            "operator_reason": "apply reviewed import",
            "operator_acknowledgement": True,
        },
    )
    rolled_back = client.post(
        f"/api/v1/spot/fill-inventory-repair/cases/{CASE_ID}/rollback",
        headers=_headers(key="fill-repair-rollback"),
        json={
            "expected_revision": 4,
            "plan_sha256": "d" * 64,
            "operator_reason": "rollback exact import",
            "operator_acknowledgement": True,
        },
    )

    assert created.status_code == 200
    assert refreshed.status_code == 200
    assert refreshed.json()["live_coinbase_read_ran"] is True
    assert refreshed.json()["coinbase_read_state"] == "RETURNED"
    assert refreshed.json()["live_coinbase_order_mutation_ran"] is False
    assert "candidates" not in refreshed.text
    assert replay.headers["X-Idempotency-Replayed"] == "true"
    assert applied.json()["case"]["state"] == "APPLIED"
    assert rolled_back.json()["case"]["state"] == "ROLLED_BACK"
    assert [name for name, _ in service.calls] == [
        "create_case",
        "refresh_case",
        "apply_case",
        "rollback_case",
    ]
    assert service.calls[-1][1]["plan_sha256"] == "d" * 64


def test_refresh_response_preserves_an_unknown_post_claim_read_state(
    route_client: tuple[TestClient, _Service],
) -> None:
    client, service = route_client

    def unknown_refresh(**kwargs):
        service.calls.append(("refresh_case", kwargs))
        record = _case(state="BLOCKED", revision=2)
        record["last_refresh_coinbase_read_state"] = (
            "UNKNOWN_AFTER_PAGE_CLAIM"
        )
        record["diagnostic_code"] = "fill_inventory_catalog_call_failed"
        return record

    service.refresh_case = unknown_refresh  # type: ignore[method-assign]
    response = client.post(
        f"/api/v1/spot/fill-inventory-repair/cases/{CASE_ID}/refresh",
        headers=_headers(key="fill-repair-unknown"),
        json={
            "expected_revision": 1,
            "manual_live_acknowledgement": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["live_coinbase_read_ran"] is None
    assert (
        response.json()["coinbase_read_state"]
        == "UNKNOWN_AFTER_PAGE_CLAIM"
    )
    assert (
        response.json()["case"]["last_refresh_coinbase_read_state"]
        == "UNKNOWN_AFTER_PAGE_CLAIM"
    )


def test_refresh_handler_exception_recovers_persisted_unknown_call_truth(
    route_client: tuple[TestClient, _Service],
) -> None:
    client, service = route_client
    persisted = _case(state="REFRESHING", revision=2)
    persisted["last_refresh_coinbase_read_state"] = (
        "UNKNOWN_AFTER_PAGE_CLAIM"
    )

    def failed_refresh(**_kwargs):
        raise RuntimeError("withheld")

    def get_persisted(case_id: str):
        assert case_id == CASE_ID
        return persisted

    service.refresh_case = failed_refresh  # type: ignore[method-assign]
    service.get_case = get_persisted  # type: ignore[method-assign]
    response = client.post(
        f"/api/v1/spot/fill-inventory-repair/cases/{CASE_ID}/refresh",
        headers=_headers(key="fill-repair-handler-unknown"),
        json={
            "expected_revision": 1,
            "manual_live_acknowledgement": True,
        },
    )

    assert response.status_code == 400
    assert response.json()["message"] == "fill_inventory_internal_failure"
    assert response.json()["live_coinbase_read_ran"] is None
    assert (
        response.json()["coinbase_read_state"]
        == "UNKNOWN_AFTER_PAGE_CLAIM"
    )


@pytest.mark.parametrize(
    ("action", "code", "body", "service_method"),
    [
        (
            "apply",
            "fill_inventory_apply_existing_projection_invalid",
            {
                "expected_revision": 3,
                "plan_sha256": "d" * 64,
                "operator_reason": "apply exact reviewed plan",
                "operator_acknowledgement": True,
            },
            "apply_operator_fill_inventory_repair_case",
        ),
        (
            "rollback",
            "fill_inventory_rollback_prior_projection_changed",
            {
                "expected_revision": 4,
                "plan_sha256": "d" * 64,
                "operator_reason": "rollback exact import",
                "operator_acknowledgement": True,
            },
            "rollback_operator_fill_inventory_repair_case",
        ),
        (
            "rollback",
            "fill_inventory_rollback_prior_projection_unverified",
            {
                "expected_revision": 4,
                "plan_sha256": "d" * 64,
                "operator_reason": "rollback exact import",
                "operator_acknowledgement": True,
            },
            "rollback_operator_fill_inventory_repair_case",
        ),
    ],
)
def test_projection_integrity_rejections_are_fixed_audited_responses(
    route_client: tuple[TestClient, _Service],
    action: str,
    code: str,
    body: dict[str, Any],
    service_method: str,
) -> None:
    client, service = route_client

    def reject(**kwargs):
        service.calls.append((f"{action}_case", kwargs))
        raise repair_routes.OperatorFillInventoryRepairError(code)

    setattr(service, f"{action}_case", reject)
    response = client.post(
        f"/api/v1/spot/fill-inventory-repair/cases/{CASE_ID}/{action}",
        headers=_headers(key=f"fill-repair-{action}-integrity"),
        json=body,
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["status"] == "rejected"
    assert payload["message"] == code
    assert payload["service_method"] == service_method
    assert payload["correlation_id"] == "fill-inventory-correlation"
    assert payload["idempotency_key"] == (
        f"fill-repair-{action}-integrity"
    )
    assert payload["audit_id"]
    assert payload["live_coinbase_read_ran"] is False
    assert payload["coinbase_read_state"] == "NOT_RUN"
    assert payload["live_coinbase_order_mutation_ran"] is False


def test_openapi_exposes_normal_fill_inventory_repair_routes() -> None:
    schema = _APP.openapi()
    paths = schema["paths"]

    assert "/api/v1/spot/fill-inventory-repair/cases" in paths
    assert "/api/v1/spot/fill-inventory-repair/cases/{case_id}" in paths
    assert (
        "/api/v1/spot/fill-inventory-repair/cases/{case_id}/refresh"
        in paths
    )
    assert (
        "/api/v1/spot/fill-inventory-repair/cases/{case_id}/apply"
        in paths
    )
    assert (
        "/api/v1/spot/fill-inventory-repair/cases/{case_id}/rollback"
        in paths
    )
