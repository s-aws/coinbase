from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from fastapi.testclient import TestClient
import pytest

from api.v1.app import create_app
from api.v1.routes import operator_hotpoint as hotpoint_routes
from api.v1.routes.operator_hotpoint import (
    get_default_operator_hotpoint_control_services,
    router as hotpoint_router,
)
from application.admin_api.auth import get_authenticated_actor
from application.admin_api.models import AdminApiActor
from application.admin_api.operator_hotpoint_control import (
    FUTURES_HOTPOINT_GOAL_ID,
    HOTPOINT_GOAL_ID,
    FUTURES_HOTPOINT_SCOPE_POLICY,
    HotpointCancelState,
    HotpointCreateState,
    HotpointKillSwitchState,
    HotpointWindowState,
    OperatorHotpointControlRecord,
    SPOT_HOTPOINT_SCOPE_POLICY,
)
from application.admin_api.operator_futures_hotpoint_v2 import (
    FUTURES_HOTPOINT_POLICY_SHA256,
    OperatorFuturesHotpointReadback as OperatorFuturesHotpointServiceReadback,
)
from application.admin_api.operator_futures_manual_lifecycle import (
    FUTURES_MANUAL_ELIGIBILITY_CATEGORIES,
    FUTURES_MANUAL_MARGIN_SUBREADS,
    FuturesManualGoalRecord,
    FuturesManualLifecycleError,
)
from application.admin_api.operator_hotpoint_runtime import (
    FuturesHotpointExecutionPosture,
    UnavailableFuturesHotpointControlService,
)
from core.enums import (
    AdminApiRole,
    AdminFuturesManualCallOutcome,
    AdminFuturesManualEligibilityOutcome,
)


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


def _goal13_control_record() -> OperatorHotpointControlRecord:
    return replace(
        _record(product_id="AVP-20DEC30-CDE"),
        goal_id=FUTURES_HOTPOINT_GOAL_ID,
        revision=7,
        kill_switch_state=HotpointKillSwitchState.ENABLED,
        window_state=HotpointWindowState.ARMED,
        parent_client_order_id=(
            "11111111-1111-4111-8111-111111111111"
        ),
        side="BUY",
        window_id="22222222-2222-4222-8222-222222222222",
        window_started_at="2026-07-26T12:00:00+00:00",
        window_expires_at="2026-07-26T12:01:00+00:00",
        diagnostic_code="operator_futures_hotpoint_trigger_ready",
        correlation_id="corr-goal13",
        audit_id="55555555-5555-4555-8555-555555555555",
        updated_at="2026-07-26T12:00:00+00:00",
    )


def _goal13_candidate() -> dict[str, str]:
    return {
        "product_id": "AVP-20DEC30-CDE",
        "side": "BUY",
        "order_type": "LIMIT_GTC",
        "post_only": "true",
        "contract_count": "1",
        "limit_price": "4.99",
        "opening_reference_notional_usdc": "49.90",
        "maximum_exposure_reference_notional_usdc": "49.90",
        "buffered_close_reference_notional_usdc": "59.88",
        "branch_turnover_reference_notional_usdc": "109.78",
        "opening_cap_usdc": "100",
        "exposure_cap_usdc": "150",
        "turnover_cap_usdc": "300",
        "product_policy_revision": "1",
        "product_policy_sha256": FUTURES_HOTPOINT_POLICY_SHA256,
        "hotpoint_session_compatibility": "OPEN_24X7_GTC",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "hotpoint_window_id": "must-not-be-public",
        "hotpoint_parent_client_order_id": "must-not-be-public",
        "private_binding": "must-not-be-public",
    }


def _goal13_lifecycle(**updates) -> FuturesManualGoalRecord:
    record = FuturesManualGoalRecord(
        goal_id=FUTURES_HOTPOINT_GOAL_ID,
        revision=0,
        cycles_used=0,
        active_cycle_number=None,
        eligibility_outcome=None,
        eligibility_diagnostic_code=(
            "operator_futures_manual_not_refreshed"
        ),
        category_attempts={
            category: 0 for category in FUTURES_MANUAL_ELIGIBILITY_CATEGORIES
        },
        candidate=None,
        candidate_sha256=None,
        portfolio_id_sha256=None,
        eligibility_evidence_sha256=None,
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
        diagnostic_code="operator_futures_hotpoint_trigger_ready",
        correlation_id=None,
        audit_id=None,
        updated_at="2026-07-26T12:00:00+00:00",
    )
    return replace(record, **updates)


def _goal13_combined(
    *,
    lifecycle: FuturesManualGoalRecord | None = None,
    allowed_actions: tuple[str, ...] = (
        "DISABLE",
        "DISARM",
        "RUN_ONCE",
    ),
) -> OperatorFuturesHotpointServiceReadback:
    return OperatorFuturesHotpointServiceReadback(
        goal_id=FUTURES_HOTPOINT_GOAL_ID,
        revision=7,
        control_revision=7,
        lifecycle_revision=(
            lifecycle.revision if lifecycle is not None else 0
        ),
        control=_goal13_control_record(),
        lifecycle=lifecycle or _goal13_lifecycle(),
        allowed_actions=allowed_actions,
        cancel_disposition=None,
        diagnostic_code="operator_futures_hotpoint_trigger_ready",
        trigger_fill_count=3,
        trigger_evidence_sha256="a" * 64,
        window_id_sha256="b" * 64,
    )


class _Goal13Service:
    policy = FUTURES_HOTPOINT_SCOPE_POLICY
    control_available = True
    placement_execution_available = True
    cancel_execution_available = True

    def __init__(
        self,
        record: OperatorFuturesHotpointServiceReadback | None = None,
    ) -> None:
        self.record = record or _goal13_combined()
        self.control_calls = []
        self.run_calls = []
        self.closeout_calls = []
        self.error: FuturesManualLifecycleError | None = None

    def read(self):
        return self.record

    def list_eligible_parents(self, *, limit: int, offset: int):
        return (
            [
                {
                    "client_order_id": (
                        "11111111-1111-4111-8111-111111111111"
                    ),
                    "product_id": "AVP-20DEC30-CDE",
                    "side": "BUY",
                    "status": "OPEN",
                }
            ],
            1,
        )

    def control(self, **kwargs):
        self.control_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.record

    def run_once(self, **kwargs):
        self.run_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.record

    def safe_closeout(self, **kwargs):
        self.closeout_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.record


def _goal13_client(
    monkeypatch,
    service: _Goal13Service,
    *,
    roles: list[AdminApiRole] | None = None,
) -> TestClient:
    monkeypatch.setenv("COINBASE_ADMIN_API_OPERATOR_HOTPOINT_ENABLED", "1")
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_FUTURES_HOTPOINT_V2_ENABLED",
        "1",
    )
    monkeypatch.setattr(
        hotpoint_routes,
        "get_operator_futures_hotpoint_execution_posture",
        lambda: FuturesHotpointExecutionPosture(
            ready=True,
            diagnostic_code=(
                "operator_futures_hotpoint_execution_posture_ready"
            ),
        ),
    )
    app = create_app()
    app.dependency_overrides[get_authenticated_actor] = lambda: AdminApiActor(
        actor_id="operator-1",
        roles=roles or [AdminApiRole.ADMIN, AdminApiRole.TRADER],
    )
    app.dependency_overrides[
        get_default_operator_hotpoint_control_services
    ] = lambda: {"SPOT": _Service(), "FUTURES": service}
    return TestClient(app)


def test_hotpoint_read_and_control_are_authenticated_backend_workflows(
    monkeypatch,
) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_OPERATOR_HOTPOINT_ENABLED", "1")
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_FUTURES_HOTPOINT_V2_ENABLED",
        "1",
    )
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
            "expected_revision": 0,
            "expected_parent_client_order_id": (
                "11111111-1111-4111-8111-111111111111"
            ),
            "confirm_bounded_trigger_evaluation": True,
            "authorize_one_no_retry_six_category_cycle": True,
            "acknowledge_cycle_is_goal_global_and_limited_to_ten": True,
            "acknowledge_unsuccessful_or_unknown_cycle_fails_closed": True,
            "authorize_one_preview_and_conditional_identical_create": True,
            "acknowledge_unknown_preview_or_create_consumes_allowance": True,
            "acknowledge_create_requires_accepted_identical_preview": True,
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


@pytest.mark.parametrize(
    "role",
    [AdminApiRole.OPERATOR, AdminApiRole.EMERGENCY],
)
def test_hotpoint_stop_control_accepts_every_automation_control_role(
    monkeypatch,
    role,
) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_OPERATOR_HOTPOINT_ENABLED", "1")
    service = _Service()
    app = create_app()
    app.dependency_overrides[get_authenticated_actor] = lambda: AdminApiActor(
        actor_id="operator-1",
        roles=[role],
    )
    app.dependency_overrides[
        get_default_operator_hotpoint_control_services
    ] = lambda: {"SPOT": service}
    client = TestClient(app)

    response = client.post(
        "/api/v1/hotpoint/control",
        headers={
            "Idempotency-Key": f"disable-{role.value}",
            "X-Correlation-Id": f"corr-disable-{role.value}",
            "X-Operator-Intent": "control_operator_hotpoint",
        },
        json={
            "domain": "SPOT",
            "action": "DISABLE",
            "expected_revision": 0,
            "confirm_control_action": True,
        },
    )

    assert response.status_code == 200
    assert service.control_calls[0]["context"].roles == (role.value,)


@pytest.mark.parametrize(
    ("role", "expected_actions"),
    [
        (AdminApiRole.OPERATOR, ["ENABLE"]),
        (AdminApiRole.EMERGENCY, []),
    ],
)
def test_hotpoint_resume_controls_require_resume_permission(
    monkeypatch,
    role,
    expected_actions,
) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_OPERATOR_HOTPOINT_ENABLED", "1")
    service = _Service()
    app = create_app()
    app.dependency_overrides[get_authenticated_actor] = lambda: AdminApiActor(
        actor_id="operator-1",
        roles=[role],
    )
    app.dependency_overrides[
        get_default_operator_hotpoint_control_services
    ] = lambda: {"SPOT": service}
    client = TestClient(app)

    readback = client.get("/api/v1/hotpoint?domain=SPOT")
    assert readback.status_code == 200
    assert readback.json()["allowed_actions"] == expected_actions

    response = client.post(
        "/api/v1/hotpoint/control",
        headers={
            "Idempotency-Key": f"enable-{role.value}",
            "X-Correlation-Id": f"corr-enable-{role.value}",
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

    assert response.status_code == (
        200 if role is AdminApiRole.OPERATOR else 403
    )


@pytest.mark.parametrize(
    ("role", "expected_actions"),
    [
        (AdminApiRole.OPERATOR, ["ENABLE"]),
        (AdminApiRole.EMERGENCY, []),
    ],
)
def test_goal13_resume_readback_requires_resume_permission(
    monkeypatch,
    role,
    expected_actions,
) -> None:
    combined = replace(
        _goal13_combined(allowed_actions=("ENABLE",)),
        control=replace(
            _goal13_control_record(),
            kill_switch_state=HotpointKillSwitchState.DISABLED,
            window_state=HotpointWindowState.NONE,
            parent_client_order_id=None,
            side=None,
            window_id=None,
            window_started_at=None,
            window_expires_at=None,
        ),
        trigger_fill_count=0,
        trigger_evidence_sha256=None,
        window_id_sha256=None,
    )
    client = _goal13_client(
        monkeypatch,
        _Goal13Service(combined),
        roles=[role],
    )

    response = client.get("/api/v1/hotpoint?domain=FUTURES")

    assert response.status_code == 200
    assert response.json()["allowed_actions"] == expected_actions


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


def test_futures_v2_flag_is_a_fail_closed_route_selector(
    monkeypatch,
) -> None:
    """Historical Goal 9 reads remain visible, but cannot receive mutations."""

    monkeypatch.setenv("COINBASE_ADMIN_API_OPERATOR_HOTPOINT_ENABLED", "1")
    monkeypatch.delenv(
        "COINBASE_ADMIN_API_OPERATOR_FUTURES_HOTPOINT_V2_ENABLED",
        raising=False,
    )
    spot_service = _Service()
    historical_futures = _Service(futures=True)
    app = create_app()
    app.dependency_overrides[get_authenticated_actor] = lambda: AdminApiActor(
        actor_id="operator-1",
        roles=[AdminApiRole.ADMIN, AdminApiRole.TRADER],
    )
    app.dependency_overrides[
        get_default_operator_hotpoint_control_services
    ] = lambda: {
        "SPOT": spot_service,
        "FUTURES": historical_futures,
    }
    client = TestClient(app)

    readback = client.get("/api/v1/hotpoint?domain=FUTURES")
    assert readback.status_code == 200
    assert readback.json()["goal_id"] == HOTPOINT_GOAL_ID

    mutation = client.post(
        "/api/v1/hotpoint/control",
        headers={
            "Idempotency-Key": "historical-futures-enable",
            "X-Correlation-Id": "corr-historical-futures-enable",
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
    assert mutation.json()["message"] == (
        "operator_futures_hotpoint_v2_disabled"
    )
    assert historical_futures.control_calls == []
    assert spot_service.control_calls == []


def test_goal13_run_and_closeout_reject_goal9_request_shapes_before_service(
    monkeypatch,
) -> None:
    """A domain literal cannot bypass Goal 13's exact authority fields."""

    monkeypatch.setenv("COINBASE_ADMIN_API_OPERATOR_HOTPOINT_ENABLED", "1")
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_FUTURES_HOTPOINT_V2_ENABLED",
        "1",
    )
    futures_service = _Service(futures=True)
    app = create_app()
    app.dependency_overrides[get_authenticated_actor] = lambda: AdminApiActor(
        actor_id="operator-1",
        roles=[AdminApiRole.ADMIN, AdminApiRole.TRADER],
    )
    app.dependency_overrides[
        get_default_operator_hotpoint_control_services
    ] = lambda: {
        "SPOT": _Service(),
        "FUTURES": futures_service,
    }
    client = TestClient(app)
    headers = {
        "Idempotency-Key": "goal13-old-shape",
        "X-Correlation-Id": "corr-goal13-old-shape",
    }

    run = client.post(
        "/api/v1/hotpoint/run-once",
        headers={
            **headers,
            "X-Operator-Intent": "run_operator_hotpoint_once",
        },
        json={
            "domain": "FUTURES",
            "confirm_bounded_trigger_evaluation": True,
            "acknowledge_unknown_outcome_consumes_create_allowance": True,
        },
    )
    closeout = client.post(
        "/api/v1/hotpoint/safe-closeout",
        headers={
            **headers,
            "X-Operator-Intent": (
                "safe_closeout_operator_hotpoint_child"
            ),
        },
        json={
            "domain": "FUTURES",
            "confirm_exact_child_safe_closeout": True,
            "acknowledge_unknown_outcome_consumes_cancel_allowance": True,
        },
    )

    assert run.status_code == 422
    assert closeout.status_code == 422
    assert futures_service.control_calls == []


def test_goal13_live_admission_uses_complete_futures_posture_only(
    monkeypatch,
) -> None:
    """Futures admission must include authority/client/portfolio/route posture."""

    posture_checks = []
    monkeypatch.setattr(
        hotpoint_routes,
        "build_admin_api_command_runtime_readiness",
        lambda: (_ for _ in ()).throw(
            AssertionError("spot runtime readiness must not be consulted")
        ),
    )
    monkeypatch.setattr(
        hotpoint_routes,
        "get_decision_backed_live_execution_service",
        lambda: (_ for _ in ()).throw(
            AssertionError("generic service state must not be consulted")
        ),
    )
    monkeypatch.setattr(
        hotpoint_routes,
        "operator_mvp_live_service_state_allows_route_admission",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Spot admission predicate must not be consulted")
        ),
    )
    monkeypatch.setattr(
        hotpoint_routes,
        "get_operator_futures_hotpoint_execution_posture",
        lambda: (
            posture_checks.append("checked")
            or FuturesHotpointExecutionPosture(
                ready=True,
                diagnostic_code=(
                    "operator_futures_hotpoint_execution_posture_ready"
                ),
            )
        ),
    )

    hotpoint_routes._require_live_runtime(
        route="/api/v1/hotpoint/run-once",
        domain="FUTURES",
    )

    assert posture_checks == ["checked"]


def test_goal13_readback_is_strict_allowlisted_and_actor_actionable(
    monkeypatch,
) -> None:
    candidate = _goal13_candidate()
    lifecycle = _goal13_lifecycle(
        revision=1,
        cycles_used=1,
        eligibility_outcome=AdminFuturesManualEligibilityOutcome.ELIGIBLE,
        eligibility_diagnostic_code=(
            "operator_futures_hotpoint_exact_v3_eligible"
        ),
        category_attempts={
            category: 1
            for category in FUTURES_MANUAL_ELIGIBILITY_CATEGORIES
        },
        margin_subread_attempts={
            subread: 1 for subread in FUTURES_MANUAL_MARGIN_SUBREADS
        },
        candidate=candidate,
        candidate_sha256="c" * 64,
        portfolio_id_sha256="d" * 64,
        eligibility_evidence_sha256="e" * 64,
    )
    service = _Goal13Service(_goal13_combined(lifecycle=lifecycle))
    client = _goal13_client(monkeypatch, service)
    monkeypatch.setattr(
        hotpoint_routes,
        "_require_live_runtime",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("GET must remain call-free")
        ),
    )

    response = client.get("/api/v1/hotpoint?domain=FUTURES")

    assert response.status_code == 200
    payload = response.json()
    assert payload["goal_id"] == FUTURES_HOTPOINT_GOAL_ID
    assert payload["portfolio_profile_alias"] == "Default"
    assert payload["portfolio_profile_type"] == "DEFAULT"
    assert payload["cycles_used"] == 1
    assert payload["cycles_remaining"] == 9
    assert payload["trigger_fill_count"] == 3
    assert payload["trigger_evidence_sha256"] == "a" * 64
    assert payload["window_id_sha256"] == "b" * 64
    assert payload["margin_subread_attempts"] == {
        "futures_balance_summary": 1,
        "intraday_margin_setting": 1,
        "current_margin_window_regular": 1,
        "current_margin_window_intraday": 1,
    }
    assert payload["latest_external_command"] is None
    assert payload["allowed_actions"] == [
        "DISABLE",
        "DISARM",
        "RUN_ONCE",
    ]
    assert set(payload["candidate"]) == {
        "product_id",
        "side",
        "order_type",
        "post_only",
        "contract_count",
        "limit_price",
        "opening_reference_notional_usdc",
        "maximum_exposure_reference_notional_usdc",
        "buffered_close_reference_notional_usdc",
        "branch_turnover_reference_notional_usdc",
        "opening_cap_usdc",
        "exposure_cap_usdc",
        "turnover_cap_usdc",
        "product_policy_revision",
        "product_policy_sha256",
        "hotpoint_session_compatibility",
        "observed_at",
    }
    assert payload["candidate"]["post_only"] is True
    assert payload["candidate"]["product_policy_revision"] == 1
    assert payload["preview"] == {
        "outcome": "NOT_RUN",
        "call_boundary_entered": None,
        "allowance_consumed": False,
        "allowance_remaining": 1,
    }
    assert payload["live_coinbase_orders_ran"] is False
    control = client.post(
        "/api/v1/hotpoint/control",
        headers={
            "Idempotency-Key": "goal13-control-call-free",
            "X-Correlation-Id": "corr-goal13-control-call-free",
            "X-Operator-Intent": "control_operator_hotpoint",
        },
        json={
            "domain": "FUTURES",
            "action": "DISABLE",
            "expected_revision": 7,
            "confirm_control_action": True,
        },
    )
    assert control.status_code == 200
    assert control.json()["live_coinbase_orders_ran"] is False

    viewer_client = _goal13_client(
        monkeypatch,
        service,
        roles=[AdminApiRole.VIEWER],
    )
    viewer = viewer_client.get("/api/v1/hotpoint?domain=FUTURES")
    assert viewer.status_code == 200
    assert viewer.json()["allowed_actions"] == []


@pytest.mark.parametrize(
    ("lifecycle_updates", "posture_ready"),
    [
        ({"active_cycle_number": 1}, True),
        ({"cycles_used": 10}, True),
        ({}, False),
    ],
)
def test_goal13_readback_suppresses_run_when_not_actionable(
    monkeypatch,
    lifecycle_updates,
    posture_ready,
) -> None:
    service = _Goal13Service(
        _goal13_combined(
            lifecycle=_goal13_lifecycle(**lifecycle_updates),
        )
    )
    client = _goal13_client(monkeypatch, service)
    monkeypatch.setattr(
        hotpoint_routes,
        "get_operator_futures_hotpoint_execution_posture",
        lambda: FuturesHotpointExecutionPosture(
            ready=posture_ready,
            diagnostic_code=(
                "operator_futures_hotpoint_execution_posture_ready"
                if posture_ready
                else "operator_futures_hotpoint_execution_authority_missing"
            ),
        ),
    )

    response = client.get("/api/v1/hotpoint?domain=FUTURES")

    assert response.status_code == 200
    assert "RUN_ONCE" not in response.json()["allowed_actions"]


@pytest.mark.parametrize(
    ("create_outcome", "create_entered", "safe_expected"),
    [
        (AdminFuturesManualCallOutcome.ACCEPTED, True, True),
        (AdminFuturesManualCallOutcome.UNKNOWN, True, True),
        (AdminFuturesManualCallOutcome.UNKNOWN, False, False),
    ],
)
def test_goal13_safe_closeout_requires_accepted_or_boundary_entered_unknown(
    monkeypatch,
    create_outcome,
    create_entered,
    safe_expected,
) -> None:
    lifecycle = _goal13_lifecycle(
        client_order_id="operator-futures-hotpoint-v2-child",
        preview_outcome=AdminFuturesManualCallOutcome.ACCEPTED,
        preview_exchange_invoked=True,
        preview_id_sha256="c" * 64,
        create_outcome=create_outcome,
        create_exchange_invoked=create_entered,
        exchange_order_id_sha256="d" * 64,
        execution_claim_id="33333333-3333-4333-8333-333333333333",
    )
    service = _Goal13Service(
        _goal13_combined(
            lifecycle=lifecycle,
            allowed_actions=("SAFE_CLOSEOUT",),
        )
    )
    client = _goal13_client(monkeypatch, service)

    response = client.get("/api/v1/hotpoint?domain=FUTURES")

    assert response.status_code == 200
    assert (
        "SAFE_CLOSEOUT" in response.json()["allowed_actions"]
    ) is safe_expected
    if safe_expected:
        viewer = _goal13_client(
            monkeypatch,
            service,
            roles=[AdminApiRole.VIEWER],
        ).get("/api/v1/hotpoint?domain=FUTURES")
        assert viewer.status_code == 200
        assert "SAFE_CLOSEOUT" not in viewer.json()["allowed_actions"]


def test_goal13_terminal_reconciliation_marks_cancel_not_required(
    monkeypatch,
) -> None:
    lifecycle = _goal13_lifecycle(
        client_order_id="operator-futures-hotpoint-v2-child",
        preview_outcome=AdminFuturesManualCallOutcome.ACCEPTED,
        preview_exchange_invoked=True,
        preview_id_sha256="c" * 64,
        create_outcome=AdminFuturesManualCallOutcome.ACCEPTED,
        create_exchange_invoked=True,
        exchange_order_id_sha256="d" * 64,
        reconciliation_outcome=AdminFuturesManualCallOutcome.ACCEPTED,
        reconciliation_exchange_invoked=True,
        order_status="FILLED",
        authoritatively_nonterminal=False,
        execution_claim_id="33333333-3333-4333-8333-333333333333",
    )
    combined = replace(
        _goal13_combined(lifecycle=lifecycle, allowed_actions=()),
        cancel_disposition="NOT_REQUIRED",
    )
    client = _goal13_client(monkeypatch, _Goal13Service(combined))

    response = client.get("/api/v1/hotpoint?domain=FUTURES")

    assert response.status_code == 200
    payload = response.json()
    assert payload["cancel_disposition"] == "NOT_REQUIRED"
    assert payload["cancel_state"] == "NOT_REQUIRED"
    assert payload["cancel"]["outcome"] == "NOT_RUN"
    assert payload["cancel"]["allowance_remaining"] == 1
    assert "SAFE_CLOSEOUT" not in payload["allowed_actions"]
    assert payload["live_exchange_submitted"] is True
    assert payload["live_coinbase_orders_ran"] is True


@pytest.mark.parametrize(
    ("order_status", "cancel_disposition"),
    [
        ("PENDING", "DEFERRED_TRANSITIONAL"),
        ("QUEUED", "DEFERRED_TRANSITIONAL"),
        ("EDIT_QUEUED", "DEFERRED_TRANSITIONAL"),
        ("CANCEL_QUEUED", "ALREADY_CANCEL_REQUESTED"),
    ],
)
def test_goal13_transitional_reconciliation_never_recancels(
    monkeypatch,
    order_status,
    cancel_disposition,
) -> None:
    lifecycle = _goal13_lifecycle(
        client_order_id="operator-futures-hotpoint-v2-child",
        preview_outcome=AdminFuturesManualCallOutcome.ACCEPTED,
        preview_exchange_invoked=True,
        preview_id_sha256="c" * 64,
        create_outcome=AdminFuturesManualCallOutcome.ACCEPTED,
        create_exchange_invoked=True,
        exchange_order_id_sha256="d" * 64,
        reconciliation_outcome=AdminFuturesManualCallOutcome.ACCEPTED,
        reconciliation_exchange_invoked=True,
        order_status=order_status,
        authoritatively_nonterminal=True,
        execution_claim_id="33333333-3333-4333-8333-333333333333",
    )
    combined = replace(
        _goal13_combined(lifecycle=lifecycle, allowed_actions=()),
        cancel_disposition=cancel_disposition,
    )
    client = _goal13_client(monkeypatch, _Goal13Service(combined))

    response = client.get("/api/v1/hotpoint?domain=FUTURES")

    assert response.status_code == 200
    payload = response.json()
    assert payload["order_status"] == order_status
    assert payload["authoritatively_nonterminal"] is True
    assert payload["cancel_disposition"] == cancel_disposition
    assert payload["cancel_state"] == "NOT_CLAIMED"
    assert payload["cancel"] == {
        "outcome": "NOT_RUN",
        "call_boundary_entered": None,
        "allowance_consumed": False,
        "allowance_remaining": 1,
    }
    assert "SAFE_CLOSEOUT" not in payload["allowed_actions"]


@pytest.mark.parametrize("reconciled", [False, True])
def test_goal13_foreign_cancel_seal_is_sanitized_fail_closed_readback(
    monkeypatch,
    reconciled,
) -> None:
    lifecycle = _goal13_lifecycle(
        client_order_id="operator-futures-hotpoint-v2-child",
        preview_outcome=AdminFuturesManualCallOutcome.ACCEPTED,
        preview_exchange_invoked=True,
        preview_id_sha256="c" * 64,
        create_outcome=AdminFuturesManualCallOutcome.ACCEPTED,
        create_exchange_invoked=True,
        exchange_order_id_sha256="d" * 64,
        reconciliation_outcome=(
            AdminFuturesManualCallOutcome.ACCEPTED
            if reconciled
            else AdminFuturesManualCallOutcome.NOT_RUN
        ),
        reconciliation_exchange_invoked=True if reconciled else None,
        order_status="OPEN" if reconciled else None,
        authoritatively_nonterminal=True if reconciled else None,
        diagnostic_code=(
            "operator_futures_cancel_invocation_already_sealed"
        ),
        execution_claim_id="33333333-3333-4333-8333-333333333333",
    )
    combined = replace(
        _goal13_combined(lifecycle=lifecycle, allowed_actions=()),
        cancel_disposition="ALREADY_CANCEL_REQUESTED",
        diagnostic_code=(
            "operator_futures_cancel_invocation_already_sealed"
        ),
    )
    client = _goal13_client(monkeypatch, _Goal13Service(combined))

    response = client.get("/api/v1/hotpoint?domain=FUTURES")

    assert response.status_code == 200
    payload = response.json()
    assert payload["cancel_disposition"] == "ALREADY_CANCEL_REQUESTED"
    assert payload["cancel_state"] == "NOT_CLAIMED"
    assert payload["cancel"]["outcome"] == "NOT_RUN"
    assert payload["cancel"]["allowance_remaining"] == 1
    assert "SAFE_CLOSEOUT" not in payload["allowed_actions"]


@pytest.mark.parametrize(
    ("order_status", "cancel_disposition"),
    [
        ("FILLED", "NOT_REQUIRED"),
        ("PENDING", "DEFERRED_TRANSITIONAL"),
        ("CANCEL_QUEUED", "ALREADY_CANCEL_REQUESTED"),
    ],
)
def test_goal13_safe_receipt_reports_only_current_cancel_boundary(
    monkeypatch,
    order_status,
    cancel_disposition,
) -> None:
    lifecycle = _goal13_lifecycle(
        revision=3,
        client_order_id="operator-futures-hotpoint-v2-child",
        preview_outcome=AdminFuturesManualCallOutcome.ACCEPTED,
        preview_exchange_invoked=True,
        preview_id_sha256="c" * 64,
        create_outcome=AdminFuturesManualCallOutcome.ACCEPTED,
        create_exchange_invoked=True,
        exchange_order_id_sha256="d" * 64,
        reconciliation_outcome=AdminFuturesManualCallOutcome.ACCEPTED,
        reconciliation_exchange_invoked=True,
        order_status=order_status,
        authoritatively_nonterminal=order_status != "FILLED",
        execution_claim_id="33333333-3333-4333-8333-333333333333",
    )
    combined = replace(
        _goal13_combined(lifecycle=lifecycle, allowed_actions=()),
        cancel_disposition=cancel_disposition,
    )
    client = _goal13_client(monkeypatch, _Goal13Service(combined))

    response = client.post(
        "/api/v1/hotpoint/safe-closeout",
        headers={
            "Idempotency-Key": f"goal13-safe-{order_status.lower()}",
            "X-Correlation-Id": f"corr-goal13-safe-{order_status.lower()}",
            "X-Operator-Intent": (
                "safe_closeout_operator_hotpoint_child"
            ),
        },
        json={
            "domain": "FUTURES",
            "expected_revision": 7,
            "expected_child_client_order_id": (
                "operator-futures-hotpoint-v2-child"
            ),
            "confirm_exact_child_safe_closeout": True,
            "authorize_one_exact_no_retry_reconciliation": True,
            "acknowledge_unknown_reconciliation_consumes_allowance": True,
            "acknowledge_cancel_only_exact_authoritatively_nonterminal_child": (
                True
            ),
            "acknowledge_unknown_outcome_consumes_cancel_allowance": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["live_exchange_submitted"] is False
    assert payload["live_coinbase_orders_ran"] is False
    assert payload["control"]["live_exchange_submitted"] is True
    assert payload["control"]["live_coinbase_orders_ran"] is True


def test_goal13_mutation_reports_preview_boundary_and_stable_audit(
    monkeypatch,
) -> None:
    lifecycle = _goal13_lifecycle(
        revision=1,
        preview_outcome=AdminFuturesManualCallOutcome.UNKNOWN,
        preview_exchange_invoked=True,
        diagnostic_code=(
            "operator_futures_hotpoint_preview_outcome_unknown"
        ),
    )
    service = _Goal13Service(
        _goal13_combined(lifecycle=lifecycle, allowed_actions=())
    )
    client = _goal13_client(monkeypatch, service)
    headers = {
        "Idempotency-Key": "goal13-run-stable",
        "X-Correlation-Id": "corr-goal13-run",
        "X-Operator-Intent": "run_operator_hotpoint_once",
    }
    body = {
        "domain": "FUTURES",
        "expected_revision": 7,
        "expected_parent_client_order_id": (
            "11111111-1111-4111-8111-111111111111"
        ),
        "confirm_bounded_trigger_evaluation": True,
        "authorize_one_no_retry_six_category_cycle": True,
        "acknowledge_cycle_is_goal_global_and_limited_to_ten": True,
        "acknowledge_unsuccessful_or_unknown_cycle_fails_closed": True,
        "authorize_one_preview_and_conditional_identical_create": True,
        "acknowledge_unknown_preview_or_create_consumes_allowance": True,
        "acknowledge_create_requires_accepted_identical_preview": True,
    }

    first = client.post(
        "/api/v1/hotpoint/run-once",
        headers=headers,
        json=body,
    )
    second = client.post(
        "/api/v1/hotpoint/run-once",
        headers=headers,
        json=body,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["live_exchange_submitted"] is False
    assert first.json()["live_coinbase_orders_ran"] is False
    assert first.json()["control"]["live_exchange_submitted"] is False
    assert first.json()["control"]["live_coinbase_orders_ran"] is False
    assert first.json()["control"]["preview"] == {
        "outcome": "UNKNOWN",
        "call_boundary_entered": True,
        "allowance_consumed": True,
        "allowance_remaining": 0,
    }
    assert service.run_calls[0]["context"].audit_id == (
        service.run_calls[1]["context"].audit_id
    )
    assert service.run_calls[0]["context"].audit_id == first.json()["audit_id"]
    forwarded = service.run_calls[0]
    assert {
        key: value
        for key, value in forwarded.items()
        if key != "context"
    } == {
        "expected_revision": 7,
        "expected_parent_client_order_id": (
            "11111111-1111-4111-8111-111111111111"
        ),
        "confirm_bounded_trigger_evaluation": True,
        "authorize_one_no_retry_six_category_cycle": True,
        "acknowledge_cycle_is_goal_global_and_limited_to_ten": True,
        "acknowledge_unsuccessful_or_unknown_cycle_fails_closed": True,
        "authorize_one_preview_and_conditional_identical_create": True,
        "acknowledge_unknown_preview_or_create_consumes_allowance": True,
        "acknowledge_create_requires_accepted_identical_preview": True,
    }


def test_goal13_safe_closeout_does_not_report_reconciliation_as_mutation(
    monkeypatch,
) -> None:
    lifecycle = _goal13_lifecycle(
        revision=3,
        client_order_id="operator-futures-hotpoint-v2-child",
        preview_outcome=AdminFuturesManualCallOutcome.ACCEPTED,
        preview_exchange_invoked=True,
        preview_id_sha256="c" * 64,
        create_outcome=AdminFuturesManualCallOutcome.ACCEPTED,
        create_exchange_invoked=True,
        exchange_order_id_sha256="d" * 64,
        reconciliation_outcome=AdminFuturesManualCallOutcome.UNKNOWN,
        reconciliation_exchange_invoked=True,
        execution_claim_id="33333333-3333-4333-8333-333333333333",
    )
    service = _Goal13Service(
        _goal13_combined(lifecycle=lifecycle, allowed_actions=())
    )
    client = _goal13_client(monkeypatch, service)
    body = {
        "domain": "FUTURES",
        "expected_revision": 7,
        "expected_child_client_order_id": (
            "operator-futures-hotpoint-v2-child"
        ),
        "confirm_exact_child_safe_closeout": True,
        "authorize_one_exact_no_retry_reconciliation": True,
        "acknowledge_unknown_reconciliation_consumes_allowance": True,
        "acknowledge_cancel_only_exact_authoritatively_nonterminal_child": True,
        "acknowledge_unknown_outcome_consumes_cancel_allowance": True,
    }

    response = client.post(
        "/api/v1/hotpoint/safe-closeout",
        headers={
            "Idempotency-Key": "goal13-safe-reconciliation",
            "X-Correlation-Id": "corr-goal13-safe-reconciliation",
            "X-Operator-Intent": (
                "safe_closeout_operator_hotpoint_child"
            ),
        },
        json=body,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["live_exchange_submitted"] is False
    assert payload["live_coinbase_orders_ran"] is False
    assert payload["control"]["live_exchange_submitted"] is True
    assert payload["control"]["live_coinbase_orders_ran"] is True
    assert payload["control"]["reconciliation"] == {
        "outcome": "UNKNOWN",
        "call_boundary_entered": True,
        "allowance_consumed": True,
        "allowance_remaining": 0,
    }
    assert {
        key: value
        for key, value in service.closeout_calls[0].items()
        if key != "context"
    } == {
        "expected_revision": 7,
        "expected_child_client_order_id": (
            "operator-futures-hotpoint-v2-child"
        ),
        "confirm_exact_child_safe_closeout": True,
        "authorize_one_exact_no_retry_reconciliation": True,
        "acknowledge_unknown_reconciliation_consumes_allowance": True,
        "acknowledge_cancel_only_exact_authoritatively_nonterminal_child": True,
        "acknowledge_unknown_outcome_consumes_cancel_allowance": True,
    }


def test_goal13_lifecycle_error_is_fixed_http_detail(
    monkeypatch,
) -> None:
    service = _Goal13Service()
    service.error = FuturesManualLifecycleError(
        "operator_futures_hotpoint_idempotency_conflict",
        http_status_code=409,
    )
    client = _goal13_client(monkeypatch, service)

    response = client.post(
        "/api/v1/hotpoint/control",
        headers={
            "Idempotency-Key": "goal13-conflict",
            "X-Correlation-Id": "corr-goal13-conflict",
            "X-Operator-Intent": "control_operator_hotpoint",
        },
        json={
            "domain": "FUTURES",
            "action": "ENABLE",
            "expected_revision": 7,
            "confirm_control_action": True,
            "authorize_one_bounded_trigger_window": True,
            "acknowledge_unknown_outcome_consumes_create_allowance": True,
            "acknowledge_backend_derives_child_terms": True,
        },
    )

    assert response.status_code == 409
    assert response.json()["message"] == (
        "operator_futures_hotpoint_idempotency_conflict"
    )
    assert "exception" not in response.text.lower()
