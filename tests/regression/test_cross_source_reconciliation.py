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
    """Helper context: patch REST_CLIENT + local ledger snapshot."""

    def _apply(rest_client, local_entry_ids):
        rest_patch = patch("configuration.REST_CLIENT", rest_client)
        ledger_patch = patch(
            "core.startup_reconciler._fetch_local_recorded_entry_ids",
            return_value=set(local_entry_ids),
        )
        return rest_patch, ledger_patch

    return _apply


class TestAuditMissedFills:
    @pytest.mark.regression
    def test_clean_when_every_rest_fill_is_locally_recorded(
        self, patch_rest_and_ledger
    ):
        rest = _FakeRestClient(
            [{"fills": [_fill("a"), _fill("b")], "cursor": None, "has_next": False}]
        )
        rp, lp = patch_rest_and_ledger(rest, {"a", "b"})
        with rp, lp:
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
        rp, lp = patch_rest_and_ledger(rest, {"a"})
        with rp, lp:
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
        rp, lp = patch_rest_and_ledger(rest, set())
        with rp, lp:
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
        rp, lp = patch_rest_and_ledger(rest, set())
        with rp, lp:
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
        rp, lp = patch_rest_and_ledger(rest, set())
        with rp, lp:
            audit_missed_fills()
        assert rest.calls, "expected at least one REST call"
        # ``start_date`` must be present and parseable as ISO-8601.
        start = rest.calls[0]["start_date"]
        parsed = datetime.fromisoformat(start.replace("Z", "+00:00"))
        # Default is 24h; allow a wide margin for slow CI.
        delta = datetime.now(timezone.utc) - parsed
        assert timedelta(hours=23) <= delta <= timedelta(hours=25)


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
    """Minimal stand-in carrying just what snapshot_drift_check uses."""

    def __init__(self, in_memory_ids):
        self.orderbook = SimpleNamespace(order={coid: {} for coid in in_memory_ids})
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
