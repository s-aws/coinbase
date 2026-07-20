"""Application adapter contract for the typed PostgreSQL automation store."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
from typing import Any

import pytest

from application.admin_api.automation_models import (
    AutomationMutationContext,
    AutomationRunEventItem,
    AutomationRunItem,
)
from application.admin_api.automation_models import (
    AutomationSingleChildAuthorizationRequest,
)
from application.admin_api.operator_automation import (
    OperatorAutomationRepository,
    OperatorAutomationService,
    AutomationRepositoryConflict,
    AutomationRepositoryUnavailable,
    PostgresOperatorAutomationRepositoryAdapter,
    get_default_operator_automation_service,
)
from application.admin_api.operator_spot_eligibility import (
    APPROVED_SPOT_ELIGIBILITY_ORDER,
    SpotEligibilityReadOutcome,
    SpotEligibilityReadResult,
    derive_spot_eligibility_client_order_id,
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
    AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES,
    AutomationControlPlaneRecord,
    AutomationDefinitionCreateCommand,
    AutomationDefinitionRecord,
    AutomationLifecycleEventRecord,
    AutomationMutationCommand,
    AutomationRunRecord,
    AutomationSpotSingleChildPlanTerms,
    AutomationSpotSingleChildPlanRecord,
    AutomationSpotEligibilityAttemptRecord,
    AutomationSpotEligibilityCycleAllocationRecord,
    AutomationSpotEligibilityCycleRecord,
    AutomationStoreMutation,
    AutomationStorePage,
)


NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc).isoformat()
DEFINITION_ID = "2f744264-8d18-46a2-b89d-f0c206216515"
RUN_ID = "19cae8ee-d8ec-43d3-a0f7-8f55ba1d76a0"
AUDIT_ID = "26371b41-f16e-4dad-83cc-946055440c62"
SECOND_AUDIT_ID = "1f1fce8b-59bb-4518-97e0-caf466db889a"
PORTFOLIO_ID = "483d1403-5d4d-4ae1-9084-ae2b080902b7"


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
    job_kind: OperatorAutomationJobKind = OperatorAutomationJobKind.SPOT_SWEEP,
) -> AutomationDefinitionRecord:
    return AutomationDefinitionRecord(
        definition_id=DEFINITION_ID,
        revision=1,
        label="Bounded Spot sweep review",
        domain=OperatorAutomationDomain.SPOT,
        job_kind=job_kind,
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
    job_kind: OperatorAutomationJobKind = OperatorAutomationJobKind.SPOT_SWEEP,
) -> AutomationRunRecord:
    return AutomationRunRecord(
        run_id=RUN_ID,
        definition_id=DEFINITION_ID,
        domain=OperatorAutomationDomain.SPOT,
        job_kind=job_kind,
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
        definition_revision=1,
    )


def _plan() -> AutomationSpotSingleChildPlanRecord:
    return AutomationSpotSingleChildPlanRecord(
        definition_id=DEFINITION_ID,
        definition_revision=1,
        portfolio_id_sha256=hashlib.sha256(
            PORTFOLIO_ID.encode("utf-8")
        ).hexdigest(),
        product_id="BTC-USDC",
        side="BUY",
        base_size="0.00001",
        limit_price="50000",
        submitted_notional_usdc="0.5",
        possible_execution_notional_usdc="0.5",
        max_submitted_notional_usdc="3.1",
        max_possible_execution_notional_usdc="1",
        post_only=False,
        plan_sha256="e" * 64,
        audit_id=AUDIT_ID,
        correlation_id="adapter-correlation-1",
        created_at=NOW,
    )


def _eligibility_cycle(
    *,
    cycle_number: int = 1,
    state: str = "REJECTED",
) -> AutomationSpotEligibilityCycleRecord:
    return AutomationSpotEligibilityCycleRecord(
        goal_key="operator_spot_automation_single_child_execution_adapter_v1",
        cycle_number=cycle_number,
        run_id=RUN_ID,
        definition_id=DEFINITION_ID,
        definition_revision=1,
        plan_sha256="e" * 64,
        portfolio_id_sha256=hashlib.sha256(
            PORTFOLIO_ID.encode("utf-8")
        ).hexdigest(),
        product_id="BTC-USDC",
        client_order_id=(
            "0d05789c-95f7-542e-8fba-ebf89c5bc80f"
        ),
        state=state,
        coinbase_api_call_count=(7 if state == "SUCCEEDED" else 1),
        call_count_exact=True,
        fresh_until=(
            "2099-07-20T12:00:00+00:00"
            if state == "SUCCEEDED"
            else None
        ),
        diagnostic_code=f"automation_spot_eligibility_cycle_{state.lower()}",
        audit_id=AUDIT_ID,
        correlation_id="adapter-correlation-1",
        started_at=NOW,
        finalized_at=NOW,
    )


class _RawRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.claim_replayed = False
        self.spot_goal_run_claimed = False
        self.current_run = _run(
            state=OperatorAutomationRunState.CLAIMED,
            diagnostic_code="one_shot_run_claimed",
        )
        self.plan: AutomationSpotSingleChildPlanRecord | None = None
        self.cycles: tuple[AutomationSpotEligibilityCycleRecord, ...] = ()

    def has_spot_single_child_run(self) -> bool:
        self.calls.append(("has_spot_single_child_run", (), {}))
        return self.spot_goal_run_claimed

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
        *,
        spot_single_child_plan: AutomationSpotSingleChildPlanTerms | None = None,
    ) -> AutomationStoreMutation:
        self.calls.append(
            (
                "create_definition",
                (command,),
                {"spot_single_child_plan": spot_single_child_plan},
            )
        )
        record = _definition(
            job_kind=(
                OperatorAutomationJobKind.SPOT_CAMPAIGN
                if spot_single_child_plan is not None
                else OperatorAutomationJobKind.SPOT_SWEEP
            )
        )
        if spot_single_child_plan is not None:
            self.plan = _plan()
        return AutomationStoreMutation(
            entity=record,
            audit_id=AUDIT_ID,
            correlation_id=command.correlation_id,
        )

    def get_spot_single_child_plan(
        self,
        definition_id: str,
        definition_revision: int,
    ) -> AutomationSpotSingleChildPlanRecord | None:
        self.calls.append(
            (
                "get_spot_single_child_plan",
                (definition_id, definition_revision),
                {},
            )
        )
        return self.plan

    def list_spot_eligibility_attempts(
        self,
        run_id: str,
        cycle_number: int | None = None,
    ) -> tuple:
        self.calls.append(
            ("list_spot_eligibility_attempts", (run_id, cycle_number), {})
        )
        return ()

    def list_spot_eligibility_cycles(
        self,
    ) -> tuple[AutomationSpotEligibilityCycleRecord, ...]:
        self.calls.append(("list_spot_eligibility_cycles", (), {}))
        return self.cycles

    def get_spot_run_execution(self, run_id: str):
        self.calls.append(("get_spot_run_execution", (run_id,), {}))
        return None

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

    def audit_spot_source_gate_authorization(
        self,
        run_id: str,
        *,
        expected_plan_sha256: str,
        command: AutomationMutationCommand,
    ) -> AutomationStoreMutation:
        self.calls.append(
            (
                "audit_spot_source_gate_authorization",
                (run_id,),
                {
                    "expected_plan_sha256": expected_plan_sha256,
                    "command": command,
                },
            )
        )
        return AutomationStoreMutation(
            entity=self.current_run,
            audit_id=AUDIT_ID,
            correlation_id=command.correlation_id,
        )

    def resume_spot_source_gated_run(
        self,
        run_id: str,
        *,
        expected_plan_sha256: str,
        command: AutomationMutationCommand,
    ) -> AutomationStoreMutation:
        self.calls.append(
            (
                "resume_spot_source_gated_run",
                (run_id,),
                {
                    "expected_plan_sha256": expected_plan_sha256,
                    "command": command,
                },
            )
        )
        self.current_run = replace(
            self.current_run,
            state=OperatorAutomationRunState.PREPARING,
            diagnostic_code="automation_spot_source_gate_resumed",
            audit_id=AUDIT_ID,
            correlation_id=command.correlation_id,
        )
        return AutomationStoreMutation(
            entity=self.current_run,
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


def test_adapter_persists_one_backend_bound_btc_single_child_plan(monkeypatch):
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID",
        PORTFOLIO_ID,
    )
    raw = _RawRepository()
    adapter = PostgresOperatorAutomationRepositoryAdapter(raw)

    result = adapter.create_definition(
        definition={
            "display_name": "One BTC child",
            "domain": "SPOT",
            "job_kind": "SPOT_CAMPAIGN",
            "product_ids": ["BTC-USDC"],
            "single_child_order": {
                "side": "BUY",
                "base_size": "0.00001",
                "limit_price": "50000",
                "order_type": "LIMIT",
                "time_in_force": "GOOD_UNTIL_CANCELLED",
                "post_only": False,
            },
        },
        context=_context().model_copy(
            update={"idempotency_key": "x" * 255}
        ),
    )

    assert [call[0] for call in raw.calls] == [
        "create_definition",
        "get_spot_single_child_plan",
        "has_spot_single_child_run",
    ]
    terms = raw.calls[0][2]["spot_single_child_plan"]
    assert isinstance(terms, AutomationSpotSingleChildPlanTerms)
    assert terms.product_id == "BTC-USDC"
    assert terms.submitted_notional_usdc == "0.50000"
    assert terms.possible_execution_notional_usdc == "0.50000"
    assert terms.max_submitted_notional_usdc == "3.10"
    assert terms.max_possible_execution_notional_usdc == "1.00"
    assert terms.portfolio_id_sha256 != (
        "483d1403-5d4d-4ae1-9084-ae2b080902b7"
    )
    assert result.entity["single_child_order"]["side"] == "BUY"
    assert result.entity["adapter_status"] == "SOURCE_GATED"


def test_adapter_rejects_noncanonical_portfolio_before_definition_persistence(
    monkeypatch,
):
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID",
        "not-a-canonical-uuid",
    )
    raw = _RawRepository()
    adapter = PostgresOperatorAutomationRepositoryAdapter(raw)

    with pytest.raises(
        AutomationRepositoryUnavailable,
        match="automation_spot_portfolio_invalid",
    ):
        adapter.create_definition(
            definition={
                "display_name": "Invalid portfolio binding",
                "domain": "SPOT",
                "job_kind": "SPOT_CAMPAIGN",
                "product_ids": ["BTC-USDC"],
                "single_child_order": {
                    "side": "BUY",
                    "base_size": "0.00001",
                    "limit_price": "50000",
                    "order_type": "LIMIT",
                    "time_in_force": "GOOD_UNTIL_CANCELLED",
                    "post_only": False,
                },
            },
            context=_context(),
        )

    assert raw.calls == []


def test_single_child_readback_withholds_test_scope_until_catalog_proves_it():
    raw = _RawRepository()
    raw.plan = _plan()
    raw.current_run = _run(
        state=OperatorAutomationRunState.BLOCKED,
        diagnostic_code="automation_active_order_catalog_read_not_authorized",
        job_kind=OperatorAutomationJobKind.SPOT_CAMPAIGN,
    )
    adapter = PostgresOperatorAutomationRepositoryAdapter(raw)

    unverified = adapter.get_run(RUN_ID)

    assert unverified is not None
    assert unverified["single_child_plan"]["portfolio_scope"] == (
        "CONFIGURED_UNVERIFIED"
    )

    portfolio_attempt = AutomationSpotEligibilityAttemptRecord(
        run_id=RUN_ID,
        cycle_number=1,
        category="PORTFOLIO_CATALOG",
        allowance_consumed=True,
        outcome="SUCCEEDED",
        eligible=True,
        coinbase_api_call_count=1,
        call_count_exact=True,
        observed_at=NOW,
        fresh_until="2099-07-20T12:00:00+00:00",
        evidence_sha256="f" * 64,
        diagnostic_code="automation_spot_eligibility_succeeded",
        audit_id=AUDIT_ID,
        correlation_id="adapter-correlation-1",
        started_at=NOW,
        finalized_at=NOW,
        portfolio_id_sha256=raw.plan.portfolio_id_sha256,
    )
    raw.list_spot_eligibility_attempts = lambda run_id, cycle_number=None: (
        portfolio_attempt,
    )
    raw.cycles = (_eligibility_cycle(),)

    catalog_proven = adapter.get_run(RUN_ID)

    assert catalog_proven is not None
    assert catalog_proven["single_child_plan"]["portfolio_scope"] == "Test"

    current_unbound_attempt = replace(
        portfolio_attempt,
        cycle_number=2,
        portfolio_id_sha256=None,
    )
    raw.list_spot_eligibility_attempts = lambda run_id, cycle_number=None: (
        portfolio_attempt,
        current_unbound_attempt,
    )
    raw.cycles = (
        _eligibility_cycle(cycle_number=1),
        _eligibility_cycle(cycle_number=2),
    )

    older_only = adapter.get_run(RUN_ID)

    assert older_only is not None
    assert older_only["single_child_plan"]["portfolio_scope"] == (
        "CONFIGURED_UNVERIFIED"
    )

    current_bound_attempt = replace(
        current_unbound_attempt,
        portfolio_id_sha256=raw.plan.portfolio_id_sha256,
    )
    raw.list_spot_eligibility_attempts = lambda run_id, cycle_number=None: (
        portfolio_attempt,
        current_bound_attempt,
    )

    current_proven = adapter.get_run(RUN_ID)

    assert current_proven is not None
    assert current_proven["single_child_plan"]["portfolio_scope"] == "Test"


def test_campaign_claim_prepares_then_blocks_before_calls_when_open_order_read_is_unauthorized():
    raw = _RawRepository()
    raw.plan = _plan()
    raw.current_run = _run(
        state=OperatorAutomationRunState.CLAIMED,
        diagnostic_code="one_shot_run_claimed",
        job_kind=OperatorAutomationJobKind.SPOT_CAMPAIGN,
    )
    raw.claim_one_shot_run = lambda definition_id, command: (
        raw.calls.append(("claim_one_shot_run", (definition_id, command), {}))
        or AutomationStoreMutation(
            raw.current_run,
            AUDIT_ID,
            command.correlation_id,
        )
    )

    def transition(run_id, state, *, diagnostic_code, command):
        raw.calls.append(
            (
                "transition_run",
                (run_id, state),
                {"diagnostic_code": diagnostic_code, "command": command},
            )
        )
        raw.current_run = replace(
            raw.current_run,
            state=state,
            diagnostic_code=diagnostic_code,
        )
        return AutomationStoreMutation(
            raw.current_run,
            AUDIT_ID,
            command.correlation_id,
        )

    raw.transition_run = transition
    adapter = PostgresOperatorAutomationRepositoryAdapter(raw)
    result = adapter.claim_one_shot_run(
        definition_id=DEFINITION_ID,
        request={"confirm_one_shot": True, "reason": "Prepare one child"},
        context=_context().model_copy(
            update={"operator_intent": "claim_automation_one_shot_run"}
        ),
    )

    assert [call[0] for call in raw.calls] == [
        "claim_one_shot_run",
        "get_spot_single_child_plan",
        "transition_run",
        "transition_run",
        "get_spot_single_child_plan",
        "list_spot_eligibility_attempts",
        "list_spot_eligibility_cycles",
        "get_spot_run_execution",
    ]
    assert result.entity["state"] == "BLOCKED"
    assert result.entity["diagnostic_code"] == (
        "automation_active_order_catalog_read_not_authorized"
    )
    assert result.entity["single_child_plan"]["product_id"] == "BTC-USDC"
    assert result.entity["coinbase_api_call_count"] == 0
    assert result.entity["create_call_count"] == 0


@pytest.mark.parametrize(
    ("current_state", "diagnostic", "expected_transitions"),
    [
        (
            OperatorAutomationRunState.CLAIMED,
            "one_shot_run_claimed",
            [
                OperatorAutomationRunState.PREPARING,
                OperatorAutomationRunState.BLOCKED,
            ],
        ),
        (
            OperatorAutomationRunState.PREPARING,
            "preparing",
            [OperatorAutomationRunState.BLOCKED],
        ),
        (
            OperatorAutomationRunState.BLOCKED,
            "automation_active_order_catalog_read_not_authorized",
            [],
        ),
    ],
)
def test_campaign_claim_replay_resumes_each_pre_source_gate_crash_boundary(
    current_state: OperatorAutomationRunState,
    diagnostic: str,
    expected_transitions: list[OperatorAutomationRunState],
):
    raw = _RawRepository()
    raw.plan = _plan()
    raw.claim_replayed = True
    raw.current_run = _run(
        state=current_state,
        diagnostic_code=diagnostic,
        job_kind=OperatorAutomationJobKind.SPOT_CAMPAIGN,
    )
    raw.claim_one_shot_run = lambda definition_id, command: (
        raw.calls.append(("claim_one_shot_run", (definition_id, command), {}))
        or AutomationStoreMutation(
            _run(
                state=OperatorAutomationRunState.CLAIMED,
                diagnostic_code="one_shot_run_claimed",
                job_kind=OperatorAutomationJobKind.SPOT_CAMPAIGN,
            ),
            AUDIT_ID,
            command.correlation_id,
            replayed=True,
        )
    )

    def transition(run_id, state, *, diagnostic_code, command):
        raw.calls.append(
            (
                "transition_run",
                (run_id, state),
                {"diagnostic_code": diagnostic_code, "command": command},
            )
        )
        raw.current_run = replace(
            raw.current_run,
            state=state,
            diagnostic_code=diagnostic_code,
        )
        return AutomationStoreMutation(
            raw.current_run,
            AUDIT_ID,
            command.correlation_id,
        )

    raw.transition_run = transition
    result = PostgresOperatorAutomationRepositoryAdapter(
        raw
    ).claim_one_shot_run(
        definition_id=DEFINITION_ID,
        request={
            "confirm_one_shot": True,
            "reason": "Resume only to the fixed source gate",
        },
        context=_context().model_copy(
            update={"operator_intent": "claim_automation_one_shot_run"}
        ),
    )

    transitions = [
        call[1][1]
        for call in raw.calls
        if call[0] == "transition_run"
    ]
    assert transitions == expected_transitions
    assert result.replayed is True
    assert result.entity["state"] == "BLOCKED"
    assert result.entity["diagnostic_code"] == (
        "automation_active_order_catalog_read_not_authorized"
    )
    assert result.entity["coinbase_api_call_count"] == 0
    assert result.entity["create_call_count"] == 0
    assert result.entity["cancel_call_count"] == 0


def test_adapter_authorization_fails_before_invocation_for_unapproved_open_order_read():
    raw = _RawRepository()
    raw.plan = _plan()
    raw.current_run = replace(
        _run(
            state=OperatorAutomationRunState.BLOCKED,
            diagnostic_code="automation_domain_adapter_unavailable",
            job_kind=OperatorAutomationJobKind.SPOT_CAMPAIGN,
        ),
        diagnostic_code="automation_active_order_catalog_read_not_authorized",
    )
    adapter = PostgresOperatorAutomationRepositoryAdapter(raw)

    with pytest.raises(
        AutomationRepositoryConflict,
        match="automation_active_order_catalog_read_not_authorized",
    ):
        adapter.authorize_single_child(
            run_id=RUN_ID,
            request=AutomationSingleChildAuthorizationRequest(
                confirm_single_child_create=True,
                confirm_exact_child_safe_closeout_cancel=True,
                confirm_unknown_consumes_allowance=True,
                expected_plan_sha256=raw.plan.plan_sha256,
                reason="Authorize exact child",
            ).model_dump(mode="json"),
            context=_context().model_copy(
                update={
                    "operator_intent": (
                        "authorize_automation_single_child_create_and_safe_closeout"
                    )
                }
            ),
        )

    assert [call[0] for call in raw.calls] == [
        "get_run",
        "get_spot_single_child_plan",
        "audit_spot_source_gate_authorization",
    ]
    audit_call = raw.calls[-1]
    assert audit_call[2]["expected_plan_sha256"] == raw.plan.plan_sha256
    assert audit_call[2]["command"].idempotency_key == (
        "adapter-idempotency-1"
    )


class _SuccessfulEligibilityReader:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str):
        if not name.startswith("read_"):
            raise AttributeError(name)

        def read(_context):
            self.calls.append(name)
            observed = datetime.now(timezone.utc)
            return SpotEligibilityReadResult(
                outcome=SpotEligibilityReadOutcome.SUCCEEDED,
                eligible=True,
                logical_call_count=1,
                http_request_count=1,
                call_count_exact=True,
                observed_at=observed,
                evidence_sha256="f" * 64,
            )

        return read


def test_adapter_runs_one_seven_category_cycle_and_restores_source_gate():
    raw = _RawRepository()
    raw.plan = _plan()
    raw.current_run = _run(
        state=OperatorAutomationRunState.BLOCKED,
        diagnostic_code="automation_active_order_catalog_read_not_authorized",
        job_kind=OperatorAutomationJobKind.SPOT_CAMPAIGN,
    )
    raw.cycles = ()
    attempts: list[AutomationSpotEligibilityAttemptRecord] = []
    client_order_id = derive_spot_eligibility_client_order_id(
        run_id=RUN_ID,
        plan_sha256=raw.plan.plan_sha256,
    )

    def resume(run_id, *, expected_plan_sha256, command):
        raw.calls.append(
            (
                "resume_spot_source_gated_run",
                (run_id,),
                {
                    "expected_plan_sha256": expected_plan_sha256,
                    "command": command,
                },
            )
        )
        raw.current_run = replace(
            raw.current_run,
            state=OperatorAutomationRunState.PREPARING,
            diagnostic_code="automation_spot_source_gate_resumed",
        )
        cycle = replace(
            _eligibility_cycle(state="REJECTED"),
            state="OPEN",
            coinbase_api_call_count=None,
            call_count_exact=False,
            fresh_until=None,
            diagnostic_code="automation_spot_eligibility_cycle_opened",
            client_order_id=client_order_id,
            finalized_at=None,
        )
        raw.cycles = (cycle,)
        return AutomationStoreMutation(
            AutomationSpotEligibilityCycleAllocationRecord(
                run=raw.current_run,
                cycle=cycle,
            ),
            AUDIT_ID,
            command.correlation_id,
        )

    def start(run_id, *, category, command):
        raw.calls.append(
            (
                "start_spot_eligibility_attempt",
                (run_id,),
                {"category": category, "command": command},
            )
        )
        record = AutomationSpotEligibilityAttemptRecord(
            run_id=run_id,
            cycle_number=1,
            category=category,
            allowance_consumed=True,
            outcome=None,
            eligible=None,
            coinbase_api_call_count=None,
            call_count_exact=False,
            observed_at=None,
            fresh_until=None,
            evidence_sha256=None,
            diagnostic_code="automation_spot_eligibility_invocation_started",
            audit_id=AUDIT_ID,
            correlation_id=command.correlation_id,
            started_at=datetime.now(timezone.utc).isoformat(),
            finalized_at=None,
        )
        attempts.append(record)
        return AutomationStoreMutation(
            record,
            AUDIT_ID,
            command.correlation_id,
        )

    def finalize(run_id, *, category, command, **kwargs):
        raw.calls.append(
            (
                "finalize_spot_eligibility_attempt",
                (run_id,),
                {"category": category, "command": command, **kwargs},
            )
        )
        index = next(
            i for i, item in enumerate(attempts) if item.category == category
        )
        record = replace(
            attempts[index],
            outcome=kwargs["outcome"],
            eligible=kwargs["eligible"],
            coinbase_api_call_count=kwargs["coinbase_api_call_count"],
            call_count_exact=kwargs["call_count_exact"],
            observed_at=kwargs["observed_at"].isoformat(),
            fresh_until=kwargs["fresh_until"].isoformat(),
            evidence_sha256=kwargs["evidence_sha256"],
            diagnostic_code=(
                f"automation_spot_eligibility_{kwargs['outcome'].lower()}"
            ),
            portfolio_id_sha256=kwargs["portfolio_id_sha256"],
            finalized_at=datetime.now(timezone.utc).isoformat(),
        )
        attempts[index] = record
        if category == APPROVED_SPOT_ELIGIBILITY_ORDER[-1].value:
            raw.cycles = (
                replace(
                    raw.cycles[0],
                    state="SUCCEEDED",
                    coinbase_api_call_count=7,
                    call_count_exact=True,
                    fresh_until=min(
                        str(item.fresh_until) for item in attempts
                    ),
                    diagnostic_code=(
                        "automation_spot_eligibility_cycle_succeeded"
                    ),
                    finalized_at=datetime.now(timezone.utc).isoformat(),
                ),
            )
            raw.current_run = replace(
                raw.current_run,
                state=OperatorAutomationRunState.BLOCKED,
                diagnostic_code=(
                    "automation_active_order_catalog_read_not_authorized"
                ),
            )
        return AutomationStoreMutation(
            record,
            AUDIT_ID,
            command.correlation_id,
        )

    raw.resume_spot_source_gated_run = resume
    raw.start_spot_eligibility_attempt = start
    raw.finalize_spot_eligibility_attempt = finalize
    raw.list_spot_eligibility_attempts = (
        lambda run_id, cycle_number=None: tuple(attempts)
    )
    reader = _SuccessfulEligibilityReader()
    adapter = PostgresOperatorAutomationRepositoryAdapter(
        raw,
        spot_eligibility_reader_factory=lambda **_kwargs: reader,
    )

    result = adapter.refresh_spot_eligibility(
        run_id=RUN_ID,
        request={
            "confirm_approved_eligibility_reads": True,
            "confirm_unknown_consumes_cycle": True,
            "expected_plan_sha256": raw.plan.plan_sha256,
            "reason": "Refresh this exact source-gated run",
        },
        context=_context().model_copy(
            update={
                "operator_intent": "refresh_automation_spot_eligibility"
            }
        ),
    )

    assert reader.calls == [
        "read_api_key_permissions",
        "read_portfolio_catalog",
        "read_account_wallet_balances",
        "read_product_metadata",
        "read_best_bid_ask",
        "read_fee_summary",
        "read_exact_order_reconciliation",
    ]
    assert result.entity["state"] == "BLOCKED"
    assert result.entity["diagnostic_code"] == (
        "automation_active_order_catalog_read_not_authorized"
    )
    assert result.entity["eligibility"]["eligible"] is True
    assert result.entity["live_execution_available"] is False
    assert result.entity["allowed_actions"] == ["REFRESH_ELIGIBILITY"]
    assert result.coinbase_api_call_count == 7
    assert result.call_count_exact is True
    assert result.replayed is False
    assert [name for name, _args, _kwargs in raw.calls].count(
        "start_spot_eligibility_attempt"
    ) == 7
    assert [name for name, _args, _kwargs in raw.calls].count(
        "finalize_spot_eligibility_attempt"
    ) == 7


def test_adapter_resumes_only_the_exact_source_gated_plan_without_service_exposure():
    raw = _RawRepository()
    raw.plan = _plan()
    raw.current_run = _run(
        state=OperatorAutomationRunState.BLOCKED,
        diagnostic_code="automation_active_order_catalog_read_not_authorized",
        job_kind=OperatorAutomationJobKind.SPOT_CAMPAIGN,
    )
    context = _context().model_copy(
        update={
            "operator_intent": "resume_automation_spot_source_gated_run",
        }
    )

    result = PostgresOperatorAutomationRepositoryAdapter(
        raw
    ).resume_spot_source_gated_run(
        run_id=RUN_ID,
        expected_plan_sha256=raw.plan.plan_sha256,
        context=context,
    )

    assert [call[0] for call in raw.calls] == [
        "resume_spot_source_gated_run",
        "get_spot_single_child_plan",
        "list_spot_eligibility_attempts",
        "list_spot_eligibility_cycles",
        "get_spot_run_execution",
    ]
    resume_call = raw.calls[0]
    assert resume_call[2]["expected_plan_sha256"] == raw.plan.plan_sha256
    command = resume_call[2]["command"]
    assert command.idempotency_key == context.idempotency_key
    assert command.actor_id == context.actor_id
    assert command.correlation_id == context.correlation_id
    assert command.operator_intent == context.operator_intent
    assert result.entity["state"] == "PREPARING"
    assert result.entity["diagnostic_code"] == (
        "automation_spot_source_gate_resumed"
    )
    assert result.entity["coinbase_api_call_count"] == 0
    assert result.entity["create_call_count"] == 0
    assert result.entity["cancel_call_count"] == 0
    AutomationRunItem.model_validate(result.entity)
    AutomationRunEventItem.model_validate(
        {
            "event_id": "36371b41-f16e-4dad-83cc-946055440c62",
            "run_id": RUN_ID,
            "sequence": 4,
            "from_state": "BLOCKED",
            "state": "PREPARING",
            "diagnostic_code": "automation_spot_source_gate_resumed",
            "audit_id": AUDIT_ID,
            "correlation_id": context.correlation_id,
            "recorded_at": NOW,
        }
    )

    assert not hasattr(
        OperatorAutomationService,
        "resume_spot_source_gated_run",
    )
    assert "resume_spot_source_gated_run" not in (
        OperatorAutomationRepository.__dict__
    )


def test_definition_readback_removes_global_run_action_with_one_goal_query():
    raw = _RawRepository()
    raw.spot_goal_run_claimed = True
    first = replace(
        _definition(
            state=OperatorAutomationDefinitionState.ENABLED,
            job_kind=OperatorAutomationJobKind.SPOT_CAMPAIGN,
        ),
        definition_id="3f744264-8d18-46a2-b89d-f0c206216515",
    )
    second = replace(
        first,
        definition_id="4f744264-8d18-46a2-b89d-f0c206216515",
    )
    raw.list_definitions = lambda **kwargs: (
        raw.calls.append(("list_definitions", (), kwargs))
        or AutomationStorePage(items=(first, second), total_count=2)
    )
    raw.get_spot_single_child_plan = lambda definition_id, revision: (
        raw.calls.append(
            ("get_spot_single_child_plan", (definition_id, revision), {})
        )
        or replace(_plan(), definition_id=definition_id)
    )
    adapter = PostgresOperatorAutomationRepositoryAdapter(raw)

    page = adapter.list_definitions(
        domain="SPOT",
        job_kind="SPOT_CAMPAIGN",
        lifecycle_state="ENABLED",
        limit=25,
        offset=0,
    )

    assert len(page.items) == 2
    assert all("RUN_ONCE" not in item["allowed_actions"] for item in page.items)
    assert [call[0] for call in raw.calls].count(
        "has_spot_single_child_run"
    ) == 1


def test_adapter_has_no_constructor_switch_or_gateway_to_bypass_source_gate():
    raw = _RawRepository()

    with pytest.raises(TypeError):
        PostgresOperatorAutomationRepositoryAdapter(
            raw,
            active_order_catalog_read_authorized=True,
        )
    with pytest.raises(TypeError):
        PostgresOperatorAutomationRepositoryAdapter(
            raw,
            spot_execution_gateway=object(),
        )

    adapter = PostgresOperatorAutomationRepositoryAdapter(raw)
    assert not hasattr(adapter, "active_order_catalog_read_authorized")
    assert not hasattr(adapter, "spot_execution_gateway")
    assert not hasattr(adapter, "place_single_child")


def test_run_projection_reports_lifetime_eligibility_calls_across_all_cycles():
    raw = _RawRepository()
    raw.plan = _plan()
    raw.current_run = _run(
        state=OperatorAutomationRunState.PREPARING,
        diagnostic_code="preparing",
        job_kind=OperatorAutomationJobKind.SPOT_CAMPAIGN,
    )
    attempts = tuple(
        AutomationSpotEligibilityAttemptRecord(
            run_id=RUN_ID,
            cycle_number=cycle,
            category=category,
            allowance_consumed=True,
            outcome="SUCCEEDED",
            eligible=True,
            coinbase_api_call_count=1,
            call_count_exact=True,
            observed_at=NOW,
            fresh_until="2099-07-20T12:00:00+00:00",
            evidence_sha256="f" * 64,
            diagnostic_code="automation_spot_eligibility_succeeded",
            audit_id=AUDIT_ID,
            correlation_id="adapter-correlation-1",
            started_at=NOW,
            finalized_at=NOW,
            portfolio_id_sha256=(
                raw.plan.portfolio_id_sha256
                if category == "PORTFOLIO_CATALOG"
                else None
            ),
        )
        for cycle in (1, 2)
        for category in AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES
    )
    raw.list_spot_eligibility_attempts = lambda run_id, cycle_number=None: (
        attempts
    )
    raw.cycles = (
        _eligibility_cycle(cycle_number=1, state="SUCCEEDED"),
        _eligibility_cycle(cycle_number=2, state="SUCCEEDED"),
    )

    projected = PostgresOperatorAutomationRepositoryAdapter(raw)._run(
        raw.current_run
    )

    assert projected["eligibility"]["cycle_number"] == 2
    assert projected["eligibility"]["coinbase_api_call_count"] == 7
    assert projected["coinbase_api_call_count"] == 14
    assert projected["call_count_exact"] is True


def test_run_projection_can_bind_an_exact_replayed_terminal_cycle():
    raw = _RawRepository()
    raw.plan = _plan()
    raw.current_run = _run(
        state=OperatorAutomationRunState.PREPARING,
        diagnostic_code="automation_spot_source_gate_resumed",
        job_kind=OperatorAutomationJobKind.SPOT_CAMPAIGN,
    )
    attempts = tuple(
        AutomationSpotEligibilityAttemptRecord(
            run_id=RUN_ID,
            cycle_number=cycle,
            category=category,
            allowance_consumed=True,
            outcome="SUCCEEDED",
            eligible=True,
            coinbase_api_call_count=1,
            call_count_exact=True,
            observed_at=NOW,
            fresh_until="2099-07-20T12:00:00+00:00",
            evidence_sha256=(str(cycle) * 64),
            diagnostic_code="automation_spot_eligibility_succeeded",
            audit_id=(AUDIT_ID if cycle == 1 else SECOND_AUDIT_ID),
            correlation_id=f"adapter-correlation-{cycle}",
            started_at=NOW,
            finalized_at=NOW,
            portfolio_id_sha256=(
                raw.plan.portfolio_id_sha256
                if category == "PORTFOLIO_CATALOG"
                else None
            ),
        )
        for cycle in (1, 2)
        for category in AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES
    )
    raw.list_spot_eligibility_attempts = lambda run_id, cycle_number=None: (
        attempts
    )
    raw.cycles = (
        replace(
            _eligibility_cycle(cycle_number=1, state="SUCCEEDED"),
            audit_id=AUDIT_ID,
            correlation_id="adapter-correlation-1",
        ),
        replace(
            _eligibility_cycle(cycle_number=2, state="SUCCEEDED"),
            audit_id=SECOND_AUDIT_ID,
            correlation_id="adapter-correlation-2",
        ),
    )

    projected = PostgresOperatorAutomationRepositoryAdapter(raw)._run(
        raw.current_run,
        eligibility_cycle_number=1,
    )

    assert projected["eligibility"]["cycle_number"] == 1
    assert projected["eligibility"]["coinbase_api_call_count"] == 7
    assert projected["coinbase_api_call_count"] == 14
    assert projected["call_count_exact"] is True


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

    projected = PostgresOperatorAutomationRepositoryAdapter(
        _RawRepository()
    )._definition(record)

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


def test_default_service_is_structurally_source_gated(monkeypatch):
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
    assert not hasattr(service.repository, "spot_execution_gateway")
    assert not hasattr(
        service.repository,
        "active_order_catalog_read_authorized",
    )
    assert service.get_control_plane().control_plane.posture.value == "ACTIVE"
