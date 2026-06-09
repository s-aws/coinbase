"""Unit tests for FillLedgerRepository.append_derived_fill.

Covers Step 3 of the WS-derived-fill design plan: the canonical entry point
that takes an OrderSnapshotDelta from OrderProgressTracker and writes one
fill_ledger row.

Uses a mock db_client so no real database is required.
"""

from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from business.fill_ledger import FillLedger, FillLedgerRepository
from business.order_progress import OrderSnapshotDelta


def _make_delta(
    *,
    coid: str = "client-001",
    product_id: str = "BTC-USDC",
    side: str = "BUY",
    size_delta: float = 1.0,
    fee_delta: float = 0.005,
    derived_price: float = 50000.0,
    cumulative_quantity: float = 1.0,
    snapshot_seq: int = 1,
    status: str = "OPEN",
) -> OrderSnapshotDelta:
    return OrderSnapshotDelta(
        client_order_id=coid,
        product_id=product_id,
        side=side,
        cumulative_quantity=cumulative_quantity,
        filled_value=cumulative_quantity * derived_price,
        total_fees=fee_delta,
        number_of_fills=1,
        leaves_quantity=0.0,
        completion_percentage=100.0,
        outstanding_hold_amount=0.0,
        status=status,
        size_delta=size_delta,
        value_delta=size_delta * derived_price,
        fee_delta=fee_delta,
        derived_price=derived_price,
        derived_trade_key="11111111-2222-3333-4444-555555555555",
        snapshot_seq=snapshot_seq,
        observed_at=datetime(2026, 4, 26, 12, 0, 0),
    )


class TestAppendDerivedFill(unittest.TestCase):

    def setUp(self):
        # Bypass _ensure_table_exists which would touch the real DB.
        with patch.object(
            FillLedgerRepository, "_ensure_table_exists", lambda self: None
        ):
            self.db = MagicMock()
            self.repo = FillLedgerRepository(self.db)

    def test_append_derived_fill_writes_expected_columns(self):
        self.db.execute_update.return_value = 1
        delta = _make_delta(
            coid="parent-1",
            product_id="ETH-USDC",
            side="SELL",
            size_delta=2.5,
            fee_delta=0.07,
            derived_price=3200.0,
        )

        ok = self.repo.append_derived_fill(delta)

        self.assertTrue(ok)
        self.db.execute_update.assert_called_once()
        _, params = self.db.execute_update.call_args[0]
        # Param order matches append_fill INSERT signature.
        (
            derived_trade_key,
            exchange_trade_id,
            exchange_entry_id,
            instrument,
            side,
            quantity,
            price,
            _ts,
            fees,
            commission_percentage,
            client_order_id,
            reconciliation_status,
        ) = params
        self.assertEqual(derived_trade_key, delta.derived_trade_key)
        self.assertIsNone(exchange_trade_id)
        self.assertIsNone(exchange_entry_id)
        self.assertEqual(instrument, "ETH-USDC")
        self.assertEqual(side, "SELL")
        self.assertEqual(quantity, 2.5)
        self.assertEqual(price, 3200.0)
        self.assertEqual(fees, 0.07)
        self.assertEqual(commission_percentage, 0.0)
        self.assertEqual(client_order_id, "parent-1")
        self.assertEqual(reconciliation_status, "WS_DERIVED")

    def test_append_derived_fill_returns_true_on_idempotent_duplicate(self):
        # ON CONFLICT DO NOTHING -> 0 rows affected; treated as success.
        self.db.execute_update.return_value = 0
        delta = _make_delta()

        self.assertTrue(self.repo.append_derived_fill(delta))

    def test_append_derived_fill_skips_when_no_size_delta(self):
        delta = _make_delta(size_delta=0.0)

        ok = self.repo.append_derived_fill(delta)

        self.assertTrue(ok)
        self.db.execute_update.assert_not_called()

    def test_append_derived_fill_handles_none(self):
        ok = self.repo.append_derived_fill(None)
        self.assertFalse(ok)
        self.db.execute_update.assert_not_called()

    def test_append_derived_fill_returns_false_on_db_error(self):
        self.db.execute_update.side_effect = RuntimeError("boom")
        delta = _make_delta()

        self.assertFalse(self.repo.append_derived_fill(delta))

    def test_from_dict_uses_instrument_as_product_id_when_schema_has_no_column(self):
        fill = FillLedger.from_dict({
            "derived_trade_key": "11111111-2222-3333-4444-555555555555",
            "instrument": "ACX-USDC",
            "side": "BUY",
            "quantity": "2",
            "price": "0.05",
            "timestamp": datetime(2026, 6, 9, 12, 0, 0),
            "fees": "0.01",
        })

        self.assertEqual(fill.instrument, "ACX-USDC")
        self.assertEqual(fill.product_id, "ACX-USDC")


if __name__ == "__main__":
    unittest.main()
