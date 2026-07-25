from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.routes import futures as futures_routes
from application.admin_api.auth import get_authenticated_actor
from application.admin_api.futures_public_projection import (
    opaque_futures_position_key,
)
from application.admin_api.models import AdminApiActor
from application.admin_api.operator_futures_position_lifecycle import (
    FuturesPositionGoalRecord,
)
from application.admin_api.operator_futures_position_service_runtime import (
    FuturesPositionExecutionPosture,
)
from application.admin_api.read_service import CONTROLLED_LIVE_MVP_ROUTES
from core.enums import (
    AdminApiRole,
    AdminFuturesPositionCallOutcome,
    AdminFuturesPositionEligibilityOutcome,
)


PORTFOLIO_ID = "11111111-1111-4111-8111-111111111111"
PRODUCT_ID = "AVP-20DEC30-CDE"
POSITION_KEY = opaque_futures_position_key(
    product_id=PRODUCT_ID,
    portfolio_identity=PORTFOLIO_ID,
)


def _record(**updates):
    record = FuturesPositionGoalRecord(
        goal_id=(
            "operator_futures_position_close_reduce_and_reconciliation_v1"
        ),
        revision=2,
        cycles_used=1,
        active_cycle_number=None,
        eligibility_outcome=AdminFuturesPositionEligibilityOutcome.ELIGIBLE,
        eligibility_diagnostic_code=(
            "operator_futures_position_exact_position_eligible"
        ),
        category_attempts={
            "api_key_permissions": 1,
            "portfolio_catalog": 1,
            "futures_positions": 1,
            "product": 1,
            "best_bid_ask": 1,
            "futures_margin_collateral": 1,
        },
        selection={
            "position_key": POSITION_KEY,
            "product_id": PRODUCT_ID,
            "position_side": "LONG",
            "close_side": "SELL",
            "current_contracts": "3",
            "full_close_size": "3",
            "bounded_reduce_size": "1",
            "best_bid": "6.45",
            "best_ask": "6.47",
            "observed_at": datetime.now(timezone.utc).isoformat(),
        },
        selection_sha256="a" * 64,
        portfolio_id_sha256="b" * 64,
        eligibility_evidence_sha256="c" * 64,
        selected_mode=None,
        client_order_id=None,
        action_outcome=AdminFuturesPositionCallOutcome.NOT_RUN,
        action_exchange_invoked=None,
        exchange_order_id_sha256=None,
        order_reconciliation_outcome=(
            AdminFuturesPositionCallOutcome.NOT_RUN
        ),
        order_reconciliation_exchange_invoked=None,
        order_status=None,
        authoritatively_nonterminal=None,
        position_reconciliation_outcome=(
            AdminFuturesPositionCallOutcome.NOT_RUN
        ),
        position_reconciliation_exchange_invoked=None,
        remaining_contracts=None,
        cancel_outcome=AdminFuturesPositionCallOutcome.NOT_RUN,
        cancel_exchange_invoked=None,
        diagnostic_code=(
            "operator_futures_position_exact_position_eligible"
        ),
        correlation_id="corr-1",
        audit_id="11111111-1111-4111-8111-111111111111",
        updated_at="2026-07-24T00:00:00+00:00",
    )
    return replace(record, **updates)


class _Service:
    def __init__(self):
        self.record = _record()
        self.refresh_calls = []
        self.execute_calls = []

    def read(self):
        return self.record

    def refresh(self, *, context, position_key):
        self.refresh_calls.append((context, position_key))
        self.record = replace(
            self.record,
            revision=self.record.revision + 1,
            cycles_used=self.record.cycles_used + 1,
        )
        return self.record

    def execute(self, *, context, mode):
        self.execute_calls.append((context, mode))
        self.record = replace(
            self.record,
            revision=self.record.revision + 1,
            selected_mode=mode,
            client_order_id="goal11-close-1",
            action_outcome=AdminFuturesPositionCallOutcome.ACCEPTED,
            action_exchange_invoked=True,
            exchange_order_id_sha256="d" * 64,
            order_reconciliation_outcome=(
                AdminFuturesPositionCallOutcome.ACCEPTED
            ),
            order_reconciliation_exchange_invoked=True,
            order_status="FILLED",
            authoritatively_nonterminal=False,
            position_reconciliation_outcome=(
                AdminFuturesPositionCallOutcome.ACCEPTED
            ),
            position_reconciliation_exchange_invoked=True,
            remaining_contracts="0",
        )
        return self.record


def _client(monkeypatch, *, roles=None):
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_FUTURES_POSITION_ENABLED",
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
        futures_routes.get_operator_futures_position_lifecycle_service
    ] = lambda: service
    monkeypatch.setattr(
        futures_routes,
        "get_operator_futures_position_execution_posture",
        lambda: FuturesPositionExecutionPosture(
            ready=True,
            diagnostic_code=(
                "operator_futures_position_execution_posture_ready"
            ),
        ),
    )
    return TestClient(app), service


def test_readback_exposes_backend_actions_without_private_identity(monkeypatch):
    client, _service = _client(monkeypatch)

    response = client.get("/api/v1/futures/position-lifecycle")

    assert response.status_code == 200
    body = response.json()
    assert body["allowed_actions"] == [
        "REFRESH_SELECTED_POSITION",
        "CLOSE_FULL",
        "REDUCE_ONE_CONTRACT",
    ]
    assert body["selection"]["position_key"] == POSITION_KEY
    assert body["selection"]["current_contracts"] == "3"
    assert "observed_at" not in body["selection"]
    assert body["private_identifiers_included"] is False
    assert body["raw_responses_included"] is False


def test_goal11_execute_route_is_in_the_operator_capability_live_allowlist():
    assert (
        "POST",
        "/api/v1/futures/position-lifecycle/execute",
    ) in CONTROLLED_LIVE_MVP_ROUTES


def test_viewer_has_no_position_mutation_actions(monkeypatch):
    client, _service = _client(
        monkeypatch,
        roles=[AdminApiRole.VIEWER],
    )

    response = client.get("/api/v1/futures/position-lifecycle")

    assert response.status_code == 200
    assert response.json()["allowed_actions"] == []


def test_refresh_binds_the_selected_opaque_position_key(monkeypatch):
    client, service = _client(monkeypatch)

    response = client.post(
        "/api/v1/futures/position-lifecycle/eligibility",
        headers={
            "Idempotency-Key": "refresh-position-1",
            "X-Correlation-Id": "corr-refresh-position-1",
            "X-Operator-Intent": (
                "refresh_one_futures_position_eligibility_cycle"
            ),
        },
        json={
            "expected_revision": 2,
            "position_key": POSITION_KEY,
            "authorize_one_no_retry_six_category_cycle": True,
            "acknowledge_cycle_is_goal_global_and_limited_to_ten": True,
            "acknowledge_unsuccessful_or_unknown_cycle_fails_closed": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["action"] == "REFRESH_SELECTED_POSITION"
    assert service.refresh_calls[0][1] == POSITION_KEY


def test_execute_forwards_only_one_explicit_mode_with_all_confirmations(
    monkeypatch,
):
    client, service = _client(monkeypatch)
    headers = {
        "Idempotency-Key": "close-position-1",
        "X-Correlation-Id": "corr-close-position-1",
        "X-Operator-Intent": (
            "authorize_one_futures_position_close_or_reduce"
        ),
    }

    incomplete = client.post(
        "/api/v1/futures/position-lifecycle/execute",
        headers=headers,
        json={
            "expected_revision": 2,
            "mode": "CLOSE_FULL",
            "authorize_exact_selected_position_action": True,
        },
    )
    assert incomplete.status_code == 422
    assert service.execute_calls == []

    response = client.post(
        "/api/v1/futures/position-lifecycle/execute",
        headers=headers,
        json={
            "expected_revision": 2,
            "mode": "CLOSE_FULL",
            "authorize_exact_selected_position_action": True,
            "acknowledge_action_is_mutually_exclusive_and_single_use": True,
            "acknowledge_unknown_outcome_consumes_allowance": True,
            "acknowledge_exact_order_cancel_only": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["action"] == "CLOSE_FULL"
    assert response.json()["result"]["action_call"]["outcome"] == "ACCEPTED"
    assert len(service.execute_calls) == 1
    assert service.execute_calls[0][1] == "CLOSE_FULL"


def test_execute_fails_closed_when_controlled_live_posture_is_not_ready(
    monkeypatch,
):
    client, service = _client(monkeypatch)
    monkeypatch.setattr(
        futures_routes,
        "get_operator_futures_position_execution_posture",
        lambda: FuturesPositionExecutionPosture(
            ready=False,
            diagnostic_code=(
                "operator_futures_position_service_decision_unavailable"
            ),
        ),
    )

    response = client.post(
        "/api/v1/futures/position-lifecycle/execute",
        headers={
            "Idempotency-Key": "close-position-1",
            "X-Correlation-Id": "corr-close-position-1",
            "X-Operator-Intent": (
                "authorize_one_futures_position_close_or_reduce"
            ),
        },
        json={
            "expected_revision": 2,
            "mode": "CLOSE_FULL",
            "authorize_exact_selected_position_action": True,
            "acknowledge_action_is_mutually_exclusive_and_single_use": True,
            "acknowledge_unknown_outcome_consumes_allowance": True,
            "acknowledge_exact_order_cancel_only": True,
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "operator_futures_position_live_runtime_unavailable"
    )
    assert service.execute_calls == []
