from __future__ import annotations

from unittest.mock import Mock

import pytest

from core.exceptions import StealthOrderPersistenceError
from core.stealth_order_manager import StealthOrderManager


def _order_data() -> dict[str, object]:
    return {
        "stealth_order_id": "990e8400-e29b-41d4-a716-446655440000",
        "product_id": "BTC-USDC",
        "side": "SELL",
    }


def test_strict_persistence_rejects_missing_atomic_result_before_publish():
    manager = StealthOrderManager(db_client=Mock())
    order = _order_data()

    with pytest.raises(StealthOrderPersistenceError, match="atomic"):
        manager._persist_new_stealth_order_strict(
            order,
            persist_rows=lambda: None,
        )

    assert order["stealth_order_id"] not in manager.in_memory_orders


def test_strict_persistence_does_not_publish_when_atomic_write_fails():
    manager = StealthOrderManager(db_client=Mock())
    order = _order_data()

    def fail_atomic_write():
        raise StealthOrderPersistenceError("synthetic atomic insert failure")

    with pytest.raises(StealthOrderPersistenceError, match="atomic insert"):
        manager._persist_new_stealth_order_strict(
            order,
            persist_rows=fail_atomic_write,
        )

    assert order["stealth_order_id"] not in manager.in_memory_orders


def test_strict_persistence_publishes_only_after_both_rows_succeed():
    manager = StealthOrderManager(db_client=Mock())
    order = _order_data()
    events: list[str] = []

    def persist_rows():
        assert order["stealth_order_id"] not in manager.in_memory_orders
        events.append("atomic")
        return (7, True)

    manager._persist_new_stealth_order_strict(
        order,
        persist_rows=persist_rows,
    )

    assert events == ["atomic"]
    assert manager.in_memory_orders[order["stealth_order_id"]] is order


def test_strict_persistence_rejects_unhydrated_existing_atomic_child():
    manager = StealthOrderManager(db_client=Mock())
    order = _order_data()

    with pytest.raises(StealthOrderPersistenceError, match="not hydrated"):
        manager._persist_new_stealth_order_strict(
            order,
            persist_rows=lambda: (7, False),
        )

    assert order["stealth_order_id"] not in manager.in_memory_orders
