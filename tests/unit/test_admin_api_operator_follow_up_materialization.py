from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal
from contextlib import contextmanager
import threading

import pytest

from application.admin_api.models import (
    AdminOrderFollowUpMaterializationCancelRequest,
    AdminOrderFollowUpMaterializationRequest,
)
from application.admin_api.operator_follow_up_materialization import (
    AUTHORIZE_AND_MATERIALIZE_FOLLOW_UP_INTENT,
    SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT,
    BackendMaterializationCandidate,
    ChildExchangeState,
    ChildStateEvidence,
    ExchangeInvocationOutcome,
    ExchangeInvocationResult,
    FollowUpMaterializationRecord,
    FreshMaterializationEligibility,
    InvocationBoundaryClaim,
    LiveProofOperationClaim,
    LiveProofTerminalEvidence,
    LocalChildPersistenceEvidence,
    LocalChildProjectionEvidence,
    MaterializationAuthorization,
    MaterializationOperationResult,
    MaterializationRecordState,
    MutationInvocationAccounting,
    OperatorFollowUpMaterializationError,
    OperatorFollowUpMaterializationService,
    OperatorFollowUpMaterializationRequestContext,
    SafeCloseoutAuthorization,
)
from core.enums import (
    FollowUpExchangeMutationState,
    FollowUpLiveProofOperationKind,
    FollowUpLiveProofTerminalOutcome,
    FollowUpReadAccountingState,
    FollowUpSdkMutationInvocationState,
    FollowUpTransportSubmissionState,
)


def _context(
    *,
    operator_intent: str = AUTHORIZE_AND_MATERIALIZE_FOLLOW_UP_INTENT,
    idempotency_key: str = "materialize-key-001",
    environment: str = "local-controlled-live",
) -> OperatorFollowUpMaterializationRequestContext:
    return OperatorFollowUpMaterializationRequestContext(
        actor_id="operator-001",
        roles=("trader",),
        idempotency_key=idempotency_key,
        correlation_id="correlation-001",
        operator_intent=operator_intent,
        audit_id="audit-001",
        environment=environment,
    )


def _authorization(**changes: bool) -> MaterializationAuthorization:
    values = {
        "authorize_materialization_of_attached_intent": True,
        "acknowledge_unknown_outcome_consumes_create_allowance": True,
        "acknowledge_child_terms_are_backend_derived": True,
    }
    values.update(changes)
    return MaterializationAuthorization(**values)


def _closeout_authorization(**changes: bool) -> SafeCloseoutAuthorization:
    values = {
        "authorize_single_cancel_for_safe_closeout": True,
        "acknowledge_unknown_outcome_consumes_cancel_allowance": True,
    }
    values.update(changes)
    return SafeCloseoutAuthorization(**values)


def _candidate(**changes: object) -> BackendMaterializationCandidate:
    from hashlib import sha256

    portfolio_id = "a79ace5d-95e9-48d2-8e31-59a8f846c1b0"
    values: dict[str, object] = {
        "attached_intent_id": "intent-001",
        "source_client_order_id": "source-001",
        "root_client_order_id": "root-001",
        "child_client_order_id": "child-001",
        "source_status": "FILLED",
        "source_side": "BUY",
        "child_side": "SELL",
        "product_id": "BTC-USDC",
        "product_type": "SPOT",
        "portfolio_type": "TEST",
        "portfolio_id": portfolio_id,
        "portfolio_scope_sha256": sha256(portfolio_id.encode()).hexdigest(),
        "environment": "local-controlled-live",
        "base_size": Decimal("0.00001"),
        "limit_price": Decimal("100000"),
        "submitted_notional_usdc": Decimal("1.00"),
        "max_submitted_notional_usdc": Decimal("3.10"),
        "max_executed_notional_usdc": Decimal("1.00"),
        "effective_notional_cap_usdc": Decimal("1.00"),
        "authoritative_source_fill_proven": True,
        "source_terminal": True,
        "attached_intent_requires_fresh_authorization": True,
        "no_existing_follow_up_child": True,
        "controlled_live_enabled": True,
        "execution_lease_valid": True,
        "approved_test_portfolio_verified": True,
        "product_policy_allowed": True,
        "action_condition_guard_passed": True,
        "wallet_check_passed": True,
    }
    values.update(changes)
    return BackendMaterializationCandidate(**values)


def _eligibility(
    candidate: BackendMaterializationCandidate | None = None,
    **changes: object,
) -> FreshMaterializationEligibility:
    values: dict[str, object] = {
        "candidate": candidate or _candidate(),
        "fresh": True,
        "eligibility_pass_count": 1,
        "reconciliation_pass_count": 1,
        "individual_retry_count": 0,
        "ambiguous": False,
        "blockers": (),
        "coinbase_read_started": True,
        "coinbase_read_count": 1,
    }
    values.update(changes)
    return FreshMaterializationEligibility(**values)


def _record(
    *,
    state: MaterializationRecordState = MaterializationRecordState.PREPARED,
    create_consumed: bool = False,
    cancel_consumed: bool = False,
    diagnostic_code: str = "follow_up_materialization_prepared",
    create_key: str = "materialize-key-001",
    cancel_key: str | None = None,
    durable_candidate: BackendMaterializationCandidate | None = None,
) -> FollowUpMaterializationRecord:
    from hashlib import sha256

    return FollowUpMaterializationRecord(
        materialization_id="materialization-001",
        attached_intent_id="intent-001",
        source_client_order_id="source-001",
        root_client_order_id="root-001",
        child_client_order_id="child-001",
        state=state,
        create_idempotency_key_sha256=sha256(create_key.encode()).hexdigest(),
        cancel_idempotency_key_sha256=(
            sha256(cancel_key.encode()).hexdigest() if cancel_key else None
        ),
        create_call_consumed=create_consumed,
        cancel_call_consumed=cancel_consumed,
        child_state=(
            ChildExchangeState.ACTIVE
            if state == MaterializationRecordState.CREATE_ACCEPTED
            else ChildExchangeState.UNKNOWN
        ),
        diagnostic_code=diagnostic_code,
        correlation_id="correlation-001",
        audit_id="audit-001",
        durable_candidate=durable_candidate,
    )


@dataclass
class FakeRepository:
    existing: FollowUpMaterializationRecord | None = None
    events: list[str] = field(default_factory=list)
    create_boundary_claimed: bool = True
    cancel_boundary_claimed: bool = True
    last_create_result: object | None = None
    last_cancel_result: object | None = None
    last_cancel_boundary_context: dict[str, object] | None = None
    last_terminal_context: dict[str, object] | None = None
    live_proof_events: list[str] = field(default_factory=list)
    live_proof_terminal_records: list[dict[str, object]] = field(
        default_factory=list
    )
    live_proof_claim_error: Exception | None = None
    claimed_live_proof_operations: set[FollowUpLiveProofOperationKind] = field(
        default_factory=set
    )
    live_proof_claim_bindings: dict[
        FollowUpLiveProofOperationKind, dict[str, str]
    ] = field(default_factory=dict)
    atomic_events: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.existing is None:
            return
        if self.existing.state is MaterializationRecordState.CREATE_INVOCATION_STARTED:
            self.claimed_live_proof_operations.add(
                FollowUpLiveProofOperationKind.CREATE
            )
        if self.existing.state is MaterializationRecordState.CANCEL_INVOCATION_STARTED:
            self.claimed_live_proof_operations.add(
                FollowUpLiveProofOperationKind.CANCEL
            )

    @contextmanager
    def live_proof_invocation_guard(self, *, source_client_order_id: str):
        assert source_client_order_id == "source-001"
        yield

    def claim_live_proof_operation(
        self,
        *,
        operation_kind: FollowUpLiveProofOperationKind,
        source_client_order_id: str,
        correlation_id: str,
        audit_id: str,
        operation_idempotency_key_sha256: str,
    ) -> LiveProofOperationClaim:
        self.live_proof_events.append(f"claim:{operation_kind.value}")
        if self.live_proof_claim_error is not None:
            raise self.live_proof_claim_error
        if operation_kind in self.claimed_live_proof_operations:
            raise RuntimeError("follow_up_live_proof_operation_consumed")
        self.claimed_live_proof_operations.add(operation_kind)
        self.live_proof_claim_bindings[operation_kind] = {
            "correlation_id": correlation_id,
            "audit_id": audit_id,
            "operation_idempotency_key_sha256": operation_idempotency_key_sha256,
        }
        bound = operation_kind is not FollowUpLiveProofOperationKind.ELIGIBILITY_READ
        return LiveProofOperationClaim(
            operation_kind=operation_kind,
            source_client_order_id=source_client_order_id,
            root_client_order_id="root-001",
            attached_intent_id="intent-001",
            materialization_id="materialization-001" if bound else None,
            child_client_order_id="child-001" if bound else None,
            correlation_id=correlation_id,
            audit_id=audit_id,
            operation_idempotency_key_sha256=operation_idempotency_key_sha256,
            claimed=True,
        )

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
    ) -> None:
        binding = self.live_proof_claim_bindings.get(operation_kind) or {
            "correlation_id": "correlation-001",
            "audit_id": "audit-001",
            "operation_idempotency_key_sha256": "a" * 64,
        }
        self.live_proof_terminal_records.append(
            {
                "operation_kind": operation_kind,
                "source_client_order_id": source_client_order_id,
                "outcome": outcome,
                "sdk_mutation_invocation_state": sdk_mutation_invocation_state,
                "transport_submission_state": transport_submission_state,
                "exchange_mutation_state": exchange_mutation_state,
                "read_accounting_state": read_accounting_state,
                "observed_read_count": observed_read_count,
                "external_call_started": external_call_started,
                "reported_read_count": reported_read_count,
                "individual_retry_count": individual_retry_count,
                "authoritative_child_state": authoritative_child_state,
                **binding,
            }
        )
        self.live_proof_events.append(
            "terminal:"
            f"{operation_kind.value}:{outcome.value}:"
            f"started={external_call_started}:reads={reported_read_count}:"
            f"retries={individual_retry_count}"
        )

    def read_live_proof_terminal(
        self,
        *,
        operation_kind: FollowUpLiveProofOperationKind,
        source_client_order_id: str,
    ) -> LiveProofTerminalEvidence | None:
        record = next(
            (
                item
                for item in reversed(self.live_proof_terminal_records)
                if item["operation_kind"] is operation_kind
                and item["source_client_order_id"] == source_client_order_id
            ),
            None,
        )
        if record is None:
            return None
        return LiveProofTerminalEvidence(
            operation_kind=operation_kind,
            source_client_order_id=source_client_order_id,
            outcome=record["outcome"],
            correlation_id=str(record["correlation_id"]),
            audit_id=str(record["audit_id"]),
            operation_idempotency_key_sha256=str(
                record["operation_idempotency_key_sha256"]
            ),
            sdk_mutation_invocation_state=record[
                "sdk_mutation_invocation_state"
            ],
            transport_submission_state=record["transport_submission_state"],
            exchange_mutation_state=record["exchange_mutation_state"],
            read_accounting_state=record["read_accounting_state"],
            observed_read_count=record["observed_read_count"],
            external_call_started=record["external_call_started"] is True,
            reported_read_count=int(record["reported_read_count"]),
            individual_retry_count=int(record["individual_retry_count"]),
            authoritative_child_state=record["authoritative_child_state"],
        )

    def read_live_proof_claim(
        self,
        *,
        operation_kind: FollowUpLiveProofOperationKind,
        source_client_order_id: str,
    ) -> LiveProofOperationClaim | None:
        if operation_kind not in self.claimed_live_proof_operations:
            return None
        binding = self.live_proof_claim_bindings.get(operation_kind, {})
        existing = self.existing
        operation_hash = (
            existing.cancel_idempotency_key_sha256
            if existing is not None
            and operation_kind is FollowUpLiveProofOperationKind.CANCEL
            else existing.create_idempotency_key_sha256
            if existing is not None
            and operation_kind is FollowUpLiveProofOperationKind.CREATE
            else binding.get("operation_idempotency_key_sha256", "a" * 64)
        )
        bound = operation_kind is not FollowUpLiveProofOperationKind.ELIGIBILITY_READ
        return LiveProofOperationClaim(
            operation_kind=operation_kind,
            source_client_order_id=source_client_order_id,
            root_client_order_id=(
                existing.root_client_order_id if existing is not None else "root-001"
            ),
            attached_intent_id=(
                existing.attached_intent_id if existing is not None else "intent-001"
            ),
            materialization_id=(existing.materialization_id if bound and existing else None),
            child_client_order_id=(
                existing.child_client_order_id if bound and existing else None
            ),
            correlation_id=str(
                binding.get(
                    "correlation_id",
                    existing.correlation_id if existing is not None else "correlation-001",
                )
            ),
            audit_id=str(
                binding.get(
                    "audit_id",
                    existing.audit_id if existing is not None else "audit-001",
                )
            ),
            operation_idempotency_key_sha256=str(operation_hash or ""),
            claimed=True,
        )

    def read_materialization(
        self,
        *,
        source_client_order_id: str,
        operation: str,
        idempotency_key: str | None,
    ) -> FollowUpMaterializationRecord | None:
        self.events.append(f"read:{operation}")
        return self.existing

    def prepare_materialization(self, command):
        self.events.append("prepare")
        self.existing = replace(
            _record(create_key=command.idempotency_key),
            audit_id=command.audit_id,
        )
        return self.existing

    def mark_create_invocation_started(
        self,
        *,
        materialization_id: str,
        correlation_id: str,
    ) -> InvocationBoundaryClaim:
        self.events.append("mark_create")
        assert self.existing is not None
        self.existing = replace(
            self.existing,
            state=MaterializationRecordState.CREATE_INVOCATION_STARTED,
            create_call_consumed=True,
            diagnostic_code="follow_up_materialization_create_outcome_unknown",
        )
        return InvocationBoundaryClaim(
            record=self.existing,
            claimed=self.create_boundary_claimed,
        )

    def claim_create_invocation_started_atomically(
        self,
        *,
        source_client_order_id: str,
        materialization_id: str,
        correlation_id: str,
        audit_id: str,
        operation_idempotency_key_sha256: str,
    ) -> InvocationBoundaryClaim:
        self.atomic_events.append("start:CREATE")
        assert self.existing is not None
        self.claimed_live_proof_operations.add(
            FollowUpLiveProofOperationKind.CREATE
        )
        self.live_proof_claim_bindings[FollowUpLiveProofOperationKind.CREATE] = {
            "correlation_id": correlation_id,
            "audit_id": audit_id,
            "operation_idempotency_key_sha256": (
                operation_idempotency_key_sha256
            ),
        }
        self.existing = replace(
            self.existing,
            state=MaterializationRecordState.CREATE_INVOCATION_STARTED,
            create_call_consumed=True,
            diagnostic_code="follow_up_materialization_create_outcome_unknown",
        )
        return InvocationBoundaryClaim(
            record=self.existing,
            claimed=self.create_boundary_claimed,
        )

    def record_create_result(self, *, materialization_id: str, result):
        self.events.append(f"record_create:{result.outcome.value}")
        self.last_create_result = result
        assert self.existing is not None
        state = {
            ExchangeInvocationOutcome.ACCEPTED: MaterializationRecordState.CREATE_ACCEPTED,
            ExchangeInvocationOutcome.REJECTED: MaterializationRecordState.CREATE_REJECTED,
            ExchangeInvocationOutcome.UNKNOWN: MaterializationRecordState.CREATE_UNKNOWN,
        }[result.outcome]
        self.existing = replace(
            self.existing,
            state=state,
            child_state=result.child_state,
            diagnostic_code=result.diagnostic_code,
        )
        return self.existing

    def finalize_create_invocation_atomically(
        self,
        *,
        source_client_order_id: str,
        materialization_id: str,
        result,
        accounting: MutationInvocationAccounting,
        external_call_started: bool,
        reported_read_count: int,
        individual_retry_count: int,
    ):
        if individual_retry_count != 0:
            raise RuntimeError("retry_accounting_rejected")
        self.atomic_events.append(f"finalize:CREATE:{result.outcome.value}")
        self.last_create_result = result
        assert self.existing is not None
        state = {
            ExchangeInvocationOutcome.ACCEPTED: (
                MaterializationRecordState.CREATE_ACCEPTED
            ),
            ExchangeInvocationOutcome.REJECTED: (
                MaterializationRecordState.CREATE_REJECTED
            ),
            ExchangeInvocationOutcome.UNKNOWN: (
                MaterializationRecordState.CREATE_UNKNOWN
            ),
        }[result.outcome]
        self.existing = replace(
            self.existing,
            state=state,
            child_state=result.child_state,
            diagnostic_code=result.diagnostic_code,
        )
        proof_outcome = {
            ExchangeInvocationOutcome.ACCEPTED: (
                FollowUpLiveProofTerminalOutcome.SUCCEEDED
            ),
            ExchangeInvocationOutcome.REJECTED: (
                FollowUpLiveProofTerminalOutcome.REJECTED
            ),
            ExchangeInvocationOutcome.UNKNOWN: (
                FollowUpLiveProofTerminalOutcome.BLOCKED
                if accounting.sdk_mutation_invocation_state
                is FollowUpSdkMutationInvocationState.NOT_INVOKED
                else FollowUpLiveProofTerminalOutcome.UNKNOWN
            ),
        }[result.outcome]
        binding = self.live_proof_claim_bindings.get(
            FollowUpLiveProofOperationKind.CREATE,
            {
                "correlation_id": self.existing.correlation_id,
                "audit_id": self.existing.audit_id,
                "operation_idempotency_key_sha256": (
                    self.existing.create_idempotency_key_sha256
                ),
            },
        )
        self.live_proof_terminal_records.append(
            {
                "operation_kind": FollowUpLiveProofOperationKind.CREATE,
                "source_client_order_id": source_client_order_id,
                "outcome": proof_outcome,
                "sdk_mutation_invocation_state": (
                    accounting.sdk_mutation_invocation_state
                ),
                "transport_submission_state": (
                    accounting.transport_submission_state
                ),
                "exchange_mutation_state": accounting.exchange_mutation_state,
                "read_accounting_state": accounting.read_accounting_state,
                "observed_read_count": accounting.observed_read_count,
                "external_call_started": external_call_started,
                "reported_read_count": reported_read_count,
                "individual_retry_count": individual_retry_count,
                "authoritative_child_state": result.child_state,
                **binding,
            }
        )
        return self.existing

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
    ) -> InvocationBoundaryClaim:
        from hashlib import sha256

        self.events.append("mark_cancel")
        self.last_cancel_boundary_context = {
            "idempotency_key": idempotency_key,
            "actor_id": actor_id,
            "roles": roles,
            "environment": environment,
            "operator_intent": operator_intent,
            "correlation_id": correlation_id,
            "audit_id": audit_id,
        }
        assert self.existing is not None
        self.existing = replace(
            self.existing,
            state=MaterializationRecordState.CANCEL_INVOCATION_STARTED,
            cancel_idempotency_key_sha256=sha256(idempotency_key.encode()).hexdigest(),
            cancel_call_consumed=True,
            diagnostic_code="follow_up_materialization_cancel_outcome_unknown",
            audit_id=audit_id,
        )
        return InvocationBoundaryClaim(
            record=self.existing,
            claimed=self.cancel_boundary_claimed,
        )

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
    ) -> InvocationBoundaryClaim:
        from hashlib import sha256

        self.atomic_events.append("start:CANCEL")
        self.last_cancel_boundary_context = {
            "idempotency_key": idempotency_key,
            "actor_id": actor_id,
            "roles": roles,
            "environment": environment,
            "operator_intent": operator_intent,
            "correlation_id": correlation_id,
            "audit_id": audit_id,
        }
        assert self.existing is not None
        operation_hash = sha256(idempotency_key.encode()).hexdigest()
        self.claimed_live_proof_operations.add(
            FollowUpLiveProofOperationKind.CANCEL
        )
        self.live_proof_claim_bindings[FollowUpLiveProofOperationKind.CANCEL] = {
            "correlation_id": correlation_id,
            "audit_id": audit_id,
            "operation_idempotency_key_sha256": operation_hash,
        }
        self.existing = replace(
            self.existing,
            state=MaterializationRecordState.CANCEL_INVOCATION_STARTED,
            cancel_idempotency_key_sha256=operation_hash,
            cancel_call_consumed=True,
            diagnostic_code="follow_up_materialization_cancel_outcome_unknown",
            audit_id=audit_id,
        )
        return InvocationBoundaryClaim(
            record=self.existing,
            claimed=self.cancel_boundary_claimed,
        )

    def record_cancel_result(self, *, materialization_id: str, result):
        self.events.append(f"record_cancel:{result.outcome.value}")
        self.last_cancel_result = result
        assert self.existing is not None
        state = {
            ExchangeInvocationOutcome.ACCEPTED: MaterializationRecordState.CANCEL_ACCEPTED,
            ExchangeInvocationOutcome.REJECTED: MaterializationRecordState.CANCEL_REJECTED,
            ExchangeInvocationOutcome.UNKNOWN: MaterializationRecordState.CANCEL_UNKNOWN,
            ExchangeInvocationOutcome.NOT_REQUIRED_TERMINAL: (
                MaterializationRecordState.CHILD_ALREADY_TERMINAL
            ),
        }[result.outcome]
        self.existing = replace(
            self.existing,
            state=state,
            child_state=result.child_state,
            cancel_idempotency_key_sha256=(
                result.operation_idempotency_key_sha256
            ),
            diagnostic_code=result.diagnostic_code,
        )
        return self.existing

    def finalize_cancel_invocation_atomically(
        self,
        *,
        source_client_order_id: str,
        materialization_id: str,
        result,
        accounting: MutationInvocationAccounting,
        external_call_started: bool,
        reported_read_count: int,
        individual_retry_count: int,
    ):
        if individual_retry_count != 0:
            raise RuntimeError("retry_accounting_rejected")
        self.atomic_events.append(f"finalize:CANCEL:{result.outcome.value}")
        self.last_cancel_result = result
        assert self.existing is not None
        state = {
            ExchangeInvocationOutcome.ACCEPTED: (
                MaterializationRecordState.CANCEL_ACCEPTED
            ),
            ExchangeInvocationOutcome.REJECTED: (
                MaterializationRecordState.CANCEL_REJECTED
            ),
            ExchangeInvocationOutcome.UNKNOWN: (
                MaterializationRecordState.CANCEL_UNKNOWN
            ),
        }[result.outcome]
        self.existing = replace(
            self.existing,
            state=state,
            child_state=result.child_state,
            cancel_idempotency_key_sha256=(
                result.operation_idempotency_key_sha256
            ),
            diagnostic_code=result.diagnostic_code,
        )
        proof_outcome = {
            ExchangeInvocationOutcome.ACCEPTED: (
                FollowUpLiveProofTerminalOutcome.SUCCEEDED
            ),
            ExchangeInvocationOutcome.REJECTED: (
                FollowUpLiveProofTerminalOutcome.REJECTED
            ),
            ExchangeInvocationOutcome.UNKNOWN: (
                FollowUpLiveProofTerminalOutcome.BLOCKED
                if accounting.sdk_mutation_invocation_state
                is FollowUpSdkMutationInvocationState.NOT_INVOKED
                else FollowUpLiveProofTerminalOutcome.UNKNOWN
            ),
        }[result.outcome]
        binding = self.live_proof_claim_bindings.get(
            FollowUpLiveProofOperationKind.CANCEL,
            {
                "correlation_id": self.existing.correlation_id,
                "audit_id": self.existing.audit_id,
                "operation_idempotency_key_sha256": (
                    self.existing.cancel_idempotency_key_sha256 or ""
                ),
            },
        )
        self.live_proof_terminal_records.append(
            {
                "operation_kind": FollowUpLiveProofOperationKind.CANCEL,
                "source_client_order_id": source_client_order_id,
                "outcome": proof_outcome,
                "sdk_mutation_invocation_state": (
                    accounting.sdk_mutation_invocation_state
                ),
                "transport_submission_state": (
                    accounting.transport_submission_state
                ),
                "exchange_mutation_state": accounting.exchange_mutation_state,
                "read_accounting_state": accounting.read_accounting_state,
                "observed_read_count": accounting.observed_read_count,
                "external_call_started": external_call_started,
                "reported_read_count": reported_read_count,
                "individual_retry_count": individual_retry_count,
                "authoritative_child_state": result.child_state,
                **binding,
            }
        )
        return self.existing

    def finalize_active_reconciliation_atomically(
        self,
        *,
        source_client_order_id: str,
        record,
        claim,
        evidence,
    ):
        self.atomic_events.append("finalize:RECONCILIATION:ACTIVE")
        assert self.existing is not None
        assert record.materialization_id == self.existing.materialization_id
        assert evidence.state is ChildExchangeState.ACTIVE
        self.live_proof_terminal_records.append(
            {
                "operation_kind": (
                    FollowUpLiveProofOperationKind.RECONCILIATION_READ
                ),
                "source_client_order_id": source_client_order_id,
                "outcome": FollowUpLiveProofTerminalOutcome.SUCCEEDED,
                "sdk_mutation_invocation_state": (
                    FollowUpSdkMutationInvocationState.NOT_INVOKED
                ),
                "transport_submission_state": (
                    FollowUpTransportSubmissionState.NOT_SUBMITTED
                ),
                "exchange_mutation_state": (
                    FollowUpExchangeMutationState.NOT_MUTATED
                ),
                "read_accounting_state": FollowUpReadAccountingState.EXACT,
                "observed_read_count": evidence.read_count,
                "external_call_started": False,
                "reported_read_count": evidence.read_count,
                "individual_retry_count": 0,
                "authoritative_child_state": ChildExchangeState.ACTIVE,
                "correlation_id": claim.correlation_id,
                "audit_id": claim.audit_id,
                "operation_idempotency_key_sha256": (
                    claim.operation_idempotency_key_sha256
                ),
            }
        )
        return self.existing

    def finalize_terminal_without_cancel_atomically(
        self,
        *,
        source_client_order_id: str,
        record,
        claim,
        evidence,
        result,
        idempotency_key: str,
        actor_id: str,
        roles: tuple[str, ...],
        environment: str,
        operator_intent: str,
        correlation_id: str,
        audit_id: str,
    ):
        del idempotency_key, actor_id, roles, environment, operator_intent
        self.atomic_events.append("finalize:RECONCILIATION:TERMINAL")
        assert self.existing is not None
        assert record.materialization_id == self.existing.materialization_id
        assert evidence.state is ChildExchangeState.TERMINAL
        self.last_terminal_context = {
            "correlation_id": correlation_id,
            "audit_id": audit_id,
        }
        self.existing = replace(
            self.existing,
            state=MaterializationRecordState.CHILD_ALREADY_TERMINAL,
            child_state=ChildExchangeState.TERMINAL,
            diagnostic_code=result.diagnostic_code,
            audit_id=audit_id,
        )
        self.live_proof_terminal_records.append(
            {
                "operation_kind": (
                    FollowUpLiveProofOperationKind.RECONCILIATION_READ
                ),
                "source_client_order_id": source_client_order_id,
                "outcome": FollowUpLiveProofTerminalOutcome.SUCCEEDED,
                "sdk_mutation_invocation_state": (
                    FollowUpSdkMutationInvocationState.NOT_INVOKED
                ),
                "transport_submission_state": (
                    FollowUpTransportSubmissionState.NOT_SUBMITTED
                ),
                "exchange_mutation_state": (
                    FollowUpExchangeMutationState.NOT_MUTATED
                ),
                "read_accounting_state": FollowUpReadAccountingState.EXACT,
                "observed_read_count": evidence.read_count,
                "external_call_started": False,
                "reported_read_count": evidence.read_count,
                "individual_retry_count": 0,
                "authoritative_child_state": ChildExchangeState.TERMINAL,
                "correlation_id": claim.correlation_id,
                "audit_id": claim.audit_id,
                "operation_idempotency_key_sha256": (
                    claim.operation_idempotency_key_sha256
                ),
            }
        )
        return self.existing

    def record_child_terminal_without_cancel(
        self,
        *,
        materialization_id: str,
        result,
        idempotency_key: str,
        actor_id: str,
        roles: tuple[str, ...],
        environment: str,
        operator_intent: str,
        audit_id: str,
    ):
        self.events.append("record_child_terminal_without_cancel")
        self.last_terminal_context = {
            "idempotency_key": idempotency_key,
            "actor_id": actor_id,
            "roles": roles,
            "environment": environment,
            "operator_intent": operator_intent,
            "audit_id": audit_id,
        }
        self.last_cancel_result = result
        assert self.existing is not None
        self.existing = replace(
            self.existing,
            state=MaterializationRecordState.CHILD_ALREADY_TERMINAL,
            child_state=ChildExchangeState.TERMINAL,
            cancel_idempotency_key_sha256=(
                result.operation_idempotency_key_sha256
            ),
            diagnostic_code=result.diagnostic_code,
            audit_id=audit_id,
        )
        return self.existing


@dataclass
class FakeRuntime:
    eligibility: FreshMaterializationEligibility = field(default_factory=_eligibility)
    child_state: ChildStateEvidence = field(
        default_factory=lambda: ChildStateEvidence(
            child_client_order_id="child-001",
            state=ChildExchangeState.ACTIVE,
            fresh=True,
            authoritative=True,
            read_count=1,
            individual_retry_count=0,
            ambiguous=False,
            coinbase_read_started=True,
            exchange_order_id_sha256="a" * 64,
        )
    )
    events: list[str] = field(default_factory=list)
    observed_child_read_binding: dict[str, str] | None = None
    projection_events: list[str] = field(default_factory=list)
    projection_succeeds: bool = True
    projection_live_read_count: int = 0
    observed_projection_records: list[FollowUpMaterializationRecord] = field(
        default_factory=list
    )
    active_identity_validations: list[str] = field(default_factory=list)

    def resolve_fresh_materialization_eligibility(self, *, source_client_order_id: str):
        self.events.append("eligibility")
        return self.eligibility

    def read_authoritative_child_state(
        self,
        *,
        child_client_order_id: str,
        materialization_id: str,
        operation_audit_id: str,
        operation_idempotency_key_sha256: str,
    ):
        self.events.append("child_state")
        self.observed_child_read_binding = {
            "child_client_order_id": child_client_order_id,
            "materialization_id": materialization_id,
            "operation_audit_id": operation_audit_id,
            "operation_idempotency_key_sha256": (
                operation_idempotency_key_sha256
            ),
        }
        return self.child_state

    def persist_preclaimed_child(self, *, candidate, materialization_id: str):
        self.events.append("persist_child")
        return LocalChildPersistenceEvidence(
            materialization_id=materialization_id,
            child_client_order_id=candidate.child_client_order_id,
            persisted=True,
            exact_replay_safe=True,
            exchange_call_ran=False,
        )

    def project_persisted_child_state(
        self,
        *,
        record: FollowUpMaterializationRecord,
        operation: str,
        allow_reconciliation_read: bool,
        evidence_audit_id: str | None = None,
        evidence_idempotency_key_sha256: str | None = None,
    ) -> LocalChildProjectionEvidence:
        del evidence_audit_id, evidence_idempotency_key_sha256
        self.projection_events.append(operation)
        self.observed_projection_records.append(record)
        return LocalChildProjectionEvidence(
            materialization_id=record.materialization_id,
            child_client_order_id=record.child_client_order_id,
            record_state=record.state,
            projected=self.projection_succeeds,
            exact_replay_safe=self.projection_succeeds,
            exchange_call_ran=False,
            live_read_count=(
                self.projection_live_read_count
                if allow_reconciliation_read
                else 0
            ),
            individual_retry_count=0,
        )

    def validate_persisted_active_child_identity(
        self,
        *,
        record: FollowUpMaterializationRecord,
    ) -> LocalChildProjectionEvidence:
        self.active_identity_validations.append(record.materialization_id)
        return LocalChildProjectionEvidence(
            materialization_id=record.materialization_id,
            child_client_order_id=record.child_client_order_id,
            record_state=record.state,
            projected=True,
            exact_replay_safe=True,
            exchange_call_ran=False,
            live_read_count=0,
            individual_retry_count=0,
        )


@dataclass
class FakeExchange:
    create_result: ExchangeInvocationResult = field(
        default_factory=lambda: ExchangeInvocationResult(
            outcome=ExchangeInvocationOutcome.ACCEPTED,
            child_state=ChildExchangeState.ACTIVE,
            exchange_call_started=True,
            exchange_order_id_sha256="a" * 64,
            post_mutation_read_started=True,
            post_mutation_read_count=1,
        )
    )
    cancel_result: ExchangeInvocationResult = field(
        default_factory=lambda: ExchangeInvocationResult(
            outcome=ExchangeInvocationOutcome.ACCEPTED,
            child_state=ChildExchangeState.TERMINAL,
            exchange_call_started=True,
            exchange_order_id_sha256="a" * 64,
            post_mutation_read_started=True,
            post_mutation_read_count=1,
        )
    )
    events: list[str] = field(default_factory=list)
    create_exception: Exception | None = None
    cancel_exception: Exception | None = None
    observed_candidate: BackendMaterializationCandidate | None = None
    observed_create_binding: dict[str, str] | None = None
    observed_cancel_binding: dict[str, str] | None = None

    def create_follow_up_child(
        self,
        *,
        candidate,
        correlation_id: str,
        materialization_id: str,
        operation_audit_id: str,
        operation_idempotency_key_sha256: str,
    ):
        self.events.append("create")
        self.observed_candidate = candidate
        self.observed_create_binding = {
            "correlation_id": correlation_id,
            "materialization_id": materialization_id,
            "operation_audit_id": operation_audit_id,
            "operation_idempotency_key_sha256": (
                operation_idempotency_key_sha256
            ),
        }
        if self.create_exception:
            raise self.create_exception
        return self.create_result

    def cancel_follow_up_child(
        self,
        *,
        child_client_order_id: str,
        correlation_id: str,
        materialization_id: str,
        operation_audit_id: str,
        operation_idempotency_key_sha256: str,
    ):
        self.events.append("cancel")
        self.observed_cancel_binding = {
            "child_client_order_id": child_client_order_id,
            "correlation_id": correlation_id,
            "materialization_id": materialization_id,
            "operation_audit_id": operation_audit_id,
            "operation_idempotency_key_sha256": (
                operation_idempotency_key_sha256
            ),
        }
        if self.cancel_exception:
            raise self.cancel_exception
        return self.cancel_result


def _service(
    repository: FakeRepository | None = None,
    runtime: FakeRuntime | None = None,
    exchange: FakeExchange | None = None,
):
    repository = repository or FakeRepository()
    runtime = runtime or FakeRuntime()
    exchange = exchange or FakeExchange()
    return (
        OperatorFollowUpMaterializationService(
            repository=repository,
            runtime=runtime,
            exchange=exchange,
        ),
        repository,
        runtime,
        exchange,
    )


def test_passive_read_is_repository_only_and_reports_no_coinbase_calls():
    existing = _record(
        state=MaterializationRecordState.CREATE_ACCEPTED,
        create_consumed=True,
        diagnostic_code="follow_up_materialization_create_accepted",
    )
    service, repository, runtime, exchange = _service(
        repository=FakeRepository(existing=existing)
    )

    result = service.read(source_client_order_id="source-001")

    assert result.record == existing
    assert result.read_only is True
    assert result.live_read_ran is False
    assert result.create_call_ran is False
    assert result.cancel_call_ran is False
    assert repository.events == ["read:READ"]
    assert runtime.events == []
    assert exchange.events == []


@pytest.mark.parametrize(
    ("context", "authorization", "expected_code"),
    [
        (
            _context(operator_intent="attach_single_follow_up_intent"),
            _authorization(),
            "follow_up_materialization_operator_intent_mismatch",
        ),
        (
            _context(),
            _authorization(authorize_materialization_of_attached_intent=False),
            "follow_up_materialization_fresh_authorization_required",
        ),
        (
            replace(_context(), roles=("operator",)),
            _authorization(),
            "follow_up_materialization_permission_denied",
        ),
    ],
)
def test_materialize_rejects_attachment_ack_missing_fresh_ack_or_missing_rbac(
    context, authorization, expected_code
):
    service, repository, runtime, exchange = _service()

    with pytest.raises(OperatorFollowUpMaterializationError) as exc_info:
        service.materialize(
            source_client_order_id="source-001",
            request=authorization,
            context=context,
        )

    assert exc_info.value.code == expected_code
    assert repository.events == []
    assert runtime.events == []
    assert exchange.events == []


def test_materialize_derives_exact_candidate_from_backend_and_orders_boundary_before_call():
    candidate = _candidate()
    runtime = FakeRuntime(eligibility=_eligibility(candidate))
    service, repository, runtime, exchange = _service(runtime=runtime)

    result = service.materialize(
        source_client_order_id="source-001",
        request=_authorization(),
        context=_context(),
    )

    assert exchange.observed_candidate is candidate
    assert result.create_call_ran is True
    assert exchange.observed_create_binding == {
        "correlation_id": "correlation-001",
        "materialization_id": "materialization-001",
        "operation_audit_id": "audit-001",
        "operation_idempotency_key_sha256": (
            _record().create_idempotency_key_sha256
        ),
    }
    assert result.record.state == MaterializationRecordState.CREATE_ACCEPTED
    assert result.diagnostic_code == "follow_up_materialization_create_accepted"
    assert result.live_read_ran is True
    assert result.create_call_ran is True
    assert result.cancel_call_ran is False
    assert result.replayed is False
    assert result.eligibility == runtime.eligibility
    assert result.candidate is candidate
    assert repository.events == ["read:CREATE", "prepare"]
    assert repository.atomic_events == [
        "start:CREATE",
        "finalize:CREATE:ACCEPTED",
    ]
    assert runtime.events == ["eligibility", "persist_child"]
    assert runtime.projection_events == []
    assert exchange.events == ["create"]


def test_materialize_uses_only_atomic_create_ledger_boundaries():
    class AtomicOnlyRepository(FakeRepository):
        def mark_create_invocation_started(self, **_kwargs):
            raise AssertionError("legacy_create_start_used")

        def record_create_result(self, **_kwargs):
            raise AssertionError("legacy_create_result_used")

        def claim_live_proof_operation(self, **kwargs):
            if kwargs["operation_kind"] is FollowUpLiveProofOperationKind.CREATE:
                raise AssertionError("separate_create_goal_claim_used")
            return super().claim_live_proof_operation(**kwargs)

        def record_live_proof_terminal(self, **kwargs):
            if kwargs["operation_kind"] is FollowUpLiveProofOperationKind.CREATE:
                raise AssertionError("separate_create_goal_terminal_used")
            return super().record_live_proof_terminal(**kwargs)

    repository = AtomicOnlyRepository()
    service, repository, runtime, exchange = _service(repository=repository)

    result = service.materialize(
        source_client_order_id="source-001",
        request=_authorization(),
        context=_context(),
    )

    assert result.record.state is MaterializationRecordState.CREATE_ACCEPTED
    assert repository.atomic_events == [
        "start:CREATE",
        "finalize:CREATE:ACCEPTED",
    ]
    assert runtime.projection_events == []
    assert exchange.events == ["create"]


def test_goal_claim_and_invocation_journal_precede_live_eligibility_runtime():
    trace: list[str] = []

    class TracingRepository(FakeRepository):
        def claim_live_proof_operation(self, **kwargs):
            trace.append(f"claim:{kwargs['operation_kind'].value}")
            return super().claim_live_proof_operation(**kwargs)

        def record_live_proof_terminal(self, **kwargs):
            trace.append(f"terminal:{kwargs['operation_kind'].value}")
            return super().record_live_proof_terminal(**kwargs)

        def claim_create_invocation_started_atomically(self, **kwargs):
            trace.append("atomic_start:CREATE")
            return super().claim_create_invocation_started_atomically(**kwargs)

        def finalize_create_invocation_atomically(self, **kwargs):
            trace.append("atomic_finalize:CREATE")
            return super().finalize_create_invocation_atomically(**kwargs)

    class TracingRuntime(FakeRuntime):
        def resolve_fresh_materialization_eligibility(self, **kwargs):
            trace.append("runtime:eligibility")
            return super().resolve_fresh_materialization_eligibility(**kwargs)

    class TracingExchange(FakeExchange):
        def create_follow_up_child(self, **kwargs):
            trace.append("exchange:create")
            return super().create_follow_up_child(**kwargs)

    service, _repository, _runtime, _exchange = _service(
        repository=TracingRepository(),
        runtime=TracingRuntime(),
        exchange=TracingExchange(),
    )

    service.materialize(
        source_client_order_id="source-001",
        request=_authorization(),
        context=_context(),
    )

    assert trace == [
        "claim:ELIGIBILITY_READ",
        "runtime:eligibility",
        "terminal:ELIGIBILITY_READ",
        "atomic_start:CREATE",
        "exchange:create",
        "atomic_finalize:CREATE",
    ]


def test_service_accepts_exact_route_pydantic_acknowledgement_body():
    service, _repository, _runtime, exchange = _service()

    result = service.materialize(
        source_client_order_id="source-001",
        request=AdminOrderFollowUpMaterializationRequest(
            authorize_materialization_of_attached_intent=True,
            acknowledge_unknown_outcome_consumes_create_allowance=True,
            acknowledge_child_terms_are_backend_derived=True,
        ),
        context=_context(),
    )

    assert result.record.state == MaterializationRecordState.CREATE_ACCEPTED
    assert exchange.events == ["create"]


@pytest.mark.parametrize(
    ("eligibility", "expected_code"),
    [
        (_eligibility(fresh=False), "follow_up_materialization_eligibility_not_fresh"),
        (
            _eligibility(coinbase_read_started=False),
            "follow_up_materialization_live_read_required",
        ),
        (
            _eligibility(individual_retry_count=1),
            "follow_up_materialization_eligibility_retry_detected",
        ),
        (
            _eligibility(candidate=_candidate(controlled_live_enabled=False)),
            "follow_up_materialization_controlled_live_required",
        ),
        (
            _eligibility(candidate=_candidate(portfolio_type="PROD")),
            "follow_up_materialization_test_portfolio_required",
        ),
        (
            _eligibility(candidate=_candidate(source_status="OPEN")),
            "follow_up_materialization_authoritative_fill_required",
        ),
        (
            _eligibility(candidate=_candidate(product_type="FUTURE")),
            "follow_up_materialization_spot_product_required",
        ),
        (
            _eligibility(candidate=_candidate(environment="different-environment")),
            "follow_up_materialization_environment_mismatch",
        ),
        (
            _eligibility(candidate=_candidate(action_condition_guard_passed=False)),
            "follow_up_materialization_action_condition_guard_failed",
        ),
        (
            _eligibility(candidate=_candidate(wallet_check_passed=False)),
            "follow_up_materialization_wallet_check_failed",
        ),
        (
            _eligibility(
                candidate=_candidate(
                    base_size=Decimal("0.0000101"),
                    submitted_notional_usdc=Decimal("1.01"),
                )
            ),
            "follow_up_materialization_current_caps_exceeded",
        ),
        (
            _eligibility(candidate=_candidate(max_submitted_notional_usdc=Decimal("3.11"))),
            "follow_up_materialization_current_caps_exceeded",
        ),
    ],
)
def test_materialize_fails_closed_before_prepare_or_create(eligibility, expected_code):
    service, repository, runtime, exchange = _service(
        runtime=FakeRuntime(eligibility=eligibility)
    )

    with pytest.raises(OperatorFollowUpMaterializationError) as exc_info:
        service.materialize(
            source_client_order_id="source-001",
            request=_authorization(),
            context=_context(),
        )

    assert exc_info.value.code == expected_code
    assert repository.events == ["read:CREATE"]
    assert runtime.events == ["eligibility"]
    assert exchange.events == []


@pytest.mark.parametrize(
    ("exchange_result", "expected_state", "expected_diagnostic"),
    [
        (
            ExchangeInvocationResult(
                outcome=ExchangeInvocationOutcome.REJECTED,
                child_state=ChildExchangeState.UNKNOWN,
                exchange_call_started=True,
            ),
            MaterializationRecordState.CREATE_REJECTED,
            "follow_up_materialization_create_rejected",
        ),
        (
            ExchangeInvocationResult(
                outcome=ExchangeInvocationOutcome.UNKNOWN,
                child_state=ChildExchangeState.UNKNOWN,
                exchange_call_started=True,
            ),
            MaterializationRecordState.CREATE_UNKNOWN,
            "follow_up_materialization_create_outcome_unknown",
        ),
    ],
)
def test_create_result_is_fixed_sanitized_and_never_retried(
    exchange_result, expected_state, expected_diagnostic
):
    exchange = FakeExchange(create_result=exchange_result)
    service, repository, _runtime, exchange = _service(exchange=exchange)

    result = service.materialize(
        source_client_order_id="source-001",
        request=_authorization(),
        context=_context(),
    )

    assert result.record.state == expected_state
    assert result.record.create_call_consumed is True
    assert result.diagnostic_code == expected_diagnostic
    assert exchange.events == ["create"]
    assert repository.atomic_events[-1] == (
        f"finalize:CREATE:{exchange_result.outcome.value}"
    )


@pytest.mark.parametrize(
    ("post_read_started", "post_read_count", "retry_count"),
    (
        pytest.param(False, 0, 0, id="accepted-without-post-create-read"),
        pytest.param(True, 1, 1, id="retry-observed"),
        pytest.param(True, 2, 0, id="too-many-post-create-reads"),
        pytest.param(False, 1, 0, id="read-count-without-start"),
    ),
)
def test_create_accounting_violation_is_consumed_unknown_and_never_clean_success(
    post_read_started: bool,
    post_read_count: int,
    retry_count: int,
):
    exchange = FakeExchange(
        create_result=ExchangeInvocationResult(
            outcome=ExchangeInvocationOutcome.ACCEPTED,
            child_state=ChildExchangeState.ACTIVE,
            exchange_call_started=True,
            exchange_order_id_sha256="a" * 64,
            post_mutation_read_started=post_read_started,
            post_mutation_read_count=post_read_count,
            individual_retry_count=retry_count,
        )
    )
    service, repository, _runtime, exchange = _service(exchange=exchange)

    if retry_count:
        with pytest.raises(OperatorFollowUpMaterializationError) as rejected_retry:
            service.materialize(
                source_client_order_id="source-001",
                request=_authorization(),
                context=_context(),
            )
        assert rejected_retry.value.code == (
            "follow_up_materialization_result_persistence_unavailable"
        )
        assert exchange.events == ["create"]
        return

    result = service.materialize(
        source_client_order_id="source-001",
        request=_authorization(),
        context=_context(),
    )

    assert result.record.state is MaterializationRecordState.CREATE_UNKNOWN
    assert result.record.create_call_consumed is True
    assert result.create_call_ran is False
    assert exchange.events == ["create"]
    assert repository.last_create_result is not None
    assert repository.last_create_result.outcome is ExchangeInvocationOutcome.UNKNOWN
    terminal = repository.live_proof_terminal_records[-1]
    assert terminal["operation_kind"] is FollowUpLiveProofOperationKind.CREATE
    assert terminal["outcome"] is FollowUpLiveProofTerminalOutcome.UNKNOWN
    assert terminal["sdk_mutation_invocation_state"] is (
        FollowUpSdkMutationInvocationState.UNKNOWN
    )
    assert terminal["transport_submission_state"] is (
        FollowUpTransportSubmissionState.POSSIBLY_SUBMITTED
    )
    assert terminal["exchange_mutation_state"] is (
        FollowUpExchangeMutationState.UNKNOWN
    )
    assert terminal["read_accounting_state"] is FollowUpReadAccountingState.UNKNOWN
    assert terminal["observed_read_count"] is None
    assert terminal["reported_read_count"] == 0
    assert terminal["individual_retry_count"] == 0


def test_create_exception_is_unknown_consumed_and_not_retried():
    exchange = FakeExchange(create_exception=RuntimeError("withheld exchange detail"))
    service, repository, _runtime, exchange = _service(exchange=exchange)

    result = service.materialize(
        source_client_order_id="source-001",
        request=_authorization(),
        context=_context(),
    )

    assert result.record.state == MaterializationRecordState.CREATE_UNKNOWN
    assert result.record.create_call_consumed is True
    assert result.diagnostic_code == "follow_up_materialization_create_outcome_unknown"
    assert "withheld" not in repr(result)
    assert exchange.events == ["create"]
    assert repository.atomic_events[-1] == "finalize:CREATE:UNKNOWN"
    exception_terminal = repository.live_proof_terminal_records[-1]
    assert exception_terminal["sdk_mutation_invocation_state"] is (
        FollowUpSdkMutationInvocationState.UNKNOWN
    )
    assert exception_terminal["transport_submission_state"] is (
        FollowUpTransportSubmissionState.POSSIBLY_SUBMITTED
    )
    assert exception_terminal["exchange_mutation_state"] is (
        FollowUpExchangeMutationState.UNKNOWN
    )
    assert exception_terminal["read_accounting_state"] is (
        FollowUpReadAccountingState.UNKNOWN
    )
    assert exception_terminal["observed_read_count"] is None


def test_known_pre_call_failure_consumes_boundary_but_reports_zero_coinbase_calls():
    exchange = FakeExchange(
        create_result=ExchangeInvocationResult(
            outcome=ExchangeInvocationOutcome.UNKNOWN,
            child_state=ChildExchangeState.UNKNOWN,
            exchange_call_started=False,
        )
    )
    service, repository, _runtime, _exchange = _service(exchange=exchange)

    result = service.materialize(
        source_client_order_id="source-001",
        request=_authorization(),
        context=_context(),
    )

    assert result.record.state == MaterializationRecordState.CREATE_UNKNOWN
    assert result.record.create_call_consumed is True
    assert result.create_call_ran is False
    pre_call_terminal = repository.live_proof_terminal_records[-1]
    assert pre_call_terminal["outcome"] is FollowUpLiveProofTerminalOutcome.BLOCKED
    assert pre_call_terminal["sdk_mutation_invocation_state"] is (
        FollowUpSdkMutationInvocationState.NOT_INVOKED
    )
    assert pre_call_terminal["transport_submission_state"] is (
        FollowUpTransportSubmissionState.NOT_SUBMITTED
    )
    assert pre_call_terminal["exchange_mutation_state"] is (
        FollowUpExchangeMutationState.NOT_MUTATED
    )
    assert pre_call_terminal["read_accounting_state"] is (
        FollowUpReadAccountingState.EXACT
    )
    assert pre_call_terminal["observed_read_count"] == 0


def test_accepted_create_persists_only_normalized_exchange_order_id_hash():
    exchange = FakeExchange(
        create_result=ExchangeInvocationResult(
            outcome=ExchangeInvocationOutcome.ACCEPTED,
            child_state=ChildExchangeState.ACTIVE,
            exchange_call_started=True,
            exchange_order_id_sha256="A" * 64,
            post_mutation_read_started=True,
            post_mutation_read_count=1,
        )
    )
    service, repository, _runtime, _exchange = _service(exchange=exchange)

    service.materialize(
        source_client_order_id="source-001",
        request=_authorization(),
        context=_context(),
    )

    assert repository.last_create_result is not None
    assert repository.last_create_result.exchange_order_id_sha256 == "a" * 64


@pytest.mark.parametrize(
    "unsafe_value",
    ["raw-coinbase-order-id", "z" * 64, "a" * 63],
)
def test_raw_or_invalid_create_exchange_order_id_evidence_is_consumed_unknown(
    unsafe_value,
):
    exchange = FakeExchange(
        create_result=ExchangeInvocationResult(
            outcome=ExchangeInvocationOutcome.ACCEPTED,
            child_state=ChildExchangeState.ACTIVE,
            exchange_call_started=True,
            exchange_order_id_sha256=unsafe_value,
            post_mutation_read_started=True,
            post_mutation_read_count=1,
        )
    )
    service, repository, _runtime, _exchange = _service(exchange=exchange)

    result = service.materialize(
        source_client_order_id="source-001",
        request=_authorization(),
        context=_context(),
    )

    assert repository.last_create_result is not None
    assert result.record.state is MaterializationRecordState.CREATE_UNKNOWN
    assert repository.last_create_result.outcome is ExchangeInvocationOutcome.UNKNOWN
    assert repository.last_create_result.exchange_order_id_sha256 is None
    terminal = repository.live_proof_terminal_records[-1]
    assert terminal["outcome"] is FollowUpLiveProofTerminalOutcome.UNKNOWN


def test_same_create_key_replay_repairs_projection_with_zero_live_or_exchange_calls():
    durable_candidate = _candidate()
    existing = _record(
        state=MaterializationRecordState.CREATE_UNKNOWN,
        create_consumed=True,
        diagnostic_code="follow_up_materialization_create_outcome_unknown",
        durable_candidate=durable_candidate,
    )
    service, repository, runtime, exchange = _service(
        repository=FakeRepository(existing=existing)
    )

    result = service.materialize(
        source_client_order_id="source-001",
        request=_authorization(),
        context=_context(),
    )

    assert result.record == existing
    assert result.replayed is True
    assert result.live_read_ran is False
    assert result.create_call_ran is False
    assert result.eligibility is None
    assert result.candidate is durable_candidate
    assert repository.events == ["read:CREATE"]
    assert runtime.events == []
    assert runtime.projection_events == ["REPLAY_REPAIR"]
    assert exchange.events == []


def test_goal_wide_guard_serializes_inflight_create_and_replay_uses_durable_result():
    entered_exchange = threading.Event()
    release_exchange = threading.Event()
    route_guard = threading.Lock()

    class GuardedRepository(FakeRepository):
        @contextmanager
        def live_proof_invocation_guard(self, *, source_client_order_id: str):
            assert source_client_order_id == "source-001"
            with route_guard:
                yield

    class BlockingExchange(FakeExchange):
        def create_follow_up_child(self, **kwargs):
            entered_exchange.set()
            assert release_exchange.wait(timeout=5)
            return super().create_follow_up_child(**kwargs)

    repository = GuardedRepository()
    exchange = BlockingExchange()
    service, _repository, _runtime, _exchange = _service(
        repository=repository,
        exchange=exchange,
    )
    results: list[MaterializationOperationResult] = []
    failures: list[BaseException] = []

    def invoke() -> None:
        try:
            results.append(
                service.materialize(
                    source_client_order_id="source-001",
                    request=_authorization(),
                    context=_context(),
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    first = threading.Thread(target=invoke)
    second = threading.Thread(target=invoke)
    first.start()
    assert entered_exchange.wait(timeout=5)
    second.start()
    assert second.is_alive()
    assert repository.atomic_events.count("finalize:CREATE:ACCEPTED") == 0

    release_exchange.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert failures == []
    assert len(results) == 2
    assert sorted(result.replayed for result in results) == [False, True]
    assert exchange.events == ["create"]
    assert repository.atomic_events.count("finalize:CREATE:ACCEPTED") == 1


def test_atomic_create_finalize_failure_recovers_unknown_without_recreate():
    class FailOnceAtomicRepository(FakeRepository):
        fail_finalize = True

        def finalize_create_invocation_atomically(self, **kwargs):
            if self.fail_finalize:
                self.fail_finalize = False
                raise RuntimeError("synthetic_atomic_rollback")
            return super().finalize_create_invocation_atomically(**kwargs)

    repository = FailOnceAtomicRepository()
    service, repository, runtime, exchange = _service(repository=repository)

    with pytest.raises(OperatorFollowUpMaterializationError) as exc_info:
        service.materialize(
            source_client_order_id="source-001",
            request=_authorization(),
            context=_context(),
        )

    assert exc_info.value.code == (
        "follow_up_materialization_result_persistence_unavailable"
    )
    assert repository.existing is not None
    assert repository.existing.state is (
        MaterializationRecordState.CREATE_INVOCATION_STARTED
    )
    assert exchange.events == ["create"]
    assert [
        terminal["operation_kind"]
        for terminal in repository.live_proof_terminal_records
    ] == [FollowUpLiveProofOperationKind.ELIGIBILITY_READ]
    replay = service.materialize(
        source_client_order_id="source-001",
        request=_authorization(),
        context=_context(),
    )

    assert replay.replayed is True
    assert replay.record.state == MaterializationRecordState.CREATE_UNKNOWN
    assert runtime.projection_events == []
    assert exchange.events == ["create"]
    create_terminal = repository.live_proof_terminal_records[-1]
    assert create_terminal["operation_kind"] is FollowUpLiveProofOperationKind.CREATE
    assert create_terminal["outcome"] is FollowUpLiveProofTerminalOutcome.UNKNOWN


def test_crash_repair_never_uses_unclaimed_projection_read_or_repeats_create():
    existing = _record(
        state=MaterializationRecordState.CREATE_ACCEPTED,
        create_consumed=True,
        diagnostic_code="follow_up_materialization_create_accepted",
    )
    runtime = FakeRuntime(projection_live_read_count=1)
    service, _repository, runtime, exchange = _service(
        repository=FakeRepository(existing=existing),
        runtime=runtime,
    )

    replay = service.materialize(
        source_client_order_id="source-001",
        request=_authorization(),
        context=_context(),
    )

    assert replay.replayed is True
    assert replay.live_read_ran is False
    assert runtime.projection_events == ["REPLAY_REPAIR"]
    assert exchange.events == []


@pytest.mark.parametrize(
    ("child_evidence", "_expected_projection_operation"),
    (
        pytest.param(
            ChildStateEvidence(
                child_client_order_id="child-001",
                state=ChildExchangeState.ACTIVE,
                fresh=True,
                authoritative=True,
                read_count=1,
                individual_retry_count=0,
                ambiguous=False,
                exchange_order_id_sha256="a" * 64,
                coinbase_read_started=True,
            ),
            "REPLAY_REPAIR",
            id="active",
        ),
        pytest.param(
            ChildStateEvidence(
                child_client_order_id="child-001",
                state=ChildExchangeState.TERMINAL,
                fresh=True,
                authoritative=True,
                read_count=1,
                individual_retry_count=0,
                ambiguous=False,
                exchange_order_id_sha256="b" * 64,
                coinbase_read_started=True,
            ),
            "REPLAY_REPAIR",
            id="terminal",
        ),
        pytest.param(
            ChildStateEvidence(
                child_client_order_id="child-001",
                state=ChildExchangeState.UNKNOWN,
                fresh=True,
                authoritative=False,
                read_count=1,
                individual_retry_count=0,
                ambiguous=False,
                coinbase_read_started=True,
            ),
            "CREATE",
            id="confirmed-absence",
        ),
        pytest.param(
            ChildStateEvidence(
                child_client_order_id="child-001",
                state=ChildExchangeState.UNKNOWN,
                fresh=False,
                authoritative=False,
                read_count=1,
                individual_retry_count=0,
                ambiguous=True,
                coinbase_read_started=True,
            ),
            "CREATE",
            id="ambiguous",
        ),
    ),
)
def test_create_invocation_started_same_key_replay_journals_unknown_without_read(
    child_evidence: ChildStateEvidence,
    _expected_projection_operation: str,
):
    trace: list[str] = []

    class TracingRepository(FakeRepository):
        def record_create_result(self, *, materialization_id: str, result):
            trace.append("journal_create_unknown")
            return super().record_create_result(
                materialization_id=materialization_id,
                result=result,
            )

        def claim_live_proof_operation(self, **kwargs):
            trace.append(f"claim:{kwargs['operation_kind'].value}")
            return super().claim_live_proof_operation(**kwargs)

        def record_live_proof_terminal(self, **kwargs):
            trace.append(f"terminal:{kwargs['operation_kind'].value}")
            return super().record_live_proof_terminal(**kwargs)

        def finalize_create_invocation_atomically(self, **kwargs):
            trace.append("atomic_finalize_create_unknown")
            return super().finalize_create_invocation_atomically(**kwargs)

    class TracingRuntime(FakeRuntime):
        def read_authoritative_child_state(self, **kwargs):
            trace.append("read_exact_child")
            return super().read_authoritative_child_state(**kwargs)

        def project_persisted_child_state(
            self,
            *,
            record,
            operation: str,
            allow_reconciliation_read: bool,
        ):
            trace.append(
                f"project:{operation}:allow_read={allow_reconciliation_read}"
            )
            return super().project_persisted_child_state(
                record=record,
                operation=operation,
                allow_reconciliation_read=allow_reconciliation_read,
            )

    existing = _record(
        state=MaterializationRecordState.CREATE_INVOCATION_STARTED,
        create_consumed=True,
        diagnostic_code="follow_up_materialization_create_outcome_unknown",
        durable_candidate=_candidate(),
    )
    repository = TracingRepository(existing=existing)
    runtime = TracingRuntime(child_state=child_evidence)
    service, repository, runtime, exchange = _service(
        repository=repository,
        runtime=runtime,
    )

    result = service.materialize(
        source_client_order_id="source-001",
        request=_authorization(),
        context=_context(),
    )

    assert result.record.state is MaterializationRecordState.CREATE_UNKNOWN
    assert result.record.create_call_consumed is True
    assert result.replayed is True
    assert result.live_read_ran is False
    assert result.create_call_ran is False
    assert result.cancel_call_ran is False
    assert repository.events == ["read:CREATE"]
    assert runtime.events == []
    assert runtime.projection_events == []
    assert trace == ["atomic_finalize_create_unknown"]
    assert repository.atomic_events == ["finalize:CREATE:UNKNOWN"]
    assert exchange.events == []
    assert repository.last_create_result is not None
    assert (
        repository.last_create_result.operation_idempotency_key_sha256
        == existing.create_idempotency_key_sha256
    )
    assert repository.last_create_result.correlation_id == existing.correlation_id
    assert repository.last_create_result.diagnostic_code == (
        "follow_up_materialization_create_outcome_unknown"
    )
    assert runtime.observed_child_read_binding is None


def test_lost_create_boundary_race_returns_durable_state_without_second_call():
    repository = FakeRepository(create_boundary_claimed=False)
    service, repository, _runtime, exchange = _service(repository=repository)

    result = service.materialize(
        source_client_order_id="source-001",
        request=_authorization(),
        context=_context(),
    )

    assert result.record.state == MaterializationRecordState.CREATE_INVOCATION_STARTED
    assert result.record.create_call_consumed is True
    assert result.replayed is True
    assert result.create_call_ran is False
    assert exchange.events == []


def test_create_boundary_without_goal_claim_recovers_blocked_with_zero_exchange_call():
    existing = _record(
        state=MaterializationRecordState.CREATE_INVOCATION_STARTED,
        create_consumed=True,
        diagnostic_code="follow_up_materialization_create_outcome_unknown",
        durable_candidate=_candidate(),
    )
    repository = FakeRepository(existing=existing)
    repository.claimed_live_proof_operations.clear()
    service, repository, runtime, exchange = _service(repository=repository)

    result = service.materialize(
        source_client_order_id="source-001",
        request=_authorization(),
        context=_context(),
    )

    assert result.record.state is MaterializationRecordState.CREATE_UNKNOWN
    assert result.create_call_ran is False
    assert exchange.events == []
    assert runtime.events == []
    terminal = repository.live_proof_terminal_records[-1]
    assert terminal["operation_kind"] is FollowUpLiveProofOperationKind.CREATE
    assert terminal["outcome"] is FollowUpLiveProofTerminalOutcome.BLOCKED
    assert terminal["external_call_started"] is False
    assert terminal["reported_read_count"] == 0


def test_prepared_same_key_resume_repersist_exact_child_then_crosses_boundary_once():
    prepared = _record()
    repository = FakeRepository(existing=prepared)
    service, repository, runtime, exchange = _service(repository=repository)

    result = service.materialize(
        source_client_order_id="source-001",
        request=_authorization(),
        context=_context(),
    )

    assert result.record.state == MaterializationRecordState.CREATE_ACCEPTED
    assert result.replayed is False
    assert repository.events == ["read:CREATE", "prepare"]
    assert repository.atomic_events == [
        "start:CREATE",
        "finalize:CREATE:ACCEPTED",
    ]
    assert runtime.events == ["eligibility", "persist_child"]
    assert exchange.events == ["create"]


def test_prepared_resume_revalidates_exact_durable_candidate_before_child_or_create():
    class ExactReplayRepository(FakeRepository):
        def prepare_materialization(self, command):
            self.events.append("prepare_exact_replay")
            if command.candidate.limit_price != Decimal("100000"):
                raise RuntimeError("durable_candidate_drift")
            return self.existing

    prepared = _record()
    repository = ExactReplayRepository(existing=prepared)
    drifted_candidate = _candidate(
        limit_price=Decimal("90000"),
        submitted_notional_usdc=Decimal("0.90"),
    )
    runtime = FakeRuntime(eligibility=_eligibility(drifted_candidate))
    service, repository, runtime, exchange = _service(
        repository=repository,
        runtime=runtime,
    )

    with pytest.raises(OperatorFollowUpMaterializationError) as exc_info:
        service.materialize(
            source_client_order_id="source-001",
            request=_authorization(),
            context=_context(),
        )

    assert exc_info.value.code == "follow_up_materialization_backend_unavailable"
    assert repository.events == ["read:CREATE", "prepare_exact_replay"]
    assert runtime.events == ["eligibility"]
    assert exchange.events == []


def test_local_child_persistence_failure_stops_before_boundary_and_exchange():
    class BrokenChildRuntime(FakeRuntime):
        def persist_preclaimed_child(self, *, candidate, materialization_id: str):
            self.events.append("persist_child")
            raise RuntimeError("withheld local detail")

    service, repository, runtime, exchange = _service(runtime=BrokenChildRuntime())

    with pytest.raises(OperatorFollowUpMaterializationError) as exc_info:
        service.materialize(
            source_client_order_id="source-001",
            request=_authorization(),
            context=_context(),
        )

    assert exc_info.value.code == "follow_up_materialization_child_persistence_unavailable"
    assert repository.events == ["read:CREATE", "prepare"]
    assert runtime.events == ["eligibility", "persist_child"]
    assert exchange.events == []


def test_create_result_persistence_failure_reports_consumed_live_boundary():
    class BrokenResultRepository(FakeRepository):
        def finalize_create_invocation_atomically(self, **kwargs):
            self.atomic_events.append(
                f"finalize:CREATE:{kwargs['result'].outcome.value}"
            )
            raise RuntimeError("withheld persistence detail")

    service, repository, runtime, exchange = _service(
        repository=BrokenResultRepository()
    )

    with pytest.raises(OperatorFollowUpMaterializationError) as exc_info:
        service.materialize(
            source_client_order_id="source-001",
            request=_authorization(),
            context=_context(),
        )

    error = exc_info.value
    assert error.code == "follow_up_materialization_result_persistence_unavailable"
    assert error.failure_stage == "create_result_persistence"
    assert error.live_coinbase_read_ran is True
    assert error.live_coinbase_orders_ran is True
    assert error.live_exchange_submitted is True
    assert repository.atomic_events[-1] == "finalize:CREATE:ACCEPTED"
    assert runtime.events == ["eligibility", "persist_child"]
    assert exchange.events == ["create"]


def _accepted_repository(*, cancel_key: str | None = None) -> FakeRepository:
    return FakeRepository(
        existing=_record(
            state=MaterializationRecordState.CREATE_ACCEPTED,
            create_consumed=True,
            diagnostic_code="follow_up_materialization_create_accepted",
            cancel_key=cancel_key,
        )
    )


def _unknown_create_repository() -> FakeRepository:
    return FakeRepository(
        existing=_record(
            state=MaterializationRecordState.CREATE_UNKNOWN,
            create_consumed=True,
            diagnostic_code="follow_up_materialization_create_outcome_unknown",
        )
    )


def _create_invocation_started_repository() -> FakeRepository:
    return FakeRepository(
        existing=_record(
            state=MaterializationRecordState.CREATE_INVOCATION_STARTED,
            create_consumed=True,
            diagnostic_code="follow_up_materialization_create_outcome_unknown",
        )
    )


def test_safe_closeout_terminal_child_uses_one_read_and_zero_cancel_calls():
    repository = _accepted_repository()
    runtime = FakeRuntime(
        child_state=ChildStateEvidence(
            child_client_order_id="child-001",
            state=ChildExchangeState.TERMINAL,
            fresh=True,
            authoritative=True,
            read_count=1,
            individual_retry_count=0,
            ambiguous=False,
            coinbase_read_started=True,
            exchange_order_id_sha256="d" * 64,
        )
    )
    service, repository, runtime, exchange = _service(
        repository=repository,
        runtime=runtime,
    )
    context = _context(
        operator_intent=SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT,
        idempotency_key="cancel-key-001",
    )

    result = service.safe_closeout(
        source_client_order_id="source-001",
        request=_closeout_authorization(),
        context=context,
    )

    assert result.record.state == MaterializationRecordState.CHILD_ALREADY_TERMINAL
    assert result.record.cancel_call_consumed is False
    assert result.diagnostic_code == "follow_up_materialization_child_already_terminal"
    assert result.live_read_ran is True
    assert result.cancel_call_ran is False
    assert runtime.events == ["child_state"]
    assert runtime.projection_events == []
    assert exchange.events == []
    assert "mark_cancel" not in repository.events
    assert repository.events == ["read:CANCEL"]
    assert repository.atomic_events == [
        "finalize:RECONCILIATION:TERMINAL"
    ]
    assert repository.last_terminal_context == {
        "correlation_id": "correlation-001",
        "audit_id": "audit-001",
    }


def test_safe_closeout_marks_boundary_before_one_cancel_and_uses_repository_child():
    repository = _accepted_repository()
    service, repository, runtime, exchange = _service(repository=repository)
    context = _context(
        operator_intent=SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT,
        idempotency_key="cancel-key-001",
    )

    result = service.safe_closeout(
        source_client_order_id="source-001",
        request=_closeout_authorization(),
        context=context,
    )

    assert result.record.state == MaterializationRecordState.CANCEL_ACCEPTED
    assert result.record.cancel_call_consumed is True
    assert result.diagnostic_code == "follow_up_materialization_cancel_accepted"
    assert repository.events == ["read:CANCEL"]
    assert repository.atomic_events == [
        "start:CANCEL",
        "finalize:CANCEL:ACCEPTED",
    ]
    assert runtime.events == ["child_state"]
    assert runtime.projection_events == []
    assert runtime.active_identity_validations == ["materialization-001"]
    assert exchange.events == ["cancel"]
    assert runtime.observed_child_read_binding == {
        "child_client_order_id": "child-001",
        "materialization_id": "materialization-001",
        "operation_audit_id": "audit-001",
        "operation_idempotency_key_sha256": (
            _record(cancel_key="cancel-key-001").cancel_idempotency_key_sha256
        ),
    }
    assert exchange.observed_cancel_binding == {
        "child_client_order_id": "child-001",
        "correlation_id": "correlation-001",
        "materialization_id": "materialization-001",
        "operation_audit_id": "audit-001",
        "operation_idempotency_key_sha256": (
            _record(cancel_key="cancel-key-001").cancel_idempotency_key_sha256
        ),
    }
    assert repository.last_cancel_boundary_context == {
        "idempotency_key": "cancel-key-001",
        "actor_id": "operator-001",
        "roles": ("trader",),
        "environment": "local-controlled-live",
        "operator_intent": SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT,
        "correlation_id": "correlation-001",
        "audit_id": "audit-001",
    }


def test_safe_closeout_uses_only_atomic_cancel_ledger_boundaries():
    class AtomicOnlyRepository(FakeRepository):
        def mark_cancel_invocation_started(self, **_kwargs):
            raise AssertionError("legacy_cancel_start_used")

        def record_cancel_result(self, **_kwargs):
            raise AssertionError("legacy_cancel_result_used")

        def claim_live_proof_operation(self, **kwargs):
            if kwargs["operation_kind"] is FollowUpLiveProofOperationKind.CANCEL:
                raise AssertionError("separate_cancel_goal_claim_used")
            return super().claim_live_proof_operation(**kwargs)

        def record_live_proof_terminal(self, **kwargs):
            if kwargs["operation_kind"] is FollowUpLiveProofOperationKind.CANCEL:
                raise AssertionError("separate_cancel_goal_terminal_used")
            return super().record_live_proof_terminal(**kwargs)

    repository = AtomicOnlyRepository(
        existing=_record(
            state=MaterializationRecordState.CREATE_ACCEPTED,
            create_consumed=True,
            diagnostic_code="follow_up_materialization_create_accepted",
            durable_candidate=_candidate(),
        )
    )
    service, repository, runtime, exchange = _service(repository=repository)

    result = service.safe_closeout(
        source_client_order_id="source-001",
        request=_closeout_authorization(),
        context=_context(
            operator_intent=SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT,
            idempotency_key="cancel-key-001",
        ),
    )

    assert result.record.state is MaterializationRecordState.CANCEL_ACCEPTED
    assert repository.atomic_events == [
        "start:CANCEL",
        "finalize:CANCEL:ACCEPTED",
    ]
    assert "CANCEL" not in runtime.projection_events
    assert exchange.events == ["cancel"]


def test_safe_closeout_claims_exact_reconciliation_and_cancel_before_ports():
    trace: list[str] = []

    class TracingRepository(FakeRepository):
        def claim_live_proof_operation(self, **kwargs):
            trace.append(f"claim:{kwargs['operation_kind'].value}")
            return super().claim_live_proof_operation(**kwargs)

        def record_live_proof_terminal(self, **kwargs):
            trace.append(f"terminal:{kwargs['operation_kind'].value}")
            return super().record_live_proof_terminal(**kwargs)

        def claim_cancel_invocation_started_atomically(self, **kwargs):
            trace.append("atomic_start:CANCEL")
            return super().claim_cancel_invocation_started_atomically(**kwargs)

        def finalize_cancel_invocation_atomically(self, **kwargs):
            trace.append("atomic_finalize:CANCEL")
            return super().finalize_cancel_invocation_atomically(**kwargs)

    class TracingRuntime(FakeRuntime):
        def read_authoritative_child_state(self, **kwargs):
            trace.append("runtime:exact_child")
            return super().read_authoritative_child_state(**kwargs)

    class TracingExchange(FakeExchange):
        def cancel_follow_up_child(self, **kwargs):
            trace.append("exchange:cancel")
            return super().cancel_follow_up_child(**kwargs)

    repository = TracingRepository(existing=_accepted_repository().existing)
    service, repository, _runtime, _exchange = _service(
        repository=repository,
        runtime=TracingRuntime(),
        exchange=TracingExchange(),
    )
    service.safe_closeout(
        source_client_order_id="source-001",
        request=_closeout_authorization(),
        context=_context(
            operator_intent=SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT,
            idempotency_key="cancel-key-001",
        ),
    )

    assert trace == [
        "claim:RECONCILIATION_READ",
        "runtime:exact_child",
        "terminal:RECONCILIATION_READ",
        "atomic_start:CANCEL",
        "exchange:cancel",
        "atomic_finalize:CANCEL",
    ]


def test_safe_closeout_reuses_matching_active_reconciliation_without_second_read():
    from hashlib import sha256

    context = replace(
        _context(
            operator_intent=SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT,
            idempotency_key="cancel-active-reconciliation-replay",
        ),
        audit_id="audit-active-reconciliation-replay",
        correlation_id="correlation-active-reconciliation-replay",
    )
    repository = _accepted_repository()
    operation_hash = sha256(context.idempotency_key.encode()).hexdigest()
    repository.claimed_live_proof_operations.add(
        FollowUpLiveProofOperationKind.RECONCILIATION_READ
    )
    repository.live_proof_claim_bindings[
        FollowUpLiveProofOperationKind.RECONCILIATION_READ
    ] = {
        "correlation_id": context.correlation_id,
        "audit_id": context.audit_id,
        "operation_idempotency_key_sha256": operation_hash,
    }
    repository.live_proof_terminal_records.append(
        {
            "operation_kind": (
                FollowUpLiveProofOperationKind.RECONCILIATION_READ
            ),
            "source_client_order_id": "source-001",
            "outcome": FollowUpLiveProofTerminalOutcome.SUCCEEDED,
            "sdk_mutation_invocation_state": (
                FollowUpSdkMutationInvocationState.NOT_INVOKED
            ),
            "transport_submission_state": (
                FollowUpTransportSubmissionState.NOT_SUBMITTED
            ),
            "exchange_mutation_state": FollowUpExchangeMutationState.NOT_MUTATED,
            "read_accounting_state": FollowUpReadAccountingState.EXACT,
            "observed_read_count": 1,
            "external_call_started": False,
            "reported_read_count": 1,
            "individual_retry_count": 0,
            "authoritative_child_state": ChildExchangeState.ACTIVE,
            "correlation_id": context.correlation_id,
            "audit_id": context.audit_id,
            "operation_idempotency_key_sha256": operation_hash,
        }
    )
    runtime = FakeRuntime()
    service, repository, runtime, exchange = _service(
        repository=repository,
        runtime=runtime,
    )

    result = service.safe_closeout(
        source_client_order_id="source-001",
        request=_closeout_authorization(),
        context=context,
    )

    assert result.record.state is MaterializationRecordState.CANCEL_ACCEPTED
    assert result.live_read_ran is False
    assert runtime.events == []
    assert runtime.active_identity_validations == ["materialization-001"]
    assert exchange.events == ["cancel"]
    assert repository.atomic_events == [
        "start:CANCEL",
        "finalize:CANCEL:ACCEPTED",
    ]
    reconciliation = repository.live_proof_terminal_records[0]
    assert reconciliation["outcome"] is FollowUpLiveProofTerminalOutcome.SUCCEEDED
    assert reconciliation["authoritative_child_state"] is ChildExchangeState.ACTIVE
    assert reconciliation["reported_read_count"] == 1


def test_safe_closeout_exact_read_uses_reconciliation_claim_audit_and_current_key():
    from hashlib import sha256

    repository = _accepted_repository()
    runtime = FakeRuntime()
    service, _repository, runtime, _exchange = _service(
        repository=repository,
        runtime=runtime,
    )
    context = replace(
        _context(
            operator_intent=SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT,
            idempotency_key="cancel-key-distinct-binding",
        ),
        audit_id="audit-closeout-distinct",
        correlation_id="correlation-closeout-distinct",
    )

    service.safe_closeout(
        source_client_order_id="source-001",
        request=_closeout_authorization(),
        context=context,
    )

    assert runtime.observed_child_read_binding == {
        "child_client_order_id": "child-001",
        "materialization_id": "materialization-001",
        "operation_audit_id": context.audit_id,
        "operation_idempotency_key_sha256": sha256(
            context.idempotency_key.encode()
        ).hexdigest(),
    }


def test_create_crash_preserves_fresh_reconciliation_for_later_exact_child_cancel():
    repository = _create_invocation_started_repository()
    runtime = FakeRuntime()
    exchange = FakeExchange()
    service, repository, runtime, exchange = _service(
        repository=repository,
        runtime=runtime,
        exchange=exchange,
    )

    recovered = service.materialize(
        source_client_order_id="source-001",
        request=_authorization(),
        context=_context(),
    )
    closeout = service.safe_closeout(
        source_client_order_id="source-001",
        request=_closeout_authorization(),
        context=replace(
            _context(
                operator_intent=SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT,
                idempotency_key="cancel-after-create-crash-reconciliation",
            ),
            audit_id="audit-closeout-after-crash",
            correlation_id="correlation-closeout-after-crash",
        ),
    )

    assert recovered.record.state is MaterializationRecordState.CREATE_UNKNOWN
    assert recovered.live_read_ran is False
    assert closeout.record.state is MaterializationRecordState.CANCEL_ACCEPTED
    assert closeout.live_read_ran is True
    assert closeout.cancel_call_ran is True
    assert runtime.events == ["child_state"]
    assert exchange.events == ["cancel"]
    assert repository.live_proof_events.count("claim:RECONCILIATION_READ") == 1
    assert repository.atomic_events.count("start:CANCEL") == 1


def test_unknown_create_can_use_separate_cancel_allowance_after_exact_active_read():
    repository = _unknown_create_repository()
    service, repository, runtime, exchange = _service(repository=repository)

    result = service.safe_closeout(
        source_client_order_id="source-001",
        request=_closeout_authorization(),
        context=_context(
            operator_intent=SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT,
            idempotency_key="cancel-key-after-unknown-create",
        ),
    )

    assert result.record.state == MaterializationRecordState.CANCEL_ACCEPTED
    assert result.record.create_call_consumed is True
    assert result.record.cancel_call_consumed is True
    assert repository.events == ["read:CANCEL"]
    assert repository.atomic_events == [
        "finalize:RECONCILIATION:ACTIVE",
        "start:CANCEL",
        "finalize:CANCEL:ACCEPTED",
    ]
    assert runtime.events == ["child_state"]
    assert exchange.events == ["cancel"]


def test_unclassified_create_boundary_can_close_exact_active_child_without_recreate():
    repository = _create_invocation_started_repository()
    service, repository, runtime, exchange = _service(repository=repository)

    result = service.safe_closeout(
        source_client_order_id="source-001",
        request=_closeout_authorization(),
        context=_context(
            operator_intent=SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT,
            idempotency_key="cancel-after-unclassified-create",
        ),
    )

    assert result.record.state == MaterializationRecordState.CANCEL_ACCEPTED
    assert result.record.create_call_consumed is True
    assert result.record.cancel_call_consumed is True
    assert repository.events == ["read:CANCEL"]
    assert repository.atomic_events == [
        "finalize:CREATE:UNKNOWN",
        "finalize:RECONCILIATION:ACTIVE",
        "start:CANCEL",
        "finalize:CANCEL:ACCEPTED",
    ]
    assert runtime.events == ["child_state"]
    assert exchange.events == ["cancel"]


def test_unclassified_create_boundary_terminal_child_uses_no_cancel():
    repository = _create_invocation_started_repository()
    runtime = FakeRuntime(
        child_state=ChildStateEvidence(
            child_client_order_id="child-001",
            state=ChildExchangeState.TERMINAL,
            fresh=True,
            authoritative=True,
            read_count=1,
            individual_retry_count=0,
            ambiguous=False,
            coinbase_read_started=True,
            exchange_order_id_sha256="e" * 64,
        )
    )
    service, repository, _runtime, exchange = _service(
        repository=repository,
        runtime=runtime,
    )

    result = service.safe_closeout(
        source_client_order_id="source-001",
        request=_closeout_authorization(),
        context=_context(
            operator_intent=SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT,
            idempotency_key="terminal-after-unclassified-create",
        ),
    )

    assert result.record.state == MaterializationRecordState.CHILD_ALREADY_TERMINAL
    assert result.cancel_call_ran is False
    assert repository.events == ["read:CANCEL"]
    assert repository.atomic_events == [
        "finalize:CREATE:UNKNOWN",
        "finalize:RECONCILIATION:TERMINAL",
    ]
    assert exchange.events == []


def test_unknown_create_terminal_exact_read_consumes_no_cancel_allowance():
    repository = _unknown_create_repository()
    runtime = FakeRuntime(
        child_state=ChildStateEvidence(
            child_client_order_id="child-001",
            state=ChildExchangeState.TERMINAL,
            fresh=True,
            authoritative=True,
            read_count=1,
            individual_retry_count=0,
            ambiguous=False,
            coinbase_read_started=True,
            exchange_order_id_sha256="d" * 64,
        )
    )
    service, repository, runtime, exchange = _service(
        repository=repository,
        runtime=runtime,
    )

    result = service.safe_closeout(
        source_client_order_id="source-001",
        request=_closeout_authorization(),
        context=_context(
            operator_intent=SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT,
            idempotency_key="terminal-read-after-unknown-create",
        ),
    )

    assert result.record.state == MaterializationRecordState.CHILD_ALREADY_TERMINAL
    assert result.record.create_call_consumed is True
    assert result.record.cancel_call_consumed is False
    assert repository.events == ["read:CANCEL"]
    assert repository.atomic_events == [
        "finalize:RECONCILIATION:TERMINAL"
    ]
    assert runtime.events == ["child_state"]
    assert exchange.events == []


def test_safe_closeout_accepts_exact_route_pydantic_acknowledgement_body():
    repository = _accepted_repository()
    service, _repository, _runtime, exchange = _service(repository=repository)

    result = service.safe_closeout(
        source_client_order_id="source-001",
        request=AdminOrderFollowUpMaterializationCancelRequest(
            authorize_single_cancel_for_safe_closeout=True,
            acknowledge_unknown_outcome_consumes_cancel_allowance=True,
        ),
        context=_context(
            operator_intent=SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT,
            idempotency_key="cancel-key-001",
        ),
    )

    assert result.record.state == MaterializationRecordState.CANCEL_ACCEPTED
    assert exchange.events == ["cancel"]


def test_cancel_exception_is_unknown_consumed_and_never_retried():
    repository = _accepted_repository()
    exchange = FakeExchange(cancel_exception=RuntimeError("withheld cancel detail"))
    service, repository, _runtime, exchange = _service(
        repository=repository,
        exchange=exchange,
    )
    context = _context(
        operator_intent=SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT,
        idempotency_key="cancel-key-001",
    )

    result = service.safe_closeout(
        source_client_order_id="source-001",
        request=_closeout_authorization(),
        context=context,
    )

    assert result.record.state == MaterializationRecordState.CANCEL_UNKNOWN
    assert result.record.cancel_call_consumed is True
    assert result.diagnostic_code == "follow_up_materialization_cancel_outcome_unknown"
    assert "withheld" not in repr(result)
    assert exchange.events == ["cancel"]
    assert repository.atomic_events[-1] == "finalize:CANCEL:UNKNOWN"


@pytest.mark.parametrize(
    ("post_read_started", "post_read_count", "retry_count"),
    (
        pytest.param(False, 0, 0, id="accepted-without-post-cancel-read"),
        pytest.param(True, 1, 1, id="retry-observed"),
        pytest.param(True, 2, 0, id="too-many-post-cancel-reads"),
        pytest.param(False, 1, 0, id="read-count-without-start"),
    ),
)
def test_cancel_accounting_violation_is_consumed_unknown_and_never_clean_success(
    post_read_started: bool,
    post_read_count: int,
    retry_count: int,
):
    repository = _accepted_repository()
    exchange = FakeExchange(
        cancel_result=ExchangeInvocationResult(
            outcome=ExchangeInvocationOutcome.ACCEPTED,
            child_state=ChildExchangeState.TERMINAL,
            exchange_call_started=True,
            exchange_order_id_sha256="b" * 64,
            post_mutation_read_started=post_read_started,
            post_mutation_read_count=post_read_count,
            individual_retry_count=retry_count,
        )
    )
    service, repository, _runtime, exchange = _service(
        repository=repository,
        exchange=exchange,
    )

    if retry_count:
        with pytest.raises(OperatorFollowUpMaterializationError) as rejected_retry:
            service.safe_closeout(
                source_client_order_id="source-001",
                request=_closeout_authorization(),
                context=_context(
                    operator_intent=(
                        SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT
                    ),
                    idempotency_key="cancel-key-accounting-violation",
                ),
            )
        assert rejected_retry.value.code == (
            "follow_up_materialization_result_persistence_unavailable"
        )
        assert exchange.events == ["cancel"]
        return

    result = service.safe_closeout(
        source_client_order_id="source-001",
        request=_closeout_authorization(),
        context=_context(
            operator_intent=SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT,
            idempotency_key="cancel-key-accounting-violation",
        ),
    )

    assert result.record.state is MaterializationRecordState.CANCEL_UNKNOWN
    assert result.record.cancel_call_consumed is True
    assert result.cancel_call_ran is False
    assert exchange.events == ["cancel"]
    assert repository.last_cancel_result is not None
    assert repository.last_cancel_result.outcome is ExchangeInvocationOutcome.UNKNOWN
    terminal = repository.live_proof_terminal_records[-1]
    assert terminal["operation_kind"] is FollowUpLiveProofOperationKind.CANCEL
    assert terminal["outcome"] is FollowUpLiveProofTerminalOutcome.UNKNOWN
    assert terminal["sdk_mutation_invocation_state"] is (
        FollowUpSdkMutationInvocationState.UNKNOWN
    )
    assert terminal["transport_submission_state"] is (
        FollowUpTransportSubmissionState.POSSIBLY_SUBMITTED
    )
    assert terminal["exchange_mutation_state"] is (
        FollowUpExchangeMutationState.UNKNOWN
    )
    assert terminal["read_accounting_state"] is FollowUpReadAccountingState.UNKNOWN
    assert terminal["observed_read_count"] is None
    assert terminal["reported_read_count"] == 0
    assert terminal["individual_retry_count"] == 0


@pytest.mark.parametrize(
    ("child_state", "exchange_hash"),
    (
        pytest.param(ChildExchangeState.ACTIVE, "b" * 64, id="active-child"),
        pytest.param(ChildExchangeState.TERMINAL, None, id="missing-exchange-hash"),
        pytest.param(ChildExchangeState.TERMINAL, "z" * 64, id="invalid-exchange-hash"),
    ),
)
def test_cancel_accepted_without_terminal_hashed_identity_is_consumed_unknown(
    child_state: ChildExchangeState,
    exchange_hash: str | None,
):
    repository = _accepted_repository()
    exchange = FakeExchange(
        cancel_result=ExchangeInvocationResult(
            outcome=ExchangeInvocationOutcome.ACCEPTED,
            child_state=child_state,
            exchange_call_started=True,
            exchange_order_id_sha256=exchange_hash,
            post_mutation_read_started=True,
            post_mutation_read_count=1,
            individual_retry_count=0,
        )
    )
    service, repository, _runtime, exchange = _service(
        repository=repository,
        exchange=exchange,
    )

    result = service.safe_closeout(
        source_client_order_id="source-001",
        request=_closeout_authorization(),
        context=_context(
            operator_intent=SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT,
            idempotency_key="cancel-key-invalid-accepted-evidence",
        ),
    )

    assert result.record.state is MaterializationRecordState.CANCEL_UNKNOWN
    assert result.record.cancel_call_consumed is True
    assert exchange.events == ["cancel"]
    assert repository.last_cancel_result is not None
    assert repository.last_cancel_result.outcome is ExchangeInvocationOutcome.UNKNOWN
    assert repository.last_cancel_result.exchange_order_id_sha256 is None
    terminal = repository.live_proof_terminal_records[-1]
    assert terminal["operation_kind"] is FollowUpLiveProofOperationKind.CANCEL
    assert terminal["outcome"] is FollowUpLiveProofTerminalOutcome.UNKNOWN


def test_cancel_result_persistence_failure_reports_consumed_live_boundary():
    class BrokenResultRepository(FakeRepository):
        def finalize_cancel_invocation_atomically(self, **kwargs):
            self.atomic_events.append(
                f"finalize:CANCEL:{kwargs['result'].outcome.value}"
            )
            raise RuntimeError("withheld persistence detail")

    repository = BrokenResultRepository(existing=_accepted_repository().existing)
    service, repository, runtime, exchange = _service(repository=repository)

    with pytest.raises(OperatorFollowUpMaterializationError) as exc_info:
        service.safe_closeout(
            source_client_order_id="source-001",
            request=_closeout_authorization(),
            context=_context(
                operator_intent=SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT,
                idempotency_key="cancel-key-001",
            ),
        )

    error = exc_info.value
    assert error.code == "follow_up_materialization_result_persistence_unavailable"
    assert error.failure_stage == "cancel_result_persistence"
    assert error.live_coinbase_read_ran is True
    assert error.live_coinbase_orders_ran is True
    assert error.live_exchange_submitted is True
    assert repository.atomic_events[-1] == "finalize:CANCEL:ACCEPTED"
    assert runtime.events == ["child_state"]
    assert exchange.events == ["cancel"]


def test_accepted_cancel_persists_only_valid_exchange_order_id_hash():
    repository = _accepted_repository()
    exchange = FakeExchange(
        cancel_result=ExchangeInvocationResult(
            outcome=ExchangeInvocationOutcome.ACCEPTED,
            child_state=ChildExchangeState.TERMINAL,
            exchange_call_started=True,
            exchange_order_id_sha256="b" * 64,
            post_mutation_read_started=True,
            post_mutation_read_count=1,
        )
    )
    service, repository, _runtime, _exchange = _service(
        repository=repository,
        exchange=exchange,
    )

    service.safe_closeout(
        source_client_order_id="source-001",
        request=_closeout_authorization(),
        context=_context(
            operator_intent=SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT,
            idempotency_key="cancel-key-001",
        ),
    )

    assert repository.last_cancel_result is not None
    assert repository.last_cancel_result.exchange_order_id_sha256 == "b" * 64


def test_cancel_replay_and_boundary_race_never_issue_a_second_cancel():
    cancel_key = "cancel-key-001"
    replay_record = replace(
        _record(
            state=MaterializationRecordState.CANCEL_UNKNOWN,
            create_consumed=True,
            cancel_consumed=True,
            diagnostic_code="follow_up_materialization_cancel_outcome_unknown",
            cancel_key=cancel_key,
        ),
        child_state=ChildExchangeState.ACTIVE,
    )
    service, repository, runtime, exchange = _service(
        repository=FakeRepository(existing=replay_record)
    )
    context = _context(
        operator_intent=SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT,
        idempotency_key=cancel_key,
    )

    result = service.safe_closeout(
        source_client_order_id="source-001",
        request=_closeout_authorization(),
        context=context,
    )

    assert result.replayed is True
    assert result.cancel_call_ran is False
    assert repository.events == ["read:CANCEL"]
    assert runtime.events == []
    assert exchange.events == []


@pytest.mark.parametrize(
    ("child_evidence", "_expected_projection_operation"),
    (
        pytest.param(
            ChildStateEvidence(
                child_client_order_id="child-001",
                state=ChildExchangeState.ACTIVE,
                fresh=True,
                authoritative=True,
                read_count=1,
                individual_retry_count=0,
                ambiguous=False,
                exchange_order_id_sha256="c" * 64,
                coinbase_read_started=True,
            ),
            "REPLAY_REPAIR",
            id="active",
        ),
        pytest.param(
            ChildStateEvidence(
                child_client_order_id="child-001",
                state=ChildExchangeState.TERMINAL,
                fresh=True,
                authoritative=True,
                read_count=1,
                individual_retry_count=0,
                ambiguous=False,
                exchange_order_id_sha256="d" * 64,
                coinbase_read_started=True,
            ),
            "REPLAY_REPAIR",
            id="terminal",
        ),
        pytest.param(
            ChildStateEvidence(
                child_client_order_id="child-001",
                state=ChildExchangeState.UNKNOWN,
                fresh=True,
                authoritative=False,
                read_count=1,
                individual_retry_count=0,
                ambiguous=False,
                coinbase_read_started=True,
            ),
            "CANCEL",
            id="confirmed-absence",
        ),
        pytest.param(
            ChildStateEvidence(
                child_client_order_id="child-001",
                state=ChildExchangeState.UNKNOWN,
                fresh=False,
                authoritative=False,
                read_count=1,
                individual_retry_count=0,
                ambiguous=True,
                coinbase_read_started=True,
            ),
            "CANCEL",
            id="ambiguous",
        ),
    ),
)
def test_cancel_invocation_started_same_key_replay_journals_unknown_without_read(
    child_evidence: ChildStateEvidence,
    _expected_projection_operation: str,
):
    trace: list[str] = []

    class TracingRepository(FakeRepository):
        def record_cancel_result(self, *, materialization_id: str, result):
            trace.append("journal_cancel_unknown")
            return super().record_cancel_result(
                materialization_id=materialization_id,
                result=result,
            )

        def finalize_cancel_invocation_atomically(self, **kwargs):
            trace.append("atomic_finalize_cancel_unknown")
            return super().finalize_cancel_invocation_atomically(**kwargs)

    class TracingRuntime(FakeRuntime):
        def read_authoritative_child_state(self, **kwargs):
            trace.append("read_exact_child")
            return super().read_authoritative_child_state(**kwargs)

        def project_persisted_child_state(
            self,
            *,
            record,
            operation: str,
            allow_reconciliation_read: bool,
        ):
            trace.append(
                f"project:{operation}:allow_read={allow_reconciliation_read}"
            )
            return super().project_persisted_child_state(
                record=record,
                operation=operation,
                allow_reconciliation_read=allow_reconciliation_read,
            )

    cancel_key = "cancel-key-crash-recovery"
    existing = _record(
        state=MaterializationRecordState.CANCEL_INVOCATION_STARTED,
        create_consumed=True,
        cancel_consumed=True,
        diagnostic_code="follow_up_materialization_cancel_outcome_unknown",
        cancel_key=cancel_key,
        durable_candidate=_candidate(),
    )
    repository = TracingRepository(existing=existing)
    runtime = TracingRuntime(child_state=child_evidence)
    service, repository, runtime, exchange = _service(
        repository=repository,
        runtime=runtime,
    )

    result = service.safe_closeout(
        source_client_order_id="source-001",
        request=_closeout_authorization(),
        context=replace(
            _context(
                operator_intent=SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT,
                idempotency_key=cancel_key,
            ),
            correlation_id="correlation-001",
        ),
    )

    assert result.record.state is MaterializationRecordState.CANCEL_UNKNOWN
    assert result.record.create_call_consumed is True
    assert result.record.cancel_call_consumed is True
    assert result.replayed is True
    assert result.live_read_ran is False
    assert result.create_call_ran is False
    assert result.cancel_call_ran is False
    assert repository.events == ["read:CANCEL"]
    assert runtime.events == []
    assert runtime.projection_events == []
    assert trace == ["atomic_finalize_cancel_unknown"]
    assert repository.atomic_events == ["finalize:CANCEL:UNKNOWN"]
    assert exchange.events == []
    assert repository.last_cancel_result is not None
    assert (
        repository.last_cancel_result.operation_idempotency_key_sha256
        == existing.cancel_idempotency_key_sha256
    )
    assert repository.last_cancel_result.correlation_id == existing.correlation_id
    assert repository.last_cancel_result.diagnostic_code == (
        "follow_up_materialization_cancel_outcome_unknown"
    )
    assert runtime.observed_child_read_binding is None


def test_ambiguous_child_state_fails_closed_before_cancel_boundary():
    repository = _accepted_repository()
    runtime = FakeRuntime(
        child_state=ChildStateEvidence(
            child_client_order_id="child-001",
            state=ChildExchangeState.UNKNOWN,
            fresh=True,
            authoritative=False,
            read_count=1,
            individual_retry_count=0,
            ambiguous=True,
            coinbase_read_started=True,
        )
    )
    service, repository, runtime, exchange = _service(
        repository=repository,
        runtime=runtime,
    )

    with pytest.raises(OperatorFollowUpMaterializationError) as exc_info:
        service.safe_closeout(
            source_client_order_id="source-001",
            request=_closeout_authorization(),
            context=_context(
                operator_intent=SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT,
                idempotency_key="cancel-key-001",
            ),
        )

    assert exc_info.value.code == "follow_up_materialization_child_state_ambiguous"
    assert exc_info.value.failure_stage == "safe_closeout_after_live_read"
    assert exc_info.value.live_coinbase_read_ran is True
    assert exc_info.value.live_coinbase_orders_ran is False
    assert exc_info.value.live_exchange_submitted is False
    assert repository.events == ["read:CANCEL"]
    assert runtime.events == ["child_state"]
    assert exchange.events == []


def test_child_read_without_a_coinbase_call_fails_before_cancel_boundary():
    repository = _accepted_repository()
    runtime = FakeRuntime(
        child_state=ChildStateEvidence(
            child_client_order_id="child-001",
            state=ChildExchangeState.ACTIVE,
            fresh=True,
            authoritative=True,
            read_count=1,
            individual_retry_count=0,
            ambiguous=False,
            coinbase_read_started=False,
        )
    )
    service, repository, _runtime, exchange = _service(
        repository=repository,
        runtime=runtime,
    )

    with pytest.raises(OperatorFollowUpMaterializationError) as exc_info:
        service.safe_closeout(
            source_client_order_id="source-001",
            request=_closeout_authorization(),
            context=_context(
                operator_intent=SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT,
                idempotency_key="cancel-key-001",
            ),
        )

    assert exc_info.value.code == (
        "follow_up_materialization_child_live_read_required"
    )
    assert repository.events == ["read:CANCEL"]
    assert exchange.events == []
