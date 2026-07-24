from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from application.admin_api.operator_hotpoint_control import (
    HOTPOINT_CONTROL_OPERATOR_INTENT,
    HOTPOINT_GOAL_ID,
    HOTPOINT_RUN_OPERATOR_INTENT,
    HOTPOINT_SAFE_CLOSEOUT_OPERATOR_INTENT,
    HotpointCancelExecution,
    HotpointCancelPlan,
    HotpointCancelState,
    HotpointControlAction,
    HotpointCreateState,
    HotpointKillSwitchState,
    HotpointPlacementExecution,
    HotpointPlacementOutcome,
    HotpointPlacementPlan,
    HotpointScopePolicy,
    HotpointWindowState,
    FUTURES_HOTPOINT_SCOPE_POLICY,
    OperatorHotpointControlError,
    OperatorHotpointControlRecord,
    OperatorHotpointControlService,
    OperatorHotpointRequestContext,
    SPOT_HOTPOINT_SCOPE_POLICY,
)


PARENT_ID = "11111111-1111-4111-8111-111111111111"
CHILD_ID = "22222222-2222-4222-8222-222222222222"
WINDOW_ID = "33333333-3333-4333-8333-333333333333"
CLAIM_ID = "44444444-4444-4444-8444-444444444444"


def _record(
    *,
    revision: int = 1,
    kill_switch_state: HotpointKillSwitchState = (
        HotpointKillSwitchState.ENABLED
    ),
    window_state: HotpointWindowState = HotpointWindowState.ARMED,
    create_state: HotpointCreateState = HotpointCreateState.NOT_CLAIMED,
    child_client_order_id: str | None = None,
) -> OperatorHotpointControlRecord:
    return OperatorHotpointControlRecord(
        goal_id=HOTPOINT_GOAL_ID,
        revision=revision,
        kill_switch_state=kill_switch_state,
        window_state=window_state,
        parent_client_order_id=PARENT_ID,
        product_id="BTC-USDC",
        side="BUY",
        window_id=WINDOW_ID,
        window_started_at="2026-07-24T00:00:00+00:00",
        window_expires_at="2026-07-24T00:01:00+00:00",
        create_state=create_state,
        cancel_state=HotpointCancelState.NOT_CLAIMED,
        create_exchange_invoked=None,
        cancel_exchange_invoked=None,
        placement_claim_id=(
            CLAIM_ID
            if create_state is not HotpointCreateState.NOT_CLAIMED
            else None
        ),
        cancel_claim_id=None,
        child_client_order_id=child_client_order_id,
        diagnostic_code="operator_hotpoint_window_armed",
        actor_id="operator-1",
        roles=("admin", "trader"),
        correlation_id="corr-1",
        audit_id="55555555-5555-4555-8555-555555555555",
        recorded_at="2026-07-24T00:00:00+00:00",
        updated_at="2026-07-24T00:00:00+00:00",
    )


def _plan() -> HotpointPlacementPlan:
    return HotpointPlacementPlan(
        goal_id=HOTPOINT_GOAL_ID,
        window_id=WINDOW_ID,
        placement_claim_id=CLAIM_ID,
        parent_client_order_id=PARENT_ID,
        child_client_order_id=CHILD_ID,
        product_id="BTC-USDC",
        side="BUY",
        base_size=Decimal("0.00001"),
        limit_price=Decimal("100000"),
        post_only=True,
        submitted_notional_usdc=Decimal("1.00000"),
        possible_execution_notional_usdc=Decimal("1.00000"),
        max_submitted_notional_usdc=Decimal("3.10"),
        max_possible_execution_notional_usdc=Decimal("1.00"),
        evidence_sha256="a" * 64,
        portfolio_id="66666666-6666-4666-8666-666666666666",
        actor_id="operator-1",
        roles=("admin", "trader"),
        correlation_id="corr-1",
        audit_id="55555555-5555-4555-8555-555555555555",
    )


def _context(
    *,
    operator_intent: str = HOTPOINT_CONTROL_OPERATOR_INTENT,
    roles: tuple[str, ...] = ("admin", "trader"),
) -> OperatorHotpointRequestContext:
    return OperatorHotpointRequestContext(
        actor_id="operator-1",
        roles=roles,
        idempotency_key="idem-1",
        correlation_id="corr-1",
        audit_id="55555555-5555-4555-8555-555555555555",
        operator_intent=operator_intent,
    )


class _Repository:
    def __init__(self) -> None:
        self.record = _record()
        self.transition_calls: list[dict[str, object]] = []
        self.claim_calls: list[dict[str, object]] = []
        self.finalize_calls: list[dict[str, object]] = []
        self.cancel_claim_calls: list[dict[str, object]] = []
        self.cancel_finalize_calls: list[dict[str, object]] = []
        self.claim_result: tuple[
            OperatorHotpointControlRecord,
            HotpointPlacementPlan,
        ] | None = (
            replace(
                self.record,
                create_state=HotpointCreateState.CLAIMED,
                placement_claim_id=CLAIM_ID,
                diagnostic_code="operator_hotpoint_create_claimed",
            ),
            _plan(),
        )

    def read(self) -> OperatorHotpointControlRecord:
        return self.record

    def transition_control(self, **kwargs):
        self.transition_calls.append(kwargs)
        return self.record

    def claim_placement(self, **kwargs):
        self.claim_calls.append(kwargs)
        return self.claim_result

    def finalize_placement(self, **kwargs):
        self.finalize_calls.append(kwargs)
        terminal = {
            HotpointPlacementOutcome.ACCEPTED: HotpointCreateState.ACCEPTED,
            HotpointPlacementOutcome.REJECTED: HotpointCreateState.REJECTED,
            HotpointPlacementOutcome.UNKNOWN: HotpointCreateState.UNKNOWN,
        }[kwargs["outcome"]]
        self.record = replace(
            self.record,
            window_state=HotpointWindowState.TERMINAL,
            create_state=terminal,
            placement_claim_id=CLAIM_ID,
            child_client_order_id=(
                CHILD_ID
                if terminal is HotpointCreateState.ACCEPTED
                else None
            ),
            diagnostic_code=kwargs["diagnostic_code"],
        )
        return self.record

    def claim_cancel(self, **kwargs):
        self.cancel_claim_calls.append(kwargs)
        plan = HotpointCancelPlan(
            goal_id=HOTPOINT_GOAL_ID,
            cancel_claim_id="77777777-7777-4777-8777-777777777777",
            placement_claim_id=CLAIM_ID,
            parent_client_order_id=PARENT_ID,
            child_client_order_id=CHILD_ID,
            product_id="BTC-USDC",
            plan_sha256="a" * 64,
            portfolio_id="66666666-6666-4666-8666-666666666666",
            actor_id="operator-1",
            roles=("admin", "trader"),
            correlation_id="corr-1",
            audit_id="55555555-5555-4555-8555-555555555555",
        )
        self.record = replace(
            self.record,
            create_state=HotpointCreateState.ACCEPTED,
            child_client_order_id=CHILD_ID,
            placement_claim_id=CLAIM_ID,
            cancel_state=HotpointCancelState.CLAIMED,
            cancel_claim_id=plan.cancel_claim_id,
        )
        return self.record, plan

    def finalize_cancel(self, **kwargs):
        self.cancel_finalize_calls.append(kwargs)
        state = {
            HotpointPlacementOutcome.ACCEPTED: HotpointCancelState.ACCEPTED,
            HotpointPlacementOutcome.REJECTED: HotpointCancelState.REJECTED,
            HotpointPlacementOutcome.UNKNOWN: HotpointCancelState.UNKNOWN,
        }[kwargs["outcome"]]
        self.record = replace(
            self.record,
            cancel_state=state,
            diagnostic_code=kwargs["diagnostic_code"],
        )
        return self.record


def test_enable_requires_explicit_future_single_child_authority() -> None:
    repository = _Repository()
    service = OperatorHotpointControlService(
        repository=repository,
        placement_executor=lambda _plan: None,
    )

    with pytest.raises(
        OperatorHotpointControlError,
        match="operator_hotpoint_enable_authority_required",
    ):
        service.control(
            action=HotpointControlAction.ENABLE,
            expected_revision=1,
            confirm_control_action=True,
            authorize_one_bounded_trigger_window=False,
            acknowledge_unknown_outcome_consumes_create_allowance=True,
            acknowledge_backend_derives_child_terms=True,
            context=_context(),
        )

    assert repository.transition_calls == []


def test_control_forwards_no_browser_order_terms() -> None:
    repository = _Repository()
    service = OperatorHotpointControlService(
        repository=repository,
        placement_executor=lambda _plan: None,
    )

    result = service.control(
        action=HotpointControlAction.ENABLE,
        expected_revision=1,
        confirm_control_action=True,
        authorize_one_bounded_trigger_window=True,
        acknowledge_unknown_outcome_consumes_create_allowance=True,
        acknowledge_backend_derives_child_terms=True,
        context=_context(),
    )

    assert result.goal_id == HOTPOINT_GOAL_ID
    assert repository.transition_calls == [
        {
            "action": HotpointControlAction.ENABLE,
            "expected_revision": 1,
            "authorize_one_bounded_trigger_window": True,
            "acknowledge_unknown_outcome_consumes_create_allowance": True,
            "acknowledge_backend_derives_child_terms": True,
            "idempotency_key": "idem-1",
            "actor_id": "operator-1",
            "roles": ("admin", "trader"),
            "correlation_id": "corr-1",
            "audit_id": "55555555-5555-4555-8555-555555555555",
        }
    ]


def test_run_claims_once_and_terminalizes_accepted_child() -> None:
    repository = _Repository()
    executions: list[HotpointPlacementPlan] = []

    def execute(plan: HotpointPlacementPlan) -> HotpointPlacementExecution:
        executions.append(plan)
        return HotpointPlacementExecution(
            outcome=HotpointPlacementOutcome.ACCEPTED,
            child_client_order_id=CHILD_ID,
            diagnostic_code="operator_hotpoint_create_accepted",
            exchange_invoked=True,
        )

    service = OperatorHotpointControlService(
        repository=repository,
        placement_executor=execute,
    )
    result = service.run_once(
        context=_context(operator_intent=HOTPOINT_RUN_OPERATOR_INTENT),
    )

    assert executions == [_plan()]
    assert result.create_state is HotpointCreateState.ACCEPTED
    assert result.window_state is HotpointWindowState.TERMINAL
    assert result.child_client_order_id == CHILD_ID
    assert repository.finalize_calls == [
        {
            "placement_claim_id": CLAIM_ID,
            "outcome": HotpointPlacementOutcome.ACCEPTED,
            "child_client_order_id": CHILD_ID,
            "diagnostic_code": "operator_hotpoint_create_accepted",
            "exchange_invoked": True,
        }
    ]


def test_run_with_no_trigger_evidence_is_call_free_and_remains_armed() -> None:
    repository = _Repository()
    repository.claim_result = None
    service = OperatorHotpointControlService(
        repository=repository,
        placement_executor=lambda _plan: pytest.fail("executor called"),
    )

    result = service.run_once(
        context=_context(operator_intent=HOTPOINT_RUN_OPERATOR_INTENT),
    )

    assert result.window_state is HotpointWindowState.ARMED
    assert result.create_state is HotpointCreateState.NOT_CLAIMED
    assert repository.finalize_calls == []


def test_executor_exception_is_terminal_unknown_and_cannot_be_replayed() -> None:
    repository = _Repository()
    calls = 0

    def execute(_plan: HotpointPlacementPlan) -> HotpointPlacementExecution:
        nonlocal calls
        calls += 1
        raise RuntimeError("withheld transport detail")

    service = OperatorHotpointControlService(
        repository=repository,
        placement_executor=execute,
    )
    result = service.run_once(
        context=_context(operator_intent=HOTPOINT_RUN_OPERATOR_INTENT),
    )

    assert calls == 1
    assert result.create_state is HotpointCreateState.UNKNOWN
    assert repository.finalize_calls[0]["diagnostic_code"] == (
        "operator_hotpoint_create_outcome_unknown"
    )

    repository.claim_result = None
    replay = service.run_once(
        context=_context(operator_intent=HOTPOINT_RUN_OPERATOR_INTENT),
    )
    assert replay.create_state is HotpointCreateState.UNKNOWN
    assert calls == 1


def test_run_rejects_browser_intent_or_missing_operator_role() -> None:
    repository = _Repository()
    service = OperatorHotpointControlService(
        repository=repository,
        placement_executor=lambda _plan: pytest.fail("executor called"),
    )

    for context in (
        _context(operator_intent="place_manual_order"),
        _context(
            operator_intent=HOTPOINT_RUN_OPERATOR_INTENT,
            roles=("viewer",),
        ),
    ):
        with pytest.raises(
            OperatorHotpointControlError,
            match="operator_hotpoint_run_authority_invalid",
        ):
            service.run_once(context=context)


def test_safe_closeout_claims_and_cancels_only_the_exact_child() -> None:
    repository = _Repository()
    executions = []

    def cancel(plan: HotpointCancelPlan) -> HotpointCancelExecution:
        executions.append(plan)
        return HotpointCancelExecution(
            outcome=HotpointPlacementOutcome.ACCEPTED,
            child_client_order_id=CHILD_ID,
            diagnostic_code="operator_hotpoint_cancel_accepted",
            exchange_invoked=True,
        )

    service = OperatorHotpointControlService(
        repository=repository,
        placement_executor=lambda _plan: pytest.fail("create called"),
        cancel_executor=cancel,
    )
    result = service.safe_closeout(
        confirm_exact_child_safe_closeout=True,
        acknowledge_unknown_outcome_consumes_cancel_allowance=True,
        context=_context(
            operator_intent=HOTPOINT_SAFE_CLOSEOUT_OPERATOR_INTENT,
        ),
    )

    assert len(executions) == 1
    assert executions[0].child_client_order_id == CHILD_ID
    assert result.cancel_state is HotpointCancelState.ACCEPTED
    assert repository.cancel_finalize_calls == [
        {
            "cancel_claim_id": "77777777-7777-4777-8777-777777777777",
            "outcome": HotpointPlacementOutcome.ACCEPTED,
            "diagnostic_code": "operator_hotpoint_cancel_accepted",
            "exchange_invoked": True,
        }
    ]


def test_spot_and_futures_scope_policies_are_separate_backend_authorities() -> None:
    assert SPOT_HOTPOINT_SCOPE_POLICY == HotpointScopePolicy(
        domain="SPOT",
        portfolio_profile_alias="Test",
        product_id="BTC-USDC",
        max_submitted_notional_usdc=Decimal("3.10"),
        max_possible_execution_notional_usdc=Decimal("1.00"),
        max_turnover_notional_usdc=None,
        exact_size=None,
        strict_caps=False,
    )
    assert FUTURES_HOTPOINT_SCOPE_POLICY == HotpointScopePolicy(
        domain="FUTURES",
        portfolio_profile_alias="Default",
        product_id="AVP-20DEC30-CDE",
        max_submitted_notional_usdc=Decimal("100"),
        max_possible_execution_notional_usdc=Decimal("150"),
        max_turnover_notional_usdc=Decimal("300"),
        exact_size=Decimal("1"),
        strict_caps=True,
    )


def test_futures_scope_accepts_only_one_contract_v3_plan() -> None:
    repository = _Repository()
    futures_record = replace(
        repository.record,
        product_id="AVP-20DEC30-CDE",
    )
    futures_plan = replace(
        _plan(),
        product_id="AVP-20DEC30-CDE",
        base_size=Decimal("1"),
        limit_price=Decimal("49"),
        submitted_notional_usdc=Decimal("49"),
        possible_execution_notional_usdc=Decimal("49"),
        max_submitted_notional_usdc=Decimal("100"),
        max_possible_execution_notional_usdc=Decimal("150"),
    )
    repository.record = futures_record
    repository.claim_result = (
        replace(
            futures_record,
            create_state=HotpointCreateState.CLAIMED,
            placement_claim_id=CLAIM_ID,
            diagnostic_code="operator_hotpoint_create_claimed",
        ),
        futures_plan,
    )
    executions: list[HotpointPlacementPlan] = []
    service = OperatorHotpointControlService(
        repository=repository,
        policy=FUTURES_HOTPOINT_SCOPE_POLICY,
        placement_executor=lambda plan: (
            executions.append(plan)
            or HotpointPlacementExecution(
                outcome=HotpointPlacementOutcome.ACCEPTED,
                child_client_order_id=CHILD_ID,
                diagnostic_code="operator_hotpoint_create_accepted",
                exchange_invoked=True,
            )
        ),
    )

    result = service.run_once(
        context=_context(operator_intent=HOTPOINT_RUN_OPERATOR_INTENT),
    )

    assert executions == [futures_plan]
    assert result.create_state is HotpointCreateState.ACCEPTED

    repository = _Repository()
    repository.record = futures_record
    repository.claim_result = (
        replace(
            futures_record,
            create_state=HotpointCreateState.CLAIMED,
            placement_claim_id=CLAIM_ID,
            diagnostic_code="operator_hotpoint_create_claimed",
        ),
        _plan(),
    )
    service = OperatorHotpointControlService(
        repository=repository,
        policy=FUTURES_HOTPOINT_SCOPE_POLICY,
        placement_executor=lambda _plan: pytest.fail("spot plan executed"),
    )
    with pytest.raises(
        OperatorHotpointControlError,
        match="operator_hotpoint_plan_invalid",
    ):
        service.run_once(
            context=_context(operator_intent=HOTPOINT_RUN_OPERATOR_INTENT),
        )
