from __future__ import annotations

from dataclasses import replace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.routes import futures as futures_routes
from application.admin_api.auth import get_authenticated_actor
from application.admin_api.models import AdminApiActor
from application.admin_api.operator_futures_follow_up_intent import (
    FUTURES_FOLLOW_UP_INTENT_GOAL_ID,
    FuturesFollowUpIntentEligibility,
    FuturesFollowUpIntentReadback,
    FuturesFollowUpIntentRecord,
)
from core.enums import AdminApiRole


SOURCE_ID = "00000000-0000-4000-8000-000000000064"
OBSERVED_AT = "2026-07-25T12:00:00+00:00"
EVIDENCE_SHA256 = "a" * 64


def _eligibility() -> FuturesFollowUpIntentEligibility:
    return FuturesFollowUpIntentEligibility(
        eligible=True,
        blockers=(),
        source_found=True,
        source_product_configured=True,
        source_status_open=True,
        source_authoritatively_nonterminal=True,
        source_exactly_one_contract=True,
        source_side_valid=True,
        follow_up_intent_absent=True,
        product_id="AVP-20DEC30-CDE",
        source_side="BUY",
        derived_follow_up_side="SELL",
        contract_count="1",
        source_status="OPEN",
        source_observed_at=OBSERVED_AT,
        source_evidence_sha256=EVIDENCE_SHA256,
    )


def _record() -> FuturesFollowUpIntentRecord:
    return FuturesFollowUpIntentRecord(
        goal_id=FUTURES_FOLLOW_UP_INTENT_GOAL_ID,
        follow_up_intent_id="00000000-0000-4000-8000-000000000065",
        source_client_order_id=SOURCE_ID,
        root_client_order_id=SOURCE_ID,
        product_id="AVP-20DEC30-CDE",
        source_side="BUY",
        derived_follow_up_side="SELL",
        contract_count="1",
        state="ATTACHED",
        source_status_at_attach="OPEN",
        source_observed_at=OBSERVED_AT,
        source_evidence_sha256=EVIDENCE_SHA256,
        reason_code="FULL_FILL_OPPOSITE_ONE_CONTRACT",
        correlation_id="00000000-0000-4000-8000-000000000066",
        audit_id="00000000-0000-4000-8000-000000000067",
        created_at=OBSERVED_AT,
    )


class _Service:
    def __init__(self) -> None:
        self.readback = FuturesFollowUpIntentReadback(
            goal_id=FUTURES_FOLLOW_UP_INTENT_GOAL_ID,
            source_client_order_id=SOURCE_ID,
            eligibility=_eligibility(),
            follow_up_intent=None,
        )
        self.attach_calls: list[dict[str, object]] = []

    def read(self, source_client_order_id: str):
        assert source_client_order_id == SOURCE_ID
        return self.readback

    def attach(self, **kwargs):
        self.attach_calls.append(kwargs)
        self.readback = replace(
            self.readback,
            eligibility=replace(
                self.readback.eligibility,
                eligible=False,
                blockers=("futures_follow_up_intent_already_attached",),
                follow_up_intent_absent=False,
            ),
            follow_up_intent=_record(),
        )
        return self.readback, False


def _client(
    monkeypatch,
    *,
    roles: list[AdminApiRole] | None = None,
) -> tuple[TestClient, _Service]:
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_FUTURES_FOLLOW_UP_INTENT_ENABLED",
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
        futures_routes.get_operator_futures_follow_up_intent_service
    ] = lambda: service
    return TestClient(app), service


def test_read_exposes_call_free_backend_eligibility(monkeypatch) -> None:
    client, _ = _client(monkeypatch)

    response = client.get(
        f"/api/v1/futures/order-operations/{SOURCE_ID}/follow-up-intent"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["goal_id"] == FUTURES_FOLLOW_UP_INTENT_GOAL_ID
    assert body["source_client_order_id"] == SOURCE_ID
    assert body["eligibility"]["eligible"] is True
    assert body["eligibility"]["derived_follow_up_side"] == "SELL"
    assert body["eligibility"]["contract_count"] == "1"
    assert body["allowed_actions"] == ["ATTACH_FOLLOW_UP_INTENT"]
    assert body["page_load_coinbase_calls"] == 0
    assert body["child_created"] is False
    assert body["raw_responses_included"] is False
    assert body["private_identifiers_included"] is False
    assert body["exception_text_included"] is False


def test_attach_forwards_only_exact_backend_binding_and_confirmations(
    monkeypatch,
) -> None:
    client, service = _client(monkeypatch)

    response = client.post(
        f"/api/v1/futures/order-operations/{SOURCE_ID}/follow-up-intent",
        headers={
            "Idempotency-Key": (
                "00000000-0000-4000-8000-000000000068"
            ),
            "X-Correlation-Id": (
                "00000000-0000-4000-8000-000000000069"
            ),
            "X-Operator-Intent": "attach_futures_follow_up_intent",
        },
        json={
            "expected_source_observed_at": OBSERVED_AT,
            "expected_source_evidence_sha256": EVIDENCE_SHA256,
            "reason_code": "FULL_FILL_OPPOSITE_ONE_CONTRACT",
            "acknowledge_future_materialization_requires_fresh_authorization": True,
            "acknowledge_no_coinbase_call_or_child_creation": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["replayed"] is False
    assert body["follow_up_intent"]["source_client_order_id"] == SOURCE_ID
    assert body["follow_up_intent"]["root_client_order_id"] == SOURCE_ID
    assert body["follow_up_intent"]["derived_follow_up_side"] == "SELL"
    assert body["follow_up_intent"]["contract_count"] == "1"
    assert body["coinbase_calls"] == 0
    assert body["child_created"] is False
    assert len(service.attach_calls) == 1
    call = service.attach_calls[0]
    context = call["context"]
    assert context.actor_id == "operator-1"
    assert context.operator_intent == "attach_futures_follow_up_intent"
    assert (
        context.acknowledge_no_coinbase_call_or_child_creation is True
    )


def test_viewer_can_read_but_cannot_attach(monkeypatch) -> None:
    client, _ = _client(monkeypatch, roles=[AdminApiRole.VIEWER])

    read = client.get(
        f"/api/v1/futures/order-operations/{SOURCE_ID}/follow-up-intent"
    )
    attach = client.post(
        f"/api/v1/futures/order-operations/{SOURCE_ID}/follow-up-intent",
        headers={
            "Idempotency-Key": "viewer-key",
            "X-Correlation-Id": "viewer-correlation",
            "X-Operator-Intent": "attach_futures_follow_up_intent",
        },
        json={
            "expected_source_observed_at": OBSERVED_AT,
            "expected_source_evidence_sha256": EVIDENCE_SHA256,
            "reason_code": "FULL_FILL_OPPOSITE_ONE_CONTRACT",
            "acknowledge_future_materialization_requires_fresh_authorization": True,
            "acknowledge_no_coinbase_call_or_child_creation": True,
        },
    )

    assert read.status_code == 200
    assert read.json()["allowed_actions"] == []
    assert attach.status_code == 403


def test_feature_disabled_fails_closed_without_service_call(monkeypatch) -> None:
    client, _ = _client(monkeypatch)
    monkeypatch.delenv(
        "COINBASE_ADMIN_API_OPERATOR_FUTURES_FOLLOW_UP_INTENT_ENABLED"
    )

    response = client.get(
        f"/api/v1/futures/order-operations/{SOURCE_ID}/follow-up-intent"
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "operator_futures_follow_up_intent_disabled"
    )
