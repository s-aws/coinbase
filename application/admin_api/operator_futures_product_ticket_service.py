"""Coordinator for Goal 3 product policy and one preview-gated ticket."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from core.enums import AdminFuturesManualCallOutcome
from database.operator_futures_manual_lifecycle import (
    OperatorFuturesManualLifecycleRepository,
)
from database.operator_futures_product_policy import (
    OperatorFuturesProductPolicyRepository,
)

from .operator_futures_manual_lifecycle import (
    FuturesManualGoalRecord,
    FuturesManualLifecycleError,
    FuturesManualRequestContext,
)
from .operator_futures_product_policy import (
    FuturesProductPolicyRecord,
)
from .operator_futures_product_ticket import (
    FUTURES_PRODUCT_TICKET_GOAL_ID,
    FuturesProductTicketEligibilityReader,
)
from .operator_futures_fill_triggered_follow_up import (
    FUTURES_FILL_TRIGGERED_EXECUTE_INTENT,
    FUTURES_FILL_TRIGGERED_FOLLOW_UP_GOAL_ID,
    FUTURES_FILL_TRIGGERED_REFRESH_INTENT,
)


@dataclass(frozen=True, slots=True)
class FuturesProductTicketState:
    policy: FuturesProductPolicyRecord
    lifecycle: FuturesManualGoalRecord


class OperatorFuturesProductTicketService:
    """Own policy transitions, eligibility, and the one terminal proof."""

    def __init__(
        self,
        *,
        policy_repository: OperatorFuturesProductPolicyRepository,
        lifecycle_repository: OperatorFuturesManualLifecycleRepository,
        eligibility_reader: FuturesProductTicketEligibilityReader,
        exchange_executor: Any,
    ) -> None:
        self.policy_repository = policy_repository
        self.lifecycle_repository = lifecycle_repository
        self.eligibility_reader = eligibility_reader
        self.exchange_executor = exchange_executor

    def _require_intent_goal_binding(self, operator_intent: str) -> None:
        expected_goal_id = (
            FUTURES_FILL_TRIGGERED_FOLLOW_UP_GOAL_ID
            if operator_intent
            in {
                FUTURES_FILL_TRIGGERED_REFRESH_INTENT,
                FUTURES_FILL_TRIGGERED_EXECUTE_INTENT,
            }
            else FUTURES_PRODUCT_TICKET_GOAL_ID
        )
        bound_goal_id = getattr(
            self.lifecycle_repository,
            "goal_id",
            expected_goal_id,
        )
        if bound_goal_id != expected_goal_id:
            raise ValueError(
                "operator_futures_product_ticket_goal_binding_invalid"
            )

    def read(self) -> FuturesProductTicketState:
        return FuturesProductTicketState(
            policy=self.policy_repository.read(),
            lifecycle=self.lifecycle_repository.read(),
        )

    def apply_policy(
        self,
        *,
        action: str,
        product_id: str,
        expected_revision: int,
        actor_id: str,
        roles: tuple[str, ...],
        operator_reason: str,
        operator_intent: str,
        confirm_exact_product_policy_action: bool,
        correlation_id: str,
        idempotency_key: str,
    ) -> FuturesProductTicketState:
        self.policy_repository.apply(
            action=action,
            product_id=product_id,
            expected_revision=expected_revision,
            actor_id=actor_id,
            roles=roles,
            operator_reason=operator_reason,
            operator_intent=operator_intent,
            confirm_exact_product_policy_action=(
                confirm_exact_product_policy_action
            ),
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        return self.read()

    def refresh(
        self,
        *,
        context: FuturesManualRequestContext,
    ) -> FuturesProductTicketState:
        self._require_intent_goal_binding(context.operator_intent)
        if (
            context.operator_intent
            not in {
                "refresh_one_futures_product_ticket_eligibility_cycle",
                FUTURES_FILL_TRIGGERED_REFRESH_INTENT,
            }
            or not context.authorize_one_no_retry_six_category_cycle
            or not context.acknowledge_cycle_is_goal_global_and_limited_to_ten
            or not (
                context
                .acknowledge_unsuccessful_or_unknown_cycle_fails_closed
            )
        ):
            raise FuturesManualLifecycleError(
                "operator_futures_product_ticket_refresh_confirmation_required",
                http_status_code=422,
            )
        record, cycle_number = (
            self.lifecycle_repository.begin_eligibility_cycle(
                context=context
            )
        )
        if cycle_number is None:
            return FuturesProductTicketState(
                policy=self.policy_repository.read(),
                lifecycle=record,
            )
        result = self.eligibility_reader.run(
            before_category=lambda category: (
                self.lifecycle_repository.claim_eligibility_category(
                    cycle_number=cycle_number,
                    category=category,
                )
            )
        )
        completed = self.lifecycle_repository.finish_eligibility_cycle(
            cycle_number=cycle_number,
            result=result,
            context=context,
        )
        return FuturesProductTicketState(
            policy=self.policy_repository.read(),
            lifecycle=completed,
        )

    def execute(
        self,
        *,
        context: FuturesManualRequestContext,
    ) -> FuturesProductTicketState:
        self._require_intent_goal_binding(context.operator_intent)
        if (
            context.operator_intent
            not in {
                (
                    "preview_submit_and_safe_closeout_one_"
                    "futures_product_ticket"
                ),
                FUTURES_FILL_TRIGGERED_EXECUTE_INTENT,
            }
            or not context.authorize_preview_create_and_safe_closeout
            or not context.acknowledge_unknown_outcome_consumes_allowance
            or not (
                context
                .acknowledge_create_requires_accepted_identical_preview
            )
            or not (
                context
                .acknowledge_cancel_is_only_for_exact_nonterminal_child
            )
        ):
            raise FuturesManualLifecycleError(
                "operator_futures_product_ticket_confirmation_required",
                http_status_code=422,
            )
        record, plan = self.lifecycle_repository.claim_preview(
            context=context
        )
        if plan is None:
            return FuturesProductTicketState(
                policy=self.policy_repository.read(),
                lifecycle=record,
            )
        try:
            preview = self.exchange_executor.preview(
                plan.candidate,
                before_call=lambda: (
                    self.lifecycle_repository.mark_preview_exchange_invoked(
                        claim_id=plan.claim_id
                    )
                ),
            )
        except Exception:
            preview = SimpleNamespace(
                outcome=AdminFuturesManualCallOutcome.UNKNOWN,
                diagnostic_code=(
                    "operator_futures_product_ticket_preview_outcome_unknown"
                ),
                preview_id_sha256=None,
                private_preview_id=None,
            )
        record = self.lifecycle_repository.finish_preview(
            claim_id=plan.claim_id,
            execution=preview,
        )
        if preview.outcome is not AdminFuturesManualCallOutcome.ACCEPTED:
            return FuturesProductTicketState(
                policy=self.policy_repository.read(),
                lifecycle=record,
            )
        if not preview.private_preview_id:
            raise FuturesManualLifecycleError(
                "operator_futures_product_ticket_preview_binding_missing"
            )

        self.lifecycle_repository.claim_create(claim_id=plan.claim_id)
        try:
            created = self.exchange_executor.create(
                candidate=plan.candidate,
                client_order_id=plan.client_order_id,
                private_preview_id=preview.private_preview_id,
                before_call=lambda: (
                    self.lifecycle_repository.mark_create_exchange_invoked(
                        claim_id=plan.claim_id
                    )
                ),
            )
        except Exception:
            created = SimpleNamespace(
                outcome=AdminFuturesManualCallOutcome.UNKNOWN,
                diagnostic_code=(
                    "operator_futures_product_ticket_create_outcome_unknown"
                ),
                exchange_order_id_sha256=None,
                private_exchange_order_id=None,
            )
        if created.outcome is not AdminFuturesManualCallOutcome.ACCEPTED:
            record = self.lifecycle_repository.finish_create(
                claim_id=plan.claim_id,
                execution=created,
            )
            return FuturesProductTicketState(
                policy=self.policy_repository.read(),
                lifecycle=record,
            )
        if not created.private_exchange_order_id:
            raise FuturesManualLifecycleError(
                "operator_futures_product_ticket_create_binding_missing"
            )

        self.lifecycle_repository.finish_create_and_claim_reconciliation(
            claim_id=plan.claim_id,
            execution=created,
        )
        try:
            reconciled = self.exchange_executor.reconcile(
                candidate=plan.candidate,
                client_order_id=plan.client_order_id,
                private_exchange_order_id=(
                    created.private_exchange_order_id
                ),
                before_call=lambda: (
                    self.lifecycle_repository
                    .mark_reconciliation_exchange_invoked(
                        claim_id=plan.claim_id
                    )
                ),
            )
        except Exception:
            reconciled = SimpleNamespace(
                outcome=AdminFuturesManualCallOutcome.UNKNOWN,
                diagnostic_code=(
                    "operator_futures_product_ticket_reconciliation_"
                    "outcome_unknown"
                ),
                order_status=None,
                authoritatively_nonterminal=False,
            )
        if (
            reconciled.outcome
            is not AdminFuturesManualCallOutcome.ACCEPTED
            or not reconciled.authoritatively_nonterminal
        ):
            record = self.lifecycle_repository.finish_reconciliation(
                claim_id=plan.claim_id,
                execution=reconciled,
            )
            return FuturesProductTicketState(
                policy=self.policy_repository.read(),
                lifecycle=record,
            )

        self.lifecycle_repository.finish_reconciliation_and_claim_cancel(
            claim_id=plan.claim_id,
            execution=reconciled,
        )
        try:
            cancelled = self.exchange_executor.cancel(
                candidate=plan.candidate,
                client_order_id=plan.client_order_id,
                private_exchange_order_id=(
                    created.private_exchange_order_id
                ),
                before_call=lambda: (
                    self.lifecycle_repository.mark_cancel_exchange_invoked(
                        claim_id=plan.claim_id
                    )
                ),
            )
        except Exception:
            cancelled = SimpleNamespace(
                outcome=AdminFuturesManualCallOutcome.UNKNOWN,
                diagnostic_code=(
                    "operator_futures_product_ticket_cancel_outcome_unknown"
                ),
            )
        record = self.lifecycle_repository.finish_cancel(
            claim_id=plan.claim_id,
            execution=cancelled,
        )
        return FuturesProductTicketState(
            policy=self.policy_repository.read(),
            lifecycle=record,
        )


__all__ = [
    "FuturesProductTicketState",
    "OperatorFuturesProductTicketService",
]
