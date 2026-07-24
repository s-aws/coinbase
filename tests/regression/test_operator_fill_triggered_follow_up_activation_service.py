from __future__ import annotations

from dataclasses import replace
from contextlib import contextmanager
from types import SimpleNamespace
import threading

import pytest

from application.admin_api.operator_fill_triggered_follow_up_activation import (
    FILL_TRIGGERED_FOLLOW_UP_GOAL_ID,
    FillTriggeredActivationControlAction,
    FillTriggeredActivationControlState,
    FillTriggeredActivationRecord,
    FillTriggeredActivationRequestContext,
    FillTriggeredActivationTriggerState,
    FillTriggeredFollowUpActivationService,
    GoalBoundFillTriggeredFollowUpMaterializer,
    recover_stranded_fill_triggered_follow_ups,
)
from application.admin_api.operator_follow_up_materialization import (
    ChildExchangeState,
    FollowUpMaterializationRecord,
    MaterializationOperationResult,
    MaterializationRecordState,
    OperatorFollowUpMaterializationError,
)


SOURCE_ID = "00000000-0000-4000-8000-000000000081"
INTENT_ID = "00000000-0000-4000-8000-000000000082"
CLAIM_ID = "00000000-0000-4000-8000-000000000083"
AUDIT_ID = "00000000-0000-4000-8000-000000000084"


def _record(
    *,
    control_state: FillTriggeredActivationControlState = (
        FillTriggeredActivationControlState.DISABLED
    ),
    trigger_state: FillTriggeredActivationTriggerState = (
        FillTriggeredActivationTriggerState.UNCLAIMED
    ),
    revision: int = 0,
) -> FillTriggeredActivationRecord:
    return FillTriggeredActivationRecord(
        goal_id=FILL_TRIGGERED_FOLLOW_UP_GOAL_ID,
        source_client_order_id=SOURCE_ID,
        follow_up_intent_id=INTENT_ID,
        control_state=control_state,
        trigger_state=trigger_state,
        revision=revision,
        delegated_create_authority=(
            control_state is FillTriggeredActivationControlState.ENABLED
        ),
        trigger_claim_id=(CLAIM_ID if trigger_state.is_claimed else None),
        trigger_evidence_sha256=("a" * 64 if trigger_state.is_claimed else None),
        materialization_state=None,
        child_client_order_id=None,
        diagnostic_code="fill_triggered_follow_up_disabled",
        actor_id="operator-1",
        roles=("admin", "trader"),
        correlation_id="corr-1",
        audit_id=AUDIT_ID,
        recorded_at="2026-07-24T00:00:00+00:00",
        updated_at="2026-07-24T00:00:00+00:00",
    )


class _Repository:
    def __init__(self, record: FillTriggeredActivationRecord) -> None:
        self.record = record
        self.control_commands: list[dict] = []
        self.claim_calls: list[dict] = []
        self.finalize_calls: list[dict] = []

    def read(self, source_client_order_id: str) -> FillTriggeredActivationRecord:
        assert source_client_order_id == SOURCE_ID
        return self.record

    def transition_control(self, **kwargs) -> FillTriggeredActivationRecord:
        self.control_commands.append(kwargs)
        action = kwargs["action"]
        target = {
            FillTriggeredActivationControlAction.ENABLE: (
                FillTriggeredActivationControlState.ENABLED
            ),
            FillTriggeredActivationControlAction.DISABLE: (
                FillTriggeredActivationControlState.DISABLED
            ),
            FillTriggeredActivationControlAction.PAUSE: (
                FillTriggeredActivationControlState.PAUSED
            ),
            FillTriggeredActivationControlAction.DRAIN: (
                FillTriggeredActivationControlState.DRAINED
            ),
        }[action]
        self.record = replace(
            self.record,
            control_state=target,
            revision=self.record.revision + 1,
            delegated_create_authority=(
                action is FillTriggeredActivationControlAction.ENABLE
            ),
            actor_id=kwargs["actor_id"],
            roles=kwargs["roles"],
            correlation_id=kwargs["correlation_id"],
            audit_id=kwargs["audit_id"],
            diagnostic_code=f"fill_triggered_follow_up_{target.value.lower()}",
        )
        return self.record

    def claim_full_fill_trigger(self, **kwargs):
        self.claim_calls.append(kwargs)
        if self.record.control_state is not FillTriggeredActivationControlState.ENABLED:
            return None
        if (
            self.record.trigger_state
            is not FillTriggeredActivationTriggerState.UNCLAIMED
        ):
            return None
        self.record = replace(
            self.record,
            trigger_state=FillTriggeredActivationTriggerState.CLAIMED,
            trigger_claim_id=CLAIM_ID,
            trigger_evidence_sha256=kwargs["trigger_evidence_sha256"],
            diagnostic_code="fill_triggered_follow_up_claimed",
        )
        return self.record

    def finalize_trigger(self, **kwargs):
        self.finalize_calls.append(kwargs)
        self.record = replace(
            self.record,
            trigger_state=kwargs["trigger_state"],
            materialization_state=kwargs["materialization_state"],
            child_client_order_id=kwargs.get("child_client_order_id"),
            diagnostic_code=kwargs["diagnostic_code"],
        )
        return self.record


class _Materializer:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict] = []

    def materialize(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("withheld materializer failure")
        return {
            "materialization_state": "CREATE_ACCEPTED_NONTERMINAL",
            "child_client_order_id": "00000000-0000-4000-8000-000000000085",
            "diagnostic_code": "fill_triggered_follow_up_create_accepted",
        }


def _context() -> FillTriggeredActivationRequestContext:
    return FillTriggeredActivationRequestContext(
        actor_id="operator-1",
        roles=("admin", "trader"),
        idempotency_key="goal8-control-key",
        correlation_id="corr-goal8-control",
        audit_id=AUDIT_ID,
        operator_intent="control_fill_triggered_follow_up",
    )


def test_enable_is_a_revision_bound_explicit_operator_control() -> None:
    repository = _Repository(_record())
    service = FillTriggeredFollowUpActivationService(
        repository=repository,
        materializer_factory=lambda: _Materializer(),
    )

    result = service.control(
        source_client_order_id=SOURCE_ID,
        action=FillTriggeredActivationControlAction.ENABLE,
        expected_revision=0,
        confirm_control_action=True,
        authorize_single_fill_triggered_materialization=True,
        acknowledge_unknown_outcome_consumes_create_allowance=True,
        acknowledge_child_terms_are_backend_derived=True,
        context=_context(),
    )

    assert result.control_state is FillTriggeredActivationControlState.ENABLED
    assert result.revision == 1
    assert repository.control_commands == [
        {
            "source_client_order_id": SOURCE_ID,
            "action": FillTriggeredActivationControlAction.ENABLE,
            "expected_revision": 0,
            "authorize_single_fill_triggered_materialization": True,
            "acknowledge_unknown_outcome_consumes_create_allowance": True,
            "acknowledge_child_terms_are_backend_derived": True,
            "idempotency_key": "goal8-control-key",
            "actor_id": "operator-1",
            "roles": ("admin", "trader"),
            "correlation_id": "corr-goal8-control",
            "audit_id": AUDIT_ID,
        }
    ]


def test_enable_requires_explicit_delegated_create_authority() -> None:
    repository = _Repository(_record())
    service = FillTriggeredFollowUpActivationService(
        repository=repository,
        materializer_factory=lambda: _Materializer(),
    )

    with pytest.raises(
        Exception,
        match="fill_triggered_follow_up_enable_authority_required",
    ):
        service.control(
            source_client_order_id=SOURCE_ID,
            action=FillTriggeredActivationControlAction.ENABLE,
            expected_revision=0,
            confirm_control_action=True,
            authorize_single_fill_triggered_materialization=False,
            acknowledge_unknown_outcome_consumes_create_allowance=False,
            acknowledge_child_terms_are_backend_derived=False,
            context=_context(),
        )

    assert repository.control_commands == []


def test_full_fill_claim_materializes_once_and_finalizes_exact_child() -> None:
    repository = _Repository(
        _record(
            control_state=FillTriggeredActivationControlState.ENABLED,
            revision=1,
        )
    )
    materializer = _Materializer()
    service = FillTriggeredFollowUpActivationService(
        repository=repository,
        materializer_factory=lambda: materializer,
    )

    first = service.dispatch_authoritative_full_fill(
        source_client_order_id=SOURCE_ID,
        trigger_evidence_sha256="b" * 64,
    )
    second = service.dispatch_authoritative_full_fill(
        source_client_order_id=SOURCE_ID,
        trigger_evidence_sha256="b" * 64,
    )

    assert first.trigger_state is FillTriggeredActivationTriggerState.COMPLETED
    assert first.child_client_order_id == (
        "00000000-0000-4000-8000-000000000085"
    )
    assert second.trigger_state is FillTriggeredActivationTriggerState.COMPLETED
    assert len(materializer.calls) == 1
    assert repository.finalize_calls[0]["trigger_claim_id"] == CLAIM_ID


@pytest.mark.parametrize(
    "control_state",
    [
        FillTriggeredActivationControlState.DISABLED,
        FillTriggeredActivationControlState.PAUSED,
        FillTriggeredActivationControlState.DRAINED,
    ],
)
def test_non_enabled_controls_are_call_free(
    control_state: FillTriggeredActivationControlState,
) -> None:
    repository = _Repository(_record(control_state=control_state, revision=1))
    materializer = _Materializer()
    service = FillTriggeredFollowUpActivationService(
        repository=repository,
        materializer_factory=lambda: materializer,
    )

    result = service.dispatch_authoritative_full_fill(
        source_client_order_id=SOURCE_ID,
        trigger_evidence_sha256="c" * 64,
    )

    assert result.control_state is control_state
    assert result.trigger_state is FillTriggeredActivationTriggerState.UNCLAIMED
    assert materializer.calls == []
    assert repository.finalize_calls == []


def test_unknown_materializer_outcome_is_terminal_and_never_replayed() -> None:
    repository = _Repository(
        _record(
            control_state=FillTriggeredActivationControlState.ENABLED,
            revision=1,
        )
    )
    materializer = _Materializer(fail=True)
    service = FillTriggeredFollowUpActivationService(
        repository=repository,
        materializer_factory=lambda: materializer,
    )

    first = service.dispatch_authoritative_full_fill(
        source_client_order_id=SOURCE_ID,
        trigger_evidence_sha256="d" * 64,
    )
    second = service.dispatch_authoritative_full_fill(
        source_client_order_id=SOURCE_ID,
        trigger_evidence_sha256="d" * 64,
    )

    assert first.trigger_state is FillTriggeredActivationTriggerState.UNKNOWN
    assert first.diagnostic_code == "fill_triggered_follow_up_outcome_unknown"
    assert second.trigger_state is FillTriggeredActivationTriggerState.UNKNOWN
    assert len(materializer.calls) == 1


def test_goal_bound_materializer_uses_fresh_backend_owned_authorization() -> None:
    class _Kernel:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def materialize(self, **kwargs):
            raise AssertionError("Goal 8 must not reacquire its invocation guard")

        def materialize_under_existing_invocation_guard(self, **kwargs):
            self.calls.append(kwargs)
            return MaterializationOperationResult(
                record=FollowUpMaterializationRecord(
                    materialization_id="00000000-0000-4000-8000-000000000091",
                    attached_intent_id=INTENT_ID,
                    source_client_order_id=SOURCE_ID,
                    root_client_order_id=SOURCE_ID,
                    child_client_order_id=(
                        "00000000-0000-4000-8000-000000000085"
                    ),
                    state=MaterializationRecordState.CREATE_ACCEPTED,
                    create_idempotency_key_sha256="e" * 64,
                    cancel_idempotency_key_sha256=None,
                    create_call_consumed=True,
                    cancel_call_consumed=False,
                    child_state=ChildExchangeState.ACTIVE,
                    diagnostic_code=(
                        "follow_up_materialization_create_accepted"
                    ),
                    correlation_id="corr-1",
                    audit_id=AUDIT_ID,
                ),
                diagnostic_code="follow_up_materialization_create_accepted",
                replayed=False,
                live_read_ran=True,
                create_call_ran=True,
                cancel_call_ran=False,
            )

    kernel = _Kernel()
    materializer = GoalBoundFillTriggeredFollowUpMaterializer(
        kernel_service=kernel,
        environment="controlled_live",
        invocation_guard_already_held=True,
    )

    result = materializer.materialize(
        source_client_order_id=SOURCE_ID,
        activation=_record(
            control_state=FillTriggeredActivationControlState.ENABLED,
            trigger_state=FillTriggeredActivationTriggerState.CLAIMED,
            revision=1,
        ),
    )

    assert result == {
        "materialization_state": "CREATE_ACCEPTED",
        "child_client_order_id": (
            "00000000-0000-4000-8000-000000000085"
        ),
        "diagnostic_code": "follow_up_materialization_create_accepted",
    }
    call = kernel.calls[0]
    assert call["source_client_order_id"] == SOURCE_ID
    assert (
        call["context"].operator_intent
        == "materialize_enabled_fill_triggered_follow_up"
    )
    assert call["context"].idempotency_key == (
        "fill-triggered:00000000-0000-4000-8000-000000000083:create"
    )
    assert call["request"].authorize_materialization_of_attached_intent is True
    assert (
        call["request"].acknowledge_unknown_outcome_consumes_create_allowance
        is True
    )


def test_known_pre_exchange_materialization_failure_is_terminal_blocked() -> None:
    repository = _Repository(
        _record(
            control_state=FillTriggeredActivationControlState.ENABLED,
            revision=1,
        )
    )

    class _BlockedMaterializer:
        def materialize(self, **_kwargs):
            raise OperatorFollowUpMaterializationError(
                "follow_up_materialization_wallet_check_failed",
                409,
                failure_stage="pre_exchange_evaluation",
                live_coinbase_read_ran=True,
                live_coinbase_orders_ran=False,
                live_exchange_submitted=False,
            )

    service = FillTriggeredFollowUpActivationService(
        repository=repository,
        materializer_factory=lambda: _BlockedMaterializer(),
    )

    result = service.dispatch_authoritative_full_fill(
        source_client_order_id=SOURCE_ID,
        trigger_evidence_sha256="f" * 64,
    )

    assert result.trigger_state is FillTriggeredActivationTriggerState.BLOCKED
    assert result.diagnostic_code == "fill_triggered_follow_up_materialization_blocked"


def test_unknown_materialization_projects_exact_child_from_canonical_ledger() -> None:
    repository = _Repository(
        _record(
            control_state=FillTriggeredActivationControlState.ENABLED,
            revision=1,
        )
    )

    class _UnknownMaterializer:
        def materialize(self, **_kwargs):
            raise OperatorFollowUpMaterializationError(
                "follow_up_materialization_create_outcome_unknown",
                503,
                failure_stage="create_invocation",
                live_coinbase_read_ran=True,
                live_coinbase_orders_ran=True,
                live_exchange_submitted=True,
            )

    service = FillTriggeredFollowUpActivationService(
        repository=repository,
        materializer_factory=lambda: _UnknownMaterializer(),
        recovery_reader=lambda _source_id: SimpleNamespace(
            current_state="CREATE_UNKNOWN_CONSUMED",
            child_client_order_id="00000000-0000-4000-8000-000000000085",
        ),
    )

    result = service.dispatch_authoritative_full_fill(
        source_client_order_id=SOURCE_ID,
        trigger_evidence_sha256="9" * 64,
    )

    assert result.trigger_state is FillTriggeredActivationTriggerState.UNKNOWN
    assert result.child_client_order_id == (
        "00000000-0000-4000-8000-000000000085"
    )
    assert result.diagnostic_code == "fill_triggered_follow_up_outcome_unknown"


def test_startup_recovery_terminalizes_stranded_claim_from_canonical_ledger() -> None:
    repository = _Repository(
        _record(
            control_state=FillTriggeredActivationControlState.ENABLED,
            trigger_state=FillTriggeredActivationTriggerState.CLAIMED,
            revision=1,
        )
    )
    repository.list_claimed = lambda: (repository.record,)

    class _Native:
        @contextmanager
        def follow_up_live_proof_invocation_guard(self, **_kwargs):
            yield

        def read_materialization(self, *_args, **_kwargs):
            return SimpleNamespace(
                attempt=SimpleNamespace(
                    current_state="CREATE_ACCEPTED_NONTERMINAL",
                    child_client_order_id=(
                        "00000000-0000-4000-8000-000000000085"
                    ),
                )
            )

    recovered = recover_stranded_fill_triggered_follow_ups(
        repository=repository,
        native_repository=_Native(),
    )

    assert recovered == 1
    assert repository.record.trigger_state is (
        FillTriggeredActivationTriggerState.COMPLETED
    )
    assert repository.record.child_client_order_id == (
        "00000000-0000-4000-8000-000000000085"
    )


def test_dispatch_owns_goal_guard_from_claim_through_terminal_persistence() -> None:
    repository = _Repository(
        _record(
            control_state=FillTriggeredActivationControlState.ENABLED,
            revision=1,
        )
    )
    repository.list_claimed = lambda: (
        (repository.record,)
        if repository.record.trigger_state
        is FillTriggeredActivationTriggerState.CLAIMED
        else ()
    )
    materializer_entered = threading.Event()
    release_materializer = threading.Event()
    second_guard_attempted = threading.Event()
    second_guard_acquired = threading.Event()

    class _BlockingMaterializer(_Materializer):
        def materialize(self, **kwargs):
            materializer_entered.set()
            assert release_materializer.wait(timeout=5)
            return super().materialize(**kwargs)

    class _Native:
        def __init__(self) -> None:
            self.lock = threading.Lock()
            self.guard_count = 0

        @contextmanager
        def follow_up_live_proof_invocation_guard(self, **_kwargs):
            self.guard_count += 1
            call_number = self.guard_count
            if call_number == 2:
                second_guard_attempted.set()
            with self.lock:
                if call_number == 2:
                    second_guard_acquired.set()
                yield

        def read_materialization(self, *_args, **_kwargs):
            return SimpleNamespace(attempt=None)

    native = _Native()
    service = FillTriggeredFollowUpActivationService(
        repository=repository,
        materializer_factory=lambda: _BlockingMaterializer(),
        invocation_guard_factory=lambda source_id: (
            native.follow_up_live_proof_invocation_guard(
                goal_id=FILL_TRIGGERED_FOLLOW_UP_GOAL_ID,
                source_client_order_id=source_id,
            )
        ),
    )
    dispatch_result: list[FillTriggeredActivationRecord] = []
    recovery_result: list[int] = []
    dispatch_thread = threading.Thread(
        target=lambda: dispatch_result.append(
            service.dispatch_authoritative_full_fill(
                source_client_order_id=SOURCE_ID,
                trigger_evidence_sha256="8" * 64,
            )
        )
    )
    recovery_thread = threading.Thread(
        target=lambda: recovery_result.append(
            recover_stranded_fill_triggered_follow_ups(
                repository=repository,
                native_repository=native,
            )
        )
    )

    dispatch_thread.start()
    assert materializer_entered.wait(timeout=5)
    recovery_thread.start()
    assert second_guard_attempted.wait(timeout=5)
    assert second_guard_acquired.is_set() is False
    assert repository.finalize_calls == []

    release_materializer.set()
    dispatch_thread.join(timeout=5)
    recovery_thread.join(timeout=5)

    assert dispatch_thread.is_alive() is False
    assert recovery_thread.is_alive() is False
    assert dispatch_result[0].trigger_state is (
        FillTriggeredActivationTriggerState.COMPLETED
    )
    assert recovery_result == [0]
    assert len(repository.finalize_calls) == 1
