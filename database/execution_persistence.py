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

    def ensure_event_stream_storage(self) -> None:
        """Preserve the event publisher's established startup DDL sequence."""

        order_db.create_order_event_stream_table(db_client=self._db_client)
        order_db.create_stealth_order_lifecycle_history_table(
            db_client=self._db_client
        )
        order_db.create_stealth_order_reveal_history_table(
            db_client=self._db_client
        )
        order_db.create_stealth_order_snapshots_table(db_client=self._db_client)
        order_db.create_partial_fill_progress_table(db_client=self._db_client)

    def append_order_event(
        self,
        *,
        event_id: str,
        event_type: str,
        source_channel: str,
        event_time_exchange: Any,
        product_id: Optional[str],
        client_order_id: Optional[str],
        order_id: Optional[str],
        parent_client_order_id: Optional[str],
        stealth_order_id: Optional[str],
        event_status_from: Optional[str],
        event_status_to: Optional[str],
        side: Optional[str],
        price: Optional[float],
        size: Optional[float],
        cumulative_filled_size: Optional[float],
        leaves_size: Optional[float],
        fee: Optional[float],
        fee_currency: Optional[str],
        trigger_type: Optional[str],
        trigger_payload_json: Optional[Dict[str, Any]],
        raw_payload_json: Optional[Dict[str, Any]],
        idempotency_key: Optional[str],
    ) -> Optional[int]:
        return order_db.insert_order_event(
            event_id=event_id,
            event_type=event_type,
            source_channel=source_channel,
            event_time_exchange=event_time_exchange,
            product_id=product_id,
            client_order_id=client_order_id,
            order_id=order_id,
            parent_client_order_id=parent_client_order_id,
            stealth_order_id=stealth_order_id,
            event_status_from=event_status_from,
            event_status_to=event_status_to,
            side=side,
            price=price,
            size=size,
            cumulative_filled_size=cumulative_filled_size,
            leaves_size=leaves_size,
            fee=fee,
            fee_currency=fee_currency,
            trigger_type=trigger_type,
            trigger_payload_json=trigger_payload_json,
            raw_payload_json=raw_payload_json,
            idempotency_key=idempotency_key,
            db_client=self._db_client,
        )

    def append_stealth_lifecycle_event(
        self,
        *,
        stealth_order_id: str,
        lifecycle_event: str,
        context: Dict[str, Any],
    ) -> Optional[int]:
        return order_db.insert_stealth_order_lifecycle_event(
            stealth_order_id=stealth_order_id,
            lifecycle_event=lifecycle_event,
            context=context,
            db_client=self._db_client,
        )

    def append_stealth_snapshot(
        self,
        *,
        stealth_order_id: str,
        lifecycle_event: str,
        context: Dict[str, Any],
    ) -> Optional[int]:
        return order_db.insert_stealth_order_snapshot(
            stealth_order_id=stealth_order_id,
            lifecycle_event=lifecycle_event,
            context=context,
            db_client=self._db_client,
        )

    def update_stealth_lifecycle_marker(
        self,
        *,
        stealth_order_id: str,
        lifecycle_event: str,
        failure_reason: Optional[str],
    ) -> bool:
        return order_db.update_stealth_order_lifecycle_event(
            stealth_order_id=stealth_order_id,
            lifecycle_event=lifecycle_event,
            failure_reason=failure_reason,
            db_client=self._db_client,
        )

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
