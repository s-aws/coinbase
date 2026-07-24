"""Focused production-runtime tests for operator follow-up materialization.

Every Coinbase-facing dependency is synthetic.  The tests assert call counts
and fixed classifications; they never construct a real client or make a
network call.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from decimal import Decimal
import hashlib
from types import SimpleNamespace

import pytest

from application.admin_api.operator_follow_up_materialization import (
    BackendMaterializationCandidate,
    ChildExchangeState,
    ChildStateEvidence,
    ExchangeInvocationOutcome,
    FollowUpMaterializationRecord,
    MaterializationOperationResult,
    MaterializationReadResult,
    MaterializationRecordState,
    FreshMaterializationEligibility,
    LiveProofOperationClaim,
    MutationInvocationAccounting,
    OperatorFollowUpMaterializationError,
    PersistedInvocationResult,
)
from application.admin_api.operator_follow_up_materialization_runtime import (
    CanonicalFollowUpMaterializationExchange,
    NativeFollowUpMaterializationRepositoryAdapter,
    OperatorFollowUpMaterializationFacade,
    ProductionFollowUpMaterializationRuntime,
    _PendingRawExchangeEvidence,
    _configured_admin_environment,
    _pending_evidence_key,
    _single_page_materialization_order_readback,
)
from application.admin_api.spot_portfolio_binding import (
    evaluate_spot_test_portfolio_binding,
)
from core.coinbase_execution_authority import CoinbaseExecutionAuthorityError
from core.enums import (
    AdminApiCommandStatus,
    FollowUpExchangeMutationState,
    FollowUpLiveProofOperationKind,
    FollowUpLiveProofTerminalOutcome,
    FollowUpReadAccountingState,
    FollowUpSdkMutationInvocationState,
    FollowUpTransportSubmissionState,
)


SOURCE_ID = "d24c9fc3-29c2-4e76-87d7-3d27cb94530f"
ROOT_ID = "87aa9a2d-b015-4701-b7e5-63cc26360ad2"
CHILD_ID = "72a77ad1-386a-5aad-a4fb-feb575b87a5c"
INTENT_ID = "0ec90842-d875-4a7b-9eb1-333c7d618bb1"
MATERIALIZATION_ID = "4f7d2e1f-96b4-43af-9901-f217879a4ac5"
AUDIT_ID = "1f418e77-9e5e-49f3-861e-a30f942f38fb"
CORRELATION_ID = "b80fe761-69e6-462b-9ccb-b40ed93b2ac7"
IDEMPOTENCY_KEY = "98296253-d0b8-44ca-8701-8c17ca99d397"
PORTFOLIO_ID = "10732555-2b9d-4a62-993d-c738fe719d3b"
EXCHANGE_ID = "86af4462-36dc-4e74-b8fc-f9be1e8f1000"
SHA = hashlib.sha256(IDEMPOTENCY_KEY.encode()).hexdigest()


def _mutation_accounting(
    outcome: ExchangeInvocationOutcome,
) -> MutationInvocationAccounting:
    if outcome is ExchangeInvocationOutcome.ACCEPTED:
        return MutationInvocationAccounting(
            sdk_mutation_invocation_state=FollowUpSdkMutationInvocationState.INVOKED,
            transport_submission_state=(
                FollowUpTransportSubmissionState.CONFIRMED_SUBMITTED
            ),
            exchange_mutation_state=(
                FollowUpExchangeMutationState.CONFIRMED_MUTATED
            ),
            read_accounting_state=FollowUpReadAccountingState.EXACT,
            observed_read_count=1,
            individual_retry_count=0,
            policy_clean=True,
        )
    return MutationInvocationAccounting(
        sdk_mutation_invocation_state=FollowUpSdkMutationInvocationState.INVOKED,
        transport_submission_state=(
            FollowUpTransportSubmissionState.POSSIBLY_SUBMITTED
        ),
        exchange_mutation_state=FollowUpExchangeMutationState.UNKNOWN,
        read_accounting_state=FollowUpReadAccountingState.UNKNOWN,
        observed_read_count=None,
        individual_retry_count=0,
        policy_clean=True,
    )


def _assert_invocation_activity(
    result: object,
    *,
    sdk: FollowUpSdkMutationInvocationState,
    transport: FollowUpTransportSubmissionState,
    exchange: FollowUpExchangeMutationState,
    read: FollowUpReadAccountingState,
    count: int | None,
) -> None:
    assert result.sdk_mutation_invocation_state is sdk
    assert result.transport_submission_state is transport
    assert result.exchange_mutation_state is exchange
    assert result.read_accounting_state is read
    assert result.observed_read_count == count


def test_environment_fallback_matches_backend_authenticated_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COINBASE_ADMIN_API_ENVIRONMENT", raising=False)
    monkeypatch.setenv("COINBASE_BACKEND_DEPLOYMENT_TIER", "test-tier")
    assert _configured_admin_environment() == "test-tier"
    monkeypatch.setenv("COINBASE_ADMIN_API_ENVIRONMENT", "controlled-live")
    assert _configured_admin_environment() == "controlled-live"
    monkeypatch.delenv("COINBASE_ADMIN_API_ENVIRONMENT", raising=False)
    monkeypatch.delenv("COINBASE_BACKEND_DEPLOYMENT_TIER", raising=False)
    assert _configured_admin_environment() == "local"


def _readiness(*, blockers: tuple[str, ...] = ()) -> SimpleNamespace:
    return SimpleNamespace(
        source_client_order_id=SOURCE_ID,
        root_client_order_id=ROOT_ID,
        follow_up_intent_id=INTENT_ID,
        deterministic_child_client_order_id=CHILD_ID,
        eligible=not blockers,
        eligibility_status="eligible" if not blockers else "blocked",
        blockers=blockers,
        source_status="FILLED",
        source_ownership_provenance="ADMIN_MANUAL_ROOT",
        product_id="BTC-USDC",
        source_side="BUY",
        derived_follow_up_side="SELL",
        base_size="0.00001",
        full_fill_consistent=True,
        flat_lineage_valid=True,
        child_absent=True,
        conflicting_claim_absent=True,
        portfolio_scope_sha256=hashlib.sha256(PORTFOLIO_ID.encode()).hexdigest(),
    )


def _native_attempt(
    *,
    state: str = "KNOWN_NOT_INVOKED",
    diagnostic: str = "known_not_invoked",
    exchange_hash: str | None = None,
    operation_hash: str | None = None,
    operation_audit_id: str | None = None,
    operation_actor_id: str | None = None,
    operation_roles: tuple[str, ...] = (),
    operation_environment: str | None = None,
    operation_intent: str | None = None,
    operation_correlation_id: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        materialization_id=MATERIALIZATION_ID,
        audit_id=AUDIT_ID,
        follow_up_intent_id=INTENT_ID,
        source_client_order_id=SOURCE_ID,
        root_client_order_id=ROOT_ID,
        child_client_order_id=CHILD_ID,
        product_id="BTC-USDC",
        child_side="SELL",
        base_size="0.00001",
        limit_price="100000.00",
        portfolio_scope_sha256=hashlib.sha256(PORTFOLIO_ID.encode()).hexdigest(),
        idempotency_key=IDEMPOTENCY_KEY,
        payload_sha256="a" * 64,
        actor_id="operator",
        roles=("trader",),
        environment="controlled_live",
        correlation_id=CORRELATION_ID,
        operator_intent="authorize_and_materialize_follow_up_intent",
        prepared_at="2026-07-18T12:00:00+00:00",
        current_state=state,
        current_diagnostic_code=diagnostic,
        exchange_order_id_sha256=exchange_hash,
        operation_idempotency_key_sha256=operation_hash,
        current_operation_audit_id=operation_audit_id,
        current_operation_actor_id=operation_actor_id,
        current_operation_roles=operation_roles,
        current_operation_environment=operation_environment,
        current_operation_intent=operation_intent,
        current_operation_correlation_id=operation_correlation_id,
        state_recorded_at="2026-07-18T12:00:01+00:00",
    )


class _NativeRepository:
    def __init__(
        self,
        attempt: SimpleNamespace | None = None,
        *,
        readiness_blockers: tuple[str, ...] = (),
    ) -> None:
        self.attempt = attempt
        self.readiness_blockers = readiness_blockers
        self.calls: list[tuple[str, object]] = []
        self.audit_events: list[SimpleNamespace] = []
        self.local_projection: SimpleNamespace | None = None
        self.live_proof_records: dict[str, SimpleNamespace] = {}
        if attempt is not None:
            operation_audit_id = (
                getattr(attempt, "current_operation_audit_id", None)
                or attempt.audit_id
            )
            self.audit_events = [
                SimpleNamespace(
                    event_id="8d0857f8-45b3-453f-8498-b5d850910770",
                    materialization_id=attempt.materialization_id,
                    state=attempt.current_state,
                    diagnostic_code=attempt.current_diagnostic_code,
                    exchange_order_id_sha256=(
                        attempt.exchange_order_id_sha256
                    ),
                    operation_audit_id=operation_audit_id,
                    actor_id="private-operator-id",
                    roles=("trader",),
                    environment=attempt.environment,
                    operator_intent=attempt.operator_intent,
                    correlation_id=attempt.correlation_id,
                    recorded_at=attempt.state_recorded_at,
                )
            ]
            if attempt.exchange_order_id_sha256:
                self.local_projection = SimpleNamespace(
                    local_state_event_id=(
                        "ad532b0f-15d6-49c7-8a73-63550ef6fe85"
                    ),
                    materialization_id=attempt.materialization_id,
                    child_client_order_id=attempt.child_client_order_id,
                    transition_kind="CREATE_ACCEPTED_ACTIVE",
                    authoritative_order_status="OPEN",
                    exchange_order_id_sha256=(
                        attempt.exchange_order_id_sha256
                    ),
                    operation_audit_id=operation_audit_id,
                    recorded_at=attempt.state_recorded_at,
                )
            self.live_proof_records["ELIGIBILITY_READ"] = self._live_proof(
                "ELIGIBILITY_READ",
                event_state="TERMINAL",
                outcome="SUCCEEDED",
                observed_read_count=1,
            )
            state = str(attempt.current_state)
            if state.startswith("CREATE_"):
                create_outcome = (
                    "SUCCEEDED"
                    if state.startswith("CREATE_ACCEPTED")
                    else "REJECTED"
                    if state == "CREATE_EXPLICITLY_REJECTED"
                    else "UNKNOWN"
                )
                self.live_proof_records["CREATE"] = self._live_proof(
                    "CREATE",
                    event_state=(
                        "INVOCATION_STARTED"
                        if state == "CREATE_INVOCATION_STARTED"
                        else "TERMINAL"
                    ),
                    outcome=(
                        None
                        if state == "CREATE_INVOCATION_STARTED"
                        else create_outcome
                    ),
                    observed_read_count=(
                        1 if create_outcome == "SUCCEEDED" else 0
                    ),
                )

    def read_materialization(self, source_client_order_id: str):
        self.calls.append(("read", source_client_order_id))
        blockers = tuple(
            dict.fromkeys(
                (
                    *(
                        ("follow_up_materialization_already_prepared",)
                        if self.attempt is not None
                        else ()
                    ),
                    *self.readiness_blockers,
                )
            )
        )
        return SimpleNamespace(
            readiness=_readiness(blockers=blockers),
            attempt=self.attempt,
        )

    def list_materialization_events(self, materialization_id: str):
        self.calls.append(("events", materialization_id))
        return tuple(self.audit_events)

    def read_latest_materialized_child_local_state(
        self, materialization_id: str
    ):
        self.calls.append(("projection", materialization_id))
        return self.local_projection

    def read_follow_up_live_proof_operation_set(
        self,
        *,
        goal_id: str,
        source_client_order_id: str,
    ):
        self.calls.append(("activity", source_client_order_id))
        assert goal_id == "operator_follow_up_operations_queue_and_single_live_proof"
        return SimpleNamespace(
            eligibility_read=self.live_proof_records.get("ELIGIBILITY_READ"),
            create=self.live_proof_records.get("CREATE"),
            reconciliation_read=self.live_proof_records.get(
                "RECONCILIATION_READ"
            ),
            cancel=self.live_proof_records.get("CANCEL"),
        )

    def prepare_materialization(self, command):
        self.calls.append(("prepare", command))
        self.attempt = _native_attempt()
        return SimpleNamespace(
            readiness=_readiness(), attempt=self.attempt, replayed=False
        )

    def mark_create_invocation_started(self, materialization_id: str):
        self.calls.append(("create_start", materialization_id))
        self.attempt = _native_attempt(
            state="CREATE_INVOCATION_STARTED",
            diagnostic="create_invocation_started",
        )
        return SimpleNamespace(
            attempt=self.attempt, event=SimpleNamespace(), replayed=False
        )

    def record_create_result(self, materialization_id: str, **kwargs):
        self.calls.append(("create_result", kwargs))
        self.attempt = _native_attempt(
            state=kwargs["outcome"],
            diagnostic=kwargs["diagnostic_code"],
            exchange_hash=kwargs.get("exchange_order_id_sha256"),
        )
        return SimpleNamespace(
            attempt=self.attempt, event=SimpleNamespace(), replayed=False
        )

    def mark_cancel_invocation_started(self, materialization_id: str, **kwargs):
        self.calls.append(("cancel_start", kwargs))
        self.attempt = _native_attempt(
            state="CANCEL_INVOCATION_STARTED",
            diagnostic="cancel_invocation_started",
            operation_hash=hashlib.sha256(
                kwargs["operation_idempotency_key"].encode()
            ).hexdigest(),
            operation_audit_id=kwargs["operation_audit_id"],
            operation_actor_id=kwargs["actor_id"],
            operation_roles=kwargs["roles"],
            operation_environment=kwargs["environment"],
            operation_intent=kwargs["operator_intent"],
            operation_correlation_id=kwargs["correlation_id"],
        )
        return SimpleNamespace(
            attempt=self.attempt, event=SimpleNamespace(), replayed=False
        )

    def record_child_terminal_without_cancel(
        self, materialization_id: str, **kwargs
    ):
        self.calls.append(("terminal_without_cancel", kwargs))
        self.attempt = _native_attempt(
            state="CANCEL_NOT_REQUIRED_TERMINAL",
            diagnostic=kwargs["diagnostic_code"],
            exchange_hash=kwargs.get("exchange_order_id_sha256"),
            operation_hash=hashlib.sha256(
                kwargs["operation_idempotency_key"].encode()
            ).hexdigest(),
            operation_audit_id=kwargs["operation_audit_id"],
            operation_actor_id=kwargs["actor_id"],
            operation_roles=kwargs["roles"],
            operation_environment=kwargs["environment"],
            operation_intent=kwargs["operator_intent"],
            operation_correlation_id=kwargs["correlation_id"],
        )
        return SimpleNamespace(
            attempt=self.attempt, event=SimpleNamespace(), replayed=False
        )

    def record_cancel_result(self, materialization_id: str, **kwargs):
        self.calls.append(("cancel_result", kwargs))
        self.attempt = _native_attempt(
            state=kwargs["outcome"],
            diagnostic=kwargs["diagnostic_code"],
            exchange_hash=kwargs.get("exchange_order_id_sha256"),
            operation_hash=SHA,
        )
        return SimpleNamespace(
            attempt=self.attempt, event=SimpleNamespace(), replayed=False
        )

    def _live_proof(
        self,
        operation_kind: str,
        *,
        event_state: str,
        outcome: str | None = None,
        audit_id: str = AUDIT_ID,
        operation_hash: str = SHA,
        child_state: str | None = None,
        observed_read_count: int | None = None,
        sdk_state: str | None = None,
        transport_state: str | None = None,
        exchange_state: str | None = None,
        read_state: str | None = None,
    ) -> SimpleNamespace:
        mutation = operation_kind in {"CREATE", "CANCEL"}
        if all(
            value is not None
            for value in (sdk_state, transport_state, exchange_state, read_state)
        ):
            pass
        elif mutation and event_state == "INVOCATION_STARTED":
            sdk_state = FollowUpSdkMutationInvocationState.UNKNOWN.value
            transport_state = (
                FollowUpTransportSubmissionState.POSSIBLY_SUBMITTED.value
            )
            exchange_state = FollowUpExchangeMutationState.UNKNOWN.value
            read_state = FollowUpReadAccountingState.UNKNOWN.value
            observed_read_count = None
        elif mutation and outcome == "SUCCEEDED":
            sdk_state = FollowUpSdkMutationInvocationState.INVOKED.value
            transport_state = (
                FollowUpTransportSubmissionState.CONFIRMED_SUBMITTED.value
            )
            exchange_state = (
                FollowUpExchangeMutationState.CONFIRMED_MUTATED.value
            )
            read_state = FollowUpReadAccountingState.EXACT.value
            observed_read_count = 1
        elif mutation and outcome == "REJECTED":
            sdk_state = FollowUpSdkMutationInvocationState.INVOKED.value
            transport_state = (
                FollowUpTransportSubmissionState.CONFIRMED_SUBMITTED.value
            )
            exchange_state = FollowUpExchangeMutationState.NOT_MUTATED.value
            read_state = FollowUpReadAccountingState.EXACT.value
            observed_read_count = 0
        elif mutation:
            sdk_state = FollowUpSdkMutationInvocationState.UNKNOWN.value
            transport_state = (
                FollowUpTransportSubmissionState.POSSIBLY_SUBMITTED.value
            )
            exchange_state = FollowUpExchangeMutationState.UNKNOWN.value
            read_state = FollowUpReadAccountingState.UNKNOWN.value
            observed_read_count = None
        else:
            sdk_state = FollowUpSdkMutationInvocationState.NOT_INVOKED.value
            transport_state = FollowUpTransportSubmissionState.NOT_SUBMITTED.value
            exchange_state = FollowUpExchangeMutationState.NOT_MUTATED.value
            read_state = (
                FollowUpReadAccountingState.UNKNOWN.value
                if event_state == "INVOCATION_STARTED" or outcome == "UNKNOWN"
                else FollowUpReadAccountingState.EXACT.value
            )
            if read_state == FollowUpReadAccountingState.UNKNOWN.value:
                observed_read_count = None
        return SimpleNamespace(
            event_id="c3ce1411-0b46-4ffc-b889-15fbfae4e88a",
            goal_id="operator_follow_up_operations_queue_and_single_live_proof",
            operation_kind=operation_kind,
            event_state=event_state,
            outcome=outcome,
            diagnostic_code="fixed_diagnostic",
            source_client_order_id=SOURCE_ID,
            root_client_order_id=ROOT_ID,
            follow_up_intent_id=INTENT_ID,
            materialization_id=(
                None if operation_kind == "ELIGIBILITY_READ" else MATERIALIZATION_ID
            ),
            child_client_order_id=(
                None if operation_kind == "ELIGIBILITY_READ" else CHILD_ID
            ),
            correlation_id=CORRELATION_ID,
            audit_id=audit_id,
            operation_idempotency_key_sha256=operation_hash,
            sdk_mutation_invocation_state=sdk_state,
            transport_submission_state=transport_state,
            exchange_mutation_state=exchange_state,
            read_accounting_state=read_state,
            observed_read_count=observed_read_count,
            accounting_evidence_origin="EXPLICIT",
            external_call_started=(
                sdk_state == FollowUpSdkMutationInvocationState.INVOKED.value
            ),
            reported_read_count=observed_read_count or 0,
            individual_retry_count=0,
            authoritative_child_state=child_state,
            recorded_at="2026-07-18T12:00:02+00:00",
            claimed=True,
        )

    def claim_create_invocation_started_atomically(self, **kwargs):
        self.calls.append(("atomic_create_start", kwargs))
        self.attempt = _native_attempt(
            state="CREATE_INVOCATION_STARTED",
            diagnostic="create_invocation_started",
            operation_hash=kwargs["operation_idempotency_key_sha256"],
            operation_audit_id=kwargs["audit_id"],
        )
        return SimpleNamespace(
            materialization=SimpleNamespace(
                attempt=self.attempt,
                event=SimpleNamespace(
                    operation_audit_id=kwargs["audit_id"],
                    operation_idempotency_key_sha256=(
                        kwargs["operation_idempotency_key_sha256"]
                    ),
                ),
                replayed=False,
            ),
            live_proof=self._live_proof(
                "CREATE",
                event_state="INVOCATION_STARTED",
                audit_id=kwargs["audit_id"],
                operation_hash=kwargs["operation_idempotency_key_sha256"],
            ),
            claimed=True,
        )

    def finalize_create_invocation_atomically(self, **kwargs):
        self.calls.append(("atomic_create_finalize", kwargs))
        self.attempt = _native_attempt(
            state=kwargs["outcome"],
            diagnostic=kwargs["diagnostic_code"],
            exchange_hash=(
                hashlib.sha256(kwargs["exchange_order_id"].encode()).hexdigest()
                if kwargs.get("exchange_order_id")
                else None
            ),
            operation_hash=SHA,
            operation_audit_id=AUDIT_ID,
        )
        self.local_projection = SimpleNamespace(
            materialization_id=MATERIALIZATION_ID,
            child_client_order_id=CHILD_ID,
            transition_kind=(
                "CREATE_ACCEPTED_ACTIVE"
                if kwargs["outcome"] == "CREATE_ACCEPTED_NONTERMINAL"
                else "CREATE_UNKNOWN_QUARANTINED"
            ),
            authoritative_order_status=kwargs["authoritative_order_status"],
            exchange_order_id_sha256=(
                hashlib.sha256(kwargs["exchange_order_id"].encode()).hexdigest()
                if kwargs.get("exchange_order_id")
                else None
            ),
            operation_audit_id=AUDIT_ID,
            operation_idempotency_key_sha256=SHA,
        )
        return SimpleNamespace(
            materialization=SimpleNamespace(
                attempt=self.attempt,
                event=SimpleNamespace(),
                replayed=False,
            ),
            local_state=SimpleNamespace(
                record=self.local_projection,
                replayed=False,
            ),
            live_proof=self._live_proof(
                "CREATE",
                event_state="TERMINAL",
                outcome=kwargs["live_proof_outcome"],
                child_state=kwargs["authoritative_child_state"],
                sdk_state=kwargs["sdk_mutation_invocation_state"],
                transport_state=kwargs["transport_submission_state"],
                exchange_state=kwargs["exchange_mutation_state"],
                read_state=kwargs["read_accounting_state"],
                observed_read_count=kwargs["observed_read_count"],
            ),
            replayed=False,
        )

    def claim_cancel_invocation_started_atomically(self, **kwargs):
        self.calls.append(("atomic_cancel_start", kwargs))
        operation_hash = hashlib.sha256(
            kwargs["operation_idempotency_key"].encode()
        ).hexdigest()
        self.attempt = _native_attempt(
            state="CANCEL_INVOCATION_STARTED",
            diagnostic="cancel_invocation_started",
            exchange_hash=hashlib.sha256(EXCHANGE_ID.encode()).hexdigest(),
            operation_hash=operation_hash,
            operation_audit_id=kwargs["audit_id"],
            operation_actor_id=kwargs["actor_id"],
            operation_roles=kwargs["roles"],
            operation_environment=kwargs["environment"],
            operation_intent=kwargs["operator_intent"],
            operation_correlation_id=kwargs["correlation_id"],
        )
        return SimpleNamespace(
            materialization=SimpleNamespace(
                attempt=self.attempt,
                event=SimpleNamespace(),
                replayed=False,
            ),
            live_proof=self._live_proof(
                "CANCEL",
                event_state="INVOCATION_STARTED",
                audit_id=kwargs["audit_id"],
                operation_hash=operation_hash,
            ),
            claimed=True,
        )

    def finalize_cancel_invocation_atomically(self, **kwargs):
        self.calls.append(("atomic_cancel_finalize", kwargs))
        operation_hash = self.attempt.operation_idempotency_key_sha256
        self.attempt = _native_attempt(
            state=kwargs["outcome"],
            diagnostic=kwargs["diagnostic_code"],
            exchange_hash=hashlib.sha256(
                kwargs["exchange_order_id"].encode()
            ).hexdigest(),
            operation_hash=operation_hash,
            operation_audit_id=AUDIT_ID,
        )
        self.local_projection = SimpleNamespace(
            materialization_id=MATERIALIZATION_ID,
            child_client_order_id=CHILD_ID,
            transition_kind="CANCEL_ACCEPTED_TERMINAL",
            authoritative_order_status=kwargs["authoritative_order_status"],
            exchange_order_id_sha256=hashlib.sha256(
                kwargs["exchange_order_id"].encode()
            ).hexdigest(),
            operation_audit_id=AUDIT_ID,
            operation_idempotency_key_sha256=operation_hash,
        )
        return SimpleNamespace(
            materialization=SimpleNamespace(
                attempt=self.attempt,
                event=SimpleNamespace(),
                replayed=False,
            ),
            local_state=SimpleNamespace(
                record=self.local_projection,
                replayed=False,
            ),
            live_proof=self._live_proof(
                "CANCEL",
                event_state="TERMINAL",
                outcome=kwargs["live_proof_outcome"],
                audit_id=AUDIT_ID,
                operation_hash=operation_hash,
                child_state=kwargs["authoritative_child_state"],
                sdk_state=kwargs["sdk_mutation_invocation_state"],
                transport_state=kwargs["transport_submission_state"],
                exchange_state=kwargs["exchange_mutation_state"],
                read_state=kwargs["read_accounting_state"],
                observed_read_count=kwargs["observed_read_count"],
            ),
            replayed=False,
        )

    def finalize_reconciliation_projection_atomically(self, **kwargs):
        self.calls.append(("atomic_reconciliation_finalize", kwargs))
        self.local_projection = SimpleNamespace(
            materialization_id=MATERIALIZATION_ID,
            child_client_order_id=CHILD_ID,
            transition_kind=kwargs["transition_kind"],
            authoritative_order_status=kwargs["authoritative_order_status"],
            exchange_order_id_sha256=hashlib.sha256(
                kwargs["exchange_order_id"].encode()
            ).hexdigest(),
            operation_audit_id=kwargs["operation_audit_id"],
            operation_idempotency_key_sha256=(
                kwargs["operation_idempotency_key_sha256"]
            ),
        )
        return SimpleNamespace(
            local_state=SimpleNamespace(
                record=self.local_projection,
                replayed=False,
            ),
            live_proof=self._live_proof(
                "RECONCILIATION_READ",
                event_state="TERMINAL",
                outcome=kwargs["live_proof_outcome"],
                audit_id=kwargs["operation_audit_id"],
                operation_hash=kwargs["operation_idempotency_key_sha256"],
                child_state=kwargs["authoritative_child_state"],
            ),
            replayed=False,
        )

    def finalize_terminal_without_cancel_atomically(self, **kwargs):
        self.calls.append(("atomic_terminal_without_cancel", kwargs))
        operation_hash = hashlib.sha256(
            kwargs["operation_idempotency_key"].encode()
        ).hexdigest()
        self.attempt = _native_attempt(
            state="CANCEL_NOT_REQUIRED_TERMINAL",
            diagnostic=kwargs["diagnostic_code"],
            exchange_hash=hashlib.sha256(
                kwargs["exchange_order_id"].encode()
            ).hexdigest(),
            operation_hash=operation_hash,
            operation_audit_id=kwargs["audit_id"],
            operation_actor_id=kwargs["actor_id"],
            operation_roles=kwargs["roles"],
            operation_environment=kwargs["environment"],
            operation_intent=kwargs["operator_intent"],
            operation_correlation_id=kwargs["correlation_id"],
        )
        self.local_projection = SimpleNamespace(
            materialization_id=MATERIALIZATION_ID,
            child_client_order_id=CHILD_ID,
            transition_kind="TERMINAL_WITHOUT_CANCEL",
            authoritative_order_status=kwargs["authoritative_order_status"],
            exchange_order_id_sha256=hashlib.sha256(
                kwargs["exchange_order_id"].encode()
            ).hexdigest(),
            operation_audit_id=kwargs["audit_id"],
            operation_idempotency_key_sha256=operation_hash,
        )
        return SimpleNamespace(
            materialization=SimpleNamespace(
                attempt=self.attempt,
                event=SimpleNamespace(),
                replayed=False,
            ),
            local_state=SimpleNamespace(
                record=self.local_projection,
                replayed=False,
            ),
            live_proof=self._live_proof(
                "RECONCILIATION_READ",
                event_state="TERMINAL",
                outcome="SUCCEEDED",
                audit_id=kwargs["audit_id"],
                operation_hash=operation_hash,
                child_state="TERMINAL",
            ),
            replayed=False,
        )


def _candidate() -> BackendMaterializationCandidate:
    return BackendMaterializationCandidate(
        attached_intent_id=INTENT_ID,
        source_client_order_id=SOURCE_ID,
        root_client_order_id=ROOT_ID,
        child_client_order_id=CHILD_ID,
        source_status="FILLED",
        source_side="BUY",
        child_side="SELL",
        product_id="BTC-USDC",
        product_type="SPOT",
        portfolio_type="TEST",
        portfolio_id=PORTFOLIO_ID,
        portfolio_scope_sha256=hashlib.sha256(PORTFOLIO_ID.encode()).hexdigest(),
        environment="controlled_live",
        base_size=Decimal("0.00001"),
        limit_price=Decimal("100000.00"),
        submitted_notional_usdc=Decimal("1.0000000"),
        max_submitted_notional_usdc=Decimal("3.10"),
        max_executed_notional_usdc=Decimal("1.00"),
        effective_notional_cap_usdc=Decimal("1.00"),
        authoritative_source_fill_proven=True,
        source_terminal=True,
        attached_intent_requires_fresh_authorization=True,
        no_existing_follow_up_child=True,
        controlled_live_enabled=True,
        execution_lease_valid=True,
        approved_test_portfolio_verified=True,
        product_policy_allowed=True,
        action_condition_guard_passed=True,
        wallet_check_passed=True,
    )


def _kernel_record(
    *, state: MaterializationRecordState = MaterializationRecordState.CREATE_ACCEPTED
) -> FollowUpMaterializationRecord:
    return FollowUpMaterializationRecord(
        materialization_id=MATERIALIZATION_ID,
        attached_intent_id=INTENT_ID,
        source_client_order_id=SOURCE_ID,
        root_client_order_id=ROOT_ID,
        child_client_order_id=CHILD_ID,
        state=state,
        create_idempotency_key_sha256=SHA,
        cancel_idempotency_key_sha256=None,
        create_call_consumed=state is not MaterializationRecordState.PREPARED,
        cancel_call_consumed=False,
        child_state=ChildExchangeState.ACTIVE,
        diagnostic_code="follow_up_materialization_create_accepted",
        correlation_id=CORRELATION_ID,
        audit_id=AUDIT_ID,
    )


def test_native_repository_adapter_maps_exact_states_and_hashes_only() -> None:
    native = _NativeRepository(_native_attempt(operation_hash=SHA))
    adapter = NativeFollowUpMaterializationRepositoryAdapter(native)

    prepared = adapter.read_materialization(
        source_client_order_id=SOURCE_ID,
        operation="CREATE",
        idempotency_key=IDEMPOTENCY_KEY,
    )
    assert prepared is not None
    assert prepared.state is MaterializationRecordState.PREPARED
    assert prepared.create_call_consumed is False
    assert prepared.cancel_idempotency_key_sha256 is None

    boundary = adapter.mark_create_invocation_started(
        materialization_id=MATERIALIZATION_ID,
        correlation_id=CORRELATION_ID,
    )
    assert boundary.claimed is True
    assert boundary.record.state is MaterializationRecordState.CREATE_INVOCATION_STARTED

    accepted = adapter.record_create_result(
        materialization_id=MATERIALIZATION_ID,
        result=SimpleNamespace(
            outcome=ExchangeInvocationOutcome.ACCEPTED,
            child_state=ChildExchangeState.ACTIVE,
            diagnostic_code="follow_up_materialization_create_accepted",
            exchange_order_id_sha256="b" * 64,
        ),
    )
    assert accepted.state is MaterializationRecordState.CREATE_ACCEPTED
    assert accepted.child_state is ChildExchangeState.ACTIVE
    assert native.calls[-1][1]["exchange_order_id_sha256"] == "b" * 64

    terminal = adapter.record_child_terminal_without_cancel(
        materialization_id=MATERIALIZATION_ID,
        result=SimpleNamespace(
            outcome=ExchangeInvocationOutcome.NOT_REQUIRED_TERMINAL,
            child_state=ChildExchangeState.TERMINAL,
            diagnostic_code="follow_up_materialization_child_already_terminal",
            exchange_order_id_sha256=None,
            operation_idempotency_key_sha256=SHA,
            correlation_id=CORRELATION_ID,
        ),
        idempotency_key=IDEMPOTENCY_KEY,
        actor_id="operator-2",
        roles=("trader", "operator"),
        environment="controlled_live",
        operator_intent="safely_close_out_materialized_follow_up",
        audit_id=AUDIT_ID,
    )
    assert terminal.state is MaterializationRecordState.CHILD_ALREADY_TERMINAL
    assert native.calls[-1][0] == "terminal_without_cancel"
    assert native.calls[-1][1] == {
        "diagnostic_code": "follow_up_materialization_child_already_terminal",
        "exchange_order_id_sha256": None,
        "operation_idempotency_key": IDEMPOTENCY_KEY,
        "actor_id": "operator-2",
        "roles": ("trader", "operator"),
        "environment": "controlled_live",
        "operator_intent": "safely_close_out_materialized_follow_up",
        "correlation_id": CORRELATION_ID,
        "operation_audit_id": AUDIT_ID,
    }

    cancel = adapter.mark_cancel_invocation_started(
        materialization_id=MATERIALIZATION_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        actor_id="operator-2",
        roles=("trader", "operator"),
        environment="controlled_live",
        operator_intent="safely_close_out_materialized_follow_up",
        correlation_id="a9dcad60-bf33-469d-b991-4dd31b938a1e",
        audit_id=AUDIT_ID,
    )
    assert cancel.claimed is True
    assert native.calls[-1] == (
        "cancel_start",
        {
            "operation_idempotency_key": IDEMPOTENCY_KEY,
            "actor_id": "operator-2",
            "roles": ("trader", "operator"),
            "environment": "controlled_live",
            "operator_intent": "safely_close_out_materialized_follow_up",
            "correlation_id": "a9dcad60-bf33-469d-b991-4dd31b938a1e",
            "operation_audit_id": AUDIT_ID,
        },
    )


def test_native_repository_adapter_rejects_changed_create_idempotency_key() -> None:
    adapter = NativeFollowUpMaterializationRepositoryAdapter(
        _NativeRepository(_native_attempt())
    )
    with pytest.raises(RuntimeError, match="idempotency_conflict"):
        adapter.read_materialization(
            source_client_order_id=SOURCE_ID,
            operation="CREATE",
            idempotency_key="different-key",
        )


def test_native_repository_adapter_uses_atomic_create_boundary_and_raw_projection() -> None:
    native = _NativeRepository(_native_attempt(operation_hash=SHA))
    pending: dict[tuple[str, str, str, str], _PendingRawExchangeEvidence] = {}
    adapter = NativeFollowUpMaterializationRepositoryAdapter(
        native,
        pending_raw_exchange_evidence=pending,
    )

    boundary = adapter.claim_create_invocation_started_atomically(
        source_client_order_id=SOURCE_ID,
        materialization_id=MATERIALIZATION_ID,
        correlation_id=CORRELATION_ID,
        audit_id=AUDIT_ID,
        operation_idempotency_key_sha256=SHA,
    )
    assert boundary.claimed is True
    assert boundary.record.state is (
        MaterializationRecordState.CREATE_INVOCATION_STARTED
    )

    pending_key = _pending_evidence_key(
        materialization_id=MATERIALIZATION_ID,
        child_client_order_id=CHILD_ID,
        operation_audit_id=AUDIT_ID,
        operation_idempotency_key_sha256=SHA,
    )
    pending[pending_key] = _PendingRawExchangeEvidence(
        materialization_id=MATERIALIZATION_ID,
        child_client_order_id=CHILD_ID,
        operation_audit_id=AUDIT_ID,
        operation_idempotency_key_sha256=SHA,
        authoritative_order_status="OPEN",
        exchange_order_id=EXCHANGE_ID,
    )
    result = PersistedInvocationResult(
        outcome=ExchangeInvocationOutcome.ACCEPTED,
        child_state=ChildExchangeState.ACTIVE,
        diagnostic_code="follow_up_materialization_create_accepted",
        operation_idempotency_key_sha256=SHA,
        correlation_id=CORRELATION_ID,
        exchange_order_id_sha256=hashlib.sha256(
            EXCHANGE_ID.encode()
        ).hexdigest(),
    )

    finalized = adapter.finalize_create_invocation_atomically(
        source_client_order_id=SOURCE_ID,
        materialization_id=MATERIALIZATION_ID,
        result=result,
        accounting=_mutation_accounting(ExchangeInvocationOutcome.ACCEPTED),
        external_call_started=True,
        reported_read_count=1,
        individual_retry_count=0,
    )

    assert finalized.state is MaterializationRecordState.CREATE_ACCEPTED
    assert pending_key not in pending
    assert native.calls[-1][0] == "atomic_create_finalize"
    assert native.calls[-1][1]["exchange_order_id"] == EXCHANGE_ID
    assert native.calls[-1][1]["authoritative_order_status"] == "OPEN"


def test_native_repository_adapter_rejects_missing_or_mismatched_atomic_create_evidence() -> None:
    native = _NativeRepository(
        _native_attempt(
            state="CREATE_INVOCATION_STARTED",
            diagnostic="create_invocation_started",
            operation_hash=SHA,
            operation_audit_id=AUDIT_ID,
        )
    )
    pending: dict[tuple[str, str, str, str], _PendingRawExchangeEvidence] = {}
    adapter = NativeFollowUpMaterializationRepositoryAdapter(
        native,
        pending_raw_exchange_evidence=pending,
    )
    result = PersistedInvocationResult(
        outcome=ExchangeInvocationOutcome.ACCEPTED,
        child_state=ChildExchangeState.ACTIVE,
        diagnostic_code="follow_up_materialization_create_accepted",
        operation_idempotency_key_sha256=SHA,
        correlation_id=CORRELATION_ID,
        exchange_order_id_sha256=hashlib.sha256(
            EXCHANGE_ID.encode()
        ).hexdigest(),
    )
    def finalize() -> FollowUpMaterializationRecord:
        return adapter.finalize_create_invocation_atomically(
            source_client_order_id=SOURCE_ID,
            materialization_id=MATERIALIZATION_ID,
            result=result,
            accounting=_mutation_accounting(ExchangeInvocationOutcome.ACCEPTED),
            external_call_started=True,
            reported_read_count=1,
            individual_retry_count=0,
        )

    with pytest.raises(RuntimeError, match="atomic_evidence_missing"):
        finalize()

    pending_key = _pending_evidence_key(
        materialization_id=MATERIALIZATION_ID,
        child_client_order_id=CHILD_ID,
        operation_audit_id=AUDIT_ID,
        operation_idempotency_key_sha256=SHA,
    )
    pending[pending_key] = _PendingRawExchangeEvidence(
        materialization_id=MATERIALIZATION_ID,
        child_client_order_id=CHILD_ID,
        operation_audit_id=AUDIT_ID,
        operation_idempotency_key_sha256=SHA,
        authoritative_order_status="OPEN",
        exchange_order_id="different-exchange-id",
    )
    with pytest.raises(RuntimeError, match="atomic_evidence_mismatch"):
        finalize()
    assert pending_key in pending


def test_native_repository_adapter_retains_pending_evidence_on_atomic_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native = _NativeRepository(
        _native_attempt(
            state="CREATE_INVOCATION_STARTED",
            diagnostic="create_invocation_started",
            operation_hash=SHA,
            operation_audit_id=AUDIT_ID,
        )
    )
    pending_key = _pending_evidence_key(
        materialization_id=MATERIALIZATION_ID,
        child_client_order_id=CHILD_ID,
        operation_audit_id=AUDIT_ID,
        operation_idempotency_key_sha256=SHA,
    )
    pending = {
        pending_key: _PendingRawExchangeEvidence(
            materialization_id=MATERIALIZATION_ID,
            child_client_order_id=CHILD_ID,
            operation_audit_id=AUDIT_ID,
            operation_idempotency_key_sha256=SHA,
            authoritative_order_status="OPEN",
            exchange_order_id=EXCHANGE_ID,
        )
    }
    adapter = NativeFollowUpMaterializationRepositoryAdapter(
        native,
        pending_raw_exchange_evidence=pending,
    )

    def fail_atomic_finalize(**_kwargs):
        raise RuntimeError("synthetic_transaction_rollback")

    monkeypatch.setattr(
        native,
        "finalize_create_invocation_atomically",
        fail_atomic_finalize,
    )
    with pytest.raises(RuntimeError, match="synthetic_transaction_rollback"):
        adapter.finalize_create_invocation_atomically(
            source_client_order_id=SOURCE_ID,
            materialization_id=MATERIALIZATION_ID,
            result=PersistedInvocationResult(
                outcome=ExchangeInvocationOutcome.ACCEPTED,
                child_state=ChildExchangeState.ACTIVE,
                diagnostic_code="follow_up_materialization_create_accepted",
                operation_idempotency_key_sha256=SHA,
                correlation_id=CORRELATION_ID,
                exchange_order_id_sha256=hashlib.sha256(
                    EXCHANGE_ID.encode()
                ).hexdigest(),
            ),
            accounting=_mutation_accounting(ExchangeInvocationOutcome.ACCEPTED),
            external_call_started=True,
            reported_read_count=1,
            individual_retry_count=0,
        )

    assert pending_key in pending


def test_atomic_create_unknown_ignores_and_consumes_exact_cached_raw_evidence() -> None:
    native = _NativeRepository(
        _native_attempt(
            state="CREATE_INVOCATION_STARTED",
            diagnostic="create_invocation_started",
            operation_hash=SHA,
            operation_audit_id=AUDIT_ID,
        )
    )
    pending_key = _pending_evidence_key(
        materialization_id=MATERIALIZATION_ID,
        child_client_order_id=CHILD_ID,
        operation_audit_id=AUDIT_ID,
        operation_idempotency_key_sha256=SHA,
    )
    pending = {
        pending_key: _PendingRawExchangeEvidence(
            materialization_id=MATERIALIZATION_ID,
            child_client_order_id=CHILD_ID,
            operation_audit_id=AUDIT_ID,
            operation_idempotency_key_sha256=SHA,
            authoritative_order_status="OPEN",
            exchange_order_id=EXCHANGE_ID,
        )
    }
    adapter = NativeFollowUpMaterializationRepositoryAdapter(
        native,
        pending_raw_exchange_evidence=pending,
    )

    finalized = adapter.finalize_create_invocation_atomically(
        source_client_order_id=SOURCE_ID,
        materialization_id=MATERIALIZATION_ID,
        result=PersistedInvocationResult(
            outcome=ExchangeInvocationOutcome.UNKNOWN,
            child_state=ChildExchangeState.UNKNOWN,
            diagnostic_code="follow_up_materialization_create_outcome_unknown",
            operation_idempotency_key_sha256=SHA,
            correlation_id=CORRELATION_ID,
        ),
        accounting=_mutation_accounting(ExchangeInvocationOutcome.UNKNOWN),
        external_call_started=True,
        reported_read_count=0,
        individual_retry_count=0,
    )

    assert finalized.state is MaterializationRecordState.CREATE_UNKNOWN
    assert pending_key not in pending
    assert native.calls[-1][1]["exchange_order_id"] is None
    assert native.calls[-1][1]["authoritative_order_status"] == (
        "SUBMISSION_UNKNOWN"
    )


def test_atomic_cancel_unknown_uses_pre_call_local_status_not_terminal_cache() -> None:
    operation_hash = hashlib.sha256(IDEMPOTENCY_KEY.encode()).hexdigest()
    native = _NativeRepository(
        _native_attempt(
            state="CANCEL_INVOCATION_STARTED",
            diagnostic="cancel_invocation_started",
            exchange_hash=hashlib.sha256(EXCHANGE_ID.encode()).hexdigest(),
            operation_hash=operation_hash,
            operation_audit_id=AUDIT_ID,
        )
    )
    pending_key = _pending_evidence_key(
        materialization_id=MATERIALIZATION_ID,
        child_client_order_id=CHILD_ID,
        operation_audit_id=AUDIT_ID,
        operation_idempotency_key_sha256=operation_hash,
    )
    pending = {
        pending_key: _PendingRawExchangeEvidence(
            materialization_id=MATERIALIZATION_ID,
            child_client_order_id=CHILD_ID,
            operation_audit_id=AUDIT_ID,
            operation_idempotency_key_sha256=operation_hash,
            authoritative_order_status="CANCELLED",
            exchange_order_id=EXCHANGE_ID,
        )
    }
    adapter = NativeFollowUpMaterializationRepositoryAdapter(
        native,
        pending_raw_exchange_evidence=pending,
        local_order_reader=lambda child_id: {
            "client_order_id": child_id,
            "exchange_order_id": EXCHANGE_ID,
            "status": "CANCEL_QUEUED",
        },
    )

    finalized = adapter.finalize_cancel_invocation_atomically(
        source_client_order_id=SOURCE_ID,
        materialization_id=MATERIALIZATION_ID,
        result=PersistedInvocationResult(
            outcome=ExchangeInvocationOutcome.UNKNOWN,
            child_state=ChildExchangeState.UNKNOWN,
            diagnostic_code="follow_up_materialization_cancel_outcome_unknown",
            operation_idempotency_key_sha256=operation_hash,
            correlation_id=CORRELATION_ID,
        ),
        accounting=_mutation_accounting(ExchangeInvocationOutcome.UNKNOWN),
        external_call_started=True,
        reported_read_count=0,
        individual_retry_count=0,
    )

    assert finalized.state is MaterializationRecordState.CANCEL_UNKNOWN
    assert pending_key not in pending
    assert native.calls[-1][1]["authoritative_order_status"] == (
        "CANCEL_QUEUED"
    )


def test_native_repository_adapter_uses_atomic_cancel_boundary_and_local_restart_evidence() -> None:
    operation_hash = hashlib.sha256(IDEMPOTENCY_KEY.encode()).hexdigest()
    native = _NativeRepository(
        _native_attempt(
            state="CREATE_ACCEPTED_NONTERMINAL",
            diagnostic="create_accepted_nonterminal",
            exchange_hash=hashlib.sha256(EXCHANGE_ID.encode()).hexdigest(),
            operation_hash=SHA,
            operation_audit_id=AUDIT_ID,
        )
    )
    local_child = {
        "client_order_id": CHILD_ID,
        "exchange_order_id": EXCHANGE_ID,
        "status": "OPEN",
    }
    adapter = NativeFollowUpMaterializationRepositoryAdapter(
        native,
        pending_raw_exchange_evidence={},
        local_order_reader=lambda child_id: (
            local_child if child_id == CHILD_ID else None
        ),
    )

    boundary = adapter.claim_cancel_invocation_started_atomically(
        source_client_order_id=SOURCE_ID,
        materialization_id=MATERIALIZATION_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        actor_id="operator-2",
        roles=("trader", "operator"),
        environment="controlled_live",
        operator_intent="safely_close_out_materialized_follow_up",
        correlation_id=CORRELATION_ID,
        audit_id=AUDIT_ID,
    )
    assert boundary.record.cancel_idempotency_key_sha256 == operation_hash

    result = PersistedInvocationResult(
        outcome=ExchangeInvocationOutcome.UNKNOWN,
        child_state=ChildExchangeState.UNKNOWN,
        diagnostic_code="follow_up_materialization_cancel_outcome_unknown",
        operation_idempotency_key_sha256=operation_hash,
        correlation_id=CORRELATION_ID,
    )
    finalized = adapter.finalize_cancel_invocation_atomically(
        source_client_order_id=SOURCE_ID,
        materialization_id=MATERIALIZATION_ID,
        result=result,
        accounting=_mutation_accounting(ExchangeInvocationOutcome.UNKNOWN),
        external_call_started=True,
        reported_read_count=0,
        individual_retry_count=0,
    )

    assert finalized.state is MaterializationRecordState.CANCEL_UNKNOWN
    assert finalized.child_state is ChildExchangeState.UNKNOWN
    assert native.calls[-1][0] == "atomic_cancel_finalize"
    assert native.calls[-1][1]["exchange_order_id"] == EXCHANGE_ID
    assert native.calls[-1][1]["authoritative_order_status"] == "OPEN"


def _reconciliation_claim() -> LiveProofOperationClaim:
    return LiveProofOperationClaim(
        operation_kind=FollowUpLiveProofOperationKind.RECONCILIATION_READ,
        source_client_order_id=SOURCE_ID,
        root_client_order_id=ROOT_ID,
        attached_intent_id=INTENT_ID,
        materialization_id=MATERIALIZATION_ID,
        child_client_order_id=CHILD_ID,
        correlation_id=CORRELATION_ID,
        audit_id=AUDIT_ID,
        operation_idempotency_key_sha256=SHA,
        claimed=True,
    )


def test_native_repository_adapter_atomically_finalizes_active_reconciliation() -> None:
    native = _NativeRepository(
        _native_attempt(
            state="CREATE_UNKNOWN_CONSUMED",
            diagnostic="create_unknown_consumed",
            operation_hash=SHA,
            operation_audit_id=AUDIT_ID,
        )
    )
    pending_key = _pending_evidence_key(
        materialization_id=MATERIALIZATION_ID,
        child_client_order_id=CHILD_ID,
        operation_audit_id=AUDIT_ID,
        operation_idempotency_key_sha256=SHA,
    )
    pending = {
        pending_key: _PendingRawExchangeEvidence(
            materialization_id=MATERIALIZATION_ID,
            child_client_order_id=CHILD_ID,
            operation_audit_id=AUDIT_ID,
            operation_idempotency_key_sha256=SHA,
            authoritative_order_status="OPEN",
            exchange_order_id=EXCHANGE_ID,
        )
    }
    adapter = NativeFollowUpMaterializationRepositoryAdapter(
        native,
        pending_raw_exchange_evidence=pending,
    )
    record = replace(
        _kernel_record(state=MaterializationRecordState.CREATE_UNKNOWN),
        child_state=ChildExchangeState.UNKNOWN,
        diagnostic_code="follow_up_materialization_create_outcome_unknown",
    )

    finalized = adapter.finalize_active_reconciliation_atomically(
        source_client_order_id=SOURCE_ID,
        record=record,
        claim=_reconciliation_claim(),
        evidence=ChildStateEvidence(
            child_client_order_id=CHILD_ID,
            state=ChildExchangeState.ACTIVE,
            fresh=True,
            authoritative=True,
            read_count=1,
            individual_retry_count=0,
            ambiguous=False,
            coinbase_read_started=True,
            exchange_order_id_sha256=hashlib.sha256(
                EXCHANGE_ID.encode()
            ).hexdigest(),
        ),
    )

    assert finalized.state is MaterializationRecordState.CREATE_UNKNOWN
    assert pending_key not in pending
    assert native.calls[-2][0] == "atomic_reconciliation_finalize"
    assert native.calls[-2][1]["transition_kind"] == "RECONCILED_ACTIVE"


def test_native_repository_adapter_atomically_finalizes_terminal_without_cancel() -> None:
    native = _NativeRepository(
        _native_attempt(
            state="CREATE_ACCEPTED_NONTERMINAL",
            diagnostic="create_accepted_nonterminal",
            exchange_hash=hashlib.sha256(EXCHANGE_ID.encode()).hexdigest(),
            operation_hash=SHA,
            operation_audit_id=AUDIT_ID,
        )
    )
    pending_key = _pending_evidence_key(
        materialization_id=MATERIALIZATION_ID,
        child_client_order_id=CHILD_ID,
        operation_audit_id=AUDIT_ID,
        operation_idempotency_key_sha256=SHA,
    )
    pending = {
        pending_key: _PendingRawExchangeEvidence(
            materialization_id=MATERIALIZATION_ID,
            child_client_order_id=CHILD_ID,
            operation_audit_id=AUDIT_ID,
            operation_idempotency_key_sha256=SHA,
            authoritative_order_status="FILLED",
            exchange_order_id=EXCHANGE_ID,
        )
    }
    adapter = NativeFollowUpMaterializationRepositoryAdapter(
        native,
        pending_raw_exchange_evidence=pending,
    )
    evidence = ChildStateEvidence(
        child_client_order_id=CHILD_ID,
        state=ChildExchangeState.TERMINAL,
        fresh=True,
        authoritative=True,
        read_count=1,
        individual_retry_count=0,
        ambiguous=False,
        coinbase_read_started=True,
        exchange_order_id_sha256=hashlib.sha256(
            EXCHANGE_ID.encode()
        ).hexdigest(),
    )

    finalized = adapter.finalize_terminal_without_cancel_atomically(
        source_client_order_id=SOURCE_ID,
        record=_kernel_record(),
        claim=_reconciliation_claim(),
        evidence=evidence,
        result=PersistedInvocationResult(
            outcome=ExchangeInvocationOutcome.NOT_REQUIRED_TERMINAL,
            child_state=ChildExchangeState.TERMINAL,
            diagnostic_code=(
                "follow_up_materialization_child_already_terminal"
            ),
            operation_idempotency_key_sha256=SHA,
            correlation_id=CORRELATION_ID,
            exchange_order_id_sha256=evidence.exchange_order_id_sha256,
        ),
        idempotency_key=IDEMPOTENCY_KEY,
        actor_id="operator-2",
        roles=("trader",),
        environment="controlled_live",
        operator_intent="safely_close_out_materialized_follow_up",
        correlation_id=CORRELATION_ID,
        audit_id=AUDIT_ID,
    )

    assert finalized.state is MaterializationRecordState.CHILD_ALREADY_TERMINAL
    assert finalized.cancel_call_consumed is False
    assert pending_key not in pending
    assert native.calls[-1][0] == "atomic_terminal_without_cancel"


class _SyntheticEligibilityClient:
    def record_read(self) -> None:
        return None


class _CountingEligibilityDependencies:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.child_rows: dict[str, dict[str, object]] = {}
        self.stealth_rows: dict[str, dict[str, object]] = {}
        self.persisted_order_payloads: list[dict[str, object]] = []

    def _count(self, name: str) -> None:
        self.counts[name] = self.counts.get(name, 0) + 1

    def authority(self) -> bool:
        self._count("authority")
        return True

    def order(self, client_order_id: str):
        self._count(f"order:{client_order_id}")
        if client_order_id in self.child_rows:
            return self.child_rows[client_order_id]
        return {
            "client_order_id": client_order_id,
            "product_id": "BTC-USDC",
            "side": "BUY",
            "size": "0.00001",
            "price": "90000",
            "status": "FILLED",
            "parent_order_id": None,
            "retail_portfolio_id": PORTFOLIO_ID,
            "exchange_order_id": EXCHANGE_ID,
            "target_movement": "10",
            "target_movement_type": "P",
        }

    def template(self, source_id: str, root_id: str):
        self._count("template")
        return {
            "product_id": "BTC-USDC",
            "side": "SELL",
            "order_base_size": "0.00001",
            "start_price": "100000.00",
            "target_movement": "10",
            "target_movement_type": "P",
        }

    def product(self, _rest_client, product_id: str):
        self._count("product")
        return {
            "product_id": product_id,
            "product_type": "SPOT",
            "trading_disabled": False,
            "base_increment": "0.00001",
            "quote_increment": "0.01",
        }

    def binding(self, rest_client, expected_id: str):
        self._count("binding")
        return SimpleNamespace(
            ready=True,
            blocker=None,
            observed_portfolio_id=expected_id,
            observed_portfolio_type="CONSUMER",
        )

    def source_order_readback(self, rest_client, **kwargs):
        self._count("source_order_readback")
        return {
            "authoritative": True,
            "exact_identity_match": True,
            "authoritative_status": "FILLED",
            "retail_portfolio_id_matches_expected": True,
            "exchange_order_id": EXCHANGE_ID,
            "matched_order": {
                "client_order_id": SOURCE_ID,
                "order_id": EXCHANGE_ID,
                "product_id": "BTC-USDC",
                "status": "FILLED",
                "side": "BUY",
                "base_size": "0.00001",
                "filled_size": "0.00001",
            },
        }

    def source_fill_readback(self, rest_client, **kwargs):
        self._count("source_fill_readback")
        return {
            "authoritative": True,
            "fill_read_succeeded": True,
            "fill_count": 1,
            "pagination_complete": True,
        }

    def market(self, _rest_client, product_id: str):
        self._count("market")
        return {
            "product_id": product_id,
            "best_bid": "50000",
            "best_ask": "50001",
            "source": "coinbase_rest_best_bid",
            "observed_at": "2026-07-18T12:00:00+00:00",
        }

    def standing(self, **kwargs):
        self._count("standing")
        return {"allowed": True, "blocker": None}

    def wallets(self, _rest_client):
        self._count("wallets")
        return {
            "BTC": {"available_balance": {"value": "0.001"}},
            "USDC": {"available_balance": {"value": "25"}},
        }

    def guard(self, **kwargs):
        self._count("guard")
        return True

    def persist_child(self, order):
        self._count("persist_child")
        self.persisted_order_payloads.append(dict(order))
        child_id = order["stealth_order_id"]
        created = child_id not in self.stealth_rows
        self.child_rows.setdefault(child_id, {
            "client_order_id": order["stealth_order_id"],
            "product_id": order["product_id"],
            "side": order["side"],
            "size": order["total_size"],
            "price": order["limit_price"],
            "parent_order_id": order["parent_order_id"],
            "retail_portfolio_id": PORTFOLIO_ID,
            "status": "PENDING",
            "exchange_order_id": None,
        })
        self.stealth_rows.setdefault(child_id, dict(order))
        return (44, created)


def _runtime(
    deps: _CountingEligibilityDependencies,
    native: _NativeRepository | None = None,
    *,
    local_state_transitioner=None,
    pending_raw_exchange_evidence=None,
) -> ProductionFollowUpMaterializationRuntime:
    return ProductionFollowUpMaterializationRuntime(
        native_repository=native or _NativeRepository(),
        rest_client=_SyntheticEligibilityClient(),
        configured_portfolio_id=PORTFOLIO_ID,
        environment="controlled_live",
        runtime_authority_check=deps.authority,
        local_order_reader=deps.order,
        template_resolver=deps.template,
        product_reader=lambda client, product_id: (
            client.record_read(),
            deps.product(client, product_id),
        )[1],
        portfolio_binding_evaluator=lambda client, expected_id: (
            client.record_read(),
            deps.binding(client, expected_id),
        )[1],
        source_order_readback=lambda client, **kwargs: (
            client.record_read(),
            deps.source_order_readback(client, **kwargs),
        )[1],
        source_fill_readback=lambda client, **kwargs: (
            client.record_read(),
            deps.source_fill_readback(client, **kwargs),
        )[1],
        market_reference_reader=lambda client, product_id: (
            client.record_read(),
            deps.market(client, product_id),
        )[1],
        standing_price_evaluator=deps.standing,
        wallet_reader=lambda client: (
            client.record_read(),
            deps.wallets(client),
        )[1],
        action_guard_evaluator=deps.guard,
        child_persister=deps.persist_child,
        local_stealth_reader=lambda child_id: deps.stealth_rows.get(child_id),
        local_state_transitioner=local_state_transitioner,
        pending_raw_exchange_evidence=pending_raw_exchange_evidence,
    )


def test_production_runtime_performs_one_fresh_pass_and_derives_candidate() -> None:
    deps = _CountingEligibilityDependencies()
    evidence = _runtime(deps).resolve_fresh_materialization_eligibility(
        source_client_order_id=SOURCE_ID
    )

    assert evidence.fresh is True
    assert evidence.ambiguous is False
    assert evidence.blockers == ()
    assert evidence.eligibility_pass_count == 1
    assert evidence.reconciliation_pass_count == 1
    assert evidence.individual_retry_count == 0
    assert evidence.coinbase_read_started is True
    assert evidence.coinbase_read_count == 6
    assert evidence.candidate == _candidate()
    for operation in (
        "authority",
        "binding",
        "product",
        "source_order_readback",
        "source_fill_readback",
        "template",
        "market",
        "standing",
        "wallets",
        "guard",
    ):
        assert deps.counts[operation] == 1


def test_production_runtime_persists_exact_preclaimed_child_without_exchange() -> None:
    deps = _CountingEligibilityDependencies()
    runtime = _runtime(deps)
    evidence = runtime.resolve_fresh_materialization_eligibility(
        source_client_order_id=SOURCE_ID
    )
    persisted = runtime.persist_preclaimed_child(
        candidate=evidence.candidate,
        materialization_id=MATERIALIZATION_ID,
    )

    assert persisted.persisted is True
    assert persisted.exact_replay_safe is True
    assert persisted.exchange_call_ran is False
    assert deps.counts["persist_child"] == 1
    child = deps.child_rows[CHILD_ID]
    assert child["parent_order_id"] == ROOT_ID
    assert child["exchange_order_id"] is None
    assert deps.persisted_order_payloads[0]["remaining_size"] == Decimal("0")
    assert deps.persisted_order_payloads[0]["status"] == "HIDDEN"
    assert (
        deps.persisted_order_payloads[0]["reveal_condition_json"][
            "operator_materialization_quarantine"
        ]
        is True
    )

    replay = runtime.persist_preclaimed_child(
        candidate=evidence.candidate,
        materialization_id=MATERIALIZATION_ID,
    )
    assert replay.exact_replay_safe is True
    assert replay.exchange_call_ran is False
    assert deps.counts["persist_child"] == 2
    assert deps.persisted_order_payloads[0] == deps.persisted_order_payloads[1]


def test_production_runtime_fails_closed_with_fixed_blocker_on_wallet_shortfall() -> None:
    deps = _CountingEligibilityDependencies()
    deps.wallets = lambda _client: {
        "BTC": {"available_balance": {"value": "0"}},
        "USDC": {"available_balance": {"value": "0"}},
    }
    evidence = _runtime(deps).resolve_fresh_materialization_eligibility(
        source_client_order_id=SOURCE_ID
    )
    assert evidence.candidate is None
    assert evidence.blockers == ("follow_up_materialization_wallet_blocked",)
    assert evidence.ambiguous is False
    assert evidence.coinbase_read_started is True


def test_production_runtime_rejects_non_usdc_spot_product_before_cap_or_wallet_use() -> None:
    deps = _CountingEligibilityDependencies()
    native = _NativeRepository()
    readiness = _readiness()
    readiness.product_id = "ETH-USD"

    def read_materialization(source_client_order_id: str):
        native.calls.append(("read", source_client_order_id))
        return SimpleNamespace(readiness=readiness, attempt=None)

    native.read_materialization = read_materialization

    def order(client_order_id: str):
        value = _CountingEligibilityDependencies.order(deps, client_order_id)
        return {**value, "product_id": "ETH-USD"}

    deps.order = order
    deps.template = lambda _source_id, _root_id: {
        "product_id": "ETH-USD",
        "side": "SELL",
        "order_base_size": "0.00001",
        "start_price": "100000.00",
    }
    deps.source_order_readback = lambda _client, **_kwargs: {
        "authoritative": True,
        "exact_identity_match": True,
        "authoritative_status": "FILLED",
        "retail_portfolio_id_matches_expected": True,
        "exchange_order_id": EXCHANGE_ID,
        "matched_order": {
            "client_order_id": SOURCE_ID,
            "order_id": EXCHANGE_ID,
            "product_id": "ETH-USD",
            "status": "FILLED",
            "side": "BUY",
            "filled_size": "0.00001",
        },
    }

    evidence = _runtime(deps, native).resolve_fresh_materialization_eligibility(
        source_client_order_id=SOURCE_ID
    )

    assert evidence.candidate is None
    assert evidence.blockers == (
        "follow_up_materialization_product_policy_blocked",
    )
    assert "template" not in deps.counts
    assert "wallets" not in deps.counts
    assert "guard" not in deps.counts


def test_runtime_precondition_failure_reports_no_coinbase_read_started() -> None:
    deps = _CountingEligibilityDependencies()
    deps.authority = lambda: False

    evidence = _runtime(deps).resolve_fresh_materialization_eligibility(
        source_client_order_id=SOURCE_ID
    )

    assert evidence.candidate is None
    assert evidence.blockers == (
        "follow_up_materialization_controlled_live_required",
    )
    assert evidence.coinbase_read_started is False
    assert "binding" not in deps.counts


def test_preclaim_replay_rejects_a_revealable_existing_stealth_row() -> None:
    deps = _CountingEligibilityDependencies()
    runtime = _runtime(deps)
    evidence = runtime.resolve_fresh_materialization_eligibility(
        source_client_order_id=SOURCE_ID
    )
    runtime.persist_preclaimed_child(
        candidate=evidence.candidate,
        materialization_id=MATERIALIZATION_ID,
    )
    deps.stealth_rows[CHILD_ID]["remaining_size"] = Decimal("0.00001")

    with pytest.raises(
        RuntimeError,
        match="follow_up_materialization_child_persistence_invalid",
    ):
        runtime.persist_preclaimed_child(
            candidate=evidence.candidate,
            materialization_id=MATERIALIZATION_ID,
        )


class _ExchangeClient:
    def __init__(self) -> None:
        self.create_calls: list[dict[str, object]] = []
        self.cancel_calls: list[tuple[str, dict[str, object]]] = []
        self.raise_create = False
        self.create_response: dict[str, object] = {
            "success": True,
            "success_response": {
                "order_id": EXCHANGE_ID,
                "product_id": "BTC-USDC",
                "side": "SELL",
                "client_order_id": CHILD_ID,
            },
            "order_configuration": {
                "limit_limit_gtc": {
                    "base_size": "0.00001",
                    "limit_price": "100000.00",
                    "post_only": False,
                }
            },
        }

    def create_order(self, **kwargs):
        self.create_calls.append(kwargs)
        if self.raise_create:
            raise TimeoutError("withheld")
        return self.create_response

    def cancel_order(self, client_order_id: str, **kwargs):
        self.cancel_calls.append((client_order_id, kwargs))
        return {
            "outcome": "succeeded",
            "succeeded": True,
            "identity_match": True,
        }


def _exact_child_readback(
    *,
    status: str = "PENDING",
    side: str = "SELL",
    base_size: str = "0.00001",
    limit_price: str = "100000.00",
    exchange_order_id: str = EXCHANGE_ID,
) -> dict[str, object]:
    return {
        "authoritative": True,
        "exact_identity_match": True,
        "authoritative_status": status,
        "retail_portfolio_id_matches_expected": True,
        "exchange_order_id": exchange_order_id,
        "matched_order": {
            "client_order_id": CHILD_ID,
            "order_id": exchange_order_id,
            "product_id": "BTC-USDC",
            "product_type": "SPOT",
            "side": side,
            "status": status,
            "order_type": "LIMIT",
            "time_in_force": "GTC",
            "base_size": base_size,
            "limit_price": limit_price,
            "order_configuration": {
                "limit_limit_gtc": {
                    "base_size": base_size,
                    "limit_price": limit_price,
                    "post_only": False,
                }
            },
        },
    }


def test_canonical_exchange_uses_one_scoped_create_and_hashes_identity() -> None:
    client = _ExchangeClient()
    scopes: list[str] = []
    inflight: list[str] = []
    updates: list[tuple[str, str, str | None]] = []
    pending: dict[tuple[str, str, str, str], object] = {}
    readbacks: list[dict[str, object]] = []

    def exact_read(_client, **kwargs):
        readbacks.append(kwargs)
        return _exact_child_readback()

    @contextmanager
    def scope(name: str):
        scopes.append(name)
        yield

    @contextmanager
    def inflight_scope(name: str):
        inflight.append(name)
        yield

    exchange = CanonicalFollowUpMaterializationExchange(
        rest_client=client,
        runtime_authority_check=lambda: True,
        local_order_reader=lambda _order_id: {
            "client_order_id": CHILD_ID,
            "product_id": "BTC-USDC",
            "retail_portfolio_id": PORTFOLIO_ID,
            "exchange_order_id": EXCHANGE_ID,
        },
        execution_scope_factory=scope,
        exact_order_readback=exact_read,
        configured_portfolio_id=PORTFOLIO_ID,
        inflight_scope_factory=inflight_scope,
        pending_raw_exchange_evidence=pending,
    )

    result = exchange.create_follow_up_child(
        candidate=_candidate(),
        correlation_id=CORRELATION_ID,
        materialization_id=MATERIALIZATION_ID,
        operation_audit_id=AUDIT_ID,
        operation_idempotency_key_sha256=SHA,
    )
    assert result.outcome is ExchangeInvocationOutcome.ACCEPTED
    _assert_invocation_activity(
        result,
        sdk=FollowUpSdkMutationInvocationState.INVOKED,
        transport=FollowUpTransportSubmissionState.CONFIRMED_SUBMITTED,
        exchange=FollowUpExchangeMutationState.CONFIRMED_MUTATED,
        read=FollowUpReadAccountingState.EXACT,
        count=1,
    )
    assert result.exchange_call_started is True
    assert result.child_state is ChildExchangeState.ACTIVE
    assert result.exchange_order_id_sha256 == hashlib.sha256(
        EXCHANGE_ID.encode()
    ).hexdigest()
    assert len(client.create_calls) == 1
    assert client.create_calls[0]["client_order_id"] == CHILD_ID
    assert client.create_calls[0]["order_configuration"] == {
        "limit_limit_gtc": {
            "base_size": "0.00001",
            "limit_price": "100000.00",
            "post_only": False,
        }
    }
    assert len(scopes) == 1
    assert inflight == ["PLACE"]
    assert len(readbacks) == 1
    assert readbacks[0]["exchange_order_id"] == EXCHANGE_ID
    assert updates == []
    assert len(pending) == 1


def test_canonical_exchange_rejects_mismatched_create_echo_without_adopting_identity() -> None:
    client = _ExchangeClient()
    client.create_response["success_response"] = {
        "order_id": EXCHANGE_ID,
        "product_id": "ETH-USDC",
        "side": "BUY",
        "client_order_id": "not-the-durable-child",
    }
    readbacks: list[object] = []
    pending: dict[tuple[str, str, str, str], object] = {}

    @contextmanager
    def scope(_name: str):
        yield

    exchange = CanonicalFollowUpMaterializationExchange(
        rest_client=client,
        runtime_authority_check=lambda: True,
        local_order_reader=lambda _order_id: None,
        execution_scope_factory=scope,
        exact_order_readback=lambda *_args, **_kwargs: readbacks.append(object()),
        configured_portfolio_id=PORTFOLIO_ID,
        pending_raw_exchange_evidence=pending,
    )

    result = exchange.create_follow_up_child(
        candidate=_candidate(),
        correlation_id=CORRELATION_ID,
        materialization_id=MATERIALIZATION_ID,
        operation_audit_id=AUDIT_ID,
        operation_idempotency_key_sha256=SHA,
    )

    assert result.outcome is ExchangeInvocationOutcome.UNKNOWN
    assert result.exchange_call_started is True
    _assert_invocation_activity(
        result,
        sdk=FollowUpSdkMutationInvocationState.INVOKED,
        transport=FollowUpTransportSubmissionState.POSSIBLY_SUBMITTED,
        exchange=FollowUpExchangeMutationState.UNKNOWN,
        read=FollowUpReadAccountingState.UNKNOWN,
        count=None,
    )
    assert len(client.create_calls) == 1
    assert readbacks == []
    assert pending == {}


def test_canonical_exchange_requires_full_exact_post_create_tuple() -> None:
    client = _ExchangeClient()
    pending: dict[tuple[str, str, str, str], object] = {}

    @contextmanager
    def scope(_name: str):
        yield

    exchange = CanonicalFollowUpMaterializationExchange(
        rest_client=client,
        runtime_authority_check=lambda: True,
        local_order_reader=lambda _order_id: None,
        execution_scope_factory=scope,
        exact_order_readback=lambda _client, **_kwargs: _exact_child_readback(
            side="BUY"
        ),
        configured_portfolio_id=PORTFOLIO_ID,
        pending_raw_exchange_evidence=pending,
    )

    result = exchange.create_follow_up_child(
        candidate=_candidate(),
        correlation_id=CORRELATION_ID,
        materialization_id=MATERIALIZATION_ID,
        operation_audit_id=AUDIT_ID,
        operation_idempotency_key_sha256=SHA,
    )

    assert result.outcome is ExchangeInvocationOutcome.UNKNOWN
    assert result.exchange_call_started is True
    _assert_invocation_activity(
        result,
        sdk=FollowUpSdkMutationInvocationState.INVOKED,
        transport=FollowUpTransportSubmissionState.POSSIBLY_SUBMITTED,
        exchange=FollowUpExchangeMutationState.UNKNOWN,
        read=FollowUpReadAccountingState.UNKNOWN,
        count=None,
    )
    assert len(client.create_calls) == 1
    assert pending == {}


def test_journaled_create_projects_pending_identity_atomically_after_call() -> None:
    client = _ExchangeClient()
    pending: dict[tuple[str, str, str, str], object] = {}

    @contextmanager
    def scope(_name: str):
        yield

    exchange = CanonicalFollowUpMaterializationExchange(
        rest_client=client,
        runtime_authority_check=lambda: True,
        local_order_reader=lambda _order_id: None,
        execution_scope_factory=scope,
        exact_order_readback=lambda _client, **_kwargs: _exact_child_readback(),
        configured_portfolio_id=PORTFOLIO_ID,
        pending_raw_exchange_evidence=pending,
    )
    invocation = exchange.create_follow_up_child(
        candidate=_candidate(),
        correlation_id=CORRELATION_ID,
        materialization_id=MATERIALIZATION_ID,
        operation_audit_id=AUDIT_ID,
        operation_idempotency_key_sha256=SHA,
    )
    assert invocation.outcome is ExchangeInvocationOutcome.ACCEPTED

    transition_calls: list[dict[str, object]] = []

    def transitioner(**kwargs):
        transition_calls.append(kwargs)
        exchange_id = kwargs["exchange_order_id"]
        return SimpleNamespace(
            record=SimpleNamespace(
                materialization_id=kwargs["materialization_id"],
                child_client_order_id=CHILD_ID,
                transition_kind=kwargs["transition_kind"],
                authoritative_order_status=kwargs[
                    "authoritative_order_status"
                ],
                exchange_order_id_sha256=(
                    hashlib.sha256(exchange_id.encode()).hexdigest()
                    if exchange_id
                    else None
                ),
                operation_audit_id=kwargs["operation_audit_id"],
                operation_idempotency_key_sha256=kwargs[
                    "operation_idempotency_key_sha256"
                ],
            ),
            replayed=False,
        )

    native = _NativeRepository(
        _native_attempt(
            state="CREATE_ACCEPTED_NONTERMINAL",
            diagnostic="follow_up_materialization_create_accepted",
            exchange_hash=hashlib.sha256(EXCHANGE_ID.encode()).hexdigest(),
            operation_hash=SHA,
            operation_audit_id=AUDIT_ID,
        )
    )
    runtime = _runtime(
        _CountingEligibilityDependencies(),
        native,
        local_state_transitioner=transitioner,
        pending_raw_exchange_evidence=pending,
    )
    projection = runtime.project_persisted_child_state(
        record=_kernel_record(),
        operation="CREATE",
        allow_reconciliation_read=False,
    )

    assert projection.projected is True
    assert projection.exact_replay_safe is True
    assert projection.exchange_call_ran is False
    assert projection.live_read_count == 0
    assert transition_calls == [
        {
            "materialization_id": MATERIALIZATION_ID,
            "transition_kind": "CREATE_ACCEPTED_ACTIVE",
            "authoritative_order_status": "PENDING",
            "exchange_order_id": EXCHANGE_ID,
            "operation_audit_id": AUDIT_ID,
            "operation_idempotency_key_sha256": SHA,
        }
    ]
    assert pending == {}


def test_projection_replay_repairs_with_one_exact_read_and_no_exchange_call() -> None:
    deps = _CountingEligibilityDependencies()
    deps.child_rows[CHILD_ID] = {
        "client_order_id": CHILD_ID,
        "product_id": "BTC-USDC",
        "side": "SELL",
        "size": "0.00001",
        "price": "100000.00",
        "parent_order_id": ROOT_ID,
        "retail_portfolio_id": PORTFOLIO_ID,
        "status": "HIDDEN",
        "exchange_order_id": None,
    }
    child_reads: list[dict[str, object]] = []

    def exact_child_read(_client, **kwargs):
        _client.record_read()
        child_reads.append(kwargs)
        return {
            "authoritative": True,
            "exact_identity_match": True,
            "authoritative_status": "OPEN",
            "retail_portfolio_id_matches_expected": True,
            "exchange_order_id": EXCHANGE_ID,
            "matched_order": {
                "client_order_id": CHILD_ID,
                "order_id": EXCHANGE_ID,
                "product_id": "BTC-USDC",
                "side": "SELL",
                "status": "OPEN",
                "order_configuration": {
                    "limit_limit_gtc": {
                        "base_size": "0.00001",
                        "limit_price": "100000.00",
                        "post_only": False,
                    }
                },
            },
        }

    transition_calls: list[dict[str, object]] = []

    def transitioner(**kwargs):
        transition_calls.append(kwargs)
        return SimpleNamespace(
            record=SimpleNamespace(
                materialization_id=MATERIALIZATION_ID,
                child_client_order_id=CHILD_ID,
                transition_kind=kwargs["transition_kind"],
                authoritative_order_status=kwargs[
                    "authoritative_order_status"
                ],
                exchange_order_id_sha256=hashlib.sha256(
                    kwargs["exchange_order_id"].encode()
                ).hexdigest(),
                operation_audit_id=AUDIT_ID,
                operation_idempotency_key_sha256=SHA,
            ),
            replayed=False,
        )

    native = _NativeRepository(
        _native_attempt(
            state="CREATE_ACCEPTED_NONTERMINAL",
            diagnostic="follow_up_materialization_create_accepted",
            exchange_hash=hashlib.sha256(EXCHANGE_ID.encode()).hexdigest(),
            operation_hash=SHA,
            operation_audit_id=AUDIT_ID,
        )
    )
    pending: dict[tuple[str, str, str, str], object] = {}
    runtime = ProductionFollowUpMaterializationRuntime(
        native_repository=native,
        rest_client=_SyntheticEligibilityClient(),
        configured_portfolio_id=PORTFOLIO_ID,
        environment="controlled_live",
        runtime_authority_check=deps.authority,
        local_order_reader=deps.order,
        template_resolver=deps.template,
        product_reader=deps.product,
        portfolio_binding_evaluator=deps.binding,
        source_order_readback=exact_child_read,
        source_fill_readback=deps.source_fill_readback,
        market_reference_reader=deps.market,
        standing_price_evaluator=deps.standing,
        wallet_reader=deps.wallets,
        action_guard_evaluator=deps.guard,
        child_persister=deps.persist_child,
        local_stealth_reader=lambda child_id: deps.stealth_rows.get(child_id),
        local_state_transitioner=transitioner,
        pending_raw_exchange_evidence=pending,
    )

    projection = runtime.project_persisted_child_state(
        record=_kernel_record(),
        operation="REPLAY_REPAIR",
        allow_reconciliation_read=True,
    )

    assert projection.live_read_count == 1
    assert projection.individual_retry_count == 0
    assert len(child_reads) == 1
    assert transition_calls[0]["transition_kind"] == "CREATE_ACCEPTED_ACTIVE"
    assert transition_calls[0]["exchange_order_id"] == EXCHANGE_ID
    assert pending == {}


def test_cancel_accepted_restart_projects_durable_terminal_without_live_read() -> None:
    deps = _CountingEligibilityDependencies()
    deps.child_rows[CHILD_ID] = {
        "client_order_id": CHILD_ID,
        "product_id": "BTC-USDC",
        "side": "SELL",
        "size": "0.00001",
        "price": "100000.00",
        "parent_order_id": ROOT_ID,
        "retail_portfolio_id": PORTFOLIO_ID,
        "status": "OPEN",
        "exchange_order_id": EXCHANGE_ID,
    }
    cancel_key_hash = hashlib.sha256(b"cancel-once").hexdigest()
    cancel_audit_id = "f33b263d-967b-4d49-ac6f-e7c2a82cd078"
    native = _NativeRepository(
        _native_attempt(
            state="CANCEL_ACCEPTED_TERMINAL",
            diagnostic="follow_up_materialization_cancel_accepted",
            exchange_hash=hashlib.sha256(EXCHANGE_ID.encode()).hexdigest(),
            operation_hash=cancel_key_hash,
            operation_audit_id=cancel_audit_id,
        )
    )
    transition_calls: list[dict[str, object]] = []

    def transitioner(**kwargs):
        transition_calls.append(kwargs)
        return SimpleNamespace(
            record=SimpleNamespace(
                materialization_id=MATERIALIZATION_ID,
                child_client_order_id=CHILD_ID,
                transition_kind=kwargs["transition_kind"],
                authoritative_order_status=kwargs["authoritative_order_status"],
                exchange_order_id_sha256=hashlib.sha256(
                    kwargs["exchange_order_id"].encode()
                ).hexdigest(),
                operation_audit_id=cancel_audit_id,
                operation_idempotency_key_sha256=cancel_key_hash,
            ),
            replayed=False,
        )

    runtime = _runtime(
        deps,
        native,
        local_state_transitioner=transitioner,
        pending_raw_exchange_evidence={},
    )
    record = replace(
        _kernel_record(state=MaterializationRecordState.CANCEL_ACCEPTED),
        cancel_idempotency_key_sha256=cancel_key_hash,
        cancel_call_consumed=True,
        child_state=ChildExchangeState.TERMINAL,
        diagnostic_code="follow_up_materialization_cancel_accepted",
        audit_id=cancel_audit_id,
    )

    projection = runtime.project_persisted_child_state(
        record=record,
        operation="CANCEL",
        allow_reconciliation_read=False,
    )

    assert projection.live_read_count == 0
    assert transition_calls == [
        {
            "materialization_id": MATERIALIZATION_ID,
            "transition_kind": "CANCEL_ACCEPTED_TERMINAL",
            "authoritative_order_status": "CANCELLED",
            "exchange_order_id": EXCHANGE_ID,
            "operation_audit_id": cancel_audit_id,
            "operation_idempotency_key_sha256": cancel_key_hash,
        }
    ]


def test_canonical_exchange_does_not_retry_unknown_create() -> None:
    client = _ExchangeClient()
    client.raise_create = True

    @contextmanager
    def scope(_name: str):
        yield

    updates: list[tuple[str, str, str | None]] = []
    exchange = CanonicalFollowUpMaterializationExchange(
        rest_client=client,
        runtime_authority_check=lambda: True,
        local_order_reader=lambda _order_id: None,
        execution_scope_factory=scope,
        exact_order_readback=lambda _client, **_kwargs: _exact_child_readback(),
        configured_portfolio_id=PORTFOLIO_ID,
    )
    result = exchange.create_follow_up_child(
        candidate=_candidate(),
        correlation_id=CORRELATION_ID,
        materialization_id=MATERIALIZATION_ID,
        operation_audit_id=AUDIT_ID,
        operation_idempotency_key_sha256=SHA,
    )
    assert result.outcome is ExchangeInvocationOutcome.UNKNOWN
    assert result.exchange_call_started is True
    _assert_invocation_activity(
        result,
        sdk=FollowUpSdkMutationInvocationState.INVOKED,
        transport=FollowUpTransportSubmissionState.POSSIBLY_SUBMITTED,
        exchange=FollowUpExchangeMutationState.UNKNOWN,
        read=FollowUpReadAccountingState.UNKNOWN,
        count=None,
    )
    assert len(client.create_calls) == 1
    assert updates == []


def test_canonical_exchange_precondition_failure_is_known_zero_calls() -> None:
    client = _ExchangeClient()

    @contextmanager
    def scope(_name: str):
        raise AssertionError("execution scope must not open")
        yield

    exchange = CanonicalFollowUpMaterializationExchange(
        rest_client=client,
        runtime_authority_check=lambda: False,
        local_order_reader=lambda _order_id: None,
        execution_scope_factory=scope,
    )
    result = exchange.create_follow_up_child(
        candidate=_candidate(),
        correlation_id=CORRELATION_ID,
        materialization_id=MATERIALIZATION_ID,
        operation_audit_id=AUDIT_ID,
        operation_idempotency_key_sha256=SHA,
    )

    assert result.outcome is ExchangeInvocationOutcome.UNKNOWN
    assert result.exchange_call_started is False
    _assert_invocation_activity(
        result,
        sdk=FollowUpSdkMutationInvocationState.NOT_INVOKED,
        transport=FollowUpTransportSubmissionState.NOT_SUBMITTED,
        exchange=FollowUpExchangeMutationState.NOT_MUTATED,
        read=FollowUpReadAccountingState.EXACT,
        count=0,
    )
    assert client.create_calls == []


def test_canonical_create_rechecks_exact_route_admission_at_final_boundary() -> None:
    client = _ExchangeClient()
    final_admission_checks: list[str] = []

    @contextmanager
    def scope(_name: str):
        yield

    def deny_final_admission() -> bool:
        final_admission_checks.append("create")
        return False

    exchange = CanonicalFollowUpMaterializationExchange(
        rest_client=client,
        runtime_authority_check=lambda: True,
        create_route_admission_check=deny_final_admission,
        local_order_reader=lambda _order_id: None,
        execution_scope_factory=scope,
        exact_order_readback=lambda _client, **_kwargs: _exact_child_readback(),
        configured_portfolio_id=PORTFOLIO_ID,
    )

    result = exchange.create_follow_up_child(
        candidate=_candidate(),
        correlation_id=CORRELATION_ID,
        materialization_id=MATERIALIZATION_ID,
        operation_audit_id=AUDIT_ID,
        operation_idempotency_key_sha256=SHA,
    )

    assert result.outcome is ExchangeInvocationOutcome.UNKNOWN
    assert result.exchange_call_started is False
    _assert_invocation_activity(
        result,
        sdk=FollowUpSdkMutationInvocationState.NOT_INVOKED,
        transport=FollowUpTransportSubmissionState.NOT_SUBMITTED,
        exchange=FollowUpExchangeMutationState.NOT_MUTATED,
        read=FollowUpReadAccountingState.EXACT,
        count=0,
    )
    assert final_admission_checks == ["create"]
    assert client.create_calls == []


def test_canonical_create_classifies_final_authority_denial_as_zero_calls() -> None:
    client = _ExchangeClient()
    authority_checks: list[str] = []

    @contextmanager
    def scope(_name: str):
        yield

    def deny_authority(expected_scope: str) -> None:
        authority_checks.append(expected_scope)
        raise CoinbaseExecutionAuthorityError("coinbase_execution_authority_missing")

    exchange = CanonicalFollowUpMaterializationExchange(
        rest_client=client,
        runtime_authority_check=lambda: True,
        create_route_admission_check=lambda: True,
        final_execution_authority_check=deny_authority,
        local_order_reader=lambda _order_id: None,
        execution_scope_factory=scope,
        exact_order_readback=lambda _client, **_kwargs: _exact_child_readback(),
        configured_portfolio_id=PORTFOLIO_ID,
    )

    result = exchange.create_follow_up_child(
        candidate=_candidate(),
        correlation_id=CORRELATION_ID,
        materialization_id=MATERIALIZATION_ID,
        operation_audit_id=AUDIT_ID,
        operation_idempotency_key_sha256=SHA,
    )

    assert result.outcome is ExchangeInvocationOutcome.UNKNOWN
    assert result.exchange_call_started is False
    _assert_invocation_activity(
        result,
        sdk=FollowUpSdkMutationInvocationState.NOT_INVOKED,
        transport=FollowUpTransportSubmissionState.NOT_SUBMITTED,
        exchange=FollowUpExchangeMutationState.NOT_MUTATED,
        read=FollowUpReadAccountingState.EXACT,
        count=0,
    )
    assert authority_checks == ["canonical_admin_api_spot_place"]
    assert client.create_calls == []


def test_canonical_exchange_rolls_back_preclaim_after_explicit_rejection() -> None:
    client = _ExchangeClient()
    client.create_response = {
        "success": False,
        "failure_reason": "withheld",
    }
    updates: list[tuple[str, str, str | None]] = []

    @contextmanager
    def scope(_name: str):
        yield

    exchange = CanonicalFollowUpMaterializationExchange(
        rest_client=client,
        runtime_authority_check=lambda: True,
        local_order_reader=lambda _order_id: None,
        execution_scope_factory=scope,
        exact_order_readback=lambda _client, **_kwargs: _exact_child_readback(),
        configured_portfolio_id=PORTFOLIO_ID,
    )
    result = exchange.create_follow_up_child(
        candidate=_candidate(),
        correlation_id=CORRELATION_ID,
        materialization_id=MATERIALIZATION_ID,
        operation_audit_id=AUDIT_ID,
        operation_idempotency_key_sha256=SHA,
    )
    assert result.outcome is ExchangeInvocationOutcome.REJECTED
    assert result.exchange_call_started is True
    _assert_invocation_activity(
        result,
        sdk=FollowUpSdkMutationInvocationState.INVOKED,
        transport=FollowUpTransportSubmissionState.CONFIRMED_SUBMITTED,
        exchange=FollowUpExchangeMutationState.NOT_MUTATED,
        read=FollowUpReadAccountingState.EXACT,
        count=0,
    )
    assert len(client.create_calls) == 1
    assert updates == []


def test_canonical_exchange_cancels_one_exact_stored_exchange_identity() -> None:
    client = _ExchangeClient()
    updates: list[tuple[str, str, str | None]] = []

    @contextmanager
    def scope(_name: str):
        yield

    exchange = CanonicalFollowUpMaterializationExchange(
        rest_client=client,
        runtime_authority_check=lambda: True,
        local_order_reader=lambda order_id: {
            "client_order_id": order_id,
            "product_id": "BTC-USDC",
            "side": "SELL",
            "size": "0.00001",
            "price": "100000.00",
            "retail_portfolio_id": PORTFOLIO_ID,
            "exchange_order_id": EXCHANGE_ID,
        },
        execution_scope_factory=scope,
        exact_order_readback=lambda _client, **_kwargs: _exact_child_readback(
            status="CANCELLED"
        ),
        configured_portfolio_id=PORTFOLIO_ID,
    )

    result = exchange.cancel_follow_up_child(
        child_client_order_id=CHILD_ID,
        correlation_id=CORRELATION_ID,
        materialization_id=MATERIALIZATION_ID,
        operation_audit_id=AUDIT_ID,
        operation_idempotency_key_sha256=SHA,
    )
    assert result.outcome is ExchangeInvocationOutcome.ACCEPTED
    assert result.exchange_call_started is True
    _assert_invocation_activity(
        result,
        sdk=FollowUpSdkMutationInvocationState.INVOKED,
        transport=FollowUpTransportSubmissionState.CONFIRMED_SUBMITTED,
        exchange=FollowUpExchangeMutationState.CONFIRMED_MUTATED,
        read=FollowUpReadAccountingState.EXACT,
        count=1,
    )
    assert result.child_state is ChildExchangeState.TERMINAL
    assert client.cancel_calls == [
        (
            CHILD_ID,
            {
                "verified_exchange_order_id": EXCHANGE_ID,
                "return_evidence": True,
            },
        )
    ]
    assert updates == []


def test_canonical_cancel_rechecks_route_and_authority_before_wrapper_call() -> None:
    child = {
        "client_order_id": CHILD_ID,
        "product_id": "BTC-USDC",
        "side": "SELL",
        "size": "0.00001",
        "price": "100000.00",
        "retail_portfolio_id": PORTFOLIO_ID,
        "exchange_order_id": EXCHANGE_ID,
    }

    @contextmanager
    def scope(_name: str):
        yield

    route_denied_client = _ExchangeClient()
    route_denied = CanonicalFollowUpMaterializationExchange(
        rest_client=route_denied_client,
        runtime_authority_check=lambda: True,
        cancel_route_admission_check=lambda: False,
        local_order_reader=lambda _order_id: child,
        execution_scope_factory=scope,
        exact_order_readback=lambda _client, **_kwargs: _exact_child_readback(
            status="CANCELLED"
        ),
        configured_portfolio_id=PORTFOLIO_ID,
    ).cancel_follow_up_child(
        child_client_order_id=CHILD_ID,
        correlation_id=CORRELATION_ID,
        materialization_id=MATERIALIZATION_ID,
        operation_audit_id=AUDIT_ID,
        operation_idempotency_key_sha256=SHA,
    )
    assert route_denied.exchange_call_started is False
    assert route_denied_client.cancel_calls == []

    authority_denied_client = _ExchangeClient()

    def deny_authority(_expected_scope: str) -> None:
        raise CoinbaseExecutionAuthorityError("coinbase_execution_authority_missing")

    authority_denied = CanonicalFollowUpMaterializationExchange(
        rest_client=authority_denied_client,
        runtime_authority_check=lambda: True,
        cancel_route_admission_check=lambda: True,
        final_execution_authority_check=deny_authority,
        local_order_reader=lambda _order_id: child,
        execution_scope_factory=scope,
        exact_order_readback=lambda _client, **_kwargs: _exact_child_readback(
            status="CANCELLED"
        ),
        configured_portfolio_id=PORTFOLIO_ID,
    ).cancel_follow_up_child(
        child_client_order_id=CHILD_ID,
        correlation_id=CORRELATION_ID,
        materialization_id=MATERIALIZATION_ID,
        operation_audit_id=AUDIT_ID,
        operation_idempotency_key_sha256=SHA,
    )
    assert authority_denied.exchange_call_started is False
    assert authority_denied_client.cancel_calls == []


def test_canonical_exchange_does_not_call_cancel_for_incomplete_local_child_tuple() -> None:
    client = _ExchangeClient()

    @contextmanager
    def scope(_name: str):
        raise AssertionError("scope must remain closed")
        yield

    exchange = CanonicalFollowUpMaterializationExchange(
        rest_client=client,
        runtime_authority_check=lambda: True,
        local_order_reader=lambda order_id: {
            "client_order_id": order_id,
            "product_id": "BTC-USDC",
            "retail_portfolio_id": PORTFOLIO_ID,
            "exchange_order_id": EXCHANGE_ID,
        },
        execution_scope_factory=scope,
        exact_order_readback=lambda *_args, **_kwargs: _exact_child_readback(
            status="CANCELLED"
        ),
        configured_portfolio_id=PORTFOLIO_ID,
    )

    result = exchange.cancel_follow_up_child(
        child_client_order_id=CHILD_ID,
        correlation_id=CORRELATION_ID,
        materialization_id=MATERIALIZATION_ID,
        operation_audit_id=AUDIT_ID,
        operation_idempotency_key_sha256=SHA,
    )

    assert result.outcome is ExchangeInvocationOutcome.UNKNOWN
    assert result.exchange_call_started is False
    _assert_invocation_activity(
        result,
        sdk=FollowUpSdkMutationInvocationState.NOT_INVOKED,
        transport=FollowUpTransportSubmissionState.NOT_SUBMITTED,
        exchange=FollowUpExchangeMutationState.NOT_MUTATED,
        read=FollowUpReadAccountingState.EXACT,
        count=0,
    )
    assert client.cancel_calls == []


def test_canonical_cancel_local_read_failure_is_known_pre_sdk_zero_calls() -> None:
    client = _ExchangeClient()

    @contextmanager
    def scope(_name: str):
        raise AssertionError("scope must remain closed")
        yield

    def unavailable_local_child(_order_id: str):
        raise RuntimeError("withheld local read failure")

    exchange = CanonicalFollowUpMaterializationExchange(
        rest_client=client,
        runtime_authority_check=lambda: True,
        cancel_route_admission_check=lambda: True,
        local_order_reader=unavailable_local_child,
        execution_scope_factory=scope,
        exact_order_readback=lambda *_args, **_kwargs: _exact_child_readback(
            status="CANCELLED"
        ),
        configured_portfolio_id=PORTFOLIO_ID,
    )

    result = exchange.cancel_follow_up_child(
        child_client_order_id=CHILD_ID,
        correlation_id=CORRELATION_ID,
        materialization_id=MATERIALIZATION_ID,
        operation_audit_id=AUDIT_ID,
        operation_idempotency_key_sha256=SHA,
    )

    assert result.outcome is ExchangeInvocationOutcome.UNKNOWN
    assert result.exchange_call_started is False
    _assert_invocation_activity(
        result,
        sdk=FollowUpSdkMutationInvocationState.NOT_INVOKED,
        transport=FollowUpTransportSubmissionState.NOT_SUBMITTED,
        exchange=FollowUpExchangeMutationState.NOT_MUTATED,
        read=FollowUpReadAccountingState.EXACT,
        count=0,
    )
    assert result.post_mutation_read_started is False
    assert result.post_mutation_read_count == 0
    assert client.cancel_calls == []


def test_canonical_exchange_keeps_accepted_but_still_active_cancel_unknown() -> None:
    client = _ExchangeClient()
    pending: dict[tuple[str, str, str, str], object] = {}

    @contextmanager
    def scope(_name: str):
        yield

    exchange = CanonicalFollowUpMaterializationExchange(
        rest_client=client,
        runtime_authority_check=lambda: True,
        local_order_reader=lambda order_id: {
            "client_order_id": order_id,
            "product_id": "BTC-USDC",
            "side": "SELL",
            "size": "0.00001",
            "price": "100000.00",
            "retail_portfolio_id": PORTFOLIO_ID,
            "exchange_order_id": EXCHANGE_ID,
            "status": "OPEN",
        },
        execution_scope_factory=scope,
        exact_order_readback=lambda _client, **_kwargs: _exact_child_readback(
            status="OPEN"
        ),
        configured_portfolio_id=PORTFOLIO_ID,
        pending_raw_exchange_evidence=pending,
    )

    result = exchange.cancel_follow_up_child(
        child_client_order_id=CHILD_ID,
        correlation_id=CORRELATION_ID,
        materialization_id=MATERIALIZATION_ID,
        operation_audit_id=AUDIT_ID,
        operation_idempotency_key_sha256=SHA,
    )

    assert result.outcome is ExchangeInvocationOutcome.UNKNOWN
    assert result.child_state is ChildExchangeState.UNKNOWN
    assert result.exchange_call_started is True
    _assert_invocation_activity(
        result,
        sdk=FollowUpSdkMutationInvocationState.INVOKED,
        transport=FollowUpTransportSubmissionState.POSSIBLY_SUBMITTED,
        exchange=FollowUpExchangeMutationState.UNKNOWN,
        read=FollowUpReadAccountingState.UNKNOWN,
        count=None,
    )
    assert len(client.cancel_calls) == 1
    assert len(pending) == 1


def test_unknown_create_child_read_projects_exact_identity_before_cancel() -> None:
    deps = _CountingEligibilityDependencies()
    native = _NativeRepository(
        _native_attempt(
            state="CREATE_UNKNOWN_CONSUMED",
            diagnostic="follow_up_materialization_create_outcome_unknown",
            operation_hash=SHA,
            operation_audit_id=AUDIT_ID,
        )
    )
    deps.child_rows[CHILD_ID] = {
        "client_order_id": CHILD_ID,
        "product_id": "BTC-USDC",
        "side": "SELL",
        "size": "0.00001",
        "price": "100000.00",
        "parent_order_id": ROOT_ID,
        "retail_portfolio_id": PORTFOLIO_ID,
        "status": "SUBMISSION_UNKNOWN",
        "exchange_order_id": None,
    }
    read_kwargs: list[dict[str, object]] = []

    def child_readback(_client, **kwargs):
        read_kwargs.append(kwargs)
        return {
            "authoritative": True,
            "exact_identity_match": True,
            "authoritative_status": "OPEN",
            "retail_portfolio_id_matches_expected": True,
            "exchange_order_id": EXCHANGE_ID,
            "matched_order": {
                "client_order_id": CHILD_ID,
                "order_id": EXCHANGE_ID,
                "product_id": "BTC-USDC",
                "side": "SELL",
                "status": "OPEN",
                "order_configuration": {
                    "limit_limit_gtc": {
                        "base_size": "0.00001",
                        "limit_price": "100000.00",
                        "post_only": False,
                    }
                },
            },
        }

    updates: list[tuple[str, str, str | None]] = []
    cache: dict[tuple[str, str, str, str], object] = {}
    projection_calls: list[dict[str, object]] = []

    def transitioner(**kwargs):
        projection_calls.append(kwargs)
        deps.child_rows[CHILD_ID]["status"] = kwargs[
            "authoritative_order_status"
        ]
        deps.child_rows[CHILD_ID]["exchange_order_id"] = kwargs[
            "exchange_order_id"
        ]
        return SimpleNamespace(
            record=SimpleNamespace(
                materialization_id=kwargs["materialization_id"],
                child_client_order_id=CHILD_ID,
                transition_kind=kwargs["transition_kind"],
                authoritative_order_status=kwargs[
                    "authoritative_order_status"
                ],
                exchange_order_id_sha256=(
                    hashlib.sha256(
                        kwargs["exchange_order_id"].encode()
                    ).hexdigest()
                    if kwargs["exchange_order_id"]
                    else None
                ),
                operation_audit_id=kwargs["operation_audit_id"],
                operation_idempotency_key_sha256=kwargs[
                    "operation_idempotency_key_sha256"
                ],
            ),
            replayed=False,
        )
    runtime = ProductionFollowUpMaterializationRuntime(
        native_repository=native,
        rest_client=object(),
        configured_portfolio_id=PORTFOLIO_ID,
        environment="controlled_live",
        runtime_authority_check=deps.authority,
        local_order_reader=deps.order,
        template_resolver=deps.template,
        product_reader=deps.product,
        portfolio_binding_evaluator=deps.binding,
        source_order_readback=child_readback,
        source_fill_readback=deps.source_fill_readback,
        market_reference_reader=deps.market,
        standing_price_evaluator=deps.standing,
        wallet_reader=deps.wallets,
        action_guard_evaluator=deps.guard,
        child_persister=deps.persist_child,
        local_stealth_reader=lambda child_id: deps.stealth_rows.get(child_id),
        local_state_transitioner=transitioner,
        pending_raw_exchange_evidence=cache,
    )
    state = runtime.read_authoritative_child_state(
        child_client_order_id=CHILD_ID,
        materialization_id=MATERIALIZATION_ID,
        operation_audit_id=AUDIT_ID,
        operation_idempotency_key_sha256=SHA,
    )
    assert state.state is ChildExchangeState.ACTIVE
    assert state.authoritative is True
    assert state.exchange_order_id_sha256 == hashlib.sha256(
        EXCHANGE_ID.encode()
    ).hexdigest()
    assert read_kwargs[0]["exchange_order_id"] is None
    assert updates == []
    projected = runtime.project_persisted_child_state(
        record=replace(
            _kernel_record(state=MaterializationRecordState.CREATE_UNKNOWN),
            child_state=ChildExchangeState.UNKNOWN,
            diagnostic_code="follow_up_materialization_create_outcome_unknown",
        ),
        operation="REPLAY_REPAIR",
        allow_reconciliation_read=False,
    )
    assert projected.live_read_count == 0
    assert [call["transition_kind"] for call in projection_calls] == [
        "CREATE_UNKNOWN_QUARANTINED",
        "RECONCILED_ACTIVE",
    ]
    assert deps.child_rows[CHILD_ID]["exchange_order_id"] == EXCHANGE_ID

    native.local_projection = SimpleNamespace(
        transition_kind="RECONCILED_ACTIVE"
    )
    projection_calls.clear()
    replay_read = runtime.read_authoritative_child_state(
        child_client_order_id=CHILD_ID,
        materialization_id=MATERIALIZATION_ID,
        operation_audit_id=AUDIT_ID,
        operation_idempotency_key_sha256=SHA,
    )
    assert replay_read.authoritative is True
    replay_projection = runtime.project_persisted_child_state(
        record=replace(
            _kernel_record(state=MaterializationRecordState.CREATE_UNKNOWN),
            child_state=ChildExchangeState.UNKNOWN,
            diagnostic_code="follow_up_materialization_create_outcome_unknown",
        ),
        operation="REPLAY_REPAIR",
        allow_reconciliation_read=False,
    )
    assert replay_projection.exact_replay_safe is True
    assert [call["transition_kind"] for call in projection_calls] == [
        "RECONCILED_ACTIVE"
    ]

    client = _ExchangeClient()

    @contextmanager
    def scope(_name: str):
        yield

    exchange = CanonicalFollowUpMaterializationExchange(
        rest_client=client,
        runtime_authority_check=lambda: True,
        local_order_reader=deps.order,
        execution_scope_factory=scope,
        exact_order_readback=lambda _client, **_kwargs: _exact_child_readback(
            status="CANCELLED"
        ),
        configured_portfolio_id=PORTFOLIO_ID,
        pending_raw_exchange_evidence=cache,
    )
    result = exchange.cancel_follow_up_child(
        child_client_order_id=CHILD_ID,
        correlation_id=CORRELATION_ID,
        materialization_id=MATERIALIZATION_ID,
        operation_audit_id=AUDIT_ID,
        operation_idempotency_key_sha256=SHA,
    )
    assert result.outcome is ExchangeInvocationOutcome.ACCEPTED
    assert client.cancel_calls[0][1]["verified_exchange_order_id"] == EXCHANGE_ID
    assert len(cache) == 1


def test_consumed_unclassified_create_reconciles_terminal_without_second_mutation() -> None:
    cancel_key = "2d787a07-ec55-4ab3-a1ce-063fdcde7daa"
    cancel_hash = hashlib.sha256(cancel_key.encode()).hexdigest()
    terminal_audit_id = "ddf07d8c-d6bd-4583-9f66-2217f2e24514"
    native = _NativeRepository(
        _native_attempt(
            state="CREATE_INVOCATION_STARTED",
            diagnostic="follow_up_materialization_create_outcome_unknown",
            operation_hash=SHA,
            operation_audit_id=AUDIT_ID,
        )
    )
    deps = _CountingEligibilityDependencies()
    deps.child_rows[CHILD_ID] = {
        "client_order_id": CHILD_ID,
        "product_id": "BTC-USDC",
        "side": "SELL",
        "size": "0.00001",
        "price": "100000.00",
        "parent_order_id": ROOT_ID,
        "retail_portfolio_id": PORTFOLIO_ID,
        "status": "HIDDEN",
        "exchange_order_id": None,
    }
    live_reads: list[dict[str, object]] = []

    def terminal_child_read(_client, **kwargs):
        _client.record_read()
        live_reads.append(kwargs)
        return {
            "authoritative": True,
            "exact_identity_match": True,
            "authoritative_status": "FILLED",
            "retail_portfolio_id_matches_expected": True,
            "exchange_order_id": EXCHANGE_ID,
            "matched_order": {
                "client_order_id": CHILD_ID,
                "order_id": EXCHANGE_ID,
                "product_id": "BTC-USDC",
                "side": "SELL",
                "status": "FILLED",
                "order_configuration": {
                    "limit_limit_gtc": {
                        "base_size": "0.00001",
                        "limit_price": "100000.00",
                        "post_only": False,
                    }
                },
            },
        }

    transition_calls: list[dict[str, object]] = []

    def transitioner(**kwargs):
        transition_calls.append(kwargs)
        raw_id = kwargs["exchange_order_id"]
        return SimpleNamespace(
            record=SimpleNamespace(
                materialization_id=MATERIALIZATION_ID,
                child_client_order_id=CHILD_ID,
                transition_kind=kwargs["transition_kind"],
                authoritative_order_status=kwargs[
                    "authoritative_order_status"
                ],
                exchange_order_id_sha256=(
                    hashlib.sha256(raw_id.encode()).hexdigest()
                    if raw_id
                    else None
                ),
                operation_audit_id=kwargs["operation_audit_id"],
                operation_idempotency_key_sha256=kwargs[
                    "operation_idempotency_key_sha256"
                ],
            ),
            replayed=False,
        )

    pending: dict[tuple[str, str, str, str], object] = {}
    runtime = ProductionFollowUpMaterializationRuntime(
        native_repository=native,
        rest_client=_SyntheticEligibilityClient(),
        configured_portfolio_id=PORTFOLIO_ID,
        environment="controlled_live",
        runtime_authority_check=deps.authority,
        local_order_reader=deps.order,
        template_resolver=deps.template,
        product_reader=deps.product,
        portfolio_binding_evaluator=deps.binding,
        source_order_readback=terminal_child_read,
        source_fill_readback=deps.source_fill_readback,
        market_reference_reader=deps.market,
        standing_price_evaluator=deps.standing,
        wallet_reader=deps.wallets,
        action_guard_evaluator=deps.guard,
        child_persister=deps.persist_child,
        local_stealth_reader=lambda child_id: deps.stealth_rows.get(child_id),
        local_state_transitioner=transitioner,
        pending_raw_exchange_evidence=pending,
    )
    child_evidence = runtime.read_authoritative_child_state(
        child_client_order_id=CHILD_ID,
        materialization_id=MATERIALIZATION_ID,
        operation_audit_id=AUDIT_ID,
        operation_idempotency_key_sha256=SHA,
    )
    assert child_evidence.state is ChildExchangeState.TERMINAL
    assert child_evidence.coinbase_read_started is True

    create_unknown_event = SimpleNamespace(
        event_id="80170d7e-5379-4a9b-a811-d6a32fdbfa28",
        materialization_id=MATERIALIZATION_ID,
        state="CREATE_UNKNOWN_CONSUMED",
        diagnostic_code="follow_up_materialization_create_outcome_unknown",
        exchange_order_id_sha256=None,
        operation_idempotency_key_sha256=SHA,
        operation_audit_id=AUDIT_ID,
        actor_id="operator",
        roles=("trader",),
        environment="controlled_live",
        operator_intent="authorize_and_materialize_follow_up_intent",
        correlation_id=CORRELATION_ID,
        recorded_at="2026-07-18T12:00:02+00:00",
    )
    terminal_event = SimpleNamespace(
        **{
            **vars(create_unknown_event),
            "event_id": "25a446fb-b257-4bc7-9b55-6dc0ecbeab7e",
            "state": "CANCEL_NOT_REQUIRED_TERMINAL",
            "diagnostic_code": (
                "follow_up_materialization_child_already_terminal"
            ),
            "exchange_order_id_sha256": hashlib.sha256(
                EXCHANGE_ID.encode()
            ).hexdigest(),
            "operation_idempotency_key_sha256": cancel_hash,
            "operation_audit_id": terminal_audit_id,
        }
    )
    native.audit_events = [create_unknown_event, terminal_event]
    native.local_projection = None
    native.attempt = _native_attempt(
        state="CANCEL_NOT_REQUIRED_TERMINAL",
        diagnostic="follow_up_materialization_child_already_terminal",
        exchange_hash=hashlib.sha256(EXCHANGE_ID.encode()).hexdigest(),
        operation_hash=cancel_hash,
        operation_audit_id=terminal_audit_id,
    )
    terminal_record = replace(
        _kernel_record(state=MaterializationRecordState.CHILD_ALREADY_TERMINAL),
        cancel_idempotency_key_sha256=cancel_hash,
        child_state=ChildExchangeState.TERMINAL,
        diagnostic_code="follow_up_materialization_child_already_terminal",
        audit_id=terminal_audit_id,
    )

    projection = runtime.project_persisted_child_state(
        record=terminal_record,
        operation="TERMINAL_READ",
        allow_reconciliation_read=False,
    )

    assert projection.live_read_count == 0
    assert len(live_reads) == 1
    assert [call["transition_kind"] for call in transition_calls] == [
        "CREATE_UNKNOWN_QUARANTINED",
        "TERMINAL_WITHOUT_CANCEL",
    ]
    assert all(call["exchange_order_id"] is None for call in transition_calls[:1])
    assert transition_calls[-1]["exchange_order_id"] == EXCHANGE_ID


def test_authoritative_child_reconciliation_reports_every_sdk_read() -> None:
    calls: list[str] = []

    class _CountingReadClient:
        def get_api_key_permissions(self):
            calls.append("get_api_key_permissions")
            return {
                "portfolio_uuid": PORTFOLIO_ID,
                "portfolio_type": "CONSUMER",
                "can_view": True,
                "can_trade": True,
            }

        def list_portfolios(self):
            calls.append("list_portfolios")
            return [
                {
                    "uuid": PORTFOLIO_ID,
                    "name": "Test",
                    "type": "CONSUMER",
                }
            ]

        def get_order(self, exchange_order_id: str):
            calls.append("get_order")
            assert exchange_order_id == EXCHANGE_ID
            return {
                "order": {
                    "client_order_id": CHILD_ID,
                    "order_id": EXCHANGE_ID,
                    "status": "OPEN",
                    "product_id": "BTC-USDC",
                    "product_type": "SPOT",
                    "side": "SELL",
                    "order_type": "LIMIT",
                    "time_in_force": "GTC",
                    "base_size": "0.00001",
                    "limit_price": "100000.00",
                    "retail_portfolio_id": PORTFOLIO_ID,
                    "order_configuration": {
                        "limit_limit_gtc": {
                            "base_size": "0.00001",
                            "limit_price": "100000.00",
                            "post_only": False,
                        }
                    },
                }
            }

    deps = _CountingEligibilityDependencies()
    deps.child_rows[CHILD_ID] = {
        "client_order_id": CHILD_ID,
        "product_id": "BTC-USDC",
        "side": "SELL",
        "size": "0.00001",
        "price": "100000.00",
        "parent_order_id": ROOT_ID,
        "retail_portfolio_id": PORTFOLIO_ID,
        "status": "OPEN",
        "exchange_order_id": EXCHANGE_ID,
    }
    runtime = ProductionFollowUpMaterializationRuntime(
        native_repository=_NativeRepository(),
        rest_client=_CountingReadClient(),
        configured_portfolio_id=PORTFOLIO_ID,
        environment="controlled_live",
        runtime_authority_check=lambda: True,
        local_order_reader=deps.order,
        template_resolver=deps.template,
        product_reader=deps.product,
        portfolio_binding_evaluator=lambda client, expected_id: (
            evaluate_spot_test_portfolio_binding(
                rest_client=client,
                expected_portfolio_id=expected_id,
                expected_portfolio_label="Test",
            )
        ),
        source_order_readback=_single_page_materialization_order_readback,
        source_fill_readback=deps.source_fill_readback,
        market_reference_reader=deps.market,
        standing_price_evaluator=deps.standing,
        wallet_reader=deps.wallets,
        action_guard_evaluator=deps.guard,
        child_persister=deps.persist_child,
        local_stealth_reader=lambda child_id: deps.stealth_rows.get(child_id),
    )

    state = runtime.read_authoritative_child_state(
        child_client_order_id=CHILD_ID,
        materialization_id=MATERIALIZATION_ID,
        operation_audit_id=AUDIT_ID,
        operation_idempotency_key_sha256=SHA,
    )

    assert state.authoritative is True
    assert state.state is ChildExchangeState.ACTIVE
    assert state.coinbase_read_started is True
    assert state.read_count == 3
    assert state.individual_retry_count == 0
    assert calls == ["get_api_key_permissions", "list_portfolios", "get_order"]


def test_child_read_fails_closed_when_authoritative_payload_identity_conflicts() -> None:
    deps = _CountingEligibilityDependencies()
    deps.child_rows[CHILD_ID] = {
        "client_order_id": CHILD_ID,
        "product_id": "BTC-USDC",
        "side": "SELL",
        "size": "0.00001",
        "price": "100000.00",
        "parent_order_id": ROOT_ID,
        "retail_portfolio_id": PORTFOLIO_ID,
        "status": "SUBMISSION_UNKNOWN",
        "exchange_order_id": None,
    }
    updates: list[tuple[str, str, str | None]] = []
    cache: dict[str, str] = {}

    def conflicting_child_readback(_client, **_kwargs):
        return {
            "authoritative": True,
            "exact_identity_match": True,
            "authoritative_status": "OPEN",
            "retail_portfolio_id_matches_expected": True,
            "exchange_order_id": EXCHANGE_ID,
            "matched_order": {
                "client_order_id": SOURCE_ID,
                "order_id": EXCHANGE_ID,
                "product_id": "ETH-USDC",
                "status": "OPEN",
            },
        }

    runtime = ProductionFollowUpMaterializationRuntime(
        native_repository=_NativeRepository(),
        rest_client=object(),
        configured_portfolio_id=PORTFOLIO_ID,
        environment="controlled_live",
        runtime_authority_check=deps.authority,
        local_order_reader=deps.order,
        template_resolver=deps.template,
        product_reader=deps.product,
        portfolio_binding_evaluator=deps.binding,
        source_order_readback=conflicting_child_readback,
        source_fill_readback=deps.source_fill_readback,
        market_reference_reader=deps.market,
        standing_price_evaluator=deps.standing,
        wallet_reader=deps.wallets,
        action_guard_evaluator=deps.guard,
        child_persister=deps.persist_child,
        local_stealth_reader=lambda child_id: deps.stealth_rows.get(child_id),
        pending_raw_exchange_evidence=cache,
    )

    state = runtime.read_authoritative_child_state(
        child_client_order_id=CHILD_ID,
        materialization_id=MATERIALIZATION_ID,
        operation_audit_id=AUDIT_ID,
        operation_idempotency_key_sha256=SHA,
    )
    assert state.state is ChildExchangeState.UNKNOWN
    assert state.authoritative is False
    assert state.ambiguous is True
    assert state.exchange_order_id_sha256 is None
    assert updates == []
    assert cache == {}


def test_native_repository_adapter_binds_invocation_guard_to_configured_goal() -> None:
    calls: list[dict[str, str]] = []

    class _GoalBoundNative:
        @contextmanager
        def follow_up_live_proof_invocation_guard(self, **kwargs):
            calls.append(dict(kwargs))
            yield

    adapter = NativeFollowUpMaterializationRepositoryAdapter(
        _GoalBoundNative(),
        live_proof_goal_id="operator_fill_triggered_follow_up_activation_v1",
    )

    with adapter.live_proof_invocation_guard(
        source_client_order_id=SOURCE_ID
    ):
        pass

    assert calls == [
        {
            "goal_id": "operator_fill_triggered_follow_up_activation_v1",
            "source_client_order_id": SOURCE_ID,
        }
    ]


class _KernelService:
    def __init__(self, result: MaterializationOperationResult | None = None) -> None:
        self.result = result
        self.calls: list[str] = []

    def read(self, **kwargs):
        raise AssertionError("facade passive read must not invoke kernel runtime")

    def materialize(self, **kwargs):
        self.calls.append("materialize")
        assert self.result is not None
        return self.result

    def safe_closeout(self, **kwargs):
        self.calls.append("safe_closeout")
        assert self.result is not None
        return self.result


def test_facade_passive_read_is_local_only_and_withholds_private_ids() -> None:
    native = _NativeRepository(
        _native_attempt(
            state="CREATE_ACCEPTED_NONTERMINAL",
            diagnostic="follow_up_materialization_create_accepted",
            exchange_hash="b" * 64,
        )
    )
    facade = OperatorFollowUpMaterializationFacade(
        service=_KernelService(), native_repository=native
    )

    response = facade.read(source_client_order_id=SOURCE_ID)
    payload = response.model_dump(mode="json")
    assert response.current_request_activity.sdk_mutation_invocation_state == "NOT_INVOKED"
    assert response.current_request_activity.transport_submission_state == "NOT_SUBMITTED"
    assert response.current_request_activity.exchange_mutation_state == "NOT_MUTATED"
    assert response.current_request_activity.read_accounting_state == "EXACT"
    assert response.current_request_activity.observed_read_count == 0
    assert response.durable_live_proof_activity.create is not None
    assert response.read_only is True
    assert response.live_coinbase_read_ran is False
    assert response.attempt.exchange_order_id_present is True
    assert len(response.audit_events) == 1
    assert response.audit_events[0].exchange_order_id_present is True
    assert response.local_projection is not None
    assert response.local_projection.order_parent_and_stealth_match is True
    assert response.local_projection.exchange_order_id_present is True
    assert response.safe_closeout_eligibility.request_eligible is True
    assert (
        response.authorization_request_forwardability.request_forwardable
        is False
    )
    assert (
        response.authorization_request_forwardability.backend_decision
        == "blocked"
    )
    assert (
        response.authorization_request_forwardability.blockers
        == response.eligibility.blockers
    )
    assert response.authorization_request_forwardability.acknowledgement_only is True
    assert response.authorization_request_forwardability.live_eligibility is False
    assert (
        response.authorization_request_forwardability.exchange_call_authority
        is False
    )
    assert (
        response.authorization_request_forwardability.browser_authority
        == "display_and_forward_fresh_acknowledgement_only"
    )
    assert (
        response.safe_closeout_eligibility.backend_decision
        == "eligible_for_authoritative_read"
    )
    assert "portfolio_id" not in str(payload)
    assert "private-operator-id" not in str(payload)
    assert "operation_idempotency_key_sha256" not in str(payload)
    assert EXCHANGE_ID not in str(payload)
    assert native.calls == [
        ("read", SOURCE_ID),
        ("events", MATERIALIZATION_ID),
        ("projection", MATERIALIZATION_ID),
        ("activity", SOURCE_ID),
    ]


def test_facade_passive_read_without_attempt_has_no_audit_projection() -> None:
    native = _NativeRepository()
    facade = OperatorFollowUpMaterializationFacade(
        service=_KernelService(), native_repository=native
    )

    response = facade.read(source_client_order_id=SOURCE_ID)

    assert response.attempt is None
    assert response.audit_events == []
    assert response.local_projection is None
    assert response.safe_closeout_eligibility.request_eligible is False
    assert response.safe_closeout_eligibility.backend_decision == "blocked"
    assert response.safe_closeout_eligibility.blockers == [
        "materialization_not_started"
    ]
    assert response.eligibility.blockers == [
        "fresh_live_authorization_required"
    ]
    assert (
        response.authorization_request_forwardability.request_forwardable
        is True
    )
    assert (
        response.authorization_request_forwardability.backend_decision
        == "forward_fresh_acknowledgement_only"
    )
    assert response.authorization_request_forwardability.blockers == []
    assert response.authorization_request_forwardability.acknowledgement_only is True
    assert response.authorization_request_forwardability.live_eligibility is False
    assert (
        response.authorization_request_forwardability.exchange_call_authority
        is False
    )
    assert (
        response.authorization_request_forwardability.browser_authority
        == "display_and_forward_fresh_acknowledgement_only"
    )
    assert native.calls == [("read", SOURCE_ID), ("activity", SOURCE_ID)]


def test_facade_terminal_goal_readback_is_blocked_and_not_forwardable() -> None:
    native = _NativeRepository(
        readiness_blockers=("follow_up_live_proof_goal_terminal",),
    )
    facade = OperatorFollowUpMaterializationFacade(
        service=_KernelService(), native_repository=native
    )

    response = facade.read(source_client_order_id=SOURCE_ID)

    assert response.eligibility.ready is False
    assert response.eligibility.backend_decision == "blocked"
    assert response.eligibility.blockers == [
        "follow_up_live_proof_goal_terminal",
        "fresh_live_authorization_required",
    ]
    assert (
        response.authorization_request_forwardability.request_forwardable
        is False
    )
    assert (
        response.authorization_request_forwardability.backend_decision
        == "blocked"
    )
    assert response.authorization_request_forwardability.blockers == (
        response.eligibility.blockers
    )
    assert response.safe_closeout_eligibility.request_eligible is False
    assert native.calls == [("read", SOURCE_ID), ("activity", SOURCE_ID)]


def test_facade_existing_exact_child_safe_closeout_remains_visible() -> None:
    native = _NativeRepository(
        _native_attempt(
            state="CREATE_ACCEPTED_NONTERMINAL",
            diagnostic="follow_up_materialization_create_accepted",
            exchange_hash="b" * 64,
        ),
    )
    facade = OperatorFollowUpMaterializationFacade(
        service=_KernelService(), native_repository=native
    )

    response = facade.read(source_client_order_id=SOURCE_ID)

    assert response.safe_closeout_eligibility.request_eligible is True
    assert response.safe_closeout_eligibility.backend_decision == (
        "eligible_for_authoritative_read"
    )
    assert response.safe_closeout_eligibility.blockers == []


def test_facade_passive_read_retains_eligibility_activity_without_attempt() -> None:
    native = _NativeRepository()
    native.live_proof_records["ELIGIBILITY_READ"] = native._live_proof(
        "ELIGIBILITY_READ",
        event_state="TERMINAL",
        outcome="BLOCKED",
        observed_read_count=1,
    )
    facade = OperatorFollowUpMaterializationFacade(
        service=_KernelService(), native_repository=native
    )

    response = facade.read(source_client_order_id=SOURCE_ID)

    assert response.attempt is None
    assert response.durable_live_proof_activity.eligibility_read is not None
    assert response.durable_live_proof_activity.create is None
    assert native.calls == [("read", SOURCE_ID), ("activity", SOURCE_ID)]


def test_facade_marks_unclassified_consumed_create_closeout_eligible() -> None:
    native = _NativeRepository(
        _native_attempt(
            state="CREATE_INVOCATION_STARTED",
            diagnostic="follow_up_materialization_create_outcome_unknown",
            operation_hash=SHA,
            operation_audit_id=AUDIT_ID,
        )
    )
    facade = OperatorFollowUpMaterializationFacade(
        service=_KernelService(), native_repository=native
    )

    response = facade.read(source_client_order_id=SOURCE_ID)

    assert response.attempt.state == "CREATE_INVOCATION_STARTED"
    assert (
        response.durable_live_proof_activity.create.sdk_mutation_invocation_state
        == "UNKNOWN"
    )
    assert (
        response.durable_live_proof_activity.create.transport_submission_state
        == "POSSIBLY_SUBMITTED"
    )
    assert response.safe_closeout_eligibility.request_eligible is True
    assert (
        response.safe_closeout_eligibility.backend_decision
        == "eligible_for_authoritative_read"
    )
    assert response.safe_closeout_eligibility.blockers == []
    assert response.live_coinbase_read_ran is False


def test_facade_blocks_safe_closeout_when_create_was_blocked_before_sdk() -> None:
    native = _NativeRepository(
        _native_attempt(
            state="CREATE_UNKNOWN_CONSUMED",
            diagnostic="follow_up_materialization_runtime_authority_lost",
            operation_hash=SHA,
            operation_audit_id=AUDIT_ID,
        )
    )
    native.live_proof_records["CREATE"] = native._live_proof(
        "CREATE",
        event_state="TERMINAL",
        outcome="BLOCKED",
        sdk_state="NOT_INVOKED",
        transport_state="NOT_SUBMITTED",
        exchange_state="NOT_MUTATED",
        read_state="EXACT",
        observed_read_count=0,
    )
    facade = OperatorFollowUpMaterializationFacade(
        service=_KernelService(), native_repository=native
    )

    response = facade.read(source_client_order_id=SOURCE_ID)

    assert response.durable_live_proof_activity.create is not None
    assert response.durable_live_proof_activity.create.terminal_outcome == "BLOCKED"
    assert response.safe_closeout_eligibility.request_eligible is False
    assert response.safe_closeout_eligibility.backend_decision == "blocked"
    assert response.safe_closeout_eligibility.blockers == [
        "create_blocked_before_sdk_invocation"
    ]


def test_facade_blocks_safe_closeout_without_durable_create_evidence() -> None:
    native = _NativeRepository(
        _native_attempt(
            state="CREATE_UNKNOWN_CONSUMED",
            diagnostic="follow_up_materialization_create_outcome_unknown",
            operation_hash=SHA,
            operation_audit_id=AUDIT_ID,
        )
    )
    native.live_proof_records.pop("CREATE")
    facade = OperatorFollowUpMaterializationFacade(
        service=_KernelService(), native_repository=native
    )

    response = facade.read(source_client_order_id=SOURCE_ID)

    assert response.durable_live_proof_activity.create is None
    assert response.safe_closeout_eligibility.request_eligible is False
    assert response.safe_closeout_eligibility.backend_decision == "blocked"
    assert response.safe_closeout_eligibility.blockers == [
        "create_safe_closeout_evidence_unproven"
    ]


def test_facade_blocks_safe_closeout_after_explicit_create_rejection() -> None:
    native = _NativeRepository(
        _native_attempt(
            state="CREATE_EXPLICITLY_REJECTED",
            diagnostic="follow_up_materialization_create_rejected",
            operation_hash=SHA,
            operation_audit_id=AUDIT_ID,
        )
    )
    facade = OperatorFollowUpMaterializationFacade(
        service=_KernelService(), native_repository=native
    )

    response = facade.read(source_client_order_id=SOURCE_ID)

    assert response.safe_closeout_eligibility.request_eligible is False
    assert response.safe_closeout_eligibility.backend_decision == "blocked"
    assert response.safe_closeout_eligibility.blockers == ["create_rejected"]
    assert response.durable_live_proof_activity.create.terminal_outcome == "REJECTED"


def test_facade_fails_closed_on_durable_operation_attempt_identity_mismatch() -> None:
    native = _NativeRepository(
        _native_attempt(
            state="CREATE_EXPLICITLY_REJECTED",
            diagnostic="follow_up_materialization_create_rejected",
            operation_hash=SHA,
            operation_audit_id=AUDIT_ID,
        )
    )
    native.live_proof_records["CREATE"].materialization_id = (
        "2bf82c2d-319c-47d4-b2ce-f22c02dc0e01"
    )
    facade = OperatorFollowUpMaterializationFacade(
        service=_KernelService(), native_repository=native
    )

    with pytest.raises(
        OperatorFollowUpMaterializationError,
        match="follow_up_materialization_backend_unavailable",
    ):
        facade.read(source_client_order_id=SOURCE_ID)


def test_facade_maps_kernel_create_result_to_typed_sanitized_response() -> None:
    native_attempt = _native_attempt(
        state="CREATE_ACCEPTED_NONTERMINAL",
        diagnostic="follow_up_materialization_create_accepted",
        exchange_hash="b" * 64,
    )
    native = _NativeRepository(native_attempt)
    eligibility = FreshMaterializationEligibility(
        candidate=_candidate(),
        fresh=True,
        eligibility_pass_count=1,
        reconciliation_pass_count=1,
        individual_retry_count=0,
        ambiguous=False,
        blockers=(),
        coinbase_read_started=True,
        coinbase_read_count=1,
    )
    kernel = _KernelService(
        MaterializationOperationResult(
            record=_kernel_record(),
            diagnostic_code="follow_up_materialization_create_accepted",
            replayed=False,
            live_read_ran=True,
            create_call_ran=True,
            cancel_call_ran=False,
            eligibility=eligibility,
            candidate=_candidate(),
        )
    )
    facade = OperatorFollowUpMaterializationFacade(
        service=kernel, native_repository=native
    )
    response = facade.materialize(
        source_client_order_id=SOURCE_ID,
        request=SimpleNamespace(),
        context=SimpleNamespace(
            correlation_id=CORRELATION_ID,
            audit_id=AUDIT_ID,
            idempotency_key=IDEMPOTENCY_KEY,
        ),
    )
    assert response.status is AdminApiCommandStatus.ACCEPTED
    assert response.current_request_activity.sdk_mutation_invocation_state == "INVOKED"
    assert (
        response.current_request_activity.transport_submission_state
        == "CONFIRMED_SUBMITTED"
    )
    assert response.current_request_activity.exchange_mutation_state == "CONFIRMED_MUTATED"
    assert response.current_request_activity.read_accounting_state == "EXACT"
    assert response.current_request_activity.observed_read_count == 2
    assert response.durable_live_proof_activity.eligibility_read is not None
    assert response.durable_live_proof_activity.create is not None
    assert response.live_coinbase_create_call_count == 1
    assert response.live_exchange_submitted is True
    assert response.candidate.child_client_order_id == CHILD_ID
    assert response.attempt.exchange_order_id_present is True
    assert PORTFOLIO_ID not in str(response.model_dump(mode="json"))
    assert EXCHANGE_ID not in str(response.model_dump(mode="json"))


def test_facade_replay_reports_zero_current_activity_and_preserves_durable_create() -> None:
    native = _NativeRepository(
        _native_attempt(
            state="CREATE_ACCEPTED_NONTERMINAL",
            diagnostic="follow_up_materialization_create_accepted",
            exchange_hash="b" * 64,
        )
    )
    kernel = _KernelService(
        MaterializationOperationResult(
            record=_kernel_record(),
            diagnostic_code="follow_up_materialization_create_accepted",
            replayed=True,
            live_read_ran=False,
            create_call_ran=False,
            cancel_call_ran=False,
            candidate=_candidate(),
        )
    )
    facade = OperatorFollowUpMaterializationFacade(
        service=kernel, native_repository=native
    )

    response = facade.materialize(
        source_client_order_id=SOURCE_ID,
        request=SimpleNamespace(),
        context=SimpleNamespace(
            correlation_id="fresh-http-correlation",
            audit_id=AUDIT_ID,
            idempotency_key=IDEMPOTENCY_KEY,
        ),
    )

    assert response.replayed is True
    assert response.current_request_activity == response.current_request_activity.model_validate(
        {
            "sdk_mutation_invocation_state": "NOT_INVOKED",
            "transport_submission_state": "NOT_SUBMITTED",
            "exchange_mutation_state": "NOT_MUTATED",
            "read_accounting_state": "EXACT",
            "observed_read_count": 0,
        }
    )
    assert response.live_coinbase_read_ran is False
    assert response.live_coinbase_create_call_count == 0
    assert response.live_exchange_submitted is False
    assert response.exchange_state_mutated is False
    assert (
        response.durable_live_proof_activity.create.exchange_mutation_state
        == "CONFIRMED_MUTATED"
    )


def test_facade_nonreplay_unknown_preserves_possible_submission_and_unknown_reads() -> None:
    native = _NativeRepository(
        _native_attempt(
            state="CREATE_UNKNOWN_CONSUMED",
            diagnostic="follow_up_materialization_create_outcome_unknown",
            operation_hash=SHA,
            operation_audit_id=AUDIT_ID,
        )
    )
    kernel = _KernelService(
        MaterializationOperationResult(
            record=_kernel_record(state=MaterializationRecordState.CREATE_UNKNOWN),
            diagnostic_code="follow_up_materialization_create_outcome_unknown",
            replayed=False,
            live_read_ran=True,
            create_call_ran=False,
            cancel_call_ran=False,
            candidate=_candidate(),
        )
    )
    facade = OperatorFollowUpMaterializationFacade(
        service=kernel, native_repository=native
    )

    response = facade.materialize(
        source_client_order_id=SOURCE_ID,
        request=SimpleNamespace(),
        context=SimpleNamespace(
            correlation_id=CORRELATION_ID,
            audit_id=AUDIT_ID,
            idempotency_key=IDEMPOTENCY_KEY,
        ),
    )

    assert response.current_request_activity.sdk_mutation_invocation_state == "UNKNOWN"
    assert response.current_request_activity.transport_submission_state == "POSSIBLY_SUBMITTED"
    assert response.current_request_activity.exchange_mutation_state == "UNKNOWN"
    assert response.current_request_activity.read_accounting_state == "UNKNOWN"
    assert response.current_request_activity.observed_read_count is None
    assert response.live_coinbase_create_call_count == 0
    assert response.live_exchange_submitted is False
    assert response.exchange_state_mutated is False
