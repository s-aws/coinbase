"""Regression tests for cross-source reconciliation (Phase 3).

Covers:

* :func:`core.startup_reconciler.audit_missed_fills` — paginates the REST
  fills endpoint, diffs against local ledger, and never mutates state.
* :class:`core.periodic_reconciler.PeriodicReconciler` — start/stop
  lifecycle, cooperative shutdown, runs the audit on cadence.
* :meth:`core.order_engine.OrderEngine.snapshot_drift_check` — detects
  WS-only and in-memory-only drift cases without mutating state.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.periodic_reconciler import PeriodicReconciler
from core.startup_reconciler import (
    MissedFillsReport,
    audit_missed_fills,
)


# ---------------------------------------------------------------------------
# audit_missed_fills
# ---------------------------------------------------------------------------


def _fill(entry_id: str, **overrides) -> dict:
    base = {
        "entry_id": entry_id,
        "trade_id": f"trade-{entry_id}",
        "order_id": "exchange-order-1",
        "product_id": "BTC-USDC",
        "side": "BUY",
        "size": "0.10",
        "price": "42000",
        "trade_time": "2026-04-27T10:00:00Z",
    }
    base.update(overrides)
    return base


class _FakeRestClient:
    """REST client stand-in that returns canned ``list_fills`` pages."""

    def __init__(self, pages):
        # ``pages`` is a list of dicts shaped like
        # {"fills": [...], "cursor": "...", "has_next": bool}
        self.pages = list(pages)
        self.calls = []

    def list_fills(self, **kwargs):
        self.calls.append(kwargs)
        if not self.pages:
            return {"fills": [], "cursor": None, "has_next": False}
        return self.pages.pop(0)


@pytest.fixture
def patch_rest_and_ledger():
    """Helper context: patch REST_CLIENT + local ledger snapshot.

    Also stubs the order_id->client_order_id resolver and WS-pending
    qty resolver so audit tests don't need a live database. By default
    every order_id resolves ("owned by us"), which preserves legacy
    test semantics where a missing fill is a real WARNING.
    Tests that need to exercise the unowned/silent-INFO path can
    override the resolver via the returned `oid_to_coid` dict.
    """

    def _apply(rest_client, local_entry_ids, *, oid_to_coid=None,
               ws_pending=None):
        rest_patch = patch("configuration.REST_CLIENT", rest_client)
        ledger_patch = patch(
            "core.startup_reconciler._fetch_local_recorded_entry_ids",
            return_value=set(local_entry_ids),
        )

        def _fake_resolve(oids):
            if oid_to_coid is None:
                # Default: every order_id is owned (legacy semantics).
                return {oid: f"coid-{oid}" for oid in oids}
            return {oid: oid_to_coid[oid] for oid in oids if oid in oid_to_coid}

        oid_patch = patch(
            "core.startup_reconciler._fetch_client_order_ids_for_exchange_order_ids",
            side_effect=_fake_resolve,
        )
        ws_patch = patch(
            "core.startup_reconciler._fetch_ws_pending_qty_by_client_order_id",
            return_value=ws_pending or {},
        )
        return rest_patch, ledger_patch, oid_patch, ws_patch

    return _apply


class TestAuditMissedFills:
    @pytest.mark.regression
    def test_clean_when_every_rest_fill_is_locally_recorded(
        self, patch_rest_and_ledger
    ):
        rest = _FakeRestClient(
            [{"fills": [_fill("a"), _fill("b")], "cursor": None, "has_next": False}]
        )
        rp, lp, op, wp = patch_rest_and_ledger(rest, {"a", "b"})
        with rp, lp, op, wp:
            report = audit_missed_fills()
        assert isinstance(report, MissedFillsReport)
        assert report.has_missed_fills is False
        assert report.rest_fills_examined == 2
        assert report.already_recorded == 2
        assert report.missed == []

    @pytest.mark.regression
    def test_flags_rest_fills_missing_from_local_ledger(
        self, patch_rest_and_ledger
    ):
        rest = _FakeRestClient(
            [{"fills": [_fill("a"), _fill("b")], "cursor": None, "has_next": False}]
        )
        # Default fixture maps every order_id to a coid ("owned"), so
        # the missing fill survives the ownership partition and ends
        # up as a real WARNING-eligible miss.
        rp, lp, op, wp = patch_rest_and_ledger(rest, {"a"})
        with rp, lp, op, wp:
            report = audit_missed_fills()
        assert report.has_missed_fills is True
        assert [f["entry_id"] for f in report.missed] == ["b"]
        assert report.already_recorded == 1

    @pytest.mark.regression
    def test_paginates_and_terminates_on_has_next_false(
        self, patch_rest_and_ledger
    ):
        rest = _FakeRestClient(
            [
                {"fills": [_fill("a")], "cursor": "c1", "has_next": True},
                {"fills": [_fill("b")], "cursor": "c2", "has_next": True},
                {"fills": [_fill("c")], "cursor": None, "has_next": False},
            ]
        )
        rp, lp, op, wp = patch_rest_and_ledger(rest, set())
        with rp, lp, op, wp:
            report = audit_missed_fills()
        assert report.rest_fills_examined == 3
        assert len(rest.calls) == 3
        # Subsequent calls passed the prior cursor.
        assert rest.calls[1]["cursor"] == "c1"
        assert rest.calls[2]["cursor"] == "c2"

    @pytest.mark.regression
    def test_aborts_gracefully_when_rest_fetch_fails(self, patch_rest_and_ledger):
        rest = MagicMock()
        rest.list_fills.side_effect = RuntimeError("API down")
        rp, lp, op, wp = patch_rest_and_ledger(rest, set())
        with rp, lp, op, wp:
            report = audit_missed_fills()
        assert report is not None
        assert report.failed_pages == 1
        # No fills examined and no missed-fills false positives.
        assert report.rest_fills_examined == 0
        assert report.missed == []

    @pytest.mark.regression
    def test_uses_default_lookback_when_since_not_supplied(
        self, patch_rest_and_ledger
    ):
        rest = _FakeRestClient(
            [{"fills": [], "cursor": None, "has_next": False}]
        )
        rp, lp, op, wp = patch_rest_and_ledger(rest, set())
        with rp, lp, op, wp:
            audit_missed_fills()
        assert rest.calls, "expected at least one REST call"
        # ``start_date`` must be present and parseable as ISO-8601.
        start = rest.calls[0]["start_date"]
        parsed = datetime.fromisoformat(start.replace("Z", "+00:00"))
        # Default is 24h; allow a wide margin for slow CI.
        delta = datetime.now(timezone.utc) - parsed
        assert timedelta(hours=23) <= delta <= timedelta(hours=25)

    @pytest.mark.regression
    def test_unowned_fills_downgraded_to_info_summary(
        self, patch_rest_and_ledger, caplog
    ):
        """REST fills for orders we don't own must NOT spam per-fill
        warnings.

        "Don't own" means the exchange `order_id` has no row in
        `order_event_stream` (= no `client_order_id` mapping). That
        happens after a DB wipe, on a fresh install, or for orders
        placed off-engine. None are backfillable and none indicate a
        WS gap on our side; they should produce a single INFO
        summary, not one WARNING per fill.

        This subsumes the old fresh-DB special case: a fresh DB has
        zero mappings → all fills are unowned → silent INFO.
        """
        rest = _FakeRestClient(
            [
                {
                    "fills": [
                        _fill("a", order_id="unknown-1"),
                        _fill("b", order_id="unknown-2"),
                        _fill("c", order_id="unknown-3"),
                    ],
                    "cursor": None,
                    "has_next": False,
                }
            ]
        )
        # Empty oid_to_coid -> every fill is "unowned".
        rp, lp, op, wp = patch_rest_and_ledger(rest, set(), oid_to_coid={})
        with rp, lp, op, wp, caplog.at_level("INFO", logger="StartupReconciler"):
            report = audit_missed_fills()

        # After ownership partition, nothing is missed in the audit
        # sense (we only flag gaps for orders we own).
        assert report.has_missed_fills is False
        assert report.missed == []
        warning_records = [r for r in caplog.records if r.levelno >= 30]
        assert warning_records == [], (
            f"unowned fills must not raise WARNINGs but got: "
            f"{[r.getMessage() for r in warning_records]}"
        )
        info_messages = [r.getMessage() for r in caplog.records if r.levelno == 20]
        assert any("unowned" in msg for msg in info_messages), info_messages

    @pytest.mark.regression
    def test_owned_fills_still_warn_per_fill(
        self, patch_rest_and_ledger, caplog
    ):
        """The inverse case: when a missing REST fill IS for an order we
        own, the WARNING loop must still fire — that's a real WS gap."""
        rest = _FakeRestClient(
            [
                {
                    "fills": [
                        _fill("a", order_id="owned-1"),
                        _fill("b", order_id="owned-2"),
                    ],
                    "cursor": None,
                    "has_next": False,
                }
            ]
        )
        rp, lp, op, wp = patch_rest_and_ledger(
            rest,
            set(),
            oid_to_coid={"owned-1": "coid-1", "owned-2": "coid-2"},
        )
        with rp, lp, op, wp, caplog.at_level("WARNING", logger="StartupReconciler"):
            report = audit_missed_fills()

        assert report.has_missed_fills is True
        assert len(report.missed) == 2
        warning_messages = [
            r.getMessage() for r in caplog.records if r.levelno >= 30
        ]
        # One header + one per fill.
        assert any("orders we own" in m for m in warning_messages)
        assert sum(1 for m in warning_messages if m.startswith("Missed fill:")) == 2


# ---------------------------------------------------------------------------
# PeriodicReconciler
# ---------------------------------------------------------------------------


class TestPeriodicReconciler:
    @pytest.mark.regression
    def test_rejects_non_positive_interval(self):
        with pytest.raises(ValueError):
            PeriodicReconciler(interval_seconds=0)
        with pytest.raises(ValueError):
            PeriodicReconciler(interval_seconds=-5)

    @pytest.mark.regression
    def test_start_is_idempotent(self):
        r = PeriodicReconciler(interval_seconds=60)
        try:
            r.start()
            t1 = r._thread
            r.start()  # second call is a no-op
            assert r._thread is t1
        finally:
            r.stop()

    @pytest.mark.regression
    def test_stop_signals_thread_to_exit_promptly(self):
        # 60s interval; after stop() the wait inside _run must wake
        # immediately, so the thread should die well within 1s.
        r = PeriodicReconciler(interval_seconds=60)
        r.start()
        time.sleep(0.05)
        r.stop()
        # Give the thread a generous window to honor the stop signal.
        deadline = time.monotonic() + 2.0
        while r.is_running and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not r.is_running, "PeriodicReconciler did not stop in time"

    @pytest.mark.regression
    def test_runs_audit_on_each_iteration(self):
        # Use a short interval and patch the audit function to count
        # invocations. Stop after we observe at least 2 calls.
        invocations = []

        def fake_audit(**kwargs):
            invocations.append(kwargs)
            return None

        with patch(
            "core.periodic_reconciler.run_startup_reconciliation",
            side_effect=fake_audit,
        ):
            r = PeriodicReconciler(interval_seconds=1)
            r.start()
            try:
                deadline = time.monotonic() + 4.0
                # First audit fires after the initial wait (~1s); wait
                # for two iterations with margin.
                while r.iterations < 2 and time.monotonic() < deadline:
                    time.sleep(0.05)
            finally:
                r.stop()

        assert r.iterations >= 2, (
            f"expected >=2 iterations, got {r.iterations} "
            f"(invocations={len(invocations)})"
        )
        # Each call passes the auto_heal / audit_fills flags.
        for kwargs in invocations:
            assert kwargs["auto_heal"] is False
            assert kwargs["audit_fills"] is False
            assert kwargs["fail_on_drift"] is False

    @pytest.mark.regression
    def test_continues_after_audit_exception(self):
        call_count = {"n": 0}

        def fake_audit(**kwargs):
            call_count["n"] += 1
            raise RuntimeError("simulated audit failure")

        with patch(
            "core.periodic_reconciler.run_startup_reconciliation",
            side_effect=fake_audit,
        ):
            r = PeriodicReconciler(interval_seconds=1)
            r.start()
            try:
                deadline = time.monotonic() + 4.0
                while call_count["n"] < 2 and time.monotonic() < deadline:
                    time.sleep(0.05)
            finally:
                r.stop()

        # The exception did not kill the thread.
        assert call_count["n"] >= 2
        assert r.iterations >= 2


# ---------------------------------------------------------------------------
# OrderEngine.snapshot_drift_check
# ---------------------------------------------------------------------------


class _FakeEngine:
    """Minimal stand-in carrying just what snapshot_drift_check uses.

    Entries default to status=OPEN because the drift check filters its
    in-memory side to only "venue-open" statuses (OPEN / UPDATE) — empty
    dicts would be invisible to the comparison and break the legacy
    test cases that just want "this id is in memory".
    """

    def __init__(self, in_memory_ids):
        if isinstance(in_memory_ids, dict):
            entries = {coid: dict(data) for coid, data in in_memory_ids.items()}
        else:
            entries = {coid: {"status": "OPEN"} for coid in in_memory_ids}
        self.orderbook = SimpleNamespace(order=entries)
        self.orderbook_lock = threading.RLock()
        self.log_calls = []

    def log_message(self, level, payload):
        self.log_calls.append((level, payload))

    def build_event_log_payload(self, event, **kwargs):
        return {"event": event, **kwargs}


class TestSnapshotDriftCheck:
    @pytest.mark.regression
    def test_clean_when_sets_match(self):
        from core.order_engine import OrderEngine

        engine = _FakeEngine({"a", "b", "c"})
        report = OrderEngine.snapshot_drift_check(
            engine, {"a", "b", "c"}, source="test"
        )
        assert report["ws_only"] == []
        assert report["in_memory_only"] == []
        assert report["in_sync_count"] == 3
        # Only the clean-summary log should be emitted (no per-id warnings).
        events = [p["event"] for _, p in engine.log_calls]
        assert "snapshot_drift_clean" in events
        assert "snapshot_drift_detected" not in events

    @pytest.mark.regression
    def test_detects_ws_only_drift(self):
        from core.order_engine import OrderEngine

        engine = _FakeEngine({"local-only"})
        report = OrderEngine.snapshot_drift_check(
            engine, {"local-only", "ws-only"}, source="test"
        )
        assert report["ws_only"] == ["ws-only"]
        assert report["in_memory_only"] == []
        events = [p["event"] for _, p in engine.log_calls]
        assert "snapshot_drift_detected" in events
        assert "snapshot_drift_ws_only" in events

    @pytest.mark.regression
    def test_detects_in_memory_only_drift(self):
        from core.order_engine import OrderEngine

        engine = _FakeEngine({"a", "b"})
        report = OrderEngine.snapshot_drift_check(
            engine, {"a"}, source="test"
        )
        assert report["ws_only"] == []
        assert report["in_memory_only"] == ["b"]
        events = [p["event"] for _, p in engine.log_calls]
        assert "snapshot_drift_in_memory_only" in events

    @pytest.mark.regression
    def test_does_not_mutate_orderbook(self):
        from core.order_engine import OrderEngine

        engine = _FakeEngine({"a", "b"})
        before = dict(engine.orderbook.order)
        OrderEngine.snapshot_drift_check(engine, {"a", "x"}, source="test")
        assert engine.orderbook.order == before, (
            "snapshot_drift_check must be read-only"
        )

    @pytest.mark.regression
    def test_filters_out_falsy_client_order_ids(self):
        from core.order_engine import OrderEngine

        engine = _FakeEngine({"a"})
        report = OrderEngine.snapshot_drift_check(
            engine, {"a", None, ""}, source="test"
        )
        assert report["ws_count"] == 1
        assert report["in_sync_count"] == 1
        assert report["ws_only"] == []

    @pytest.mark.regression
    def test_in_memory_only_log_includes_diagnostic_fields(self):
        """The orphan-row log payload must carry status/product/qty so
        operators can identify what the leaked entry is without an
        ad-hoc DB query."""
        from core.order_engine import OrderEngine

        engine = _FakeEngine([])
        engine.orderbook.order["leaked"] = {
            "status": "OPEN",
            "product_id": "BTC-USDC",
            "cumulative_quantity": "0.5",
            "leaves_quantity": "0",
            "creation_time": "2026-04-27T10:00:00Z",
        }
        OrderEngine.snapshot_drift_check(engine, set(), source="test")

        in_mem_payloads = [
            payload
            for _, payload in engine.log_calls
            if payload.get("event") == "snapshot_drift_in_memory_only"
        ]
        assert len(in_mem_payloads) == 1
        payload = in_mem_payloads[0]
        assert payload["client_order_id"] == "leaked"
        assert payload["in_memory_status"] == "OPEN"
        assert payload["product_id"] == "BTC-USDC"
        assert payload["cumulative_quantity"] == "0.5"

    @pytest.mark.regression
    @pytest.mark.parametrize(
        "transient_status",
        ["FILLED", "CANCELLED", "FAILED", "PENDING", "CANCEL_QUEUED", "SNAPSHOT"],
    )
    def test_non_open_statuses_never_trigger_in_memory_only(
        self, transient_status
    ):
        """Drift compares apples-to-apples: the venue's open-orders
        snapshot only contains OPEN/UPDATE orders. In-memory entries
        with terminal (FILLED/CANCELLED/FAILED) or pre-ack
        (PENDING/CANCEL_QUEUED) or routing-only (SNAPSHOT) statuses
        must NOT count as drift, even if they're transiently still in
        ``orderbook.order`` waiting for bookkeeping cleanup.

        Regression for 2026-04-27 spam: every WS frame arriving in the
        ~500ms window between FILLED-arrives and hold-clears was
        firing this warning, drowning out real signal.
        """
        from core.order_engine import OrderEngine

        engine = _FakeEngine({"transient": {"status": transient_status}})
        report = OrderEngine.snapshot_drift_check(
            engine, set(), source="test"
        )
        assert report["in_memory_only"] == [], (
            f"status={transient_status} must NOT appear as drift"
        )
        events = [p["event"] for _, p in engine.log_calls]
        assert "snapshot_drift_in_memory_only" not in events
        assert "snapshot_drift_detected" not in events


# ---------------------------------------------------------------------------
# OrderEngine terminal-state eviction (no in-memory leak)
#
# Regression for snapshot_drift_in_memory_only never clearing: terminal
# WS deltas (FILLED, CANCELLED, FAILED) must remove the entry from
# orderbook.order so the next WS snapshot frame sees a consistent set.
# ---------------------------------------------------------------------------


class TestTerminalStatusEvictsOrderbookEntry:
    """Drives ``OrderEngine.process_user_order`` against a stub engine and
    asserts the in-memory entry is gone after each terminal status."""

    def _engine_with_stubbed_handlers(self, monkeypatch):
        from core.order_engine import OrderEngine

        engine = OrderEngine.__new__(OrderEngine)
        engine.orderbook = SimpleNamespace(order={})
        engine.orderbook_lock = threading.RLock()
        engine.websocket_hooks = SimpleNamespace(
            call_pre_order_status=lambda *a, **k: None,
            call_order_normalizers=lambda *a, **k: None,
            call_post_order_status=lambda *a, **k: None,
        )
        engine.stealth_order_bridge = None
        engine.db_helper = SimpleNamespace(
            update_order_parent_status=lambda **kw: None,
            get_parent_order=lambda *_a, **_k: None,
        )

        # Stub away every side effect that isn't the eviction we're testing.
        monkeypatch.setattr(engine, "normalize_product_type", lambda o: "FUTURE")
        monkeypatch.setattr(engine, "_sync_stealth_exchange_order_id", lambda o: None)
        monkeypatch.setattr(engine, "_process_ws_order_delta", lambda o: None)
        monkeypatch.setattr(engine, "is_parent_order", lambda coid: False)
        monkeypatch.setattr(
            engine, "_finalize_partial_fill_progress", lambda *a, **k: None
        )
        monkeypatch.setattr(engine, "handle_filled_order", lambda o: None)
        monkeypatch.setattr(engine, "handle_cancelled_order", lambda o: None)
        monkeypatch.setattr(
            engine, "_update_dashboard_order_status", lambda *a, **k: None
        )
        monkeypatch.setattr(engine, "build_order_log_context", lambda o: {})
        monkeypatch.setattr(engine, "include_debug_fields", lambda **kw: {})
        monkeypatch.setattr(
            engine, "build_event_log_payload", lambda event, **kw: {"event": event}
        )
        monkeypatch.setattr(engine, "log_message", lambda *a, **k: None)
        return engine

    @pytest.mark.regression
    @pytest.mark.parametrize("status", ["FILLED", "CANCELLED", "FAILED"])
    def test_terminal_status_pops_entry(self, monkeypatch, status):
        engine = self._engine_with_stubbed_handlers(monkeypatch)
        order = {
            "client_order_id": "abc",
            "status": status,
            "product_id": "BTC-USDC",
            "outstanding_hold_amount": "0",
        }
        engine.process_user_order(order)
        assert "abc" not in engine.orderbook.order, (
            f"{status} must evict orderbook.order entry to prevent "
            "snapshot_drift_in_memory_only from re-firing every snapshot"
        )

    @pytest.mark.regression
    def test_open_status_does_not_evict(self, monkeypatch):
        """Sanity check: non-terminal OPEN must KEEP the entry."""
        engine = self._engine_with_stubbed_handlers(monkeypatch)
        order = {
            "client_order_id": "abc",
            "status": "OPEN",
            "product_id": "BTC-USDC",
            "outstanding_hold_amount": "0",
        }
        engine.process_user_order(order)
        assert "abc" in engine.orderbook.order
