"""Authenticated, local-only Admin API routes for operator automation."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Mapping

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.v1.app import app as _ADMIN_API_APP
from api.v1.routes import operator_automation as operator_automation_routes
from application.admin_api.automation_models import (
    AutomationControlAction,
    AutomationControlPlaneItem,
    AutomationDefinitionLifecycleAction,
    AutomationEligibilityCycleMutationResponse,
    AutomationEligibilityRefreshActivity,
    AutomationRunDetailResponse,
    AutomationRunItem,
    AutomationRunMutationResponse,
)
from application.admin_api.models import AdminApiActor
from application.admin_api.live_execution import (
    CONFIGURED_LIVE_EXECUTION_SERVICE_SOURCE,
    AdminApiLiveExecutionServiceState,
)
from application.admin_api.operator_automation import (
    AutomationRepositoryConflict,
    AutomationRepositoryMutation,
    AutomationRepositoryPage,
    OperatorAutomationService,
)
from application.admin_api.operator_mvp_policy import (
    OPERATOR_MVP_AUTOMATION_ATOMIC_MARKET_SNAPSHOT_ROUTE,
    OPERATOR_MVP_AUTOMATION_PREVIEW_GATED_SINGLE_CHILD_ROUTE,
)
from application.admin_api.route_inventory import ADMIN_API_ROUTE_INVENTORY
from core.enums import AdminApiLiveExecutionStatus, AdminApiPermission


pytestmark = pytest.mark.regression

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
DEFINITION_ID = "2f744264-8d18-46a2-b89d-f0c206216515"
RUN_ID = "19cae8ee-d8ec-43d3-a0f7-8f55ba1d76a0"
AUDIT_ID = "26371b41-f16e-4dad-83cc-946055440c62"
_SERVICE_SLOT: dict[str, OperatorAutomationService] = {}
_SHARED_CLIENT: TestClient | None = None


def _resolve_test_service() -> OperatorAutomationService:
    return _SERVICE_SLOT["service"]


_ADMIN_API_APP.dependency_overrides[
    operator_automation_routes.get_operator_automation_service
] = _resolve_test_service


def _definition(*, state: str = "DRAFT") -> dict[str, Any]:
    return {
        "definition_id": DEFINITION_ID,
        "revision": 1,
        "display_name": "Bounded Spot sweep review",
        "domain": "SPOT",
        "job_kind": "SPOT_SWEEP",
        "product_ids": ["BTC-USDC"],
        "lifecycle_state": state,
        "minimum_size_preparation": None,
        "schedule": {
            "mode": "MANUAL_ONLY",
            "interval_minutes": None,
            "next_review_at": None,
            "due": False,
        },
        "adapter_status": "UNAVAILABLE",
        "live_execution_available": False,
        "allowed_actions": ["ENABLE", "DISABLE", "SET_SCHEDULE", "RUN_ONCE"],
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
    }


def _run() -> dict[str, Any]:
    return {
        "run_id": RUN_ID,
        "definition_id": DEFINITION_ID,
        "domain": "SPOT",
        "job_kind": "SPOT_SWEEP",
        "trigger": "ONE_SHOT",
        "state": "BLOCKED",
        "diagnostic_code": "automation_domain_adapter_unavailable",
        "adapter_status": "UNAVAILABLE",
        "live_attempt_consumed": False,
        "coinbase_api_call_count": 0,
        "create_call_count": 0,
        "cancel_call_count": 0,
        "reconciliation_call_count": 0,
        "create_allowance_consumed": False,
        "cancel_allowance_consumed": False,
        "client_order_id": None,
        "audit_id": AUDIT_ID,
        "correlation_id": "automation-route-correlation",
        "claimed_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
    }


def _actionable_single_child_run() -> dict[str, Any]:
    categories = [
        "api_key_permissions",
        "portfolio_catalog",
        "wallet_balances",
        "product_metadata",
        "best_bid_ask",
        "fee_summary",
        "exact_order_reconciliation",
        "active_order_catalog",
    ]
    return {
        **_run(),
        "job_kind": "SPOT_CAMPAIGN",
        "state": "AWAITING_OPERATOR_AUTHORIZATION",
        "diagnostic_code": "awaiting_operator_authorization",
        "adapter_status": "AWAITING_OPERATOR_AUTHORIZATION",
        "live_execution_available": True,
        "coinbase_api_call_count": 8,
        "call_count_exact": True,
        "child_terminal": None,
        "single_child_plan": {
            "plan_sha256": "a" * 64,
            "portfolio_scope": "Test",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "base_size": "0.5",
            "limit_price": "2",
            "order_type": "LIMIT",
            "time_in_force": "GOOD_UNTIL_CANCELLED",
            "post_only": False,
            "submitted_notional_usdc": "1",
            "possible_execution_notional_usdc": "1",
            "max_submitted_notional_usdc": "3.10",
            "max_possible_execution_notional_usdc": "1.00",
        },
        "eligibility": {
            "cycle_number": 1,
            "required_categories": categories,
            "completed_categories": categories,
            "eligible": True,
            "blocker_code": None,
            "coinbase_api_call_count": 8,
            "call_count_exact": True,
        },
        "allowed_actions": ["AUTHORIZE_SINGLE_CHILD"],
    }


def _source_gated_single_child_run() -> dict[str, Any]:
    categories = [
        "api_key_permissions",
        "portfolio_catalog",
        "wallet_balances",
        "product_metadata",
        "best_bid_ask",
        "fee_summary",
        "exact_order_reconciliation",
        "active_order_catalog",
    ]
    return {
        **_run(),
        "job_kind": "SPOT_CAMPAIGN",
        "state": "BLOCKED",
        "diagnostic_code": "automation_active_order_catalog_read_not_authorized",
        "adapter_status": "BLOCKED",
        "live_execution_available": False,
        "call_count_exact": True,
        "single_child_plan": {
            "plan_sha256": "a" * 64,
            "portfolio_scope": "CONFIGURED_UNVERIFIED",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "base_size": "0.5",
            "limit_price": "2",
            "order_type": "LIMIT",
            "time_in_force": "GOOD_UNTIL_CANCELLED",
            "post_only": False,
            "submitted_notional_usdc": "1",
            "possible_execution_notional_usdc": "1",
            "max_submitted_notional_usdc": "3.10",
            "max_possible_execution_notional_usdc": "1.00",
        },
        "eligibility": {
            "cycle_number": None,
            "required_categories": categories,
            "completed_categories": [],
            "eligible": False,
            "blocker_code": "automation_active_order_catalog_read_not_authorized",
            "coinbase_api_call_count": 0,
            "call_count_exact": True,
        },
        "allowed_actions": ["REFRESH_ELIGIBILITY"],
    }


def _control(posture: str = "ACTIVE") -> dict[str, Any]:
    allowed_actions = {
        "ACTIVE": ["PAUSE", "DRAIN", "SHUTDOWN"],
        "PAUSED": ["RESUME", "DRAIN", "SHUTDOWN"],
        "DRAINING": ["RESUME", "SHUTDOWN"],
        "SHUTDOWN": ["RESUME"],
    }[posture]
    return {
        "posture": posture,
        "local_admission_enabled": posture == "ACTIVE",
        "recurring_worker_started": False,
        "live_scheduler_enabled": False,
        "coinbase_api_call_count": 0,
        "exchange_mutation_count": 0,
        "allowed_actions": allowed_actions,
        "updated_at": NOW.isoformat(),
    }


@dataclass
class _FakeRepository:
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    replayed: bool = False
    error: Exception | None = None
    control_posture: str = "ACTIVE"

    def _record(self, name: str, **kwargs: Any) -> None:
        self.calls.append((name, kwargs))
        if self.error is not None:
            raise self.error

    def get_control_posture(self) -> Mapping[str, Any]:
        self._record("get_control_posture")
        return _control(self.control_posture)

    def list_definitions(self, **kwargs: Any) -> AutomationRepositoryPage:
        self._record("list_definitions", **kwargs)
        return AutomationRepositoryPage(items=(_definition(),), total_count=1)

    def get_definition(self, definition_id: str) -> Mapping[str, Any] | None:
        self._record("get_definition", definition_id=definition_id)
        return _definition() if definition_id == DEFINITION_ID else None

    def create_definition(self, **kwargs: Any) -> AutomationRepositoryMutation:
        self._record("create_definition", **kwargs)
        return self._mutation(_definition(), kwargs["context"].correlation_id)

    def prepare_near_market_candidate(
        self,
        **kwargs: Any,
    ) -> AutomationRepositoryMutation:
        self._record("prepare_near_market_candidate", **kwargs)
        definition = _definition()
        definition.update(
            {
                "display_name": "BTC-USDC near-market successor V4",
                "job_kind": "SPOT_CAMPAIGN",
                "spot_execution_mode": "NEAR_MARKET_POST_ONLY_V4",
                "single_child_order": {
                    "side": "BUY",
                    "base_size": "0.00001",
                    "limit_price": "50000.00",
                    "order_type": "LIMIT",
                    "time_in_force": "GOOD_UNTIL_CANCELLED",
                    "post_only": True,
                },
            }
        )
        return self._mutation(
            {
                "outcome": "MATERIALIZED",
                "candidate_version": 4,
                "spot_execution_mode": "NEAR_MARKET_POST_ONLY_V4",
                "cycle_number": 1,
                "policy_revision": "BTC_USDC_POST_ONLY_BEST_BID_V1",
                "diagnostic_code": "automation_near_market_terms_derived",
                "completed_categories": [
                    "api_key_permissions",
                    "portfolio_catalog",
                    "wallet_balances",
                    "product_metadata",
                    "best_bid_ask",
                    "fee_summary",
                ],
                "coinbase_api_call_count": 6,
                "call_count_exact": True,
                "definition": definition,
                "preview_call_count": 0,
                "create_call_count": 0,
                "cancel_call_count": 0,
            },
            kwargs["context"].correlation_id,
        )

    def prepare_minimum_size_candidate(
        self,
        **kwargs: Any,
    ) -> AutomationRepositoryMutation:
        self._record("prepare_minimum_size_candidate", **kwargs)
        definition = _definition()
        definition.update(
            {
                "display_name": "BTC-USDC minimum-size successor V7",
                "job_kind": "SPOT_CAMPAIGN",
                "spot_execution_mode": "MINIMUM_SIZE_POST_ONLY_V7",
                "minimum_size_preparation": {
                    "policy_revision": (
                        "BTC_USDC_POST_ONLY_BEST_BID_MINIMUM_SIZE_V2"
                    ),
                    "boundary_classification": (
                        "minimum_size_v4_fee_reserve_conflict"
                    ),
                    "cycle_number": 1,
                    "completed_categories": [
                        "api_key_permissions",
                        "portfolio_catalog",
                        "wallet_balances",
                        "product_metadata",
                        "best_bid_ask",
                        "fee_summary",
                    ],
                    "coinbase_api_call_count": 6,
                    "call_count_exact": True,
                    "max_submitted_notional_usdc": "3.10",
                    "max_possible_execution_notional_usdc": "1.01",
                },
                "single_child_order": {
                    "side": "BUY",
                    "base_size": "0.00001",
                    "limit_price": "100000.00",
                    "order_type": "LIMIT",
                    "time_in_force": "GOOD_UNTIL_CANCELLED",
                    "post_only": True,
                },
            }
        )
        return self._mutation(
            {
                "outcome": "MATERIALIZED",
                "candidate_version": 7,
                "spot_execution_mode": "MINIMUM_SIZE_POST_ONLY_V7",
                "cycle_number": 1,
                "policy_revision": (
                    "BTC_USDC_POST_ONLY_BEST_BID_MINIMUM_SIZE_V2"
                ),
                "boundary_classification": (
                    "minimum_size_v4_fee_reserve_conflict"
                ),
                "diagnostic_code": "minimum_size_v4_fee_reserve_conflict",
                "completed_categories": [
                    "api_key_permissions",
                    "portfolio_catalog",
                    "wallet_balances",
                    "product_metadata",
                    "best_bid_ask",
                    "fee_summary",
                ],
                "coinbase_api_call_count": 6,
                "call_count_exact": True,
                "definition": definition,
                "max_submitted_notional_usdc": "3.10",
                "max_possible_execution_notional_usdc": "1.01",
                "preview_call_count": 0,
                "create_call_count": 0,
                "cancel_call_count": 0,
            },
            kwargs["context"].correlation_id,
        )

    def authorize_atomic_market_snapshot_candidate(
        self,
        **kwargs: Any,
    ) -> AutomationRepositoryMutation:
        self._record("authorize_atomic_market_snapshot_candidate", **kwargs)
        return self._mutation(
            {
                "outcome": "BLOCKED",
                "candidate_version": 13,
                "cycle_number": 1,
                "diagnostic_code": "atomic_market_snapshot_stale",
                "completed_categories": [
                    "api_key_permissions",
                    "portfolio_catalog",
                    "wallet_balances",
                    "product_metadata",
                    "best_bid_ask",
                    "fee_summary",
                    "exact_order_reconciliation",
                    "active_order_catalog",
                ],
                "coinbase_api_call_count": 8,
                "call_count_exact": True,
                "market_snapshot_binding": "UNAVAILABLE",
                "transport_readiness": "PASSED",
                "transport_failure_class": "NONE",
                "dns_status": "SUCCEEDED",
                "tcp_status": "SUCCEEDED",
                "tls_status": "SUCCEEDED",
                "dns_probe_count": 1,
                "tcp_probe_count": 1,
                "tls_probe_count": 1,
                "run": None,
            },
            kwargs["context"].correlation_id,
        )

    def transition_definition(self, **kwargs: Any) -> AutomationRepositoryMutation:
        self._record("transition_definition", **kwargs)
        state = {
            AutomationDefinitionLifecycleAction.ENABLE: "ENABLED",
            AutomationDefinitionLifecycleAction.DISABLE: "DISABLED",
            AutomationDefinitionLifecycleAction.PAUSE: "PAUSED",
            AutomationDefinitionLifecycleAction.RESUME: "ENABLED",
            AutomationDefinitionLifecycleAction.DRAIN: "DRAINING",
        }[kwargs["action"]]
        return self._mutation(_definition(state=state), kwargs["context"].correlation_id)

    def set_schedule(self, **kwargs: Any) -> AutomationRepositoryMutation:
        self._record("set_schedule", **kwargs)
        entity = _definition()
        entity["schedule"] = {
            "mode": "INTERVAL_REVIEW_ONLY",
            "interval_minutes": 60,
            "next_review_at": "2026-07-20T13:00:00+00:00",
            "due": False,
        }
        return self._mutation(entity, kwargs["context"].correlation_id)

    def clear_schedule(self, **kwargs: Any) -> AutomationRepositoryMutation:
        self._record("clear_schedule", **kwargs)
        return self._mutation(_definition(), kwargs["context"].correlation_id)

    def transition_control_posture(self, **kwargs: Any) -> AutomationRepositoryMutation:
        self._record("transition_control_posture", **kwargs)
        return self._mutation(
            _control(kwargs["action"].value),
            kwargs["context"].correlation_id,
        )

    def claim_one_shot_run(self, **kwargs: Any) -> AutomationRepositoryMutation:
        self._record("claim_one_shot_run", **kwargs)
        return self._mutation(_run(), kwargs["context"].correlation_id)

    def list_runs(self, **kwargs: Any) -> AutomationRepositoryPage:
        self._record("list_runs", **kwargs)
        return AutomationRepositoryPage(items=(_run(),), total_count=1)

    def get_run(self, run_id: str) -> Mapping[str, Any] | None:
        self._record("get_run", run_id=run_id)
        return _run() if run_id == RUN_ID else None

    def list_run_events(self, **kwargs: Any) -> AutomationRepositoryPage:
        self._record("list_run_events", **kwargs)
        return AutomationRepositoryPage(
            items=(
                {
                    "event_id": "218d5f34-a054-410b-9c92-ddd09dcd6b03",
                    "run_id": RUN_ID,
                    "sequence": 1,
                    "from_state": None,
                    "state": "CLAIMED",
                    "diagnostic_code": "one_shot_run_claimed",
                    "audit_id": AUDIT_ID,
                    "correlation_id": "automation-route-correlation",
                    "recorded_at": NOW.isoformat(),
                },
                {
                    "event_id": "228d5f34-a054-410b-9c92-ddd09dcd6b03",
                    "run_id": RUN_ID,
                    "sequence": 2,
                    "from_state": "CLAIMED",
                    "state": "BLOCKED",
                    "diagnostic_code": "automation_domain_adapter_unavailable",
                    "audit_id": AUDIT_ID,
                    "correlation_id": "automation-route-correlation",
                    "recorded_at": NOW.isoformat(),
                },
            ),
            total_count=2,
        )

    def list_definition_events(self, **kwargs: Any) -> AutomationRepositoryPage:
        self._record("list_definition_events", **kwargs)
        return AutomationRepositoryPage(
            items=(
                {
                    "event_id": "318d5f34-a054-410b-9c92-ddd09dcd6b03",
                    "definition_id": DEFINITION_ID,
                    "from_state": None,
                    "to_state": "DRAFT",
                    "diagnostic_code": "automation_definition_created",
                    "audit_id": AUDIT_ID,
                    "correlation_id": "automation-route-correlation",
                    "recorded_at": NOW.isoformat(),
                },
            ),
            total_count=1,
        )

    def list_control_events(self, **kwargs: Any) -> AutomationRepositoryPage:
        self._record("list_control_events", **kwargs)
        return AutomationRepositoryPage(
            items=(
                {
                    "event_id": "418d5f34-a054-410b-9c92-ddd09dcd6b03",
                    "from_state": "ACTIVE",
                    "to_state": "PAUSED",
                    "diagnostic_code": "automation_control_pause",
                    "audit_id": AUDIT_ID,
                    "correlation_id": "automation-route-correlation",
                    "recorded_at": NOW.isoformat(),
                },
            ),
            total_count=1,
        )

    def _mutation(
        self,
        entity: Mapping[str, Any],
        correlation_id: str,
    ) -> AutomationRepositoryMutation:
        return AutomationRepositoryMutation(
            entity=entity,
            audit_id=AUDIT_ID,
            correlation_id=correlation_id,
            replayed=self.replayed,
        )


@pytest.fixture(autouse=True)
def _bootstrap_auth(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("COINBASE_ADMIN_API_AUTH_MODE", "bootstrap_bearer")
    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "local-admin-token")
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_AUTOMATION_ENABLED",
        "1",
    )


@pytest.fixture(scope="module", autouse=True)
def _shared_admin_api_client():
    global _SHARED_CLIENT
    with TestClient(_ADMIN_API_APP) as client:
        _SHARED_CLIENT = client
        yield
    _SHARED_CLIENT = None
    _SERVICE_SLOT.clear()
    _ADMIN_API_APP.dependency_overrides.pop(
        operator_automation_routes.get_operator_automation_service,
        None,
    )


def _headers(
    *,
    roles: str = "trader",
    operator_intent: str | None = None,
    idempotency_key: str = "automation-idempotency-1",
) -> dict[str, str]:
    headers = {
        "Authorization": "Bearer local-admin-token",
        "X-Admin-Actor": "operator-automation-route-test",
        "X-Admin-Roles": roles,
    }
    if operator_intent is not None:
        headers.update(
            {
                "Idempotency-Key": idempotency_key,
                "X-Correlation-Id": "automation-route-correlation",
                "X-Operator-Intent": operator_intent,
            }
        )
    return headers


def _client(repository: _FakeRepository) -> TestClient:
    assert _SHARED_CLIENT is not None
    _SERVICE_SLOT["service"] = OperatorAutomationService(repository)
    return _SHARED_CLIENT


@pytest.mark.parametrize("configured_value", [None, "", "true", "yes", "0", " 1"])
def test_nonexact_feature_gate_fails_closed_before_repository(
    monkeypatch: pytest.MonkeyPatch,
    configured_value: str | None,
):
    if configured_value is None:
        monkeypatch.delenv(
            "COINBASE_ADMIN_API_OPERATOR_AUTOMATION_ENABLED",
            raising=False,
        )
    else:
        monkeypatch.setenv(
            "COINBASE_ADMIN_API_OPERATOR_AUTOMATION_ENABLED",
            configured_value,
        )
    repository = _FakeRepository()
    response = _client(repository).get(
        "/api/v1/automation/control-plane",
        headers=_headers(),
    )
    assert response.status_code == 503
    assert response.json()["message"] == "operator_automation_disabled"
    assert repository.calls == []


def test_read_routes_are_local_typed_and_backend_paginated():
    repository = _FakeRepository()
    client = _client(repository)

    control = client.get("/api/v1/automation/control-plane", headers=_headers())
    definitions = client.get(
        "/api/v1/automation/definitions",
        params={"domain": "SPOT", "job_kind": "SPOT_SWEEP", "limit": 25, "offset": 0},
        headers=_headers(),
    )
    detail = client.get(
        f"/api/v1/automation/definitions/{DEFINITION_ID}",
        headers=_headers(),
    )
    runs = client.get(
        "/api/v1/automation/runs",
        params={"definition_id": DEFINITION_ID, "state": "BLOCKED", "limit": 25},
        headers=_headers(),
    )
    run = client.get(f"/api/v1/automation/runs/{RUN_ID}", headers=_headers())
    events = client.get(
        f"/api/v1/automation/runs/{RUN_ID}/events",
        params={"limit": 25, "offset": 0},
        headers=_headers(),
    )
    definition_events = client.get(
        f"/api/v1/automation/definitions/{DEFINITION_ID}/events",
        params={"limit": 25, "offset": 0},
        headers=_headers(),
    )
    control_events = client.get(
        "/api/v1/automation/control-plane/events",
        params={"limit": 25, "offset": 0},
        headers=_headers(),
    )

    assert [
        response.status_code
        for response in (
            control,
            definitions,
            detail,
            runs,
            run,
            events,
            definition_events,
            control_events,
        )
    ] == [200] * 8
    assert control.json()["activity"]["coinbase_api_call_count"] == 0
    assert definitions.json()["pagination"]["total_matching_count"] == 1
    assert detail.json()["definition"]["domain"] == "SPOT"
    assert runs.json()["items"][0]["state"] == "BLOCKED"
    assert run.json()["run"]["live_attempt_consumed"] is False
    assert events.json()["items"][1]["diagnostic_code"] == "automation_domain_adapter_unavailable"
    assert events.json()["items"][1]["from_state"] == "CLAIMED"
    assert events.json()["items"][1]["audit_id"] == AUDIT_ID
    assert events.json()["items"][1]["correlation_id"] == "automation-route-correlation"
    assert definition_events.json()["items"][0]["definition_id"] == DEFINITION_ID
    assert definition_events.json()["items"][0]["audit_id"] == AUDIT_ID
    assert control_events.json()["items"][0]["diagnostic_code"] == (
        "automation_control_pause"
    )


def test_definition_list_rejects_cross_domain_filter_without_repository_access():
    repository = _FakeRepository()
    response = _client(repository).get(
        "/api/v1/automation/definitions",
        params={"domain": "SPOT", "job_kind": "FOLLOW_UP"},
        headers=_headers(),
    )
    assert response.status_code == 422
    assert response.json()["message"] == "automation_filter_domain_kind_mismatch"
    assert repository.calls == []


@pytest.mark.parametrize(
    (
        "roles",
        "can_create",
        "can_prepare_near_market",
        "control_actions",
        "definition_actions",
    ),
    [
        ("viewer", False, False, [], []),
        (
            "operator",
            True,
            False,
            ["PAUSE", "DRAIN", "SHUTDOWN"],
            ["ENABLE", "DISABLE", "SET_SCHEDULE"],
        ),
        (
            "trader",
            True,
            True,
            ["PAUSE", "DRAIN", "SHUTDOWN"],
            ["ENABLE", "DISABLE", "SET_SCHEDULE", "RUN_ONCE"],
        ),
        (
            "emergency",
            False,
            False,
            ["PAUSE", "DRAIN", "SHUTDOWN"],
            [],
        ),
    ],
)
def test_readback_actions_are_scoped_by_backend_rbac(
    monkeypatch: pytest.MonkeyPatch,
    roles: str,
    can_create: bool,
    can_prepare_near_market: bool,
    control_actions: list[str],
    definition_actions: list[str],
):
    monkeypatch.setattr(
        operator_automation_routes,
        "_operator_automation_live_action_ready",
        lambda action: action == "REFRESH_ELIGIBILITY",
    )
    repository = _FakeRepository()
    client = _client(repository)

    control = client.get(
        "/api/v1/automation/control-plane",
        headers=_headers(roles=roles),
    )
    definitions = client.get(
        "/api/v1/automation/definitions",
        headers=_headers(roles=roles),
    )

    assert control.status_code == 200
    assert control.json()["control_plane"]["definition_create_allowed"] is can_create
    assert (
        control.json()["control_plane"][
            "near_market_candidate_preparation_allowed"
        ]
        is can_prepare_near_market
    )
    assert control.json()["control_plane"]["allowed_actions"] == control_actions
    assert definitions.status_code == 200
    assert definitions.json()["items"][0]["allowed_actions"] == definition_actions


def test_near_market_preparation_readback_fails_closed_outside_active_posture(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        operator_automation_routes,
        "_operator_automation_live_action_ready",
        lambda _action: True,
    )
    repository = _FakeRepository(control_posture="PAUSED")

    response = _client(repository).get(
        "/api/v1/automation/control-plane",
        headers=_headers(roles="trader"),
    )

    assert response.status_code == 200
    assert response.json()["control_plane"][
        "near_market_candidate_preparation_allowed"
    ] is False


def test_single_child_live_readback_is_scoped_by_backend_rbac(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        operator_automation_routes,
        "_operator_automation_live_action_ready",
        lambda _action: True,
        raising=False,
    )
    payload = AutomationRunDetailResponse(
        run=AutomationRunItem.model_validate(_actionable_single_child_run())
    )

    viewer = operator_automation_routes._scope_payload_for_actor(
        payload,
        AdminApiActor(actor_id="viewer", roles=["viewer"]),
    )
    trader = operator_automation_routes._scope_payload_for_actor(
        payload,
        AdminApiActor(actor_id="trader", roles=["trader"]),
    )

    assert viewer.run.live_execution_available is False
    assert viewer.run.allowed_actions == []
    assert trader.run.live_execution_available is True
    assert trader.run.allowed_actions == ["AUTHORIZE_SINGLE_CHILD"]


@pytest.mark.parametrize(
    ("action", "route"),
    [
        (
            "AUTHORIZE_SINGLE_CHILD",
            "/api/v1/automation/runs/{run_id}/authorize-single-child",
        ),
        (
            "AUTHORIZE_PREVIEW_GATED_SINGLE_CHILD",
            "/api/v1/automation/runs/{run_id}/authorize-preview-gated-single-child",
        ),
        (
            "SAFE_CLOSEOUT_CHILD",
            "/api/v1/automation/runs/{run_id}/safe-closeout-child",
        ),
    ],
)
def test_live_run_actions_require_exact_route_service_and_runtime_readiness(
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    route: str,
):
    payload = _actionable_single_child_run()
    if action == "AUTHORIZE_PREVIEW_GATED_SINGLE_CHILD":
        payload.update(
            {
                "spot_execution_mode": "DOCUMENTED_MARKET_FRESHNESS_V3",
                "allowed_actions": [action],
            }
        )
    elif action == "SAFE_CLOSEOUT_CHILD":
        payload.update(
            {
                "state": "ACTIVE",
                "diagnostic_code": "automation_spot_safe_closeout_ready",
                "adapter_status": "ACTIVE",
                "live_attempt_consumed": True,
                "coinbase_api_call_count": 10,
                "create_call_count": 1,
                "reconciliation_call_count": 1,
                "create_allowance_consumed": True,
                "client_order_id": "4dc878e7-f27b-42b5-adf3-4965b2b916d9",
                "child_terminal": False,
                "allowed_actions": [action],
            }
        )
    item = AutomationRunItem.model_validate(payload)
    actor = AdminApiActor(actor_id="trader", roles=["trader"])

    def scoped(
        *,
        state: AdminApiLiveExecutionServiceState,
        runtime_ready: bool,
    ) -> AutomationRunItem:
        monkeypatch.setattr(
            operator_automation_routes,
            "get_decision_backed_live_execution_service",
            lambda: SimpleNamespace(admission_state=lambda: state),
            raising=False,
        )
        monkeypatch.setattr(
            operator_automation_routes,
            "build_admin_api_command_runtime_readiness",
            lambda: SimpleNamespace(runtime_ready=runtime_ready),
            raising=False,
        )
        return operator_automation_routes._scope_run_item(item, actor)

    disabled = AdminApiLiveExecutionServiceState(
        required=True,
        present=True,
        status=AdminApiLiveExecutionStatus.LIVE_DISABLED,
        source="disabled_backend_service",
        missing_reason="live_execution_disabled",
        supported_routes=frozenset({("POST", route)}),
    )
    exact_route_missing = AdminApiLiveExecutionServiceState(
        required=True,
        present=True,
        status=AdminApiLiveExecutionStatus.APPROVAL_REQUIRED,
        source=CONFIGURED_LIVE_EXECUTION_SERVICE_SOURCE,
        missing_reason=None,
        max_submitted_notional_usdc="3.10",
        max_executed_notional_usdc="1.00",
        supported_routes=frozenset({("POST", "/api/v1/orders")}),
    )
    admitted = replace(
        exact_route_missing,
        supported_routes=frozenset({("POST", route)}),
    )

    assert scoped(state=disabled, runtime_ready=True).allowed_actions == []
    assert scoped(state=exact_route_missing, runtime_ready=True).allowed_actions == []
    assert scoped(state=admitted, runtime_ready=False).allowed_actions == []
    available = scoped(state=admitted, runtime_ready=True)
    assert available.allowed_actions == [action]
    assert available.live_execution_available is True

    refresh = operator_automation_routes._scope_run_item(
        AutomationRunItem.model_validate(_source_gated_single_child_run()),
        actor,
    )
    assert refresh.allowed_actions == ["REFRESH_ELIGIBILITY"]
    assert refresh.live_execution_available is False


def test_run_contract_exposes_only_direct_safe_closeout_after_create_readback():
    payload = {
        **_actionable_single_child_run(),
        "state": "ACTIVE",
        "diagnostic_code": "automation_spot_safe_closeout_ready",
        "adapter_status": "ACTIVE",
        "live_execution_available": True,
        "live_attempt_consumed": True,
        "coinbase_api_call_count": 10,
        "create_call_count": 1,
        "reconciliation_call_count": 1,
        "create_allowance_consumed": True,
        "client_order_id": "4dc878e7-f27b-42b5-adf3-4965b2b916d9",
        "child_terminal": False,
        "allowed_actions": ["SAFE_CLOSEOUT_CHILD"],
    }
    item = AutomationRunItem.model_validate(payload)
    assert item.allowed_actions == ["SAFE_CLOSEOUT_CHILD"]

    with pytest.raises(ValueError):
        AutomationRunItem.model_validate(
            {
                **payload,
                "allowed_actions": ["RECONCILE_CHILD"],
                "live_execution_available": False,
            }
        )


def test_run_contract_rejects_authorization_action_without_live_authority():
    with pytest.raises(ValueError):
        AutomationRunItem.model_validate(
            {
                **_actionable_single_child_run(),
                "allowed_actions": ["AUTHORIZE_SINGLE_CHILD"],
                "live_execution_available": False,
            }
        )


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/api/v1/automation/definitions", [("limit", "10"), ("limit", "20")]),
        ("/api/v1/automation/definitions", {"executor": "coinbase"}),
        ("/api/v1/automation/runs", {"futures_product": "AVP-20DEC30-CDE"}),
        (f"/api/v1/automation/definitions/{DEFINITION_ID}", {"refresh": "true"}),
    ],
)
def test_reads_reject_duplicate_or_unknown_queries_before_repository(path: str, params: Any):
    repository = _FakeRepository()
    response = _client(repository).get(path, params=params, headers=_headers())
    assert response.status_code == 422
    assert repository.calls == []


def test_read_rbac_and_mutation_rbac_are_backend_enforced():
    repository = _FakeRepository()
    client = _client(repository)
    no_auth = client.get("/api/v1/automation/definitions")
    assert no_auth.status_code == 401

    trigger = client.post(
        f"/api/v1/automation/definitions/{DEFINITION_ID}/runs",
        json={"confirm_one_shot": True, "reason": "Explicit one-shot review"},
        headers=_headers(
            roles="operator",
            operator_intent="claim_automation_one_shot_run",
        ),
    )
    assert trigger.status_code == 403
    assert repository.calls == []


def test_emergency_role_can_stop_but_cannot_resume_automation():
    repository = _FakeRepository(control_posture="PAUSED")
    client = _client(repository)

    readback = client.get(
        "/api/v1/automation/control-plane",
        headers=_headers(roles="emergency"),
    )
    assert readback.status_code == 200
    assert readback.json()["control_plane"]["allowed_actions"] == [
        "DRAIN",
        "SHUTDOWN",
    ]

    repository.calls.clear()
    resume = client.post(
        "/api/v1/automation/control-plane/resume",
        json={"reason": "Emergency role must not restore admission"},
        headers=_headers(
            roles="emergency",
            operator_intent="resume_automation_control_plane",
        ),
    )
    assert resume.status_code == 403
    assert repository.calls == []


def test_create_route_derives_spot_domain_and_rejects_futures_or_generic_payloads():
    repository = _FakeRepository()
    client = _client(repository)
    response = client.post(
        "/api/v1/automation/definitions",
        json={
            "display_name": "Bounded Spot sweep",
            "job_kind": "SPOT_SWEEP",
            "product_ids": ["BTC-USDC"],
        },
        headers=_headers(operator_intent="create_automation_definition"),
    )
    assert response.status_code == 200
    assert response.json()["definition"]["domain"] == "SPOT"
    assert response.json()["activity"]["exchange_mutation_count"] == 0
    assert repository.calls[-1][1]["definition"]["domain"] == "SPOT"

    rejected = client.post(
        "/api/v1/automation/definitions",
        json={
            "display_name": "Futures executor",
            "job_kind": "FUTURES_SWEEP",
            "executor_payload": {"product_id": "AVP-20DEC30-CDE"},
        },
        headers=_headers(operator_intent="create_automation_definition"),
    )
    assert rejected.status_code == 422


def test_near_market_candidate_route_requires_explicit_backend_derived_acknowledgement(
    monkeypatch: pytest.MonkeyPatch,
):
    repository = _FakeRepository()
    monkeypatch.setattr(
        operator_automation_routes,
        "build_admin_api_command_runtime_readiness",
        lambda: SimpleNamespace(runtime_ready=True),
    )
    body = {
        "confirm_backend_derived_terms": True,
        "confirm_one_no_retry_preparation_cycle": True,
        "confirm_btc_usdc_test_portfolio_scope": True,
        "confirm_unknown_consumes_cycle": True,
        "reason": "Prepare one exact near-market successor",
    }
    response = _client(repository).post(
        "/api/v1/automation/near-market-candidates",
        json=body,
        headers=_headers(
            operator_intent="prepare_automation_near_market_candidate"
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["outcome"] == "MATERIALIZED"
    assert payload["definition"]["single_child_order"]["post_only"] is True
    assert payload["coinbase_api_call_count"] == 6
    assert payload["preview_call_count"] == 0
    assert repository.calls[-1][0] == "prepare_near_market_candidate"

    repository.calls.clear()
    rejected = _client(repository).post(
        "/api/v1/automation/near-market-candidates",
        json={**body, "confirm_backend_derived_terms": False},
        headers=_headers(
            operator_intent="prepare_automation_near_market_candidate"
        ),
    )
    assert rejected.status_code == 422
    assert repository.calls == []


def test_minimum_size_candidate_route_requires_dynamic_cap_acknowledgement(
    monkeypatch: pytest.MonkeyPatch,
):
    repository = _FakeRepository()
    monkeypatch.setattr(
        operator_automation_routes,
        "build_admin_api_command_runtime_readiness",
        lambda: SimpleNamespace(runtime_ready=True),
    )
    body = {
        "confirm_backend_derived_terms": True,
        "confirm_one_no_retry_preparation_cycle": True,
        "confirm_btc_usdc_test_portfolio_scope": True,
        "confirm_dynamic_cap_strictly_below_3_10": True,
        "confirm_unknown_consumes_cycle": True,
        "reason": "Prepare one exact minimum-size successor",
    }
    response = _client(repository).post(
        "/api/v1/automation/minimum-size-candidates",
        json=body,
        headers=_headers(
            operator_intent="prepare_automation_minimum_size_candidate"
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate_version"] == 7
    assert payload["max_possible_execution_notional_usdc"] == "1.01"
    assert payload["preview_call_count"] == 0
    assert repository.calls[-1][0] == "prepare_minimum_size_candidate"


def test_atomic_market_snapshot_route_requires_all_live_acknowledgements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _FakeRepository()
    monkeypatch.setattr(
        operator_automation_routes,
        "build_admin_api_command_runtime_readiness",
        lambda: SimpleNamespace(runtime_ready=True),
    )
    monkeypatch.setattr(
        operator_automation_routes,
        "get_decision_backed_live_execution_service",
        lambda: SimpleNamespace(admission_state=lambda: SimpleNamespace()),
    )
    monkeypatch.setattr(
        operator_automation_routes,
        "operator_mvp_live_service_state_allows_route_admission",
        lambda *_args, **_kwargs: True,
    )
    body = {
        "confirm_atomic_final_market_snapshot_binding": True,
        "confirm_one_no_http_transport_readiness_sequence": True,
        "confirm_one_no_retry_eight_category_cycle": True,
        "confirm_single_preview": True,
        "confirm_conditional_identical_single_child_create": True,
        "confirm_btc_usdc_test_portfolio_scope": True,
        "confirm_both_notionals_strictly_below_3_10": True,
        "confirm_unknown_consumes_applicable_allowance": True,
        "reason": "Bind one final V10 snapshot and execute its bounded proof",
    }

    response = _client(repository).post(
        "/api/v1/automation/atomic-market-snapshot-candidates/authorize",
        json=body,
        headers=_headers(
            operator_intent=(
                "authorize_automation_atomic_market_snapshot_candidate"
            )
        ),
    )

    assert response.status_code == 200
    assert response.json()["diagnostic_code"] == "atomic_market_snapshot_stale"
    assert response.json()["run"] is None
    assert repository.calls[-1][0] == (
        "authorize_atomic_market_snapshot_candidate"
    )

    repository.calls.clear()
    rejected = _client(repository).post(
        "/api/v1/automation/atomic-market-snapshot-candidates/authorize",
        json={**body, "confirm_single_preview": False},
        headers=_headers(
            operator_intent=(
                "authorize_automation_atomic_market_snapshot_candidate"
            )
        ),
    )
    assert rejected.status_code == 422
    assert repository.calls == []

    missing_transport_acknowledgement = _client(repository).post(
        "/api/v1/automation/atomic-market-snapshot-candidates/authorize",
        json={
            key: value
            for key, value in body.items()
            if key != "confirm_one_no_http_transport_readiness_sequence"
        },
        headers=_headers(
            operator_intent=(
                "authorize_automation_atomic_market_snapshot_candidate"
            )
        ),
    )
    assert missing_transport_acknowledgement.status_code == 422
    assert repository.calls == []


def test_atomic_market_snapshot_route_requires_its_exact_live_service_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _FakeRepository()
    monkeypatch.setattr(
        operator_automation_routes,
        "build_admin_api_command_runtime_readiness",
        lambda: SimpleNamespace(runtime_ready=True),
    )
    monkeypatch.setattr(
        operator_automation_routes,
        "get_decision_backed_live_execution_service",
        lambda: SimpleNamespace(admission_state=lambda: SimpleNamespace()),
    )
    admitted_routes: list[tuple[str, str]] = []

    def admit_only_legacy_preview(_state, *, method: str, route: str) -> bool:
        admitted_routes.append((method, route))
        return route == OPERATOR_MVP_AUTOMATION_PREVIEW_GATED_SINGLE_CHILD_ROUTE

    monkeypatch.setattr(
        operator_automation_routes,
        "operator_mvp_live_service_state_allows_route_admission",
        admit_only_legacy_preview,
    )
    response = _client(repository).post(
        "/api/v1/automation/atomic-market-snapshot-candidates/authorize",
        json={
            "confirm_atomic_final_market_snapshot_binding": True,
            "confirm_one_no_http_transport_readiness_sequence": True,
            "confirm_one_no_retry_eight_category_cycle": True,
            "confirm_single_preview": True,
            "confirm_conditional_identical_single_child_create": True,
            "confirm_btc_usdc_test_portfolio_scope": True,
            "confirm_both_notionals_strictly_below_3_10": True,
            "confirm_unknown_consumes_applicable_allowance": True,
            "reason": "Require exact atomic route admission",
        },
        headers=_headers(
            operator_intent=(
                "authorize_automation_atomic_market_snapshot_candidate"
            )
        ),
    )

    assert response.status_code == 503
    assert admitted_routes == [
        ("POST", OPERATOR_MVP_AUTOMATION_ATOMIC_MARKET_SNAPSHOT_ROUTE)
    ]
    assert repository.calls == []


def test_atomic_market_snapshot_control_actionability_requires_ledger_and_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        operator_automation_routes,
        "_operator_automation_live_action_ready",
        lambda action: action == "AUTHORIZE_ATOMIC_MARKET_SNAPSHOT",
    )
    actor = AdminApiActor(actor_id="trader", roles=["trader"])
    available = AutomationControlPlaneItem.model_validate(
        {
            **_control(),
            "atomic_market_snapshot_authorization_allowed": True,
        }
    )
    exhausted = available.model_copy(
        update={"atomic_market_snapshot_authorization_allowed": False}
    )

    assert operator_automation_routes._scope_control_item(
        available, actor
    ).atomic_market_snapshot_authorization_allowed is True
    assert operator_automation_routes._scope_control_item(
        exhausted, actor
    ).atomic_market_snapshot_authorization_allowed is False


@pytest.mark.parametrize(
    ("action", "intent", "expected_state"),
    [
        ("enable", "enable_automation_definition", "ENABLED"),
        ("disable", "disable_automation_definition", "DISABLED"),
        ("pause", "pause_automation_definition", "PAUSED"),
        ("resume", "resume_automation_definition", "ENABLED"),
        ("drain", "drain_automation_definition", "DRAINING"),
    ],
)
def test_definition_lifecycle_routes_are_explicit_local_mutations(
    action: str,
    intent: str,
    expected_state: str,
):
    repository = _FakeRepository()
    response = _client(repository).post(
        f"/api/v1/automation/definitions/{DEFINITION_ID}/{action}",
        json={"reason": f"Explicit {action} review"},
        headers=_headers(operator_intent=intent),
    )
    assert response.status_code == 200
    assert response.json()["definition"]["lifecycle_state"] == expected_state
    assert response.json()["activity"]["coinbase_api_call_count"] == 0


def test_schedule_set_and_clear_are_separate_from_run_claim():
    repository = _FakeRepository()
    client = _client(repository)
    scheduled = client.post(
        f"/api/v1/automation/definitions/{DEFINITION_ID}/schedule",
        json={"mode": "INTERVAL_REVIEW_ONLY", "interval_minutes": 60},
        headers=_headers(operator_intent="set_automation_definition_schedule"),
    )
    cleared = client.post(
        f"/api/v1/automation/definitions/{DEFINITION_ID}/schedule/clear",
        json={"reason": "Return to manual-only review"},
        headers=_headers(operator_intent="clear_automation_definition_schedule"),
    )
    assert scheduled.status_code == 200
    assert scheduled.json()["definition"]["schedule"]["mode"] == "INTERVAL_REVIEW_ONLY"
    assert cleared.status_code == 200
    assert cleared.json()["definition"]["schedule"]["mode"] == "MANUAL_ONLY"
    assert [call[0] for call in repository.calls] == [
        "set_schedule",
        "clear_schedule",
    ]


@pytest.mark.parametrize("action", ["pause", "resume", "drain", "shutdown"])
def test_control_posture_routes_never_report_worker_or_exchange_activity(action: str):
    repository = _FakeRepository()
    response = _client(repository).post(
        f"/api/v1/automation/control-plane/{action}",
        json={"reason": f"Explicit automation {action}"},
        headers=_headers(operator_intent=f"{action}_automation_control_plane"),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["control_plane"]["recurring_worker_started"] is False
    assert payload["control_plane"]["live_scheduler_enabled"] is False
    assert payload["activity"]["exchange_mutation_count"] == 0


def test_one_shot_run_is_explicit_blocked_and_never_becomes_live_authority():
    repository = _FakeRepository()
    response = _client(repository).post(
        f"/api/v1/automation/definitions/{DEFINITION_ID}/runs",
        json={"confirm_one_shot": True, "reason": "Explicit one-shot review"},
        headers=_headers(operator_intent="claim_automation_one_shot_run"),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["state"] == "BLOCKED"
    assert payload["run"]["live_attempt_consumed"] is False
    assert payload["run"]["create_call_count"] == 0
    assert payload["run"]["cancel_call_count"] == 0
    assert payload["activity"]["coinbase_api_call_count"] == 0


def _install_authorize_single_child_probe(
    monkeypatch: pytest.MonkeyPatch,
    repository: _FakeRepository,
) -> None:
    monkeypatch.setattr(
        operator_automation_routes,
        "_operator_automation_live_action_ready",
        lambda _action: True,
    )

    def authorize_single_child(
        _service: OperatorAutomationService,
        *,
        run_id: str,
        request: Any,
        context: Any,
    ) -> AutomationRunMutationResponse:
        repository._record(
            "authorize_single_child",
            run_id=run_id,
            request=request,
            context=context,
        )
        return AutomationRunMutationResponse(
            run=AutomationRunItem.model_validate(_run()),
            audit_id=AUDIT_ID,
            correlation_id=context.correlation_id,
        )

    monkeypatch.setattr(
        OperatorAutomationService,
        "authorize_single_child",
        authorize_single_child,
        raising=False,
    )


def _authorize_single_child_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "confirm_single_child_create": True,
        "confirm_final_eligibility_refresh": True,
        "confirm_account_wide_active_spot_order_catalog_read": True,
        "confirm_unknown_consumes_allowance": True,
        "expected_plan_sha256": "a" * 64,
        "reason": "Authorize this exact prepared child",
    }
    body.update(overrides)
    return body


def _authorize_preview_gated_single_child_body(
    **overrides: Any,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "confirm_single_preview": True,
        "confirm_conditional_single_child_create": True,
        "confirm_final_eligibility_refresh": True,
        "confirm_account_wide_active_spot_order_catalog_read": True,
        "confirm_preview_unknown_consumes_allowance": True,
        "confirm_create_unknown_consumes_allowance": True,
        "expected_plan_sha256": "a" * 64,
        "reason": "Preview then conditionally create this exact candidate",
    }
    body.update(overrides)
    return body


def _install_authorize_preview_gated_probe(
    monkeypatch: pytest.MonkeyPatch,
    repository: _FakeRepository,
) -> None:
    monkeypatch.setattr(
        operator_automation_routes,
        "_operator_automation_live_action_ready",
        lambda _action: True,
    )

    def authorize_preview_gated_single_child(
        _service: OperatorAutomationService,
        *,
        run_id: str,
        request: Any,
        context: Any,
    ) -> AutomationRunMutationResponse:
        repository._record(
            "authorize_preview_gated_single_child",
            run_id=run_id,
            request=request,
            context=context,
        )
        return AutomationRunMutationResponse(
            run=AutomationRunItem.model_validate(_run()),
            audit_id=AUDIT_ID,
            correlation_id=context.correlation_id,
        )

    monkeypatch.setattr(
        OperatorAutomationService,
        "authorize_preview_gated_single_child",
        authorize_preview_gated_single_child,
        raising=False,
    )


def _install_refresh_eligibility_probe(
    monkeypatch: pytest.MonkeyPatch,
    repository: _FakeRepository,
) -> None:
    monkeypatch.setattr(
        operator_automation_routes,
        "_operator_automation_live_action_ready",
        lambda _action: True,
    )

    def refresh_spot_eligibility(
        _service: OperatorAutomationService,
        *,
        run_id: str,
        request: Any,
        context: Any,
    ) -> AutomationEligibilityCycleMutationResponse:
        repository._record(
            "refresh_spot_eligibility",
            run_id=run_id,
            request=request,
            context=context,
        )
        return AutomationEligibilityCycleMutationResponse(
            run=AutomationRunItem.model_validate(
                _source_gated_single_child_run()
            ),
            audit_id=AUDIT_ID,
            correlation_id=context.correlation_id,
            activity=AutomationEligibilityRefreshActivity(
                coinbase_api_call_count=3,
                call_count_exact=True,
            ),
        )

    monkeypatch.setattr(
        OperatorAutomationService,
        "refresh_spot_eligibility",
        refresh_spot_eligibility,
        raising=False,
    )


def _refresh_eligibility_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "confirm_approved_eligibility_reads": True,
        "confirm_account_wide_active_spot_order_catalog_read": True,
        "confirm_unknown_consumes_cycle": True,
        "expected_plan_sha256": "a" * 64,
        "reason": "Refresh this exact source-gated run",
    }
    body.update(overrides)
    return body


def test_refresh_spot_eligibility_route_binds_exact_run_request_and_context(
    monkeypatch: pytest.MonkeyPatch,
):
    repository = _FakeRepository()
    _install_refresh_eligibility_probe(monkeypatch, repository)

    response = _client(repository).post(
        f"/api/v1/automation/runs/{RUN_ID}/eligibility-cycles",
        json=_refresh_eligibility_body(),
        headers=_headers(
            roles="trader",
            operator_intent="refresh_automation_spot_eligibility",
            idempotency_key="automation-eligibility-cycle-1",
        ),
    )

    assert response.status_code == 200
    assert response.headers["X-Correlation-Id"] == (
        "automation-route-correlation"
    )
    payload = response.json()
    assert payload["type"] == "automation_eligibility_cycle_mutation"
    assert payload["run"]["live_execution_available"] is False
    assert payload["activity"] == {
        "coinbase_api_call_count": 3,
        "exchange_mutation_count": 0,
        "create_call_count": 0,
        "cancel_call_count": 0,
        "call_count_exact": True,
        "recurring_worker_started": False,
    }
    name, call = repository.calls[-1]
    assert name == "refresh_spot_eligibility"
    assert call["run_id"] == RUN_ID
    assert call["request"].model_dump(mode="json") == (
        _refresh_eligibility_body()
    )
    assert call["context"].idempotency_key == "automation-eligibility-cycle-1"
    assert call["context"].operator_intent == (
        "refresh_automation_spot_eligibility"
    )


def test_refresh_spot_eligibility_requires_exact_three_read_permissions(
    monkeypatch: pytest.MonkeyPatch,
):
    repository = _FakeRepository()
    _install_refresh_eligibility_probe(monkeypatch, repository)
    permission_checks: list[AdminApiPermission] = []

    def require_all_permissions(
        _actor: Any,
        permission: AdminApiPermission,
    ) -> None:
        permission_checks.append(permission)
        if permission is AdminApiPermission.ACCOUNT_REALITY_REFRESH:
            raise HTTPException(status_code=403, detail="forbidden")

    monkeypatch.setattr(
        operator_automation_routes,
        "require_permission",
        require_all_permissions,
    )

    response = _client(repository).post(
        f"/api/v1/automation/runs/{RUN_ID}/eligibility-cycles",
        json=_refresh_eligibility_body(),
        headers=_headers(
            roles="trader",
            operator_intent="refresh_automation_spot_eligibility",
        ),
    )

    assert response.status_code == 403
    assert permission_checks == [
        AdminApiPermission.AUTOMATION_TRIGGER,
        AdminApiPermission.AUTOMATION_RESUME,
        AdminApiPermission.ACCOUNT_REALITY_REFRESH,
    ]
    assert repository.calls == []


@pytest.mark.parametrize(
    ("query", "body", "intent"),
    [
        (
            {"retry": "true"},
            _refresh_eligibility_body(),
            "refresh_automation_spot_eligibility",
        ),
        (
            {},
            _refresh_eligibility_body(product_id="BTC-USDC"),
            "refresh_automation_spot_eligibility",
        ),
        (
            {},
            {
                key: value
                for key, value in _refresh_eligibility_body().items()
                if key
                != "confirm_account_wide_active_spot_order_catalog_read"
            },
            "refresh_automation_spot_eligibility",
        ),
        ({}, _refresh_eligibility_body(), "claim_automation_one_shot_run"),
    ],
)
def test_refresh_spot_eligibility_rejects_query_body_or_intent_broadening(
    monkeypatch: pytest.MonkeyPatch,
    query: dict[str, str],
    body: dict[str, Any],
    intent: str,
):
    repository = _FakeRepository()
    _install_refresh_eligibility_probe(monkeypatch, repository)

    response = _client(repository).post(
        f"/api/v1/automation/runs/{RUN_ID}/eligibility-cycles",
        params=query,
        json=body,
        headers=_headers(roles="trader", operator_intent=intent),
    )

    assert response.status_code == 422
    assert repository.calls == []


def test_authorize_single_child_route_binds_exact_run_request_and_context(
    monkeypatch: pytest.MonkeyPatch,
):
    repository = _FakeRepository()
    _install_authorize_single_child_probe(monkeypatch, repository)

    response = _client(repository).post(
        f"/api/v1/automation/runs/{RUN_ID}/authorize-single-child",
        json=_authorize_single_child_body(),
        headers=_headers(
            roles="trader",
            operator_intent=(
                "authorize_automation_single_child_create"
            ),
            idempotency_key="automation-single-child-authorization-1",
        ),
    )

    assert response.status_code == 200
    assert response.headers["X-Correlation-Id"] == "automation-route-correlation"
    assert response.json()["type"] == "automation_run_mutation"
    assert len(repository.calls) == 1
    name, call = repository.calls[0]
    assert name == "authorize_single_child"
    assert call["run_id"] == RUN_ID
    assert call["request"].model_dump(mode="json") == (
        _authorize_single_child_body()
    )
    assert call["context"].actor_id == "operator-automation-route-test"
    assert call["context"].idempotency_key == (
        "automation-single-child-authorization-1"
    )
    assert call["context"].operator_intent == (
        "authorize_automation_single_child_create"
    )


def test_preview_gated_route_binds_distinct_acknowledgements_and_context(
    monkeypatch: pytest.MonkeyPatch,
):
    repository = _FakeRepository()
    _install_authorize_preview_gated_probe(monkeypatch, repository)

    response = _client(repository).post(
        f"/api/v1/automation/runs/{RUN_ID}/"
        "authorize-preview-gated-single-child",
        json=_authorize_preview_gated_single_child_body(),
        headers=_headers(
            roles="trader",
            operator_intent=(
                "authorize_automation_preview_gated_single_child"
            ),
            idempotency_key="automation-preview-gated-authorization-1",
        ),
    )

    assert response.status_code == 200
    assert len(repository.calls) == 1
    name, call = repository.calls[0]
    assert name == "authorize_preview_gated_single_child"
    assert call["run_id"] == RUN_ID
    assert call["request"].model_dump(mode="json") == (
        _authorize_preview_gated_single_child_body()
    )
    assert call["context"].idempotency_key == (
        "automation-preview-gated-authorization-1"
    )
    assert call["context"].operator_intent == (
        "authorize_automation_preview_gated_single_child"
    )


def test_authorize_single_child_requires_refresh_and_create_before_service(
    monkeypatch: pytest.MonkeyPatch,
):
    repository = _FakeRepository()
    _install_authorize_single_child_probe(monkeypatch, repository)
    permission_checks: list[AdminApiPermission] = []

    def require_all_permissions(
        _actor: Any,
        permission: AdminApiPermission,
    ) -> None:
        permission_checks.append(permission)
        if permission is AdminApiPermission.ORDER_CREATE:
            raise HTTPException(status_code=403, detail="forbidden")

    monkeypatch.setattr(
        operator_automation_routes,
        "require_permission",
        require_all_permissions,
    )

    response = _client(repository).post(
        f"/api/v1/automation/runs/{RUN_ID}/authorize-single-child",
        json=_authorize_single_child_body(),
        headers=_headers(
            roles="trader",
            operator_intent=(
                "authorize_automation_single_child_create"
            ),
        ),
    )

    assert response.status_code == 403
    assert permission_checks == [
        AdminApiPermission.AUTOMATION_TRIGGER,
        AdminApiPermission.AUTOMATION_RESUME,
        AdminApiPermission.ACCOUNT_REALITY_REFRESH,
        AdminApiPermission.ORDER_CREATE,
    ]
    assert repository.calls == []


@pytest.mark.parametrize(
    ("query", "body", "intent"),
    [
        ({"refresh": "true"}, _authorize_single_child_body(), (
            "authorize_automation_single_child_create"
        )),
        ({}, _authorize_single_child_body(product_id="BTC-USDC"), (
            "authorize_automation_single_child_create"
        )),
        ({}, {
            **_authorize_single_child_body(),
            "confirm_exact_child_safe_closeout_cancel": True,
        }, "authorize_automation_single_child_create"),
        ({}, _authorize_single_child_body(), "claim_automation_one_shot_run"),
    ],
)
def test_authorize_single_child_rejects_query_body_or_intent_broadening(
    monkeypatch: pytest.MonkeyPatch,
    query: dict[str, str],
    body: dict[str, Any],
    intent: str,
):
    repository = _FakeRepository()
    _install_authorize_single_child_probe(monkeypatch, repository)

    response = _client(repository).post(
        f"/api/v1/automation/runs/{RUN_ID}/authorize-single-child",
        params=query,
        json=body,
        headers=_headers(roles="trader", operator_intent=intent),
    )

    assert response.status_code == 422
    assert repository.calls == []


def _safe_closeout_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "confirm_exact_child_safe_closeout_cancel": True,
        "confirm_unknown_consumes_allowance": True,
        "expected_plan_sha256": "a" * 64,
        "reason": "Safely close out this exact child",
    }
    body.update(overrides)
    return body


def _install_safe_closeout_probe(
    monkeypatch: pytest.MonkeyPatch,
    repository: _FakeRepository,
) -> None:
    monkeypatch.setattr(
        operator_automation_routes,
        "_operator_automation_live_action_ready",
        lambda _action: True,
    )

    def invoke(
        _service: OperatorAutomationService,
        *,
        run_id: str,
        request: Any,
        context: Any,
    ) -> AutomationRunMutationResponse:
        repository._record(
            "safe_closeout_single_child",
            run_id=run_id,
            request=request,
            context=context,
        )
        return AutomationRunMutationResponse(
            run=AutomationRunItem.model_validate(_run()),
            audit_id=AUDIT_ID,
            correlation_id=context.correlation_id,
        )

    monkeypatch.setattr(
        OperatorAutomationService,
        "safe_closeout_single_child",
        invoke,
        raising=False,
    )


@pytest.mark.parametrize(
    ("path", "body", "operator_intent"),
    [
        (
            f"/api/v1/automation/runs/{RUN_ID}/eligibility-cycles",
            _refresh_eligibility_body(),
            "refresh_automation_spot_eligibility",
        ),
        (
            f"/api/v1/automation/runs/{RUN_ID}/authorize-single-child",
            _authorize_single_child_body(),
            "authorize_automation_single_child_create",
        ),
        (
            f"/api/v1/automation/runs/{RUN_ID}/safe-closeout-child",
            _safe_closeout_body(),
            "safe_closeout_automation_single_child",
        ),
    ],
)
def test_no_live_runtime_blocks_before_automation_service_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    body: dict[str, Any],
    operator_intent: str,
):
    repository = _FakeRepository()
    _install_refresh_eligibility_probe(monkeypatch, repository)
    _install_authorize_single_child_probe(monkeypatch, repository)
    _install_safe_closeout_probe(monkeypatch, repository)
    monkeypatch.setattr(
        operator_automation_routes,
        "_operator_automation_live_action_ready",
        lambda _action: False,
    )

    response = _client(repository).post(
        path,
        json=body,
        headers=_headers(
            roles="trader",
            operator_intent=operator_intent,
            idempotency_key="automation-no-live-runtime-block",
        ),
    )

    assert response.status_code == 503
    assert response.json()["message"] == (
        "operator_automation_action_runtime_unavailable"
    )
    assert repository.calls == []


def test_safe_closeout_route_binds_exact_run_request_and_context(
    monkeypatch: pytest.MonkeyPatch,
):
    repository = _FakeRepository()
    _install_safe_closeout_probe(monkeypatch, repository)

    response = _client(repository).post(
        f"/api/v1/automation/runs/{RUN_ID}/safe-closeout-child",
        json=_safe_closeout_body(),
        headers=_headers(
            roles="trader",
            operator_intent="safe_closeout_automation_single_child",
            idempotency_key="automation-safe-closeout-child-1",
        ),
    )

    assert response.status_code == 200
    name, call = repository.calls[-1]
    assert name == "safe_closeout_single_child"
    assert call["run_id"] == RUN_ID
    assert call["request"].model_dump(mode="json") == (
        _safe_closeout_body()
    )
    assert call["context"].operator_intent == (
        "safe_closeout_automation_single_child"
    )


def test_safe_closeout_route_requires_trigger_and_cancel_before_service(
    monkeypatch: pytest.MonkeyPatch,
):
    repository = _FakeRepository()
    _install_safe_closeout_probe(monkeypatch, repository)
    permission_checks: list[AdminApiPermission] = []

    def require_all_permissions(
        _actor: Any,
        permission: AdminApiPermission,
    ) -> None:
        permission_checks.append(permission)
        if permission is AdminApiPermission.ORDER_CANCEL:
            raise HTTPException(status_code=403, detail="forbidden")

    monkeypatch.setattr(
        operator_automation_routes,
        "require_permission",
        require_all_permissions,
    )
    response = _client(repository).post(
        f"/api/v1/automation/runs/{RUN_ID}/safe-closeout-child",
        json=_safe_closeout_body(),
        headers=_headers(
            roles="trader",
            operator_intent="safe_closeout_automation_single_child",
        ),
    )

    assert response.status_code == 403
    assert permission_checks == [
        AdminApiPermission.AUTOMATION_TRIGGER,
        AdminApiPermission.ORDER_CANCEL,
    ]
    assert repository.calls == []


def test_safe_closeout_route_rejects_browser_identity_or_query_broadening(
    monkeypatch: pytest.MonkeyPatch,
):
    repository = _FakeRepository()
    _install_safe_closeout_probe(monkeypatch, repository)
    response = _client(repository).post(
        f"/api/v1/automation/runs/{RUN_ID}/safe-closeout-child",
        params={"retry": "true"},
        json=_safe_closeout_body(client_order_id=RUN_ID),
        headers=_headers(
            roles="trader",
            operator_intent="safe_closeout_automation_single_child",
        ),
    )

    assert response.status_code == 422
    assert repository.calls == []


def test_exact_replay_header_and_payload_conflict_are_mapped_without_retry():
    repository = _FakeRepository(replayed=True)
    client = _client(repository)
    replay = client.post(
        "/api/v1/automation/definitions",
        json={
            "display_name": "Bounded Spot sweep",
            "job_kind": "SPOT_SWEEP",
            "product_ids": ["BTC-USDC"],
        },
        headers=_headers(operator_intent="create_automation_definition"),
    )
    assert replay.status_code == 200
    assert replay.headers["X-Idempotency-Replayed"] == "true"
    assert replay.json()["replayed"] is True

    repository.replayed = False
    repository.error = AutomationRepositoryConflict(
        "automation_idempotency_payload_conflict"
    )
    conflict = client.post(
        "/api/v1/automation/definitions",
        json={
            "display_name": "Changed Spot sweep",
            "job_kind": "SPOT_SWEEP",
            "product_ids": ["BTC-USDC"],
        },
        headers=_headers(operator_intent="create_automation_definition"),
    )
    assert conflict.status_code == 409
    assert conflict.json()["message"] == "automation_idempotency_payload_conflict"
    assert "withheld" not in conflict.text


def test_repository_exception_text_is_withheld_by_fixed_diagnostic():
    repository = _FakeRepository(error=RuntimeError("withheld-private-database-value"))
    response = _client(repository).get(
        "/api/v1/automation/control-plane",
        headers=_headers(),
    )
    assert response.status_code == 503
    assert response.json()["message"] == "automation_control_plane_unavailable"
    assert "withheld-private-database-value" not in response.text


def test_app_openapi_and_inventory_expose_only_local_control_plane_actions():
    paths = _ADMIN_API_APP.openapi()["paths"]
    expected = {
        "/api/v1/automation/control-plane",
        "/api/v1/automation/definitions",
        "/api/v1/automation/definitions/{definition_id}",
        "/api/v1/automation/definitions/{definition_id}/enable",
        "/api/v1/automation/definitions/{definition_id}/schedule",
        "/api/v1/automation/definitions/{definition_id}/runs",
        "/api/v1/automation/runs",
        "/api/v1/automation/runs/{run_id}",
        "/api/v1/automation/runs/{run_id}/eligibility-cycles",
        "/api/v1/automation/runs/{run_id}/authorize-single-child",
        "/api/v1/automation/runs/{run_id}/safe-closeout-child",
        "/api/v1/automation/runs/{run_id}/events",
    }
    assert expected <= set(paths)
    operation_ids = {
        (method.upper(), path): operation["operationId"]
        for path, path_item in paths.items()
        if path.startswith("/api/v1/automation/")
        for method, operation in path_item.items()
        if method in {"get", "post"}
    }
    expected_operation_ids = {
        ("GET", "/api/v1/automation/control-plane"): (
            "get_operator_automation_control_plane"
        ),
        ("GET", "/api/v1/automation/definitions"): (
            "list_operator_automation_definitions"
        ),
        ("POST", "/api/v1/automation/definitions"): (
            "create_operator_automation_definition"
        ),
        ("GET", "/api/v1/automation/definitions/{definition_id}"): (
            "get_operator_automation_definition"
        ),
        ("POST", "/api/v1/automation/definitions/{definition_id}/enable"): (
            "enable_operator_automation_definition"
        ),
        ("POST", "/api/v1/automation/definitions/{definition_id}/disable"): (
            "disable_operator_automation_definition"
        ),
        ("POST", "/api/v1/automation/definitions/{definition_id}/pause"): (
            "pause_operator_automation_definition"
        ),
        ("POST", "/api/v1/automation/definitions/{definition_id}/resume"): (
            "resume_operator_automation_definition"
        ),
        ("POST", "/api/v1/automation/definitions/{definition_id}/drain"): (
            "drain_operator_automation_definition"
        ),
        ("POST", "/api/v1/automation/definitions/{definition_id}/schedule"): (
            "set_operator_automation_definition_schedule"
        ),
        (
            "POST",
            "/api/v1/automation/definitions/{definition_id}/schedule/clear",
        ): "clear_operator_automation_definition_schedule",
        ("POST", "/api/v1/automation/control-plane/pause"): (
            "pause_operator_automation_control_plane"
        ),
        ("POST", "/api/v1/automation/control-plane/resume"): (
            "resume_operator_automation_control_plane"
        ),
        ("POST", "/api/v1/automation/control-plane/drain"): (
            "drain_operator_automation_control_plane"
        ),
        ("POST", "/api/v1/automation/control-plane/shutdown"): (
            "shutdown_operator_automation_control_plane"
        ),
        ("POST", "/api/v1/automation/definitions/{definition_id}/runs"): (
            "claim_operator_automation_one_shot_run"
        ),
        ("GET", "/api/v1/automation/runs"): "list_operator_automation_runs",
        ("GET", "/api/v1/automation/runs/{run_id}"): (
            "get_operator_automation_run"
        ),
        (
            "POST",
            "/api/v1/automation/runs/{run_id}/eligibility-cycles",
        ): "refresh_operator_automation_spot_eligibility",
        (
            "POST",
            "/api/v1/automation/runs/{run_id}/authorize-single-child",
        ): "authorize_operator_automation_single_child",
        (
            "POST",
            "/api/v1/automation/runs/{run_id}/safe-closeout-child",
        ): "safe_closeout_operator_automation_single_child",
        ("GET", "/api/v1/automation/runs/{run_id}/events"): (
            "list_operator_automation_run_events"
        ),
    }
    assert {
        key: operation_ids[key]
        for key in expected_operation_ids
    } == expected_operation_ids
    inventory = {
        row.surface: row
        for row in ADMIN_API_ROUTE_INVENTORY
        if row.module_id == "automation_control_plane"
    }
    assert "GET /api/v1/automation/definitions" in inventory
    assert inventory["GET /api/v1/automation/definitions"].permission == (
        AdminApiPermission.AUTOMATION_READ
    )
    assert inventory[
        "POST /api/v1/automation/definitions/{definition_id}/runs"
    ].permission == AdminApiPermission.AUTOMATION_TRIGGER
    assert inventory[
        "POST /api/v1/automation/runs/{run_id}/eligibility-cycles"
    ].permission == AdminApiPermission.ACCOUNT_REALITY_REFRESH
    assert inventory[
        "POST /api/v1/automation/runs/{run_id}/authorize-single-child"
    ].permission == AdminApiPermission.ORDER_CREATE
    assert inventory[
        "POST /api/v1/automation/runs/{run_id}/safe-closeout-child"
    ].permission == AdminApiPermission.ORDER_CANCEL
    assert all("Coinbase call" in row.parity_test for row in inventory.values())
