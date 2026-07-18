from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from application.admin_api.models import AdminOrderFollowUpIntentAttachRequest
from application.admin_api.operator_follow_up_intent import (
    ATTACH_SINGLE_FOLLOW_UP_INTENT,
    OperatorFollowUpIntentError,
    OperatorFollowUpIntentRequestContext,
    OperatorFollowUpIntentService,
)
from database.order_follow_up_intent import (
    FollowUpIntentAttachResult,
    FollowUpIntentEligibility,
    FollowUpIntentRecord,
    FollowUpIntentStoreConflict,
)


SOURCE_ID = "d24c9fc3-29c2-4e76-87d7-3d27cb94530f"
ROOT_ID = "87aa9a2d-b015-4701-b7e5-63cc26360ad2"


def _eligibility() -> FollowUpIntentEligibility:
    return FollowUpIntentEligibility(
        source_client_order_id=SOURCE_ID,
        root_client_order_id=ROOT_ID,
        source_found=True,
        eligible=False,
        eligibility_status="attached",
        blockers=("follow_up_intent_already_attached",),
        source_status="OPEN",
        source_ownership_provenance="ADMIN_FILL_FOLLOW_UP",
        product_id="BTC-USDC",
        product_type="SPOT",
        source_is_child=True,
        source_authoritative_zero_fill=True,
        source_follow_up_child_absent=True,
        automatic_semantic_claim_absent=False,
        portfolio_scope_sha256="a" * 64,
        slot_used=1,
        semantic_intent="EXIT",
        derived_follow_up_side="SELL",
    )


def _record() -> FollowUpIntentRecord:
    return FollowUpIntentRecord(
        follow_up_intent_id="0ec90842-d875-4a7b-9eb1-333c7d618bb1",
        claim_id="6cf63093-4463-4855-bd7d-ab3ca1b6bbbe",
        source_client_order_id=SOURCE_ID,
        root_client_order_id=ROOT_ID,
        semantic_intent="EXIT",
        derived_follow_up_side="SELL",
        intent_sha256="b" * 64,
        audit_id="1f418e77-9e5e-49f3-861e-a30f942f38fb",
        correlation_id="corr-attach-follow-up-001",
        actor_id="operator-test-001",
        environment="local",
        portfolio_scope_sha256="a" * 64,
        idempotency_key="idem-attach-follow-up-001",
        payload_sha256="c" * 64,
        recorded_at="2026-07-18T12:00:00+00:00",
    )


class _AcceptedRepository:
    def attach(self, _command):
        return FollowUpIntentAttachResult(
            eligibility=_eligibility(),
            record=_record(),
            replayed=False,
        )


class _RejectedRepository:
    def attach(self, _command):
        raise FollowUpIntentStoreConflict("source_status_not_open")


@dataclass
class _AuditStore:
    fail: bool = False
    events: list[object] = field(default_factory=list)

    def append(self, event):
        if self.fail:
            raise OSError("withheld private path")
        self.events.append(event)
        return event.audit_id


def _context() -> OperatorFollowUpIntentRequestContext:
    return OperatorFollowUpIntentRequestContext(
        actor_id="operator-test-001",
        roles=("trader",),
        idempotency_key="idem-attach-follow-up-001",
        correlation_id="corr-attach-follow-up-001",
        operator_intent=ATTACH_SINGLE_FOLLOW_UP_INTENT,
    )


def _request() -> AdminOrderFollowUpIntentAttachRequest:
    return AdminOrderFollowUpIntentAttachRequest(
        acknowledge_future_materialization_requires_fresh_authorization=True
    )


def test_accepted_follow_up_intent_is_visible_in_canonical_admin_audit(monkeypatch):
    monkeypatch.setenv("COINBASE_ADMIN_API_OPERATOR_FOLLOW_UP_INTENT_ENABLED", "1")
    audit_store = _AuditStore()
    service = OperatorFollowUpIntentService(
        repository=_AcceptedRepository(),
        audit_store=audit_store,
    )

    response = service.attach(
        source_client_order_id=SOURCE_ID,
        request=_request(),
        context=_context(),
    )

    assert response.audit_id == _record().audit_id
    assert len(audit_store.events) == 1
    event = audit_store.events[0]
    assert event.audit_id == response.audit_id
    assert event.status.value == "accepted"
    assert event.action_class.value == "local_state_mutation"
    assert event.client_order_id == SOURCE_ID
    assert event.live_exchange_submitted is False
    assert event.live_coinbase_orders_ran is False


def test_rejected_follow_up_intent_is_audited_with_fixed_classification(monkeypatch):
    monkeypatch.setenv("COINBASE_ADMIN_API_OPERATOR_FOLLOW_UP_INTENT_ENABLED", "1")
    audit_store = _AuditStore()
    service = OperatorFollowUpIntentService(
        repository=_RejectedRepository(),
        audit_store=audit_store,
    )

    with pytest.raises(OperatorFollowUpIntentError) as exc_info:
        service.attach(
            source_client_order_id=SOURCE_ID,
            request=_request(),
            context=_context(),
        )

    assert exc_info.value.code == "source_status_not_open"
    assert len(audit_store.events) == 1
    event = audit_store.events[0]
    assert event.status.value == "rejected"
    assert event.failure_stage == "source_status_not_open"
    assert event.message == "follow_up_intent_rejected"


def test_audit_failure_after_persistence_returns_value_blind_unknown(monkeypatch):
    monkeypatch.setenv("COINBASE_ADMIN_API_OPERATOR_FOLLOW_UP_INTENT_ENABLED", "1")
    service = OperatorFollowUpIntentService(
        repository=_AcceptedRepository(),
        audit_store=_AuditStore(fail=True),
    )

    with pytest.raises(OperatorFollowUpIntentError) as exc_info:
        service.attach(
            source_client_order_id=SOURCE_ID,
            request=_request(),
            context=_context(),
        )

    assert exc_info.value.code == "follow_up_intent_audit_unavailable"
    assert exc_info.value.http_status_code == 503
    assert "withheld" not in str(exc_info.value)
