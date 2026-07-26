"""Installed runtime for Goal 5 Futures fill-triggered follow-ups."""

from __future__ import annotations

import os
from threading import Lock

from .operator_futures_fill_triggered_follow_up import (
    FUTURES_FILL_TRIGGERED_FOLLOW_UP_GOAL_ID,
    FuturesFillTriggeredEligibilityReader,
    FuturesFillTriggeredExecutionCoordinator,
    FuturesFillTriggeredFollowUpService,
    validate_futures_fill_triggered_eligibility_evidence,
)
from .operator_futures_follow_up_intent import (
    FuturesFollowUpIntentRecord,
)
from .operator_futures_product_ticket_runtime import (
    AdminApiFuturesProductTicketExchangeExecutor,
)
from .operator_futures_product_ticket_service import (
    OperatorFuturesProductTicketService,
)
from .operator_futures_product_ticket_service_runtime import (
    _DeferredFuturesDefaultRestClient,
    get_operator_futures_product_ticket_execution_posture,
)


OPERATOR_FUTURES_FILL_TRIGGERED_FOLLOW_UP_ENABLED_ENV = (
    "COINBASE_ADMIN_API_OPERATOR_FUTURES_FILL_TRIGGERED_FOLLOW_UP_ENABLED"
)

_DEFAULT_SERVICE: FuturesFillTriggeredFollowUpService | None = None
_DEFAULT_LOCK = Lock()


def _intent_record(value: dict[str, object]) -> FuturesFollowUpIntentRecord:
    return FuturesFollowUpIntentRecord(
        goal_id=str(value["goal_id"]),
        follow_up_intent_id=str(value["follow_up_intent_id"]),
        source_client_order_id=str(value["source_client_order_id"]),
        root_client_order_id=str(value["root_client_order_id"]),
        product_id=str(value["product_id"]),
        source_side=str(value["source_side"]),
        derived_follow_up_side=str(value["derived_follow_up_side"]),
        contract_count=str(value["contract_count"]),
        state=str(value["state"]),
        source_status_at_attach=str(value["source_status_at_attach"]),
        source_observed_at=str(value["source_observed_at"]),
        source_evidence_sha256=str(value["source_evidence_sha256"]),
        reason_code=str(value["reason_code"]),
        correlation_id=str(value["correlation_id"]),
        audit_id=str(value["audit_id"]),
        created_at=str(value["created_at"]),
    )


def get_default_operator_futures_fill_triggered_follow_up_service(
) -> FuturesFillTriggeredFollowUpService:
    global _DEFAULT_SERVICE
    if _DEFAULT_SERVICE is None:
        with _DEFAULT_LOCK:
            if _DEFAULT_SERVICE is None:
                from database import order as order_db
                from database.operator_futures_fill_triggered_follow_up import (
                    get_default_operator_futures_fill_triggered_follow_up_repository,
                )
                from database.operator_futures_manual_lifecycle import (
                    OperatorFuturesManualLifecycleRepository,
                )
                from database.operator_futures_product_policy import (
                    OperatorFuturesProductPolicyRepository,
                )

                activation_repository = (
                    get_default_operator_futures_fill_triggered_follow_up_repository()
                )
                policy_repository = (
                    OperatorFuturesProductPolicyRepository(
                        order_db.DB_CLIENT
                    )
                )
                policy_repository.ensure_schema()
                rest_client = _DeferredFuturesDefaultRestClient()
                portfolio_id = str(
                    os.environ.get(
                        "COINBASE_ADMIN_API_FUTURES_PORTFOLIO_ID"
                    )
                    or ""
                ).strip()
                lifecycle_repository = (
                    OperatorFuturesManualLifecycleRepository(
                        order_db.DB_CLIENT,
                        configured_portfolio_id=portfolio_id or None,
                        goal_id=(
                            FUTURES_FILL_TRIGGERED_FOLLOW_UP_GOAL_ID
                        ),
                        eligibility_evidence_validator=(
                            validate_futures_fill_triggered_eligibility_evidence
                        ),
                        claim_validator=(
                            policy_repository.validate_selection_binding
                        ),
                        client_order_id_prefix=(
                            "operator-futures-follow-up-"
                        ),
                    )
                )
                lifecycle_repository.ensure_schema()

                def active():
                    claimed = activation_repository.list_claimed()
                    if len(claimed) != 1:
                        raise ValueError(
                            "operator_futures_fill_triggered_"
                            "active_claim_ambiguous"
                        )
                    return claimed[0]

                eligibility_reader = FuturesFillTriggeredEligibilityReader(
                    rest_client=rest_client,
                    selection_reader=policy_repository.selection,
                    intent_reader=lambda: _intent_record(
                        activation_repository.read_intent(
                            active().source_client_order_id
                        )
                    ),
                    trigger_evidence_reader=lambda: str(
                        active().trigger_evidence_sha256 or ""
                    ),
                )
                ticket_service = OperatorFuturesProductTicketService(
                    policy_repository=policy_repository,
                    lifecycle_repository=lifecycle_repository,
                    eligibility_reader=eligibility_reader,
                    exchange_executor=(
                        AdminApiFuturesProductTicketExchangeExecutor(
                            rest_client=rest_client
                        )
                    ),
                )
                _DEFAULT_SERVICE = FuturesFillTriggeredFollowUpService(
                    repository=activation_repository,
                    coordinator=FuturesFillTriggeredExecutionCoordinator(
                        ticket_service=ticket_service
                    ),
                )
    return _DEFAULT_SERVICE


def operator_futures_fill_triggered_execution_ready() -> bool:
    return (
        os.environ.get(
            OPERATOR_FUTURES_FILL_TRIGGERED_FOLLOW_UP_ENABLED_ENV
        )
        == "1"
        and get_operator_futures_product_ticket_execution_posture().ready
    )


def reset_operator_futures_fill_triggered_follow_up_service_for_tests(
) -> None:
    global _DEFAULT_SERVICE
    with _DEFAULT_LOCK:
        _DEFAULT_SERVICE = None


__all__ = [
    "OPERATOR_FUTURES_FILL_TRIGGERED_FOLLOW_UP_ENABLED_ENV",
    "get_default_operator_futures_fill_triggered_follow_up_service",
    "operator_futures_fill_triggered_execution_ready",
    "reset_operator_futures_fill_triggered_follow_up_service_for_tests",
]
