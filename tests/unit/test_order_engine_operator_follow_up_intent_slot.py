from __future__ import annotations

from threading import RLock
from types import SimpleNamespace

import pytest

from core.order_engine import OrderEngine
from core.operator_follow_up_intent import operator_follow_up_intent_enabled


class _ClaimingOrderBook:
    def __init__(self) -> None:
        self.states: dict[tuple[str, str], str] = {}

    def try_claim_follow_up(self, kind: str, source_client_order_id: str) -> bool:
        key = (kind, source_client_order_id)
        if key in self.states:
            return False
        self.states[key] = "processing"
        return True

    def release_follow_up(self, kind: str, source_client_order_id: str) -> None:
        self.states.pop((kind, source_client_order_id), None)

    def complete_follow_up(self, kind: str, source_client_order_id: str) -> None:
        self.states[(kind, source_client_order_id)] = "done"


class _DurableDb:
    FOLLOW_UP_INTENT_DURABLE_SLOT_REQUIRED = True

    def __init__(self, claim_result: str | None = "claim-001") -> None:
        self.claim_result = claim_result
        self.claim_calls: list[tuple[str, str]] = []
        self.release_calls: list[tuple[str, str, str]] = []
        self.complete_calls: list[tuple[str, str, str]] = []
        self.fill_activity_allowed = True
        self.fill_activity_calls: list[str] = []

    def try_claim_automatic_order_follow_up(
        self,
        *,
        source_client_order_id: str,
        trigger: str,
    ) -> str | None:
        self.claim_calls.append((trigger, source_client_order_id))
        return self.claim_result

    def release_automatic_order_follow_up_claim(
        self,
        *,
        source_client_order_id: str,
        trigger: str,
        claim_id: str,
    ) -> bool:
        self.release_calls.append((trigger, source_client_order_id, claim_id))
        return True

    def complete_automatic_order_follow_up_claim(
        self,
        *,
        source_client_order_id: str,
        trigger: str,
        claim_id: str,
    ) -> bool:
        self.complete_calls.append((trigger, source_client_order_id, claim_id))
        return True

    def mark_order_follow_up_positive_fill_activity(
        self,
        *,
        source_client_order_id: str,
    ) -> bool:
        self.fill_activity_calls.append(source_client_order_id)
        return self.fill_activity_allowed


def _engine(db: object) -> OrderEngine:
    engine = OrderEngine.__new__(OrderEngine)
    engine.db_module = db
    engine.orderbook = _ClaimingOrderBook()
    engine.orderbook_lock = RLock()
    engine._durable_follow_up_claim_ids = {}
    engine.log_message = lambda *_args, **_kwargs: None
    return engine


@pytest.mark.parametrize("trigger", ["filled", "cancelled"])
def test_operator_slot_blocks_automatic_terminal_follow_up_before_local_claim(trigger: str):
    db = _DurableDb(claim_result=None)
    engine = _engine(db)

    claimed = engine.claim_follow_up_processing(trigger, "source-001")

    assert claimed is False
    assert db.claim_calls == [(trigger, "source-001")]
    assert engine.orderbook.states == {}


@pytest.mark.parametrize("value", [None, "", "0", "true", "TRUE", "yes", "2"])
def test_operator_follow_up_intent_gate_requires_exact_one(monkeypatch, value):
    if value is None:
        monkeypatch.delenv(
            "COINBASE_ADMIN_API_OPERATOR_FOLLOW_UP_INTENT_ENABLED",
            raising=False,
        )
    else:
        monkeypatch.setenv(
            "COINBASE_ADMIN_API_OPERATOR_FOLLOW_UP_INTENT_ENABLED",
            value,
        )

    assert operator_follow_up_intent_enabled() is False


def test_operator_follow_up_intent_gate_accepts_exact_one(monkeypatch):
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_FOLLOW_UP_INTENT_ENABLED",
        "1",
    )

    assert operator_follow_up_intent_enabled() is True


def test_disabled_durable_slot_preserves_existing_local_claim_path():
    db = _DurableDb()
    db.FOLLOW_UP_INTENT_DURABLE_SLOT_REQUIRED = False
    engine = _engine(db)

    assert engine.claim_follow_up_processing("filled", "source-001") is True
    assert db.claim_calls == []
    assert engine.orderbook.states[("filled", "source-001")] == "processing"


def test_enabled_feature_does_not_interlock_an_out_of_scope_order():
    db = _DurableDb()
    db.FOLLOW_UP_INTENT_DURABLE_SLOT_APPLIES = lambda _source_id: False
    engine = _engine(db)

    assert engine.claim_follow_up_processing("filled", "external-source") is True
    assert db.claim_calls == []
    assert engine.orderbook.states[("filled", "external-source")] == "processing"


def test_out_of_scope_fill_does_not_require_operator_slot_marker(monkeypatch):
    db = _DurableDb()
    db.FOLLOW_UP_INTENT_DURABLE_SLOT_APPLIES = lambda _source_id: False
    engine = _engine(db)
    delta = SimpleNamespace(
        client_order_id="external-source",
        is_new_match=True,
        is_terminal=False,
        cumulative_quantity=1.0,
        number_of_fills=1,
        completion_percentage=10.0,
    )
    record = SimpleNamespace()
    engine.order_progress_tracker = SimpleNamespace(
        ingest=lambda _order: delta,
        get_record=lambda _source: record,
    )
    engine.fill_repo = object()
    engine._append_derived_fill_with_hooks = lambda _delta: calls.append("fill")
    engine._maybe_dispatch_hotpoint = lambda _delta: calls.append("hotpoint")
    engine._append_order_match_audit = lambda *_args: calls.append("audit")
    engine._persist_progress_from_record = lambda **_kwargs: calls.append("progress")
    engine._maybe_create_partial_fill_follow_up = lambda *_args: calls.append("partial")
    calls: list[str] = []
    monkeypatch.setattr("core.order_engine.LOT_TRACKING_AVAILABLE", True)

    engine._process_ws_order_delta({"client_order_id": "external-source"})

    assert db.fill_activity_calls == []
    assert calls == ["fill", "hotpoint", "audit", "progress", "partial"]


@pytest.mark.parametrize("trigger", ["filled", "cancelled"])
def test_no_operator_slot_preserves_terminal_claim_and_cas_completion(trigger: str):
    db = _DurableDb(claim_result="claim-001")
    engine = _engine(db)

    assert engine.claim_follow_up_processing(trigger, "source-001") is True
    assert engine.orderbook.states[(trigger, "source-001")] == "processing"

    engine.complete_follow_up_processing(trigger, "source-001")

    assert db.complete_calls == [(trigger, "source-001", "claim-001")]
    assert engine.orderbook.states[(trigger, "source-001")] == "done"


def test_durable_claim_failure_fails_closed_and_releases_local_claim():
    class _FailingDb(_DurableDb):
        def try_claim_automatic_order_follow_up(self, **_kwargs):
            raise RuntimeError("private persistence detail must be withheld")

    engine = _engine(_FailingDb())

    assert engine.claim_follow_up_processing("filled", "source-001") is False
    assert engine.orderbook.states == {}


def test_release_keeps_local_claim_when_durable_release_is_unknown():
    class _UnknownReleaseDb(_DurableDb):
        def release_automatic_order_follow_up_claim(self, **_kwargs):
            return False

    engine = _engine(_UnknownReleaseDb())
    assert engine.claim_follow_up_processing("filled", "source-001") is True

    engine.release_follow_up_processing("filled", "source-001")

    assert engine.orderbook.states[("filled", "source-001")] == "processing"


def test_positive_fill_marker_blocks_hotpoint_and_partial_follow_up_but_not_fill_evidence(monkeypatch):
    db = _DurableDb()
    db.fill_activity_allowed = False
    engine = _engine(db)
    delta = SimpleNamespace(
        client_order_id="source-001",
        is_new_match=True,
        is_terminal=False,
        cumulative_quantity=1.0,
        number_of_fills=1,
        completion_percentage=10.0,
    )
    record = SimpleNamespace()
    engine.order_progress_tracker = SimpleNamespace(
        ingest=lambda _order: delta,
        get_record=lambda _source: record,
    )
    engine.fill_repo = object()
    engine._append_derived_fill_with_hooks = lambda _delta: calls.append("fill")
    engine._maybe_dispatch_hotpoint = lambda _delta: calls.append("hotpoint")
    engine._append_order_match_audit = lambda *_args: calls.append("audit")
    engine._persist_progress_from_record = lambda **_kwargs: calls.append("progress")
    engine._maybe_create_partial_fill_follow_up = lambda *_args: calls.append("partial")
    calls: list[str] = []
    monkeypatch.setattr("core.order_engine.LOT_TRACKING_AVAILABLE", True)

    result = engine._process_ws_order_delta({"client_order_id": "source-001"})

    assert result is delta
    assert db.fill_activity_calls == ["source-001"]
    assert calls == ["fill", "audit", "progress"]


def test_positive_fill_marker_allows_existing_automatic_paths_without_operator_intent(monkeypatch):
    db = _DurableDb()
    engine = _engine(db)
    delta = SimpleNamespace(
        client_order_id="source-001",
        is_new_match=True,
        is_terminal=False,
        cumulative_quantity=1.0,
        number_of_fills=1,
        completion_percentage=10.0,
    )
    record = SimpleNamespace()
    engine.order_progress_tracker = SimpleNamespace(
        ingest=lambda _order: delta,
        get_record=lambda _source: record,
    )
    engine.fill_repo = object()
    engine._append_derived_fill_with_hooks = lambda _delta: calls.append("fill")
    engine._maybe_dispatch_hotpoint = lambda _delta: calls.append("hotpoint")
    engine._append_order_match_audit = lambda *_args: calls.append("audit")
    engine._persist_progress_from_record = lambda **_kwargs: calls.append("progress")
    engine._maybe_create_partial_fill_follow_up = lambda *_args: calls.append("partial")
    calls: list[str] = []
    monkeypatch.setattr("core.order_engine.LOT_TRACKING_AVAILABLE", True)

    engine._process_ws_order_delta({"client_order_id": "source-001"})

    assert calls == ["fill", "hotpoint", "audit", "progress", "partial"]
