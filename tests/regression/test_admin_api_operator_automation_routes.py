"""Authenticated, local-only Admin API routes for operator automation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

import pytest
from fastapi.testclient import TestClient

from api.v1.app import app as _ADMIN_API_APP
from api.v1.routes import operator_automation as operator_automation_routes
from application.admin_api.automation_models import (
    AutomationControlAction,
    AutomationDefinitionLifecycleAction,
)
from application.admin_api.operator_automation import (
    AutomationRepositoryConflict,
    AutomationRepositoryMutation,
    AutomationRepositoryPage,
    OperatorAutomationService,
)
from application.admin_api.route_inventory import ADMIN_API_ROUTE_INVENTORY
from core.enums import AdminApiPermission


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
        "client_order_id": None,
        "audit_id": AUDIT_ID,
        "correlation_id": "automation-route-correlation",
        "claimed_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
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
    ("roles", "can_create", "control_actions", "definition_actions"),
    [
        ("viewer", False, [], []),
        (
            "operator",
            True,
            ["PAUSE", "DRAIN", "SHUTDOWN"],
            ["ENABLE", "DISABLE", "SET_SCHEDULE"],
        ),
        (
            "trader",
            True,
            ["PAUSE", "DRAIN", "SHUTDOWN"],
            ["ENABLE", "DISABLE", "SET_SCHEDULE", "RUN_ONCE"],
        ),
        ("emergency", False, ["PAUSE", "DRAIN", "SHUTDOWN"], []),
    ],
)
def test_readback_actions_are_scoped_by_backend_rbac(
    roles: str,
    can_create: bool,
    control_actions: list[str],
    definition_actions: list[str],
):
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
    assert control.json()["control_plane"]["allowed_actions"] == control_actions
    assert definitions.status_code == 200
    assert definitions.json()["items"][0]["allowed_actions"] == definition_actions


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
    assert all("Coinbase call" in row.parity_test for row in inventory.values())
