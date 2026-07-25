from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.routes import futures as futures_routes
from application.admin_api.auth import get_authenticated_actor
from application.admin_api.models import AdminApiActor
from application.admin_api.operator_futures_manual_lifecycle import (
    FuturesManualGoalRecord,
    FuturesManualLifecycleError,
    is_futures_manual_goal_terminal,
)
from application.admin_api.operator_futures_manual_service_runtime import (
    FuturesManualExecutionPosture,
)
from core.enums import (
    AdminApiRole,
    AdminFuturesManualCallOutcome,
    AdminFuturesManualEligibilityOutcome,
)


def _record(**updates):
    record = FuturesManualGoalRecord(
        goal_id="operator_futures_manual_order_lifecycle_v1",
        revision=2,
        cycles_used=1,
        active_cycle_number=None,
        eligibility_outcome=AdminFuturesManualEligibilityOutcome.ELIGIBLE,
        eligibility_diagnostic_code=(
            "operator_futures_manual_exact_v3_eligible"
        ),
        category_attempts={
            "api_key_permissions": 1,
            "portfolio_catalog": 1,
            "product": 1,
            "best_bid_ask": 1,
            "futures_positions": 1,
            "futures_margin_collateral": 1,
        },
        candidate={
            "product_id": "AVP-20DEC30-CDE",
            "side": "BUY",
            "order_type": "LIMIT_GTC",
            "post_only": "true",
            "contract_count": "1",
            "limit_price": "6.45",
            "contract_size": "10",
            "opening_reference_notional_usdc": "64.80",
            "maximum_exposure_reference_notional_usdc": "129.60",
            "buffered_close_reference_notional_usdc": "129.60",
            "branch_turnover_reference_notional_usdc": "259.20",
            "opening_cap_usdc": "100",
            "exposure_cap_usdc": "150",
            "turnover_cap_usdc": "300",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "reference_price_source": "best_bid_ask",
        },
        candidate_sha256="a" * 64,
        portfolio_id_sha256="b" * 64,
        eligibility_evidence_sha256="c" * 64,
        client_order_id=None,
        preview_outcome=AdminFuturesManualCallOutcome.NOT_RUN,
        preview_exchange_invoked=None,
        preview_id_sha256=None,
        create_outcome=AdminFuturesManualCallOutcome.NOT_RUN,
        create_exchange_invoked=None,
        exchange_order_id_sha256=None,
        reconciliation_outcome=AdminFuturesManualCallOutcome.NOT_RUN,
        reconciliation_exchange_invoked=None,
        order_status=None,
        authoritatively_nonterminal=None,
        cancel_outcome=AdminFuturesManualCallOutcome.NOT_RUN,
        cancel_exchange_invoked=None,
        diagnostic_code="operator_futures_manual_exact_v3_eligible",
        correlation_id="corr-1",
        audit_id="11111111-1111-4111-8111-111111111111",
        updated_at="2026-07-24T00:00:00+00:00",
    )
    return replace(record, **updates)


class _Service:
    def __init__(self):
        self.record = _record()
        self.refresh_contexts = []
        self.execute_contexts = []

    def read(self):
        return self.record

    def refresh(self, *, context):
        self.refresh_contexts.append(context)
        if is_futures_manual_goal_terminal(
            self.record.eligibility_diagnostic_code
        ):
            self.refresh_contexts.pop()
            raise FuturesManualLifecycleError(
                "operator_futures_manual_goal_terminal"
            )
        self.record = replace(
            self.record,
            revision=self.record.revision + 1,
            cycles_used=self.record.cycles_used + 1,
        )
        return self.record

    def execute(self, *, context):
        self.execute_contexts.append(context)
        self.record = replace(
            self.record,
            revision=self.record.revision + 1,
            client_order_id="operator-futures-manual-child",
            preview_outcome=AdminFuturesManualCallOutcome.ACCEPTED,
            preview_exchange_invoked=True,
            preview_id_sha256="d" * 64,
            create_outcome=AdminFuturesManualCallOutcome.ACCEPTED,
            create_exchange_invoked=True,
            exchange_order_id_sha256="e" * 64,
            reconciliation_outcome=(
                AdminFuturesManualCallOutcome.ACCEPTED
            ),
            reconciliation_exchange_invoked=True,
            order_status="FILLED",
            authoritatively_nonterminal=False,
        )
        return self.record


def _client(
    monkeypatch,
    *,
    roles: list[AdminApiRole] | None = None,
):
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_FUTURES_MANUAL_ENABLED",
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
        futures_routes.get_operator_futures_manual_lifecycle_service
    ] = lambda: service
    monkeypatch.setattr(
        futures_routes,
        "get_operator_futures_manual_execution_posture",
        lambda: FuturesManualExecutionPosture(
            ready=True,
            diagnostic_code=(
                "operator_futures_manual_execution_posture_ready"
            ),
        ),
    )
    return TestClient(app), service


def test_get_exposes_backend_authority_without_private_identifiers(
    monkeypatch,
):
    client, _service = _client(monkeypatch)

    response = client.get("/api/v1/futures/manual-lifecycle")

    assert response.status_code == 200
    body = response.json()
    assert body["product_scope"] == "AVP-20DEC30-CDE"
    assert body["contract_count"] == "1"
    assert body["strict_opening_cap_usdc"] == "100"
    assert body["strict_exposure_cap_usdc"] == "150"
    assert body["strict_turnover_cap_usdc"] == "300"
    assert body["allowed_actions"] == [
        "REFRESH_ELIGIBILITY",
        "EXECUTE_PREVIEW_GATED_PROOF",
    ]
    assert body["candidate_fresh_for_execution"] is True
    assert body["execution_posture_ready"] is True
    assert (
        body["candidate_freshness_diagnostic_code"]
        == "operator_futures_manual_candidate_fresh"
    )
    assert body["private_identifiers_included"] is False
    assert "observed_at" not in body["candidate"]
    assert "reference_price_source" not in body["candidate"]


def test_get_withholds_actions_from_analytics_only_actor(monkeypatch):
    client, _service = _client(
        monkeypatch,
        roles=[AdminApiRole.VIEWER],
    )

    response = client.get("/api/v1/futures/manual-lifecycle")

    assert response.status_code == 200
    assert response.json()["allowed_actions"] == []


def test_get_removes_execute_authority_when_candidate_is_stale(monkeypatch):
    client, service = _client(monkeypatch)
    service.record = replace(
        service.record,
        candidate={
            **service.record.candidate,
            "observed_at": (
                datetime.now(timezone.utc) - timedelta(seconds=31)
            ).isoformat(),
        },
    )

    response = client.get("/api/v1/futures/manual-lifecycle")

    assert response.status_code == 200
    body = response.json()
    assert body["allowed_actions"] == ["REFRESH_ELIGIBILITY"]
    assert body["candidate_fresh_for_execution"] is False
    assert (
        body["candidate_freshness_diagnostic_code"]
        == "operator_futures_manual_candidate_stale"
    )


def test_get_closes_refresh_authority_after_terminal_positions_forbidden(
    monkeypatch,
):
    client, service = _client(monkeypatch)
    service.record = replace(
        service.record,
        revision=4,
        cycles_used=2,
        eligibility_outcome=AdminFuturesManualEligibilityOutcome.UNKNOWN,
        eligibility_diagnostic_code=(
            "operator_futures_manual_futures_positions_http_forbidden"
        ),
        category_attempts={
            "api_key_permissions": 1,
            "portfolio_catalog": 1,
            "product": 1,
            "best_bid_ask": 1,
            "futures_positions": 1,
            "futures_margin_collateral": 0,
        },
        candidate=None,
        candidate_sha256=None,
        portfolio_id_sha256=None,
        eligibility_evidence_sha256=None,
        diagnostic_code=(
            "operator_futures_manual_futures_positions_http_forbidden"
        ),
    )

    response = client.get("/api/v1/futures/manual-lifecycle")

    assert response.status_code == 200
    body = response.json()
    assert body["cycles_used"] == 2
    assert body["cycles_remaining"] == 8
    assert body["allowed_actions"] == []


def test_get_and_execute_fail_closed_when_futures_posture_is_not_ready(
    monkeypatch,
):
    client, service = _client(monkeypatch)
    monkeypatch.setattr(
        futures_routes,
        "get_operator_futures_manual_execution_posture",
        lambda: FuturesManualExecutionPosture(
            ready=False,
            diagnostic_code=(
                "operator_futures_manual_service_decision_unavailable"
            ),
        ),
    )

    read_response = client.get("/api/v1/futures/manual-lifecycle")

    assert read_response.status_code == 200
    body = read_response.json()
    assert body["execution_posture_ready"] is False
    assert body["execution_posture_diagnostic_code"] == (
        "operator_futures_manual_service_decision_unavailable"
    )
    assert body["allowed_actions"] == ["REFRESH_ELIGIBILITY"]

    execute_response = client.post(
        "/api/v1/futures/manual-lifecycle/execute",
        headers={
            "Idempotency-Key": "execute-blocked",
            "X-Correlation-Id": "corr-execute-blocked",
            "X-Operator-Intent": (
                "preview_submit_and_safe_closeout_one_futures_order"
            ),
        },
        json={
            "expected_revision": 2,
            "authorize_preview_create_and_safe_closeout": True,
            "acknowledge_unknown_outcome_consumes_allowance": True,
            "acknowledge_create_requires_accepted_identical_preview": True,
            "acknowledge_cancel_is_only_for_exact_nonterminal_child": True,
        },
    )
    assert execute_response.status_code == 503
    assert execute_response.json()["detail"] == (
        "operator_futures_manual_live_runtime_unavailable"
    )
    assert service.execute_contexts == []


def test_refresh_forwards_only_explicit_operator_intent(monkeypatch):
    client, service = _client(monkeypatch)

    response = client.post(
        "/api/v1/futures/manual-lifecycle/eligibility",
        headers={
            "Idempotency-Key": "refresh-1",
            "X-Correlation-Id": "corr-refresh-1",
            "X-Operator-Intent": (
                "refresh_one_futures_manual_eligibility_cycle"
            ),
        },
        json={
            "expected_revision": 2,
            "authorize_one_no_retry_six_category_cycle": True,
            "acknowledge_cycle_is_goal_global_and_limited_to_ten": True,
            "acknowledge_unsuccessful_or_unknown_cycle_fails_closed": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["action"] == "REFRESH_ELIGIBILITY"
    assert len(service.refresh_contexts) == 1
    assert service.refresh_contexts[0].idempotency_key == "refresh-1"


def test_refresh_route_rejects_terminal_goal_without_service_mutation(
    monkeypatch,
):
    client, service = _client(monkeypatch)
    service.record = replace(
        service.record,
        cycles_used=2,
        eligibility_outcome=AdminFuturesManualEligibilityOutcome.UNKNOWN,
        eligibility_diagnostic_code=(
            "operator_futures_manual_futures_positions_http_forbidden"
        ),
        diagnostic_code=(
            "operator_futures_manual_futures_positions_http_forbidden"
        ),
        candidate=None,
    )

    response = client.post(
        "/api/v1/futures/manual-lifecycle/eligibility",
        headers={
            "Idempotency-Key": "refresh-after-terminal",
            "X-Correlation-Id": "corr-refresh-after-terminal",
            "X-Operator-Intent": (
                "refresh_one_futures_manual_eligibility_cycle"
            ),
        },
        json={
            "expected_revision": 2,
            "authorize_one_no_retry_six_category_cycle": True,
            "acknowledge_cycle_is_goal_global_and_limited_to_ten": True,
            "acknowledge_unsuccessful_or_unknown_cycle_fails_closed": True,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "operator_futures_manual_goal_terminal"
    )
    assert service.refresh_contexts == []


def test_execute_requires_all_confirmations_and_forwards_one_intent(
    monkeypatch,
):
    client, service = _client(monkeypatch)
    headers = {
        "Idempotency-Key": "execute-1",
        "X-Correlation-Id": "corr-execute-1",
        "X-Operator-Intent": (
            "preview_submit_and_safe_closeout_one_futures_order"
        ),
    }
    incomplete = client.post(
        "/api/v1/futures/manual-lifecycle/execute",
        headers=headers,
        json={
            "expected_revision": 2,
            "authorize_preview_create_and_safe_closeout": True,
            "acknowledge_unknown_outcome_consumes_allowance": True,
        },
    )
    assert incomplete.status_code == 422
    assert service.execute_contexts == []

    response = client.post(
        "/api/v1/futures/manual-lifecycle/execute",
        headers=headers,
        json={
            "expected_revision": 2,
            "authorize_preview_create_and_safe_closeout": True,
            "acknowledge_unknown_outcome_consumes_allowance": True,
            "acknowledge_create_requires_accepted_identical_preview": True,
            "acknowledge_cancel_is_only_for_exact_nonterminal_child": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["result"]["create"]["outcome"] == "ACCEPTED"
    assert len(service.execute_contexts) == 1
    assert (
        service.execute_contexts[0]
        .authorize_preview_create_and_safe_closeout
        is True
    )


def test_route_is_fail_closed_when_feature_is_not_installed(monkeypatch):
    client, _service = _client(monkeypatch)
    monkeypatch.delenv(
        "COINBASE_ADMIN_API_OPERATOR_FUTURES_MANUAL_ENABLED"
    )

    response = client.get("/api/v1/futures/manual-lifecycle")

    assert response.status_code == 503
    assert response.json()["detail"] == "operator_futures_manual_disabled"
