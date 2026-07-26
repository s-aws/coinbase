from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
from types import SimpleNamespace

import pytest

from application.admin_api.operator_futures_fill_triggered_follow_up import (
    FUTURES_FILL_TRIGGERED_FOLLOW_UP_GOAL_ID,
    FuturesFillTriggeredControlAction,
    FuturesFillTriggeredControlState,
    FuturesFillTriggeredFollowUpService,
    FuturesFillTriggeredRequestContext,
    FuturesFillTriggeredTriggerState,
    build_futures_follow_up_candidate,
)
from application.admin_api.operator_futures_follow_up_intent import (
    FuturesFollowUpIntentRecord,
)
from application.admin_api.operator_futures_manual_lifecycle import (
    FuturesManualRequestContext,
)
from application.admin_api.operator_futures_product_ticket import (
    FUTURES_PRODUCT_TICKET_GOAL_ID,
    FuturesProductPolicySelection,
)
from application.admin_api.operator_futures_product_ticket_service import (
    OperatorFuturesProductTicketService,
)
from core.enums import AdminFuturesManualCallOutcome


SOURCE_ID = "00000000-0000-4000-8000-000000000501"
INTENT_ID = "00000000-0000-4000-8000-000000000502"
SHA = hashlib.sha256(b"goal-5").hexdigest()
NOW = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)


def _intent(*, source_side: str = "BUY"):
    return FuturesFollowUpIntentRecord(
        goal_id="operator_futures_follow_up_intent_attachment_v1",
        follow_up_intent_id=INTENT_ID,
        source_client_order_id=SOURCE_ID,
        root_client_order_id=SOURCE_ID,
        product_id="AVP-20DEC30-CDE",
        source_side=source_side,
        derived_follow_up_side=(
            "SELL" if source_side == "BUY" else "BUY"
        ),
        contract_count="1",
        state="ATTACHED",
        source_status_at_attach="OPEN",
        source_observed_at="2026-07-25T11:00:00+00:00",
        source_evidence_sha256=SHA,
        reason_code="FULL_FILL_OPPOSITE_ONE_CONTRACT",
        correlation_id="intent-correlation",
        audit_id="00000000-0000-4000-8000-000000000503",
        created_at="2026-07-25T11:01:00+00:00",
    )


def _product():
    return {
        "product_id": "AVP-20DEC30-CDE",
        "product_type": "FUTURE",
        "status": "ONLINE",
        "trading_disabled": False,
        "view_only": False,
        "cancel_only": False,
        "price": "6.95",
        "price_increment": "0.01",
        "base_increment": "1",
        "base_min_size": "1",
        "fcm_trading_session_details": {
            "is_session_open": True,
            "after_hours_order_entry_disabled": False,
        },
        "future_product_details": {
            "contract_code": "AVP",
            "venue": "cde",
            "risk_managed_by": "MANAGED_BY_FCM",
            "contract_expiry": "2030-12-20T16:00:00Z",
            "contract_expiry_type": "EXPIRING",
            "contract_size": "10",
            "intraday_margin_rate": {
                "long_margin_rate": "0.1",
                "short_margin_rate": "0.1",
            },
            "overnight_margin_rate": {
                "long_margin_rate": "0.2",
                "short_margin_rate": "0.2",
            },
        },
    }


def _book():
    return {
        "pricebooks": [
            {
                "product_id": "AVP-20DEC30-CDE",
                "time": "2026-07-25T12:00:00Z",
                "bids": [{"price": "6.90", "size": "1"}],
                "asks": [{"price": "7.00", "size": "1"}],
            }
        ]
    }


def _selection():
    return FuturesProductPolicySelection(
        product_id="AVP-20DEC30-CDE",
        lifecycle="ENABLED",
        policy_revision=2,
        policy_sha256=SHA,
    )


def test_follow_up_candidate_is_opposite_side_and_cap_bounded() -> None:
    candidate = build_futures_follow_up_candidate(
        intent=_intent(source_side="BUY"),
        selection=_selection(),
        product=_product(),
        book=_book(),
        positions={
            "positions": [
                {
                    "product_id": "AVP-20DEC30-CDE",
                    "number_of_contracts": "1",
                    "side": "LONG",
                }
            ]
        },
        available_margin_usdc="1000",
        observed_at=NOW,
        trigger_evidence_sha256=SHA,
    )

    assert candidate["side"] == "SELL"
    assert candidate["contract_count"] == "1"
    assert candidate["limit_price"] == "7.01"
    assert candidate["source_client_order_id"] == SOURCE_ID
    assert candidate["follow_up_intent_id"] == INTENT_ID
    assert candidate["trigger_evidence_sha256"] == SHA
    assert float(candidate["opening_reference_notional_usdc"]) < 100
    assert float(candidate["maximum_exposure_reference_notional_usdc"]) < 150
    assert float(candidate["branch_turnover_reference_notional_usdc"]) < 300


def test_follow_up_candidate_rejects_wrong_position_side() -> None:
    with pytest.raises(
        ValueError,
        match="operator_futures_fill_triggered_position_binding_invalid",
    ):
        build_futures_follow_up_candidate(
            intent=_intent(source_side="BUY"),
            selection=_selection(),
            product=_product(),
            book=_book(),
            positions={
                "positions": [
                    {
                        "product_id": "AVP-20DEC30-CDE",
                        "number_of_contracts": "1",
                        "side": "SHORT",
                    }
                ]
            },
            available_margin_usdc="1000",
            observed_at=NOW,
            trigger_evidence_sha256=SHA,
        )


class _Repository:
    def __init__(self, record):
        self.record = record
        self.calls = []
        self.claimed = False
        self.finalizations = []

    def read(self, source_client_order_id):
        assert source_client_order_id == SOURCE_ID
        return self.record

    def transition_control(self, **kwargs):
        self.calls.append(kwargs)
        action = kwargs["action"]
        target = {
            FuturesFillTriggeredControlAction.ENABLE: (
                FuturesFillTriggeredControlState.ENABLED
            ),
            FuturesFillTriggeredControlAction.PAUSE: (
                FuturesFillTriggeredControlState.PAUSED
            ),
            FuturesFillTriggeredControlAction.RESUME: (
                FuturesFillTriggeredControlState.ENABLED
            ),
            FuturesFillTriggeredControlAction.DISABLE: (
                FuturesFillTriggeredControlState.DISABLED
            ),
            FuturesFillTriggeredControlAction.DRAIN: (
                FuturesFillTriggeredControlState.DRAINED
            ),
        }[action]
        self.record = replace(
            self.record,
            control_state=target,
            revision=self.record.revision + 1,
            delegated_live_authority=(
                action
                in {
                    FuturesFillTriggeredControlAction.ENABLE,
                    FuturesFillTriggeredControlAction.RESUME,
                }
            ),
        )
        return self.record

    def claim_full_fill_trigger(self, *, source_client_order_id):
        assert source_client_order_id == SOURCE_ID
        if self.claimed:
            return None
        self.claimed = True
        self.record = replace(
            self.record,
            control_state=FuturesFillTriggeredControlState.ENABLED,
            trigger_state=FuturesFillTriggeredTriggerState.CLAIMED,
            delegated_live_authority=True,
            trigger_claim_id=(
                "00000000-0000-4000-8000-000000000505"
            ),
            trigger_evidence_sha256=SHA,
        )
        return self.record

    def finalize_trigger(self, **kwargs):
        self.finalizations.append(kwargs)
        lifecycle = kwargs["lifecycle"]
        self.record = replace(
            self.record,
            trigger_state=kwargs["trigger_state"],
            lifecycle_revision=(
                lifecycle.revision if lifecycle is not None else 0
            ),
            child_client_order_id=(
                lifecycle.client_order_id
                if lifecycle is not None
                else None
            ),
            preview_outcome=(
                lifecycle.preview_outcome.value
                if lifecycle is not None
                else "NOT_RUN"
            ),
            create_outcome=(
                lifecycle.create_outcome.value
                if lifecycle is not None
                else "NOT_RUN"
            ),
            reconciliation_outcome=(
                lifecycle.reconciliation_outcome.value
                if lifecycle is not None
                else "NOT_RUN"
            ),
            cancel_outcome=(
                lifecycle.cancel_outcome.value
                if lifecycle is not None
                else "NOT_RUN"
            ),
            diagnostic_code=kwargs["diagnostic_code"],
        )
        return self.record


def _record():
    from application.admin_api.operator_futures_fill_triggered_follow_up import (
        FuturesFillTriggeredActivationRecord,
    )

    return FuturesFillTriggeredActivationRecord(
        goal_id=FUTURES_FILL_TRIGGERED_FOLLOW_UP_GOAL_ID,
        source_client_order_id=SOURCE_ID,
        follow_up_intent_id=INTENT_ID,
        control_state=FuturesFillTriggeredControlState.DISABLED,
        trigger_state=FuturesFillTriggeredTriggerState.UNCLAIMED,
        revision=0,
        delegated_live_authority=False,
        trigger_claim_id=None,
        trigger_evidence_sha256=None,
        lifecycle_revision=0,
        child_client_order_id=None,
        preview_outcome="NOT_RUN",
        create_outcome="NOT_RUN",
        reconciliation_outcome="NOT_RUN",
        cancel_outcome="NOT_RUN",
        diagnostic_code=(
            "operator_futures_fill_triggered_follow_up_disabled"
        ),
        actor_id="operator-1",
        roles=("admin", "trader"),
        correlation_id="intent-correlation",
        audit_id="00000000-0000-4000-8000-000000000503",
        recorded_at="2026-07-25T11:01:00+00:00",
        updated_at="2026-07-25T11:01:00+00:00",
    )


def _context(*, intent: str):
    return FuturesFillTriggeredRequestContext(
        actor_id="operator-1",
        roles=("admin", "trader"),
        expected_revision=0,
        idempotency_key="goal5-control-key",
        correlation_id="goal5-control-correlation",
        audit_id="00000000-0000-4000-8000-000000000504",
        operator_intent=intent,
    )


def test_enable_requires_explicit_single_use_authority_and_resume_is_distinct():
    repository = _Repository(_record())
    service = FuturesFillTriggeredFollowUpService(
        repository=repository,
        coordinator=None,
    )

    with pytest.raises(
        ValueError,
        match="operator_futures_fill_triggered_confirmation_required",
    ):
        service.control(
            source_client_order_id=SOURCE_ID,
            action=FuturesFillTriggeredControlAction.ENABLE,
            context=_context(
                intent="control_futures_fill_triggered_follow_up"
            ),
        )

    enabled = service.control(
        source_client_order_id=SOURCE_ID,
        action=FuturesFillTriggeredControlAction.ENABLE,
        context=_context(
            intent="control_futures_fill_triggered_follow_up"
        ),
        authorize_one_preview_create_and_safe_closeout=True,
        acknowledge_unknown_outcome_consumes_allowance=True,
        acknowledge_child_terms_are_backend_derived=True,
    )
    assert enabled.control_state is FuturesFillTriggeredControlState.ENABLED
    assert enabled.delegated_live_authority is True


def test_goal5_refresh_intent_cannot_use_goal3_lifecycle_ledger() -> None:
    lifecycle_repository = type(
        "LifecycleRepository",
        (),
        {"goal_id": FUTURES_PRODUCT_TICKET_GOAL_ID},
    )()
    service = OperatorFuturesProductTicketService(
        policy_repository=object(),
        lifecycle_repository=lifecycle_repository,
        eligibility_reader=object(),
        exchange_executor=object(),
    )
    context = FuturesManualRequestContext(
        actor_id="operator-1",
        roles=("admin", "trader"),
        expected_revision=0,
        idempotency_key="goal5-ledger-boundary",
        correlation_id="goal5-ledger-boundary",
        audit_id="00000000-0000-4000-8000-000000000504",
        operator_intent=(
            "refresh_one_futures_fill_triggered_follow_up_eligibility_cycle"
        ),
        authorize_one_no_retry_six_category_cycle=True,
        acknowledge_cycle_is_goal_global_and_limited_to_ten=True,
        acknowledge_unsuccessful_or_unknown_cycle_fails_closed=True,
    )

    with pytest.raises(
        ValueError,
        match="operator_futures_product_ticket_goal_binding_invalid",
    ):
        service.refresh(context=context)


def test_authoritative_full_fill_dispatches_once_and_finalizes_exact_child():
    repository = _Repository(_record())
    lifecycle = SimpleNamespace(
        revision=9,
        client_order_id="operator-futures-follow-up-exact-child",
        preview_outcome=AdminFuturesManualCallOutcome.ACCEPTED,
        create_outcome=AdminFuturesManualCallOutcome.ACCEPTED,
        reconciliation_outcome=AdminFuturesManualCallOutcome.ACCEPTED,
        cancel_outcome=AdminFuturesManualCallOutcome.ACCEPTED,
        diagnostic_code="operator_futures_product_ticket_cancel_accepted",
    )

    class _Coordinator:
        def __init__(self):
            self.calls = []

        def execute(self, activation):
            self.calls.append(activation)
            return lifecycle

    coordinator = _Coordinator()
    service = FuturesFillTriggeredFollowUpService(
        repository=repository,
        coordinator=coordinator,
    )

    terminal = service.on_source_reconciled(SOURCE_ID)
    replay = service.on_source_reconciled(SOURCE_ID)

    assert replay is None
    assert len(coordinator.calls) == 1
    assert len(repository.finalizations) == 1
    assert terminal is not None
    assert (
        terminal.trigger_state
        is FuturesFillTriggeredTriggerState.COMPLETED
    )
    assert terminal.child_client_order_id == (
        "operator-futures-follow-up-exact-child"
    )
    assert terminal.preview_outcome == "ACCEPTED"
    assert terminal.create_outcome == "ACCEPTED"
    assert terminal.reconciliation_outcome == "ACCEPTED"
    assert terminal.cancel_outcome == "ACCEPTED"
