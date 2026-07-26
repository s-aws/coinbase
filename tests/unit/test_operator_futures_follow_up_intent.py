from __future__ import annotations

from dataclasses import replace

import pytest

from application.admin_api.operator_futures_follow_up_intent import (
    FUTURES_FOLLOW_UP_INTENT_GOAL_ID,
    FuturesFollowUpIntentRecord,
    FuturesFollowUpIntentRequestContext,
    OperatorFuturesFollowUpIntentService,
    futures_follow_up_source_evidence_sha256,
)


SOURCE_ID = "00000000-0000-4000-8000-000000000044"
OBSERVED_AT = "2026-07-25T12:00:00+00:00"


class FakeRepository:
    def __init__(self, *, projection: dict[str, object] | None) -> None:
        self.projection = projection
        self.intent: FuturesFollowUpIntentRecord | None = None
        self.attach_calls = 0

    def read(
        self, source_client_order_id: str
    ) -> tuple[dict[str, object] | None, FuturesFollowUpIntentRecord | None]:
        assert source_client_order_id == SOURCE_ID
        return self.projection, self.intent

    def attach(
        self,
        *,
        context: FuturesFollowUpIntentRequestContext,
        source_client_order_id: str,
        expected_source_observed_at: str,
        expected_source_evidence_sha256: str,
    ) -> tuple[FuturesFollowUpIntentRecord, bool]:
        assert context.operator_intent == "attach_futures_follow_up_intent"
        assert source_client_order_id == SOURCE_ID
        assert expected_source_observed_at == OBSERVED_AT
        assert expected_source_evidence_sha256 == EVIDENCE_SHA256
        self.attach_calls += 1
        if self.intent is None:
            self.intent = FuturesFollowUpIntentRecord(
                goal_id=FUTURES_FOLLOW_UP_INTENT_GOAL_ID,
                follow_up_intent_id=(
                    "00000000-0000-4000-8000-000000000045"
                ),
                source_client_order_id=SOURCE_ID,
                root_client_order_id=SOURCE_ID,
                product_id="AVP-20DEC30-CDE",
                source_side="BUY",
                derived_follow_up_side="SELL",
                contract_count="1",
                state="ATTACHED",
                source_status_at_attach="OPEN",
                source_observed_at=OBSERVED_AT,
                source_evidence_sha256=EVIDENCE_SHA256,
                reason_code="FULL_FILL_OPPOSITE_ONE_CONTRACT",
                correlation_id=context.correlation_id,
                audit_id=context.audit_id,
                created_at=OBSERVED_AT,
            )
            return self.intent, False
        return self.intent, True


def _projection(**updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "client_order_id": SOURCE_ID,
        "product_id": "AVP-20DEC30-CDE",
        "side": "BUY",
        "status": "OPEN",
        "size": "1",
        "observed_at": OBSERVED_AT,
        "exchange_order_id_sha256": "b" * 64,
        "authoritatively_nonterminal": True,
    }
    value.update(updates)
    return value


EVIDENCE_SHA256 = futures_follow_up_source_evidence_sha256(_projection())


def _context(**updates: object) -> FuturesFollowUpIntentRequestContext:
    value = FuturesFollowUpIntentRequestContext(
        actor_id="operator-1",
        roles=("trader",),
        idempotency_key="00000000-0000-4000-8000-000000000046",
        correlation_id="00000000-0000-4000-8000-000000000047",
        audit_id="00000000-0000-4000-8000-000000000048",
        operator_intent="attach_futures_follow_up_intent",
        reason_code="FULL_FILL_OPPOSITE_ONE_CONTRACT",
        acknowledge_future_materialization_requires_fresh_authorization=True,
        acknowledge_no_coinbase_call_or_child_creation=True,
    )
    return replace(value, **updates)


def test_read_derives_one_contract_opposite_side_without_exchange_authority() -> None:
    service = OperatorFuturesFollowUpIntentService(
        repository=FakeRepository(projection=_projection())
    )

    readback = service.read(SOURCE_ID)

    assert readback.eligibility.eligible is True
    assert readback.eligibility.blockers == ()
    assert readback.eligibility.derived_follow_up_side == "SELL"
    assert readback.eligibility.contract_count == "1"
    assert readback.eligibility.source_evidence_sha256 == EVIDENCE_SHA256
    assert readback.follow_up_intent is None
    assert readback.coinbase_calls == 0
    assert readback.child_created is False


@pytest.mark.parametrize(
    ("updates", "blocker"),
    [
        ({"status": "FILLED"}, "source_status_not_open"),
        (
            {"authoritatively_nonterminal": False},
            "source_not_authoritatively_nonterminal",
        ),
        ({"product_id": "ETH-USDC"}, "source_product_not_configured"),
        ({"size": "2"}, "source_not_exactly_one_contract"),
        ({"side": "UNKNOWN"}, "source_side_invalid"),
    ],
)
def test_read_fails_closed_for_ineligible_source(
    updates: dict[str, object],
    blocker: str,
) -> None:
    service = OperatorFuturesFollowUpIntentService(
        repository=FakeRepository(projection=_projection(**updates))
    )

    readback = service.read(SOURCE_ID)

    assert readback.eligibility.eligible is False
    assert blocker in readback.eligibility.blockers
    assert readback.eligibility.source_evidence_sha256 is not None


def test_read_fails_closed_when_source_projection_is_missing() -> None:
    service = OperatorFuturesFollowUpIntentService(
        repository=FakeRepository(projection=None)
    )

    readback = service.read(SOURCE_ID)

    assert readback.eligibility.eligible is False
    assert readback.eligibility.blockers == ("source_order_not_found",)
    assert readback.eligibility.source_evidence_sha256 is None


def test_attached_intent_blocks_duplicate_source() -> None:
    repository = FakeRepository(projection=_projection())
    service = OperatorFuturesFollowUpIntentService(repository=repository)
    service.attach(
        context=_context(),
        source_client_order_id=SOURCE_ID,
        expected_source_observed_at=OBSERVED_AT,
        expected_source_evidence_sha256=EVIDENCE_SHA256,
    )

    readback = service.read(SOURCE_ID)

    assert readback.eligibility.eligible is False
    assert readback.eligibility.blockers == (
        "futures_follow_up_intent_already_attached",
    )
    assert readback.follow_up_intent is not None
    assert readback.follow_up_intent.root_client_order_id == SOURCE_ID
    assert readback.follow_up_intent.derived_follow_up_side == "SELL"


def test_attach_requires_both_explicit_acknowledgements() -> None:
    repository = FakeRepository(projection=_projection())
    service = OperatorFuturesFollowUpIntentService(repository=repository)

    with pytest.raises(
        ValueError,
        match="operator_futures_follow_up_intent_confirmation_required",
    ):
        service.attach(
            context=_context(
                acknowledge_no_coinbase_call_or_child_creation=False
            ),
            source_client_order_id=SOURCE_ID,
            expected_source_observed_at=OBSERVED_AT,
            expected_source_evidence_sha256=EVIDENCE_SHA256,
        )

    assert repository.attach_calls == 0


def test_attach_rejects_wrong_operator_intent() -> None:
    repository = FakeRepository(projection=_projection())
    service = OperatorFuturesFollowUpIntentService(repository=repository)

    with pytest.raises(
        ValueError,
        match="operator_futures_follow_up_intent_operator_intent_invalid",
    ):
        service.attach(
            context=_context(operator_intent="attach_single_follow_up_intent"),
            source_client_order_id=SOURCE_ID,
            expected_source_observed_at=OBSERVED_AT,
            expected_source_evidence_sha256=EVIDENCE_SHA256,
        )

    assert repository.attach_calls == 0
