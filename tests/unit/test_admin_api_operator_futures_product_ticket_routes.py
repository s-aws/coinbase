from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.routes import futures as futures_routes
from application.admin_api.auth import get_authenticated_actor
from application.admin_api.models import AdminApiActor
from application.admin_api.operator_futures_manual_lifecycle import (
    FuturesManualGoalRecord,
)
from application.admin_api.operator_futures_product_policy import (
    FuturesProductPolicyItem,
    FuturesProductPolicyRecord,
)
from application.admin_api.operator_futures_product_ticket import (
    FuturesProductPolicySelection,
)
from application.admin_api.operator_futures_product_ticket_service import (
    FuturesProductTicketState,
)
from application.admin_api.operator_futures_product_ticket_service_runtime import (
    FuturesProductTicketExecutionPosture,
)
from core.enums import (
    AdminApiRole,
    AdminFuturesManualCallOutcome,
    AdminFuturesManualEligibilityOutcome,
)


PRODUCT_ID = "BIP-20DEC30-CDE"


def _candidate() -> dict[str, str]:
    return {
        "product_id": PRODUCT_ID,
        "side": "BUY",
        "order_type": "LIMIT_GTC",
        "post_only": "true",
        "contract_count": "1",
        "contract_code": "BIP",
        "contract_size": "0.1",
        "contract_expiry": "2030-12-20T16:00:00Z",
        "contract_expiry_type": "EXPIRING",
        "venue": "cde",
        "risk_managed_by": "MANAGED_BY_FCM",
        "product_price": "500",
        "reference_price": "501",
        "reference_price_source": (
            "max_product_price_and_fresh_best_ask"
        ),
        "price_increment": "1",
        "base_increment": "1",
        "base_min_size": "1",
        "best_bid": "499",
        "best_ask": "501",
        "limit_price": "498",
        "intraday_margin_rate": "0.25",
        "overnight_margin_rate": "0.50",
        "worst_case_margin_rate": "0.50",
        "required_margin_reference_usdc": "25.05",
        "opening_reference_notional_usdc": "50.10",
        "maximum_exposure_reference_notional_usdc": "100.20",
        "buffered_close_reference_notional_usdc": "120.24",
        "branch_turnover_reference_notional_usdc": "170.34",
        "opening_cap_usdc": "100",
        "exposure_cap_usdc": "150",
        "turnover_cap_usdc": "300",
        "close_buffer_multiplier": "1.20",
        "product_policy_revision": "4",
        "product_policy_sha256": "d" * 64,
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }


def _policy() -> FuturesProductPolicyRecord:
    return FuturesProductPolicyRecord(
        revision=4,
        snapshot_sha256="a" * 64,
        products=(
            FuturesProductPolicyItem(
                product_id="AVP-20DEC30-CDE",
                lifecycle="PENDING",
                allowed_actions=("APPROVE", "RETIRE"),
            ),
            FuturesProductPolicyItem(
                product_id=PRODUCT_ID,
                lifecycle="ENABLED",
                allowed_actions=("DISABLE", "RETIRE", "SELECT"),
            ),
        ),
        selected_product_id=PRODUCT_ID,
        selection=FuturesProductPolicySelection(
            product_id=PRODUCT_ID,
            policy_revision=4,
            policy_sha256="d" * 64,
            lifecycle="ENABLED",
        ),
        last_action="SELECT",
        last_product_id=PRODUCT_ID,
        last_correlation_id="corr-select",
        allowed_actions=["APPROVE", "ENABLE", "DISABLE", "RETIRE", "SELECT"],
        updated_at="2026-07-25T20:00:00+00:00",
    )


def _lifecycle(**updates) -> FuturesManualGoalRecord:
    record = FuturesManualGoalRecord(
        goal_id="operator_futures_product_policy_and_ticket_expansion_v1",
        revision=2,
        cycles_used=1,
        active_cycle_number=None,
        eligibility_outcome=AdminFuturesManualEligibilityOutcome.ELIGIBLE,
        eligibility_diagnostic_code=(
            "operator_futures_product_ticket_eligible"
        ),
        category_attempts={
            "api_key_permissions": 1,
            "portfolio_catalog": 1,
            "product": 1,
            "best_bid_ask": 1,
            "futures_positions": 1,
            "futures_margin_collateral": 1,
        },
        candidate=_candidate(),
        candidate_sha256="b" * 64,
        portfolio_id_sha256="c" * 64,
        eligibility_evidence_sha256="e" * 64,
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
        diagnostic_code="operator_futures_product_ticket_eligible",
        correlation_id="corr-refresh",
        audit_id="11111111-1111-4111-8111-111111111111",
        updated_at="2026-07-25T20:00:00+00:00",
    )
    return replace(record, **updates)


class _Service:
    def __init__(self) -> None:
        self.state = FuturesProductTicketState(
            policy=_policy(),
            lifecycle=_lifecycle(),
        )
        self.policy_calls: list[dict[str, object]] = []
        self.refresh_contexts = []
        self.execute_contexts = []

    def read(self):
        return self.state

    def apply_policy(self, **kwargs):
        self.policy_calls.append(kwargs)
        return self.state

    def refresh(self, *, context):
        self.refresh_contexts.append(context)
        return self.state

    def execute(self, *, context):
        self.execute_contexts.append(context)
        return self.state


def _client(
    monkeypatch,
    *,
    roles: list[AdminApiRole] | None = None,
) -> tuple[TestClient, _Service]:
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_FUTURES_PRODUCT_TICKET_ENABLED",
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
        futures_routes.get_operator_futures_product_ticket_service
    ] = lambda: service
    monkeypatch.setattr(
        futures_routes,
        "get_operator_futures_product_ticket_execution_posture",
        lambda: FuturesProductTicketExecutionPosture(
            ready=True,
            diagnostic_code=(
                "operator_futures_product_ticket_execution_posture_ready"
            ),
        ),
    )
    return TestClient(app), service


def test_get_exposes_backend_product_policy_and_dynamic_ticket(monkeypatch):
    client, _service = _client(monkeypatch)

    response = client.get("/api/v1/futures/product-ticket")

    assert response.status_code == 200
    body = response.json()
    assert body["portfolio_profile_alias"] == "Default"
    assert body["configured_product_scope"] == [
        "AVP-20DEC30-CDE",
        "BIP-20DEC30-CDE",
    ]
    assert body["selected_product_id"] == PRODUCT_ID
    assert body["products"][1]["allowed_actions"] == [
        "DISABLE",
        "RETIRE",
        "SELECT",
    ]
    assert body["candidate"]["contract_size"] == "0.1"
    assert body["candidate"]["required_margin_reference_usdc"] == "25.05"
    assert body["allowed_actions"] == [
        "APPROVE_PRODUCT",
        "DISABLE_PRODUCT",
        "RETIRE_PRODUCT",
        "SELECT_PRODUCT",
        "REFRESH_ELIGIBILITY",
        "EXECUTE_PREVIEW_GATED_PROOF",
    ]
    assert body["raw_responses_included"] is False
    assert body["private_identifiers_included"] is False
    assert body["exception_text_included"] is False


def test_get_normalizes_unattempted_eligibility_categories_to_zero(
    monkeypatch,
):
    client, service = _client(monkeypatch)
    service.state = replace(
        service.state,
        lifecycle=_lifecycle(
            category_attempts={},
            eligibility_outcome=None,
            eligibility_diagnostic_code=(
                "operator_futures_manual_not_refreshed"
            ),
            candidate=None,
            candidate_sha256=None,
            portfolio_id_sha256=None,
            eligibility_evidence_sha256=None,
            diagnostic_code="operator_futures_manual_not_refreshed",
        ),
    )

    response = client.get("/api/v1/futures/product-ticket")

    assert response.status_code == 200
    assert response.json()["category_attempts"] == {
        "api_key_permissions": 0,
        "portfolio_catalog": 0,
        "product": 0,
        "best_bid_ask": 0,
        "futures_positions": 0,
        "futures_margin_collateral": 0,
    }
    assert response.json()["eligibility_diagnostic_code"] == (
        "operator_futures_product_ticket_not_refreshed"
    )
    assert response.json()["diagnostic_code"] == (
        "operator_futures_product_ticket_not_refreshed"
    )


def test_get_withholds_policy_actions_after_preview_is_claimed(monkeypatch):
    client, service = _client(monkeypatch)
    service.state = replace(
        service.state,
        lifecycle=_lifecycle(
            preview_outcome=AdminFuturesManualCallOutcome.CLAIMED,
            preview_exchange_invoked=False,
            diagnostic_code="operator_futures_product_ticket_preview_claimed",
        ),
    )

    response = client.get("/api/v1/futures/product-ticket")

    assert response.status_code == 200
    body = response.json()
    assert all(
        product["allowed_actions"] == []
        for product in body["products"]
    )
    assert body["allowed_actions"] == []


def test_policy_command_requires_config_authority_and_forwards_no_terms(
    monkeypatch,
):
    client, service = _client(monkeypatch)

    response = client.post(
        f"/api/v1/futures/product-ticket/products/{PRODUCT_ID}/disable",
        headers={
            "Idempotency-Key": "disable-bip",
            "X-Correlation-Id": "corr-disable-bip",
            "X-Operator-Intent": (
                "disable_exact_futures_product_for_operator_ticket"
            ),
        },
        json={
            "expected_policy_revision": 4,
            "operator_reason": "operator policy review",
            "confirm_exact_product_policy_action": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["action"] == "DISABLE_PRODUCT"
    assert service.policy_calls == [
        {
            "action": "DISABLE",
            "product_id": PRODUCT_ID,
            "expected_revision": 4,
            "actor_id": "operator-1",
            "roles": ("admin", "trader"),
            "operator_reason": "operator policy review",
            "operator_intent": (
                "disable_exact_futures_product_for_operator_ticket"
            ),
            "confirm_exact_product_policy_action": True,
            "correlation_id": "corr-disable-bip",
            "idempotency_key": "disable-bip",
        }
    ]

    viewer, viewer_service = _client(
        monkeypatch,
        roles=[AdminApiRole.VIEWER],
    )
    denied = viewer.post(
        f"/api/v1/futures/product-ticket/products/{PRODUCT_ID}/disable",
        headers={
            "Idempotency-Key": "viewer-disable",
            "X-Correlation-Id": "corr-viewer-disable",
            "X-Operator-Intent": (
                "disable_exact_futures_product_for_operator_ticket"
            ),
        },
        json={
            "expected_policy_revision": 4,
            "operator_reason": "must be rejected",
            "confirm_exact_product_policy_action": True,
        },
    )
    assert denied.status_code == 403
    assert viewer_service.policy_calls == []


def test_refresh_and_execute_use_distinct_backend_owned_intents(monkeypatch):
    client, service = _client(monkeypatch)

    refreshed = client.post(
        "/api/v1/futures/product-ticket/eligibility",
        headers={
            "Idempotency-Key": "ticket-refresh",
            "X-Correlation-Id": "corr-ticket-refresh",
            "X-Operator-Intent": (
                "refresh_one_futures_product_ticket_eligibility_cycle"
            ),
        },
        json={
            "expected_ticket_revision": 2,
            "authorize_one_no_retry_six_category_cycle": True,
            "acknowledge_cycle_is_goal_global_and_limited_to_ten": True,
            "acknowledge_unsuccessful_or_unknown_cycle_fails_closed": True,
        },
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["action"] == "REFRESH_ELIGIBILITY"
    assert len(service.refresh_contexts) == 1
    assert service.refresh_contexts[0].expected_revision == 2

    executed = client.post(
        "/api/v1/futures/product-ticket/execute",
        headers={
            "Idempotency-Key": "ticket-execute",
            "X-Correlation-Id": "corr-ticket-execute",
            "X-Operator-Intent": (
                "preview_submit_and_safe_closeout_one_futures_product_ticket"
            ),
        },
        json={
            "expected_ticket_revision": 2,
            "authorize_preview_create_and_safe_closeout": True,
            "acknowledge_unknown_outcome_consumes_allowance": True,
            "acknowledge_create_requires_accepted_identical_preview": True,
            "acknowledge_cancel_is_only_for_exact_nonterminal_child": True,
        },
    )
    assert executed.status_code == 200
    assert executed.json()["action"] == "EXECUTE_PREVIEW_GATED_PROOF"
    assert len(service.execute_contexts) == 1


def test_execute_fails_before_service_when_runtime_is_not_ready(monkeypatch):
    client, service = _client(monkeypatch)
    monkeypatch.setattr(
        futures_routes,
        "get_operator_futures_product_ticket_execution_posture",
        lambda: FuturesProductTicketExecutionPosture(
            ready=False,
            diagnostic_code=(
                "operator_futures_product_ticket_service_decision_unavailable"
            ),
        ),
    )

    response = client.post(
        "/api/v1/futures/product-ticket/execute",
        headers={
            "Idempotency-Key": "ticket-execute-blocked",
            "X-Correlation-Id": "corr-ticket-execute-blocked",
            "X-Operator-Intent": (
                "preview_submit_and_safe_closeout_one_futures_product_ticket"
            ),
        },
        json={
            "expected_ticket_revision": 2,
            "authorize_preview_create_and_safe_closeout": True,
            "acknowledge_unknown_outcome_consumes_allowance": True,
            "acknowledge_create_requires_accepted_identical_preview": True,
            "acknowledge_cancel_is_only_for_exact_nonterminal_child": True,
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "operator_futures_product_ticket_live_runtime_unavailable"
    )
    assert service.execute_contexts == []


def test_feature_flag_fails_closed(monkeypatch):
    client, _service = _client(monkeypatch)
    monkeypatch.delenv(
        "COINBASE_ADMIN_API_OPERATOR_FUTURES_PRODUCT_TICKET_ENABLED"
    )

    response = client.get("/api/v1/futures/product-ticket")

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "operator_futures_product_ticket_disabled"
    )
