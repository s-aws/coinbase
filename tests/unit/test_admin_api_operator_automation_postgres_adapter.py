"""Application adapter contract for the typed PostgreSQL automation store."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from application.admin_api.automation_models import AutomationMutationContext
from application.admin_api.operator_automation import (
    PostgresOperatorAutomationRepositoryAdapter,
    get_default_operator_automation_service,
)
from core.enums import (
    OperatorAutomationControlPosture,
    OperatorAutomationDefinitionState,
    OperatorAutomationDomain,
    OperatorAutomationJobKind,
    OperatorAutomationRunState,
    OperatorAutomationScheduleKind,
)
from database.operator_automation import (
    AutomationControlPlaneRecord,
    AutomationDefinitionCreateCommand,
    AutomationDefinitionRecord,
    AutomationLifecycleEventRecord,
    AutomationMutationCommand,
    AutomationRunRecord,
    AutomationStoreMutation,
    AutomationStorePage,
)


NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc).isoformat()
DEFINITION_ID = "2f744264-8d18-46a2-b89d-f0c206216515"
RUN_ID = "19cae8ee-d8ec-43d3-a0f7-8f55ba1d76a0"
AUDIT_ID = "26371b41-f16e-4dad-83cc-946055440c62"


def _context() -> AutomationMutationContext:
    return AutomationMutationContext(
        actor_id="operator-adapter-test",
        roles=("trader",),
        idempotency_key="adapter-idempotency-1",
        correlation_id="adapter-correlation-1",
        operator_intent="create_automation_definition",
    )


def _definition(
    *,
    state: OperatorAutomationDefinitionState = (
        OperatorAutomationDefinitionState.DRAFT
    ),
) -> AutomationDefinitionRecord:
    return AutomationDefinitionRecord(
        definition_id=DEFINITION_ID,
        revision=1,
        label="Bounded Spot sweep review",
        domain=OperatorAutomationDomain.SPOT,
        job_kind=OperatorAutomationJobKind.SPOT_SWEEP,
        lifecycle_state=state,
        product_ids=("BTC-USDC",),
        schedule_kind=OperatorAutomationScheduleKind.MANUAL_ONLY,
        interval_seconds=None,
        next_review_at=None,
        schedule_due=False,
        due_reason="manual_only",
        created_at=NOW,
        updated_at=NOW,
    )


def _run(
    *,
    state: OperatorAutomationRunState,
    diagnostic_code: str,
) -> AutomationRunRecord:
    return AutomationRunRecord(
        run_id=RUN_ID,
        definition_id=DEFINITION_ID,
        domain=OperatorAutomationDomain.SPOT,
        job_kind=OperatorAutomationJobKind.SPOT_SWEEP,
        state=state,
        diagnostic_code=diagnostic_code,
        audit_id=AUDIT_ID,
        correlation_id="adapter-correlation-1",
        client_order_id=None,
        live_attempt_consumed=False,
        coinbase_api_call_count=0,
        create_call_count=0,
        cancel_call_count=0,
        claimed_at=NOW,
        updated_at=NOW,
    )


class _RawRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.claim_replayed = False
        self.current_run = _run(
            state=OperatorAutomationRunState.CLAIMED,
            diagnostic_code="one_shot_run_claimed",
        )

    def get_control_posture(self) -> AutomationControlPlaneRecord:
        self.calls.append(("get_control_posture", (), {}))
        return AutomationControlPlaneRecord(
            posture=OperatorAutomationControlPosture.ACTIVE,
            updated_at=NOW,
        )

    def list_definitions(self, **kwargs: Any) -> AutomationStorePage:
        self.calls.append(("list_definitions", (), kwargs))
        return AutomationStorePage(items=(_definition(),), total_count=1)

    def get_definition(self, definition_id: str) -> AutomationDefinitionRecord | None:
        self.calls.append(("get_definition", (definition_id,), {}))
        return _definition() if definition_id == DEFINITION_ID else None

    def create_definition(
        self,
        command: AutomationDefinitionCreateCommand,
    ) -> AutomationStoreMutation:
        self.calls.append(("create_definition", (command,), {}))
        return AutomationStoreMutation(
            entity=_definition(),
            audit_id=AUDIT_ID,
            correlation_id=command.correlation_id,
        )

    def transition_definition(
        self,
        definition_id: str,
        action: str,
        command: AutomationMutationCommand,
    ) -> AutomationStoreMutation:
        self.calls.append(
            ("transition_definition", (definition_id, action, command), {})
        )
        return AutomationStoreMutation(
            entity=replace(
                _definition(),
                lifecycle_state=OperatorAutomationDefinitionState.ENABLED,
            ),
            audit_id=AUDIT_ID,
            correlation_id=command.correlation_id,
        )

    def claim_one_shot_run(
        self,
        definition_id: str,
        command: AutomationMutationCommand,
    ) -> AutomationStoreMutation:
        self.calls.append(
            ("claim_one_shot_run", (definition_id, command), {})
        )
        return AutomationStoreMutation(
            entity=_run(
                state=OperatorAutomationRunState.CLAIMED,
                diagnostic_code="one_shot_run_claimed",
            ),
            audit_id=AUDIT_ID,
            correlation_id=command.correlation_id,
            replayed=self.claim_replayed,
        )

    def get_run(self, run_id: str) -> AutomationRunRecord | None:
        self.calls.append(("get_run", (run_id,), {}))
        return self.current_run if run_id == RUN_ID else None

    def transition_run(
        self,
        run_id: str,
        state: OperatorAutomationRunState,
        *,
        diagnostic_code: str,
        command: AutomationMutationCommand,
    ) -> AutomationStoreMutation:
        self.calls.append(
            (
                "transition_run",
                (run_id, state),
                {"diagnostic_code": diagnostic_code, "command": command},
            )
        )
        return AutomationStoreMutation(
            entity=_run(state=state, diagnostic_code=diagnostic_code),
            audit_id=AUDIT_ID,
            correlation_id=command.correlation_id,
        )


def test_adapter_builds_typed_create_command_and_strict_public_projection():
    raw = _RawRepository()
    adapter = PostgresOperatorAutomationRepositoryAdapter(raw)

    result = adapter.create_definition(
        definition={
            "display_name": "Bounded Spot sweep review",
            "domain": "SPOT",
            "job_kind": "SPOT_SWEEP",
            "product_ids": ["BTC-USDC"],
        },
        context=_context(),
    )

    command = raw.calls[-1][1][0]
    assert isinstance(command, AutomationDefinitionCreateCommand)
    assert command.domain is OperatorAutomationDomain.SPOT
    assert command.job_kind is OperatorAutomationJobKind.SPOT_SWEEP
    assert command.label == "Bounded Spot sweep review"
    assert command.product_ids == ("BTC-USDC",)
    assert len(command.payload_sha256) == 64
    assert result.entity["display_name"] == "Bounded Spot sweep review"
    assert result.entity["domain"] == "SPOT"
    assert result.entity["schedule"]["mode"] == "MANUAL_ONLY"
    assert result.entity["adapter_status"] == "UNAVAILABLE"
    assert result.entity["live_execution_available"] is False


def test_adapter_converts_filters_and_pages_to_the_application_protocol():
    raw = _RawRepository()
    adapter = PostgresOperatorAutomationRepositoryAdapter(raw)

    page = adapter.list_definitions(
        domain="SPOT",
        job_kind="SPOT_SWEEP",
        lifecycle_state="DRAFT",
        limit=25,
        offset=0,
    )

    assert page.total_count == 1
    assert page.items[0]["definition_id"] == DEFINITION_ID
    assert raw.calls[-1] == (
        "list_definitions",
        (),
        {
            "domain": OperatorAutomationDomain.SPOT,
            "job_kind": OperatorAutomationJobKind.SPOT_SWEEP,
            "lifecycle_state": OperatorAutomationDefinitionState.DRAFT,
            "limit": 25,
            "offset": 0,
        },
    )


def test_adapter_removes_run_action_when_global_control_is_not_active():
    record = replace(
        _definition(state=OperatorAutomationDefinitionState.ENABLED),
        due_reason="control_plane_not_active",
    )

    projected = PostgresOperatorAutomationRepositoryAdapter._definition(record)

    assert "RUN_ONCE" not in projected["allowed_actions"]


def test_adapter_omits_definition_identity_from_control_event_projection():
    control_event = AutomationLifecycleEventRecord(
        event_id="418d5f34-a054-410b-9c92-ddd09dcd6b03",
        definition_id=None,
        from_state="ACTIVE",
        to_state="PAUSED",
        diagnostic_code="automation_control_pause",
        audit_id=AUDIT_ID,
        correlation_id="adapter-correlation-1",
        recorded_at=NOW,
    )
    definition_event = replace(control_event, definition_id=DEFINITION_ID)

    assert "definition_id" not in (
        PostgresOperatorAutomationRepositoryAdapter._lifecycle_event(control_event)
    )
    assert (
        PostgresOperatorAutomationRepositoryAdapter._lifecycle_event(
            definition_event
        )["definition_id"]
        == DEFINITION_ID
    )


def test_adapter_finalizes_claim_as_blocked_without_domain_or_exchange_activity():
    raw = _RawRepository()
    adapter = PostgresOperatorAutomationRepositoryAdapter(raw)
    context = _context().model_copy(
        update={"operator_intent": "claim_automation_one_shot_run"}
    )

    result = adapter.claim_one_shot_run(
        definition_id=DEFINITION_ID,
        request={
            "confirm_one_shot": True,
            "reason": "Explicit adapter readiness review",
        },
        context=context,
    )

    assert [call[0] for call in raw.calls] == [
        "claim_one_shot_run",
        "transition_run",
    ]
    claim_command = raw.calls[0][1][1]
    blocked_command = raw.calls[1][2]["command"]
    assert claim_command.idempotency_key == context.idempotency_key
    assert blocked_command.idempotency_key != context.idempotency_key
    assert raw.calls[1][1][1] is OperatorAutomationRunState.BLOCKED
    assert raw.calls[1][2]["diagnostic_code"] == (
        "automation_domain_adapter_unavailable"
    )
    assert result.entity["state"] == "BLOCKED"
    assert result.entity["trigger"] == "ONE_SHOT"
    assert result.entity["coinbase_api_call_count"] == 0
    assert result.entity["create_call_count"] == 0
    assert result.entity["cancel_call_count"] == 0


def test_adapter_exact_replay_returns_terminal_restart_recovery_without_retransition():
    raw = _RawRepository()
    raw.claim_replayed = True
    raw.current_run = replace(
        raw.current_run,
        state=OperatorAutomationRunState.BLOCKED,
        diagnostic_code="restart_pre_invocation_blocked",
        audit_id="36371b41-f16e-4dad-83cc-946055440c62",
        correlation_id="automation-restart-recovery",
    )
    adapter = PostgresOperatorAutomationRepositoryAdapter(raw)
    context = _context().model_copy(
        update={"operator_intent": "claim_automation_one_shot_run"}
    )

    result = adapter.claim_one_shot_run(
        definition_id=DEFINITION_ID,
        request={
            "confirm_one_shot": True,
            "reason": "Replay one interrupted local claim.",
        },
        context=context,
    )

    assert [call[0] for call in raw.calls] == ["claim_one_shot_run", "get_run"]
    assert result.replayed is True
    assert result.entity["state"] == "BLOCKED"
    assert result.entity["diagnostic_code"] == "restart_pre_invocation_blocked"
    assert result.audit_id == "36371b41-f16e-4dad-83cc-946055440c62"
    assert result.correlation_id == "adapter-correlation-1"


def test_default_service_composes_the_application_adapter(monkeypatch):
    import database.operator_automation as store_module

    raw = _RawRepository()
    monkeypatch.setattr(
        store_module,
        "get_default_operator_automation_repository",
        lambda: raw,
    )

    service = get_default_operator_automation_service()

    assert isinstance(
        service.repository,
        PostgresOperatorAutomationRepositoryAdapter,
    )
    assert service.get_control_plane().control_plane.posture.value == "ACTIVE"
