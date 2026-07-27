from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from api.v1.routes import operator_parent_move_premark as routes
from application.admin_api.operator_parent_move_premark_models import (
    OperatorParentMovePlan,
    OperatorParentMovePremarkReadback,
    OperatorParentMoveSourceSelection,
)


SOURCE_ID = "11111111-1111-4111-8111-111111111111"


def _readback(
    *,
    allowed_actions: list[str] | None = None,
    state: str = "UNCONSUMED",
) -> OperatorParentMovePremarkReadback:
    successor_id = "22222222-2222-4222-8222-222222222222"
    plan_payload = {
        "goal_id": "operator_parent_move_premark_lifecycle_v1",
        "policy_revision": "PARENT_MOVE_PREMARK_V1",
        "source_client_order_id": SOURCE_ID,
        "reserved_successor_client_order_id": successor_id,
        "portfolio_scope_sha256": "b" * 64,
        "product_id": "BTC-USDC",
        "side": "BUY",
        "base_size": "0.00001",
        "source_limit_price": "50000",
        "requested_limit_price": "50000.127",
        "replacement_limit_price": "50000.12",
        "price_increment": "0.01",
        "base_increment": "0.00000001",
        "base_min_size": "0.00000001",
        "quote_min_size": "0.01",
        "source_status": "OPEN",
        "source_filled_size": "0",
        "source_order_type": "LIMIT",
        "source_time_in_force": "GOOD_UNTIL_CANCELLED",
        "source_ownership_provenance": "ADMIN_MANUAL_ROOT",
        "post_only": True,
        "submitted_notional": "0.5000012",
        "possible_execution_notional": "0.5000012",
        "submitted_notional_cap": "3.10",
        "possible_execution_notional_cap": "1.00",
        "zero_fill_proven": True,
        "system_owned": True,
        "source_evidence_sha256": "c" * 64,
    }
    plan = (
        OperatorParentMovePlan.model_validate(plan_payload)
        if state != "UNCONSUMED"
        else None
    )
    plan_sha256 = (
        hashlib.sha256(
            json.dumps(
                plan_payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        if plan is not None
        else None
    )
    return OperatorParentMovePremarkReadback(
        state=state,
        diagnostic_code=(
            "operator_parent_move_source_eligible"
            if state == "UNCONSUMED"
            else "operator_parent_move_plan_ready"
        ),
        source_client_order_id=SOURCE_ID,
        source_client_order_id_sha256=hashlib.sha256(
            SOURCE_ID.encode()
        ).hexdigest(),
        reserved_successor_client_order_id=(
            successor_id if plan is not None else None
        ),
        reserved_successor_client_order_id_sha256=(
            hashlib.sha256(successor_id.encode()).hexdigest()
            if plan is not None
            else None
        ),
        source_selection=OperatorParentMoveSourceSelection(
            client_order_id=SOURCE_ID,
            found=True,
            eligible=True,
            diagnostic_code="operator_parent_move_source_eligible",
            product_id="BTC-USDC",
            side="BUY",
            status="OPEN",
            order_type="LIMIT",
            time_in_force="GOOD_UNTIL_CANCELLED",
            size="0.00001",
            limit_price="50000",
            filled_size="0",
            ownership_provenance="ADMIN_MANUAL_ROOT",
            authoritatively_nonterminal=True,
            cancel_eligible=True,
            zero_fill_proven=True,
            system_owned=True,
            direct_root=True,
            post_only_compatible=True,
            legacy_pending_move=False,
            portfolio_scope_sha256="b" * 64,
            source_evidence_sha256="c" * 64,
        ),
        plan=plan,
        plan_sha256=plan_sha256,
        allowed_actions=allowed_actions or [],
        planning_terms_complete=True,
        execution_authority_enabled=True,
        cycle_count=1 if plan is not None else 0,
        latest_cycle_number=1 if plan is not None else None,
        latest_cycle_phase="PLAN" if plan is not None else None,
        latest_cycle_status="COMPLETED" if plan is not None else None,
        latest_cycle_correlation_id=(
            "goal14-correlation" if plan is not None else None
        ),
        latest_cycle_actor_id_sha256=(
            "d" * 64 if plan is not None else None
        ),
        latest_cycle_idempotency_key_sha256=(
            "e" * 64 if plan is not None else None
        ),
        latest_cycle_payload_sha256=(
            "f" * 64 if plan is not None else None
        ),
        latest_cycle_evidence_sha256=(
            "1" * 64 if plan is not None else None
        ),
        correlation_id=(
            "goal14-correlation" if plan is not None else None
        ),
    )


@dataclass
class _ApiService:
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def readback(
        self,
        source_client_order_id: str,
        *,
        allow_premark: bool,
    ) -> OperatorParentMovePremarkReadback:
        self.calls.append(
            (
                "get",
                {
                    "source_client_order_id": source_client_order_id,
                    "allow_premark": allow_premark,
                },
            )
        )
        return _readback(
            allowed_actions=["PREMARK"] if allow_premark else []
        )

    def premark(self, **kwargs: Any) -> OperatorParentMovePremarkReadback:
        self.calls.append(("premark", kwargs))
        return _readback(state="PLANNED")


def _app(service: _ApiService) -> FastAPI:
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    app.dependency_overrides[
        routes.get_operator_parent_move_premark_api_service
    ] = lambda: service
    return app


def _headers(
    intent: str,
    *,
    roles: str = "admin,trader",
) -> dict[str, str]:
    return {
        "Authorization": "Bearer local-admin-token",
        "X-Admin-Actor": "operator",
        "X-Admin-Roles": roles,
        "X-Correlation-Id": "goal14-correlation",
        "Idempotency-Key": "goal14-idempotency",
        "X-Operator-Intent": intent,
    }


def _enable(monkeypatch) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_AUTH_MODE", "bootstrap_bearer")
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_BEARER_TOKEN",
        "local-admin-token",
    )
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_PARENT_MOVE_PREMARK_ENABLED",
        "1",
    )


def test_call_free_get_and_local_premark_bind_rbac_intent_and_context(
    monkeypatch,
) -> None:
    _enable(monkeypatch)
    service = _ApiService()
    client = TestClient(_app(service))

    read = client.get(
        (
            f"/api/v1/movement-repricing/orders/{SOURCE_ID}"
            "/parent-move"
        ),
        headers=_headers("read_parent_move"),
    )
    premark = client.post(
        (
            f"/api/v1/movement-repricing/orders/{SOURCE_ID}"
            "/parent-move-plans"
        ),
        headers=_headers("premark_parent_move"),
        json={
            "requested_limit_price": "50000.127",
            "operator_reason": "Review this exact local parent move plan.",
            "confirm_premark": True,
        },
    )

    assert read.status_code == 200
    assert read.json()["allowed_actions"] == ["PREMARK"]
    assert read.json()["page_load_coinbase_calls"] == 0
    assert read.json()["raw_response_persisted"] is False
    assert read.json()["raw_exception_persisted"] is False
    assert read.json()["private_identifiers_included"] is False
    assert premark.status_code == 200
    assert [name for name, _ in service.calls] == ["get", "premark"]
    context = service.calls[1][1]["context"]
    request = service.calls[1][1]["request"]
    assert context.operator_intent == "premark_parent_move"
    assert context.idempotency_key == "goal14-idempotency"
    assert context.correlation_id == "goal14-correlation"
    assert request.source_client_order_id == SOURCE_ID
    assert request.requested_limit_price == "50000.127"
    assert request.confirm_premark is True


def test_viewer_readback_never_advertises_premark(monkeypatch) -> None:
    _enable(monkeypatch)
    service = _ApiService()
    client = TestClient(_app(service))

    response = client.get(
        (
            f"/api/v1/movement-repricing/orders/{SOURCE_ID}"
            "/parent-move"
        ),
        headers=_headers("read_parent_move", roles="viewer"),
    )

    assert response.status_code == 200
    assert response.json()["allowed_actions"] == []
    assert service.calls[0][1]["allow_premark"] is False


def test_live_routes_fail_before_service_ledger_or_runtime(monkeypatch) -> None:
    _enable(monkeypatch)
    service = _ApiService()
    client = TestClient(_app(service))
    body = {
        "expected_plan_sha256": "d" * 64,
        "confirmation_sha256": "e" * 64,
        "confirm_cancel_then_replace": True,
    }

    execute = client.post(
        (
            f"/api/v1/movement-repricing/orders/{SOURCE_ID}"
            "/execute-parent-move"
        ),
        headers=_headers("execute_parent_move"),
        json=body,
    )
    closeout = client.post(
        (
            f"/api/v1/movement-repricing/orders/{SOURCE_ID}"
            "/parent-move-safe-closeout"
        ),
        headers=_headers("safe_closeout_parent_move_successor"),
        json={
            "expected_plan_sha256": "d" * 64,
            "confirmation_sha256": "e" * 64,
            "confirm_exact_successor_cancel": True,
        },
    )

    assert execute.status_code == 409
    assert execute.json()["detail"] == (
        "operator_parent_move_live_authority_terms_incomplete"
    )
    assert closeout.status_code == 409
    assert closeout.json()["detail"] == (
        "operator_parent_move_live_authority_terms_incomplete"
    )
    assert service.calls == []


def test_premark_requires_cancel_and_create_permissions(monkeypatch) -> None:
    _enable(monkeypatch)
    service = _ApiService()
    client = TestClient(_app(service))

    response = client.post(
        (
            f"/api/v1/movement-repricing/orders/{SOURCE_ID}"
            "/parent-move-plans"
        ),
        headers=_headers("premark_parent_move", roles="viewer"),
        json={
            "requested_limit_price": "50000.127",
            "operator_reason": "Review this exact local parent move plan.",
            "confirm_premark": True,
        },
    )

    assert response.status_code == 403
    assert service.calls == []


@pytest.mark.parametrize(
    ("update", "code"),
    [
        (
            {"allowed_actions": ["EXECUTE_PARENT_MOVE"]},
            "operator_parent_move_live_action_not_authorized",
        ),
        (
            {"source_client_order_id_sha256": "0" * 64},
            "operator_parent_move_source_hash_invalid",
        ),
        (
            {"source_cancel_allowance_consumed": True},
            "operator_parent_move_call_accounting_invalid",
        ),
    ],
)
def test_readback_model_rejects_untrusted_authority_combinations(
    update: dict[str, Any],
    code: str,
) -> None:
    payload = _readback(allowed_actions=["PREMARK"]).model_dump(
        mode="json"
    )
    payload.update(update)

    with pytest.raises(ValidationError, match=code):
        OperatorParentMovePremarkReadback.model_validate(payload)


def test_readback_model_binds_plan_successor_and_hash() -> None:
    payload = _readback(state="PLANNED").model_dump(mode="json")
    payload["reserved_successor_client_order_id_sha256"] = "0" * 64

    with pytest.raises(
        ValidationError,
        match="operator_parent_move_plan_readback_invalid",
    ):
        OperatorParentMovePremarkReadback.model_validate(payload)


@pytest.mark.parametrize(
    "update",
    [
        {
            "state": "REPLACEMENT_CREATED",
            "latest_cycle_phase": "EXECUTE",
        },
        {
            "state": "SUCCESSOR_CLOSED",
            "source_cancel_allowance_consumed": True,
            "source_cancel_call_count": 1,
            "replacement_create_allowance_consumed": True,
            "replacement_create_call_count": 1,
            "successor_closeout_cancel_allowance_consumed": True,
            "successor_closeout_cancel_call_count": 1,
            "latest_cycle_phase": "PLAN",
        },
    ],
)
def test_readback_model_rejects_impossible_lifecycle_evidence(
    update: dict[str, Any],
) -> None:
    payload = _readback(state="PLANNED").model_dump(mode="json")
    payload.update(update)

    with pytest.raises(
        ValidationError,
        match="operator_parent_move_lifecycle_evidence_invalid",
    ):
        OperatorParentMovePremarkReadback.model_validate(payload)
