"""Response-safe Admin runtime drain and queued shutdown contracts."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.routes import admin as admin_routes
from application.admin_api.auth import get_authenticated_actor
from application.admin_api.audit import FileAdminApiAuditStore
from application.admin_api.idempotency import FileIdempotencyStore
from application.admin_api.models import AdminApiActor, AdminRuntimeControlResponse
from application.admin_api.mvp_service import (
    AdminMvpDependencies,
    AdminMvpEvidenceLog,
    AdminMvpService,
    AdminMvpStore,
)
from core.enums import AdminApiRole


class _CoinbaseCallsForbidden:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str):
        def unexpected(*args, **kwargs):
            self.calls.append(name)
            raise AssertionError(f"Unexpected Coinbase call: {name}")

        return unexpected


@dataclass
class _FakeLifecycleController:
    state: str = "RUNNING"
    drain_calls: int = 0
    shutdown_requests: int = 0

    def request_shutdown(self) -> bool:
        self.shutdown_requests += 1
        if self.state in {"DRAINING", "STOPPED"}:
            return False
        self.state = "DRAINING"
        return True

    def drain_and_stop(self, timeout_seconds: float = 30.0):
        self.drain_calls += 1
        before = self.state
        self.state = "STOPPED"
        return SimpleNamespace(
            state_before=before,
            state_after="STOPPED",
            duration_seconds=0.01,
            drained_clean=True,
            inflight_at_timeout={},
        )

    def inflight_snapshot(self) -> dict[str, int]:
        return {}

    def total_inflight(self) -> int:
        return 0

    def is_admitting(self) -> bool:
        return self.state == "RUNNING"

    def is_stopping(self) -> bool:
        return self.state in {"DRAINING", "STOPPED"}


def _route_client(
    monkeypatch,
    tmp_path,
    *,
    role: AdminApiRole,
):
    controller = _FakeLifecycleController()
    rest_client = _CoinbaseCallsForbidden()
    scheduled: list[object] = []
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            runtime_controller_factory=lambda: controller,
            runtime_shutdown_scheduler=lambda target: scheduled.append(target),
        ),
        store=AdminMvpStore(),
        evidence_log=AdminMvpEvidenceLog({}),
        idempotency_store=FileIdempotencyStore(tmp_path / "idempotency.jsonl"),
        audit_store=FileAdminApiAuditStore(tmp_path / "audit.jsonl"),
    )
    app = FastAPI()
    app.include_router(admin_routes.router, prefix="/api/v1")
    app.dependency_overrides[get_authenticated_actor] = lambda: AdminApiActor(
        actor_id="runtime-operator",
        roles=[role],
    )
    monkeypatch.setattr(admin_routes, "get_admin_mvp_service", lambda: service)
    return TestClient(app), controller, scheduled, rest_client


def _headers(key: str) -> dict[str, str]:
    return {
        "Idempotency-Key": key,
        "X-Correlation-Id": f"{key}-correlation",
        "X-Operator-Intent": "operate_runtime",
    }


def test_drain_is_distinct_reachable_transition_and_never_queues_shutdown(
    monkeypatch,
    tmp_path,
) -> None:
    client, controller, scheduled, rest_client = _route_client(
        monkeypatch,
        tmp_path,
        role=AdminApiRole.OPERATOR,
    )

    response = client.post(
        "/api/v1/admin/runtime/drain",
        json={"reason": "stop admission and remain observable"},
        headers=_headers("runtime-drain-1"),
    )

    assert response.status_code == 200
    body = response.json()
    AdminRuntimeControlResponse.model_validate(body)
    assert body["required_permission"] == "runtime:drain"
    assert body["service_method"] == "drain_runtime"
    assert body["runtime_state_after"] == "DRAINING"
    assert body["drain_requested"] is True
    assert body["drain_executed"] is True
    assert body["shutdown_queued"] is False
    assert controller.shutdown_requests == 1
    assert controller.drain_calls == 0
    assert scheduled == []
    assert rest_client.calls == []


def test_shutdown_returns_durable_receipt_before_separate_owner_executes(
    monkeypatch,
    tmp_path,
) -> None:
    client, controller, scheduled, rest_client = _route_client(
        monkeypatch,
        tmp_path,
        role=AdminApiRole.ADMIN,
    )

    response = client.post(
        "/api/v1/admin/runtime/shutdown",
        json={"reason": "operator shutdown", "timeout_seconds": 20},
        headers=_headers("runtime-shutdown-1"),
    )

    assert response.status_code == 200
    body = response.json()
    AdminRuntimeControlResponse.model_validate(body)
    assert body["status"] == "accepted"
    assert body["service_method"] == "queue_runtime_shutdown"
    assert body["runtime_state_before"] == "RUNNING"
    assert body["runtime_state_after"] == "RUNNING"
    assert body["shutdown_queued"] is True
    assert body["drain_requested"] is True
    assert body["drain_executed"] is False
    assert controller.shutdown_requests == 0
    assert controller.drain_calls == 0
    assert len(scheduled) == 1

    replay = client.post(
        "/api/v1/admin/runtime/shutdown",
        json={"reason": "operator shutdown", "timeout_seconds": 20},
        headers=_headers("runtime-shutdown-1"),
    )
    assert replay.status_code == 200
    assert replay.json() == body
    assert replay.headers["X-Idempotency-Replayed"] == "true"
    assert len(scheduled) == 1

    owner = scheduled[0]
    assert callable(owner)
    owner()
    assert controller.drain_calls == 1
    assert controller.state == "STOPPED"
    assert rest_client.calls == []


def test_runtime_openapi_exposes_distinct_drain_and_shutdown_receipt_fields() -> None:
    app = FastAPI()
    app.include_router(admin_routes.router, prefix="/api/v1")
    operation = app.openapi()["paths"]["/api/v1/admin/runtime/drain"]["post"]

    assert {"200", "401", "403", "409", "422", "503"} <= set(
        operation["responses"]
    )
    properties = AdminRuntimeControlResponse.model_json_schema()["properties"]
    assert {"shutdown_queued", "drain_requested", "drain_executed"} <= set(
        properties
    )
