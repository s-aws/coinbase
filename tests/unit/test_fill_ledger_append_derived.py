"""Unit tests for FillLedgerRepository.append_derived_fill.

Covers Step 3 of the WS-derived-fill design plan: the canonical entry point
that takes an OrderSnapshotDelta from OrderProgressTracker and writes one
fill_ledger row.

Uses a mock db_client so no real database is required.
"""

from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import MagicMock

from business.fill_ledger import FillLedgerRepository
from business.lot_builder import PositionLotBuilder
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
        self.persistence = MagicMock()
        self.persistence.append_fill_record.return_value = 1
        self.persistence.list_fills_by_instrument.return_value = []
        self.repo = FillLedgerRepository(self.persistence)

    def test_append_derived_fill_writes_expected_columns(self):
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
        self.persistence.append_fill_record.assert_called_once_with(
            derived_trade_key=delta.derived_trade_key,
            exchange_trade_id=None,
            exchange_entry_id=None,
            instrument="ETH-USDC",
            side="SELL",
            quantity=2.5,
            price=3200.0,
            timestamp=delta.observed_at,
            fees=0.07,
            commission_percentage=0.0,
            client_order_id="parent-1",
            reconciliation_status="WS_DERIVED",
        )

    def test_append_derived_fill_returns_true_on_idempotent_duplicate(self):
        # ON CONFLICT DO NOTHING -> no inserted id; treated as success.
        self.persistence.append_fill_record.return_value = None
        delta = _make_delta()

        self.assertTrue(self.repo.append_derived_fill(delta))

    def test_append_derived_fill_skips_when_no_size_delta(self):
        delta = _make_delta(size_delta=0.0)

        ok = self.repo.append_derived_fill(delta)

        self.assertTrue(ok)
        self.persistence.append_fill_record.assert_not_called()

    def test_append_derived_fill_handles_none(self):
        ok = self.repo.append_derived_fill(None)
        self.assertFalse(ok)
        self.persistence.append_fill_record.assert_not_called()

    def test_append_derived_fill_returns_false_on_db_error(self):
        self.persistence.append_fill_record.side_effect = RuntimeError("boom")
        delta = _make_delta()

        self.assertFalse(self.repo.append_derived_fill(delta))

    def test_get_fills_by_instrument_restores_lot_builder_contract(self):
        row = {
            "derived_trade_key": "11111111-2222-3333-4444-555555555555",
            "instrument": "BTC-USDC",
            "side": "BUY",
            "quantity": 0.25,
            "price": 50000.0,
            "timestamp": datetime(2026, 4, 26, 12, 0, 0),
            "reconciliation_status": "WS_DERIVED",
        }
        self.persistence.list_fills_by_instrument.return_value = [row]

        fills = self.repo.get_fills_by_instrument("BTC-USDC")

        self.assertEqual(len(fills), 1)
        self.assertEqual(fills[0].derived_trade_key, row["derived_trade_key"])
        self.persistence.list_fills_by_instrument.assert_called_once_with(
            "BTC-USDC"
        )

    def test_lot_builder_uses_restored_instrument_query(self):
        self.persistence.list_fills_by_instrument.return_value = [
            {
                "derived_trade_key": "11111111-2222-3333-4444-555555555555",
                "instrument": "BTC-USDC",
                "side": "BUY",
                "quantity": 0.25,
                "price": 50000.0,
                "timestamp": datetime(2026, 4, 26, 12, 0, 0),
                "reconciliation_status": "WS_DERIVED",
            }
        ]

        position = PositionLotBuilder(self.repo).build_position_lots("BTC-USDC")

        self.assertEqual(len(position.lots), 1)
        self.assertEqual(position.total_quantity, 0.25)

    def test_get_fills_by_product_normalizes_optional_side(self):
        self.repo.get_fills_by_product("BTC-USDC", side="buy")

        self.persistence.list_fills_by_instrument.assert_called_once_with(
            "BTC-USDC",
            side="BUY",
        )


if __name__ == "__main__":
    unittest.main()
