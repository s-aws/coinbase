"""Contracts for event-stream operations on the execution persistence adapter."""

from datetime import datetime
from unittest.mock import MagicMock, call, patch

from database import order as order_db
from database.execution_persistence import DatabaseOrderPersistenceAdapter


def _event_kwargs() -> dict:
    return {
        "event_id": "11111111-2222-3333-4444-555555555555",
        "event_type": "order_open",
        "source_channel": "ws_user",
        "event_time_exchange": datetime(2026, 11, 28, 12, 0),
        "product_id": "BTC-USDC",
        "client_order_id": "client-order-1",
        "order_id": "exchange-order-1",
        "parent_client_order_id": "parent-order-1",
        "stealth_order_id": "stealth-order-1",
        "event_status_from": None,
        "event_status_to": "OPEN",
        "side": "BUY",
        "price": 50000.0,
        "size": 0.25,
        "cumulative_filled_size": 0.0,
        "leaves_size": 0.25,
        "fee": 0.0,
        "fee_currency": "USDC",
        "trigger_type": None,
        "trigger_payload_json": {"reason": "unit_test"},
        "raw_payload_json": {"client_order_id": "client-order-1"},
        "idempotency_key": "ws:OPEN:client-order-1:OPEN",
    }


def test_adapter_preserves_event_storage_initialization_order() -> None:
    db_client = MagicMock()
    adapter = DatabaseOrderPersistenceAdapter(db_client)
    parent = MagicMock()

    with (
        patch.object(
            order_db,
            "create_order_event_stream_table",
            parent.event_stream,
        ),
        patch.object(
            order_db,
            "create_stealth_order_lifecycle_history_table",
            parent.lifecycle_history,
        ),
        patch.object(
            order_db,
            "create_stealth_order_reveal_history_table",
            parent.reveal_history,
        ),
        patch.object(
            order_db,
            "create_stealth_order_snapshots_table",
            parent.snapshots,
        ),
        patch.object(
            order_db,
            "create_partial_fill_progress_table",
            parent.partial_progress,
        ),
    ):
        adapter.ensure_event_stream_storage()

    assert parent.mock_calls == [
        call.event_stream(db_client=db_client),
        call.lifecycle_history(db_client=db_client),
        call.reveal_history(db_client=db_client),
        call.snapshots(db_client=db_client),
        call.partial_progress(db_client=db_client),
    ]


def test_adapter_delegates_order_event_to_explicit_database_client() -> None:
    db_client = MagicMock()
    adapter = DatabaseOrderPersistenceAdapter(db_client)

    with patch.object(order_db, "insert_order_event", return_value=17) as insert:
        inserted_id = adapter.append_order_event(**_event_kwargs())

    assert inserted_id == 17
    insert.assert_called_once_with(**_event_kwargs(), db_client=db_client)


def test_adapter_keeps_lifecycle_audit_operations_separate() -> None:
    db_client = MagicMock()
    adapter = DatabaseOrderPersistenceAdapter(db_client)
    context = {"status": "TRIGGERED"}

    with (
        patch.object(
            order_db,
            "insert_stealth_order_lifecycle_event",
            return_value=21,
        ) as history,
        patch.object(
            order_db,
            "insert_stealth_order_snapshot",
            return_value=22,
        ) as snapshot,
        patch.object(
            order_db,
            "update_stealth_order_lifecycle_event",
            return_value=True,
        ) as marker,
    ):
        assert adapter.append_stealth_lifecycle_event(
            stealth_order_id="stealth-order-1",
            lifecycle_event="CONDITION_MET",
            context=context,
        ) == 21
        assert adapter.append_stealth_snapshot(
            stealth_order_id="stealth-order-1",
            lifecycle_event="CONDITION_MET",
            context=context,
        ) == 22
        assert adapter.update_stealth_lifecycle_marker(
            stealth_order_id="stealth-order-1",
            lifecycle_event="CONDITION_MET",
            failure_reason=None,
        ) is True

    history.assert_called_once_with(
        stealth_order_id="stealth-order-1",
        lifecycle_event="CONDITION_MET",
        context=context,
        db_client=db_client,
    )
    snapshot.assert_called_once_with(
        stealth_order_id="stealth-order-1",
        lifecycle_event="CONDITION_MET",
        context=context,
        db_client=db_client,
    )
    marker.assert_called_once_with(
        stealth_order_id="stealth-order-1",
        lifecycle_event="CONDITION_MET",
        failure_reason=None,
        db_client=db_client,
    )


def test_canonical_event_insert_uses_explicit_database_client() -> None:
    db_client = MagicMock()
    db_client.execute_query.return_value = [{"id": 17}]

    inserted_id = order_db.insert_order_event(
        **_event_kwargs(),
        db_client=db_client,
    )

    assert inserted_id == 17
    db_client.execute_query.assert_called_once()
