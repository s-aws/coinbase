"""Durability proofs for authenticated Admin runtime lifecycle commands."""

from __future__ import annotations

from fastapi import FastAPI

from api.v1.routes.admin import RUNTIME_CONTROL_RESPONSES, router as admin_router
from application.admin_api.audit import FileAdminApiAuditStore
from application.admin_api.idempotency import FileIdempotencyStore
from application.admin_api.models import AdminRuntimeControlResponse
from application.admin_api.mvp_service import (
    AdminMvpDependencies,
    AdminMvpEvidenceLog,
    AdminMvpRequestContext,
    AdminMvpService,
    AdminMvpStore,
)
from core.runtime_controller import RuntimeController


class _CoinbaseCallsForbidden:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str):
        def _unexpected_call(*args, **kwargs):
            self.calls.append(name)
            raise AssertionError(f"Unexpected Coinbase call: {name}")

        return _unexpected_call


class _AmbiguousPauseController(RuntimeController):
    def __init__(self) -> None:
        super().__init__()
        self.pause_calls = 0

    def request_pause(self) -> bool:
        self.pause_calls += 1
        super().request_pause()
        raise RuntimeError("withheld transition failure")


def _context(
    idempotency_key: str,
    *,
    correlation_id: str | None = None,
) -> AdminMvpRequestContext:
    return AdminMvpRequestContext(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id or f"{idempotency_key}-correlation",
        operator_intent="operate_local_runtime",
        actor_id="operator-1",
        roles=("operator",),
    )


def _service(
    *,
    controller: RuntimeController,
    rest_client: _CoinbaseCallsForbidden,
    idempotency_store: FileIdempotencyStore,
    audit_store: FileAdminApiAuditStore,
) -> AdminMvpService:
    return AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_coinbase_execution_enabled=True,
            runtime_controller_factory=lambda: controller,
        ),
        store=AdminMvpStore(),
        evidence_log=AdminMvpEvidenceLog(collection_paths={}),
        idempotency_store=idempotency_store,
        audit_store=audit_store,
    )


def test_runtime_control_is_durably_idempotent_audited_and_call_free(tmp_path):
    controller = RuntimeController()
    rest_client = _CoinbaseCallsForbidden()
    idempotency_path = tmp_path / "runtime-idempotency.jsonl"
    audit_path = tmp_path / "runtime-audit.jsonl"
    service = _service(
        controller=controller,
        rest_client=rest_client,
        idempotency_store=FileIdempotencyStore(idempotency_path),
        audit_store=FileAdminApiAuditStore(audit_path),
    )

    paused = service.control_runtime(
        "pause",
        {"reason": "operator review"},
        _context("runtime-key-a"),
    )
    assert paused.status_code == 200
    assert paused.body["action"] == "pause"
    assert paused.body["accepted"] is True
    assert paused.body["state"] == "PAUSED"
    assert paused.body["correlation_id"] == "runtime-key-a-correlation"
    assert paused.body["idempotency_key"] == "runtime-key-a"
    assert paused.body["audit_id"]
    assert paused.body["attempt_audit_id"]
    assert paused.body["idempotency_replayed"] is False
    validated = AdminRuntimeControlResponse.model_validate(paused.body)
    assert validated.live_coinbase_read_ran is False
    assert controller.state.value == "PAUSED"

    resumed = service.control_runtime(
        "resume",
        {"reason": "operator review complete"},
        _context("runtime-key-b"),
    )
    assert resumed.status_code == 200
    assert resumed.body["state"] == "RUNNING"
    assert controller.state.value == "RUNNING"

    restarted_service = _service(
        controller=controller,
        rest_client=rest_client,
        idempotency_store=FileIdempotencyStore(idempotency_path),
        audit_store=FileAdminApiAuditStore(audit_path),
    )
    replayed_pause = restarted_service.control_runtime(
        "pause",
        {"reason": "operator review"},
        _context("runtime-key-a", correlation_id="replay-correlation"),
    )
    assert replayed_pause.status_code == 200
    assert replayed_pause.body == paused.body
    assert replayed_pause.headers["X-Idempotency-Replayed"] == "true"
    assert controller.state.value == "RUNNING"

    changed_payload = restarted_service.control_runtime(
        "pause",
        {"reason": "different reason"},
        _context("runtime-key-a"),
    )
    assert changed_payload.status_code == 409
    assert changed_payload.body["status"] == "conflict"
    assert changed_payload.body["failure_stage"] == "idempotency"
    assert changed_payload.body["transition_applied"] is False
    assert changed_payload.body["audit_id"]
    assert controller.state.value == "RUNNING"

    changed_action = restarted_service.control_runtime(
        "shutdown",
        {"reason": "operator review"},
        _context("runtime-key-a"),
    )
    assert changed_action.status_code == 409
    assert changed_action.body["status"] == "conflict"
    assert changed_action.body["action"] == "shutdown"
    assert changed_action.body["transition_applied"] is False
    assert controller.state.value == "RUNNING"

    events = FileAdminApiAuditStore(audit_path).read_recent(limit=20)
    pause_events = [
        event for event in events if event.idempotency_key == "runtime-key-a"
    ]
    assert any(event.failure_stage == "runtime_transition_claimed" for event in pause_events)
    assert any(
        event.status.value == "accepted" and event.failure_stage is None
        for event in pause_events
    )
    assert sum(event.failure_stage == "idempotency" for event in pause_events) == 2
    assert rest_client.calls == []


def test_runtime_control_unknown_claim_is_not_retried_after_restart(tmp_path):
    controller = _AmbiguousPauseController()
    rest_client = _CoinbaseCallsForbidden()
    idempotency_path = tmp_path / "runtime-idempotency.jsonl"
    audit_path = tmp_path / "runtime-audit.jsonl"
    service = _service(
        controller=controller,
        rest_client=rest_client,
        idempotency_store=FileIdempotencyStore(idempotency_path),
        audit_store=FileAdminApiAuditStore(audit_path),
    )

    unknown = service.control_runtime(
        "pause",
        {"reason": "operator review"},
        _context("runtime-unknown-key"),
    )
    assert unknown.status_code == 503
    assert unknown.body["status"] == "outcome_unknown"
    assert unknown.body["failure_stage"] == "runtime_transition_outcome_unknown"
    assert controller.pause_calls == 1
    assert controller.state.value == "PAUSED"

    assert controller.resume() is True
    restarted_service = _service(
        controller=controller,
        rest_client=rest_client,
        idempotency_store=FileIdempotencyStore(idempotency_path),
        audit_store=FileAdminApiAuditStore(audit_path),
    )
    replayed_unknown = restarted_service.control_runtime(
        "pause",
        {"reason": "operator review"},
        _context("runtime-unknown-key", correlation_id="retry-correlation"),
    )
    assert replayed_unknown.status_code == 503
    assert replayed_unknown.body == unknown.body
    assert replayed_unknown.headers["X-Idempotency-Replayed"] == "true"
    assert controller.pause_calls == 1
    assert controller.state.value == "RUNNING"
    assert rest_client.calls == []


def test_runtime_control_routes_document_conflict_and_unknown_outcomes():
    assert RUNTIME_CONTROL_RESPONSES[409]["model"] is AdminRuntimeControlResponse
    assert RUNTIME_CONTROL_RESPONSES[503]["model"] is AdminRuntimeControlResponse
    response_properties = set(
        AdminRuntimeControlResponse.model_json_schema()["properties"]
    )
    assert {
        "correlation_id",
        "idempotency_key",
        "audit_id",
        "attempt_audit_id",
        "failure_stage",
        "idempotency_replayed",
        "local_state_mutated",
        "read_only",
        "frontend_safe",
        "browser_authority",
        "bff_authority",
        "live_coinbase_execution",
        "live_coinbase_orders_ran",
        "live_coinbase_read_ran",
    } <= response_properties

    app = FastAPI()
    app.include_router(admin_router, prefix="/api/v1")
    openapi = app.openapi()
    for path in (
        "/api/v1/admin/runtime/pause",
        "/api/v1/admin/runtime/resume",
        "/api/v1/admin/runtime/shutdown",
    ):
        assert {"200", "401", "403", "409", "422", "503"} <= set(
            openapi["paths"][path]["post"]["responses"]
        )
        assert openapi["paths"][path]["post"]["responses"]["409"]["content"][
            "application/json"
        ]["schema"]["$ref"] == "#/components/schemas/AdminRuntimeControlResponse"
        assert openapi["paths"][path]["post"]["responses"]["503"]["content"][
            "application/json"
        ]["schema"]["$ref"] == "#/components/schemas/AdminRuntimeControlResponse"
