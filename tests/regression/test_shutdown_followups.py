"""Regression tests for graceful-shutdown follow-up pieces.

Covers:

* :func:`core.startup_reconciler.apply_auto_heal` — only heals the safe
  drift bucket; leaves risky buckets untouched; tolerates per-row
  failures without raising.
* OrderEngine cooperative-shutdown plumbing — ``stop()`` flips the
  shutdown event so periodic loops exit promptly.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.startup_reconciler import (
    HEAL_STATUS_RECONCILED_CLOSED,
    HealResult,
    ReconciliationReport,
    apply_auto_heal,
)


# ---------------------------------------------------------------------------
# apply_auto_heal
# ---------------------------------------------------------------------------


class _FakeDB:
    """Minimal PostgresDB stand-in capturing UPDATE statements."""

    def __init__(self, parent_matches=None, raise_on=None):
        # parent_matches maps client_order_id -> rows-affected.
        self.parent_matches = parent_matches or {}
        self.raise_on = raise_on or set()
        self.calls = []

    def execute_update(self, sql: str, params: tuple) -> int:
        self.calls.append((sql, params))
        coid = params[1]  # (HEAL_STATUS, coid, *terminals)
        if (sql, coid) in self.raise_on or coid in self.raise_on:
            raise RuntimeError(f"injected DB failure for {coid}")
        if "order_parent" in sql:
            return self.parent_matches.get(coid, 0)
        return 0

    def disconnect(self) -> None:
        pass


class TestApplyAutoHeal:
    @pytest.mark.regression
    def test_no_drift_is_no_op(self):
        report = ReconciliationReport()  # all empty
        result = apply_auto_heal(report)
        assert isinstance(result, HealResult)
        assert result.total_healed == 0
        assert result.failed_ids == []

    @pytest.mark.regression
    def test_only_safe_bucket_is_healed(self):
        report = ReconciliationReport(
            unknown_to_local=["risky-1"],
            open_on_exchange_terminal_locally=["risky-2"],
            closed_on_exchange_open_locally=["safe-1", "safe-2"],
        )
        fake = _FakeDB(parent_matches={"safe-1": 1, "safe-2": 1})
        with patch("database.database.PostgresDB", return_value=fake):
            result = apply_auto_heal(report)

        # Risky buckets are reported as skipped, not touched.
        assert "risky-1" in result.skipped_unknown
        assert "risky-2" in result.skipped_open_on_exchange_terminal_locally
        # Safe rows were healed in order_parent.
        assert sorted(result.healed_parent_ids) == ["safe-1", "safe-2"]
        # Heal status is the dedicated marker, not user CANCELLED.
        for sql, params in fake.calls:
            assert params[0] == HEAL_STATUS_RECONCILED_CLOSED

    @pytest.mark.regression
    def test_failure_on_one_row_does_not_abort_others(self):
        report = ReconciliationReport(
            closed_on_exchange_open_locally=["bad", "good"],
        )
        fake = _FakeDB(
            parent_matches={"good": 1},
            raise_on={"bad"},
        )
        with patch("database.database.PostgresDB", return_value=fake):
            result = apply_auto_heal(report)

        assert "bad" in result.failed_ids
        assert "good" in result.healed_parent_ids

    @pytest.mark.regression
    def test_heals_only_safe_bucket_in_flat_hierarchy(self):
        # Flat hierarchy: every healable order lives in order_parent
        # (children + parents share that table). One UPDATE pass.
        report = ReconciliationReport(
            closed_on_exchange_open_locally=["flat-1"],
        )
        fake = _FakeDB(parent_matches={"flat-1": 1})
        with patch("database.database.PostgresDB", return_value=fake):
            result = apply_auto_heal(report)

        assert result.healed_parent_ids == ["flat-1"]
        # Only one UPDATE statement should have been issued (no
        # phantom child table query).
        assert len(fake.calls) == 1
        assert "order_parent" in fake.calls[0][0]
        assert "order_child" not in fake.calls[0][0]

    @pytest.mark.regression
    def test_heal_update_excludes_already_terminal_rows(self):
        # The healing UPDATE must include a precondition that excludes
        # terminal statuses, so we never silently overwrite a FILLED /
        # CANCELLED row mid-flight.
        report = ReconciliationReport(
            closed_on_exchange_open_locally=["x"],
        )
        fake = _FakeDB(parent_matches={"x": 1})
        with patch("database.database.PostgresDB", return_value=fake):
            apply_auto_heal(report)

        # Every UPDATE issued must guard with NOT IN (terminal statuses).
        assert fake.calls, "expected at least one UPDATE"
        for sql, _ in fake.calls:
            assert "NOT IN" in sql, (
                "auto-heal UPDATE must not overwrite terminal rows; "
                f"missing NOT IN guard in: {sql}"
            )


# ---------------------------------------------------------------------------
# Pre-reveal stealth-order filter (false-positive drift guard)
# ---------------------------------------------------------------------------


class TestPreRevealStatusesExcluded:
    """Hidden stealth orders must NOT be reported as exchange drift.

    Stealth orders are inserted into ``order_parent`` with status
    PENDING (and earlier HIDDEN/TRIGGERED) BEFORE they are placed on
    the exchange. Comparing those rows against ``list_orders(OPEN)``
    would falsely report every hidden order as drift.
    """

    @pytest.mark.regression
    def test_pre_reveal_statuses_excluded_from_local_open_set(self):
        from core.startup_reconciler import _fetch_local_open_client_order_ids

        rows = [
            {"client_order_id": "hidden-1", "status": "HIDDEN"},
            {"client_order_id": "pending-1", "status": "PENDING"},
            {"client_order_id": "triggered-1", "status": "TRIGGERED"},
            {"client_order_id": "open-1", "status": "OPEN"},
            {"client_order_id": "filled-1", "status": "FILLED"},
        ]

        class _PreRevealStatusStubDB:
            def execute_query(self, sql, params=None):
                return rows
            def disconnect(self):
                pass

        with patch("database.database.PostgresDB", return_value=_PreRevealStatusStubDB()):
            ids = _fetch_local_open_client_order_ids()

        # Only the truly placed-on-exchange row should be returned.
        assert ids == {"open-1"}, (
            "Pre-reveal stealth statuses must be filtered out so they "
            "are not falsely reported as exchange drift"
        )

    @pytest.mark.regression
    def test_reconciled_closed_excluded_from_local_open_set(self):
        """Auto-healed rows must NOT re-appear as drift on the next cycle.

        Bug regression: ``RECONCILED_CLOSED`` is the marker auto-heal
        applies to fix drift; if it isn't classified as terminal, every
        subsequent reconciliation cycle re-discovers and re-heals the
        same rows, generating noisy WARN logs and wasted DB writes.
        """
        from core.startup_reconciler import _fetch_local_open_client_order_ids

        rows = [
            {"client_order_id": "healed-1", "status": "RECONCILED_CLOSED"},
            {"client_order_id": "open-1", "status": "OPEN"},
        ]

        class _ReconciledClosedStubDB:
            def execute_query(self, sql, params=None):
                return rows
            def disconnect(self):
                pass

        with patch("database.database.PostgresDB", return_value=_ReconciledClosedStubDB()):
            ids = _fetch_local_open_client_order_ids()

        assert ids == {"open-1"}, (
            "RECONCILED_CLOSED must be treated as terminal; otherwise "
            "auto-healed rows are re-discovered as drift on every cycle"
        )


# ---------------------------------------------------------------------------
# Missed-fills audit: WS-pending suppression
# ---------------------------------------------------------------------------


class TestWsPendingFillSuppression:
    """REST fills covered by WS_DERIVED rows must NOT be flagged as missed.

    Bug regression: WS pipeline writes per-match rows to ``fill_ledger``
    with ``exchange_entry_id IS NULL`` until the FillReconciler stamps
    them. The audit's entry_id-based diff treated those as missed,
    inflating the missed count by every recent live fill.
    """

    @pytest.mark.regression
    def test_ws_covered_orders_suppressed_from_missed(self):
        from core import startup_reconciler as sr

        # Two REST fills for the same exchange order_id, totalling 10.
        rest_fills = [
            {
                "entry_id": "e1", "trade_id": "t1", "order_id": "EXCH-1",
                "product_id": "BIT", "side": "SELL", "size": "6",
                "price": "100", "trade_time": "2026-04-27T00:00:00Z",
            },
            {
                "entry_id": "e2", "trade_id": "t2", "order_id": "EXCH-1",
                "product_id": "BIT", "side": "SELL", "size": "4",
                "price": "100", "trade_time": "2026-04-27T00:00:01Z",
            },
        ]

        # Stub the REST client.
        rest_client = SimpleNamespace(
            list_fills=lambda **kw: {"fills": rest_fills, "has_next": False}
        )

        with patch("core.startup_reconciler._fetch_local_recorded_entry_ids",
                   return_value=set()), \
             patch("core.startup_reconciler._fetch_client_order_ids_for_exchange_order_ids",
                   return_value={"EXCH-1": "COID-1"}), \
             patch("core.startup_reconciler._fetch_ws_pending_qty_by_client_order_id",
                   return_value={"COID-1": 10.0}), \
             patch("configuration.REST_CLIENT", rest_client):
            report = sr.audit_missed_fills()

        assert report is not None
        assert report.rest_fills_examined == 2
        assert report.missed == [], (
            "WS_DERIVED rows pending entry_id stamp must suppress the "
            "matching REST fills from `missed`"
        )
        assert report.already_recorded == 2

    @pytest.mark.regression
    def test_partial_ws_coverage_does_not_suppress(self):
        """If WS recorded LESS than REST shows, the gap must still surface."""
        from core import startup_reconciler as sr

        rest_fills = [
            {
                "entry_id": "e1", "trade_id": "t1", "order_id": "EXCH-2",
                "product_id": "BIT", "side": "BUY", "size": "10",
                "price": "100", "trade_time": "2026-04-27T00:00:00Z",
            },
        ]
        rest_client = SimpleNamespace(
            list_fills=lambda **kw: {"fills": rest_fills, "has_next": False}
        )

        with patch("core.startup_reconciler._fetch_local_recorded_entry_ids",
                   return_value=set()), \
             patch("core.startup_reconciler._fetch_client_order_ids_for_exchange_order_ids",
                   return_value={"EXCH-2": "COID-2"}), \
             patch("core.startup_reconciler._fetch_ws_pending_qty_by_client_order_id",
                   return_value={"COID-2": 4.0}), \
             patch("configuration.REST_CLIENT", rest_client):
            report = sr.audit_missed_fills()

        assert report is not None
        assert len(report.missed) == 1, (
            "Partial WS coverage (4 of 10) must NOT suppress the missed fill"
        )


# ---------------------------------------------------------------------------
# OrderEngine cooperative shutdown
# ---------------------------------------------------------------------------


class TestEngineShutdownPlumbing:
    """Light-touch tests that don't require a full OrderEngine instance.

    We exercise the periodic-loop pattern directly to confirm that an
    ``Event``-driven loop returns promptly when the event is set, which
    is the contract the runtime controller's drain orchestrator relies
    on.
    """

    @pytest.mark.regression
    def test_event_driven_loop_exits_promptly(self):
        # Surrogate for ``while not self._shutdown_event.is_set(): ...
        # self._shutdown_event.wait(timeout=interval)``. With a long
        # interval, setting the event from another thread must wake the
        # waiter immediately rather than blocking out the full sleep.
        evt = threading.Event()
        iterations = []
        long_interval = 5.0  # would dominate test runtime if not woken

        def loop():
            while not evt.is_set():
                iterations.append(1)
                if evt.wait(timeout=long_interval):
                    return

        t = threading.Thread(target=loop, daemon=True)
        t.start()

        # Trigger shutdown almost immediately.
        evt.set()
        t.join(timeout=1.0)
        assert not t.is_alive(), "loop did not exit promptly on event.set()"
        assert iterations, "loop did not run at least once"

    @pytest.mark.regression
    def test_engine_stop_sets_shutdown_event(self):
        # We don't construct a real OrderEngine (it requires DB + REST
        # wiring); instead build a SimpleNamespace bound to the real
        # method to verify the contract.
        from core.order_engine import OrderEngine

        engine = SimpleNamespace(
            _shutdown_event=threading.Event(),
            event_executor=SimpleNamespace(shutdown=lambda **kw: None),
            fee_manager=None,
        )
        # Invoke the unbound method against our stand-in instance.
        OrderEngine.stop(engine)
        assert engine._shutdown_event.is_set()

    @pytest.mark.regression
    def test_engine_stop_is_idempotent(self):
        from core.order_engine import OrderEngine

        engine = SimpleNamespace(
            _shutdown_event=threading.Event(),
            event_executor=SimpleNamespace(shutdown=lambda **kw: None),
            fee_manager=None,
        )
        OrderEngine.stop(engine)
        # Calling twice must not raise even though the executor was
        # already shut down conceptually.
        OrderEngine.stop(engine)
        assert engine._shutdown_event.is_set()
