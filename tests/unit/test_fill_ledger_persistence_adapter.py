"""Contracts for the concrete fill-ledger persistence adapter."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from database import order as order_db
from database.execution_persistence import DatabaseOrderPersistenceAdapter


def _insert_kwargs() -> dict:
    return {
        "derived_trade_key": "11111111-2222-3333-4444-555555555555",
        "instrument": "BTC-USDC",
        "side": "BUY",
        "quantity": 0.25,
        "price": 50000.0,
        "timestamp": datetime(2026, 11, 27, 12, 0, 0),
        "fees": 1.25,
        "commission_percentage": 0.001,
        "client_order_id": "client-order-1",
        "exchange_trade_id": None,
        "exchange_entry_id": None,
        "reconciliation_status": "RECONCILED",
    }


def test_adapter_requests_strict_canonical_insert() -> None:
    db_client = MagicMock()
    adapter = DatabaseOrderPersistenceAdapter(db_client)

    with patch.object(order_db, "insert_fill_record", return_value=17) as insert:
        inserted_id = adapter.append_fill_record(**_insert_kwargs())

    assert inserted_id == 17
    insert.assert_called_once_with(
        **_insert_kwargs(),
        db_client=db_client,
        raise_on_error=True,
    )


def test_canonical_insert_persists_reconciliation_status() -> None:
    db_client = MagicMock()
    db_client.execute_query.return_value = [{"id": 17}]

    inserted_id = order_db.insert_fill_record(
        **_insert_kwargs(),
        db_client=db_client,
        raise_on_error=True,
    )

    assert inserted_id == 17
    _query, params = db_client.execute_query.call_args.args
    assert params[-1] == "RECONCILED"


def test_canonical_insert_distinguishes_duplicate_from_strict_error() -> None:
    duplicate_client = MagicMock()
    duplicate_client.execute_query.return_value = []
    assert order_db.insert_fill_record(
        **_insert_kwargs(),
        db_client=duplicate_client,
        raise_on_error=True,
    ) is None

    failing_client = MagicMock()
    failing_client.execute_query.side_effect = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError, match="database unavailable"):
        order_db.insert_fill_record(
            **_insert_kwargs(),
            db_client=failing_client,
            raise_on_error=True,
        )


def test_canonical_instrument_query_applies_normalized_side_filter() -> None:
    db_client = MagicMock()
    db_client.execute_query.return_value = []

    rows = order_db.get_fills_by_instrument(
        "BTC-USDC",
        side="buy",
        db_client=db_client,
    )

    assert rows == []
    query, params = db_client.execute_query.call_args.args
    assert "side = %s" in query
    assert params == ("BTC-USDC", "BUY")
