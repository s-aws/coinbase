from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.routes import operator_single_order_reprice_now as routes
from application.admin_api.operator_single_order_reprice_now_models import (
    OperatorSingleOrderRepriceNowReadback,
    OperatorSingleOrderRepriceNowSourceSelection,
)
from application.admin_api.operator_single_order_reprice_now_policy import (
    build_single_order_reprice_now_intent,
)


STEALTH_ID = "11111111-1111-4111-8111-111111111111"
SOURCE_ID = "22222222-2222-4222-8222-222222222222"
SOURCE_EVIDENCE = "b" * 64


def _selection() -> OperatorSingleOrderRepriceNowSourceSelection:
    return OperatorSingleOrderRepriceNowSourceSelection(
        stealth_order_id=STEALTH_ID,
        source_client_order_id=SOURCE_ID,
        found=True,
        eligible=True,
        diagnostic_code="operator_reprice_now_source_eligible",
        definition_revision=7,
        definition_sha256="a" * 64,
        root_client_order_id=STEALTH_ID,
        source_status="REVEALED",
        zero_fill_proven=True,
        system_owned=True,
        direct_parent=True,
        source_evidence_sha256=SOURCE_EVIDENCE,
    )


def _readback(
    *,
    prepared: bool,
    allow_prepare: bool = False,
) -> OperatorSingleOrderRepriceNowReadback:
    selection = _selection()
    if not prepared:
        return OperatorSingleOrderRepriceNowReadback(
            state="UNCONSUMED",
            diagnostic_code="operator_reprice_now_source_eligible",
            stealth_order_id=STEALTH_ID,
            source_client_order_id=SOURCE_ID,
            source_client_order_id_sha256=hashlib.sha256(
                SOURCE_ID.encode()
            ).hexdigest(),
            source_selection=selection,
            allowed_actions=(
                ["PREPARE_REPRICE_NOW"] if allow_prepare else []
            ),
            local_cycles_used=0,
            execution_authority_enabled=False,
            command_service_method="get_single_order_reprice_now",
        )
    built = build_single_order_reprice_now_intent(
        source=selection.model_dump(mode="json")
    )
    intent = built.to_persisted_payload()
    successor = built.reserved_successor_client_order_id
    return OperatorSingleOrderRepriceNowReadback(
        state="INTENT_PREPARED",
        diagnostic_code="operator_reprice_now_intent_prepared",
        stealth_order_id=STEALTH_ID,
        source_client_order_id=SOURCE_ID,
        source_client_order_id_sha256=hashlib.sha256(
            SOURCE_ID.encode()
        ).hexdigest(),
        reserved_successor_client_order_id=successor,
        reserved_successor_client_order_id_sha256=hashlib.sha256(
            successor.encode()
        ).hexdigest(),
        source_selection=selection,
        intent=intent,
        intent_sha256=built.intent_sha256,
        events=[
            {
                "event_id": (
                    "33333333-3333-4333-8333-333333333333"
                ),
                "event_type": "REPRICE_NOW_INTENT_PREPARED",
                "cycle_number": 1,
                "diagnostic_code": (
                    "operator_reprice_now_intent_prepared"
                ),
                "correlation_id": "goal15-correlation",
                "evidence_sha256": "c" * 64,
                "recorded_at": "2026-07-27T00:00:00Z",
            }
        ],
        local_cycles_used=1,
        latest_cycle_idempotency_key_sha256="d" * 64,
        latest_cycle_payload_sha256="e" * 64,
        latest_cycle_actor_id_sha256="f" * 64,
        latest_cycle_evidence_sha256="1" * 64,
        execution_authority_enabled=False,
        correlation_id="goal15-correlation",
        operator_intent="prepare_single_order_reprice_now",
        command_service_method="prepare_reprice_now_intent",
    )


@dataclass
class _Service:
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def get_single_order_reprice_now(
        self,
        **kwargs: Any,
    ) -> OperatorSingleOrderRepriceNowReadback:
        self.calls.append(("get", kwargs))
        return _readback(
            prepared=False,
            allow_prepare=kwargs["allow_prepare"],
        )

    def prepare_reprice_now_intent(
        self,
        **kwargs: Any,
    ) -> OperatorSingleOrderRepriceNowReadback:
        self.calls.append(("prepare", kwargs))
        return _readback(prepared=True)


def _app(service: _Service) -> FastAPI:
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    app.dependency_overrides[
        routes.get_operator_single_order_reprice_now_service
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
        "X-Correlation-Id": "goal15-correlation",
        "Idempotency-Key": "goal15-idempotency",
        "X-Operator-Intent": intent,
    }


def _enable(monkeypatch) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_AUTH_MODE", "bootstrap_bearer")
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_BEARER_TOKEN",
        "local-admin-token",
    )
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_SINGLE_ORDER_REPRICE_NOW_ENABLED",
        "1",
    )


def _base() -> str:
    return (
        f"/api/v1/movement-repricing/stealth/{STEALTH_ID}"
        f"/placements/{SOURCE_ID}"
    )


def test_get_and_prepare_are_call_free_rbac_bound_operator_actions(
    monkeypatch,
) -> None:
    _enable(monkeypatch)
    service = _Service()
    client = TestClient(_app(service))

    read = client.get(
        f"{_base()}/reprice-now",
        headers=_headers("read_single_order_reprice_now"),
    )
    prepare = client.post(
        f"{_base()}/reprice-now-intents",
        headers=_headers("prepare_single_order_reprice_now"),
        json={
            "expected_definition_revision": 7,
            "expected_definition_sha256": "a" * 64,
            "expected_source_evidence_sha256": SOURCE_EVIDENCE,
            "operator_reason": "Operator reviewed this exact placement.",
            "confirm_prepare_reprice_now_intent": True,
        },
    )

    assert read.status_code == 200
    assert read.json()["allowed_actions"] == ["PREPARE_REPRICE_NOW"]
    assert read.json()["page_load_coinbase_calls"] == 0
    assert prepare.status_code == 200
    assert prepare.json()["market_terms_bound"] is False
    assert prepare.json()["source_cancel_call_count"] == 0
    assert prepare.json()["replacement_create_call_count"] == 0
    assert [name for name, _ in service.calls] == ["get", "prepare"]
    assert service.calls[1][1]["context"].operator_intent == (
        "prepare_single_order_reprice_now"
    )


def test_execute_fails_before_service_ledger_or_runtime(monkeypatch) -> None:
    _enable(monkeypatch)
    service = _Service()
    client = TestClient(_app(service))

    response = client.post(
        f"{_base()}/execute-reprice-now",
        headers=_headers("execute_single_order_reprice_now"),
        json={
            "expected_intent_sha256": "a" * 64,
            "confirm_execute_reprice_now": True,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "operator_reprice_now_live_authority_terms_incomplete"
    )
    assert service.calls == []


def test_prepare_requires_both_cancel_and_create_permissions(
    monkeypatch,
) -> None:
    _enable(monkeypatch)
    service = _Service()
    client = TestClient(_app(service))

    response = client.post(
        f"{_base()}/reprice-now-intents",
        headers=_headers(
            "prepare_single_order_reprice_now",
            roles="viewer",
        ),
        json={
            "expected_definition_revision": 7,
            "expected_definition_sha256": "a" * 64,
            "expected_source_evidence_sha256": SOURCE_EVIDENCE,
            "operator_reason": "Operator reviewed this exact placement.",
            "confirm_prepare_reprice_now_intent": True,
        },
    )

    assert response.status_code == 403
    assert service.calls == []


def test_browser_cannot_supply_market_or_cap_terms(monkeypatch) -> None:
    _enable(monkeypatch)
    service = _Service()
    client = TestClient(_app(service))

    response = client.post(
        f"{_base()}/reprice-now-intents",
        headers=_headers("prepare_single_order_reprice_now"),
        json={
            "expected_definition_revision": 7,
            "expected_definition_sha256": "a" * 64,
            "expected_source_evidence_sha256": SOURCE_EVIDENCE,
            "operator_reason": "Operator reviewed this exact placement.",
            "confirm_prepare_reprice_now_intent": True,
            "limit_price": "50000",
        },
    )

    assert response.status_code == 422
    assert service.calls == []


def test_goal15_route_has_no_global_execution_authority_dependency() -> None:
    source = Path(routes.__file__).read_text(encoding="utf-8")

    assert "coinbase_execution_authority_enabled" not in source
    assert "execution_authority_checker" not in source
