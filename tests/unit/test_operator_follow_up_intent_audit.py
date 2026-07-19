from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import threading

import pytest

from application.admin_api.audit import AdminApiAuditEvent, FileAdminApiAuditStore
from application.admin_api.models import (
    AdminOrderFollowUpCurrentRequestActivity,
    AdminOrderFollowUpIntentAttachRequest,
)
from application.admin_api.operator_follow_up_intent import (
    ATTACH_SINGLE_FOLLOW_UP_INTENT,
    FOLLOW_UP_INTENT_AUDIT_PROJECTION_LIMIT,
    OperatorFollowUpIntentError,
    OperatorFollowUpIntentRequestContext,
    OperatorFollowUpIntentService,
    project_pending_operator_follow_up_intent_audits,
)
from database.order_follow_up_intent import (
    FollowUpIntentAuditOutboxRecord,
    FollowUpIntentAttachResult,
    FollowUpIntentEligibility,
    FollowUpIntentReadback,
    FollowUpIntentRecord,
    FollowUpIntentStoreConflict,
)
from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiPermission,
)
from core.runtime_controller import (
    INFLIGHT_OPERATOR_FOLLOW_UP_INTENT,
    RuntimeController,
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
        automatic_semantic_claim_absent=True,
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
    replayed = False

    def __init__(self):
        self.audit_projected = False
        self.mark_projected_calls = 0
        self.read_calls = 0
        self.list_limits: list[int] = []

    def attach(self, _command):
        return FollowUpIntentAttachResult(
            eligibility=_eligibility(),
            record=_record(),
            replayed=self.replayed,
        )

    def read(self, _source_client_order_id):
        self.read_calls += 1
        return FollowUpIntentReadback(
            eligibility=_eligibility(),
            record=_record(),
        )

    def read_audit_outbox(self, audit_id):
        event = _canonical_audit_event(audit_id=audit_id)
        payload = event.model_dump(mode="json")
        return FollowUpIntentAuditOutboxRecord(
            audit_id=audit_id,
            follow_up_intent_id=_record().follow_up_intent_id,
            source_client_order_id=SOURCE_ID,
            event=payload,
            event_sha256=hashlib.sha256(
                json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            recorded_at=_record().recorded_at,
            projected_at=(
                _record().recorded_at if self.audit_projected else None
            ),
        )

    def mark_audit_projected(self, *, audit_id, event_sha256):
        outbox = self.read_audit_outbox(audit_id)
        assert event_sha256 == outbox.event_sha256
        self.mark_projected_calls += 1
        self.audit_projected = True
        return self.read_audit_outbox(audit_id)

    def list_unprojected_audit_outbox(self, *, limit):
        self.list_limits.append(limit)
        if self.audit_projected:
            return ()
        return (self.read_audit_outbox(_record().audit_id),)


class _RejectedRepository:
    def attach(self, _command):
        raise FollowUpIntentStoreConflict("source_status_not_open")


@dataclass
class _AuditStore:
    fail_appends_remaining: int = 0
    fail_lookup: bool = False
    events: list[object] = field(default_factory=list)

    def append(self, event):
        if self.fail_appends_remaining:
            self.fail_appends_remaining -= 1
            raise OSError("withheld private path")
        self.events.append(event)
        return event.audit_id

    def find_by_audit_id(self, audit_id):
        if self.fail_lookup:
            raise OSError("withheld private lookup path")
        return next(
            (
                event
                for event in reversed(self.events)
                if getattr(event, "audit_id", None) == audit_id
            ),
            None,
        )


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


def _canonical_audit_event(
    *,
    audit_id: str = "1f418e77-9e5e-49f3-861e-a30f942f38fb",
    actor_id: str = "operator-test-001",
) -> AdminApiAuditEvent:
    return AdminApiAuditEvent(
        audit_id=audit_id,
        recorded_at="2026-07-18T12:00:00+00:00",
        actor_id=actor_id,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.ORDER_CREATE,
        endpoint="/api/v1/orders/{source_client_order_id}/follow-up-intent",
        request_id="corr-attach-follow-up-001",
        operator_intent=ATTACH_SINGLE_FOLLOW_UP_INTENT,
        idempotency_key="idem-attach-follow-up-001",
        client_order_id=SOURCE_ID,
        status=AdminApiCommandStatus.ACCEPTED,
        message="follow_up_intent_attached",
    )


def test_accepted_follow_up_intent_is_visible_in_canonical_admin_audit(monkeypatch):
    monkeypatch.setenv("COINBASE_ADMIN_API_OPERATOR_FOLLOW_UP_INTENT_ENABLED", "1")
    audit_store = _AuditStore()
    service = OperatorFollowUpIntentService(
        repository=_AcceptedRepository(),
        audit_store=audit_store,
        runtime_controller_factory=RuntimeController,
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
        runtime_controller_factory=RuntimeController,
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
        audit_store=_AuditStore(fail_appends_remaining=1),
        runtime_controller_factory=RuntimeController,
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


def test_same_key_replay_repairs_missing_canonical_audit_once(monkeypatch):
    monkeypatch.setenv("COINBASE_ADMIN_API_OPERATOR_FOLLOW_UP_INTENT_ENABLED", "1")
    repository = _AcceptedRepository()
    audit_store = _AuditStore(fail_appends_remaining=1)
    service = OperatorFollowUpIntentService(
        repository=repository,
        audit_store=audit_store,
        runtime_controller_factory=RuntimeController,
    )

    with pytest.raises(OperatorFollowUpIntentError) as first_error:
        service.attach(
            source_client_order_id=SOURCE_ID,
            request=_request(),
            context=_context(),
        )
    assert first_error.value.code == "follow_up_intent_audit_unavailable"
    assert audit_store.events == []

    repository.replayed = True
    replay = service.attach(
        source_client_order_id=SOURCE_ID,
        request=_request(),
        context=_context(),
    )
    repeated_replay = service.attach(
        source_client_order_id=SOURCE_ID,
        request=_request(),
        context=_context(),
    )

    assert replay.replayed is True
    assert repeated_replay.replayed is True
    assert len(audit_store.events) == 1
    repaired = audit_store.events[0]
    assert repaired.audit_id == _record().audit_id
    assert repaired.recorded_at == _record().recorded_at
    assert repaired.status.value == "accepted"
    assert repaired.request_id == _record().correlation_id
    assert repaired.actor_id == _record().actor_id
    assert repaired.idempotency_key == _record().idempotency_key
    assert repository.audit_projected is True
    assert repository.mark_projected_calls == 1


def test_same_key_replay_rejects_mismatched_or_unreadable_canonical_audit(
    monkeypatch,
):
    monkeypatch.setenv("COINBASE_ADMIN_API_OPERATOR_FOLLOW_UP_INTENT_ENABLED", "1")
    repository = _AcceptedRepository()
    repository.replayed = True

    mismatched_store = _AuditStore(events=[object()])
    mismatched_store.find_by_audit_id = lambda _audit_id: {
        "audit_id": _record().audit_id,
        "unexpected_private_field": "must_not_be_echoed",
    }
    service = OperatorFollowUpIntentService(
        repository=repository,
        audit_store=mismatched_store,
        runtime_controller_factory=RuntimeController,
    )
    with pytest.raises(OperatorFollowUpIntentError) as mismatch_error:
        service.attach(
            source_client_order_id=SOURCE_ID,
            request=_request(),
            context=_context(),
        )
    assert mismatch_error.value.code == "follow_up_intent_audit_mismatch"
    assert "private" not in str(mismatch_error.value)

    lookup_store = _AuditStore(fail_lookup=True)
    service = OperatorFollowUpIntentService(
        repository=repository,
        audit_store=lookup_store,
        runtime_controller_factory=RuntimeController,
    )
    with pytest.raises(OperatorFollowUpIntentError) as lookup_error:
        service.attach(
            source_client_order_id=SOURCE_ID,
            request=_request(),
            context=_context(),
        )
    assert lookup_error.value.code == "follow_up_intent_audit_unavailable"
    assert "withheld" not in str(lookup_error.value)


def test_attach_is_rejected_after_shutdown_before_persistence(monkeypatch):
    monkeypatch.setenv("COINBASE_ADMIN_API_OPERATOR_FOLLOW_UP_INTENT_ENABLED", "1")
    controller = RuntimeController()
    controller.request_shutdown()
    repository = _AcceptedRepository()
    repository.attach_calls = 0
    original_attach = repository.attach

    def attach(command):
        repository.attach_calls += 1
        return original_attach(command)

    repository.attach = attach
    audit_store = _AuditStore()
    service = OperatorFollowUpIntentService(
        repository=repository,
        audit_store=audit_store,
        runtime_controller_factory=lambda: controller,
    )

    with pytest.raises(OperatorFollowUpIntentError) as exc_info:
        service.attach(
            source_client_order_id=SOURCE_ID,
            request=_request(),
            context=_context(),
        )

    assert exc_info.value.code == "follow_up_intent_runtime_not_admitting"
    assert exc_info.value.http_status_code == 503
    assert repository.attach_calls == 0
    assert audit_store.events == []


def test_started_attach_keeps_shutdown_draining_through_audit(monkeypatch):
    monkeypatch.setenv("COINBASE_ADMIN_API_OPERATOR_FOLLOW_UP_INTENT_ENABLED", "1")
    controller = RuntimeController()
    repository_started = threading.Event()
    release_repository = threading.Event()
    attach_finished = threading.Event()
    drain_finished = threading.Event()
    outcomes: dict[str, object] = {}

    class BlockingRepository(_AcceptedRepository):
        def attach(self, command):
            repository_started.set()
            assert release_repository.wait(timeout=2)
            return super().attach(command)

    service = OperatorFollowUpIntentService(
        repository=BlockingRepository(),
        audit_store=_AuditStore(),
        runtime_controller_factory=lambda: controller,
    )

    def run_attach() -> None:
        try:
            outcomes["attach"] = service.attach(
                source_client_order_id=SOURCE_ID,
                request=_request(),
                context=_context(),
            )
        finally:
            attach_finished.set()

    def run_drain() -> None:
        try:
            outcomes["drain"] = controller.drain_and_stop(timeout_seconds=2)
        finally:
            drain_finished.set()

    attach_thread = threading.Thread(target=run_attach)
    attach_thread.start()
    assert repository_started.wait(timeout=1)
    assert controller.inflight_snapshot() == {
        INFLIGHT_OPERATOR_FOLLOW_UP_INTENT: 1
    }

    drain_thread = threading.Thread(target=run_drain)
    drain_thread.start()
    assert drain_finished.wait(timeout=0.1) is False
    assert attach_finished.is_set() is False

    release_repository.set()
    attach_thread.join(timeout=2)
    drain_thread.join(timeout=2)

    assert attach_finished.is_set() is True
    assert drain_finished.is_set() is True
    assert outcomes["attach"].status.value == "accepted"
    assert outcomes["drain"].drained_clean is True
    assert controller.inflight_snapshot() == {}


def test_authoritative_get_requires_outbox_but_never_projects_or_writes(
    monkeypatch,
):
    monkeypatch.setenv("COINBASE_ADMIN_API_OPERATOR_FOLLOW_UP_INTENT_ENABLED", "1")
    repository = _AcceptedRepository()

    class ProjectionForbiddenAuditStore:
        def append(self, _event):
            pytest.fail("GET must not append a file audit projection")

        def find_by_audit_id(self, _audit_id):
            pytest.fail("GET must not inspect or repair the file projection")

    service = OperatorFollowUpIntentService(
        repository=repository,
        audit_store=ProjectionForbiddenAuditStore(),
        runtime_controller_factory=RuntimeController,
    )

    response = service.read(source_client_order_id=SOURCE_ID)

    assert response.follow_up_intent is not None
    assert response.follow_up_intent.audit_id == _record().audit_id
    assert response.read_only is True
    assert response.local_state_mutated is False
    assert repository.read_calls == 1
    assert repository.mark_projected_calls == 0


def test_file_audit_store_unique_projection_is_full_file_exact_and_idempotent(
    tmp_path,
):
    path = tmp_path / "admin-audit.jsonl"
    canonical = _canonical_audit_event()
    noise = [
        _canonical_audit_event(
            audit_id=f"noise-audit-{index}",
            actor_id=f"noise-actor-{index}",
        )
        for index in range(501)
    ]
    path.write_text(
        "\n".join(
            event.model_dump_json()
            for event in [canonical, *noise]
        )
        + "\n",
        encoding="utf-8",
    )
    store = FileAdminApiAuditStore(path)

    resolved = store.find_unique_by_audit_id(canonical.audit_id)

    assert resolved == canonical
    before = path.read_bytes()
    assert store.append_unique(canonical) == canonical.audit_id
    assert path.read_bytes() == before

    conflicting = canonical.model_copy(update={"actor_id": "different-actor"})
    with pytest.raises(ValueError) as exc_info:
        store.append_unique(conflicting)
    assert str(exc_info.value) == "admin_api_audit_id_conflict"
    assert path.read_bytes() == before

    assert store.append(conflicting) == conflicting.audit_id
    assert store.find_by_audit_id(canonical.audit_id) == conflicting
    with pytest.raises(ValueError, match="admin_api_audit_id_conflict"):
        store.find_unique_by_audit_id(canonical.audit_id)


def test_file_audit_store_unique_projection_preserves_source_event_field_set(
    tmp_path,
):
    path = tmp_path / "admin-audit.jsonl"
    source_event = _canonical_audit_event().model_dump(mode="json")
    source_event.pop("current_request_activity")
    canonical = AdminApiAuditEvent.model_validate(source_event)
    assert "current_request_activity" not in canonical.model_fields_set

    store = FileAdminApiAuditStore(path)
    assert store.append_unique(canonical) == canonical.audit_id

    projected_event = json.loads(path.read_text(encoding="utf-8"))
    assert projected_event == source_event
    assert hashlib.sha256(
        json.dumps(
            projected_event,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest() == hashlib.sha256(
        json.dumps(
            source_event,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def test_file_audit_store_unique_projection_keeps_complete_explicit_activity(
    tmp_path,
):
    path = tmp_path / "admin-audit.jsonl"
    activity = AdminOrderFollowUpCurrentRequestActivity(
        sdk_mutation_invocation_state="NOT_INVOKED",
        transport_submission_state="NOT_SUBMITTED",
        exchange_mutation_state="NOT_MUTATED",
        read_accounting_state="EXACT",
        observed_read_count=0,
    )
    canonical = _canonical_audit_event().model_copy(
        update={"current_request_activity": activity}
    )

    store = FileAdminApiAuditStore(path)
    assert store.append_unique(canonical) == canonical.audit_id

    projected_event = json.loads(path.read_text(encoding="utf-8"))
    assert projected_event["current_request_activity"] == {
        "sdk_mutation_invocation_state": "NOT_INVOKED",
        "transport_submission_state": "NOT_SUBMITTED",
        "exchange_mutation_state": "NOT_MUTATED",
        "read_accounting_state": "EXACT",
        "observed_read_count": 0,
        "accounting_scope": "current_request",
    }


def test_bounded_startup_projector_repairs_pending_and_leaves_failures_pending():
    repository = _AcceptedRepository()
    audit_store = _AuditStore(fail_appends_remaining=1)

    failed = project_pending_operator_follow_up_intent_audits(
        repository=repository,
        audit_store=audit_store,
        limit=10_000,
    )

    assert failed == {
        "limit": FOLLOW_UP_INTENT_AUDIT_PROJECTION_LIMIT,
        "scanned": 1,
        "projected": 0,
        "failed": 1,
        "scan_failed": False,
    }
    assert repository.audit_projected is False
    assert repository.mark_projected_calls == 0
    assert audit_store.events == []

    repaired = project_pending_operator_follow_up_intent_audits(
        repository=repository,
        audit_store=audit_store,
        limit=10_000,
    )

    assert repaired == {
        "limit": FOLLOW_UP_INTENT_AUDIT_PROJECTION_LIMIT,
        "scanned": 1,
        "projected": 1,
        "failed": 0,
        "scan_failed": False,
    }
    assert repository.list_limits == [
        FOLLOW_UP_INTENT_AUDIT_PROJECTION_LIMIT,
        FOLLOW_UP_INTENT_AUDIT_PROJECTION_LIMIT,
    ]
    assert repository.audit_projected is True
    assert repository.mark_projected_calls == 1
    assert len(audit_store.events) == 1
    assert audit_store.events[0].audit_id == _record().audit_id
