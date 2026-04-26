"""Unit tests for FillReconciler — Step 5 of the WS-derived-fill design plan."""

from __future__ import annotations

import unittest
from typing import Any, Dict, List
from unittest.mock import MagicMock

from business.fill_reconciler import (
    FillReconciler,
    ReconcileMatch,
    ReconcileReport,
)


def _ws_row(
    *,
    row_id: int,
    derived_trade_key: str,
    side: str = "BUY",
    quantity: float = 1.0,
    price: float = 100.0,
) -> Dict[str, Any]:
    return {
        "id": row_id,
        "derived_trade_key": derived_trade_key,
        "side": side,
        "quantity": quantity,
        "price": price,
        "fees": 0.0,
        "timestamp": None,
    }


def _rest_fill(
    *,
    trade_id: str,
    entry_id: str,
    side: str = "BUY",
    size: float = 1.0,
    price: float = 100.0,
) -> Dict[str, Any]:
    return {
        "trade_id": trade_id,
        "entry_id": entry_id,
        "side": side,
        "size": size,
        "price": price,
    }


class _FakeDB:
    def __init__(self, ws_rows: List[Dict[str, Any]]):
        self._ws_rows = ws_rows
        self.updates: List[tuple] = []

    def execute_query(self, query: str, params: tuple):
        # All queries in this module are the WS-row SELECT.
        return list(self._ws_rows)

    def execute_update(self, query: str, params: tuple):
        self.updates.append((query, params))
        return 1


class TestFillReconciler(unittest.TestCase):

    def _build(self, ws_rows, rest_fills):
        db = _FakeDB(ws_rows)
        fetcher = MagicMock(return_value=rest_fills)
        return FillReconciler(db, fetcher), db, fetcher

    # ------------------------------------------------------------------
    # Happy paths
    # ------------------------------------------------------------------

    def test_clean_one_to_one_match(self):
        ws = [
            _ws_row(row_id=1, derived_trade_key="dtk-1", quantity=1.0, price=78000.0),
            _ws_row(row_id=2, derived_trade_key="dtk-2", quantity=4.0, price=78000.0),
        ]
        rest = [
            _rest_fill(trade_id="t-1", entry_id="e-1", size=1.0, price=78000.0),
            _rest_fill(trade_id="t-2", entry_id="e-2", size=4.0, price=78000.0),
        ]
        recon, db, fetcher = self._build(ws, rest)

        report = recon.reconcile_order("coid-1", "exch-1")

        fetcher.assert_called_once_with("exch-1")
        self.assertTrue(report.is_clean)
        self.assertEqual(len(report.matched), 2)
        self.assertEqual(report.ws_unmatched, [])
        self.assertEqual(report.rest_unmatched, [])
        # Two RECONCILED updates expected (no MISMATCH writes).
        self.assertEqual(len(db.updates), 2)

        # First match must pair the matching keys.
        m1 = report.matched[0]
        self.assertEqual(m1.derived_trade_key, "dtk-1")
        self.assertEqual(m1.exchange_trade_id, "t-1")
        self.assertEqual(m1.exchange_entry_id, "e-1")

    def test_size_tolerance_within_threshold(self):
        ws = [_ws_row(row_id=1, derived_trade_key="dtk-1", quantity=1.0)]
        # REST size differs by 1e-9 (well below default 1e-8 tolerance).
        rest = [_rest_fill(trade_id="t-1", entry_id="e-1", size=1.0 + 1e-9)]
        recon, _, _ = self._build(ws, rest)

        report = recon.reconcile_order("coid-1", "exch-1")
        self.assertEqual(len(report.matched), 1)

    # ------------------------------------------------------------------
    # Mismatch paths
    # ------------------------------------------------------------------

    def test_ws_row_with_no_rest_counterpart_is_flagged_mismatch(self):
        ws = [
            _ws_row(row_id=1, derived_trade_key="dtk-1", quantity=1.0),
            _ws_row(row_id=2, derived_trade_key="dtk-orphan", quantity=99.0),
        ]
        rest = [_rest_fill(trade_id="t-1", entry_id="e-1", size=1.0)]
        recon, db, _ = self._build(ws, rest)

        report = recon.reconcile_order("coid-1", "exch-1")

        self.assertFalse(report.is_clean)
        self.assertEqual(report.ws_unmatched, ["dtk-orphan"])
        self.assertEqual(len(report.matched), 1)
        # 1 RECONCILED + 1 MISMATCH update.
        self.assertEqual(len(db.updates), 2)
        update_queries = [u[0] for u in db.updates]
        self.assertTrue(any("MISMATCH" in q for q in update_queries))

    def test_rest_fill_with_no_ws_counterpart_is_reported_only(self):
        ws = [_ws_row(row_id=1, derived_trade_key="dtk-1", quantity=1.0)]
        rest = [
            _rest_fill(trade_id="t-1", entry_id="e-1", size=1.0),
            _rest_fill(trade_id="t-orphan", entry_id="e-orphan", size=42.0),
        ]
        recon, db, _ = self._build(ws, rest)

        report = recon.reconcile_order("coid-1", "exch-1")

        self.assertEqual(len(report.rest_unmatched), 1)
        self.assertEqual(report.rest_unmatched[0]["trade_id"], "t-orphan")
        # Only the matched row triggers an UPDATE; orphan REST fills are
        # never inserted (operator review).
        self.assertEqual(len(db.updates), 1)

    def test_side_mismatch_blocks_pairing(self):
        ws = [_ws_row(row_id=1, derived_trade_key="dtk-1", side="BUY", quantity=1.0)]
        rest = [_rest_fill(trade_id="t-1", entry_id="e-1", side="SELL", size=1.0)]
        recon, _, _ = self._build(ws, rest)

        report = recon.reconcile_order("coid-1", "exch-1")
        self.assertEqual(report.matched, [])
        self.assertEqual(report.ws_unmatched, ["dtk-1"])
        self.assertEqual(len(report.rest_unmatched), 1)

    def test_price_outside_tolerance_blocks_pairing(self):
        ws = [_ws_row(row_id=1, derived_trade_key="dtk-1", quantity=1.0, price=100.0)]
        # 1% drift, far beyond the default 0.01% tolerance.
        rest = [_rest_fill(trade_id="t-1", entry_id="e-1", size=1.0, price=101.0)]
        recon, _, _ = self._build(ws, rest)

        report = recon.reconcile_order("coid-1", "exch-1")
        self.assertEqual(report.matched, [])
        self.assertEqual(report.ws_unmatched, ["dtk-1"])

    # ------------------------------------------------------------------
    # Failure handling
    # ------------------------------------------------------------------

    def test_fetcher_failure_yields_empty_rest_side(self):
        ws = [_ws_row(row_id=1, derived_trade_key="dtk-1", quantity=1.0)]
        db = _FakeDB(ws)
        fetcher = MagicMock(side_effect=RuntimeError("network down"))
        recon = FillReconciler(db, fetcher)

        report = recon.reconcile_order("coid-1", "exch-1")

        # Fetcher error is logged, not raised; WS row gets MISMATCH-flagged.
        self.assertEqual(report.matched, [])
        self.assertEqual(report.ws_unmatched, ["dtk-1"])

    def test_no_ws_rows_no_db_updates(self):
        recon, db, _ = self._build([], [_rest_fill(trade_id="t", entry_id="e")])
        report = recon.reconcile_order("coid-1", "exch-1")
        self.assertEqual(report.matched, [])
        self.assertEqual(db.updates, [])
        self.assertEqual(len(report.rest_unmatched), 1)


if __name__ == "__main__":
    unittest.main()
