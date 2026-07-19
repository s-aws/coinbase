from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal

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
    LocalChildPersistenceEvidence,
    LocalChildProjectionEvidence,
    MaterializationAuthorization,
    MaterializationRecordState,
    OperatorFollowUpMaterializationError,
    OperatorFollowUpMaterializationService,
    OperatorFollowUpMaterializationRequestContext,
    SafeCloseoutAuthorization,
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
    ) -> LocalChildProjectionEvidence:
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


@dataclass
class FakeExchange:
    create_result: ExchangeInvocationResult = field(
        default_factory=lambda: ExchangeInvocationResult(
            outcome=ExchangeInvocationOutcome.ACCEPTED,
            child_state=ChildExchangeState.ACTIVE,
            exchange_call_started=True,
        )
    )
    cancel_result: ExchangeInvocationResult = field(
        default_factory=lambda: ExchangeInvocationResult(
            outcome=ExchangeInvocationOutcome.ACCEPTED,
            child_state=ChildExchangeState.TERMINAL,
            exchange_call_started=True,
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
    assert repository.events == [
        "read:CREATE",
        "prepare",
        "mark_create",
        "record_create:ACCEPTED",
    ]
    assert runtime.events == ["eligibility", "persist_child"]
    assert runtime.projection_events == ["CREATE"]
    assert runtime.observed_projection_records[-1].state == (
        MaterializationRecordState.CREATE_ACCEPTED
    )
    assert exchange.events == ["create"]


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
    assert repository.events[-1] == f"record_create:{exchange_result.outcome.value}"


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
    assert repository.events[-1] == "record_create:UNKNOWN"


def test_known_pre_call_failure_consumes_boundary_but_reports_zero_coinbase_calls():
    exchange = FakeExchange(
        create_result=ExchangeInvocationResult(
            outcome=ExchangeInvocationOutcome.UNKNOWN,
            child_state=ChildExchangeState.UNKNOWN,
            exchange_call_started=False,
        )
    )
    service, _repository, _runtime, _exchange = _service(exchange=exchange)

    result = service.materialize(
        source_client_order_id="source-001",
        request=_authorization(),
        context=_context(),
    )

    assert result.record.state == MaterializationRecordState.CREATE_UNKNOWN
    assert result.record.create_call_consumed is True
    assert result.create_call_ran is False


def test_accepted_create_persists_only_normalized_exchange_order_id_hash():
    exchange = FakeExchange(
        create_result=ExchangeInvocationResult(
            outcome=ExchangeInvocationOutcome.ACCEPTED,
            child_state=ChildExchangeState.ACTIVE,
            exchange_call_started=True,
            exchange_order_id_sha256="A" * 64,
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
def test_raw_or_invalid_create_exchange_order_id_evidence_is_dropped(unsafe_value):
    exchange = FakeExchange(
        create_result=ExchangeInvocationResult(
            outcome=ExchangeInvocationOutcome.ACCEPTED,
            child_state=ChildExchangeState.ACTIVE,
            exchange_call_started=True,
            exchange_order_id_sha256=unsafe_value,
        )
    )
    service, repository, _runtime, _exchange = _service(exchange=exchange)

    service.materialize(
        source_client_order_id="source-001",
        request=_authorization(),
        context=_context(),
    )

    assert repository.last_create_result is not None
    assert repository.last_create_result.exchange_order_id_sha256 is None


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


def test_projection_failure_happens_after_result_journal_and_replay_never_recreates():
    runtime = FakeRuntime(projection_succeeds=False)
    service, repository, runtime, exchange = _service(runtime=runtime)

    with pytest.raises(OperatorFollowUpMaterializationError) as exc_info:
        service.materialize(
            source_client_order_id="source-001",
            request=_authorization(),
            context=_context(),
        )

    assert exc_info.value.code == "follow_up_materialization_child_projection_invalid"
    assert repository.events[-1] == "record_create:ACCEPTED"
    assert exchange.events == ["create"]
    runtime.projection_succeeds = True

    replay = service.materialize(
        source_client_order_id="source-001",
        request=_authorization(),
        context=_context(),
    )

    assert replay.replayed is True
    assert replay.record.state == MaterializationRecordState.CREATE_ACCEPTED
    assert runtime.projection_events == ["CREATE", "REPLAY_REPAIR"]
    assert exchange.events == ["create"]


def test_crash_repair_may_use_one_exact_read_but_never_repeats_create():
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
    assert replay.live_read_ran is True
    assert runtime.projection_events == ["REPLAY_REPAIR"]
    assert exchange.events == []


@pytest.mark.parametrize(
    ("child_evidence", "expected_projection_operation"),
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
def test_create_invocation_started_same_key_replay_journals_unknown_before_one_read(
    child_evidence: ChildStateEvidence,
    expected_projection_operation: str,
):
    trace: list[str] = []

    class TracingRepository(FakeRepository):
        def record_create_result(self, *, materialization_id: str, result):
            trace.append("journal_create_unknown")
            return super().record_create_result(
                materialization_id=materialization_id,
                result=result,
            )

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
        context=replace(_context(), correlation_id="replay-correlation-new"),
    )

    assert result.record.state is MaterializationRecordState.CREATE_UNKNOWN
    assert result.record.create_call_consumed is True
    assert result.replayed is True
    assert result.live_read_ran is True
    assert result.create_call_ran is False
    assert result.cancel_call_ran is False
    assert repository.events == ["read:CREATE", "record_create:UNKNOWN"]
    assert runtime.events == ["child_state"]
    assert runtime.projection_events == [expected_projection_operation]
    assert trace == [
        "journal_create_unknown",
        "read_exact_child",
        f"project:{expected_projection_operation}:allow_read=False",
    ]
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
    assert runtime.observed_child_read_binding == {
        "child_client_order_id": existing.child_client_order_id,
        "materialization_id": existing.materialization_id,
        "operation_audit_id": existing.audit_id,
        "operation_idempotency_key_sha256": (
            existing.create_idempotency_key_sha256
        ),
    }


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
    assert repository.events == [
        "read:CREATE",
        "prepare",
        "mark_create",
        "record_create:ACCEPTED",
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
        def record_create_result(self, *, materialization_id: str, result):
            self.events.append(f"record_create:{result.outcome.value}")
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
    assert repository.events[-1] == "record_create:ACCEPTED"
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
    assert runtime.projection_events == ["TERMINAL_READ"]
    assert exchange.events == []
    assert "mark_cancel" not in repository.events
    assert repository.events == [
        "read:CANCEL",
        "record_child_terminal_without_cancel",
    ]
    assert repository.last_cancel_result.exchange_order_id_sha256 == "d" * 64
    assert repository.last_terminal_context == {
        "idempotency_key": "cancel-key-001",
        "actor_id": "operator-001",
        "roles": ("trader",),
        "environment": "local-controlled-live",
        "operator_intent": SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT,
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
    assert repository.events == [
        "read:CANCEL",
        "mark_cancel",
        "record_cancel:ACCEPTED",
    ]
    assert runtime.events == ["child_state"]
    assert runtime.projection_events == ["REPLAY_REPAIR", "CANCEL"]
    assert exchange.events == ["cancel"]
    assert runtime.observed_child_read_binding == {
        "child_client_order_id": "child-001",
        "materialization_id": "materialization-001",
        "operation_audit_id": "audit-001",
        "operation_idempotency_key_sha256": (
            _record().create_idempotency_key_sha256
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
    assert repository.events == [
        "read:CANCEL",
        "mark_cancel",
        "record_cancel:ACCEPTED",
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
    assert repository.events == [
        "read:CANCEL",
        "record_create:UNKNOWN",
        "mark_cancel",
        "record_cancel:ACCEPTED",
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
    assert repository.events == [
        "read:CANCEL",
        "record_create:UNKNOWN",
        "record_child_terminal_without_cancel",
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
    assert repository.events == [
        "read:CANCEL",
        "record_child_terminal_without_cancel",
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
    assert repository.events[-1] == "record_cancel:UNKNOWN"


def test_cancel_result_persistence_failure_reports_consumed_live_boundary():
    class BrokenResultRepository(FakeRepository):
        def record_cancel_result(self, *, materialization_id: str, result):
            self.events.append(f"record_cancel:{result.outcome.value}")
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
    assert repository.events[-1] == "record_cancel:ACCEPTED"
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
    ("child_evidence", "expected_projection_operation"),
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
def test_cancel_invocation_started_same_key_replay_journals_unknown_before_one_read(
    child_evidence: ChildStateEvidence,
    expected_projection_operation: str,
):
    trace: list[str] = []

    class TracingRepository(FakeRepository):
        def record_cancel_result(self, *, materialization_id: str, result):
            trace.append("journal_cancel_unknown")
            return super().record_cancel_result(
                materialization_id=materialization_id,
                result=result,
            )

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
            correlation_id="replay-correlation-new",
        ),
    )

    assert result.record.state is MaterializationRecordState.CANCEL_UNKNOWN
    assert result.record.create_call_consumed is True
    assert result.record.cancel_call_consumed is True
    assert result.replayed is True
    assert result.live_read_ran is True
    assert result.create_call_ran is False
    assert result.cancel_call_ran is False
    assert repository.events == ["read:CANCEL", "record_cancel:UNKNOWN"]
    assert runtime.events == ["child_state"]
    assert runtime.projection_events == [expected_projection_operation]
    assert trace == [
        "journal_cancel_unknown",
        "read_exact_child",
        f"project:{expected_projection_operation}:allow_read=False",
    ]
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
    assert runtime.observed_child_read_binding == {
        "child_client_order_id": existing.child_client_order_id,
        "materialization_id": existing.materialization_id,
        "operation_audit_id": existing.audit_id,
        "operation_idempotency_key_sha256": (
            existing.cancel_idempotency_key_sha256
        ),
    }


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
