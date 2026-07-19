"""Strict public accounting models for the bounded follow-up live proof."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from application.admin_api.models import (
    AdminOrderFollowUpCurrentRequestActivity,
    AdminOrderFollowUpDurableLiveProofActivity,
    AdminOrderFollowUpDurableOperationActivity,
    AdminOrderFollowUpMaterializationCallAllowance,
)
from core.enums import (
    FollowUpExchangeMutationState,
    FollowUpLiveProofEventState,
    FollowUpLiveProofOperationKind,
    FollowUpLiveProofTerminalOutcome,
    FollowUpReadAccountingState,
    FollowUpSdkMutationInvocationState,
    FollowUpTransportSubmissionState,
)


def _current_request(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "sdk_mutation_invocation_state": "NOT_INVOKED",
        "transport_submission_state": "NOT_SUBMITTED",
        "exchange_mutation_state": "NOT_MUTATED",
        "read_accounting_state": "EXACT",
        "observed_read_count": 0,
    }
    payload.update(overrides)
    return payload


def _durable_operation(
    operation_kind: str,
    **overrides: object,
) -> dict[str, object]:
    payload = _current_request(
        accounting_scope="durable_attempt",
        operation_kind=operation_kind,
        event_state="TERMINAL",
        terminal_outcome="SUCCEEDED",
        individual_retry_count=0,
        evidence_origin="live_proof_journal",
        recorded_at="2026-07-19T00:00:00+00:00",
    )
    payload.update(overrides)
    return payload


def test_current_request_activity_represents_passive_or_replay_exact_zero():
    activity = AdminOrderFollowUpCurrentRequestActivity.model_validate(
        _current_request()
    )

    assert activity.accounting_scope == "current_request"
    assert (
        activity.sdk_mutation_invocation_state
        is FollowUpSdkMutationInvocationState.NOT_INVOKED
    )
    assert activity.observed_read_count == 0
    assert "action" not in activity.model_dump()
    assert "actionable" not in activity.model_dump()


@pytest.mark.parametrize(
    ("read_state", "observed_count"),
    (
        pytest.param("EXACT", None, id="exact-requires-count"),
        pytest.param("UNKNOWN", 0, id="unknown-requires-null"),
        pytest.param("UNKNOWN", 1, id="unknown-rejects-nonzero"),
    ),
)
def test_current_request_activity_requires_exact_iff_count_is_integer(
    read_state: str,
    observed_count: int | None,
):
    with pytest.raises(ValidationError, match="follow_up_activity_read_accounting_invalid"):
        AdminOrderFollowUpCurrentRequestActivity.model_validate(
            _current_request(
                read_accounting_state=read_state,
                observed_read_count=observed_count,
            )
        )


@pytest.mark.parametrize("invalid_count", [True, "0", -1, 11])
def test_activity_counts_are_strict_bounded_integers(invalid_count: object):
    with pytest.raises(ValidationError):
        AdminOrderFollowUpCurrentRequestActivity.model_validate(
            _current_request(observed_read_count=invalid_count)
        )

    with pytest.raises(ValidationError):
        AdminOrderFollowUpDurableOperationActivity.model_validate(
            _durable_operation(
                "ELIGIBILITY_READ",
                individual_retry_count=invalid_count,
                observed_read_count=1,
            )
        )


@pytest.mark.parametrize(
    "overrides",
    (
        pytest.param(
            {
                "sdk_mutation_invocation_state": "NOT_INVOKED",
                "transport_submission_state": "CONFIRMED_SUBMITTED",
            },
            id="not-invoked-cannot-submit",
        ),
        pytest.param(
            {
                "sdk_mutation_invocation_state": "NOT_INVOKED",
                "exchange_mutation_state": "UNKNOWN",
            },
            id="not-invoked-cannot-mutate",
        ),
        pytest.param(
            {
                "sdk_mutation_invocation_state": "INVOKED",
                "transport_submission_state": "NOT_SUBMITTED",
                "exchange_mutation_state": "NOT_MUTATED",
            },
            id="sdk-invocation-cannot-be-reported-as-pre-port",
        ),
        pytest.param(
            {
                "sdk_mutation_invocation_state": "INVOKED",
                "transport_submission_state": "POSSIBLY_SUBMITTED",
                "exchange_mutation_state": "NOT_MUTATED",
            },
            id="possible-submission-requires-unknown-exchange",
        ),
        pytest.param(
            {
                "sdk_mutation_invocation_state": "UNKNOWN",
                "transport_submission_state": "CONFIRMED_SUBMITTED",
                "exchange_mutation_state": "CONFIRMED_MUTATED",
            },
            id="confirmed-mutation-requires-invoked-sdk",
        ),
        pytest.param(
            {
                "sdk_mutation_invocation_state": "INVOKED",
                "transport_submission_state": "NOT_SUBMITTED",
                "exchange_mutation_state": "CONFIRMED_MUTATED",
            },
            id="confirmed-mutation-requires-confirmed-submission",
        ),
    ),
)
def test_current_request_activity_rejects_impossible_mutation_observations(
    overrides: dict[str, object],
):
    with pytest.raises(ValidationError, match="follow_up_activity_mutation_observation_invalid"):
        AdminOrderFollowUpCurrentRequestActivity.model_validate(
            _current_request(**overrides)
        )


@pytest.mark.parametrize(
    ("operation_kind", "states"),
    (
        pytest.param(
            "ELIGIBILITY_READ",
            {
                "sdk_mutation_invocation_state": "NOT_INVOKED",
                "transport_submission_state": "NOT_SUBMITTED",
                "exchange_mutation_state": "NOT_MUTATED",
                "read_accounting_state": "EXACT",
                "observed_read_count": 6,
            },
            id="eligibility-success",
        ),
        pytest.param(
            "RECONCILIATION_READ",
            {
                "sdk_mutation_invocation_state": "NOT_INVOKED",
                "transport_submission_state": "NOT_SUBMITTED",
                "exchange_mutation_state": "NOT_MUTATED",
                "read_accounting_state": "EXACT",
                "observed_read_count": 3,
            },
            id="reconciliation-success",
        ),
        pytest.param(
            "CREATE",
            {
                "sdk_mutation_invocation_state": "INVOKED",
                "transport_submission_state": "CONFIRMED_SUBMITTED",
                "exchange_mutation_state": "CONFIRMED_MUTATED",
                "read_accounting_state": "EXACT",
                "observed_read_count": 1,
            },
            id="create-accepted",
        ),
        pytest.param(
            "CANCEL",
            {
                "sdk_mutation_invocation_state": "INVOKED",
                "transport_submission_state": "CONFIRMED_SUBMITTED",
                "exchange_mutation_state": "CONFIRMED_MUTATED",
                "read_accounting_state": "EXACT",
                "observed_read_count": 1,
            },
            id="cancel-accepted",
        ),
    ),
)
def test_durable_terminal_success_accepts_only_operation_specific_accounting(
    operation_kind: str,
    states: dict[str, object],
):
    activity = AdminOrderFollowUpDurableOperationActivity.model_validate(
        _durable_operation(operation_kind, **states)
    )

    assert activity.operation_kind.value == operation_kind
    assert activity.event_state is FollowUpLiveProofEventState.TERMINAL
    assert activity.terminal_outcome is FollowUpLiveProofTerminalOutcome.SUCCEEDED


def test_durable_terminal_mutation_rejection_and_known_pre_port_block_are_distinct():
    rejected = AdminOrderFollowUpDurableOperationActivity.model_validate(
        _durable_operation(
            "CREATE",
            terminal_outcome="REJECTED",
            sdk_mutation_invocation_state="INVOKED",
            transport_submission_state="CONFIRMED_SUBMITTED",
            exchange_mutation_state="NOT_MUTATED",
            observed_read_count=0,
        )
    )
    pre_port = AdminOrderFollowUpDurableOperationActivity.model_validate(
        _durable_operation(
            "CREATE",
            terminal_outcome="BLOCKED",
            sdk_mutation_invocation_state="NOT_INVOKED",
            transport_submission_state="NOT_SUBMITTED",
            exchange_mutation_state="NOT_MUTATED",
            observed_read_count=0,
        )
    )

    assert (
        rejected.transport_submission_state
        is FollowUpTransportSubmissionState.CONFIRMED_SUBMITTED
    )
    assert (
        pre_port.sdk_mutation_invocation_state
        is FollowUpSdkMutationInvocationState.NOT_INVOKED
    )
    assert (
        pre_port.transport_submission_state
        is FollowUpTransportSubmissionState.NOT_SUBMITTED
    )


@pytest.mark.parametrize("sdk_state", ["UNKNOWN", "INVOKED"])
def test_durable_terminal_unknown_mutation_is_conservative_and_nullable(
    sdk_state: str,
):
    activity = AdminOrderFollowUpDurableOperationActivity.model_validate(
        _durable_operation(
            "CREATE",
            terminal_outcome="UNKNOWN",
            sdk_mutation_invocation_state=sdk_state,
            transport_submission_state="POSSIBLY_SUBMITTED",
            exchange_mutation_state="UNKNOWN",
            read_accounting_state="UNKNOWN",
            observed_read_count=None,
        )
    )

    assert activity.read_accounting_state is FollowUpReadAccountingState.UNKNOWN
    assert activity.observed_read_count is None


@pytest.mark.parametrize("operation_kind", ["CREATE", "CANCEL"])
def test_durable_mutation_start_keeps_lost_owner_observation_unknown(
    operation_kind: str,
):
    payload = _durable_operation(
        operation_kind,
        event_state="INVOCATION_STARTED",
        sdk_mutation_invocation_state="UNKNOWN",
        transport_submission_state="POSSIBLY_SUBMITTED",
        exchange_mutation_state="UNKNOWN",
        read_accounting_state="UNKNOWN",
        observed_read_count=None,
    )
    payload.pop("terminal_outcome")
    activity = AdminOrderFollowUpDurableOperationActivity.model_validate(payload)

    assert activity.terminal_outcome is None


@pytest.mark.parametrize(
    "operation_kind", ["ELIGIBILITY_READ", "RECONCILIATION_READ"]
)
def test_durable_read_start_is_non_mutating_unknown_read(
    operation_kind: str,
):
    activity = AdminOrderFollowUpDurableOperationActivity.model_validate(
        _durable_operation(
            operation_kind,
            event_state="INVOCATION_STARTED",
            terminal_outcome=None,
            read_accounting_state="UNKNOWN",
            observed_read_count=None,
        )
    )

    assert activity.sdk_mutation_invocation_state is FollowUpSdkMutationInvocationState.NOT_INVOKED


@pytest.mark.parametrize(
    "overrides",
    (
        pytest.param(
            {"event_state": "INVOCATION_STARTED", "terminal_outcome": "UNKNOWN"},
            id="start-cannot-have-outcome",
        ),
        pytest.param(
            {"event_state": "TERMINAL", "terminal_outcome": None},
            id="terminal-requires-outcome",
        ),
        pytest.param(
            {
                "operation_kind": "ELIGIBILITY_READ",
                "sdk_mutation_invocation_state": "INVOKED",
                "observed_read_count": 1,
            },
            id="read-cannot-invoke-mutation-sdk",
        ),
        pytest.param(
            {
                "operation_kind": "CREATE",
                "terminal_outcome": "SUCCEEDED",
                "sdk_mutation_invocation_state": "INVOKED",
                "transport_submission_state": "CONFIRMED_SUBMITTED",
                "exchange_mutation_state": "NOT_MUTATED",
                "observed_read_count": 1,
            },
            id="accepted-mutation-must-confirm-mutation",
        ),
        pytest.param(
            {
                "operation_kind": "CREATE",
                "terminal_outcome": "REJECTED",
                "sdk_mutation_invocation_state": "INVOKED",
                "transport_submission_state": "POSSIBLY_SUBMITTED",
                "exchange_mutation_state": "UNKNOWN",
                "read_accounting_state": "UNKNOWN",
                "observed_read_count": None,
            },
            id="rejected-mutation-cannot-be-ambiguous",
        ),
        pytest.param(
            {
                "operation_kind": "RECONCILIATION_READ",
                "terminal_outcome": "REJECTED",
                "observed_read_count": 0,
            },
            id="read-cannot-be-exchange-rejected",
        ),
    ),
)
def test_durable_operation_rejects_cross_field_accounting_attacks(
    overrides: dict[str, object],
):
    attack = dict(overrides)
    operation_kind = str(attack.pop("operation_kind", "CREATE"))
    with pytest.raises(ValidationError):
        AdminOrderFollowUpDurableOperationActivity.model_validate(
            _durable_operation(operation_kind, **attack)
        )


def test_durable_activity_slots_enforce_their_canonical_operation_kind():
    eligibility = AdminOrderFollowUpDurableOperationActivity.model_validate(
        _durable_operation("ELIGIBILITY_READ", observed_read_count=1)
    )
    create = AdminOrderFollowUpDurableOperationActivity.model_validate(
        _durable_operation(
            "CREATE",
            sdk_mutation_invocation_state="INVOKED",
            transport_submission_state="CONFIRMED_SUBMITTED",
            exchange_mutation_state="CONFIRMED_MUTATED",
            observed_read_count=1,
        )
    )

    activity = AdminOrderFollowUpDurableLiveProofActivity(
        eligibility_read=eligibility,
        create=create,
    )
    assert activity.eligibility_read is eligibility
    assert activity.reconciliation_read is None

    with pytest.raises(ValidationError, match="follow_up_live_proof_activity_slot_kind_mismatch"):
        AdminOrderFollowUpDurableLiveProofActivity(create=eligibility)


def test_durable_activity_is_extra_forbid_and_uses_typed_enums():
    payload = _durable_operation(
        "CREATE",
        sdk_mutation_invocation_state="INVOKED",
        transport_submission_state="CONFIRMED_SUBMITTED",
        exchange_mutation_state="CONFIRMED_MUTATED",
        observed_read_count=1,
        evidence_origin="conservative_legacy_projection",
    )
    payload["unexpected_authority"] = True

    with pytest.raises(ValidationError):
        AdminOrderFollowUpDurableOperationActivity.model_validate(payload)

    assert set(FollowUpExchangeMutationState) == {
        FollowUpExchangeMutationState.NOT_MUTATED,
        FollowUpExchangeMutationState.UNKNOWN,
        FollowUpExchangeMutationState.CONFIRMED_MUTATED,
    }


def test_call_allowance_counts_match_consumption_and_expose_canonical_aliases():
    allowance = AdminOrderFollowUpMaterializationCallAllowance(
        create_call_count=1,
        create_call_consumed=True,
        cancel_call_count=0,
        cancel_call_consumed=False,
    )

    assert allowance.create_allowance_consumed is True
    assert allowance.cancel_allowance_consumed is False
    assert allowance.model_dump()["create_allowance_consumed"] is True
    assert allowance.model_dump()["cancel_allowance_consumed"] is False
    assert (
        AdminOrderFollowUpMaterializationCallAllowance.model_validate(
            allowance.model_dump()
        )
        == allowance
    )


@pytest.mark.parametrize(
    "overrides",
    (
        pytest.param(
            {"create_call_count": 0, "create_call_consumed": True},
            id="create-true-with-zero",
        ),
        pytest.param(
            {"create_call_count": 1, "create_call_consumed": False},
            id="create-false-with-one",
        ),
        pytest.param(
            {"cancel_call_count": 0, "cancel_call_consumed": True},
            id="cancel-true-with-zero",
        ),
        pytest.param(
            {"cancel_call_count": 1, "cancel_call_consumed": False},
            id="cancel-false-with-one",
        ),
        pytest.param(
            {"create_allowance_consumed": True},
            id="canonical-create-alias-mismatch",
        ),
        pytest.param(
            {"cancel_allowance_consumed": True},
            id="canonical-cancel-alias-mismatch",
        ),
    ),
)
def test_call_allowance_rejects_consumption_count_mismatch(
    overrides: dict[str, object],
):
    payload: dict[str, object] = {
        "create_call_count": 0,
        "create_call_consumed": False,
        "cancel_call_count": 0,
        "cancel_call_consumed": False,
    }
    payload.update(overrides)

    with pytest.raises(ValidationError, match="follow_up_call_allowance_accounting_invalid"):
        AdminOrderFollowUpMaterializationCallAllowance.model_validate(payload)


@pytest.mark.parametrize("invalid_count", [True, "0"])
def test_call_allowance_counts_reject_coercion(invalid_count: object):
    with pytest.raises(ValidationError):
        AdminOrderFollowUpMaterializationCallAllowance(
            create_call_count=invalid_count,
            create_call_consumed=False,
            cancel_call_count=0,
            cancel_call_consumed=False,
        )
