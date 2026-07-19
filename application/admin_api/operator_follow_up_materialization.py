"""Backend-owned, single-use materialization of one attached follow-up intent.

This module is deliberately an application kernel rather than a Coinbase
adapter.  The route supplies only authenticated request context and explicit
acknowledgements.  A backend runtime resolves the exact source/root/child and
order tuple, while a durable repository owns replay and invocation-boundary
claims.  The injected exchange port must be the canonical guarded command
path; tests use synthetic ports and make no network calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
import hashlib
import json
from contextlib import AbstractContextManager
from typing import Literal, Protocol

from application.admin_api.auth import ROLE_PERMISSIONS
from application.admin_api.operator_mvp_policy import (
    OPERATOR_MVP_MAX_EXECUTED_NOTIONAL_USDC,
    OPERATOR_MVP_MAX_SUBMITTED_NOTIONAL_USDC,
)
from core.enums import (
    AdminApiPermission,
    AdminApiRole,
    FollowUpExchangeMutationState,
    FollowUpLiveProofOperationKind,
    FollowUpLiveProofTerminalOutcome,
    FollowUpReadAccountingState,
    FollowUpSdkMutationInvocationState,
    FollowUpTransportSubmissionState,
)


AUTHORIZE_AND_MATERIALIZE_FOLLOW_UP_INTENT = (
    "authorize_and_materialize_follow_up_intent"
)
SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT = (
    "safe_closeout_materialized_follow_up_intent"
)
OPERATOR_FOLLOW_UP_LIVE_PROOF_GOAL_ID = (
    "operator_follow_up_operations_queue_and_single_live_proof"
)

CURRENT_MAX_SUBMITTED_NOTIONAL_USDC = OPERATOR_MVP_MAX_SUBMITTED_NOTIONAL_USDC
CURRENT_MAX_EXECUTED_NOTIONAL_USDC = OPERATOR_MVP_MAX_EXECUTED_NOTIONAL_USDC
CURRENT_EFFECTIVE_NOTIONAL_CAP_USDC = min(
    CURRENT_MAX_SUBMITTED_NOTIONAL_USDC,
    CURRENT_MAX_EXECUTED_NOTIONAL_USDC,
)

CREATE_ACCEPTED_DIAGNOSTIC = "follow_up_materialization_create_accepted"
CREATE_REJECTED_DIAGNOSTIC = "follow_up_materialization_create_rejected"
CREATE_UNKNOWN_DIAGNOSTIC = "follow_up_materialization_create_outcome_unknown"
CANCEL_ACCEPTED_DIAGNOSTIC = "follow_up_materialization_cancel_accepted"
CANCEL_REJECTED_DIAGNOSTIC = "follow_up_materialization_cancel_rejected"
CANCEL_UNKNOWN_DIAGNOSTIC = "follow_up_materialization_cancel_outcome_unknown"
CHILD_ALREADY_TERMINAL_DIAGNOSTIC = (
    "follow_up_materialization_child_already_terminal"
)
PREPARED_DIAGNOSTIC = "follow_up_materialization_prepared"

_SAFE_DIAGNOSTICS = frozenset(
    {
        PREPARED_DIAGNOSTIC,
        CREATE_ACCEPTED_DIAGNOSTIC,
        CREATE_REJECTED_DIAGNOSTIC,
        CREATE_UNKNOWN_DIAGNOSTIC,
        CANCEL_ACCEPTED_DIAGNOSTIC,
        CANCEL_REJECTED_DIAGNOSTIC,
        CANCEL_UNKNOWN_DIAGNOSTIC,
        CHILD_ALREADY_TERMINAL_DIAGNOSTIC,
    }
)


class OperatorFollowUpMaterializationError(RuntimeError):
    """Fixed, value-blind application-boundary error."""

    def __init__(
        self,
        code: str,
        http_status_code: int,
        *,
        failure_stage: str = "execution_stage_unknown",
        live_coinbase_read_ran: bool | None = None,
        live_coinbase_orders_ran: bool | None = None,
        live_exchange_submitted: bool | None = None,
    ) -> None:
        self.code = str(code)
        self.http_status_code = int(http_status_code)
        self.failure_stage = str(failure_stage)
        self.live_coinbase_read_ran = live_coinbase_read_ran
        self.live_coinbase_orders_ran = live_coinbase_orders_ran
        self.live_exchange_submitted = live_exchange_submitted
        super().__init__(self.code)

    def with_execution_evidence(
        self,
        *,
        failure_stage: str,
        live_coinbase_read_ran: bool,
        live_coinbase_orders_ran: bool,
        live_exchange_submitted: bool,
    ) -> "OperatorFollowUpMaterializationError":
        return OperatorFollowUpMaterializationError(
            self.code,
            self.http_status_code,
            failure_stage=failure_stage,
            live_coinbase_read_ran=live_coinbase_read_ran,
            live_coinbase_orders_ran=live_coinbase_orders_ran,
            live_exchange_submitted=live_exchange_submitted,
        )


class MaterializationRecordState(str, Enum):
    """Durable states whose invocation-started values consume call allowance."""

    PREPARED = "PREPARED"
    CREATE_INVOCATION_STARTED = "CREATE_INVOCATION_STARTED"
    CREATE_ACCEPTED = "CREATE_ACCEPTED"
    CREATE_REJECTED = "CREATE_REJECTED"
    CREATE_UNKNOWN = "CREATE_UNKNOWN"
    CANCEL_INVOCATION_STARTED = "CANCEL_INVOCATION_STARTED"
    CANCEL_ACCEPTED = "CANCEL_ACCEPTED"
    CANCEL_REJECTED = "CANCEL_REJECTED"
    CANCEL_UNKNOWN = "CANCEL_UNKNOWN"
    CHILD_ALREADY_TERMINAL = "CHILD_ALREADY_TERMINAL"


class ChildExchangeState(str, Enum):
    """Sanitized child state; no exchange-native identifier is represented."""

    ACTIVE = "ACTIVE"
    TERMINAL = "TERMINAL"
    UNKNOWN = "UNKNOWN"


class ExchangeInvocationOutcome(str, Enum):
    """Fixed result classes accepted from the canonical exchange adapter."""

    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"
    NOT_REQUIRED_TERMINAL = "NOT_REQUIRED_TERMINAL"


@dataclass(frozen=True, slots=True)
class OperatorFollowUpMaterializationRequestContext:
    actor_id: str
    roles: tuple[str, ...]
    idempotency_key: str
    correlation_id: str
    operator_intent: str
    audit_id: str
    environment: str = "local"


@dataclass(frozen=True, slots=True)
class MaterializationAuthorization:
    """Fresh live acknowledgement; the attachment acknowledgement is excluded."""

    authorize_materialization_of_attached_intent: bool
    acknowledge_unknown_outcome_consumes_create_allowance: bool
    acknowledge_child_terms_are_backend_derived: bool


@dataclass(frozen=True, slots=True)
class SafeCloseoutAuthorization:
    """Fresh acknowledgement for the optional one-call child closeout."""

    authorize_single_cancel_for_safe_closeout: bool
    acknowledge_unknown_outcome_consumes_cancel_allowance: bool


@dataclass(frozen=True, slots=True)
class BackendMaterializationCandidate:
    """Exact child tuple derived by backend runtime, never by the browser."""

    attached_intent_id: str
    source_client_order_id: str
    root_client_order_id: str
    child_client_order_id: str
    source_status: str
    source_side: str
    child_side: str
    product_id: str
    product_type: str
    portfolio_type: str
    portfolio_id: str
    portfolio_scope_sha256: str
    environment: str
    base_size: Decimal
    limit_price: Decimal
    submitted_notional_usdc: Decimal
    max_submitted_notional_usdc: Decimal
    max_executed_notional_usdc: Decimal
    effective_notional_cap_usdc: Decimal
    authoritative_source_fill_proven: bool
    source_terminal: bool
    attached_intent_requires_fresh_authorization: bool
    no_existing_follow_up_child: bool
    controlled_live_enabled: bool
    execution_lease_valid: bool
    approved_test_portfolio_verified: bool
    product_policy_allowed: bool
    action_condition_guard_passed: bool
    wallet_check_passed: bool


@dataclass(frozen=True, slots=True)
class FreshMaterializationEligibility:
    """Evidence from exactly one backend-owned eligibility/reconciliation pass."""

    candidate: BackendMaterializationCandidate | None
    fresh: bool
    eligibility_pass_count: int
    reconciliation_pass_count: int
    individual_retry_count: int
    ambiguous: bool
    blockers: tuple[str, ...]
    coinbase_read_started: bool = False
    coinbase_read_count: int = 0


@dataclass(frozen=True, slots=True)
class ChildStateEvidence:
    """One sanitized authoritative read of the exact repository child."""

    child_client_order_id: str
    state: ChildExchangeState
    fresh: bool
    authoritative: bool
    read_count: int
    individual_retry_count: int
    ambiguous: bool
    exchange_order_id_sha256: str | None = None
    coinbase_read_started: bool = False


@dataclass(frozen=True, slots=True)
class LocalChildPersistenceEvidence:
    """Proof the exact reserved child exists locally before live invocation."""

    materialization_id: str
    child_client_order_id: str
    persisted: bool
    exact_replay_safe: bool
    exchange_call_ran: bool


@dataclass(frozen=True, slots=True)
class LocalChildProjectionEvidence:
    """Sanitized proof that journaled truth reached both local child rows."""

    materialization_id: str
    child_client_order_id: str
    record_state: MaterializationRecordState
    projected: bool
    exact_replay_safe: bool
    exchange_call_ran: bool
    live_read_count: int
    individual_retry_count: int


@dataclass(frozen=True, slots=True)
class ExchangeInvocationResult:
    """Value-blind result emitted by the canonical create/cancel adapter."""

    outcome: ExchangeInvocationOutcome
    child_state: ChildExchangeState
    exchange_call_started: bool
    exchange_order_id_sha256: str | None = None
    post_mutation_read_started: bool = False
    post_mutation_read_count: int = 0
    individual_retry_count: int = 0
    sdk_mutation_invocation_state: FollowUpSdkMutationInvocationState | None = None
    transport_submission_state: FollowUpTransportSubmissionState | None = None
    exchange_mutation_state: FollowUpExchangeMutationState | None = None
    read_accounting_state: FollowUpReadAccountingState | None = None
    observed_read_count: int | None = None


@dataclass(frozen=True, slots=True)
class FollowUpMaterializationRecord:
    """Sanitized durable readback; raw Coinbase evidence has no field here."""

    materialization_id: str
    attached_intent_id: str
    source_client_order_id: str
    root_client_order_id: str
    child_client_order_id: str
    state: MaterializationRecordState
    create_idempotency_key_sha256: str
    cancel_idempotency_key_sha256: str | None
    create_call_consumed: bool
    cancel_call_consumed: bool
    child_state: ChildExchangeState
    diagnostic_code: str
    correlation_id: str
    audit_id: str
    durable_candidate: BackendMaterializationCandidate | None = None


@dataclass(frozen=True, slots=True)
class MaterializationPrepareCommand:
    """Sanitized repository command built only after all live gates pass."""

    candidate: BackendMaterializationCandidate
    actor_id: str
    roles: tuple[str, ...]
    idempotency_key: str
    idempotency_key_sha256: str
    correlation_id: str
    operator_intent: str
    audit_id: str
    request_sha256: str


@dataclass(frozen=True, slots=True)
class InvocationBoundaryClaim:
    """Atomic repository decision determining the sole exchange caller."""

    record: FollowUpMaterializationRecord
    claimed: bool


@dataclass(frozen=True, slots=True)
class LiveProofOperationClaim:
    """Exact durable goal binding journaled before an external port call."""

    operation_kind: FollowUpLiveProofOperationKind
    source_client_order_id: str
    root_client_order_id: str
    attached_intent_id: str
    materialization_id: str | None
    child_client_order_id: str | None
    correlation_id: str
    audit_id: str
    operation_idempotency_key_sha256: str
    claimed: bool


@dataclass(frozen=True, slots=True)
class LiveProofTerminalEvidence:
    """Sanitized immutable goal terminal used only for replay convergence."""

    operation_kind: FollowUpLiveProofOperationKind
    source_client_order_id: str
    outcome: FollowUpLiveProofTerminalOutcome
    correlation_id: str
    audit_id: str
    operation_idempotency_key_sha256: str
    sdk_mutation_invocation_state: FollowUpSdkMutationInvocationState
    transport_submission_state: FollowUpTransportSubmissionState
    exchange_mutation_state: FollowUpExchangeMutationState
    read_accounting_state: FollowUpReadAccountingState
    observed_read_count: int | None
    external_call_started: bool
    reported_read_count: int
    individual_retry_count: int
    authoritative_child_state: ChildExchangeState | None


@dataclass(frozen=True, slots=True)
class PersistedInvocationResult:
    """Fixed evidence written after an invocation (or terminal no-op read)."""

    outcome: ExchangeInvocationOutcome
    child_state: ChildExchangeState
    diagnostic_code: str
    operation_idempotency_key_sha256: str
    correlation_id: str
    exchange_order_id_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class MutationInvocationAccounting:
    """Observed mutation activity, kept separate from allowance consumption."""

    sdk_mutation_invocation_state: FollowUpSdkMutationInvocationState
    transport_submission_state: FollowUpTransportSubmissionState
    exchange_mutation_state: FollowUpExchangeMutationState
    read_accounting_state: FollowUpReadAccountingState
    observed_read_count: int | None
    individual_retry_count: int
    policy_clean: bool

    @property
    def sdk_invoked(self) -> bool:
        return (
            self.sdk_mutation_invocation_state
            is FollowUpSdkMutationInvocationState.INVOKED
        )


@dataclass(frozen=True, slots=True)
class MaterializationReadResult:
    record: FollowUpMaterializationRecord | None
    read_only: bool = True
    live_read_ran: bool = False
    create_call_ran: bool = False
    cancel_call_ran: bool = False


@dataclass(frozen=True, slots=True)
class MaterializationOperationResult:
    record: FollowUpMaterializationRecord
    diagnostic_code: str
    replayed: bool
    live_read_ran: bool
    create_call_ran: bool
    cancel_call_ran: bool
    eligibility: FreshMaterializationEligibility | None = None
    candidate: BackendMaterializationCandidate | None = None


class OperatorFollowUpMaterializationRepository(Protocol):
    def live_proof_invocation_guard(
        self,
        *,
        source_client_order_id: str,
    ) -> AbstractContextManager[None]: ...

    def claim_live_proof_operation(
        self,
        *,
        operation_kind: FollowUpLiveProofOperationKind,
        source_client_order_id: str,
        correlation_id: str,
        audit_id: str,
        operation_idempotency_key_sha256: str,
    ) -> LiveProofOperationClaim: ...

    def record_live_proof_terminal(
        self,
        *,
        operation_kind: FollowUpLiveProofOperationKind,
        source_client_order_id: str,
        outcome: FollowUpLiveProofTerminalOutcome,
        sdk_mutation_invocation_state: FollowUpSdkMutationInvocationState,
        transport_submission_state: FollowUpTransportSubmissionState,
        exchange_mutation_state: FollowUpExchangeMutationState,
        read_accounting_state: FollowUpReadAccountingState,
        observed_read_count: int | None,
        external_call_started: bool,
        reported_read_count: int,
        individual_retry_count: int,
        authoritative_child_state: ChildExchangeState | None,
    ) -> None: ...

    def read_live_proof_terminal(
        self,
        *,
        operation_kind: FollowUpLiveProofOperationKind,
        source_client_order_id: str,
    ) -> LiveProofTerminalEvidence | None: ...

    def read_live_proof_claim(
        self,
        *,
        operation_kind: FollowUpLiveProofOperationKind,
        source_client_order_id: str,
    ) -> LiveProofOperationClaim | None: ...

    def claim_create_invocation_started_atomically(
        self,
        *,
        source_client_order_id: str,
        materialization_id: str,
        correlation_id: str,
        audit_id: str,
        operation_idempotency_key_sha256: str,
    ) -> InvocationBoundaryClaim: ...

    def finalize_create_invocation_atomically(
        self,
        *,
        source_client_order_id: str,
        materialization_id: str,
        result: PersistedInvocationResult,
        accounting: MutationInvocationAccounting,
        external_call_started: bool,
        reported_read_count: int,
        individual_retry_count: int,
    ) -> FollowUpMaterializationRecord: ...

    def claim_cancel_invocation_started_atomically(
        self,
        *,
        source_client_order_id: str,
        materialization_id: str,
        idempotency_key: str,
        actor_id: str,
        roles: tuple[str, ...],
        environment: str,
        operator_intent: str,
        correlation_id: str,
        audit_id: str,
    ) -> InvocationBoundaryClaim: ...

    def finalize_cancel_invocation_atomically(
        self,
        *,
        source_client_order_id: str,
        materialization_id: str,
        result: PersistedInvocationResult,
        accounting: MutationInvocationAccounting,
        external_call_started: bool,
        reported_read_count: int,
        individual_retry_count: int,
    ) -> FollowUpMaterializationRecord: ...

    def finalize_active_reconciliation_atomically(
        self,
        *,
        source_client_order_id: str,
        record: FollowUpMaterializationRecord,
        claim: LiveProofOperationClaim,
        evidence: ChildStateEvidence,
    ) -> FollowUpMaterializationRecord: ...

    def finalize_terminal_without_cancel_atomically(
        self,
        *,
        source_client_order_id: str,
        record: FollowUpMaterializationRecord,
        claim: LiveProofOperationClaim,
        evidence: ChildStateEvidence,
        result: PersistedInvocationResult,
        idempotency_key: str,
        actor_id: str,
        roles: tuple[str, ...],
        environment: str,
        operator_intent: str,
        correlation_id: str,
        audit_id: str,
    ) -> FollowUpMaterializationRecord: ...

    def read_materialization(
        self,
        *,
        source_client_order_id: str,
        operation: str,
        idempotency_key: str | None,
    ) -> FollowUpMaterializationRecord | None: ...

    def prepare_materialization(
        self,
        command: MaterializationPrepareCommand,
    ) -> FollowUpMaterializationRecord: ...

    def mark_create_invocation_started(
        self,
        *,
        materialization_id: str,
        correlation_id: str,
    ) -> InvocationBoundaryClaim: ...

    def record_create_result(
        self,
        *,
        materialization_id: str,
        result: PersistedInvocationResult,
    ) -> FollowUpMaterializationRecord: ...

    def mark_cancel_invocation_started(
        self,
        *,
        materialization_id: str,
        idempotency_key: str,
        actor_id: str,
        roles: tuple[str, ...],
        environment: str,
        operator_intent: str,
        correlation_id: str,
        audit_id: str,
    ) -> InvocationBoundaryClaim: ...

    def record_cancel_result(
        self,
        *,
        materialization_id: str,
        result: PersistedInvocationResult,
    ) -> FollowUpMaterializationRecord: ...

    def record_child_terminal_without_cancel(
        self,
        *,
        materialization_id: str,
        result: PersistedInvocationResult,
        idempotency_key: str,
        actor_id: str,
        roles: tuple[str, ...],
        environment: str,
        operator_intent: str,
        audit_id: str,
    ) -> FollowUpMaterializationRecord: ...


class OperatorFollowUpMaterializationRuntime(Protocol):
    def resolve_fresh_materialization_eligibility(
        self,
        *,
        source_client_order_id: str,
    ) -> FreshMaterializationEligibility: ...

    def read_authoritative_child_state(
        self,
        *,
        child_client_order_id: str,
        materialization_id: str,
        operation_audit_id: str,
        operation_idempotency_key_sha256: str,
    ) -> ChildStateEvidence: ...

    def persist_preclaimed_child(
        self,
        *,
        candidate: BackendMaterializationCandidate,
        materialization_id: str,
    ) -> LocalChildPersistenceEvidence: ...

    def project_persisted_child_state(
        self,
        *,
        record: FollowUpMaterializationRecord,
        operation: Literal[
            "CREATE",
            "CANCEL",
            "TERMINAL_READ",
            "REPLAY_REPAIR",
        ],
        allow_reconciliation_read: bool,
        evidence_audit_id: str | None = None,
        evidence_idempotency_key_sha256: str | None = None,
    ) -> LocalChildProjectionEvidence: ...

    def validate_persisted_active_child_identity(
        self,
        *,
        record: FollowUpMaterializationRecord,
    ) -> LocalChildProjectionEvidence: ...


class OperatorFollowUpMaterializationExchange(Protocol):
    def create_follow_up_child(
        self,
        *,
        candidate: BackendMaterializationCandidate,
        correlation_id: str,
        materialization_id: str,
        operation_audit_id: str,
        operation_idempotency_key_sha256: str,
    ) -> ExchangeInvocationResult: ...

    def cancel_follow_up_child(
        self,
        *,
        child_client_order_id: str,
        correlation_id: str,
        materialization_id: str,
        operation_audit_id: str,
        operation_idempotency_key_sha256: str,
    ) -> ExchangeInvocationResult: ...


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _role_value(value: object) -> str:
    return _clean_text(getattr(value, "value", value))


def _context_has_permission(
    context: OperatorFollowUpMaterializationRequestContext,
    permission: AdminApiPermission,
) -> bool:
    granted: set[AdminApiPermission] = set()
    for raw_role in context.roles:
        try:
            role = AdminApiRole(_role_value(raw_role))
        except ValueError:
            continue
        granted.update(ROLE_PERMISSIONS.get(role, frozenset()))
    return permission in granted


def _require_context(
    context: OperatorFollowUpMaterializationRequestContext,
    *,
    expected_intent: str,
    permission: AdminApiPermission,
) -> None:
    if context.operator_intent != expected_intent:
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_operator_intent_mismatch",
            400,
        )
    if not all(
        _clean_text(value)
        for value in (
            context.actor_id,
            context.idempotency_key,
            context.correlation_id,
            context.environment,
            context.audit_id,
        )
    ):
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_context_invalid",
            400,
        )
    if any(
        len(_clean_text(value)) > maximum
        for value, maximum in (
            (context.actor_id, 256),
            (context.idempotency_key, 512),
            (context.correlation_id, 256),
            (context.environment, 128),
            (context.audit_id, 64),
        )
    ):
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_context_invalid",
            400,
        )
    if not _context_has_permission(context, permission):
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_permission_denied",
            403,
        )


def _require_source_client_order_id(value: str) -> str:
    normalized = _clean_text(value)
    if not normalized or len(normalized) > 256:
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_source_client_order_id_invalid",
            422,
        )
    return normalized


def _require_materialization_authorization(
    request: MaterializationAuthorization,
) -> None:
    acknowledgements = (
        getattr(
            request,
            "authorize_materialization_of_attached_intent",
            False,
        ),
        getattr(
            request,
            "acknowledge_unknown_outcome_consumes_create_allowance",
            False,
        ),
        getattr(
            request,
            "acknowledge_child_terms_are_backend_derived",
            False,
        ),
    )
    if any(value is not True for value in acknowledgements):
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_fresh_authorization_required",
            400,
        )


def _require_closeout_authorization(request: SafeCloseoutAuthorization) -> None:
    acknowledgements = (
        getattr(request, "authorize_single_cancel_for_safe_closeout", False),
        getattr(
            request,
            "acknowledge_unknown_outcome_consumes_cancel_allowance",
            False,
        ),
    )
    if any(value is not True for value in acknowledgements):
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_safe_closeout_authorization_required",
            400,
        )


def _decimal(value: object) -> Decimal | None:
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return normalized if normalized.is_finite() else None


def _validate_sha256(value: str) -> bool:
    normalized = _clean_text(value).lower()
    return len(normalized) == 64 and all(character in "0123456789abcdef" for character in normalized)


def _validate_candidate(
    evidence: FreshMaterializationEligibility,
    *,
    source_client_order_id: str,
    expected_environment: str,
) -> BackendMaterializationCandidate:
    if evidence.fresh is not True:
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_eligibility_not_fresh",
            409,
        )
    if evidence.coinbase_read_started is not True:
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_live_read_required",
            409,
        )
    if (
        type(evidence.coinbase_read_count) is not int
        or not 1 <= evidence.coinbase_read_count <= 10
    ):
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_eligibility_pass_invalid",
            409,
        )
    if evidence.individual_retry_count != 0:
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_eligibility_retry_detected",
            409,
        )
    if (
        evidence.eligibility_pass_count != 1
        or evidence.reconciliation_pass_count != 1
    ):
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_eligibility_pass_invalid",
            409,
        )
    if evidence.ambiguous is True:
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_eligibility_ambiguous",
            409,
        )
    if evidence.blockers:
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_eligibility_blocked",
            409,
        )
    candidate = evidence.candidate
    if candidate is None:
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_candidate_unavailable",
            409,
        )
    if candidate.source_client_order_id != source_client_order_id:
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_candidate_identity_mismatch",
            409,
        )
    if candidate.environment != expected_environment:
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_environment_mismatch",
            409,
        )
    if not all(
        _clean_text(value)
        for value in (
            candidate.attached_intent_id,
            candidate.root_client_order_id,
            candidate.child_client_order_id,
            candidate.product_id,
            candidate.portfolio_id,
            candidate.environment,
        )
    ) or candidate.child_client_order_id in {
        candidate.source_client_order_id,
        candidate.root_client_order_id,
    }:
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_candidate_identity_invalid",
            409,
        )
    if (
        _clean_text(candidate.source_status).upper() != "FILLED"
        or candidate.authoritative_source_fill_proven is not True
        or candidate.source_terminal is not True
    ):
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_authoritative_fill_required",
            409,
        )
    if candidate.attached_intent_requires_fresh_authorization is not True:
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_attachment_authority_invalid",
            409,
        )
    if candidate.no_existing_follow_up_child is not True:
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_child_already_exists",
            409,
        )
    if candidate.controlled_live_enabled is not True:
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_controlled_live_required",
            503,
        )
    if candidate.execution_lease_valid is not True:
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_execution_lease_required",
            503,
        )
    if (
        _clean_text(candidate.portfolio_type).upper() != "TEST"
        or candidate.approved_test_portfolio_verified is not True
        or not _validate_sha256(candidate.portfolio_scope_sha256)
        or candidate.portfolio_scope_sha256.lower()
        != _sha256(candidate.portfolio_id)
    ):
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_test_portfolio_required",
            409,
        )
    if _clean_text(candidate.product_type).upper() != "SPOT":
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_spot_product_required",
            409,
        )
    if candidate.product_policy_allowed is not True:
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_product_policy_blocked",
            409,
        )
    if candidate.action_condition_guard_passed is not True:
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_action_condition_guard_failed",
            409,
        )
    if candidate.wallet_check_passed is not True:
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_wallet_check_failed",
            409,
        )
    source_side = _clean_text(candidate.source_side).upper()
    child_side = _clean_text(candidate.child_side).upper()
    if (source_side, child_side) not in {("BUY", "SELL"), ("SELL", "BUY")}:
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_child_side_invalid",
            409,
        )
    base_size = _decimal(candidate.base_size)
    limit_price = _decimal(candidate.limit_price)
    submitted_notional = _decimal(candidate.submitted_notional_usdc)
    max_submitted_notional = _decimal(candidate.max_submitted_notional_usdc)
    max_executed_notional = _decimal(candidate.max_executed_notional_usdc)
    effective_notional_cap = _decimal(candidate.effective_notional_cap_usdc)
    if (
        base_size is None
        or limit_price is None
        or submitted_notional is None
        or max_submitted_notional is None
        or max_executed_notional is None
        or effective_notional_cap is None
        or min(
            base_size,
            limit_price,
            submitted_notional,
            max_submitted_notional,
            max_executed_notional,
            effective_notional_cap,
        )
        <= 0
        or base_size * limit_price != submitted_notional
    ):
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_order_tuple_invalid",
            409,
        )
    if not (
        max_submitted_notional == CURRENT_MAX_SUBMITTED_NOTIONAL_USDC
        and max_executed_notional == CURRENT_MAX_EXECUTED_NOTIONAL_USDC
        and effective_notional_cap == CURRENT_EFFECTIVE_NOTIONAL_CAP_USDC
        and submitted_notional <= max_submitted_notional
        and submitted_notional <= effective_notional_cap
    ):
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_current_caps_exceeded",
            409,
        )
    return candidate


def _request_sha256(
    *,
    source_client_order_id: str,
    request: MaterializationAuthorization,
    context: OperatorFollowUpMaterializationRequestContext,
    candidate: BackendMaterializationCandidate,
) -> str:
    payload = {
        "source_client_order_id": source_client_order_id,
        "actor_id": context.actor_id,
        "roles": sorted(_role_value(role) for role in context.roles),
        "environment": context.environment,
        "operator_intent": context.operator_intent,
        "acknowledgements": {
            "authorize_materialization_of_attached_intent": getattr(
                request,
                "authorize_materialization_of_attached_intent",
                False,
            ),
            "unknown_outcome_consumes_create_allowance": getattr(
                request,
                "acknowledge_unknown_outcome_consumes_create_allowance",
                False,
            ),
            "child_terms_are_backend_derived": getattr(
                request,
                "acknowledge_child_terms_are_backend_derived",
                False,
            ),
        },
        "backend_candidate": {
            "attached_intent_id": candidate.attached_intent_id,
            "source_client_order_id": candidate.source_client_order_id,
            "root_client_order_id": candidate.root_client_order_id,
            "child_client_order_id": candidate.child_client_order_id,
            "product_id": candidate.product_id,
            "product_type": candidate.product_type,
            "portfolio_scope_sha256": candidate.portfolio_scope_sha256,
            "child_side": candidate.child_side,
            "base_size": str(candidate.base_size),
            "limit_price": str(candidate.limit_price),
            "submitted_notional_usdc": str(candidate.submitted_notional_usdc),
            "max_submitted_notional_usdc": str(
                candidate.max_submitted_notional_usdc
            ),
            "max_executed_notional_usdc": str(
                candidate.max_executed_notional_usdc
            ),
            "effective_notional_cap_usdc": str(
                candidate.effective_notional_cap_usdc
            ),
        },
    }
    return _sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"))
    )


def _validate_record(
    record: FollowUpMaterializationRecord,
    *,
    source_client_order_id: str,
) -> FollowUpMaterializationRecord:
    if record.source_client_order_id != source_client_order_id:
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_record_identity_mismatch",
            503,
        )
    if not all(
        _clean_text(value)
        for value in (
            record.materialization_id,
            record.attached_intent_id,
            record.root_client_order_id,
            record.child_client_order_id,
            record.correlation_id,
            record.audit_id,
        )
    ):
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_record_invalid",
            503,
        )
    if not _validate_sha256(record.create_idempotency_key_sha256):
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_record_invalid",
            503,
        )
    if (
        record.cancel_idempotency_key_sha256 is not None
        and not _validate_sha256(record.cancel_idempotency_key_sha256)
    ):
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_record_invalid",
            503,
        )
    if record.diagnostic_code not in _SAFE_DIAGNOSTICS:
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_record_diagnostic_invalid",
            503,
        )
    create_consuming_states = {
        MaterializationRecordState.CREATE_INVOCATION_STARTED,
        MaterializationRecordState.CREATE_ACCEPTED,
        MaterializationRecordState.CREATE_REJECTED,
        MaterializationRecordState.CREATE_UNKNOWN,
        MaterializationRecordState.CANCEL_INVOCATION_STARTED,
        MaterializationRecordState.CANCEL_ACCEPTED,
        MaterializationRecordState.CANCEL_REJECTED,
        MaterializationRecordState.CANCEL_UNKNOWN,
        MaterializationRecordState.CHILD_ALREADY_TERMINAL,
    }
    cancel_consuming_states = {
        MaterializationRecordState.CANCEL_INVOCATION_STARTED,
        MaterializationRecordState.CANCEL_ACCEPTED,
        MaterializationRecordState.CANCEL_REJECTED,
        MaterializationRecordState.CANCEL_UNKNOWN,
    }
    if (record.state in create_consuming_states) is not record.create_call_consumed:
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_record_allowance_invalid",
            503,
        )
    if (record.state in cancel_consuming_states) is not record.cancel_call_consumed:
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_record_allowance_invalid",
            503,
        )
    return record


def _require_prepared_record_matches_candidate(
    record: FollowUpMaterializationRecord,
    candidate: BackendMaterializationCandidate,
) -> None:
    if (
        record.attached_intent_id != candidate.attached_intent_id
        or record.source_client_order_id != candidate.source_client_order_id
        or record.root_client_order_id != candidate.root_client_order_id
        or record.child_client_order_id != candidate.child_client_order_id
    ):
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_record_identity_mismatch",
            503,
        )


_PROJECTABLE_RECORD_STATES = frozenset(
    {
        MaterializationRecordState.CREATE_ACCEPTED,
        MaterializationRecordState.CREATE_REJECTED,
        MaterializationRecordState.CREATE_UNKNOWN,
        MaterializationRecordState.CANCEL_ACCEPTED,
        MaterializationRecordState.CANCEL_REJECTED,
        MaterializationRecordState.CANCEL_UNKNOWN,
        MaterializationRecordState.CHILD_ALREADY_TERMINAL,
    }
)


def _project_persisted_child_state(
    *,
    runtime: OperatorFollowUpMaterializationRuntime,
    record: FollowUpMaterializationRecord,
    operation: Literal[
        "CREATE",
        "CANCEL",
        "TERMINAL_READ",
        "REPLAY_REPAIR",
    ],
    allow_reconciliation_read: bool,
    evidence_audit_id: str | None = None,
    evidence_idempotency_key_sha256: str | None = None,
) -> LocalChildProjectionEvidence | None:
    """Project only after the durable result event; never repeat a mutation."""

    if record.state not in _PROJECTABLE_RECORD_STATES:
        return None
    try:
        projection_kwargs: dict[str, object] = {
            "record": record,
            "operation": operation,
            "allow_reconciliation_read": allow_reconciliation_read,
        }
        if evidence_audit_id is not None:
            projection_kwargs["evidence_audit_id"] = evidence_audit_id
        if evidence_idempotency_key_sha256 is not None:
            projection_kwargs["evidence_idempotency_key_sha256"] = (
                evidence_idempotency_key_sha256
            )
        evidence = runtime.project_persisted_child_state(
            **projection_kwargs,
        )
    except Exception:
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_child_projection_unavailable",
            503,
        ) from None
    if (
        evidence.materialization_id != record.materialization_id
        or evidence.child_client_order_id != record.child_client_order_id
        or evidence.record_state != record.state
        or evidence.projected is not True
        or evidence.exact_replay_safe is not True
        or evidence.exchange_call_ran is not False
        or isinstance(evidence.live_read_count, bool)
        or evidence.live_read_count not in ({0, 1} if allow_reconciliation_read else {0})
        or isinstance(evidence.individual_retry_count, bool)
        or evidence.individual_retry_count != 0
    ):
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_child_projection_invalid",
            503,
        )
    return evidence


def _fixed_invocation_result(
    result: object,
    *,
    operation: str,
    idempotency_key: str,
    correlation_id: str,
    force_unknown: bool = False,
) -> PersistedInvocationResult:
    call_started = getattr(result, "exchange_call_started", False) is True
    outcome = getattr(result, "outcome", ExchangeInvocationOutcome.UNKNOWN)
    child_state = getattr(result, "child_state", ChildExchangeState.UNKNOWN)
    raw_exchange_hash = getattr(result, "exchange_order_id_sha256", None)
    normalized_exchange_hash = _clean_text(raw_exchange_hash).lower()
    accepted_identity_valid = _validate_sha256(normalized_exchange_hash)
    if force_unknown or (
        not call_started and outcome is not ExchangeInvocationOutcome.UNKNOWN
    ):
        outcome = ExchangeInvocationOutcome.UNKNOWN
        child_state = ChildExchangeState.UNKNOWN
    if operation == "CREATE":
        if outcome == ExchangeInvocationOutcome.ACCEPTED:
            if accepted_identity_valid and child_state in {
                ChildExchangeState.ACTIVE,
                ChildExchangeState.TERMINAL,
            }:
                diagnostic = CREATE_ACCEPTED_DIAGNOSTIC
                normalized_state = child_state
            else:
                outcome = ExchangeInvocationOutcome.UNKNOWN
                diagnostic = CREATE_UNKNOWN_DIAGNOSTIC
                normalized_state = ChildExchangeState.UNKNOWN
        elif outcome == ExchangeInvocationOutcome.REJECTED:
            diagnostic = CREATE_REJECTED_DIAGNOSTIC
            normalized_state = ChildExchangeState.UNKNOWN
        else:
            outcome = ExchangeInvocationOutcome.UNKNOWN
            diagnostic = CREATE_UNKNOWN_DIAGNOSTIC
            normalized_state = ChildExchangeState.UNKNOWN
    else:
        if outcome == ExchangeInvocationOutcome.ACCEPTED:
            if (
                accepted_identity_valid
                and child_state is ChildExchangeState.TERMINAL
            ):
                diagnostic = CANCEL_ACCEPTED_DIAGNOSTIC
                normalized_state = child_state
            else:
                outcome = ExchangeInvocationOutcome.UNKNOWN
                diagnostic = CANCEL_UNKNOWN_DIAGNOSTIC
                normalized_state = ChildExchangeState.UNKNOWN
        elif outcome == ExchangeInvocationOutcome.REJECTED:
            diagnostic = CANCEL_REJECTED_DIAGNOSTIC
            normalized_state = ChildExchangeState.ACTIVE
        else:
            outcome = ExchangeInvocationOutcome.UNKNOWN
            diagnostic = CANCEL_UNKNOWN_DIAGNOSTIC
            normalized_state = ChildExchangeState.UNKNOWN
    exchange_order_id_sha256 = (
        normalized_exchange_hash
        if outcome == ExchangeInvocationOutcome.ACCEPTED
        and _validate_sha256(normalized_exchange_hash)
        else None
    )
    return PersistedInvocationResult(
        outcome=outcome,
        child_state=normalized_state,
        diagnostic_code=diagnostic,
        operation_idempotency_key_sha256=_sha256(idempotency_key),
        correlation_id=correlation_id,
        exchange_order_id_sha256=exchange_order_id_sha256,
    )


def _normalized_invocation_accounting(
    result: object,
    *,
    exchange_call_started: bool,
) -> MutationInvocationAccounting:
    """Normalize exact activity or preserve a conservative unknown tuple."""

    raw_read_started = getattr(result, "post_mutation_read_started", False)
    raw_read_count = getattr(result, "post_mutation_read_count", 0)
    raw_retry_count = getattr(result, "individual_retry_count", 0)
    raw_outcome = getattr(result, "outcome", ExchangeInvocationOutcome.UNKNOWN)
    retry_count = raw_retry_count if type(raw_retry_count) is int else 0
    explicit_values = (
        getattr(result, "sdk_mutation_invocation_state", None),
        getattr(result, "transport_submission_state", None),
        getattr(result, "exchange_mutation_state", None),
        getattr(result, "read_accounting_state", None),
    )
    explicit_supplied = any(value is not None for value in explicit_values)
    if explicit_supplied:
        try:
            sdk_state = FollowUpSdkMutationInvocationState(explicit_values[0])
            transport_state = FollowUpTransportSubmissionState(explicit_values[1])
            exchange_state = FollowUpExchangeMutationState(explicit_values[2])
            read_state = FollowUpReadAccountingState(explicit_values[3])
        except (TypeError, ValueError):
            pass
        else:
            observed_count = getattr(result, "observed_read_count", None)
            count_valid = bool(
                (
                    read_state is FollowUpReadAccountingState.EXACT
                    and type(observed_count) is int
                    and 0 <= observed_count <= 10
                )
                or (
                    read_state is FollowUpReadAccountingState.UNKNOWN
                    and observed_count is None
                )
            )
            outcome_valid = bool(
                (
                    raw_outcome is ExchangeInvocationOutcome.ACCEPTED
                    and sdk_state is FollowUpSdkMutationInvocationState.INVOKED
                    and transport_state
                    is FollowUpTransportSubmissionState.CONFIRMED_SUBMITTED
                    and exchange_state
                    is FollowUpExchangeMutationState.CONFIRMED_MUTATED
                    and read_state is FollowUpReadAccountingState.EXACT
                    and observed_count == 1
                )
                or (
                    raw_outcome is ExchangeInvocationOutcome.REJECTED
                    and sdk_state is FollowUpSdkMutationInvocationState.INVOKED
                    and transport_state
                    is FollowUpTransportSubmissionState.CONFIRMED_SUBMITTED
                    and exchange_state is FollowUpExchangeMutationState.NOT_MUTATED
                    and read_state is FollowUpReadAccountingState.EXACT
                    and observed_count == 0
                )
                or (
                    raw_outcome is ExchangeInvocationOutcome.UNKNOWN
                    and (
                        (
                            sdk_state
                            in {
                                FollowUpSdkMutationInvocationState.INVOKED,
                                FollowUpSdkMutationInvocationState.UNKNOWN,
                            }
                            and transport_state
                            is FollowUpTransportSubmissionState.POSSIBLY_SUBMITTED
                            and exchange_state
                            is FollowUpExchangeMutationState.UNKNOWN
                            and read_state is FollowUpReadAccountingState.UNKNOWN
                            and observed_count is None
                        )
                        or (
                            sdk_state
                            is FollowUpSdkMutationInvocationState.NOT_INVOKED
                            and transport_state
                            is FollowUpTransportSubmissionState.NOT_SUBMITTED
                            and exchange_state
                            is FollowUpExchangeMutationState.NOT_MUTATED
                            and read_state is FollowUpReadAccountingState.EXACT
                            and observed_count == 0
                        )
                    )
                )
            )
            policy_clean = bool(
                count_valid
                and outcome_valid
                and type(raw_retry_count) is int
                and raw_retry_count == 0
            )
            if policy_clean:
                return MutationInvocationAccounting(
                    sdk_mutation_invocation_state=sdk_state,
                    transport_submission_state=transport_state,
                    exchange_mutation_state=exchange_state,
                    read_accounting_state=read_state,
                    observed_read_count=observed_count,
                    individual_retry_count=0,
                    policy_clean=True,
                )

    legacy_exact = bool(
        not explicit_supplied
        and type(raw_read_started) is bool
        and type(raw_read_count) is int
        and type(raw_retry_count) is int
        and raw_retry_count == 0
        and 0 <= raw_read_count <= 10
    )
    if (
        legacy_exact
        and raw_outcome is ExchangeInvocationOutcome.ACCEPTED
        and exchange_call_started
        and raw_read_started is True
        and raw_read_count == 1
    ):
        return MutationInvocationAccounting(
            sdk_mutation_invocation_state=(
                FollowUpSdkMutationInvocationState.INVOKED
            ),
            transport_submission_state=(
                FollowUpTransportSubmissionState.CONFIRMED_SUBMITTED
            ),
            exchange_mutation_state=FollowUpExchangeMutationState.CONFIRMED_MUTATED,
            read_accounting_state=FollowUpReadAccountingState.EXACT,
            observed_read_count=1,
            individual_retry_count=0,
            policy_clean=True,
        )
    if (
        legacy_exact
        and raw_outcome is ExchangeInvocationOutcome.REJECTED
        and exchange_call_started
        and raw_read_started is False
        and raw_read_count == 0
    ):
        return MutationInvocationAccounting(
            sdk_mutation_invocation_state=(
                FollowUpSdkMutationInvocationState.INVOKED
            ),
            transport_submission_state=(
                FollowUpTransportSubmissionState.CONFIRMED_SUBMITTED
            ),
            exchange_mutation_state=FollowUpExchangeMutationState.NOT_MUTATED,
            read_accounting_state=FollowUpReadAccountingState.EXACT,
            observed_read_count=0,
            individual_retry_count=0,
            policy_clean=True,
        )
    if (
        legacy_exact
        and raw_outcome is ExchangeInvocationOutcome.UNKNOWN
        and exchange_call_started is False
        and raw_read_started is False
        and raw_read_count == 0
    ):
        return MutationInvocationAccounting(
            sdk_mutation_invocation_state=(
                FollowUpSdkMutationInvocationState.NOT_INVOKED
            ),
            transport_submission_state=(
                FollowUpTransportSubmissionState.NOT_SUBMITTED
            ),
            exchange_mutation_state=FollowUpExchangeMutationState.NOT_MUTATED,
            read_accounting_state=FollowUpReadAccountingState.EXACT,
            observed_read_count=0,
            individual_retry_count=0,
            policy_clean=True,
        )
    return MutationInvocationAccounting(
        sdk_mutation_invocation_state=FollowUpSdkMutationInvocationState.UNKNOWN,
        transport_submission_state=(
            FollowUpTransportSubmissionState.POSSIBLY_SUBMITTED
        ),
        exchange_mutation_state=FollowUpExchangeMutationState.UNKNOWN,
        read_accounting_state=FollowUpReadAccountingState.UNKNOWN,
        observed_read_count=None,
        individual_retry_count=(retry_count if 0 <= retry_count <= 10 else 0),
        policy_clean=False,
    )


def _exact_read_count(value: object) -> int | None:
    return value if type(value) is int and 0 <= value <= 10 else None


def _read_operation_accounting(
    observed_read_count: int | None,
) -> dict[str, object]:
    exact = observed_read_count is not None
    return {
        "sdk_mutation_invocation_state": (
            FollowUpSdkMutationInvocationState.NOT_INVOKED
        ),
        "transport_submission_state": (
            FollowUpTransportSubmissionState.NOT_SUBMITTED
        ),
        "exchange_mutation_state": FollowUpExchangeMutationState.NOT_MUTATED,
        "read_accounting_state": (
            FollowUpReadAccountingState.EXACT
            if exact
            else FollowUpReadAccountingState.UNKNOWN
        ),
        "observed_read_count": observed_read_count,
        "external_call_started": False,
        "reported_read_count": observed_read_count or 0,
    }


def _mutation_operation_accounting(
    accounting: MutationInvocationAccounting,
) -> dict[str, object]:
    return {
        "sdk_mutation_invocation_state": (
            accounting.sdk_mutation_invocation_state
        ),
        "transport_submission_state": accounting.transport_submission_state,
        "exchange_mutation_state": accounting.exchange_mutation_state,
        "read_accounting_state": accounting.read_accounting_state,
        "observed_read_count": accounting.observed_read_count,
        "external_call_started": accounting.sdk_invoked,
        "reported_read_count": accounting.observed_read_count or 0,
    }


class OperatorFollowUpMaterializationService:
    """Orchestrate one bounded create and its optional exact-child closeout."""

    def __init__(
        self,
        *,
        repository: OperatorFollowUpMaterializationRepository,
        runtime: OperatorFollowUpMaterializationRuntime,
        exchange: OperatorFollowUpMaterializationExchange,
    ) -> None:
        self.repository = repository
        self.runtime = runtime
        self.exchange = exchange

    def _claim_live_proof_operation(
        self,
        *,
        operation_kind: FollowUpLiveProofOperationKind,
        source_client_order_id: str,
        context: OperatorFollowUpMaterializationRequestContext,
        record: FollowUpMaterializationRecord | None = None,
    ) -> LiveProofOperationClaim:
        try:
            claim = self.repository.claim_live_proof_operation(
                operation_kind=operation_kind,
                source_client_order_id=source_client_order_id,
                correlation_id=context.correlation_id,
                audit_id=context.audit_id,
                operation_idempotency_key_sha256=_sha256(
                    context.idempotency_key
                ),
            )
        except Exception:
            raise OperatorFollowUpMaterializationError(
                "follow_up_live_proof_operation_unavailable",
                409,
            ) from None
        if (
            claim.claimed is not True
            or claim.operation_kind is not operation_kind
            or claim.source_client_order_id != source_client_order_id
            or claim.correlation_id != context.correlation_id
            or claim.audit_id != context.audit_id
            or claim.operation_idempotency_key_sha256
            != _sha256(context.idempotency_key)
            or not _clean_text(claim.root_client_order_id)
            or not _clean_text(claim.attached_intent_id)
        ):
            raise OperatorFollowUpMaterializationError(
                "follow_up_live_proof_claim_invalid",
                503,
            )
        requires_child = operation_kind is not FollowUpLiveProofOperationKind.ELIGIBILITY_READ
        if requires_child != bool(
            _clean_text(claim.materialization_id)
            and _clean_text(claim.child_client_order_id)
        ):
            raise OperatorFollowUpMaterializationError(
                "follow_up_live_proof_claim_invalid",
                503,
            )
        if record is not None and (
            claim.root_client_order_id != record.root_client_order_id
            or claim.attached_intent_id != record.attached_intent_id
            or claim.materialization_id != record.materialization_id
            or claim.child_client_order_id != record.child_client_order_id
        ):
            raise OperatorFollowUpMaterializationError(
                "follow_up_live_proof_claim_binding_mismatch",
                503,
            )
        return claim

    def _record_live_proof_terminal(
        self,
        *,
        operation_kind: FollowUpLiveProofOperationKind,
        source_client_order_id: str,
        outcome: FollowUpLiveProofTerminalOutcome,
        sdk_mutation_invocation_state: FollowUpSdkMutationInvocationState,
        transport_submission_state: FollowUpTransportSubmissionState,
        exchange_mutation_state: FollowUpExchangeMutationState,
        read_accounting_state: FollowUpReadAccountingState,
        observed_read_count: int | None,
        external_call_started: bool,
        reported_read_count: int,
        individual_retry_count: int,
        authoritative_child_state: ChildExchangeState | None = None,
    ) -> None:
        try:
            self.repository.record_live_proof_terminal(
                operation_kind=operation_kind,
                source_client_order_id=source_client_order_id,
                outcome=outcome,
                sdk_mutation_invocation_state=sdk_mutation_invocation_state,
                transport_submission_state=transport_submission_state,
                exchange_mutation_state=exchange_mutation_state,
                read_accounting_state=read_accounting_state,
                observed_read_count=observed_read_count,
                external_call_started=external_call_started,
                reported_read_count=reported_read_count,
                individual_retry_count=individual_retry_count,
                authoritative_child_state=authoritative_child_state,
            )
        except Exception:
            raise OperatorFollowUpMaterializationError(
                "follow_up_live_proof_terminal_persistence_unavailable",
                503,
            ) from None

    def _read_live_proof_terminal(
        self,
        *,
        operation_kind: FollowUpLiveProofOperationKind,
        source_client_order_id: str,
    ) -> LiveProofTerminalEvidence | None:
        try:
            evidence = self.repository.read_live_proof_terminal(
                operation_kind=operation_kind,
                source_client_order_id=source_client_order_id,
            )
        except Exception:
            raise OperatorFollowUpMaterializationError(
                "follow_up_live_proof_terminal_persistence_unavailable",
                503,
            ) from None
        if evidence is None:
            return None
        if (
            evidence.operation_kind is not operation_kind
            or evidence.source_client_order_id != source_client_order_id
            or not isinstance(evidence.outcome, FollowUpLiveProofTerminalOutcome)
            or not _clean_text(evidence.correlation_id)
            or not _clean_text(evidence.audit_id)
            or not _validate_sha256(evidence.operation_idempotency_key_sha256)
            or not isinstance(
                evidence.sdk_mutation_invocation_state,
                FollowUpSdkMutationInvocationState,
            )
            or not isinstance(
                evidence.transport_submission_state,
                FollowUpTransportSubmissionState,
            )
            or not isinstance(
                evidence.exchange_mutation_state,
                FollowUpExchangeMutationState,
            )
            or not isinstance(
                evidence.read_accounting_state,
                FollowUpReadAccountingState,
            )
            or (
                evidence.read_accounting_state is FollowUpReadAccountingState.EXACT
                and (
                    type(evidence.observed_read_count) is not int
                    or not 0 <= evidence.observed_read_count <= 10
                )
            )
            or (
                evidence.read_accounting_state
                is FollowUpReadAccountingState.UNKNOWN
                and evidence.observed_read_count is not None
            )
            or type(evidence.external_call_started) is not bool
            or evidence.external_call_started
            is not (
                evidence.sdk_mutation_invocation_state
                is FollowUpSdkMutationInvocationState.INVOKED
            )
            or type(evidence.reported_read_count) is not int
            or evidence.reported_read_count
            != (evidence.observed_read_count or 0)
            or type(evidence.individual_retry_count) is not int
            or evidence.individual_retry_count != 0
            or (
                evidence.authoritative_child_state is not None
                and not isinstance(
                    evidence.authoritative_child_state,
                    ChildExchangeState,
                )
            )
        ):
            raise OperatorFollowUpMaterializationError(
                "follow_up_live_proof_terminal_invalid",
                503,
            )
        return evidence

    def _read_live_proof_claim(
        self,
        *,
        operation_kind: FollowUpLiveProofOperationKind,
        source_client_order_id: str,
        record: FollowUpMaterializationRecord | None = None,
    ) -> LiveProofOperationClaim | None:
        try:
            claim = self.repository.read_live_proof_claim(
                operation_kind=operation_kind,
                source_client_order_id=source_client_order_id,
            )
        except Exception:
            raise OperatorFollowUpMaterializationError(
                "follow_up_live_proof_operation_unavailable",
                503,
            ) from None
        if claim is None:
            return None
        if (
            claim.claimed is not True
            or claim.operation_kind is not operation_kind
            or claim.source_client_order_id != source_client_order_id
            or not _clean_text(claim.root_client_order_id)
            or not _clean_text(claim.attached_intent_id)
            or not _clean_text(claim.correlation_id)
            or not _clean_text(claim.audit_id)
            or not _validate_sha256(claim.operation_idempotency_key_sha256)
        ):
            raise OperatorFollowUpMaterializationError(
                "follow_up_live_proof_claim_invalid",
                503,
            )
        if record is not None and (
            claim.root_client_order_id != record.root_client_order_id
            or claim.attached_intent_id != record.attached_intent_id
            or claim.materialization_id != record.materialization_id
            or claim.child_client_order_id != record.child_client_order_id
        ):
            raise OperatorFollowUpMaterializationError(
                "follow_up_live_proof_claim_binding_mismatch",
                503,
            )
        return claim

    def _finalize_replayed_mutation(
        self,
        *,
        record: FollowUpMaterializationRecord,
        source_client_order_id: str,
        operation: Literal["CREATE", "CANCEL"],
    ) -> None:
        """Converge a crash after projection but before the goal terminal."""

        operation_kind = (
            FollowUpLiveProofOperationKind.CREATE
            if operation == "CREATE"
            else FollowUpLiveProofOperationKind.CANCEL
        )
        if self._read_live_proof_terminal(
            operation_kind=operation_kind,
            source_client_order_id=source_client_order_id,
        ) is not None:
            return
        if operation == "CREATE":
            mapping = {
                MaterializationRecordState.CREATE_ACCEPTED: (
                    FollowUpLiveProofTerminalOutcome.SUCCEEDED,
                    FollowUpSdkMutationInvocationState.INVOKED,
                    FollowUpTransportSubmissionState.CONFIRMED_SUBMITTED,
                    FollowUpExchangeMutationState.CONFIRMED_MUTATED,
                    FollowUpReadAccountingState.EXACT,
                    1,
                ),
                MaterializationRecordState.CREATE_REJECTED: (
                    FollowUpLiveProofTerminalOutcome.REJECTED,
                    FollowUpSdkMutationInvocationState.INVOKED,
                    FollowUpTransportSubmissionState.CONFIRMED_SUBMITTED,
                    FollowUpExchangeMutationState.NOT_MUTATED,
                    FollowUpReadAccountingState.EXACT,
                    0,
                ),
                MaterializationRecordState.CREATE_UNKNOWN: (
                    FollowUpLiveProofTerminalOutcome.UNKNOWN,
                    FollowUpSdkMutationInvocationState.UNKNOWN,
                    FollowUpTransportSubmissionState.POSSIBLY_SUBMITTED,
                    FollowUpExchangeMutationState.UNKNOWN,
                    FollowUpReadAccountingState.UNKNOWN,
                    None,
                ),
            }
        else:
            mapping = {
                MaterializationRecordState.CANCEL_ACCEPTED: (
                    FollowUpLiveProofTerminalOutcome.SUCCEEDED,
                    FollowUpSdkMutationInvocationState.INVOKED,
                    FollowUpTransportSubmissionState.CONFIRMED_SUBMITTED,
                    FollowUpExchangeMutationState.CONFIRMED_MUTATED,
                    FollowUpReadAccountingState.EXACT,
                    1,
                ),
                MaterializationRecordState.CANCEL_REJECTED: (
                    FollowUpLiveProofTerminalOutcome.REJECTED,
                    FollowUpSdkMutationInvocationState.INVOKED,
                    FollowUpTransportSubmissionState.CONFIRMED_SUBMITTED,
                    FollowUpExchangeMutationState.NOT_MUTATED,
                    FollowUpReadAccountingState.EXACT,
                    0,
                ),
                MaterializationRecordState.CANCEL_UNKNOWN: (
                    FollowUpLiveProofTerminalOutcome.UNKNOWN,
                    FollowUpSdkMutationInvocationState.UNKNOWN,
                    FollowUpTransportSubmissionState.POSSIBLY_SUBMITTED,
                    FollowUpExchangeMutationState.UNKNOWN,
                    FollowUpReadAccountingState.UNKNOWN,
                    None,
                ),
            }
        classification = mapping.get(record.state)
        if classification is None:
            return
        outcome, sdk_state, transport_state, exchange_state, read_state, read_count = (
            classification
        )
        self._record_live_proof_terminal(
            operation_kind=operation_kind,
            source_client_order_id=source_client_order_id,
            outcome=outcome,
            sdk_mutation_invocation_state=sdk_state,
            transport_submission_state=transport_state,
            exchange_mutation_state=exchange_state,
            read_accounting_state=read_state,
            observed_read_count=read_count,
            external_call_started=(
                sdk_state is FollowUpSdkMutationInvocationState.INVOKED
            ),
            reported_read_count=read_count or 0,
            individual_retry_count=0,
            authoritative_child_state=record.child_state,
        )

    def read(self, *, source_client_order_id: str) -> MaterializationReadResult:
        """Read durable local evidence without invoking runtime or exchange ports."""

        source_id = _require_source_client_order_id(source_client_order_id)
        try:
            record = self.repository.read_materialization(
                source_client_order_id=source_id,
                operation="READ",
                idempotency_key=None,
            )
        except Exception:
            raise OperatorFollowUpMaterializationError(
                "follow_up_materialization_backend_unavailable",
                503,
            ) from None
        return MaterializationReadResult(
            record=(
                _validate_record(record, source_client_order_id=source_id)
                if record is not None
                else None
            )
        )

    def _recover_invocation_started(
        self,
        *,
        record: FollowUpMaterializationRecord,
        source_client_order_id: str,
        operation: Literal["CREATE", "CANCEL"],
        context: OperatorFollowUpMaterializationRequestContext,
        allow_missing_claim_recovery: bool = True,
    ) -> tuple[FollowUpMaterializationRecord, bool]:
        """Classify an unobserved mutation UNKNOWN without spending another call."""

        if operation == "CREATE":
            expected_started = MaterializationRecordState.CREATE_INVOCATION_STARTED
            expected_unknown = MaterializationRecordState.CREATE_UNKNOWN
            diagnostic = CREATE_UNKNOWN_DIAGNOSTIC
            operation_key_sha256 = record.create_idempotency_key_sha256
            persist_result = self.repository.record_create_result
            atomic_persist_result = (
                self.repository.finalize_create_invocation_atomically
            )
        else:
            expected_started = MaterializationRecordState.CANCEL_INVOCATION_STARTED
            expected_unknown = MaterializationRecordState.CANCEL_UNKNOWN
            diagnostic = CANCEL_UNKNOWN_DIAGNOSTIC
            operation_key_sha256 = record.cancel_idempotency_key_sha256
            persist_result = self.repository.record_cancel_result
            atomic_persist_result = (
                self.repository.finalize_cancel_invocation_atomically
            )
        if (
            record.state is not expected_started
            or not _validate_sha256(operation_key_sha256)
        ):
            raise OperatorFollowUpMaterializationError(
                "follow_up_materialization_record_invalid",
                503,
            )

        proof_operation = (
            FollowUpLiveProofOperationKind.CREATE
            if operation == "CREATE"
            else FollowUpLiveProofOperationKind.CANCEL
        )
        existing_proof_terminal = self._read_live_proof_terminal(
            operation_kind=proof_operation,
            source_client_order_id=source_client_order_id,
        )
        existing_proof_claim: LiveProofOperationClaim | None = None
        proof_claim_was_missing = False
        if existing_proof_terminal is None:
            existing_proof_claim = self._read_live_proof_claim(
                operation_kind=proof_operation,
                source_client_order_id=source_client_order_id,
                record=record,
            )
            if existing_proof_claim is None and not allow_missing_claim_recovery:
                raise OperatorFollowUpMaterializationError(
                    "follow_up_live_proof_claim_invalid",
                    503,
                )
            if existing_proof_claim is None:
                # With the current ordering, a missing goal claim proves the
                # process stopped before the exchange adapter was reachable.
                # Bind and terminalize that gap as BLOCKED.  If the claim was
                # already present, the call outcome is genuinely unknown after
                # guard-owner loss and remains consumed.
                self._claim_live_proof_operation(
                    operation_kind=proof_operation,
                    source_client_order_id=source_client_order_id,
                    context=context,
                    record=record,
                )
                proof_claim_was_missing = True

        unknown_result = PersistedInvocationResult(
            outcome=ExchangeInvocationOutcome.UNKNOWN,
            child_state=ChildExchangeState.UNKNOWN,
            diagnostic_code=diagnostic,
            operation_idempotency_key_sha256=operation_key_sha256,
            correlation_id=record.correlation_id,
        )
        lost_owner_accounting = MutationInvocationAccounting(
            sdk_mutation_invocation_state=FollowUpSdkMutationInvocationState.UNKNOWN,
            transport_submission_state=(
                FollowUpTransportSubmissionState.POSSIBLY_SUBMITTED
            ),
            exchange_mutation_state=FollowUpExchangeMutationState.UNKNOWN,
            read_accounting_state=FollowUpReadAccountingState.UNKNOWN,
            observed_read_count=None,
            individual_retry_count=0,
            policy_clean=False,
        )
        try:
            if (
                existing_proof_claim is not None
                and existing_proof_terminal is None
            ):
                # A paired atomic START proves the mutation allowance is
                # consumed.  Classify the lost owner as UNKNOWN while the
                # native result, local quarantine, and goal terminal commit in
                # one transaction.  No recovery read or exchange port is used.
                recovered = atomic_persist_result(
                    source_client_order_id=source_client_order_id,
                    materialization_id=record.materialization_id,
                    result=unknown_result,
                    accounting=lost_owner_accounting,
                    external_call_started=False,
                    reported_read_count=0,
                    individual_retry_count=0,
                )
            else:
                # Explicit compatibility path for a pre-atomic START.  It is
                # terminalized BLOCKED and cannot cross an exchange port.
                recovered = persist_result(
                    materialization_id=record.materialization_id,
                    result=unknown_result,
                )
            recovered = _validate_record(
                recovered,
                source_client_order_id=source_client_order_id,
            )
        except OperatorFollowUpMaterializationError:
            raise
        except Exception:
            raise OperatorFollowUpMaterializationError(
                "follow_up_materialization_result_persistence_unavailable",
                503,
            ) from None
        if (
            recovered.state is not expected_unknown
            or recovered.diagnostic_code != diagnostic
            or recovered.materialization_id != record.materialization_id
            or recovered.attached_intent_id != record.attached_intent_id
            or recovered.root_client_order_id != record.root_client_order_id
            or recovered.child_client_order_id != record.child_client_order_id
            or recovered.create_idempotency_key_sha256
            != record.create_idempotency_key_sha256
            or recovered.cancel_idempotency_key_sha256
            != record.cancel_idempotency_key_sha256
            or recovered.correlation_id != record.correlation_id
            or recovered.audit_id != record.audit_id
        ):
            raise OperatorFollowUpMaterializationError(
                "follow_up_materialization_result_persistence_invalid",
                503,
            )

        atomic_recovery = bool(
            existing_proof_claim is not None
            and existing_proof_terminal is None
        )
        if atomic_recovery:
            return recovered, False

        _project_persisted_child_state(
            runtime=self.runtime,
            record=recovered,
            operation=operation,
            allow_reconciliation_read=False,
        )
        if existing_proof_terminal is not None:
            if existing_proof_terminal.outcome not in {
                FollowUpLiveProofTerminalOutcome.UNKNOWN,
                FollowUpLiveProofTerminalOutcome.BLOCKED,
            }:
                raise OperatorFollowUpMaterializationError(
                    "follow_up_live_proof_terminal_invalid",
                    503,
                )
        else:
            recovery_accounting = (
                MutationInvocationAccounting(
                    sdk_mutation_invocation_state=(
                        FollowUpSdkMutationInvocationState.NOT_INVOKED
                    ),
                    transport_submission_state=(
                        FollowUpTransportSubmissionState.NOT_SUBMITTED
                    ),
                    exchange_mutation_state=(
                        FollowUpExchangeMutationState.NOT_MUTATED
                    ),
                    read_accounting_state=FollowUpReadAccountingState.EXACT,
                    observed_read_count=0,
                    individual_retry_count=0,
                    policy_clean=True,
                )
                if proof_claim_was_missing
                else lost_owner_accounting
            )
            self._record_live_proof_terminal(
                operation_kind=proof_operation,
                source_client_order_id=source_client_order_id,
                outcome=(
                    FollowUpLiveProofTerminalOutcome.BLOCKED
                    if proof_claim_was_missing
                    else FollowUpLiveProofTerminalOutcome.UNKNOWN
                ),
                **_mutation_operation_accounting(recovery_accounting),
                individual_retry_count=0,
                authoritative_child_state=ChildExchangeState.UNKNOWN,
            )
        return recovered, False

    def materialize(
        self,
        *,
        source_client_order_id: str,
        request: MaterializationAuthorization,
        context: OperatorFollowUpMaterializationRequestContext,
    ) -> MaterializationOperationResult:
        """Serialize the complete one-use route across workers/processes."""

        try:
            source_id = _require_source_client_order_id(source_client_order_id)
            guard = self.repository.live_proof_invocation_guard(
                source_client_order_id=source_id,
            )
            with guard:
                return self._materialize_under_guard(
                    source_client_order_id=source_id,
                    request=request,
                    context=context,
                )
        except OperatorFollowUpMaterializationError:
            raise
        except Exception:
            raise OperatorFollowUpMaterializationError(
                "follow_up_materialization_backend_unavailable",
                503,
                failure_stage="pre_exchange_evaluation",
                live_coinbase_read_ran=False,
                live_coinbase_orders_ran=False,
                live_exchange_submitted=False,
            ) from None

    def _materialize_under_guard(
        self,
        *,
        source_client_order_id: str,
        request: MaterializationAuthorization,
        context: OperatorFollowUpMaterializationRequestContext,
    ) -> MaterializationOperationResult:
        try:
            source_id = _require_source_client_order_id(source_client_order_id)
            _require_context(
                context,
                expected_intent=AUTHORIZE_AND_MATERIALIZE_FOLLOW_UP_INTENT,
                permission=AdminApiPermission.ORDER_CREATE,
            )
            _require_materialization_authorization(request)
        except OperatorFollowUpMaterializationError as exc:
            raise exc.with_execution_evidence(
                failure_stage="pre_exchange_evaluation",
                live_coinbase_read_ran=False,
                live_coinbase_orders_ran=False,
                live_exchange_submitted=False,
            ) from exc
        try:
            existing = self.repository.read_materialization(
                source_client_order_id=source_id,
                operation="CREATE",
                idempotency_key=context.idempotency_key,
            )
        except Exception:
            raise OperatorFollowUpMaterializationError(
                "follow_up_materialization_backend_unavailable",
                503,
                failure_stage="pre_exchange_evaluation",
                live_coinbase_read_ran=False,
                live_coinbase_orders_ran=False,
                live_exchange_submitted=False,
            ) from None
        prepared: FollowUpMaterializationRecord | None = None
        if existing is not None:
            prepared = _validate_record(existing, source_client_order_id=source_id)
            if prepared.create_idempotency_key_sha256 != _sha256(
                context.idempotency_key
            ):
                raise OperatorFollowUpMaterializationError(
                    "follow_up_materialization_idempotency_conflict",
                    409,
                    failure_stage="pre_exchange_evaluation",
                    live_coinbase_read_ran=False,
                    live_coinbase_orders_ran=False,
                    live_exchange_submitted=False,
                )
            if prepared.audit_id != context.audit_id:
                raise OperatorFollowUpMaterializationError(
                    "follow_up_materialization_audit_binding_conflict",
                    409,
                    failure_stage="pre_exchange_evaluation",
                    live_coinbase_read_ran=False,
                    live_coinbase_orders_ran=False,
                    live_exchange_submitted=False,
                )
            if (
                prepared.state
                is MaterializationRecordState.CREATE_INVOCATION_STARTED
            ):
                recovered, live_read_ran = self._recover_invocation_started(
                    record=prepared,
                    source_client_order_id=source_id,
                    operation="CREATE",
                    context=context,
                )
                return MaterializationOperationResult(
                    record=recovered,
                    diagnostic_code=recovered.diagnostic_code,
                    replayed=True,
                    live_read_ran=live_read_ran,
                    create_call_ran=False,
                    cancel_call_ran=False,
                    candidate=recovered.durable_candidate,
                )
            if prepared.state != MaterializationRecordState.PREPARED:
                projection = _project_persisted_child_state(
                    runtime=self.runtime,
                    record=prepared,
                    operation="REPLAY_REPAIR",
                    allow_reconciliation_read=False,
                )
                self._finalize_replayed_mutation(
                    record=prepared,
                    source_client_order_id=source_id,
                    operation="CREATE",
                )
                return MaterializationOperationResult(
                    record=prepared,
                    diagnostic_code=prepared.diagnostic_code,
                    replayed=True,
                    live_read_ran=bool(
                        projection is not None and projection.live_read_count
                    ),
                    create_call_ran=False,
                    cancel_call_ran=False,
                    candidate=prepared.durable_candidate,
                )
        try:
            eligibility_claim = self._claim_live_proof_operation(
                operation_kind=FollowUpLiveProofOperationKind.ELIGIBILITY_READ,
                source_client_order_id=source_id,
                context=context,
            )
        except OperatorFollowUpMaterializationError as exc:
            raise exc.with_execution_evidence(
                failure_stage="eligibility_claim_before_read",
                live_coinbase_read_ran=False,
                live_coinbase_orders_ran=False,
                live_exchange_submitted=False,
            ) from exc
        try:
            evidence = self.runtime.resolve_fresh_materialization_eligibility(
                source_client_order_id=source_id
            )
        except Exception:
            self._record_live_proof_terminal(
                operation_kind=FollowUpLiveProofOperationKind.ELIGIBILITY_READ,
                source_client_order_id=source_id,
                outcome=FollowUpLiveProofTerminalOutcome.UNKNOWN,
                **_read_operation_accounting(None),
                individual_retry_count=0,
            )
            raise OperatorFollowUpMaterializationError(
                "follow_up_materialization_eligibility_unavailable",
                503,
                failure_stage="eligibility_read_outcome_unknown",
                live_coinbase_read_ran=True,
                live_coinbase_orders_ran=False,
                live_exchange_submitted=False,
            ) from None
        try:
            candidate = _validate_candidate(
                evidence,
                source_client_order_id=source_id,
                expected_environment=context.environment,
            )
        except OperatorFollowUpMaterializationError as exc:
            retry_count = getattr(evidence, "individual_retry_count", 0)
            if type(retry_count) is not int or not 0 <= retry_count <= 10:
                retry_count = 1
            blocked_read_count = (
                _exact_read_count(getattr(evidence, "coinbase_read_count", None))
                if evidence.coinbase_read_started is True
                else 0
            )
            self._record_live_proof_terminal(
                operation_kind=FollowUpLiveProofOperationKind.ELIGIBILITY_READ,
                source_client_order_id=source_id,
                outcome=FollowUpLiveProofTerminalOutcome.BLOCKED,
                **_read_operation_accounting(blocked_read_count),
                individual_retry_count=retry_count,
            )
            raise exc.with_execution_evidence(
                failure_stage=(
                    "eligibility_after_live_read"
                    if evidence.coinbase_read_started is True
                    else "pre_exchange_evaluation"
                ),
                live_coinbase_read_ran=evidence.coinbase_read_started is True,
                live_coinbase_orders_ran=False,
                live_exchange_submitted=False,
            ) from exc
        if (
            eligibility_claim.root_client_order_id != candidate.root_client_order_id
            or eligibility_claim.attached_intent_id != candidate.attached_intent_id
        ):
            self._record_live_proof_terminal(
                operation_kind=FollowUpLiveProofOperationKind.ELIGIBILITY_READ,
                source_client_order_id=source_id,
                outcome=FollowUpLiveProofTerminalOutcome.BLOCKED,
                **_read_operation_accounting(evidence.coinbase_read_count),
                individual_retry_count=evidence.individual_retry_count,
            )
            raise OperatorFollowUpMaterializationError(
                "follow_up_live_proof_candidate_binding_mismatch",
                409,
                failure_stage="eligibility_after_live_read",
                live_coinbase_read_ran=evidence.coinbase_read_started is True,
                live_coinbase_orders_ran=False,
                live_exchange_submitted=False,
            )
        command = MaterializationPrepareCommand(
            candidate=candidate,
            actor_id=context.actor_id,
            roles=tuple(_role_value(role) for role in context.roles),
            idempotency_key=context.idempotency_key,
            idempotency_key_sha256=_sha256(context.idempotency_key),
            correlation_id=context.correlation_id,
            operator_intent=context.operator_intent,
            audit_id=context.audit_id,
            request_sha256=_request_sha256(
                source_client_order_id=source_id,
                request=request,
                context=context,
                candidate=candidate,
            ),
        )
        prior_prepared = prepared
        try:
            prepared = self.repository.prepare_materialization(command)
            prepared = _validate_record(
                prepared,
                source_client_order_id=source_id,
            )
        except OperatorFollowUpMaterializationError as exc:
            raise exc.with_execution_evidence(
                failure_stage="eligibility_after_live_read",
                live_coinbase_read_ran=evidence.coinbase_read_started is True,
                live_coinbase_orders_ran=False,
                live_exchange_submitted=False,
            ) from exc
        except Exception:
            raise OperatorFollowUpMaterializationError(
                "follow_up_materialization_backend_unavailable",
                503,
                failure_stage="eligibility_after_live_read",
                live_coinbase_read_ran=evidence.coinbase_read_started is True,
                live_coinbase_orders_ran=False,
                live_exchange_submitted=False,
            ) from None
        if (
            prior_prepared is not None
            and prepared.materialization_id != prior_prepared.materialization_id
        ):
            raise OperatorFollowUpMaterializationError(
                "follow_up_materialization_record_identity_mismatch",
                503,
                failure_stage="eligibility_after_live_read",
                live_coinbase_read_ran=evidence.coinbase_read_started is True,
                live_coinbase_orders_ran=False,
                live_exchange_submitted=False,
            )
        if prepared.audit_id != context.audit_id:
            raise OperatorFollowUpMaterializationError(
                "follow_up_materialization_audit_binding_conflict",
                409,
                failure_stage="eligibility_after_live_read",
                live_coinbase_read_ran=evidence.coinbase_read_started is True,
                live_coinbase_orders_ran=False,
                live_exchange_submitted=False,
            )
        if prepared.state != MaterializationRecordState.PREPARED:
            _project_persisted_child_state(
                runtime=self.runtime,
                record=prepared,
                operation="REPLAY_REPAIR",
                allow_reconciliation_read=False,
            )
            return MaterializationOperationResult(
                record=prepared,
                diagnostic_code=prepared.diagnostic_code,
                replayed=True,
                live_read_ran=evidence.coinbase_read_started,
                create_call_ran=False,
                cancel_call_ran=False,
                eligibility=evidence,
                candidate=candidate,
            )
        _require_prepared_record_matches_candidate(prepared, candidate)
        try:
            local_child = self.runtime.persist_preclaimed_child(
                candidate=candidate,
                materialization_id=prepared.materialization_id,
            )
        except Exception:
            raise OperatorFollowUpMaterializationError(
                "follow_up_materialization_child_persistence_unavailable",
                503,
                failure_stage="eligibility_after_live_read",
                live_coinbase_read_ran=evidence.coinbase_read_started is True,
                live_coinbase_orders_ran=False,
                live_exchange_submitted=False,
            ) from None
        if (
            local_child.persisted is not True
            or local_child.exact_replay_safe is not True
            or local_child.exchange_call_ran is not False
            or local_child.materialization_id != prepared.materialization_id
            or local_child.child_client_order_id != candidate.child_client_order_id
        ):
            raise OperatorFollowUpMaterializationError(
                "follow_up_materialization_child_persistence_invalid",
                503,
                failure_stage="eligibility_after_live_read",
                live_coinbase_read_ran=evidence.coinbase_read_started is True,
                live_coinbase_orders_ran=False,
                live_exchange_submitted=False,
            )
        # Eligibility is clean only after the durable attempt and exact local
        # child quarantine both exist.  A crash or local persistence failure
        # before this point leaves the read claim consumed but never records a
        # false successful prerequisite.
        self._record_live_proof_terminal(
            operation_kind=FollowUpLiveProofOperationKind.ELIGIBILITY_READ,
            source_client_order_id=source_id,
            outcome=FollowUpLiveProofTerminalOutcome.SUCCEEDED,
            **_read_operation_accounting(evidence.coinbase_read_count),
            individual_retry_count=evidence.individual_retry_count,
        )
        try:
            boundary = self.repository.claim_create_invocation_started_atomically(
                source_client_order_id=source_id,
                materialization_id=prepared.materialization_id,
                correlation_id=context.correlation_id,
                audit_id=context.audit_id,
                operation_idempotency_key_sha256=(
                    prepared.create_idempotency_key_sha256
                ),
            )
            boundary_record = _validate_record(
                boundary.record,
                source_client_order_id=source_id,
            )
        except OperatorFollowUpMaterializationError as exc:
            raise exc.with_execution_evidence(
                failure_stage="create_claim_before_invocation",
                live_coinbase_read_ran=evidence.coinbase_read_started is True,
                live_coinbase_orders_ran=False,
                live_exchange_submitted=False,
            ) from exc
        except Exception:
            raise OperatorFollowUpMaterializationError(
                "follow_up_materialization_backend_unavailable",
                503,
                failure_stage="create_claim_before_invocation",
                live_coinbase_read_ran=evidence.coinbase_read_started is True,
                live_coinbase_orders_ran=False,
                live_exchange_submitted=False,
            ) from None
        if boundary_record.create_idempotency_key_sha256 != _sha256(
            context.idempotency_key
        ):
            raise OperatorFollowUpMaterializationError(
                "follow_up_materialization_record_identity_mismatch",
                503,
                failure_stage="create_claim_before_invocation",
                live_coinbase_read_ran=evidence.coinbase_read_started is True,
                live_coinbase_orders_ran=False,
                live_exchange_submitted=False,
            )
        if not boundary.claimed:
            _project_persisted_child_state(
                runtime=self.runtime,
                record=boundary_record,
                operation="REPLAY_REPAIR",
                allow_reconciliation_read=False,
            )
            return MaterializationOperationResult(
                record=boundary_record,
                diagnostic_code=boundary_record.diagnostic_code,
                replayed=True,
                live_read_ran=evidence.coinbase_read_started,
                create_call_ran=False,
                cancel_call_ran=False,
                eligibility=evidence,
                candidate=candidate,
            )
        if boundary_record.state != MaterializationRecordState.CREATE_INVOCATION_STARTED:
            raise OperatorFollowUpMaterializationError(
                "follow_up_materialization_create_boundary_invalid",
                503,
                failure_stage="create_claim_before_invocation",
                live_coinbase_read_ran=evidence.coinbase_read_started is True,
                live_coinbase_orders_ran=False,
                live_exchange_submitted=False,
            )
        try:
            exchange_result: object = self.exchange.create_follow_up_child(
                candidate=candidate,
                correlation_id=context.correlation_id,
                materialization_id=boundary_record.materialization_id,
                operation_audit_id=boundary_record.audit_id,
                operation_idempotency_key_sha256=(
                    boundary_record.create_idempotency_key_sha256
                ),
            )
        except Exception:
            exchange_result = ExchangeInvocationResult(
                outcome=ExchangeInvocationOutcome.UNKNOWN,
                child_state=ChildExchangeState.UNKNOWN,
                exchange_call_started=False,
                sdk_mutation_invocation_state=(
                    FollowUpSdkMutationInvocationState.UNKNOWN
                ),
                transport_submission_state=(
                    FollowUpTransportSubmissionState.POSSIBLY_SUBMITTED
                ),
                exchange_mutation_state=FollowUpExchangeMutationState.UNKNOWN,
                read_accounting_state=FollowUpReadAccountingState.UNKNOWN,
                observed_read_count=None,
                individual_retry_count=0,
            )
        create_call_started = (
            getattr(exchange_result, "exchange_call_started", False) is True
        )
        accounting = _normalized_invocation_accounting(
            exchange_result,
            exchange_call_started=create_call_started,
        )
        persisted_result = _fixed_invocation_result(
            exchange_result,
            operation="CREATE",
            idempotency_key=context.idempotency_key,
            correlation_id=context.correlation_id,
            force_unknown=not accounting.policy_clean,
        )
        try:
            record = self.repository.finalize_create_invocation_atomically(
                source_client_order_id=source_id,
                materialization_id=boundary_record.materialization_id,
                result=persisted_result,
                accounting=accounting,
                external_call_started=accounting.sdk_invoked,
                reported_read_count=accounting.observed_read_count or 0,
                individual_retry_count=accounting.individual_retry_count,
            )
            record = _validate_record(record, source_client_order_id=source_id)
        except OperatorFollowUpMaterializationError as exc:
            raise exc.with_execution_evidence(
                failure_stage="create_result_persistence",
                live_coinbase_read_ran=evidence.coinbase_read_started is True,
                live_coinbase_orders_ran=accounting.sdk_invoked,
                live_exchange_submitted=accounting.sdk_invoked,
            ) from exc
        except Exception:
            raise OperatorFollowUpMaterializationError(
                "follow_up_materialization_result_persistence_unavailable",
                503,
                failure_stage="create_result_persistence",
                live_coinbase_read_ran=evidence.coinbase_read_started is True,
                live_coinbase_orders_ran=accounting.sdk_invoked,
                live_exchange_submitted=accounting.sdk_invoked,
            ) from None
        expected_create_state = {
            ExchangeInvocationOutcome.ACCEPTED: MaterializationRecordState.CREATE_ACCEPTED,
            ExchangeInvocationOutcome.REJECTED: MaterializationRecordState.CREATE_REJECTED,
            ExchangeInvocationOutcome.UNKNOWN: MaterializationRecordState.CREATE_UNKNOWN,
        }[persisted_result.outcome]
        if (
            record.state != expected_create_state
            or record.diagnostic_code != persisted_result.diagnostic_code
        ):
            raise OperatorFollowUpMaterializationError(
                "follow_up_materialization_create_result_invalid",
                503,
                failure_stage="create_result_projection",
                live_coinbase_read_ran=evidence.coinbase_read_started is True,
                live_coinbase_orders_ran=accounting.sdk_invoked,
                live_exchange_submitted=accounting.sdk_invoked,
            )
        return MaterializationOperationResult(
            record=record,
            diagnostic_code=persisted_result.diagnostic_code,
            replayed=False,
            live_read_ran=evidence.coinbase_read_started,
            create_call_ran=accounting.sdk_invoked,
            cancel_call_ran=False,
            eligibility=evidence,
            candidate=candidate,
        )

    def safe_closeout(
        self,
        *,
        source_client_order_id: str,
        request: SafeCloseoutAuthorization,
        context: OperatorFollowUpMaterializationRequestContext,
    ) -> MaterializationOperationResult:
        """Serialize reconciliation and optional exact-child Cancel."""

        try:
            source_id = _require_source_client_order_id(source_client_order_id)
            guard = self.repository.live_proof_invocation_guard(
                source_client_order_id=source_id,
            )
            with guard:
                return self._safe_closeout_under_guard(
                    source_client_order_id=source_id,
                    request=request,
                    context=context,
                )
        except OperatorFollowUpMaterializationError:
            raise
        except Exception:
            raise OperatorFollowUpMaterializationError(
                "follow_up_materialization_backend_unavailable",
                503,
                failure_stage="pre_exchange_evaluation",
                live_coinbase_read_ran=False,
                live_coinbase_orders_ran=False,
                live_exchange_submitted=False,
            ) from None

    def _safe_closeout_under_guard(
        self,
        *,
        source_client_order_id: str,
        request: SafeCloseoutAuthorization,
        context: OperatorFollowUpMaterializationRequestContext,
    ) -> MaterializationOperationResult:
        try:
            source_id = _require_source_client_order_id(source_client_order_id)
            _require_context(
                context,
                expected_intent=SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT,
                permission=AdminApiPermission.ORDER_CANCEL,
            )
            _require_closeout_authorization(request)
        except OperatorFollowUpMaterializationError as exc:
            raise exc.with_execution_evidence(
                failure_stage="pre_exchange_evaluation",
                live_coinbase_read_ran=False,
                live_coinbase_orders_ran=False,
                live_exchange_submitted=False,
            ) from exc
        try:
            existing = self.repository.read_materialization(
                source_client_order_id=source_id,
                operation="CANCEL",
                idempotency_key=context.idempotency_key,
            )
        except Exception:
            raise OperatorFollowUpMaterializationError(
                "follow_up_materialization_backend_unavailable",
                503,
                failure_stage="pre_exchange_evaluation",
                live_coinbase_read_ran=False,
                live_coinbase_orders_ran=False,
                live_exchange_submitted=False,
            ) from None
        if existing is None:
            raise OperatorFollowUpMaterializationError(
                "follow_up_materialization_not_found",
                404,
                failure_stage="pre_exchange_evaluation",
                live_coinbase_read_ran=False,
                live_coinbase_orders_ran=False,
                live_exchange_submitted=False,
            )
        record = _validate_record(existing, source_client_order_id=source_id)
        cancel_key_sha256 = _sha256(context.idempotency_key)
        if record.cancel_idempotency_key_sha256 is not None:
            if record.cancel_idempotency_key_sha256 != cancel_key_sha256:
                raise OperatorFollowUpMaterializationError(
                    "follow_up_materialization_cancel_idempotency_conflict",
                    409,
                    failure_stage="pre_exchange_evaluation",
                    live_coinbase_read_ran=False,
                    live_coinbase_orders_ran=False,
                    live_exchange_submitted=False,
                )
            if record.audit_id != context.audit_id:
                raise OperatorFollowUpMaterializationError(
                    "follow_up_materialization_audit_binding_conflict",
                    409,
                    failure_stage="pre_exchange_evaluation",
                    live_coinbase_read_ran=False,
                    live_coinbase_orders_ran=False,
                    live_exchange_submitted=False,
                )
            if (
                record.state
                is MaterializationRecordState.CANCEL_INVOCATION_STARTED
            ):
                recovered, live_read_ran = self._recover_invocation_started(
                    record=record,
                    source_client_order_id=source_id,
                    operation="CANCEL",
                    context=context,
                )
                return MaterializationOperationResult(
                    record=recovered,
                    diagnostic_code=recovered.diagnostic_code,
                    replayed=True,
                    live_read_ran=live_read_ran,
                    create_call_ran=False,
                    cancel_call_ran=False,
                    candidate=recovered.durable_candidate,
                )
            projection = _project_persisted_child_state(
                runtime=self.runtime,
                record=record,
                operation="REPLAY_REPAIR",
                allow_reconciliation_read=False,
            )
            self._finalize_replayed_mutation(
                record=record,
                source_client_order_id=source_id,
                operation="CANCEL",
            )
            return MaterializationOperationResult(
                record=record,
                diagnostic_code=record.diagnostic_code,
                replayed=True,
                live_read_ran=bool(
                    projection is not None and projection.live_read_count
                ),
                create_call_ran=False,
                cancel_call_ran=False,
                candidate=record.durable_candidate,
            )
        if record.state not in {
            MaterializationRecordState.CREATE_INVOCATION_STARTED,
            MaterializationRecordState.CREATE_ACCEPTED,
            MaterializationRecordState.CREATE_UNKNOWN,
        }:
            raise OperatorFollowUpMaterializationError(
                "follow_up_materialization_child_not_cancelable",
                409,
                failure_stage="pre_exchange_evaluation",
                live_coinbase_read_ran=False,
                live_coinbase_orders_ran=False,
                live_exchange_submitted=False,
            )
        if record.state is MaterializationRecordState.CREATE_INVOCATION_STARTED:
            record, _ = self._recover_invocation_started(
                record=record,
                source_client_order_id=source_id,
                operation="CREATE",
                context=context,
                allow_missing_claim_recovery=False,
            )
        existing_reconciliation_terminal = self._read_live_proof_terminal(
            operation_kind=FollowUpLiveProofOperationKind.RECONCILIATION_READ,
            source_client_order_id=source_id,
        )
        reconciliation_replayed = existing_reconciliation_terminal is not None
        if reconciliation_replayed:
            reconciliation_claim = self._read_live_proof_claim(
                operation_kind=(
                    FollowUpLiveProofOperationKind.RECONCILIATION_READ
                ),
                source_client_order_id=source_id,
                record=record,
            )
            if (
                reconciliation_claim is None
                or existing_reconciliation_terminal is None
                or reconciliation_claim.audit_id != context.audit_id
                or reconciliation_claim.operation_idempotency_key_sha256
                != cancel_key_sha256
                or existing_reconciliation_terminal.audit_id
                != reconciliation_claim.audit_id
                or existing_reconciliation_terminal.operation_idempotency_key_sha256
                != reconciliation_claim.operation_idempotency_key_sha256
                or existing_reconciliation_terminal.outcome
                is not FollowUpLiveProofTerminalOutcome.SUCCEEDED
                or existing_reconciliation_terminal.sdk_mutation_invocation_state
                is not FollowUpSdkMutationInvocationState.NOT_INVOKED
                or existing_reconciliation_terminal.transport_submission_state
                is not FollowUpTransportSubmissionState.NOT_SUBMITTED
                or existing_reconciliation_terminal.exchange_mutation_state
                is not FollowUpExchangeMutationState.NOT_MUTATED
                or existing_reconciliation_terminal.read_accounting_state
                is not FollowUpReadAccountingState.EXACT
                or type(existing_reconciliation_terminal.observed_read_count)
                is not int
                or not 1
                <= existing_reconciliation_terminal.observed_read_count
                <= 10
                or existing_reconciliation_terminal.individual_retry_count != 0
                or existing_reconciliation_terminal.authoritative_child_state
                is not ChildExchangeState.ACTIVE
            ):
                raise OperatorFollowUpMaterializationError(
                    "follow_up_materialization_reconciliation_replay_invalid",
                    409,
                    failure_stage="pre_exchange_evaluation",
                    live_coinbase_read_ran=False,
                    live_coinbase_orders_ran=False,
                    live_exchange_submitted=False,
                )
            try:
                local_active = self.runtime.validate_persisted_active_child_identity(
                    record=record
                )
            except Exception:
                raise OperatorFollowUpMaterializationError(
                    "follow_up_materialization_projection_unavailable",
                    503,
                    failure_stage="pre_exchange_evaluation",
                    live_coinbase_read_ran=False,
                    live_coinbase_orders_ran=False,
                    live_exchange_submitted=False,
                ) from None
            if (
                local_active.projected is not True
                or local_active.exact_replay_safe is not True
                or local_active.exchange_call_ran is not False
                or local_active.live_read_count != 0
            ):
                raise OperatorFollowUpMaterializationError(
                    "follow_up_materialization_projection_invalid",
                    503,
                )
            child_evidence = ChildStateEvidence(
                child_client_order_id=record.child_client_order_id,
                state=ChildExchangeState.ACTIVE,
                fresh=True,
                authoritative=True,
                read_count=0,
                individual_retry_count=0,
                ambiguous=False,
                coinbase_read_started=False,
            )
        else:
            try:
                reconciliation_claim = self._claim_live_proof_operation(
                    operation_kind=(
                        FollowUpLiveProofOperationKind.RECONCILIATION_READ
                    ),
                    source_client_order_id=source_id,
                    context=context,
                    record=record,
                )
            except OperatorFollowUpMaterializationError as exc:
                raise exc.with_execution_evidence(
                    failure_stage="reconciliation_claim_before_read",
                    live_coinbase_read_ran=False,
                    live_coinbase_orders_ran=False,
                    live_exchange_submitted=False,
                ) from exc
            try:
                child_evidence = self.runtime.read_authoritative_child_state(
                    child_client_order_id=record.child_client_order_id,
                    materialization_id=record.materialization_id,
                    operation_audit_id=reconciliation_claim.audit_id,
                    operation_idempotency_key_sha256=(
                        reconciliation_claim.operation_idempotency_key_sha256
                    ),
                )
            except Exception:
                self._record_live_proof_terminal(
                    operation_kind=(
                        FollowUpLiveProofOperationKind.RECONCILIATION_READ
                    ),
                    source_client_order_id=source_id,
                    outcome=FollowUpLiveProofTerminalOutcome.UNKNOWN,
                    **_read_operation_accounting(None),
                    individual_retry_count=0,
                    authoritative_child_state=ChildExchangeState.UNKNOWN,
                )
                raise OperatorFollowUpMaterializationError(
                    "follow_up_materialization_child_state_unavailable",
                    503,
                    failure_stage="child_read_outcome_unknown",
                    live_coinbase_read_ran=True,
                    live_coinbase_orders_ran=False,
                    live_exchange_submitted=False,
                ) from None
            try:
                if child_evidence.individual_retry_count != 0:
                    raise OperatorFollowUpMaterializationError(
                        "follow_up_materialization_child_state_retry_detected",
                        409,
                    )
                if child_evidence.coinbase_read_started is not True:
                    raise OperatorFollowUpMaterializationError(
                        "follow_up_materialization_child_live_read_required",
                        409,
                    )
                if (
                    type(child_evidence.read_count) is not int
                    or not 1 <= child_evidence.read_count <= 10
                    or child_evidence.fresh is not True
                ):
                    raise OperatorFollowUpMaterializationError(
                        "follow_up_materialization_child_state_not_fresh",
                        409,
                    )
                if (
                    child_evidence.ambiguous is True
                    or child_evidence.authoritative is not True
                    or child_evidence.child_client_order_id
                    != record.child_client_order_id
                    or child_evidence.state is ChildExchangeState.UNKNOWN
                    or not _validate_sha256(
                        child_evidence.exchange_order_id_sha256
                    )
                ):
                    raise OperatorFollowUpMaterializationError(
                        "follow_up_materialization_child_state_ambiguous",
                        409,
                    )
            except OperatorFollowUpMaterializationError as exc:
                retry_count = getattr(child_evidence, "individual_retry_count", 0)
                if type(retry_count) is not int or not 0 <= retry_count <= 10:
                    retry_count = 1
                read_count = (
                    _exact_read_count(getattr(child_evidence, "read_count", None))
                    if child_evidence.coinbase_read_started is True
                    else 0
                )
                self._record_live_proof_terminal(
                    operation_kind=(
                        FollowUpLiveProofOperationKind.RECONCILIATION_READ
                    ),
                    source_client_order_id=source_id,
                    outcome=FollowUpLiveProofTerminalOutcome.BLOCKED,
                    **_read_operation_accounting(read_count),
                    individual_retry_count=retry_count,
                    authoritative_child_state=ChildExchangeState.UNKNOWN,
                )
                raise exc.with_execution_evidence(
                    failure_stage=(
                        "safe_closeout_after_live_read"
                        if child_evidence.coinbase_read_started is True
                        else "pre_exchange_evaluation"
                    ),
                    live_coinbase_read_ran=(
                        child_evidence.coinbase_read_started is True
                    ),
                    live_coinbase_orders_ran=False,
                    live_exchange_submitted=False,
                ) from exc
        if child_evidence.state == ChildExchangeState.TERMINAL:
            terminal_result = PersistedInvocationResult(
                outcome=ExchangeInvocationOutcome.NOT_REQUIRED_TERMINAL,
                child_state=ChildExchangeState.TERMINAL,
                diagnostic_code=CHILD_ALREADY_TERMINAL_DIAGNOSTIC,
                operation_idempotency_key_sha256=cancel_key_sha256,
                correlation_id=context.correlation_id,
                exchange_order_id_sha256=(
                    _clean_text(child_evidence.exchange_order_id_sha256).lower()
                    if _validate_sha256(
                        _clean_text(child_evidence.exchange_order_id_sha256)
                    )
                    else None
                ),
            )
            try:
                terminal_record = (
                    self.repository.finalize_terminal_without_cancel_atomically(
                    source_client_order_id=source_id,
                    record=record,
                    claim=reconciliation_claim,
                    evidence=child_evidence,
                    result=terminal_result,
                    idempotency_key=context.idempotency_key,
                    actor_id=context.actor_id,
                    roles=tuple(_role_value(role) for role in context.roles),
                    environment=context.environment,
                    operator_intent=context.operator_intent,
                    correlation_id=context.correlation_id,
                    audit_id=context.audit_id,
                    )
                )
                terminal_record = _validate_record(
                    terminal_record,
                    source_client_order_id=source_id,
                )
            except OperatorFollowUpMaterializationError as exc:
                raise exc.with_execution_evidence(
                    failure_stage="safe_closeout_after_live_read",
                    live_coinbase_read_ran=(
                        child_evidence.coinbase_read_started is True
                    ),
                    live_coinbase_orders_ran=False,
                    live_exchange_submitted=False,
                ) from exc
            except Exception:
                raise OperatorFollowUpMaterializationError(
                    "follow_up_materialization_result_persistence_unavailable",
                    503,
                    failure_stage="safe_closeout_after_live_read",
                    live_coinbase_read_ran=(
                        child_evidence.coinbase_read_started is True
                    ),
                    live_coinbase_orders_ran=False,
                    live_exchange_submitted=False,
                ) from None
            if (
                terminal_record.state
                != MaterializationRecordState.CHILD_ALREADY_TERMINAL
                or terminal_record.diagnostic_code
                != CHILD_ALREADY_TERMINAL_DIAGNOSTIC
                or terminal_record.cancel_call_consumed is not False
            ):
                raise OperatorFollowUpMaterializationError(
                    "follow_up_materialization_terminal_read_result_invalid",
                    503,
                    failure_stage="safe_closeout_after_live_read",
                    live_coinbase_read_ran=(
                        child_evidence.coinbase_read_started is True
                    ),
                    live_coinbase_orders_ran=False,
                    live_exchange_submitted=False,
                )
            if terminal_record.audit_id != context.audit_id:
                raise OperatorFollowUpMaterializationError(
                    "follow_up_materialization_audit_binding_conflict",
                    409,
                    failure_stage="safe_closeout_after_live_read",
                    live_coinbase_read_ran=(
                        child_evidence.coinbase_read_started is True
                    ),
                    live_coinbase_orders_ran=False,
                    live_exchange_submitted=False,
                )
            return MaterializationOperationResult(
                record=terminal_record,
                diagnostic_code=CHILD_ALREADY_TERMINAL_DIAGNOSTIC,
                replayed=False,
                live_read_ran=child_evidence.coinbase_read_started,
                create_call_ran=False,
                cancel_call_ran=False,
                candidate=terminal_record.durable_candidate,
            )
        if not reconciliation_replayed:
            try:
                if record.state is MaterializationRecordState.CREATE_UNKNOWN:
                    record = (
                        self.repository.finalize_active_reconciliation_atomically(
                            source_client_order_id=source_id,
                            record=record,
                            claim=reconciliation_claim,
                            evidence=child_evidence,
                        )
                    )
                    record = _validate_record(
                        record,
                        source_client_order_id=source_id,
                    )
                else:
                    local_active = (
                        self.runtime.validate_persisted_active_child_identity(
                            record=record
                        )
                    )
                    if (
                        local_active.projected is not True
                        or local_active.exact_replay_safe is not True
                        or local_active.exchange_call_ran is not False
                        or local_active.live_read_count != 0
                    ):
                        raise RuntimeError(
                            "follow_up_materialization_projection_invalid"
                        )
                    self._record_live_proof_terminal(
                        operation_kind=(
                            FollowUpLiveProofOperationKind.RECONCILIATION_READ
                        ),
                        source_client_order_id=source_id,
                        outcome=FollowUpLiveProofTerminalOutcome.SUCCEEDED,
                        **_read_operation_accounting(child_evidence.read_count),
                        individual_retry_count=0,
                        authoritative_child_state=ChildExchangeState.ACTIVE,
                    )
            except OperatorFollowUpMaterializationError:
                raise
            except Exception:
                raise OperatorFollowUpMaterializationError(
                    "follow_up_materialization_projection_unavailable",
                    503,
                    failure_stage="safe_closeout_after_live_read",
                    live_coinbase_read_ran=(
                        child_evidence.coinbase_read_started is True
                    ),
                    live_coinbase_orders_ran=False,
                    live_exchange_submitted=False,
                ) from None
        try:
            boundary = self.repository.claim_cancel_invocation_started_atomically(
                source_client_order_id=source_id,
                materialization_id=record.materialization_id,
                idempotency_key=context.idempotency_key,
                actor_id=context.actor_id,
                roles=tuple(_role_value(role) for role in context.roles),
                environment=context.environment,
                operator_intent=context.operator_intent,
                correlation_id=context.correlation_id,
                audit_id=context.audit_id,
            )
            boundary_record = _validate_record(
                boundary.record,
                source_client_order_id=source_id,
            )
        except OperatorFollowUpMaterializationError as exc:
            raise exc.with_execution_evidence(
                failure_stage="cancel_claim_before_invocation",
                live_coinbase_read_ran=(
                    child_evidence.coinbase_read_started is True
                ),
                live_coinbase_orders_ran=False,
                live_exchange_submitted=False,
            ) from exc
        except Exception:
            raise OperatorFollowUpMaterializationError(
                "follow_up_materialization_backend_unavailable",
                503,
                failure_stage="cancel_claim_before_invocation",
                live_coinbase_read_ran=(
                    child_evidence.coinbase_read_started is True
                ),
                live_coinbase_orders_ran=False,
                live_exchange_submitted=False,
            ) from None
        if boundary_record.cancel_idempotency_key_sha256 != cancel_key_sha256:
            raise OperatorFollowUpMaterializationError(
                "follow_up_materialization_record_identity_mismatch",
                503,
                failure_stage="cancel_claim_before_invocation",
                live_coinbase_read_ran=(
                    child_evidence.coinbase_read_started is True
                ),
                live_coinbase_orders_ran=False,
                live_exchange_submitted=False,
            )
        if boundary_record.audit_id != context.audit_id:
            raise OperatorFollowUpMaterializationError(
                "follow_up_materialization_audit_binding_conflict",
                409,
                failure_stage="cancel_claim_before_invocation",
                live_coinbase_read_ran=(
                    child_evidence.coinbase_read_started is True
                ),
                live_coinbase_orders_ran=False,
                live_exchange_submitted=False,
            )
        if not boundary.claimed:
            _project_persisted_child_state(
                runtime=self.runtime,
                record=boundary_record,
                operation="REPLAY_REPAIR",
                allow_reconciliation_read=False,
            )
            return MaterializationOperationResult(
                record=boundary_record,
                diagnostic_code=boundary_record.diagnostic_code,
                replayed=True,
                live_read_ran=child_evidence.coinbase_read_started,
                create_call_ran=False,
                cancel_call_ran=False,
                candidate=boundary_record.durable_candidate,
            )
        if boundary_record.state != MaterializationRecordState.CANCEL_INVOCATION_STARTED:
            raise OperatorFollowUpMaterializationError(
                "follow_up_materialization_cancel_boundary_invalid",
                503,
                failure_stage="cancel_claim_before_invocation",
                live_coinbase_read_ran=(
                    child_evidence.coinbase_read_started is True
                ),
                live_coinbase_orders_ran=False,
                live_exchange_submitted=False,
            )
        try:
            exchange_result: object = self.exchange.cancel_follow_up_child(
                child_client_order_id=record.child_client_order_id,
                correlation_id=context.correlation_id,
                materialization_id=boundary_record.materialization_id,
                operation_audit_id=boundary_record.audit_id,
                operation_idempotency_key_sha256=(
                    boundary_record.cancel_idempotency_key_sha256 or ""
                ),
            )
        except Exception:
            exchange_result = ExchangeInvocationResult(
                outcome=ExchangeInvocationOutcome.UNKNOWN,
                child_state=ChildExchangeState.UNKNOWN,
                exchange_call_started=False,
                sdk_mutation_invocation_state=(
                    FollowUpSdkMutationInvocationState.UNKNOWN
                ),
                transport_submission_state=(
                    FollowUpTransportSubmissionState.POSSIBLY_SUBMITTED
                ),
                exchange_mutation_state=FollowUpExchangeMutationState.UNKNOWN,
                read_accounting_state=FollowUpReadAccountingState.UNKNOWN,
                observed_read_count=None,
                individual_retry_count=0,
            )
        cancel_call_started = (
            getattr(exchange_result, "exchange_call_started", False) is True
        )
        accounting = _normalized_invocation_accounting(
            exchange_result,
            exchange_call_started=cancel_call_started,
        )
        persisted_result = _fixed_invocation_result(
            exchange_result,
            operation="CANCEL",
            idempotency_key=context.idempotency_key,
            correlation_id=context.correlation_id,
            force_unknown=not accounting.policy_clean,
        )
        try:
            final_record = self.repository.finalize_cancel_invocation_atomically(
                source_client_order_id=source_id,
                materialization_id=record.materialization_id,
                result=persisted_result,
                accounting=accounting,
                external_call_started=accounting.sdk_invoked,
                reported_read_count=accounting.observed_read_count or 0,
                individual_retry_count=accounting.individual_retry_count,
            )
            final_record = _validate_record(
                final_record,
                source_client_order_id=source_id,
            )
        except OperatorFollowUpMaterializationError as exc:
            raise exc.with_execution_evidence(
                failure_stage="cancel_result_persistence",
                live_coinbase_read_ran=(
                    child_evidence.coinbase_read_started is True
                ),
                live_coinbase_orders_ran=accounting.sdk_invoked,
                live_exchange_submitted=accounting.sdk_invoked,
            ) from exc
        except Exception:
            raise OperatorFollowUpMaterializationError(
                "follow_up_materialization_result_persistence_unavailable",
                503,
                failure_stage="cancel_result_persistence",
                live_coinbase_read_ran=(
                    child_evidence.coinbase_read_started is True
                ),
                live_coinbase_orders_ran=accounting.sdk_invoked,
                live_exchange_submitted=accounting.sdk_invoked,
            ) from None
        expected_cancel_state = {
            ExchangeInvocationOutcome.ACCEPTED: MaterializationRecordState.CANCEL_ACCEPTED,
            ExchangeInvocationOutcome.REJECTED: MaterializationRecordState.CANCEL_REJECTED,
            ExchangeInvocationOutcome.UNKNOWN: MaterializationRecordState.CANCEL_UNKNOWN,
        }[persisted_result.outcome]
        if (
            final_record.state != expected_cancel_state
            or final_record.diagnostic_code != persisted_result.diagnostic_code
        ):
            raise OperatorFollowUpMaterializationError(
                "follow_up_materialization_cancel_result_invalid",
                503,
                failure_stage="cancel_result_projection",
                live_coinbase_read_ran=(
                    child_evidence.coinbase_read_started is True
                ),
                live_coinbase_orders_ran=accounting.sdk_invoked,
                live_exchange_submitted=accounting.sdk_invoked,
            )
        return MaterializationOperationResult(
            record=final_record,
            diagnostic_code=persisted_result.diagnostic_code,
            replayed=False,
            live_read_ran=child_evidence.coinbase_read_started,
            create_call_ran=False,
            cancel_call_ran=accounting.sdk_invoked,
            candidate=final_record.durable_candidate,
        )


def get_default_operator_follow_up_materialization_service(
) -> OperatorFollowUpMaterializationService:
    """Build the production service lazily to keep route imports side-effect free."""

    try:
        from application.admin_api.operator_follow_up_materialization_runtime import (
            build_default_operator_follow_up_materialization_service,
        )
    except Exception:
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_runtime_unavailable",
            503,
        ) from None
    try:
        return build_default_operator_follow_up_materialization_service()
    except OperatorFollowUpMaterializationError:
        raise
    except Exception:
        raise OperatorFollowUpMaterializationError(
            "follow_up_materialization_runtime_unavailable",
            503,
        ) from None
