"""Concrete persistence adapters composed into execution consumers.

The adapter deliberately delegates to the canonical helpers in
``database.order``.  It owns no SQL and adds no transaction boundary: every
operation retains the helper's existing cursor-lock and commit/rollback scope.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from database import order as order_db
from database.database import PostgresDB


class DatabaseOrderPersistenceAdapter:
    """Structural adapter for narrow execution-owned persistence protocols."""

    def __init__(self, db_client: PostgresDB) -> None:
        if db_client is None:
            raise ValueError(
                "DatabaseOrderPersistenceAdapter requires an explicit db_client"
            )
        self._db_client = db_client

    def ensure_fill_ledger(self) -> None:
        order_db.create_fill_ledger_table(db_client=self._db_client)

    def append_fill_record(
        self,
        *,
        derived_trade_key: str,
        instrument: str,
        side: str,
        quantity: float,
        price: float,
        timestamp: Any,
        fees: float,
        commission_percentage: float,
        client_order_id: Optional[str],
        exchange_trade_id: Optional[str],
        exchange_entry_id: Optional[str],
        reconciliation_status: str,
    ) -> Optional[int]:
        return order_db.insert_fill_record(
            derived_trade_key=derived_trade_key,
            instrument=instrument,
            side=side,
            quantity=quantity,
            price=price,
            timestamp=timestamp,
            fees=fees,
            commission_percentage=commission_percentage,
            client_order_id=client_order_id,
            exchange_trade_id=exchange_trade_id,
            exchange_entry_id=exchange_entry_id,
            reconciliation_status=reconciliation_status,
            db_client=self._db_client,
            raise_on_error=True,
        )

    def list_fills_by_instrument(
        self,
        instrument: str,
        side: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return order_db.get_fills_by_instrument(
            instrument,
            side=side,
            db_client=self._db_client,
        )

    def find_fill_by_derived_trade_key(
        self,
        derived_trade_key: str,
    ) -> Optional[Dict[str, Any]]:
        return order_db.get_fill_by_derived_trade_key(
            derived_trade_key,
            db_client=self._db_client,
        )

    def list_fills_by_order(
        self,
        client_order_id: str,
    ) -> List[Dict[str, Any]]:
        return order_db.get_fills_by_order(
            client_order_id,
            db_client=self._db_client,
        )

    def list_fills_since(
        self,
        instrument: str,
        since: Any,
    ) -> List[Dict[str, Any]]:
        return order_db.get_fills_since(
            instrument,
            since,
            db_client=self._db_client,
        )
