from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi.testclient import TestClient

from api.v1.app import app as _APP
from api.v1.routes import operator_revealed_order_movement as routes
from application.admin_api.operator_revealed_order_movement_service import (
    OperatorRevealedOrderMovePlan,
    OperatorRevealedOrderMovementResponse,
)


STEALTH_ID = "11111111-1111-4111-8111-111111111111"


def _plan() -> OperatorRevealedOrderMovePlan:
    return OperatorRevealedOrderMovePlan(
        stealth_order_id=STEALTH_ID,
        definition_revision=4,
        definition_sha256="a" * 64,
        portfolio_scope_sha256="b" * 64,
        source_client_order_id="22222222-2222-4222-8222-222222222222",
        source_exchange_order_id_sha256="c" * 64,
        replacement_client_order_id=(
            "33333333-3333-4333-8333-333333333333"
        ),
        root_client_order_id=STEALTH_ID,
        product_id="BTC-USDC",
        side="BUY",
        base_size="0.00001",
        old_limit_price="50000",
        requested_limit_price="50000.127",
        replacement_limit_price="50000.12",
        price_increment="0.01",
        target_movement="0.01",
        target_movement_type="P",
        post_only=True,
        submitted_notional_usdc="0.5000012",
        possible_execution_notional_usdc="0.5000012",
        profitability_validated=True,
        zero_fill_validated=True,
        plan_sha256="d" * 64,
    )


def _response(state: str) -> OperatorRevealedOrderMovementResponse:
    plan = _plan() if state != "UNCONSUMED" else None
    return OperatorRevealedOrderMovementResponse(
        state=state,
        stealth_order_id=STEALTH_ID,
        plan=plan,
        plan_sha256=plan.plan_sha256 if plan else None,
        source_client_order_id=(
            plan.source_client_order_id if plan else None
        ),
        replacement_client_order_id=(
            plan.replacement_client_order_id if plan else None
        ),
        source_exchange_order_id_sha256=(
            plan.source_exchange_order_id_sha256 if plan else None
        ),
        replacement_exchange_order_id_sha256=None,
        cancel_allowance_consumed=state == "REPLACED",
        create_allowance_consumed=state == "REPLACED",
        cancel_call_count=1 if state == "REPLACED" else 0,
        create_call_count=1 if state == "REPLACED" else 0,
        read_call_count=4 if state == "REPLACED" else 0,
        diagnostic_code=f"operator_move_{state.lower()}",
        operator_intent=(
            "prepare_revealed_order_move"
            if state == "UNCONSUMED"
            else "execute_revealed_order_cancel_then_replace"
        ),
        command_service_method=(
            "get_execution"
            if state == "UNCONSUMED"
            else (
                "prepare_plan"
                if state == "PLANNED"
                else "execute_move"
            )
        ),
        correlation_id="goal7-correlation",
        plan_idempotency_key_sha256=None,
        execute_idempotency_key_sha256=None,
        command_cycle_status=(
            "COMPLETED" if state != "UNCONSUMED" else None
        ),
        command_cycle_phase=("PLAN" if state == "PLANNED" else None),
        command_cycle_number=(1 if state != "UNCONSUMED" else None),
        command_cycle_correlation_id=(
            "goal7-correlation" if state != "UNCONSUMED" else None
        ),
        command_cycle_evidence_sha256=(
            "e" * 64 if state != "UNCONSUMED" else None
        ),
        execution_authority_enabled=True,
        allowed_actions=(
            ["PREPARE_PLAN"]
            if state == "UNCONSUMED"
            else ["EXECUTE_MOVE"]
            if state == "PLANNED"
            else []
        ),
    )


@dataclass
class _Service:
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def get_execution(self, stealth_order_id: str, **kwargs: Any):
        self.calls.append(
            ("get", {"stealth_order_id": stealth_order_id, **kwargs})
        )
        return _response("UNCONSUMED")

    def prepare_plan(self, **kwargs: Any):
        self.calls.append(("prepare", kwargs))
        return _response("PLANNED")

    def execute_move(self, **kwargs: Any):
        self.calls.append(("execute", kwargs))
        return _response("REPLACED")


def _headers(intent: str, *, roles: str = "admin,trader") -> dict[str, str]:
    return {
        "Authorization": "Bearer local-admin-token",
        "X-Admin-Actor": "operator",
        "X-Admin-Roles": roles,
        "X-Correlation-Id": "goal7-correlation",
        "Idempotency-Key": "goal7-idempotency",
        "X-Operator-Intent": intent,
    }


def test_routes_bind_review_plan_execute_rbac_and_intent(monkeypatch) -> None:
    service = _Service()
    monkeypatch.setenv("COINBASE_ADMIN_API_AUTH_MODE", "bootstrap_bearer")
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_BEARER_TOKEN",
        "local-admin-token",
    )
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_REVEALED_ORDER_MOVEMENT_ENABLED",
        "1",
    )
    _APP.dependency_overrides[
        routes.get_operator_revealed_order_movement_service
    ] = lambda: service
    _APP.dependency_overrides[
        routes.get_operator_revealed_order_movement_read_service
    ] = lambda: service
    client = TestClient(_APP)
    try:
        read = client.get(
            (
                f"/api/v1/movement-repricing/stealth/{STEALTH_ID}"
                "/move-execution"
            ),
            headers=_headers("read"),
        )
        prepare = client.post(
            (
                f"/api/v1/movement-repricing/stealth/{STEALTH_ID}"
                "/move-plans"
            ),
            headers=_headers("prepare_revealed_order_move"),
            json={
                "expected_definition_revision": 4,
                "expected_definition_sha256": "a" * 64,
                "requested_limit_price": "50000.127",
                "operator_reason": "review this exact movement plan",
                "confirm_operator_move_plan": True,
            },
        )
        execute = client.post(
            (
                f"/api/v1/movement-repricing/stealth/{STEALTH_ID}"
                "/execute-move"
            ),
            headers=_headers(
                "execute_revealed_order_cancel_then_replace"
            ),
            json={
                "expected_plan_sha256": "d" * 64,
                "operator_reason": "execute exact cancel and replacement",
                "confirm_operator_cancel_then_replace": True,
            },
        )
    finally:
        _APP.dependency_overrides.clear()

    assert read.status_code == 200
    assert prepare.status_code == 200
    assert execute.status_code == 200
    assert [name for name, _ in service.calls] == [
        "get",
        "prepare",
        "execute",
    ]
    assert (
        service.calls[1][1]["body"].requested_limit_price
        == "50000.127"
    )
    assert service.calls[1][1]["operator_intent"] == (
        "prepare_revealed_order_move"
    )
    assert (
        service.calls[2][1]["body"].expected_plan_sha256 == "d" * 64
    )
    assert service.calls[2][1]["operator_intent"] == (
        "execute_revealed_order_cancel_then_replace"
    )


def test_execute_requires_trader_or_admin_permissions(monkeypatch) -> None:
    service = _Service()
    monkeypatch.setenv("COINBASE_ADMIN_API_AUTH_MODE", "bootstrap_bearer")
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_BEARER_TOKEN",
        "local-admin-token",
    )
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_REVEALED_ORDER_MOVEMENT_ENABLED",
        "1",
    )
    _APP.dependency_overrides[
        routes.get_operator_revealed_order_movement_service
    ] = lambda: service
    client = TestClient(_APP)
    try:
        response = client.post(
            (
                f"/api/v1/movement-repricing/stealth/{STEALTH_ID}"
                "/execute-move"
            ),
            headers=_headers(
                "execute_revealed_order_cancel_then_replace",
                roles="viewer",
            ),
            json={
                "expected_plan_sha256": "d" * 64,
                "operator_reason": "execute exact cancel and replacement",
                "confirm_operator_cancel_then_replace": True,
            },
        )
    finally:
        _APP.dependency_overrides.clear()

    assert response.status_code == 403
    assert service.calls == []
