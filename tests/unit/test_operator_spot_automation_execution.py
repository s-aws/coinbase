from __future__ import annotations

from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiPermission,
)
from application.admin_api.models import AdminApiCommandResponse
from application.admin_api.operator_spot_automation_execution import (
    OperatorSpotAutomationExecutionOutcome,
    classify_canonical_spot_automation_cancel_response,
    classify_canonical_spot_automation_create_response,
)


def _create_response(
    *,
    status: AdminApiCommandStatus,
    submission_attempt: dict | None,
    read_ran: bool = False,
    read_count: int | None = 0,
    orders_ran: bool = False,
    failure_stage: str | None = None,
) -> AdminApiCommandResponse:
    return AdminApiCommandResponse(
        status=status,
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        required_permission=AdminApiPermission.ORDER_CREATE,
        service_method="place_manual_order",
        message="withheld private response text",
        client_order_id="22daf1ea-4c57-4c03-98c5-e74459576228",
        live_coinbase_orders_ran=orders_ran,
        live_coinbase_read_ran=read_ran,
        live_coinbase_read_call_count=read_count,
        data=(
            {"submission_attempt": submission_attempt}
            if submission_attempt is not None
            else None
        ),
        failure_stage=failure_stage,
    )


def _cancel_response(
    *,
    status: AdminApiCommandStatus,
    cancellation_readback: dict | None,
    read_ran: bool = False,
    read_count: int | None = 0,
    orders_ran: bool = False,
    failure_stage: str | None = None,
) -> AdminApiCommandResponse:
    return AdminApiCommandResponse(
        status=status,
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        required_permission=AdminApiPermission.ORDER_CANCEL,
        service_method="cancel_order_by_client_order_id",
        message="withheld private response text",
        client_order_id="22daf1ea-4c57-4c03-98c5-e74459576228",
        live_coinbase_orders_ran=orders_ran,
        live_coinbase_read_ran=read_ran,
        live_coinbase_read_call_count=read_count,
        data=(
            {"cancellation_readback": cancellation_readback}
            if cancellation_readback is not None
            else None
        ),
        failure_stage=failure_stage,
    )


def _order_readback(status: str) -> dict:
    return {
        "authoritative": True,
        "exact_identity_match": True,
        "authoritative_status": status,
        "page_count": 1,
    }


def test_create_classifies_proven_active_and_terminal_children() -> None:
    active = classify_canonical_spot_automation_create_response(
        _create_response(
            status=AdminApiCommandStatus.ACCEPTED,
            submission_attempt={
                "rest_invocation_attempted": True,
                "outcome": "accepted",
                "authoritative_readback_confirmed": True,
                "authoritative_status": "OPEN",
                "readback": _order_readback("OPEN"),
            },
            read_ran=True,
            read_count=1,
            orders_ran=True,
        )
    )
    terminal = classify_canonical_spot_automation_create_response(
        _create_response(
            status=AdminApiCommandStatus.REJECTED,
            submission_attempt={
                "rest_invocation_attempted": True,
                "outcome": "accepted",
                "authoritative_readback_confirmed": True,
                "authoritative_status": "FILLED",
                "readback": _order_readback("FILLED"),
            },
            read_ran=True,
            read_count=1,
            orders_ran=True,
            failure_stage="order_root_status_persistence",
        )
    )

    assert active.outcome is OperatorSpotAutomationExecutionOutcome.ACCEPTED
    assert active.child_terminal is False
    assert active.mutation_call_count == 1
    assert active.mutation_call_count_exact is True
    assert active.read_call_count == 1
    assert active.read_call_count_exact is True
    assert terminal.outcome is OperatorSpotAutomationExecutionOutcome.ACCEPTED
    assert terminal.child_terminal is True


def test_create_classifies_pre_boundary_and_explicit_rejection_exactly() -> None:
    pre_boundary = classify_canonical_spot_automation_create_response(
        _create_response(
            status=AdminApiCommandStatus.REJECTED,
            submission_attempt=None,
        )
    )
    explicit = classify_canonical_spot_automation_create_response(
        _create_response(
            status=AdminApiCommandStatus.REJECTED,
            submission_attempt={
                "rest_invocation_attempted": True,
                "outcome": "explicitly_rejected",
                "authoritative_readback_attempted": False,
            },
            orders_ran=True,
            failure_stage="coinbase_rest",
        )
    )

    assert pre_boundary.outcome is OperatorSpotAutomationExecutionOutcome.REJECTED
    assert pre_boundary.child_terminal is None
    assert pre_boundary.mutation_call_count == 0
    assert pre_boundary.read_call_count == 0
    assert explicit.outcome is OperatorSpotAutomationExecutionOutcome.REJECTED
    assert explicit.child_terminal is None
    assert explicit.mutation_call_count == 1
    assert explicit.read_call_count == 0


def test_create_unknown_readback_is_value_blind_and_consumes_one_mutation() -> None:
    classification = classify_canonical_spot_automation_create_response(
        _create_response(
            status=AdminApiCommandStatus.REJECTED,
            submission_attempt={
                "rest_invocation_attempted": True,
                "outcome": "unknown",
                "authoritative_readback_attempted": True,
                "readback": {
                    "authoritative": False,
                    "detail": "withheld secret response",
                },
            },
            read_ran=True,
            read_count=None,
            orders_ran=True,
            failure_stage="coinbase_submission_unknown",
        )
    )

    assert classification.outcome is OperatorSpotAutomationExecutionOutcome.UNKNOWN
    assert classification.child_terminal is None
    assert classification.mutation_call_count == 1
    assert classification.mutation_call_count_exact is True
    assert classification.read_call_count is None
    assert classification.read_call_count_exact is False
    assert "withheld" not in repr(classification)


def test_cancel_already_terminal_is_accepted_without_mutation() -> None:
    classification = classify_canonical_spot_automation_cancel_response(
        _cancel_response(
            status=AdminApiCommandStatus.REJECTED,
            cancellation_readback={
                "pre_cancel_read_attempted": True,
                "pre_cancel_reconciled": True,
                "canonical_cancel_attempted": False,
                "terminal_status_proven": True,
                "authoritative_status": "FILLED",
                "authoritative_readback": _order_readback("FILLED"),
            },
            read_ran=True,
            read_count=1,
            failure_stage="cancellation_preflight_terminal_status",
        )
    )

    assert classification.outcome is OperatorSpotAutomationExecutionOutcome.ACCEPTED
    assert classification.child_terminal is True
    assert classification.mutation_call_count == 0
    assert classification.mutation_call_count_exact is True
    assert classification.read_call_count == 1
    assert classification.read_call_count_exact is True


def test_cancel_classifies_confirmed_cancel_and_explicit_active_rejection() -> None:
    cancelled = classify_canonical_spot_automation_cancel_response(
        _cancel_response(
            status=AdminApiCommandStatus.ACCEPTED,
            cancellation_readback={
                "pre_cancel_read_attempted": True,
                "canonical_cancel_attempted": True,
                "canonical_cancel_accepted": True,
                "canonical_cancel_explicitly_rejected": False,
                "terminal_status_proven": True,
                "authoritative_status": "CANCELLED",
                "authoritative_readback": _order_readback("CANCELLED"),
            },
            read_ran=True,
            read_count=2,
            orders_ran=True,
        )
    )
    rejected = classify_canonical_spot_automation_cancel_response(
        _cancel_response(
            status=AdminApiCommandStatus.REJECTED,
            cancellation_readback={
                "pre_cancel_read_attempted": True,
                "canonical_cancel_attempted": True,
                "canonical_cancel_accepted": False,
                "canonical_cancel_explicitly_rejected": True,
                "terminal_status_proven": False,
                "authoritative_status": "OPEN",
                "authoritative_readback": _order_readback("OPEN"),
            },
            read_ran=True,
            read_count=2,
            orders_ran=True,
            failure_stage="cancellation_rejected",
        )
    )

    assert cancelled.outcome is OperatorSpotAutomationExecutionOutcome.ACCEPTED
    assert cancelled.child_terminal is True
    assert cancelled.mutation_call_count == 1
    assert cancelled.read_call_count == 2
    assert rejected.outcome is OperatorSpotAutomationExecutionOutcome.REJECTED
    assert rejected.child_terminal is False
    assert rejected.mutation_call_count == 1
    assert rejected.read_call_count == 2


def test_cancel_uncertain_post_read_is_unknown_with_exact_mutation_count() -> None:
    classification = classify_canonical_spot_automation_cancel_response(
        _cancel_response(
            status=AdminApiCommandStatus.REJECTED,
            cancellation_readback={
                "pre_cancel_read_attempted": True,
                "canonical_cancel_attempted": True,
                "canonical_cancel_accepted": True,
                "canonical_cancel_explicitly_rejected": False,
                "terminal_status_proven": False,
                "authoritative_readback": {
                    "authoritative": False,
                    "detail": "withheld private post-read",
                },
            },
            read_ran=True,
            read_count=None,
            orders_ran=True,
            failure_stage="cancellation_readback",
        )
    )

    assert classification.outcome is OperatorSpotAutomationExecutionOutcome.UNKNOWN
    assert classification.child_terminal is None
    assert classification.mutation_call_count == 1
    assert classification.mutation_call_count_exact is True
    assert classification.read_call_count is None
    assert classification.read_call_count_exact is False
    assert "withheld" not in repr(classification)


def test_cancel_post_read_terminal_is_successful_safe_closeout() -> None:
    classification = classify_canonical_spot_automation_cancel_response(
        _cancel_response(
            status=AdminApiCommandStatus.REJECTED,
            cancellation_readback={
                "pre_cancel_read_attempted": True,
                "canonical_cancel_attempted": True,
                "canonical_cancel_accepted": False,
                "canonical_cancel_explicitly_rejected": True,
                "terminal_status_proven": True,
                "authoritative_status": "FILLED",
                "authoritative_readback": _order_readback("FILLED"),
            },
            read_ran=True,
            read_count=2,
            orders_ran=True,
            failure_stage="cancellation_rejected",
        )
    )

    assert classification.outcome is OperatorSpotAutomationExecutionOutcome.ACCEPTED
    assert classification.child_terminal is True
    assert classification.mutation_call_count == 1
    assert classification.read_call_count == 2


def test_noncanonical_or_contradictory_response_fails_to_unknown_counts() -> None:
    response = _create_response(
        status=AdminApiCommandStatus.ACCEPTED,
        submission_attempt={
            "rest_invocation_attempted": True,
            "outcome": "accepted",
        },
        read_ran=False,
        read_count=1,
        orders_ran=False,
    ).model_copy(update={"service_method": "parallel_create_path"})

    classification = classify_canonical_spot_automation_create_response(response)

    assert classification.outcome is OperatorSpotAutomationExecutionOutcome.UNKNOWN
    assert classification.child_terminal is None
    assert classification.mutation_call_count is None
    assert classification.mutation_call_count_exact is False
    assert classification.read_call_count is None
    assert classification.read_call_count_exact is False
