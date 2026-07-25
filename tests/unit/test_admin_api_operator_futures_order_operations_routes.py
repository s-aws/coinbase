from __future__ import annotations

from dataclasses import replace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.routes import futures as futures_routes
from application.admin_api.auth import get_authenticated_actor
from application.admin_api.models import AdminApiActor
from application.admin_api.operator_futures_order_operations_service import (
    FuturesOrderOperationsGoalRecord,
)
from application.admin_api.operator_futures_order_operations_service_runtime import (
    FuturesOrderOperationsExecutionPosture,
)
from application.admin_api.read_service import CONTROLLED_LIVE_MVP_ROUTES
from core.enums import AdminApiRole


CLIENT_ORDER_ID = "operator-futures-order-001"


def _record(**updates):
    record = FuturesOrderOperationsGoalRecord(
        goal_id="operator_futures_order_inventory_detail_cancel_reconcile_v1",
        revision=2,
        cycles_used=1,
        active_cycle_number=None,
        last_action="REFRESH_CATALOG",
        last_target_client_order_id=None,
        last_outcome="SUCCEEDED",
        diagnostic_code="operator_futures_orders_catalog_refreshed",
        category_attempts={
            "api_key_permissions": 1,
            "portfolio_catalog": 1,
            "futures_order_catalog": 1,
        },
        page_count=1,
        order_count=1,
        portfolio_id_sha256="a" * 64,
        evidence_sha256="b" * 64,
        cancel_outcome="NOT_RUN",
        cancel_exchange_invoked=None,
        cancel_target_client_order_id=None,
        cancel_exchange_order_id_sha256=None,
        correlation_id="corr-1",
        audit_id="audit-1",
        refreshed_at="2026-07-25T09:00:00+00:00",
        updated_at="2026-07-25T09:00:00+00:00",
    )
    return replace(record, **updates)


def _order():
    return {
        "client_order_id": CLIENT_ORDER_ID,
        "product_id": "AVP-20DEC30-CDE",
        "side": "BUY",
        "status": "OPEN",
        "order_type": "LIMIT",
        "time_in_force": "GOOD_UNTIL_CANCELLED",
        "size": "1",
        "limit_price": "6.90",
        "filled_size": "0",
        "created_at": "2026-07-25T08:00:00+00:00",
        "updated_at": "2026-07-25T08:00:01+00:00",
        "observed_at": "2026-07-25T09:00:00+00:00",
        "exchange_order_id_sha256": "c" * 64,
        "authoritatively_nonterminal": True,
        "cancel_eligible": True,
    }


class _Service:
    def __init__(self):
        self.record = _record()
        self.cycle_record = replace(
            self.record,
            revision=3,
            correlation_id="11111111-1111-4111-8111-111111111111",
        )
        self.calls = []

    def read_goal(self):
        return self.record

    def list_orders(self, **kwargs):
        return {
            "filters": {
                "product_id": kwargs["product_id"],
                "order_status": kwargs["order_status"],
            },
            "pagination": {
                "limit": kwargs["limit"],
                "offset": kwargs["offset"],
                "returned_count": 1,
                "total_matching_count": 1,
                "next_offset": None,
                "has_more": False,
            },
            "items": [_order()],
        }

    def get_order(self, client_order_id):
        return _order() if client_order_id == CLIENT_ORDER_ID else None

    def read_cycle_result(self, *, correlation_id, actor_id):
        if (
            correlation_id == "11111111-1111-4111-8111-111111111111"
            and actor_id == "operator-1"
        ):
            return (
                True,
                True,
                self.cycle_record,
            )
        return False, False, None

    def refresh_catalog(self, *, context):
        self.calls.append(("REFRESH_CATALOG", context))
        self.record = replace(self.record, revision=3, cycles_used=2)
        return self.record

    def reconcile_exact(self, *, context, client_order_id):
        self.calls.append(("RECONCILE_EXACT", context, client_order_id))
        self.record = replace(
            self.record,
            revision=3,
            cycles_used=2,
            last_action="RECONCILE_EXACT",
            last_target_client_order_id=client_order_id,
        )
        return self.record

    def cancel_exact(self, *, context, client_order_id):
        self.calls.append(("CANCEL_EXACT", context, client_order_id))
        self.record = replace(
            self.record,
            revision=4,
            cycles_used=2,
            last_action="CANCEL_EXACT",
            last_target_client_order_id=client_order_id,
            cancel_outcome="ACCEPTED",
            cancel_exchange_invoked=True,
            cancel_target_client_order_id=client_order_id,
            cancel_exchange_order_id_sha256="c" * 64,
        )
        return self.record


def _client(monkeypatch, *, roles=None):
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_FUTURES_ORDER_OPERATIONS_ENABLED",
        "1",
    )
    service = _Service()
    app = FastAPI()
    app.include_router(futures_routes.router, prefix="/api/v1")
    app.dependency_overrides[get_authenticated_actor] = lambda: AdminApiActor(
        actor_id="operator-1",
        roles=roles or [AdminApiRole.ADMIN, AdminApiRole.TRADER],
    )
    app.dependency_overrides[
        futures_routes.get_operator_futures_order_operations_service
    ] = lambda: service
    monkeypatch.setattr(
        futures_routes,
        "get_operator_futures_order_operations_execution_posture",
        lambda: FuturesOrderOperationsExecutionPosture(
            ready=True,
            diagnostic_code=(
                "operator_futures_orders_execution_posture_ready"
            ),
        ),
    )
    return TestClient(app), service


def test_list_and_detail_are_postgres_backed_and_call_free(monkeypatch):
    client, _service = _client(monkeypatch)

    listed = client.get(
        "/api/v1/futures/order-operations",
        params={
            "product_id": "AVP-20DEC30-CDE",
            "order_status": "OPEN",
            "limit": 25,
            "offset": 0,
        },
    )
    detail = client.get(
        f"/api/v1/futures/order-operations/{CLIENT_ORDER_ID}"
    )

    assert listed.status_code == 200
    assert listed.json()["page_load_coinbase_calls"] == 0
    assert listed.json()["items"][0]["client_order_id"] == CLIENT_ORDER_ID
    assert listed.json()["items"][0].get("order_id") is None
    assert detail.status_code == 200
    assert detail.json()["found"] is True
    assert detail.json()["page_load_coinbase_calls"] == 0


def test_request_result_readback_is_actor_bound_call_free_and_terminal(
    monkeypatch,
):
    client, service = _client(monkeypatch)
    service.record = replace(
        service.record,
        revision=4,
        active_cycle_number=2,
        last_outcome="CLAIMED",
        cancel_outcome="CLAIMED",
    )

    response = client.get(
        "/api/v1/futures/order-operations/mutation-results/"
        "11111111-1111-4111-8111-111111111111"
    )
    missing = client.get(
        "/api/v1/futures/order-operations/mutation-results/"
        "22222222-2222-4222-8222-222222222222"
    )

    assert response.status_code == 200
    assert response.json()["found"] is True
    assert response.json()["terminal"] is True
    assert response.json()["result"]["correlation_id"] == (
        "11111111-1111-4111-8111-111111111111"
    )
    assert response.json()["result"]["allowed_actions"] == []
    assert (
        response.json()["result"]["execution_posture_ready"] is False
    )
    assert (
        response.json()["result"][
            "execution_posture_diagnostic_code"
        ]
        == "operator_futures_orders_historical_result_non_actionable"
    )
    assert response.json()["page_load_coinbase_calls"] == 0
    assert response.json()["readback_source"] == (
        "postgresql_cycle_result"
    )
    assert missing.status_code == 200
    assert missing.json()["found"] is False
    assert missing.json()["terminal"] is False
    assert missing.json()["result"] is None


def test_exact_reconcile_and_cancel_require_explicit_confirmations(monkeypatch):
    client, service = _client(monkeypatch)
    common = {
        "expected_revision": 2,
        "authorize_one_no_retry_cycle": True,
        "acknowledge_cycle_is_goal_global_and_limited_to_ten": True,
        "acknowledge_unknown_read_fails_closed": True,
    }
    reconcile = client.post(
        f"/api/v1/futures/order-operations/"
        f"{CLIENT_ORDER_ID}/reconciliation",
        headers={
            "Idempotency-Key": "reconcile-1",
            "X-Correlation-Id": "corr-reconcile-1",
            "X-Operator-Intent": "reconcile_exact_futures_order",
        },
        json=common,
    )
    assert reconcile.status_code == 200
    assert service.calls[0][0] == "RECONCILE_EXACT"

    incomplete = client.post(
        f"/api/v1/futures/order-operations/{CLIENT_ORDER_ID}/cancel",
        headers={
            "Idempotency-Key": "cancel-1",
            "X-Correlation-Id": "corr-cancel-1",
            "X-Operator-Intent": "cancel_exact_futures_order",
        },
        json={**common, "expected_revision": 3},
    )
    assert incomplete.status_code == 422

    cancelled = client.post(
        f"/api/v1/futures/order-operations/{CLIENT_ORDER_ID}/cancel",
        headers={
            "Idempotency-Key": "cancel-1",
            "X-Correlation-Id": "corr-cancel-1",
            "X-Operator-Intent": "cancel_exact_futures_order",
        },
        json={
            **common,
            "expected_revision": 3,
            "acknowledge_unknown_cancel_consumes_allowance": True,
        },
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["result"]["cancel_outcome"] == "ACCEPTED"


def test_viewer_can_read_but_has_no_mutation_actions(monkeypatch):
    client, _service = _client(monkeypatch, roles=[AdminApiRole.VIEWER])

    response = client.get("/api/v1/futures/order-operations")

    assert response.status_code == 200
    assert response.json()["authority"]["allowed_actions"] == []


def test_claimed_cancel_fences_every_operator_action(monkeypatch):
    client, service = _client(monkeypatch)
    service.record = _record(
        revision=4,
        last_action="CANCEL_EXACT",
        last_target_client_order_id=CLIENT_ORDER_ID,
        last_outcome="SUCCEEDED",
        diagnostic_code="operator_futures_order_cancel_claimed",
        cancel_outcome="CLAIMED",
        cancel_exchange_invoked=False,
        cancel_target_client_order_id=CLIENT_ORDER_ID,
        cancel_exchange_order_id_sha256="c" * 64,
    )

    response = client.get("/api/v1/futures/order-operations")

    assert response.status_code == 200
    assert response.json()["authority"]["allowed_actions"] == []


def test_viewer_cannot_refresh_or_cancel(monkeypatch):
    client, service = _client(monkeypatch, roles=[AdminApiRole.VIEWER])
    common = {
        "expected_revision": 2,
        "authorize_one_no_retry_cycle": True,
        "acknowledge_cycle_is_goal_global_and_limited_to_ten": True,
        "acknowledge_unknown_read_fails_closed": True,
    }
    refresh = client.post(
        "/api/v1/futures/order-operations/refresh",
        headers={
            "Idempotency-Key": "viewer-refresh",
            "X-Correlation-Id": "corr-viewer-refresh",
            "X-Operator-Intent": "refresh_futures_order_catalog",
        },
        json=common,
    )
    cancel = client.post(
        f"/api/v1/futures/order-operations/{CLIENT_ORDER_ID}/cancel",
        headers={
            "Idempotency-Key": "viewer-cancel",
            "X-Correlation-Id": "corr-viewer-cancel",
            "X-Operator-Intent": "cancel_exact_futures_order",
        },
        json={
            **common,
            "acknowledge_unknown_cancel_consumes_allowance": True,
        },
    )

    assert refresh.status_code == 403
    assert cancel.status_code == 403
    assert service.calls == []


def test_feature_and_cancel_runtime_fail_closed(monkeypatch):
    client, service = _client(monkeypatch)
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_FUTURES_ORDER_OPERATIONS_ENABLED",
        "0",
    )
    disabled = client.get("/api/v1/futures/order-operations")
    assert disabled.status_code == 503

    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_FUTURES_ORDER_OPERATIONS_ENABLED",
        "1",
    )
    monkeypatch.setattr(
        futures_routes,
        "get_operator_futures_order_operations_execution_posture",
        lambda: FuturesOrderOperationsExecutionPosture(
            ready=False,
            diagnostic_code=(
                "operator_futures_orders_execution_posture_unavailable"
            ),
        ),
    )
    blocked = client.post(
        f"/api/v1/futures/order-operations/{CLIENT_ORDER_ID}/cancel",
        headers={
            "Idempotency-Key": "blocked-cancel",
            "X-Correlation-Id": "corr-blocked-cancel",
            "X-Operator-Intent": "cancel_exact_futures_order",
        },
        json={
            "expected_revision": 2,
            "authorize_one_no_retry_cycle": True,
            "acknowledge_cycle_is_goal_global_and_limited_to_ten": True,
            "acknowledge_unknown_read_fails_closed": True,
            "acknowledge_unknown_cancel_consumes_allowance": True,
        },
    )

    assert blocked.status_code == 503
    assert service.calls == []


def test_goal2_cancel_route_is_in_controlled_live_allowlist():
    assert (
        "POST",
        "/api/v1/futures/order-operations/{client_order_id}/cancel",
    ) in CONTROLLED_LIVE_MVP_ROUTES
