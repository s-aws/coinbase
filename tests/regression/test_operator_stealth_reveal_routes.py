from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi.testclient import TestClient

from api.v1.app import app as _APP
from api.v1.routes import operator_stealth_reveal as routes
from application.admin_api.operator_stealth_reveal_service import (
    OperatorStealthRevealExecutionResponse,
)


DEFINITION_ID = "11111111-1111-4111-8111-111111111111"


def _response(state: str = "UNCONSUMED"):
    return OperatorStealthRevealExecutionResponse(
        goal_id="operator_stealth_reveal_and_exact_closeout_v1",
        state=state,
        definition_id=DEFINITION_ID,
        definition_revision=2,
        definition_sha256="b" * 64,
        portfolio_scope_sha256="a" * 64,
        client_order_id=DEFINITION_ID,
        product_id="BTC-USDC",
        side="BUY",
        plan=None,
        plan_sha256=None,
        preview_allowance_consumed=state != "UNCONSUMED",
        create_allowance_consumed=state == "REVEALED",
        cancel_allowance_consumed=state == "CANCELLED",
        preview_call_count=0 if state == "UNCONSUMED" else 1,
        create_call_count=1 if state in {"REVEALED", "CANCELLED"} else 0,
        cancel_call_count=1 if state == "CANCELLED" else 0,
        read_call_count=0,
        preview_outcome=(
            "ACCEPTED" if state in {"REVEALED", "CANCELLED"} else None
        ),
        create_outcome=(
            "ACCEPTED" if state in {"REVEALED", "CANCELLED"} else None
        ),
        cancel_outcome="CANCELLED" if state == "CANCELLED" else None,
        exchange_order_id_sha256=None,
        diagnostic_code=f"operator_stealth_{state.lower()}",
        correlation_id="goal6-correlation",
        command_idempotency_key_sha256=None,
        command_identity_bound=False,
        execution_authority_enabled=True,
        allowed_actions=(
            ["REVEAL"]
            if state == "UNCONSUMED"
            else ["CLOSEOUT"]
            if state == "REVEALED"
            else []
        ),
    )


@dataclass
class _Service:
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def get_execution(self, definition_id: str, **kwargs: Any):
        self.calls.append(
            ("get", {"definition_id": definition_id, **kwargs})
        )
        return _response()

    def reveal(self, **kwargs: Any):
        self.calls.append(("reveal", kwargs))
        return _response("REVEALED")

    def closeout(self, **kwargs: Any):
        self.calls.append(("closeout", kwargs))
        return _response("CANCELLED")

    def resume_accepted_create(self, **kwargs: Any):
        self.calls.append(("resume", kwargs))
        return _response("REVEALED")


def _headers(
    permission: str,
    *,
    intent: str,
    roles: str = "admin,trader",
) -> dict[str, str]:
    _ = permission
    return {
        "Authorization": "Bearer local-admin-token",
        "X-Admin-Actor": "operator",
        "X-Admin-Roles": roles,
        "X-Correlation-Id": "goal6-correlation",
        "Idempotency-Key": "goal6-idempotency",
        "X-Operator-Intent": intent,
    }


def test_routed_review_reveal_and_closeout_bind_rbac_and_intent(
    monkeypatch,
) -> None:
    service = _Service()
    monkeypatch.setenv("COINBASE_ADMIN_API_AUTH_MODE", "bootstrap_bearer")
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_BEARER_TOKEN",
        "local-admin-token",
    )
    _APP.dependency_overrides[
        routes.get_operator_stealth_reveal_service
    ] = lambda: service
    _APP.dependency_overrides[
        routes.get_operator_stealth_reveal_read_service
    ] = lambda: service
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_STEALTH_REVEAL_ENABLED",
        "1",
    )
    client = TestClient(_APP)
    try:
        read = client.get(
            f"/api/v1/stealth/definitions/{DEFINITION_ID}/execution",
            headers=_headers("order:create", intent="read"),
        )
        reveal = client.post(
            f"/api/v1/stealth/definitions/{DEFINITION_ID}/reveal",
            headers=_headers(
                "order:create",
                intent="reveal_operator_stealth_definition",
            ),
            json={
                "expected_revision": 2,
                "expected_definition_sha256": "b" * 64,
                "operator_reason": "reveal this exact reviewed definition",
                "confirm_operator_stealth_reveal": True,
            },
        )
        resume = client.post(
            (
                f"/api/v1/stealth/definitions/{DEFINITION_ID}"
                "/resume-accepted-create"
            ),
            headers=_headers(
                "order:create",
                intent="resume_operator_stealth_accepted_create",
            ),
            json={
                "expected_plan_sha256": "c" * 64,
                "operator_reason": "resume this exact accepted preview",
                "confirm_operator_stealth_resume_create": True,
            },
        )
        closeout = client.post(
            f"/api/v1/stealth/definitions/{DEFINITION_ID}/closeout",
            headers=_headers(
                "order:cancel",
                intent="closeout_operator_stealth_placement",
            ),
            json={
                "expected_plan_sha256": "c" * 64,
                "operator_reason": "close this exact reviewed placement",
                "confirm_operator_stealth_closeout": True,
            },
        )
    finally:
        _APP.dependency_overrides.clear()

    assert read.status_code == 200
    assert reveal.status_code == 200
    assert resume.status_code == 200
    assert closeout.status_code == 200
    assert [name for name, _ in service.calls] == [
        "get",
        "reveal",
        "resume",
        "closeout",
    ]
    assert (
        service.calls[1][1]["body"].expected_definition_sha256
        == "b" * 64
    )
    assert service.calls[2][1]["body"].expected_plan_sha256 == "c" * 64
    assert service.calls[3][1]["body"].expected_plan_sha256 == "c" * 64


def test_reveal_requires_order_create_permission(monkeypatch) -> None:
    service = _Service()
    monkeypatch.setenv("COINBASE_ADMIN_API_AUTH_MODE", "bootstrap_bearer")
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_BEARER_TOKEN",
        "local-admin-token",
    )
    _APP.dependency_overrides[
        routes.get_operator_stealth_reveal_service
    ] = lambda: service
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_STEALTH_REVEAL_ENABLED",
        "1",
    )
    client = TestClient(_APP)
    try:
        response = client.post(
            f"/api/v1/stealth/definitions/{DEFINITION_ID}/reveal",
            headers=_headers(
                "config:update",
                intent="reveal_operator_stealth_definition",
                roles="viewer",
            ),
            json={
                "expected_revision": 2,
                "expected_definition_sha256": "b" * 64,
                "operator_reason": "reveal this exact reviewed definition",
                "confirm_operator_stealth_reveal": True,
            },
        )
    finally:
        _APP.dependency_overrides.clear()

    assert response.status_code == 403
    assert service.calls == []
