from __future__ import annotations

from dataclasses import replace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.routes import futures as futures_routes
from application.admin_api.auth import (
    ROLE_PERMISSIONS,
    get_authenticated_actor,
)
from application.admin_api.models import AdminApiActor
from application.admin_api.operator_futures_fill_triggered_follow_up import (
    FUTURES_FILL_TRIGGERED_FOLLOW_UP_GOAL_ID,
    FuturesFillTriggeredActivationRecord,
    FuturesFillTriggeredControlState,
    FuturesFillTriggeredTriggerState,
)
from core.enums import AdminApiPermission, AdminApiRole


SOURCE_ID = "00000000-0000-4000-8000-000000000571"


def _record():
    return FuturesFillTriggeredActivationRecord(
        goal_id=FUTURES_FILL_TRIGGERED_FOLLOW_UP_GOAL_ID,
        source_client_order_id=SOURCE_ID,
        follow_up_intent_id=(
            "00000000-0000-4000-8000-000000000572"
        ),
        control_state=FuturesFillTriggeredControlState.DISABLED,
        trigger_state=FuturesFillTriggeredTriggerState.UNCLAIMED,
        revision=0,
        delegated_live_authority=False,
        trigger_claim_id=None,
        trigger_evidence_sha256=None,
        lifecycle_revision=0,
        child_client_order_id=None,
        preview_outcome="NOT_RUN",
        create_outcome="NOT_RUN",
        reconciliation_outcome="NOT_RUN",
        cancel_outcome="NOT_RUN",
        diagnostic_code=(
            "operator_futures_fill_triggered_follow_up_disabled"
        ),
        actor_id="operator-1",
        roles=("admin", "trader"),
        correlation_id="goal5-intent-correlation",
        audit_id="00000000-0000-4000-8000-000000000573",
        recorded_at="2026-07-25T12:00:00+00:00",
        updated_at="2026-07-25T12:00:00+00:00",
    )


class _Service:
    def __init__(self):
        self.record = _record()
        self.control_calls = []

    def read(self, source_client_order_id):
        assert source_client_order_id == SOURCE_ID
        return self.record

    def control(self, **kwargs):
        self.control_calls.append(kwargs)
        self.record = replace(
            self.record,
            control_state=FuturesFillTriggeredControlState.ENABLED,
            revision=1,
            delegated_live_authority=True,
        )
        return self.record


def _client(monkeypatch, *, viewer=False, roles=None):
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_FUTURES_FILL_TRIGGERED_FOLLOW_UP_ENABLED",
        "1",
    )
    monkeypatch.setattr(
        futures_routes,
        "operator_futures_fill_triggered_execution_ready",
        lambda: True,
        raising=False,
    )
    service = _Service()
    app = FastAPI()
    app.include_router(futures_routes.router, prefix="/api/v1")
    app.dependency_overrides[get_authenticated_actor] = lambda: AdminApiActor(
        actor_id="operator-1",
        roles=roles or (
            [AdminApiRole.VIEWER]
            if viewer
            else [AdminApiRole.ADMIN, AdminApiRole.TRADER]
        ),
    )
    dependency = getattr(
        futures_routes,
        "get_operator_futures_fill_triggered_follow_up_service",
        lambda: None,
    )
    app.dependency_overrides[dependency] = lambda: service
    return TestClient(app), service


def test_read_exposes_postgresql_control_authority_without_coinbase_call(
    monkeypatch,
) -> None:
    client, _ = _client(monkeypatch)

    response = client.get(
        f"/api/v1/futures/order-operations/{SOURCE_ID}/"
        "follow-up-intent/fill-triggered-activation"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["goal_id"] == (
        FUTURES_FILL_TRIGGERED_FOLLOW_UP_GOAL_ID
    )
    assert body["portfolio_profile_alias"] == "Default"
    assert body["control_state"] == "DISABLED"
    assert body["trigger_state"] == "UNCLAIMED"
    assert body["operator_intent"] == (
        "control_futures_fill_triggered_follow_up"
    )
    assert body["caps"] == {
        "opening_usdc": "100",
        "exposure_usdc": "150",
        "turnover_usdc": "300",
        "comparison": "strictly_less_than",
    }
    assert body["allowed_actions"] == ["ENABLE", "DRAIN"]
    assert body["page_load_coinbase_calls"] == 0
    assert body["raw_responses_included"] is False


def test_enable_forwards_only_explicit_authority_and_backend_identity(
    monkeypatch,
) -> None:
    client, service = _client(monkeypatch)

    response = client.post(
        f"/api/v1/futures/order-operations/{SOURCE_ID}/"
        "follow-up-intent/fill-triggered-activation",
        headers={
            "Idempotency-Key": "goal5-enable",
            "X-Correlation-Id": "goal5-enable-correlation",
            "X-Operator-Intent": (
                "control_futures_fill_triggered_follow_up"
            ),
        },
        json={
            "action": "ENABLE",
            "expected_revision": 0,
            "authorize_one_preview_create_and_safe_closeout": True,
            "acknowledge_unknown_outcome_consumes_allowance": True,
            "acknowledge_child_terms_are_backend_derived": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["control_state"] == "ENABLED"
    assert len(service.control_calls) == 1
    call = service.control_calls[0]
    assert call["source_client_order_id"] == SOURCE_ID
    assert (
        call["authorize_one_preview_create_and_safe_closeout"] is True
    )
    assert (
        call["context"].operator_intent
        == "control_futures_fill_triggered_follow_up"
    )


def test_viewer_reads_but_has_no_control_actions(monkeypatch) -> None:
    client, _ = _client(monkeypatch, viewer=True)

    read = client.get(
        f"/api/v1/futures/order-operations/{SOURCE_ID}/"
        "follow-up-intent/fill-triggered-activation"
    )
    write = client.post(
        f"/api/v1/futures/order-operations/{SOURCE_ID}/"
        "follow-up-intent/fill-triggered-activation",
        headers={
            "Idempotency-Key": "viewer-goal5",
            "X-Correlation-Id": "viewer-goal5",
            "X-Operator-Intent": (
                "control_futures_fill_triggered_follow_up"
            ),
        },
        json={
            "action": "ENABLE",
            "expected_revision": 0,
            "authorize_one_preview_create_and_safe_closeout": True,
            "acknowledge_unknown_outcome_consumes_allowance": True,
            "acknowledge_child_terms_are_backend_derived": True,
        },
    )

    assert read.status_code == 200
    assert read.json()["allowed_actions"] == []
    assert write.status_code == 403


def test_enable_requires_cancel_permission_for_conditional_closeout(
    monkeypatch,
) -> None:
    monkeypatch.setitem(
        ROLE_PERMISSIONS,
        AdminApiRole.OPERATOR,
        frozenset(
            {
                AdminApiPermission.ANALYTICS_READ,
                AdminApiPermission.ORDER_CREATE,
            }
        ),
    )
    client, _ = _client(
        monkeypatch,
        roles=[AdminApiRole.OPERATOR],
    )

    read = client.get(
        f"/api/v1/futures/order-operations/{SOURCE_ID}/"
        "follow-up-intent/fill-triggered-activation"
    )
    write = client.post(
        f"/api/v1/futures/order-operations/{SOURCE_ID}/"
        "follow-up-intent/fill-triggered-activation",
        headers={
            "Idempotency-Key": "goal5-missing-cancel",
            "X-Correlation-Id": "goal5-missing-cancel",
            "X-Operator-Intent": (
                "control_futures_fill_triggered_follow_up"
            ),
        },
        json={
            "action": "ENABLE",
            "expected_revision": 0,
            "authorize_one_preview_create_and_safe_closeout": True,
            "acknowledge_unknown_outcome_consumes_allowance": True,
            "acknowledge_child_terms_are_backend_derived": True,
        },
    )

    assert read.status_code == 200
    assert read.json()["allowed_actions"] == ["DRAIN"]
    assert write.status_code == 403
    assert write.json()["detail"] == (
        "Missing required permission: order:cancel"
    )
