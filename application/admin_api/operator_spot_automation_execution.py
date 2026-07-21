"""Pure classification of canonical Spot Automation exchange responses.

This module performs no I/O and carries no exchange-native identifiers.  It
reduces the shared Admin command response to fixed outcome and call-accounting
evidence suitable for the durable Automation coordinator.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiPermission,
)

from .models import AdminApiCommandResponse


class OperatorSpotAutomationExecutionOperation(str, Enum):
    """The one canonical mutation family being classified."""

    CREATE = "CREATE"
    CANCEL = "CANCEL"


class OperatorSpotAutomationExecutionOutcome(str, Enum):
    """Value-blind terminal classification for one canonical invocation."""

    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class OperatorSpotAutomationExecutionClassification:
    """Sanitized outcome and operation-local call accounting."""

    operation: OperatorSpotAutomationExecutionOperation
    outcome: OperatorSpotAutomationExecutionOutcome
    child_terminal: bool | None
    mutation_call_count: int | None
    mutation_call_count_exact: bool
    read_call_count: int | None
    read_call_count_exact: bool

    def __post_init__(self) -> None:
        if self.child_terminal is not None and type(self.child_terminal) is not bool:
            raise ValueError("spot_automation_child_terminal_invalid")
        if self.mutation_call_count_exact is (
            self.mutation_call_count is None
        ):
            raise ValueError("spot_automation_mutation_count_invalid")
        if self.read_call_count_exact is (self.read_call_count is None):
            raise ValueError("spot_automation_read_count_invalid")
        if self.mutation_call_count is not None and (
            type(self.mutation_call_count) is not int
            or self.mutation_call_count not in {0, 1}
        ):
            raise ValueError("spot_automation_mutation_count_invalid")
        if self.read_call_count is not None and (
            type(self.read_call_count) is not int or self.read_call_count < 0
        ):
            raise ValueError("spot_automation_read_count_invalid")


_ACTIVE_STATUSES = frozenset({"PENDING", "OPEN", "QUEUED"})
_TERMINAL_STATUSES = frozenset({"FILLED", "CANCELLED", "EXPIRED", "FAILED"})
_CREATE_STATUSES = _ACTIVE_STATUSES | _TERMINAL_STATUSES
_KNOWN_REJECTIONS = frozenset(
    {
        AdminApiCommandStatus.REJECTED,
        AdminApiCommandStatus.NOT_IMPLEMENTED,
        AdminApiCommandStatus.CONFLICT,
    }
)


def _mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _strict_bool(value: Any) -> bool | None:
    return value if type(value) is bool else None


def _fixed_text(value: Any, allowed: frozenset[str]) -> str | None:
    if isinstance(value, str) and value in allowed:
        return value
    return None


def _read_accounting(response: AdminApiCommandResponse) -> tuple[int | None, bool]:
    count = response.live_coinbase_read_call_count
    read_ran = response.live_coinbase_read_ran is True
    if type(count) is int and count >= 0:
        if (count == 0 and not read_ran) or (count >= 1 and read_ran):
            return count, True
        return None, False
    if count is None and not read_ran:
        return 0, True
    return None, False


def _mutation_accounting(
    evidence: Mapping[str, Any] | None,
    *,
    attempted_key: str,
    response: AdminApiCommandResponse,
) -> tuple[int | None, bool]:
    ran = response.live_coinbase_orders_ran is True
    if evidence is None or attempted_key not in evidence:
        return (0, True) if not ran else (None, False)
    attempted = _strict_bool(evidence.get(attempted_key))
    if attempted is None or attempted is not ran:
        return None, False
    return (1 if attempted else 0), True


def _classification(
    *,
    operation: OperatorSpotAutomationExecutionOperation,
    outcome: OperatorSpotAutomationExecutionOutcome,
    child_terminal: bool | None,
    mutation: tuple[int | None, bool],
    reads: tuple[int | None, bool],
) -> OperatorSpotAutomationExecutionClassification:
    return OperatorSpotAutomationExecutionClassification(
        operation=operation,
        outcome=outcome,
        child_terminal=child_terminal,
        mutation_call_count=mutation[0],
        mutation_call_count_exact=mutation[1],
        read_call_count=reads[0],
        read_call_count_exact=reads[1],
    )


def _unknown(
    operation: OperatorSpotAutomationExecutionOperation,
    *,
    mutation: tuple[int | None, bool] = (None, False),
    reads: tuple[int | None, bool] = (None, False),
) -> OperatorSpotAutomationExecutionClassification:
    return _classification(
        operation=operation,
        outcome=OperatorSpotAutomationExecutionOutcome.UNKNOWN,
        child_terminal=None,
        mutation=mutation,
        reads=reads,
    )


def _canonical_create_response(response: AdminApiCommandResponse) -> bool:
    return bool(
        isinstance(response, AdminApiCommandResponse)
        and response.service_method == "place_manual_order"
        and response.action_class is AdminApiActionClass.LIVE_EXCHANGE_PLACE
        and response.required_permission is AdminApiPermission.ORDER_CREATE
        and response.client_order_id
    )


def _canonical_cancel_response(response: AdminApiCommandResponse) -> bool:
    return bool(
        isinstance(response, AdminApiCommandResponse)
        and response.service_method == "cancel_order_by_client_order_id"
        and response.action_class is AdminApiActionClass.LIVE_EXCHANGE_CANCEL
        and response.required_permission is AdminApiPermission.ORDER_CANCEL
        and response.client_order_id
    )


def classify_canonical_spot_automation_create_response(
    response: AdminApiCommandResponse,
) -> OperatorSpotAutomationExecutionClassification:
    """Classify one canonical Create response without retaining response values."""

    operation = OperatorSpotAutomationExecutionOperation.CREATE
    if not _canonical_create_response(response):
        return _unknown(operation)

    data = _mapping(response.data)
    attempt = _mapping(data.get("submission_attempt")) if data is not None else None
    mutation = _mutation_accounting(
        attempt,
        attempted_key="rest_invocation_attempted",
        response=response,
    )
    reads = _read_accounting(response)
    if not mutation[1]:
        return _unknown(operation, mutation=mutation, reads=reads)

    if mutation[0] == 0:
        if response.status not in _KNOWN_REJECTIONS or reads != (0, True):
            return _unknown(operation, mutation=mutation, reads=reads)
        return _classification(
            operation=operation,
            outcome=OperatorSpotAutomationExecutionOutcome.REJECTED,
            child_terminal=None,
            mutation=mutation,
            reads=reads,
        )

    if attempt is None:
        return _unknown(operation, mutation=mutation, reads=reads)
    invocation_outcome = _fixed_text(
        attempt.get("outcome"),
        frozenset({"accepted", "explicitly_rejected", "unknown"}),
    )
    if invocation_outcome == "explicitly_rejected":
        if response.status is not AdminApiCommandStatus.REJECTED or reads != (0, True):
            return _unknown(operation, mutation=mutation, reads=reads)
        return _classification(
            operation=operation,
            outcome=OperatorSpotAutomationExecutionOutcome.REJECTED,
            child_terminal=None,
            mutation=mutation,
            reads=reads,
        )
    if invocation_outcome != "accepted":
        return _unknown(operation, mutation=mutation, reads=reads)

    readback = _mapping(attempt.get("readback"))
    status = _fixed_text(attempt.get("authoritative_status"), _CREATE_STATUSES)
    readback_status = (
        _fixed_text(readback.get("authoritative_status"), _CREATE_STATUSES)
        if readback is not None
        else None
    )
    proven = bool(
        _strict_bool(attempt.get("authoritative_readback_confirmed")) is True
        and readback is not None
        and _strict_bool(readback.get("authoritative")) is True
        and _strict_bool(readback.get("exact_identity_match")) is True
        and status is not None
        and readback_status == status
        and reads == (1, True)
        and response.status
        in {AdminApiCommandStatus.ACCEPTED, AdminApiCommandStatus.REJECTED}
    )
    if not proven:
        return _unknown(operation, mutation=mutation, reads=reads)
    return _classification(
        operation=operation,
        outcome=OperatorSpotAutomationExecutionOutcome.ACCEPTED,
        child_terminal=status in _TERMINAL_STATUSES,
        mutation=mutation,
        reads=reads,
    )


def _exact_cancel_status(
    cancellation: Mapping[str, Any],
) -> tuple[str | None, bool]:
    readback = _mapping(cancellation.get("authoritative_readback"))
    if readback is None:
        return None, False
    status = _fixed_text(
        cancellation.get("authoritative_status"),
        _ACTIVE_STATUSES | _TERMINAL_STATUSES,
    )
    readback_status = _fixed_text(
        readback.get("authoritative_status"),
        _ACTIVE_STATUSES | _TERMINAL_STATUSES,
    )
    exact = bool(
        _strict_bool(readback.get("authoritative")) is True
        and _strict_bool(readback.get("exact_identity_match")) is True
        and status is not None
        and readback_status == status
    )
    return status, exact


def classify_canonical_spot_automation_cancel_response(
    response: AdminApiCommandResponse,
) -> OperatorSpotAutomationExecutionClassification:
    """Classify one canonical exact-child Cancel response value-blindly."""

    operation = OperatorSpotAutomationExecutionOperation.CANCEL
    if not _canonical_cancel_response(response):
        return _unknown(operation)

    data = _mapping(response.data)
    cancellation = (
        _mapping(data.get("cancellation_readback")) if data is not None else None
    )
    mutation = _mutation_accounting(
        cancellation,
        attempted_key="canonical_cancel_attempted",
        response=response,
    )
    reads = _read_accounting(response)
    if not mutation[1]:
        return _unknown(operation, mutation=mutation, reads=reads)

    status, exact_status = (
        _exact_cancel_status(cancellation)
        if cancellation is not None
        else (None, False)
    )
    terminal = bool(
        exact_status
        and status in _TERMINAL_STATUSES
        and cancellation is not None
        and _strict_bool(cancellation.get("terminal_status_proven")) is True
    )
    active = bool(exact_status and status in _ACTIVE_STATUSES)

    if mutation[0] == 0:
        already_terminal = bool(
            cancellation is not None
            and terminal
            and _strict_bool(cancellation.get("pre_cancel_read_attempted")) is True
            and _strict_bool(cancellation.get("pre_cancel_reconciled")) is True
            and response.status is AdminApiCommandStatus.REJECTED
            and response.failure_stage == "cancellation_preflight_terminal_status"
            and reads[1]
            and reads[0] is not None
            and reads[0] >= 1
        )
        if already_terminal:
            return _classification(
                operation=operation,
                outcome=OperatorSpotAutomationExecutionOutcome.ACCEPTED,
                child_terminal=True,
                mutation=mutation,
                reads=reads,
            )
        if response.status not in _KNOWN_REJECTIONS:
            return _unknown(operation, mutation=mutation, reads=reads)
        return _classification(
            operation=operation,
            outcome=OperatorSpotAutomationExecutionOutcome.REJECTED,
            child_terminal=False if active else None,
            mutation=mutation,
            reads=reads,
        )

    if cancellation is None:
        return _unknown(operation, mutation=mutation, reads=reads)
    accepted = _strict_bool(cancellation.get("canonical_cancel_accepted"))
    explicitly_rejected = _strict_bool(
        cancellation.get("canonical_cancel_explicitly_rejected")
    )
    if accepted is None or explicitly_rejected is None:
        return _unknown(operation, mutation=mutation, reads=reads)
    if accepted and explicitly_rejected:
        return _unknown(operation, mutation=mutation, reads=reads)

    # Any uncertain or absent post-Cancel read is terminally unknown even when
    # the mutation response itself said it was accepted or rejected.
    if not reads[1] or reads[0] is None or reads[0] < 2 or not exact_status:
        return _unknown(operation, mutation=mutation, reads=reads)

    if (
        accepted
        and terminal
        and status == "CANCELLED"
        and response.status is AdminApiCommandStatus.ACCEPTED
    ):
        return _classification(
            operation=operation,
            outcome=OperatorSpotAutomationExecutionOutcome.ACCEPTED,
            child_terminal=True,
            mutation=mutation,
            reads=reads,
        )
    if explicitly_rejected and active and response.status is AdminApiCommandStatus.REJECTED:
        return _classification(
            operation=operation,
            outcome=OperatorSpotAutomationExecutionOutcome.REJECTED,
            child_terminal=False,
            mutation=mutation,
            reads=reads,
        )
    if terminal and response.status is AdminApiCommandStatus.REJECTED:
        return _classification(
            operation=operation,
            # Safe closeout is complete when the exact authoritative post-read
            # proves any terminal child state, even if Coinbase did not accept
            # the Cancel because the child terminalized concurrently.
            outcome=OperatorSpotAutomationExecutionOutcome.ACCEPTED,
            child_terminal=True,
            mutation=mutation,
            reads=reads,
        )
    return _unknown(operation, mutation=mutation, reads=reads)


__all__ = [
    "OperatorSpotAutomationExecutionClassification",
    "OperatorSpotAutomationExecutionOperation",
    "OperatorSpotAutomationExecutionOutcome",
    "classify_canonical_spot_automation_cancel_response",
    "classify_canonical_spot_automation_create_response",
]
