"""Call-free route contracts for operator fill-triggered activation controls."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from api.v1.app import create_app
from api.v1.routes import orders as order_routes
from application.admin_api.operator_fill_triggered_follow_up_activation import (
    FILL_TRIGGERED_FOLLOW_UP_GOAL_ID,
    FillTriggeredActivationControlState,
    FillTriggeredActivationRecord,
    FillTriggeredActivationTriggerState,
)


pytestmark = [pytest.mark.regression, pytest.mark.serial]

SOURCE_ID = "d24c9fc3-29c2-4e76-87d7-3d27cb94530f"
INTENT_ID = "0ec90842-d875-4a7b-9eb1-333c7d618bb1"
AUDIT_ID = "1f418e77-9e5e-49f3-861e-a30f942f38fb"


def _record() -> FillTriggeredActivationRecord:
    return FillTriggeredActivationRecord(
        goal_id=FILL_TRIGGERED_FOLLOW_UP_GOAL_ID,
        source_client_order_id=SOURCE_ID,
        follow_up_intent_id=INTENT_ID,
        control_state=FillTriggeredActivationControlState.DISABLED,
        trigger_state=FillTriggeredActivationTriggerState.UNCLAIMED,
        revision=0,
        delegated_create_authority=False,
        trigger_claim_id=None,
        trigger_evidence_sha256=None,
        materialization_state=None,
        child_client_order_id=None,
        diagnostic_code="fill_triggered_follow_up_disabled",
        actor_id="private-operator",
        roles=("admin", "trader"),
        correlation_id="attach-correlation",
        audit_id=AUDIT_ID,
        recorded_at="2026-07-24T00:00:00+00:00",
        updated_at="2026-07-24T00:00:00+00:00",
    )


class _Service:
    def __init__(self) -> None:
        self.record = _record()
        self.control_calls: list[dict] = []

    def read(self, **_kwargs):
        return self.record

    def control(self, **kwargs):
        self.control_calls.append(kwargs)
        self.record = replace(
            self.record,
            control_state=FillTriggeredActivationControlState.ENABLED,
            revision=1,
            actor_id=kwargs["context"].actor_id,
            roles=kwargs["context"].roles,
            correlation_id=kwargs["context"].correlation_id,
            diagnostic_code="fill_triggered_follow_up_enabled",
        )
        return self.record


def _headers(*, mutating: bool = False) -> dict[str, str]:
    headers = {
        "Authorization": "Bearer local-admin-token",
        "X-Admin-Actor": "operator-goal8",
        "X-Admin-Roles": "admin,trader",
    }
    if mutating:
        headers.update(
            {
                "Idempotency-Key": "goal8-enable-001",
                "X-Correlation-Id": (
                    "b80fe761-69e6-462b-9ccb-b40ed93b2ac7"
                ),
                "X-Operator-Intent": "control_fill_triggered_follow_up",
            }
        )
    return headers


def test_activation_read_is_local_and_withholds_actor_identity(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_FOLLOW_UP_INTENT_ENABLED",
        "1",
    )
    monkeypatch.setenv("COINBASE_ADMIN_API_AUTH_MODE", "bootstrap_bearer")
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_BEARER_TOKEN",
        "local-admin-token",
    )
    service = _Service()
    app = create_app()
    app.dependency_overrides[
        order_routes.get_fill_triggered_follow_up_activation_service
    ] = lambda: service
    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/orders/{SOURCE_ID}/follow-up-intent/fill-triggered-activation",
            headers=_headers(),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["activation"]["control_state"] == "DISABLED"
    assert payload["read_only"] is True
    assert payload["live_coinbase_read_ran"] is False
    assert payload["live_coinbase_orders_ran"] is False
    assert "actor_id" not in response.text
    assert "roles" not in payload["activation"]


def test_enable_control_forwards_only_revision_action_and_operator_context(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_FOLLOW_UP_INTENT_ENABLED",
        "1",
    )
    monkeypatch.setenv("COINBASE_ADMIN_API_AUTH_MODE", "bootstrap_bearer")
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_BEARER_TOKEN",
        "local-admin-token",
    )
    service = _Service()
    app = create_app()
    app.dependency_overrides[
        order_routes.get_fill_triggered_follow_up_activation_service
    ] = lambda: service
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/orders/{SOURCE_ID}/follow-up-intent/fill-triggered-activation",
            headers=_headers(mutating=True),
            json={
                "action": "ENABLE",
                "expected_revision": 0,
                "confirm_control_action": True,
                "authorize_single_fill_triggered_materialization": True,
                "acknowledge_unknown_outcome_consumes_create_allowance": True,
                "acknowledge_child_terms_are_backend_derived": True,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "accepted"
    assert payload["activation"]["control_state"] == "ENABLED"
    assert payload["live_coinbase_read_ran"] is False
    assert payload["live_coinbase_orders_ran"] is False
    assert len(service.control_calls) == 1
    call = service.control_calls[0]
    assert call["source_client_order_id"] == SOURCE_ID
    assert call["expected_revision"] == 0
    assert call["authorize_single_fill_triggered_materialization"] is True
    assert (
        call["acknowledge_unknown_outcome_consumes_create_allowance"] is True
    )
    assert call["acknowledge_child_terms_are_backend_derived"] is True
    assert call["context"].operator_intent == (
        "control_fill_triggered_follow_up"
    )


def test_fill_triggered_exact_child_safe_closeout_is_a_distinct_route() -> None:
    schema = create_app().openapi()
    path = (
        "/api/v1/orders/{source_client_order_id}/follow-up-intent/"
        "fill-triggered-activation/safe-closeout"
    )

    assert "post" in schema["paths"][path]
    header = next(
        parameter
        for parameter in schema["paths"][path]["post"]["parameters"]
        if parameter["name"] == "X-Operator-Intent"
    )
    assert header["schema"]["const"] == (
        "safe_closeout_fill_triggered_follow_up"
    )
