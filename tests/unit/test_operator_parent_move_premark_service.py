from __future__ import annotations

import pytest

from application.admin_api.operator_parent_move_premark_policy import (
    ParentMovePremarkPolicyTerms,
)
from application.admin_api.operator_parent_move_premark_service import (
    ParentMoveCommandContext,
    ParentMoveExecuteRequest,
    ParentMovePremarkRequest,
    ParentMoveRuntimeOutcome,
    ParentMoveSafeCloseoutRequest,
    OperatorParentMovePremarkService,
    OperatorParentMoveServiceError,
)


SOURCE_ID = "11111111-1111-4111-8111-111111111111"
SUCCESSOR_ID = "22222222-2222-4222-8222-222222222222"
PORTFOLIO_SHA256 = "a" * 64
CONFIRMATION_SHA256 = "b" * 64


def _source() -> dict[str, object]:
    return {
        "client_order_id": SOURCE_ID,
        "parent_order_id": None,
        "ownership_provenance": "ADMIN_MANUAL_ROOT",
        "portfolio_scope_sha256": PORTFOLIO_SHA256,
        "product_id": "BTC-USDC",
        "side": "BUY",
        "size": "0.001",
        "limit_price": "900",
        "filled_size": "0",
        "status": "OPEN",
        "order_type": "LIMIT",
        "time_in_force": "GOOD_UNTIL_CANCELLED",
        "authoritatively_nonterminal": True,
        "cancel_eligible": True,
        "post_only_compatible": True,
    }


def _terms() -> ParentMovePremarkPolicyTerms:
    return ParentMovePremarkPolicyTerms(
        terms_complete=True,
        policy_revision="PARENT_MOVE_PREMARK_V1",
        portfolio_scope_sha256=PORTFOLIO_SHA256,
        approved_product_id="BTC-USDC",
        price_increment="0.01",
        base_increment="0.00000001",
        base_min_size="0.00000001",
        quote_min_size="0.01",
        max_submitted_notional_usdc="3.10",
        max_possible_execution_notional_usdc="1.00",
    )


def _context(intent: str) -> ParentMoveCommandContext:
    return ParentMoveCommandContext(
        actor_id="operator@example.test",
        roles=("admin",),
        idempotency_key=f"idem-{intent}",
        correlation_id=f"corr-{intent}",
        audit_id=f"audit-{intent}",
        operator_intent=intent,
    )


class FakeOrderRepository:
    def __init__(self) -> None:
        self.source = _source()
        self.actions: list[str] = []

    def get_order(self, client_order_id: str):
        self.actions.append("get_order")
        return self.source if client_order_id == SOURCE_ID else None


class FakeRepository:
    def __init__(self) -> None:
        self.legacy_pending = False
        self.plan = None
        self.state = "UNCONSUMED"
        self.actions: list[str] = []
        self.cycles_used = 0
        self.call_count = 0
        self.plan_creates: list[dict[str, object]] = []
        self.premark_binding: dict[str, object] | None = None
        self.execute_binding: dict[str, object] | None = None
        self.source_follow_up_suppressed = False
        self.source_cancel_event_acknowledged = False
        self.source_cancel_allowance_consumed = False
        self.source_cancel_call_count = 0
        self.replacement_create_allowance_consumed = False
        self.replacement_create_call_count = 0

    def create_plan(
        self,
        *,
        plan,
        plan_sha256,
        actor_id,
        correlation_id,
        idempotency_key,
        premark_request_sha256,
        payload_sha256,
    ):
        self.actions.append("create_plan")
        self.plan_creates.append(
            {
                "plan": dict(plan),
                "plan_sha256": plan_sha256,
                "premark_request_sha256": premark_request_sha256,
                "payload_sha256": payload_sha256,
            }
        )
        self.plan = plan
        self.plan_sha256 = plan_sha256
        self.premark_binding = {
            "source_client_order_id": plan["source_client_order_id"],
            "actor_id": actor_id,
            "correlation_id": correlation_id,
            "idempotency_key": idempotency_key,
            "premark_request_sha256": premark_request_sha256,
        }
        self.state = "PLANNED"
        return {
            "state": self.state,
            "plan": plan,
            "plan_sha256": plan_sha256,
            "diagnostic_code": "operator_parent_move_plan_ready",
            "payload_sha256": payload_sha256,
        }

    def get_premark_replay(
        self,
        *,
        source_client_order_id,
        actor_id,
        correlation_id,
        idempotency_key,
        premark_request_sha256,
    ):
        self.actions.append("get_premark_replay")
        if self.premark_binding is None:
            return None
        assert self.premark_binding == {
            "source_client_order_id": source_client_order_id,
            "actor_id": actor_id,
            "correlation_id": correlation_id,
            "idempotency_key": idempotency_key,
            "premark_request_sha256": premark_request_sha256,
        }
        return {
            "state": self.state,
            "plan": self.plan,
            "plan_sha256": self.plan_sha256,
            "diagnostic_code": "operator_parent_move_plan_ready",
            "command_replayed": True,
        }

    def get_goal(self, source_client_order_id: str):
        self.actions.append("get_goal")
        return {
            "state": self.state,
            "plan": self.plan,
            "plan_sha256": (
                self.plan_sha256
                if self.plan is not None
                else None
            ),
            "diagnostic_code": "operator_parent_move_readback",
            "source_follow_up_suppressed": (
                self.source_follow_up_suppressed
            ),
            "source_cancel_event_acknowledged": (
                self.source_cancel_event_acknowledged
            ),
            "source_cancel_allowance_consumed": (
                self.source_cancel_allowance_consumed
            ),
            "source_cancel_call_count": self.source_cancel_call_count,
            "replacement_create_allowance_consumed": (
                self.replacement_create_allowance_consumed
            ),
            "replacement_create_call_count": (
                self.replacement_create_call_count
            ),
        }

    def get_execute_replay(
        self,
        *,
        source_client_order_id,
        expected_plan_sha256,
        actor_id,
        correlation_id,
        idempotency_key,
        payload_sha256,
    ):
        self.actions.append("get_execute_replay")
        if self.execute_binding is None:
            return None
        assert self.execute_binding == {
            "source_client_order_id": source_client_order_id,
            "expected_plan_sha256": expected_plan_sha256,
            "actor_id": actor_id,
            "correlation_id": correlation_id,
            "idempotency_key": idempotency_key,
            "payload_sha256": payload_sha256,
        }
        projection = self.get_goal(source_client_order_id)
        projection["command_replayed"] = True
        return projection

    def begin_execute(
        self,
        *,
        source_client_order_id,
        expected_plan_sha256,
        actor_id,
        correlation_id,
        idempotency_key,
        payload_sha256,
    ):
        self.actions.append("begin_execute")
        assert self.plan_sha256 == expected_plan_sha256
        self.execute_binding = {
            "source_client_order_id": source_client_order_id,
            "expected_plan_sha256": expected_plan_sha256,
            "actor_id": actor_id,
            "correlation_id": correlation_id,
            "idempotency_key": idempotency_key,
            "payload_sha256": payload_sha256,
        }
        self.cycles_used += 1
        projection = self.get_goal(source_client_order_id)
        projection["command_replayed"] = False
        return projection

    def activate_source_follow_up_suppression(
        self, *, source_client_order_id, correlation_id
    ):
        self.actions.append("activate_source_follow_up_suppression")
        self.source_follow_up_suppressed = True

    def finalize_source_follow_up_suppression(
        self, *, source_client_order_id, diagnostic_code
    ):
        self.actions.append("finalize_source_follow_up_suppression")
        self.source_follow_up_suppressed = False

    def claim_source_cancel(self, *, source_client_order_id, correlation_id):
        self.actions.append("claim_source_cancel")
        self.state = "SOURCE_CANCEL_CLAIMED"
        return self.get_goal(source_client_order_id)

    def mark_source_cancel_boundary_crossed(
        self, *, source_client_order_id, correlation_id
    ):
        self.actions.append("mark_source_cancel_boundary_crossed")
        self.call_count += 1
        self.source_cancel_allowance_consumed = True
        self.source_cancel_call_count = 1

    def record_source_cancel_outcome(
        self,
        *,
        source_client_order_id,
        outcome,
        diagnostic_code,
        exchange_evidence_sha256=None,
    ):
        self.actions.append(f"record_source_cancel_outcome:{outcome}")
        if outcome == "CANCELLED":
            self.state = "SOURCE_CANCELLED"
        elif outcome == "REJECTED":
            self.state = "SOURCE_CANCEL_REJECTED"
        else:
            self.state = "SOURCE_CANCEL_UNKNOWN"
        return self.get_goal(source_client_order_id)

    def abort_source_cancel_before_boundary(
        self, *, source_client_order_id, correlation_id, diagnostic_code
    ):
        self.actions.append("abort_source_cancel_before_boundary")
        self.state = "PLANNED"
        return self.get_goal(source_client_order_id)

    def claim_replacement_create(
        self, *, source_client_order_id, correlation_id
    ):
        self.actions.append("claim_replacement_create")
        self.state = "REPLACEMENT_CREATE_CLAIMED"
        return self.get_goal(source_client_order_id)

    def mark_replacement_create_boundary_crossed(
        self, *, source_client_order_id, correlation_id
    ):
        self.actions.append("mark_replacement_create_boundary_crossed")
        self.call_count += 1
        self.replacement_create_allowance_consumed = True
        self.replacement_create_call_count = 1

    def record_replacement_create_outcome(
        self,
        *,
        source_client_order_id,
        outcome,
        diagnostic_code,
        exchange_evidence_sha256=None,
    ):
        self.actions.append(f"record_replacement_create_outcome:{outcome}")
        self.state = (
            "REPLACEMENT_CREATED"
            if outcome == "ACCEPTED"
            else f"REPLACEMENT_CREATE_{outcome}"
        )
        return self.get_goal(source_client_order_id)

    def abort_replacement_create_before_boundary(
        self, *, source_client_order_id, correlation_id, diagnostic_code
    ):
        self.actions.append("abort_replacement_create_before_boundary")
        self.state = "SOURCE_CANCELLED"
        return self.get_goal(source_client_order_id)

    def begin_closeout(
        self,
        *,
        source_client_order_id,
        reserved_successor_client_order_id,
        expected_plan_sha256,
        actor_id,
        correlation_id,
        idempotency_key,
        payload_sha256,
    ):
        self.actions.append("begin_closeout")
        assert self.state == "REPLACEMENT_CREATED"
        assert self.plan_sha256 == expected_plan_sha256
        assert reserved_successor_client_order_id == SUCCESSOR_ID
        self.cycles_used += 1
        return {
            "state": self.state,
            "plan": self.plan,
            "command_replayed": False,
        }

    def claim_successor_closeout_cancel(
        self,
        *,
        source_client_order_id,
        reserved_successor_client_order_id,
        correlation_id,
    ):
        self.actions.append("claim_successor_closeout_cancel")
        self.state = "SUCCESSOR_CLOSEOUT_CANCEL_CLAIMED"
        return self.get_goal(source_client_order_id)

    def mark_successor_closeout_cancel_boundary_crossed(
        self,
        *,
        source_client_order_id,
        reserved_successor_client_order_id,
        correlation_id,
    ):
        self.actions.append(
            "mark_successor_closeout_cancel_boundary_crossed"
        )
        self.call_count += 1

    def record_successor_closeout_cancel_outcome(
        self,
        *,
        source_client_order_id,
        reserved_successor_client_order_id,
        outcome,
        diagnostic_code,
        exchange_evidence_sha256=None,
    ):
        self.actions.append(
            f"record_successor_closeout_cancel_outcome:{outcome}"
        )
        self.state = (
            "SUCCESSOR_CLOSED"
            if outcome == "CANCELLED"
            else f"SUCCESSOR_CLOSEOUT_CANCEL_{outcome}"
        )
        return self.get_goal(source_client_order_id)

    def abort_successor_closeout_cancel_before_boundary(
        self,
        *,
        source_client_order_id,
        reserved_successor_client_order_id,
        correlation_id,
        diagnostic_code,
    ):
        self.actions.append(
            "abort_successor_closeout_cancel_before_boundary"
        )
        self.state = "REPLACEMENT_CREATED"
        return self.get_goal(source_client_order_id)

    def complete_cycle(
        self,
        *,
        source_client_order_id,
        correlation_id,
        idempotency_key,
        diagnostic_code,
    ):
        self.actions.append(f"complete_cycle:{diagnostic_code}")
        return self.get_goal(source_client_order_id)


class FakeRuntime:
    def __init__(self) -> None:
        self.actions: list[str] = []

    def cancel_source(self, plan, *, before_exchange_call):
        self.actions.append("cancel_source")
        before_exchange_call()
        return ParentMoveRuntimeOutcome(
            classification="CANCELLED",
            exchange_invoked=True,
            diagnostic_code="operator_parent_move_source_cancelled",
            exchange_evidence_sha256="c" * 64,
            client_order_id=SOURCE_ID,
            parent_client_order_id=None,
        )

    def create_successor(self, plan, *, before_exchange_call):
        self.actions.append("create_successor")
        before_exchange_call()
        return ParentMoveRuntimeOutcome(
            classification="ACCEPTED",
            exchange_invoked=True,
            diagnostic_code="operator_parent_move_successor_created",
            exchange_evidence_sha256="d" * 64,
            client_order_id=SUCCESSOR_ID,
            parent_client_order_id=SOURCE_ID,
        )

    def cancel_successor(self, plan, *, before_exchange_call):
        self.actions.append("cancel_successor")
        before_exchange_call()
        return ParentMoveRuntimeOutcome(
            classification="CANCELLED",
            exchange_invoked=True,
            diagnostic_code="operator_parent_move_successor_cancelled",
            exchange_evidence_sha256="e" * 64,
            client_order_id=SUCCESSOR_ID,
            parent_client_order_id=SOURCE_ID,
        )


def _service(
    repository: FakeRepository,
    runtime: FakeRuntime,
    *,
    order_repository: FakeOrderRepository | None = None,
    policy_terms: ParentMovePremarkPolicyTerms | None = None,
    live_terms_complete: bool = True,
    execution_authority: bool = True,
) -> OperatorParentMovePremarkService:
    return OperatorParentMovePremarkService(
        repository=repository,
        order_repository=order_repository or FakeOrderRepository(),
        runtime=runtime,
        policy_terms=policy_terms or _terms(),
        legacy_pending_move_checker=lambda _source_id: (
            repository.legacy_pending
        ),
        reserved_successor_client_order_id_factory=lambda: SUCCESSOR_ID,
        live_authority_terms_complete=lambda: live_terms_complete,
        execution_authority_checker=lambda: execution_authority,
    )


def test_premark_is_call_free_and_persists_one_immutable_plan() -> None:
    repository = FakeRepository()
    order_repository = FakeOrderRepository()
    runtime = FakeRuntime()

    result = _service(
        repository, runtime, order_repository=order_repository
    ).premark(
        context=_context("premark_parent_move"),
        request=ParentMovePremarkRequest(
            source_client_order_id=SOURCE_ID,
            requested_limit_price="901.239",
            operator_reason="reviewed parent replacement",
            confirm_premark=True,
        ),
    )

    assert result["state"] == "PLANNED"
    assert (
        result["plan"]["reserved_successor_client_order_id"]
        == SUCCESSOR_ID
    )
    assert runtime.actions == []
    assert repository.call_count == 0
    assert order_repository.actions == ["get_order"]


def test_default_successor_identity_is_deterministic_for_exact_replay() -> None:
    repository = FakeRepository()
    order_repository = FakeOrderRepository()
    service = OperatorParentMovePremarkService(
        repository=repository,
        order_repository=order_repository,
        runtime=FakeRuntime(),
        policy_terms=_terms(),
        legacy_pending_move_checker=lambda _source_id: False,
    )
    context = _context("premark_parent_move")
    request = ParentMovePremarkRequest(
        source_client_order_id=SOURCE_ID,
        requested_limit_price="901.239",
        operator_reason="reviewed parent replacement",
        confirm_premark=True,
    )

    created = service.premark(context=context, request=request)
    replayed = service.premark(context=context, request=request)

    assert len(repository.plan_creates) == 1
    first = repository.plan_creates[0]
    assert replayed["plan_sha256"] == created["plan_sha256"]
    assert replayed["command_replayed"] is True
    successor = str(first["plan"]["reserved_successor_client_order_id"])
    assert successor != SOURCE_ID
    assert successor[14] == "4"


def test_exact_premark_replay_returns_before_mutable_source_reads() -> None:
    repository = FakeRepository()
    order_repository = FakeOrderRepository()
    service = OperatorParentMovePremarkService(
        repository=repository,
        order_repository=order_repository,
        runtime=FakeRuntime(),
        policy_terms=_terms(),
        legacy_pending_move_checker=lambda _source_id: False,
    )
    context = _context("premark_parent_move")
    request = ParentMovePremarkRequest(
        source_client_order_id=SOURCE_ID,
        requested_limit_price="901.239",
        operator_reason="reviewed parent replacement",
        confirm_premark=True,
    )
    created = service.premark(context=context, request=request)
    order_repository.source["filled_size"] = "0.001"
    reads_before_replay = list(order_repository.actions)

    replayed = service.premark(context=context, request=request)

    assert replayed["command_replayed"] is True
    assert replayed["plan_sha256"] == created["plan_sha256"]
    assert order_repository.actions == reads_before_replay


def test_default_incomplete_terms_do_not_touch_goal_ledger_or_runtime() -> None:
    repository = FakeRepository()
    order_repository = FakeOrderRepository()
    runtime = FakeRuntime()
    service = _service(
        repository,
        runtime,
        order_repository=order_repository,
        policy_terms=ParentMovePremarkPolicyTerms(),
    )

    with pytest.raises(OperatorParentMoveServiceError) as exc_info:
        service.premark(
            context=_context("premark_parent_move"),
            request=ParentMovePremarkRequest(
                source_client_order_id=SOURCE_ID,
                requested_limit_price="901.23",
                operator_reason="reviewed parent replacement",
                confirm_premark=True,
            ),
        )

    assert exc_info.value.code == (
        "operator_parent_move_authority_terms_incomplete"
    )
    assert repository.actions == []
    assert order_repository.actions == []
    assert runtime.actions == []
    assert repository.cycles_used == 0
    assert repository.call_count == 0


@pytest.mark.parametrize(
    ("live_terms_complete", "execution_authority", "expected"),
    [
        (
            False,
            True,
            "operator_parent_move_live_authority_terms_incomplete",
        ),
        (
            True,
            False,
            "operator_parent_move_execution_authority_disabled",
        ),
    ],
)
def test_execute_gates_before_repository_claim_and_runtime(
    live_terms_complete: bool,
    execution_authority: bool,
    expected: str,
) -> None:
    repository = FakeRepository()
    runtime = FakeRuntime()
    service = _service(repository, runtime)
    prepared = service.premark(
        context=_context("premark_parent_move"),
        request=ParentMovePremarkRequest(
            source_client_order_id=SOURCE_ID,
            requested_limit_price="901.23",
            operator_reason="reviewed parent replacement",
            confirm_premark=True,
        ),
    )
    before = list(repository.actions)
    service = _service(
        repository,
        runtime,
        live_terms_complete=live_terms_complete,
        execution_authority=execution_authority,
    )

    with pytest.raises(OperatorParentMoveServiceError) as exc_info:
        service.execute(
            context=_context("execute_parent_move"),
            request=ParentMoveExecuteRequest(
                source_client_order_id=SOURCE_ID,
                expected_plan_sha256=prepared["plan_sha256"],
                confirmation_sha256=CONFIRMATION_SHA256,
                confirm_cancel_then_replace=True,
            ),
        )

    assert exc_info.value.code == expected
    assert repository.actions == before
    assert runtime.actions == []


def test_execute_is_claimed_then_cancels_source_before_creating_successor() -> None:
    repository = FakeRepository()
    runtime = FakeRuntime()
    service = _service(repository, runtime)
    prepared = service.premark(
        context=_context("premark_parent_move"),
        request=ParentMovePremarkRequest(
            source_client_order_id=SOURCE_ID,
            requested_limit_price="901.23",
            operator_reason="reviewed parent replacement",
            confirm_premark=True,
        ),
    )

    result = service.execute(
        context=_context("execute_parent_move"),
        request=ParentMoveExecuteRequest(
            source_client_order_id=SOURCE_ID,
            expected_plan_sha256=prepared["plan_sha256"],
            confirmation_sha256=CONFIRMATION_SHA256,
            confirm_cancel_then_replace=True,
        ),
    )

    assert result["state"] == "REPLACEMENT_CREATED"
    assert runtime.actions == ["cancel_source", "create_successor"]
    assert "mark_source_cancel_boundary_crossed" in repository.actions
    assert "record_source_cancel_outcome:CANCELLED" in repository.actions
    assert "mark_replacement_create_boundary_crossed" in repository.actions
    assert "record_replacement_create_outcome:ACCEPTED" in repository.actions
    assert "finalize_source_follow_up_suppression" not in repository.actions
    assert repository.call_count == 2


def test_source_cancel_unknown_stops_before_successor_create() -> None:
    repository = FakeRepository()
    runtime = FakeRuntime()
    service = _service(repository, runtime)
    prepared = service.premark(
        context=_context("premark_parent_move"),
        request=ParentMovePremarkRequest(
            source_client_order_id=SOURCE_ID,
            requested_limit_price="901.23",
            operator_reason="reviewed parent replacement",
            confirm_premark=True,
        ),
    )
    def cancel_unknown(plan, *, before_exchange_call):
        before_exchange_call()
        return ParentMoveRuntimeOutcome(
            classification="UNKNOWN",
            exchange_invoked=True,
            diagnostic_code="operator_parent_move_source_cancel_unknown",
        )

    runtime.cancel_source = cancel_unknown

    result = service.execute(
        context=_context("execute_parent_move"),
        request=ParentMoveExecuteRequest(
            source_client_order_id=SOURCE_ID,
            expected_plan_sha256=prepared["plan_sha256"],
            confirmation_sha256=CONFIRMATION_SHA256,
            confirm_cancel_then_replace=True,
        ),
    )

    assert result["state"] == "SOURCE_CANCEL_UNKNOWN"
    assert "create_successor" not in runtime.actions
    assert repository.call_count == 1


def test_post_boundary_service_error_is_persisted_as_unknown() -> None:
    repository = FakeRepository()
    runtime = FakeRuntime()
    service = _service(repository, runtime)
    prepared = service.premark(
        context=_context("premark_parent_move"),
        request=ParentMovePremarkRequest(
            source_client_order_id=SOURCE_ID,
            requested_limit_price="901.23",
            operator_reason="reviewed parent replacement",
            confirm_premark=True,
        ),
    )

    def cancel_then_fail(plan, *, before_exchange_call):
        before_exchange_call()
        raise OperatorParentMoveServiceError(
            "operator_parent_move_runtime_failed"
        )

    runtime.cancel_source = cancel_then_fail
    result = service.execute(
        context=_context("execute_parent_move"),
        request=ParentMoveExecuteRequest(
            source_client_order_id=SOURCE_ID,
            expected_plan_sha256=prepared["plan_sha256"],
            confirmation_sha256=CONFIRMATION_SHA256,
            confirm_cancel_then_replace=True,
        ),
    )

    assert result["state"] == "SOURCE_CANCEL_UNKNOWN"
    assert "record_source_cancel_outcome:UNKNOWN" in repository.actions
    assert repository.call_count == 1


def test_accepted_replacement_with_wrong_linkage_is_persisted_unknown() -> None:
    repository = FakeRepository()
    runtime = FakeRuntime()
    service = _service(repository, runtime)
    prepared = service.premark(
        context=_context("premark_parent_move"),
        request=ParentMovePremarkRequest(
            source_client_order_id=SOURCE_ID,
            requested_limit_price="901.23",
            operator_reason="reviewed parent replacement",
            confirm_premark=True,
        ),
    )

    def create_wrong_successor(plan, *, before_exchange_call):
        before_exchange_call()
        return ParentMoveRuntimeOutcome(
            classification="ACCEPTED",
            exchange_invoked=True,
            diagnostic_code="operator_parent_move_successor_created",
            exchange_evidence_sha256="d" * 64,
            client_order_id="33333333-3333-4333-8333-333333333333",
            parent_client_order_id=SOURCE_ID,
        )

    runtime.create_successor = create_wrong_successor
    result = service.execute(
        context=_context("execute_parent_move"),
        request=ParentMoveExecuteRequest(
            source_client_order_id=SOURCE_ID,
            expected_plan_sha256=prepared["plan_sha256"],
            confirmation_sha256=CONFIRMATION_SHA256,
            confirm_cancel_then_replace=True,
        ),
    )

    assert result["state"] == "REPLACEMENT_CREATE_UNKNOWN"
    assert "record_replacement_create_outcome:UNKNOWN" in repository.actions
    assert "record_replacement_create_outcome:ACCEPTED" not in repository.actions


def test_execute_revalidates_zero_fill_before_claiming_any_mutation() -> None:
    repository = FakeRepository()
    order_repository = FakeOrderRepository()
    runtime = FakeRuntime()
    service = _service(
        repository,
        runtime,
        order_repository=order_repository,
    )
    prepared = service.premark(
        context=_context("premark_parent_move"),
        request=ParentMovePremarkRequest(
            source_client_order_id=SOURCE_ID,
            requested_limit_price="901.23",
            operator_reason="reviewed parent replacement",
            confirm_premark=True,
        ),
    )
    order_repository.source["filled_size"] = "0.0001"
    before = list(repository.actions)

    with pytest.raises(OperatorParentMoveServiceError) as exc_info:
        service.execute(
            context=_context("execute_parent_move"),
            request=ParentMoveExecuteRequest(
                source_client_order_id=SOURCE_ID,
                expected_plan_sha256=prepared["plan_sha256"],
                confirmation_sha256=CONFIRMATION_SHA256,
                confirm_cancel_then_replace=True,
            ),
        )

    assert exc_info.value.code == "operator_parent_move_source_not_zero_fill"
    assert "begin_execute" not in repository.actions[len(before):]
    assert runtime.actions == []


def test_exact_execute_replay_returns_before_mutable_source_revalidation() -> None:
    repository = FakeRepository()
    order_repository = FakeOrderRepository()
    runtime = FakeRuntime()
    service = _service(
        repository,
        runtime,
        order_repository=order_repository,
    )
    prepared = service.premark(
        context=_context("premark_parent_move"),
        request=ParentMovePremarkRequest(
            source_client_order_id=SOURCE_ID,
            requested_limit_price="901.23",
            operator_reason="reviewed parent replacement",
            confirm_premark=True,
        ),
    )
    context = _context("execute_parent_move")
    request = ParentMoveExecuteRequest(
        source_client_order_id=SOURCE_ID,
        expected_plan_sha256=prepared["plan_sha256"],
        confirmation_sha256=CONFIRMATION_SHA256,
        confirm_cancel_then_replace=True,
    )
    first = service.execute(context=context, request=request)
    order_repository.source["status"] = "CANCELLED"
    order_repository.source["filled_size"] = "0.001"
    order_reads_before = list(order_repository.actions)
    runtime_actions_before = list(runtime.actions)

    replayed = service.execute(context=context, request=request)

    assert first["state"] == "REPLACEMENT_CREATED"
    assert replayed["state"] == "REPLACEMENT_CREATED"
    assert replayed["command_replayed"] is True
    assert order_repository.actions == order_reads_before
    assert runtime.actions == runtime_actions_before


@pytest.mark.parametrize("cancel_event_acknowledged", [False, True])
def test_execute_resumes_only_unconsumed_replacement_after_recovered_claim(
    cancel_event_acknowledged: bool,
) -> None:
    repository = FakeRepository()
    order_repository = FakeOrderRepository()
    runtime = FakeRuntime()
    service = _service(
        repository,
        runtime,
        order_repository=order_repository,
    )
    prepared = service.premark(
        context=_context("premark_parent_move"),
        request=ParentMovePremarkRequest(
            source_client_order_id=SOURCE_ID,
            requested_limit_price="901.23",
            operator_reason="reviewed parent replacement",
            confirm_premark=True,
        ),
    )
    repository.state = "SOURCE_CANCELLED"
    repository.source_follow_up_suppressed = not cancel_event_acknowledged
    repository.source_cancel_event_acknowledged = cancel_event_acknowledged
    repository.source_cancel_allowance_consumed = True
    repository.source_cancel_call_count = 1
    order_repository.source["status"] = "CANCELLED"

    result = service.execute(
        context=_context("execute_parent_move"),
        request=ParentMoveExecuteRequest(
            source_client_order_id=SOURCE_ID,
            expected_plan_sha256=prepared["plan_sha256"],
            confirmation_sha256=CONFIRMATION_SHA256,
            confirm_cancel_then_replace=True,
        ),
    )

    assert result["state"] == "REPLACEMENT_CREATED"
    assert runtime.actions == ["create_successor"]
    assert "claim_source_cancel" not in repository.actions
    assert repository.source_cancel_call_count == 1
    assert repository.replacement_create_call_count == 1


def test_safe_closeout_requires_separate_claim_and_cancels_exact_successor() -> None:
    repository = FakeRepository()
    runtime = FakeRuntime()
    service = _service(repository, runtime)
    prepared = service.premark(
        context=_context("premark_parent_move"),
        request=ParentMovePremarkRequest(
            source_client_order_id=SOURCE_ID,
            requested_limit_price="901.23",
            operator_reason="reviewed parent replacement",
            confirm_premark=True,
        ),
    )
    service.execute(
        context=_context("execute_parent_move"),
        request=ParentMoveExecuteRequest(
            source_client_order_id=SOURCE_ID,
            expected_plan_sha256=prepared["plan_sha256"],
            confirmation_sha256=CONFIRMATION_SHA256,
            confirm_cancel_then_replace=True,
        ),
    )

    result = service.safe_closeout(
        context=_context("safe_closeout_parent_move_successor"),
        request=ParentMoveSafeCloseoutRequest(
            source_client_order_id=SOURCE_ID,
            expected_plan_sha256=prepared["plan_sha256"],
            confirmation_sha256=CONFIRMATION_SHA256,
            confirm_exact_successor_cancel=True,
        ),
    )

    assert result["state"] == "SUCCESSOR_CLOSED"
    assert runtime.actions[-1] == "cancel_successor"
    assert "begin_closeout" in repository.actions
    assert "claim_successor_closeout_cancel" in repository.actions
    assert (
        "record_successor_closeout_cancel_outcome:CANCELLED"
        in repository.actions
    )
    assert repository.call_count == 3
