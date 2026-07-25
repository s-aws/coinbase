from __future__ import annotations

from dataclasses import replace

from application.admin_api.operator_futures_manual_lifecycle import (
    FuturesManualEligibilityResult,
    FuturesManualExecutionPlan,
    FuturesManualGoalRecord,
    FuturesManualLifecycleError,
    FuturesManualRequestContext,
    OperatorFuturesManualLifecycleService,
)
from application.admin_api.operator_futures_manual_runtime import (
    FuturesManualCancelExecution,
    FuturesManualCreateExecution,
    FuturesManualPreviewExecution,
    FuturesManualReconciliationExecution,
)
from core.enums import (
    AdminFuturesManualCallOutcome,
    AdminFuturesManualEligibilityOutcome,
)


def _record(**updates):
    value = FuturesManualGoalRecord(
        goal_id="operator_futures_manual_order_lifecycle_v1",
        revision=1,
        cycles_used=1,
        active_cycle_number=None,
        eligibility_outcome=AdminFuturesManualEligibilityOutcome.ELIGIBLE,
        eligibility_diagnostic_code=(
            "operator_futures_manual_exact_v3_eligible"
        ),
        category_attempts={
            "api_key_permissions": 1,
            "portfolio_catalog": 1,
            "product": 1,
            "best_bid_ask": 1,
            "futures_positions": 1,
            "futures_margin_collateral": 1,
        },
        candidate={"product_id": "AVP-20DEC30-CDE"},
        candidate_sha256="a" * 64,
        portfolio_id_sha256="b" * 64,
        eligibility_evidence_sha256="c" * 64,
        client_order_id=None,
        preview_outcome=AdminFuturesManualCallOutcome.NOT_RUN,
        preview_exchange_invoked=None,
        preview_id_sha256=None,
        create_outcome=AdminFuturesManualCallOutcome.NOT_RUN,
        create_exchange_invoked=None,
        exchange_order_id_sha256=None,
        reconciliation_outcome=AdminFuturesManualCallOutcome.NOT_RUN,
        reconciliation_exchange_invoked=None,
        order_status=None,
        authoritatively_nonterminal=None,
        cancel_outcome=AdminFuturesManualCallOutcome.NOT_RUN,
        cancel_exchange_invoked=None,
        diagnostic_code="operator_futures_manual_exact_v3_eligible",
        correlation_id="corr-1",
        audit_id="11111111-1111-4111-8111-111111111111",
        updated_at="2026-07-24T00:00:00+00:00",
    )
    return replace(value, **updates)


def _context(**updates):
    value = FuturesManualRequestContext(
        actor_id="operator-1",
        roles=("admin", "trader"),
        expected_revision=1,
        idempotency_key="idem-1",
        correlation_id="corr-1",
        audit_id="11111111-1111-4111-8111-111111111111",
        operator_intent=(
            "preview_submit_and_safe_closeout_one_futures_order"
        ),
        authorize_preview_create_and_safe_closeout=True,
        acknowledge_unknown_outcome_consumes_allowance=True,
        acknowledge_create_requires_accepted_identical_preview=True,
        acknowledge_cancel_is_only_for_exact_nonterminal_child=True,
    )
    return replace(value, **updates)


class _Reader:
    def run(self, *, before_category):
        attempts = {}
        for category in (
            "api_key_permissions",
            "portfolio_catalog",
            "product",
            "best_bid_ask",
            "futures_positions",
            "futures_margin_collateral",
        ):
            before_category(category)
            attempts[category] = 1
        return FuturesManualEligibilityResult(
            outcome=AdminFuturesManualEligibilityOutcome.ELIGIBLE,
            diagnostic_code="operator_futures_manual_exact_v3_eligible",
            category_attempts=attempts,
            candidate={"product_id": "AVP-20DEC30-CDE"},
            portfolio_id_sha256="b" * 64,
            evidence_sha256="c" * 64,
            public_evidence={"raw_responses_included": False},
        )


class _Repository:
    def __init__(self):
        self.record = _record()
        self.events = []

    def read(self):
        return self.record

    def begin_eligibility_cycle(self, *, context):
        self.events.append("cycle:begin")
        return self.record, 2

    def claim_eligibility_category(self, *, cycle_number, category):
        assert cycle_number == 2
        self.events.append(f"category:{category}")

    def finish_eligibility_cycle(self, *, cycle_number, result, context):
        assert cycle_number == 2
        self.events.append("cycle:finish")
        self.record = replace(
            self.record,
            revision=2,
            cycles_used=2,
            eligibility_outcome=result.outcome,
        )
        return self.record

    def claim_preview(self, *, context):
        self.events.append("preview:claim")
        return self.record, FuturesManualExecutionPlan(
            claim_id="claim-1",
            client_order_id="client-1",
            candidate={"product_id": "AVP-20DEC30-CDE"},
            candidate_sha256="a" * 64,
            eligibility_evidence_sha256="c" * 64,
        )

    def mark_preview_exchange_invoked(self, *, claim_id):
        self.events.append("preview:invoke")

    def finish_preview(self, *, claim_id, execution):
        self.events.append("preview:finish")
        return self.record

    def claim_create(self, *, claim_id):
        self.events.append("create:claim")
        return self.record

    def mark_create_exchange_invoked(self, *, claim_id):
        self.events.append("create:invoke")

    def finish_create(self, *, claim_id, execution):
        self.events.append("create:finish")
        return self.record

    def finish_create_and_claim_reconciliation(
        self,
        *,
        claim_id,
        execution,
    ):
        self.events.append("create:finish+reconcile:claim")
        return self.record

    def claim_reconciliation(self, *, claim_id):
        self.events.append("reconcile:claim")
        return self.record

    def mark_reconciliation_exchange_invoked(self, *, claim_id):
        self.events.append("reconcile:invoke")

    def finish_reconciliation(self, *, claim_id, execution):
        self.events.append("reconcile:finish")
        return self.record

    def finish_reconciliation_and_claim_cancel(
        self,
        *,
        claim_id,
        execution,
    ):
        self.events.append("reconcile:finish+cancel:claim")
        return self.record

    def claim_cancel(self, *, claim_id):
        self.events.append("cancel:claim")
        return self.record

    def mark_cancel_exchange_invoked(self, *, claim_id):
        self.events.append("cancel:invoke")

    def finish_cancel(self, *, claim_id, execution):
        self.events.append("cancel:finish")
        return self.record


class _Executor:
    def __init__(self, *, preview_outcome="ACCEPTED", nonterminal=True):
        self.preview_outcome = AdminFuturesManualCallOutcome(preview_outcome)
        self.nonterminal = nonterminal

    def preview(self, candidate, *, before_call):
        before_call()
        return FuturesManualPreviewExecution(
            outcome=self.preview_outcome,
            diagnostic_code="preview",
            preview_id_sha256="d" * 64,
            public_evidence={},
            private_preview_id=(
                "ephemeral-preview"
                if self.preview_outcome
                is AdminFuturesManualCallOutcome.ACCEPTED
                else None
            ),
        )

    def create(self, **kwargs):
        kwargs["before_call"]()
        return FuturesManualCreateExecution(
            outcome=AdminFuturesManualCallOutcome.ACCEPTED,
            diagnostic_code="create",
            exchange_order_id_sha256="e" * 64,
            public_evidence={},
            private_exchange_order_id="ephemeral-exchange-order",
        )

    def reconcile(self, **kwargs):
        kwargs["before_call"]()
        return FuturesManualReconciliationExecution(
            outcome=AdminFuturesManualCallOutcome.ACCEPTED,
            diagnostic_code="reconcile",
            exchange_order_id_sha256="e" * 64,
            order_status="OPEN" if self.nonterminal else "FILLED",
            authoritatively_nonterminal=self.nonterminal,
            public_evidence={},
        )

    def cancel(self, **kwargs):
        kwargs["before_call"]()
        return FuturesManualCancelExecution(
            outcome=AdminFuturesManualCallOutcome.ACCEPTED,
            diagnostic_code="cancel",
            exchange_order_id_sha256="e" * 64,
            public_evidence={},
        )


def test_refresh_claims_each_exact_category_before_finishing():
    repository = _Repository()
    service = OperatorFuturesManualLifecycleService(
        repository=repository,
        eligibility_reader=_Reader(),
        exchange_executor=_Executor(),
    )

    result = service.refresh(
        context=_context(
            operator_intent="refresh_one_futures_manual_eligibility_cycle",
            authorize_preview_create_and_safe_closeout=False,
            acknowledge_unknown_outcome_consumes_allowance=False,
            acknowledge_create_requires_accepted_identical_preview=False,
            acknowledge_cancel_is_only_for_exact_nonterminal_child=False,
            authorize_one_no_retry_six_category_cycle=True,
            acknowledge_cycle_is_goal_global_and_limited_to_ten=True,
            acknowledge_unsuccessful_or_unknown_cycle_fails_closed=True,
        )
    )

    assert result.cycles_used == 2
    assert repository.events == [
        "cycle:begin",
        "category:api_key_permissions",
        "category:portfolio_catalog",
        "category:product",
        "category:best_bid_ask",
        "category:futures_positions",
        "category:futures_margin_collateral",
        "cycle:finish",
    ]


def test_execute_commits_every_claim_before_call_and_safe_closes_nonterminal():
    repository = _Repository()
    service = OperatorFuturesManualLifecycleService(
        repository=repository,
        eligibility_reader=_Reader(),
        exchange_executor=_Executor(nonterminal=True),
    )

    service.execute(context=_context())

    assert repository.events == [
        "preview:claim",
        "preview:invoke",
        "preview:finish",
        "create:claim",
        "create:invoke",
        "create:finish+reconcile:claim",
        "reconcile:invoke",
        "reconcile:finish+cancel:claim",
        "cancel:invoke",
        "cancel:finish",
    ]


def test_rejected_preview_stops_without_create_or_cancel():
    repository = _Repository()
    service = OperatorFuturesManualLifecycleService(
        repository=repository,
        eligibility_reader=_Reader(),
        exchange_executor=_Executor(preview_outcome="REJECTED"),
    )

    service.execute(context=_context())

    assert repository.events == [
        "preview:claim",
        "preview:invoke",
        "preview:finish",
    ]


def test_terminal_create_stops_after_one_reconciliation_without_cancel():
    repository = _Repository()
    service = OperatorFuturesManualLifecycleService(
        repository=repository,
        eligibility_reader=_Reader(),
        exchange_executor=_Executor(nonterminal=False),
    )

    service.execute(context=_context())

    assert repository.events[-1] == "reconcile:finish"
    assert not any(event.startswith("cancel:") for event in repository.events)


def test_execute_requires_exact_explicit_confirmation():
    service = OperatorFuturesManualLifecycleService(
        repository=_Repository(),
        eligibility_reader=_Reader(),
        exchange_executor=_Executor(),
    )

    try:
        service.execute(
            context=_context(
                authorize_preview_create_and_safe_closeout=False
            )
        )
    except FuturesManualLifecycleError as exc:
        assert exc.code == "operator_futures_manual_confirmation_required"
        assert exc.http_status_code == 422
    else:
        raise AssertionError("missing confirmation did not fail closed")


def test_refresh_requires_exact_no_retry_cycle_confirmation():
    service = OperatorFuturesManualLifecycleService(
        repository=_Repository(),
        eligibility_reader=_Reader(),
        exchange_executor=_Executor(),
    )

    try:
        service.refresh(
            context=_context(
                operator_intent="refresh_one_futures_manual_eligibility_cycle",
                authorize_preview_create_and_safe_closeout=False,
                acknowledge_unknown_outcome_consumes_allowance=False,
            )
        )
    except FuturesManualLifecycleError as exc:
        assert (
            exc.code
            == "operator_futures_manual_refresh_confirmation_required"
        )
        assert exc.http_status_code == 422
    else:
        raise AssertionError("missing refresh confirmation did not fail closed")


def test_unexpected_adapter_exception_finalizes_claim_unknown_immediately():
    repository = _Repository()

    class _BrokenExecutor(_Executor):
        def preview(self, candidate, *, before_call):
            before_call()
            raise RuntimeError("withheld private adapter detail")

    service = OperatorFuturesManualLifecycleService(
        repository=repository,
        eligibility_reader=_Reader(),
        exchange_executor=_BrokenExecutor(),
    )

    service.execute(context=_context())

    assert repository.events == [
        "preview:claim",
        "preview:invoke",
        "preview:finish",
    ]
