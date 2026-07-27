from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from api.v1.routes import operator_spot_safe_closeout_sweep as routes
from application.admin_api.operator_spot_safe_closeout_sweep_models import (
    OperatorSpotSafeCloseoutSweepReadback,
)
from core.enums import AdminApiPermission


SWEEP_ID = "11111111-1111-4111-8111-111111111111"
CLIENT_ID = "22222222-2222-4222-8222-222222222222"


def _readback(
    *,
    allowed_actions: list[str],
) -> OperatorSpotSafeCloseoutSweepReadback:
    return OperatorSpotSafeCloseoutSweepReadback(
        sweep_id=SWEEP_ID,
        revision=1,
        state="READY",
        diagnostic_code="operator_spot_sweep_plan_ready",
        plan_sha256="d" * 64,
        configured_portfolio_scope_sha256="a" * 64,
        items=[
            {
                "position": 1,
                "client_order_id": CLIENT_ID,
                "root_client_order_id": (
                    "33333333-3333-4333-8333-333333333333"
                ),
                "product_id": "BTC-USDC",
                "status": "OPEN",
                "ownership_provenance": "ADMIN_FILL_FOLLOW_UP",
                "portfolio_scope_sha256": "a" * 64,
                "predecessor_evidence_sha256": "b" * 64,
                "candidate_evidence_sha256": "c" * 64,
                "state": "PENDING",
                "diagnostic_code": "operator_spot_sweep_item_pending",
                "last_event_sequence": 17,
                "updated_at": "2026-07-27T00:00:00Z",
            }
        ],
        events=[
            {
                "event_id": (
                    "44444444-4444-4444-8444-444444444444"
                ),
                "event_sequence": 17,
                "event_type": "PLAN_CREATED",
                "diagnostic_code": "operator_spot_sweep_plan_ready",
                "correlation_id": "goal16-correlation",
                "evidence_sha256": "e" * 64,
                "recorded_at": "2026-07-27T00:00:00Z",
            }
        ],
        candidate_count=1,
        allowed_actions=allowed_actions,
        allowances=[
            {"category": category}
            for category in (
                "API_KEY_PERMISSIONS",
                "PORTFOLIO_CATALOG",
                "PRE_CANCEL_EXACT_ORDER_READ",
                "CANCEL",
                "POST_CANCEL_EXACT_ORDER_READ",
            )
        ],
        local_cycles_used=1,
        partial_result_quarantine=False,
        latest_idempotency_key_sha256="f" * 64,
        latest_payload_sha256="1" * 64,
        latest_actor_id_sha256="2" * 64,
        latest_evidence_sha256="e" * 64,
        correlation_id="goal16-correlation",
        operator_intent=None,
        command_service_method="get_safe_closeout_sweep",
        created_at="2026-07-27T00:00:00Z",
        updated_at="2026-07-27T00:00:00Z",
    )


@dataclass
class _Service:
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def list_safe_closeout_candidates(self, **kwargs):
        self.calls.append(("candidates", kwargs))
        return routes.OperatorSpotSafeCloseoutCandidatePage(
            goal_id="operator_spot_sweep_safe_closeout_v1",
            items=[
                {
                    "client_order_id": CLIENT_ID,
                    "root_client_order_id": (
                        "33333333-3333-4333-8333-333333333333"
                    ),
                    "product_id": "BTC-USDC",
                    "status": "OPEN",
                    "ownership_provenance": (
                        "ADMIN_FILL_FOLLOW_UP"
                    ),
                    "portfolio_scope_sha256": "a" * 64,
                    "predecessor_evidence_sha256": "b" * 64,
                    "candidate_evidence_sha256": "c" * 64,
                    "created_at": "2026-07-27T00:00:00Z",
                }
            ],
            total=1,
            limit=kwargs["limit"],
            offset=kwargs["offset"],
            status_filter=kwargs["status_filter"],
            ownership_provenance_filter=(
                kwargs["ownership_provenance_filter"]
            ),
            configured_portfolio_scope_sha256="a" * 64,
            diagnostic_code="operator_spot_sweep_candidates_empty",
            allowed_actions=["CREATE_SWEEP"] if kwargs["can_mutate"] else [],
        )

    def get_safe_closeout_sweep(self, **kwargs):
        self.calls.append(("get", kwargs))
        return _readback(
            allowed_actions=(
                ["PAUSE", "ABORT"]
                if kwargs["can_mutate"]
                else []
            )
        )

    def get_current_safe_closeout_sweep(self, **kwargs):
        self.calls.append(("get_current", kwargs))
        return _readback(
            allowed_actions=(
                ["PAUSE", "ABORT"]
                if kwargs["can_mutate"]
                else []
            )
        ).model_copy(
            update={
                "command_service_method": (
                    "get_current_safe_closeout_sweep"
                )
            }
        )

    def create_safe_closeout_sweep(self, **kwargs):
        self.calls.append(("create", kwargs))
        raise AssertionError("not used")


def _app(service: _Service) -> FastAPI:
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    app.dependency_overrides[
        routes.get_operator_spot_safe_closeout_sweep_service
    ] = lambda: service
    return app


def _headers(
    intent: str = "read_operator_spot_safe_closeout_sweep",
    *,
    roles: str = "admin,trader",
) -> dict[str, str]:
    return {
        "Authorization": "Bearer local-admin-token",
        "X-Admin-Actor": "operator",
        "X-Admin-Roles": roles,
        "X-Correlation-Id": "goal16-correlation",
        "Idempotency-Key": "goal16-idempotency",
        "X-Operator-Intent": intent,
    }


def _enable(monkeypatch) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_AUTH_MODE", "bootstrap_bearer")
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_BEARER_TOKEN",
        "local-admin-token",
    )
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_SPOT_SAFE_CLOSEOUT_SWEEP_ENABLED",
        "1",
    )


def test_candidate_page_is_local_paginated_and_backend_action_bound(
    monkeypatch,
) -> None:
    _enable(monkeypatch)
    service = _Service()
    client = TestClient(_app(service))

    response = client.get(
        "/api/v1/spot/safe-closeout-sweeps/candidates",
        params={
            "limit": 25,
            "offset": 0,
            "status": "OPEN",
            "ownership_provenance": "ADMIN_FILL_FOLLOW_UP",
        },
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json()["page_load_coinbase_calls"] == 0
    assert response.json()["total_exchange_call_count"] == 0
    assert response.json()["allowed_actions"] == ["CREATE_SWEEP"]
    assert service.calls == [
        (
            "candidates",
            {
                "limit": 25,
                "offset": 0,
                "status_filter": "OPEN",
                "ownership_provenance_filter": (
                    "ADMIN_FILL_FOLLOW_UP"
                ),
                "can_mutate": True,
            },
        )
    ]


def test_current_read_recovers_singleton_without_mutation(
    monkeypatch,
) -> None:
    _enable(monkeypatch)
    service = _Service()
    client = TestClient(_app(service))

    response = client.get(
        "/api/v1/spot/safe-closeout-sweeps/current",
        headers=_headers(roles="trader"),
    )

    assert response.status_code == 200
    assert response.json()["sweep_id"] == SWEEP_ID
    assert response.json()["operator_intent"] is None
    assert response.json()["command_service_method"] == (
        "get_current_safe_closeout_sweep"
    )
    assert response.json()["total_exchange_call_count"] == 0
    assert service.calls == [
        ("get_current", {"can_mutate": True})
    ]


@pytest.mark.parametrize("execution_enabled", [None, "1"])
def test_advance_fails_before_service_ledger_runtime_or_client(
    monkeypatch,
    execution_enabled,
) -> None:
    _enable(monkeypatch)
    if execution_enabled is None:
        monkeypatch.delenv("COINBASE_EXECUTION_ENABLED", raising=False)
    else:
        monkeypatch.setenv(
            "COINBASE_EXECUTION_ENABLED",
            execution_enabled,
        )
    service = _Service()
    app = _app(service)
    app.dependency_overrides[
        routes.get_operator_spot_safe_closeout_sweep_service
    ] = lambda: (_ for _ in ()).throw(
        AssertionError("advance instantiated Goal 16 service")
    )
    client = TestClient(app)

    response = client.post(
        f"/api/v1/spot/safe-closeout-sweeps/{SWEEP_ID}/advance",
        headers=_headers(
            "advance_operator_spot_safe_closeout_sweep"
        ),
        json={
            "expected_revision": 1,
            "expected_plan_sha256": "a" * 64,
            "confirm_advance_cancel_only_sweep": True,
            "acknowledge_unknown_or_partial_result_quarantines_sweep": (
                True
            ),
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "operator_spot_sweep_live_read_authority_incomplete"
    )
    assert service.calls == []


@pytest.mark.parametrize(
    "missing_permission",
    [
        AdminApiPermission.SPOT_SWEEP_EXECUTE,
        AdminApiPermission.ORDER_CANCEL,
    ],
)
def test_advance_requires_each_mutation_permission_before_fixed_block(
    monkeypatch,
    missing_permission,
) -> None:
    _enable(monkeypatch)

    def require_exact_permission(_actor, permission):
        if permission is missing_permission:
            raise HTTPException(
                status_code=403,
                detail=f"missing:{permission.value}",
            )

    monkeypatch.setattr(
        routes,
        "require_permission",
        require_exact_permission,
    )
    client = TestClient(_app(_Service()))

    response = client.post(
        f"/api/v1/spot/safe-closeout-sweeps/{SWEEP_ID}/advance",
        headers=_headers(
            "advance_operator_spot_safe_closeout_sweep"
        ),
        json={
            "expected_revision": 1,
            "expected_plan_sha256": "a" * 64,
            "confirm_advance_cancel_only_sweep": True,
            "acknowledge_unknown_or_partial_result_quarantines_sweep": (
                True
            ),
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == (
        f"missing:{missing_permission.value}"
    )


@pytest.mark.parametrize(
    "missing_permission",
    [
        AdminApiPermission.SPOT_SWEEP_EXECUTE,
        AdminApiPermission.ORDER_CANCEL,
    ],
)
def test_get_readback_suppresses_actions_when_either_permission_missing(
    monkeypatch,
    missing_permission,
) -> None:
    _enable(monkeypatch)
    real_actor_has_permission = routes.actor_has_permission

    def has_permission(actor, permission):
        if permission is missing_permission:
            return False
        return real_actor_has_permission(actor, permission)

    monkeypatch.setattr(routes, "actor_has_permission", has_permission)
    service = _Service()
    client = TestClient(_app(service))

    response = client.get(
        f"/api/v1/spot/safe-closeout-sweeps/{SWEEP_ID}",
        headers=_headers(roles="trader"),
    )

    assert response.status_code == 200
    assert response.json()["allowed_actions"] == []
    assert service.calls == [
        ("get", {"sweep_id": SWEEP_ID, "can_mutate": False})
    ]


def test_mutations_require_both_spot_sweep_and_cancel_permissions(
    monkeypatch,
) -> None:
    _enable(monkeypatch)
    service = _Service()
    client = TestClient(_app(service))

    response = client.post(
        "/api/v1/spot/safe-closeout-sweeps",
        headers=_headers(
            "create_operator_spot_safe_closeout_sweep",
            roles="operator",
        ),
        json={
            "items": [
                {
                    "client_order_id": CLIENT_ID,
                    "expected_candidate_evidence_sha256": "a" * 64,
                }
            ],
            "operator_reason": "Operator reviewed exact candidates.",
            "confirm_create_cancel_only_sweep": True,
        },
    )

    assert response.status_code == 403
    assert service.calls == []
