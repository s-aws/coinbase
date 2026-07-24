from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient
import pytest

from api.v1.app import create_app
from api.v1.routes.operator_hotpoint import (
    get_default_operator_hotpoint_control_services,
    router as hotpoint_router,
)
from application.admin_api.auth import get_authenticated_actor
from application.admin_api.models import AdminApiActor
from application.admin_api.operator_hotpoint_control import (
    HOTPOINT_GOAL_ID,
    FUTURES_HOTPOINT_SCOPE_POLICY,
    HotpointCancelState,
    HotpointCreateState,
    HotpointKillSwitchState,
    HotpointWindowState,
    OperatorHotpointControlRecord,
    SPOT_HOTPOINT_SCOPE_POLICY,
)
from application.admin_api.operator_hotpoint_runtime import (
    UnavailableFuturesHotpointControlService,
)
from core.enums import AdminApiRole


pytestmark = [pytest.mark.regression, pytest.mark.serial]


def test_hotpoint_operator_routes_are_registered_contract_surfaces() -> None:
    paths = {
        route.path: set(route.methods or ())
        for route in hotpoint_router.routes
    }

    assert paths == {
        "/hotpoint": {"GET"},
        "/hotpoint/eligible-parents": {"GET"},
        "/hotpoint/control": {"POST"},
        "/hotpoint/run-once": {"POST"},
        "/hotpoint/safe-closeout": {"POST"},
    }


def _record(*, product_id: str | None = None) -> OperatorHotpointControlRecord:
    return OperatorHotpointControlRecord(
        goal_id=HOTPOINT_GOAL_ID,
        revision=0,
        kill_switch_state=HotpointKillSwitchState.DISABLED,
        window_state=HotpointWindowState.NONE,
        parent_client_order_id=None,
        product_id=product_id,
        side=None,
        window_id=None,
        window_started_at=None,
        window_expires_at=None,
        create_state=HotpointCreateState.NOT_CLAIMED,
        cancel_state=HotpointCancelState.NOT_CLAIMED,
        create_exchange_invoked=None,
        cancel_exchange_invoked=None,
        placement_claim_id=None,
        cancel_claim_id=None,
        child_client_order_id=None,
        diagnostic_code="operator_hotpoint_disabled",
        actor_id="system",
        roles=(),
        correlation_id="not_recorded",
        audit_id="00000000-0000-0000-0000-000000000000",
        recorded_at="1970-01-01T00:00:00+00:00",
        updated_at="1970-01-01T00:00:00+00:00",
    )


class _Service:
    def __init__(self, *, futures: bool = False) -> None:
        self.policy = (
            FUTURES_HOTPOINT_SCOPE_POLICY
            if futures
            else SPOT_HOTPOINT_SCOPE_POLICY
        )
        self.placement_execution_available = not futures
        self.cancel_execution_available = not futures
        self.record = _record()
        self.control_calls = []

    def read(self):
        return self.record

    def list_eligible_parents(self, *, limit: int, offset: int):
        return (
            [
                {
                    "client_order_id": (
                        "11111111-1111-4111-8111-111111111111"
                    ),
                    "product_id": self.policy.product_id,
                    "side": "BUY",
                    "status": "OPEN",
                }
            ],
            1,
        )

    def control(self, **kwargs):
        self.control_calls.append(kwargs)
        self.record = replace(
            self.record,
            revision=1,
            kill_switch_state=HotpointKillSwitchState.ENABLED,
            diagnostic_code="operator_hotpoint_enabled",
            actor_id=kwargs["context"].actor_id,
            roles=kwargs["context"].roles,
            correlation_id=kwargs["context"].correlation_id,
            audit_id=kwargs["context"].audit_id,
        )
        return self.record


def test_hotpoint_read_and_control_are_authenticated_backend_workflows(
    monkeypatch,
) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_OPERATOR_HOTPOINT_ENABLED", "1")
    service = _Service()
    futures_service = _Service(futures=True)
    app = create_app()
    app.dependency_overrides[get_authenticated_actor] = lambda: AdminApiActor(
        actor_id="operator-1",
        roles=[AdminApiRole.ADMIN],
    )
    app.dependency_overrides[
        get_default_operator_hotpoint_control_services
    ] = lambda: {
        "SPOT": service,
        "FUTURES": futures_service,
    }
    client = TestClient(app)

    readback = client.get("/api/v1/hotpoint")
    assert readback.status_code == 200
    assert readback.json()["allowed_actions"] == ["ENABLE"]
    assert readback.json()["rate_limit"] == {
        "scope": "GOAL_GLOBAL",
        "create_cap": 1,
        "create_claims_consumed": 0,
        "create_claims_remaining": 1,
        "consumed_by_domain": None,
        "trigger_window_seconds": 60,
    }
    assert readback.json()["recent_placement"] is None
    parents = client.get("/api/v1/hotpoint/eligible-parents")
    assert parents.status_code == 200
    assert parents.json()["items"][0]["product_id"] == "BTC-USDC"
    futures_readback = client.get("/api/v1/hotpoint?domain=FUTURES")
    assert futures_readback.status_code == 200
    assert futures_readback.json()["domain"] == "FUTURES"
    assert futures_readback.json()["product_scope"] == "AVP-20DEC30-CDE"
    assert futures_readback.json()["exact_size"] == "1"
    assert futures_readback.json()["max_submitted_notional_usdc"] == "100"
    assert futures_readback.json()["max_possible_execution_notional_usdc"] == "150"
    assert futures_readback.json()["max_turnover_notional_usdc"] == "300"
    assert futures_readback.json()["placement_execution_available"] is False
    assert futures_readback.json()["rate_limit"]["scope"] == "GOAL_GLOBAL"
    futures_parents = client.get(
        "/api/v1/hotpoint/eligible-parents?domain=FUTURES"
    )
    assert futures_parents.status_code == 200
    assert futures_parents.json()["items"][0]["domain"] == "FUTURES"
    assert futures_parents.json()["items"][0]["product_id"] == (
        "AVP-20DEC30-CDE"
    )
    futures_service.record = replace(
        futures_service.record,
        goal_create_claim_consumed=True,
        goal_create_claim_domain="SPOT",
    )
    globally_consumed_futures = client.get(
        "/api/v1/hotpoint?domain=FUTURES"
    )
    assert globally_consumed_futures.status_code == 200
    assert globally_consumed_futures.json()["allowed_actions"] == []
    assert globally_consumed_futures.json()["rate_limit"][
        "create_claims_remaining"
    ] == 0
    assert globally_consumed_futures.json()["rate_limit"][
        "consumed_by_domain"
    ] == "SPOT"

    response = client.post(
        "/api/v1/hotpoint/control",
        headers={
            "Idempotency-Key": "enable-1",
            "X-Correlation-Id": "corr-enable-1",
            "X-Operator-Intent": "control_operator_hotpoint",
        },
        json={
            "domain": "SPOT",
            "action": "ENABLE",
            "expected_revision": 0,
            "confirm_control_action": True,
            "authorize_one_bounded_trigger_window": True,
            "acknowledge_unknown_outcome_consumes_create_allowance": True,
            "acknowledge_backend_derives_child_terms": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["control"]["kill_switch_state"] == "ENABLED"
    assert payload["control"]["allowed_actions"] == ["DISABLE", "ARM"]
    assert payload["live_coinbase_orders_ran"] is False
    assert len(service.control_calls) == 1

    rejected = client.post(
        "/api/v1/hotpoint/control",
        headers={
            "Idempotency-Key": "enable-terms",
            "X-Correlation-Id": "corr-enable-terms",
            "X-Operator-Intent": "control_operator_hotpoint",
        },
        json={
            "domain": "SPOT",
            "action": "ENABLE",
            "expected_revision": 0,
            "confirm_control_action": True,
            "limit_price": "1",
        },
    )
    assert rejected.status_code == 422
    assert len(service.control_calls) == 1
    futures_run = client.post(
        "/api/v1/hotpoint/run-once",
        headers={
            "Idempotency-Key": "futures-run-1",
            "X-Correlation-Id": "corr-futures-run-1",
            "X-Operator-Intent": "run_operator_hotpoint_once",
        },
        json={
            "domain": "FUTURES",
            "confirm_bounded_trigger_evaluation": True,
            "acknowledge_unknown_outcome_consumes_create_allowance": True,
        },
    )
    assert futures_run.status_code == 503
    assert futures_run.json()["message"] == (
        "operator_hotpoint_domain_execution_unavailable"
    )

    service.record = replace(
        service.record,
        window_state=HotpointWindowState.TERMINAL,
        create_state=HotpointCreateState.ACCEPTED,
        parent_client_order_id="11111111-1111-4111-8111-111111111111",
        child_client_order_id="33333333-3333-4333-8333-333333333333",
        create_exchange_invoked=True,
        diagnostic_code="operator_hotpoint_create_accepted",
        updated_at="2026-07-24T16:00:00+00:00",
        goal_create_claim_consumed=True,
        goal_create_claim_domain="SPOT",
    )
    recent = client.get("/api/v1/hotpoint?domain=SPOT")
    assert recent.status_code == 200
    assert recent.json()["recent_placement"] == {
        "domain": "SPOT",
        "parent_client_order_id": (
            "11111111-1111-4111-8111-111111111111"
        ),
        "child_client_order_id": (
            "33333333-3333-4333-8333-333333333333"
        ),
        "create_state": "ACCEPTED",
        "create_exchange_invoked": True,
        "diagnostic_code": "operator_hotpoint_create_accepted",
        "updated_at": "2026-07-24T16:00:00+00:00",
    }


def test_unconfigured_futures_hotpoint_is_visible_but_has_no_actions(
    monkeypatch,
) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_OPERATOR_HOTPOINT_ENABLED", "1")
    spot_service = _Service()
    futures_service = UnavailableFuturesHotpointControlService(
        shared_goal_service=spot_service,
    )
    app = create_app()
    app.dependency_overrides[get_authenticated_actor] = lambda: AdminApiActor(
        actor_id="operator-1",
        roles=[AdminApiRole.ADMIN],
    )
    app.dependency_overrides[
        get_default_operator_hotpoint_control_services
    ] = lambda: {
        "SPOT": spot_service,
        "FUTURES": futures_service,
    }
    client = TestClient(app)

    readback = client.get("/api/v1/hotpoint?domain=FUTURES")

    assert readback.status_code == 200
    payload = readback.json()
    assert payload["domain"] == "FUTURES"
    assert payload["portfolio_profile_alias"] == "Default"
    assert payload["product_scope"] == "AVP-20DEC30-CDE"
    assert payload["placement_execution_available"] is False
    assert payload["cancel_execution_available"] is False
    assert payload["diagnostic_code"] == (
        "operator_futures_hotpoint_portfolio_not_configured"
    )
    assert payload["allowed_actions"] == []
    assert payload["rate_limit"]["create_claims_remaining"] == 1

    parents = client.get(
        "/api/v1/hotpoint/eligible-parents?domain=FUTURES"
    )
    assert parents.status_code == 200
    assert parents.json()["items"] == []
    assert parents.json()["total_count"] == 0

    mutation = client.post(
        "/api/v1/hotpoint/control",
        headers={
            "Idempotency-Key": "futures-enable-1",
            "X-Correlation-Id": "corr-futures-enable-1",
            "X-Operator-Intent": "control_operator_hotpoint",
        },
        json={
            "domain": "FUTURES",
            "action": "ENABLE",
            "expected_revision": 0,
            "confirm_control_action": True,
            "authorize_one_bounded_trigger_window": True,
            "acknowledge_unknown_outcome_consumes_create_allowance": True,
            "acknowledge_backend_derives_child_terms": True,
        },
    )
    assert mutation.status_code == 503
    assert mutation.json()["code"] == "backend_unavailable"
    assert mutation.json()["live_coinbase_orders_ran"] is False
