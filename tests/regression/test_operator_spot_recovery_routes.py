from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from api.v1.app import app as _APP
from api.v1.routes import orders as order_routes
from api.v1.routes import operator_spot_recovery as recovery_routes
from application.admin_api.audit import FileAdminApiAuditStore
from application.admin_api.idempotency import FileIdempotencyStore
from application.admin_api.models import (
    AdminApiActor,
    AdminApiCommandResponse,
    AdminApiRole,
    CancelOrderRequest,
)
from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiPermission,
    SpotRecoveryCaseState,
)


pytestmark = [pytest.mark.regression, pytest.mark.serial]

CASE_ID = "0d756620-2ce5-4fd3-a24a-a14c4d8bf3c1"
CLIENT_ORDER_ID = "8f1bf38c-90ad-4a7c-90fb-87cb56c72a80"


def _case(*, state: str = "OPEN", revision: int = 1) -> dict[str, Any]:
    return {
        "case_id": CASE_ID,
        "goal_id": "operator_spot_recovery_execution_ui_v1",
        "goal_refresh_cycles_used": 0 if revision == 1 else 1,
        "goal_cancel_outcome": "NOT_RUN",
        "client_order_id": CLIENT_ORDER_ID,
        "product_id": "BTC-USDC",
        "portfolio_id_sha256": "a" * 64,
        "state": state,
        "revision": revision,
        "refresh_count": 0 if revision == 1 else 1,
        "order_read_logical_count": 0 if revision == 1 else 1,
        "fill_read_logical_count": 0 if revision == 1 else 1,
        "cancel_call_count": 0,
        "cancel_allowance_consumed": False,
        "plan_kind": None,
        "plan_sha256": None,
        "plan": None,
        "pre_apply_status": None,
        "applied_status": None,
        "diagnostic_code": "recovery_case_created",
        "created_by": "route-operator",
        "correlation_id": "recovery-correlation",
        "created_at": "2026-07-23T08:00:00+00:00",
        "updated_at": "2026-07-23T08:00:00+00:00",
    }


@dataclass
class _FakeRepository:
    events: list[dict[str, Any]] = field(default_factory=list)

    def list_events(self, case_id: str, *, limit: int = 100):
        assert case_id == CASE_ID
        assert limit == 100
        return list(self.events)


@dataclass
class _FakeService:
    repository: _FakeRepository = field(default_factory=_FakeRepository)
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def list_cases(self, *, limit: int, offset: int):
        self.calls.append(("list_cases", {"limit": limit, "offset": offset}))
        return [_case()], 1

    def portfolio_binding_verified(self, case: dict[str, Any]) -> bool:
        return case.get("portfolio_id_sha256") == "a" * 64

    def get_case(self, case_id: str):
        self.calls.append(("get_case", {"case_id": case_id}))
        return _case()

    def create_case(self, **kwargs):
        self.calls.append(("create_case", kwargs))
        return _case()

    def refresh_case(self, **kwargs):
        self.calls.append(("refresh_case", kwargs))
        return {
            **_case(state=SpotRecoveryCaseState.PLAN_READY.value, revision=3),
            "diagnostic_code": "recovery_plan_ready",
            "plan_kind": "SET_LOCAL_STATUS",
            "plan_sha256": "b" * 64,
            "plan": {
                "kind": "SET_LOCAL_STATUS",
                "client_order_id": CLIENT_ORDER_ID,
                "product_id": "BTC-USDC",
                "from_status": "OPEN",
                "to_status": "FILLED",
                "fill_count": 1,
                "apply_available": True,
                "cancel_available": False,
                "rollback_after_apply_available": False,
                "blockers": [],
                "plan_sha256": "b" * 64,
            },
        }

    def apply_case(self, **kwargs):
        self.calls.append(("apply_case", kwargs))
        return {
            **self.refresh_case(
                case_id=CASE_ID,
                expected_revision=2,
                actor_id="route-operator",
                correlation_id="recovery-correlation",
                manual_live_acknowledgement=True,
            ),
            "state": "APPLIED",
            "revision": 4,
            "diagnostic_code": "recovery_plan_applied",
        }

    def rollback_case(self, **kwargs):
        self.calls.append(("rollback_case", kwargs))
        return {
            **self.apply_case(
                case_id=CASE_ID,
                expected_revision=3,
                actor_id="route-operator",
                operator_reason="reason",
                correlation_id="recovery-correlation",
                operator_acknowledgement=True,
            ),
            "state": "ROLLED_BACK",
            "revision": 5,
            "diagnostic_code": "recovery_plan_rolled_back",
        }


@pytest.fixture
def route_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, _FakeService]:
    monkeypatch.setenv("COINBASE_ADMIN_API_AUTH_MODE", "bootstrap_bearer")
    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "local-admin-token")
    service = _FakeService()
    idempotency_store = FileIdempotencyStore(
        tmp_path / "recovery-idempotency.jsonl"
    )
    audit_store = FileAdminApiAuditStore(tmp_path / "recovery-audit.jsonl")
    _APP.dependency_overrides[
        recovery_routes.get_operator_spot_recovery_service
    ] = lambda: service
    _APP.dependency_overrides[
        recovery_routes.get_idempotency_store
    ] = lambda: idempotency_store
    _APP.dependency_overrides[
        recovery_routes.get_audit_store
    ] = lambda: audit_store
    with TestClient(_APP) as client:
        yield client, service
    _APP.dependency_overrides.pop(
        recovery_routes.get_operator_spot_recovery_service,
        None,
    )
    _APP.dependency_overrides.pop(recovery_routes.get_idempotency_store, None)
    _APP.dependency_overrides.pop(recovery_routes.get_audit_store, None)


def _headers(
    *,
    key: str = "recovery-idempotency-1",
    intent: str,
) -> dict[str, str]:
    return {
        "Authorization": "Bearer local-admin-token",
        "X-Admin-Actor": "route-operator",
        "X-Admin-Roles": "trader",
        "Idempotency-Key": key,
        "X-Correlation-Id": "recovery-correlation",
        "X-Operator-Intent": intent,
    }


def test_recovery_routes_are_authenticated_paginated_operator_workflows(
    route_client: tuple[TestClient, _FakeService],
) -> None:
    client, service = route_client
    response = client.get(
        "/api/v1/spot/recovery/cases?limit=25&offset=0",
        headers={
            "Authorization": "Bearer local-admin-token",
            "X-Admin-Actor": "route-operator",
            "X-Admin-Roles": "trader",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_count"] == 1
    assert payload["items"][0]["client_order_id"] == CLIENT_ORDER_ID
    assert payload["items"][0]["allowed_actions"] == ["REFRESH"]
    assert payload["live_coinbase_read_ran"] is False
    assert service.calls == [("list_cases", {"limit": 25, "offset": 0})]


def test_recovery_refresh_is_idempotent_and_reports_backend_read_activity(
    route_client: tuple[TestClient, _FakeService],
) -> None:
    client, service = route_client
    body = {
        "expected_revision": 1,
        "manual_live_acknowledgement": True,
    }
    first = client.post(
        f"/api/v1/spot/recovery/cases/{CASE_ID}/refresh",
        headers=_headers(intent="refresh_operator_spot_recovery_case"),
        json=body,
    )
    replay = client.post(
        f"/api/v1/spot/recovery/cases/{CASE_ID}/refresh",
        headers=_headers(intent="refresh_operator_spot_recovery_case"),
        json=body,
    )

    assert first.status_code == 200
    assert first.json()["case"]["state"] == "PLAN_READY"
    assert first.json()["live_coinbase_read_ran"] is True
    assert first.json()["live_coinbase_orders_ran"] is False
    assert replay.status_code == 200
    assert replay.headers["X-Idempotency-Replayed"] == "true"
    assert replay.json()["replayed"] is True
    assert [name for name, _kwargs in service.calls] == ["refresh_case"]


def test_recovery_create_apply_and_rollback_are_local_operator_actions(
    route_client: tuple[TestClient, _FakeService],
) -> None:
    client, _service = route_client
    created = client.post(
        "/api/v1/spot/recovery/cases",
        headers=_headers(
            key="recovery-create",
            intent="create_operator_spot_recovery_case",
        ),
        json={
            "client_order_id": CLIENT_ORDER_ID,
            "operator_reason": "review exact system-owned root",
        },
    )
    applied = client.post(
        f"/api/v1/spot/recovery/cases/{CASE_ID}/apply",
        headers=_headers(
            key="recovery-apply",
            intent="apply_operator_spot_recovery_case",
        ),
        json={
            "expected_revision": 3,
            "operator_reason": "apply reviewed repair",
            "operator_acknowledgement": True,
        },
    )
    rolled_back = client.post(
        f"/api/v1/spot/recovery/cases/{CASE_ID}/rollback",
        headers=_headers(
            key="recovery-rollback",
            intent="rollback_operator_spot_recovery_case",
        ),
        json={
            "expected_revision": 4,
            "operator_reason": "restore reviewed safe snapshot",
            "operator_acknowledgement": True,
        },
    )

    assert created.status_code == 200
    assert applied.status_code == 200
    assert applied.json()["live_coinbase_read_ran"] is False
    assert rolled_back.status_code == 200
    assert rolled_back.json()["case"]["state"] == "ROLLED_BACK"
    assert rolled_back.json()["live_exchange_submitted"] is False


@pytest.mark.parametrize(
    ("path", "body", "expected_service_method"),
    [
        (
            "/api/v1/spot/recovery/cases",
            {
                "client_order_id": CLIENT_ORDER_ID,
                "operator_reason": "review exact system-owned root",
            },
            "create_operator_spot_recovery_case",
        ),
        (
            f"/api/v1/spot/recovery/cases/{CASE_ID}/refresh",
            {
                "expected_revision": 1,
                "manual_live_acknowledgement": True,
            },
            "refresh_operator_spot_recovery_case",
        ),
        (
            f"/api/v1/spot/recovery/cases/{CASE_ID}/apply",
            {
                "expected_revision": 3,
                "operator_reason": "apply reviewed repair",
                "operator_acknowledgement": True,
            },
            "apply_operator_spot_recovery_case",
        ),
        (
            f"/api/v1/spot/recovery/cases/{CASE_ID}/rollback",
            {
                "expected_revision": 4,
                "operator_reason": "restore reviewed safe snapshot",
                "operator_acknowledgement": True,
            },
            "rollback_operator_spot_recovery_case",
        ),
    ],
)
def test_recovery_mutations_reject_wrong_operator_intent(
    route_client: tuple[TestClient, _FakeService],
    path: str,
    body: dict[str, Any],
    expected_service_method: str,
) -> None:
    client, service = route_client

    response = client.post(
        path,
        headers=_headers(
            key=f"wrong-intent-{expected_service_method}",
            intent="operator_spot_recovery",
        ),
        json=body,
    )

    assert response.status_code == 400
    assert response.json()["status"] == "rejected"
    assert response.json()["message"] == "recovery_operator_intent_invalid"
    assert response.json()["service_method"] == expected_service_method
    assert service.calls == []


def test_recovery_openapi_exposes_normal_operator_routes() -> None:
    paths = _APP.openapi()["paths"]
    expected = {
        "/api/v1/spot/recovery/cases",
        "/api/v1/spot/recovery/cases/{case_id}",
        "/api/v1/spot/recovery/cases/{case_id}/refresh",
        "/api/v1/spot/recovery/cases/{case_id}/apply",
        "/api/v1/spot/recovery/cases/{case_id}/rollback",
        "/api/v1/orders/{client_order_id}/cancel",
    }
    assert expected <= set(paths)


def test_canonical_cancel_route_binds_and_closes_recovery_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _RecoveryRepository:
        def __init__(self) -> None:
            self.events: list[tuple[str, dict[str, Any]]] = []

        def begin_cancel(self, **kwargs):
            self.events.append(("begin_cancel", kwargs))
            return {
                **_case(state="CANCEL_PENDING", revision=4),
                "plan_sha256": "b" * 64,
                "plan": {
                    "kind": "CANCEL_ACTIVE_ORPHAN",
                    "client_order_id": CLIENT_ORDER_ID,
                    "product_id": "BTC-USDC",
                    "from_status": "CANCELLED",
                },
            }

        def read_local_order(self, client_order_id: str):
            assert client_order_id == CLIENT_ORDER_ID
            return {"ownership_provenance": "ADMIN_MANUAL_ROOT"}

        def record_cancel_result(self, **kwargs):
            self.events.append(("record_cancel_result", kwargs))
            return {
                **_case(state="CANCELLED", revision=5),
                "cancel_call_count": 1,
                "cancel_allowance_consumed": True,
                "diagnostic_code": "recovery_cancel_confirmed",
            }

    class _CommandService:
        def __init__(self) -> None:
            self.evidence = None

        def cancel_order_by_client_order_id(
            self,
            command,
            *,
            recovery_ownership=None,
        ):
            assert command.allow_live_execution is True
            self.evidence = recovery_ownership
            return AdminApiCommandResponse(
                status=AdminApiCommandStatus.ACCEPTED,
                action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
                required_permission=AdminApiPermission.ORDER_CANCEL,
                service_method="cancel_order_by_client_order_id",
                message="recovery_cancel_confirmed",
                client_order_id=CLIENT_ORDER_ID,
                live_exchange_submitted=True,
                live_coinbase_orders_ran=True,
                live_coinbase_read_ran=True,
            )

    repository = _RecoveryRepository()
    command_service = _CommandService()

    def _execute(**kwargs):
        return kwargs["command_runner_with_admission"](
            SimpleNamespace(allowed=True)
        )

    monkeypatch.setattr(order_routes, "_execute_idempotent_command", _execute)
    response = order_routes.cancel_order_by_client_order_id(
        request=Request(
            {
                "type": "http",
                "method": "POST",
                "path": f"/api/v1/orders/{CLIENT_ORDER_ID}/cancel",
                "headers": [],
            }
        ),
        body=CancelOrderRequest(
            reason="cancel exact active orphan",
            manual_live_acknowledgement=True,
            recovery_case_id=CASE_ID,
            recovery_case_revision=3,
            recovery_plan_sha256="b" * 64,
        ),
        client_order_id=CLIENT_ORDER_ID,
        idempotency_key="recovery-cancel-key",
        correlation_id="recovery-cancel-correlation",
        operator_intent="cancel_exact_recovery_orphan",
        actor=AdminApiActor(
            actor_id="route-operator",
            roles=[AdminApiRole.TRADER],
        ),
        service=command_service,
        idempotency_store=SimpleNamespace(),
        audit_store=SimpleNamespace(),
        approval_store=SimpleNamespace(),
        cap_guard_store=SimpleNamespace(),
        reconciliation_store=SimpleNamespace(),
        live_execution_service=SimpleNamespace(),
        recovery_repository_factory=lambda: repository,
    )

    assert response.status is AdminApiCommandStatus.ACCEPTED
    assert command_service.evidence.case_id == CASE_ID
    assert response.data["recovery_case"]["state"] == "CANCELLED"
    assert [event for event, _data in repository.events] == [
        "begin_cancel",
        "record_cancel_result",
    ]
    assert repository.events[1][1]["outcome"] == "ACCEPTED"


@pytest.mark.parametrize(
    (
        "explicit_rejection",
        "failure_stage",
        "expected_outcome",
        "expected_diagnostic",
        "expected_state",
    ),
    [
        (
            True,
            "cancellation_rejected",
            "REJECTED",
            "recovery_cancel_explicitly_rejected",
            "BLOCKED",
        ),
        (
            False,
            "cancellation_unknown",
            "UNKNOWN",
            "recovery_cancel_outcome_unknown",
            "UNKNOWN",
        ),
    ],
)
def test_canonical_cancel_route_preserves_rejected_vs_unknown_outcome(
    monkeypatch: pytest.MonkeyPatch,
    explicit_rejection: bool,
    failure_stage: str,
    expected_outcome: str,
    expected_diagnostic: str,
    expected_state: str,
) -> None:
    class _RecoveryRepository:
        def __init__(self) -> None:
            self.events: list[tuple[str, dict[str, Any]]] = []

        def begin_cancel(self, **kwargs):
            self.events.append(("begin_cancel", kwargs))
            return {
                **_case(state="CANCEL_PENDING", revision=4),
                "plan_sha256": "b" * 64,
                "plan": {
                    "kind": "CANCEL_ACTIVE_ORPHAN",
                    "client_order_id": CLIENT_ORDER_ID,
                    "product_id": "BTC-USDC",
                    "from_status": "CANCELLED",
                },
            }

        def read_local_order(self, client_order_id: str):
            assert client_order_id == CLIENT_ORDER_ID
            return {"ownership_provenance": "ADMIN_MANUAL_ROOT"}

        def record_cancel_result(self, **kwargs):
            self.events.append(("record_cancel_result", kwargs))
            return {
                **_case(state=expected_state, revision=5),
                "cancel_call_count": 1,
                "cancel_allowance_consumed": True,
                "diagnostic_code": expected_diagnostic,
            }

    class _CommandService:
        def cancel_order_by_client_order_id(
            self,
            command,
            *,
            recovery_ownership=None,
        ):
            assert command.allow_live_execution is True
            assert recovery_ownership.case_id == CASE_ID
            return AdminApiCommandResponse(
                status=AdminApiCommandStatus.REJECTED,
                action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
                required_permission=AdminApiPermission.ORDER_CANCEL,
                service_method="cancel_order_by_client_order_id",
                message="fixed_cancel_result",
                client_order_id=CLIENT_ORDER_ID,
                live_exchange_submitted=True,
                live_coinbase_orders_ran=True,
                live_coinbase_read_ran=True,
                failure_stage=failure_stage,
                data={
                    "cancellation_readback": {
                        "canonical_cancel_explicitly_rejected": (
                            explicit_rejection
                        ),
                    }
                },
            )

    repository = _RecoveryRepository()

    def _execute(**kwargs):
        return kwargs["command_runner_with_admission"](
            SimpleNamespace(allowed=True)
        )

    monkeypatch.setattr(order_routes, "_execute_idempotent_command", _execute)
    response = order_routes.cancel_order_by_client_order_id(
        request=Request(
            {
                "type": "http",
                "method": "POST",
                "path": f"/api/v1/orders/{CLIENT_ORDER_ID}/cancel",
                "headers": [],
            }
        ),
        body=CancelOrderRequest(
            reason="cancel exact active orphan",
            manual_live_acknowledgement=True,
            recovery_case_id=CASE_ID,
            recovery_case_revision=3,
            recovery_plan_sha256="b" * 64,
        ),
        client_order_id=CLIENT_ORDER_ID,
        idempotency_key=f"recovery-cancel-{expected_outcome.lower()}-key",
        correlation_id=(
            f"recovery-cancel-{expected_outcome.lower()}-correlation"
        ),
        operator_intent="cancel_exact_recovery_orphan",
        actor=AdminApiActor(
            actor_id="route-operator",
            roles=[AdminApiRole.TRADER],
        ),
        service=_CommandService(),
        idempotency_store=SimpleNamespace(),
        audit_store=SimpleNamespace(),
        approval_store=SimpleNamespace(),
        cap_guard_store=SimpleNamespace(),
        reconciliation_store=SimpleNamespace(),
        live_execution_service=SimpleNamespace(),
        recovery_repository_factory=lambda: repository,
    )

    assert response.status is AdminApiCommandStatus.REJECTED
    assert response.data["recovery_case"]["state"] == expected_state
    result = repository.events[1][1]
    assert result["outcome"] == expected_outcome
    assert result["diagnostic_code"] == expected_diagnostic


def test_recovery_cancel_proof_pass_does_not_claim_or_consume_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _RecoveryRepository:
        def __init__(self) -> None:
            self.reads = 0

        def read_cancel_candidate(self, **kwargs):
            self.reads += 1
            return {
                **_case(state="PLAN_READY", revision=3),
                "plan_sha256": "b" * 64,
                "plan": {
                    "kind": "CANCEL_ACTIVE_ORPHAN",
                    "client_order_id": CLIENT_ORDER_ID,
                    "product_id": "BTC-USDC",
                    "from_status": "CANCELLED",
                },
            }

        def read_local_order(self, client_order_id: str):
            assert client_order_id == CLIENT_ORDER_ID
            return {"ownership_provenance": "ADMIN_MANUAL_ROOT"}

        def begin_cancel(self, **_kwargs):
            raise AssertionError("proof pass must not claim Cancel allowance")

    class _CommandService:
        def cancel_order_by_client_order_id(
            self,
            command,
            *,
            recovery_ownership=None,
        ):
            assert command.allow_live_execution is False
            assert recovery_ownership.case_revision == 3
            return AdminApiCommandResponse(
                status=AdminApiCommandStatus.NOT_IMPLEMENTED,
                action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
                required_permission=AdminApiPermission.ORDER_CANCEL,
                service_method="cancel_order_by_client_order_id",
                message="live_execution_requires_backend_admission",
                client_order_id=CLIENT_ORDER_ID,
                live_exchange_submitted=False,
                live_coinbase_orders_ran=False,
            )

    repository = _RecoveryRepository()

    def _execute(**kwargs):
        return kwargs["command_runner_with_admission"](
            SimpleNamespace(allowed=False)
        )

    monkeypatch.setattr(order_routes, "_execute_idempotent_command", _execute)
    response = order_routes.cancel_order_by_client_order_id(
        request=Request(
            {
                "type": "http",
                "method": "POST",
                "path": f"/api/v1/orders/{CLIENT_ORDER_ID}/cancel",
                "headers": [],
            }
        ),
        body=CancelOrderRequest(
            reason="review exact active orphan cancel",
            manual_live_acknowledgement=True,
            recovery_case_id=CASE_ID,
            recovery_case_revision=3,
            recovery_plan_sha256="b" * 64,
        ),
        client_order_id=CLIENT_ORDER_ID,
        idempotency_key="recovery-cancel-proof-key",
        correlation_id="recovery-cancel-proof-correlation",
        operator_intent="cancel_exact_recovery_orphan",
        actor=AdminApiActor(
            actor_id="route-operator",
            roles=[AdminApiRole.TRADER],
        ),
        service=_CommandService(),
        idempotency_store=SimpleNamespace(),
        audit_store=SimpleNamespace(),
        approval_store=SimpleNamespace(),
        cap_guard_store=SimpleNamespace(),
        reconciliation_store=SimpleNamespace(),
        live_execution_service=SimpleNamespace(),
        recovery_repository_factory=lambda: repository,
    )

    assert response.status is AdminApiCommandStatus.NOT_IMPLEMENTED
    assert repository.reads == 1
