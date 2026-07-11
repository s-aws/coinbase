from __future__ import annotations

from contextlib import contextmanager
import uuid

import database.order as order_db
import pytest


def _order_data() -> dict[str, object]:
    return {
        "stealth_order_id": "990e8400-e29b-41d4-a716-446655440000",
        "product_id": "BTC-USDC",
        "side": "SELL",
        "total_size": 0.01,
        "remaining_size": 0.01,
        "limit_price": 101.0,
        "status": "HIDDEN",
        "reveal_condition_type": "price",
        "reveal_condition_json": {"type": "price", "direction": "above"},
        "sizing_strategy_json": {"type": "fixed"},
        "reason": "follow_up_replacement",
        "notes": "filled follow-up",
        "parent_order_id": "880e8400-e29b-41d4-a716-446655440000",
        "anchor_repricing_policy_json": {},
        "anchor_repricing_state_json": {},
        "cancel_reentry_policy_json": {},
        "cancel_reentry_state_json": {},
        "post_fill_retreat_policy_json": {"enabled": False},
    }


class _AtomicCursor:
    def __init__(self, *, existing: bool = False) -> None:
        self.existing = existing
        self.executions: list[tuple[str, tuple[object, ...]]] = []
        self.description = []
        self._row = None

    def execute(self, query, params=()):
        normalized = " ".join(str(query).split())
        self.executions.append((normalized, tuple(params or ())))
        if normalized.startswith("SELECT id, product_id"):
            self.description = [
                ("id",),
                ("product_id",),
                ("side",),
                ("size",),
                ("price",),
                ("parent_order_id",),
            ]
            self._row = (
                7,
                "BTC-USDC",
                "SELL",
                0.01,
                101.0,
                "880e8400-e29b-41d4-a716-446655440000",
            ) if self.existing else None
        elif normalized.startswith("SELECT product_id"):
            self.description = [
                ("product_id",),
                ("side",),
                ("total_size",),
                ("parent_order_id",),
            ]
            self._row = (
                "BTC-USDC",
                "SELL",
                0.01,
                "880e8400-e29b-41d4-a716-446655440000",
            ) if self.existing else None
        elif normalized.startswith("INSERT INTO order_parent"):
            self.description = [("id",)]
            self._row = (7,)
        else:
            self.description = []
            self._row = None

    def fetchone(self):
        return self._row


class _AtomicDb:
    def __init__(self, *, existing: bool = False) -> None:
        self.cursor = _AtomicCursor(existing=existing)
        self.context_entries = 0

    @contextmanager
    def get_cursor(self):
        self.context_entries += 1
        yield self.cursor


def test_filled_follow_up_rows_are_written_in_one_atomic_cursor(monkeypatch):
    db = _AtomicDb()
    monkeypatch.setattr(order_db, "DB_CLIENT", db)

    result = order_db.persist_filled_follow_up_atomic(
        order=_order_data(),
        target_movement=0.001,
        target_movement_type="P",
    )

    assert result == (7, True)
    assert db.context_entries == 1
    sql = [query for query, _params in db.cursor.executions]
    assert sum(query.startswith("INSERT INTO order_parent") for query in sql) == 1
    assert sum(query.startswith("INSERT INTO stealth_orders") for query in sql) == 1


def test_filled_follow_up_atomic_write_is_idempotent_for_existing_identity(
    monkeypatch,
):
    db = _AtomicDb(existing=True)
    monkeypatch.setattr(order_db, "DB_CLIENT", db)

    result = order_db.persist_filled_follow_up_atomic(
        order=_order_data(),
        target_movement=0.001,
        target_movement_type="P",
    )

    assert result == (7, False)
    assert not any(
        query.startswith("INSERT INTO")
        for query, _params in db.cursor.executions
    )


@pytest.mark.integration
@pytest.mark.serial
def test_filled_follow_up_atomic_write_round_trips_both_test_db_rows():
    order_db.create_order_parent_table()
    order_db.create_stealth_orders_table()
    root_id = str(uuid.uuid4())
    child_id = str(uuid.uuid4())
    order_db.insert_order_parent(
        client_order_id=root_id,
        product_id="BTC-USDC",
        side="BUY",
        size=0.01,
        price=100.0,
        target_movement=0.001,
        target_movement_type="P",
        max_order_replacement=11,
        status="FILLED",
    )
    order = _order_data()
    order["stealth_order_id"] = child_id
    order["parent_order_id"] = root_id

    try:
        first = order_db.persist_filled_follow_up_atomic(
            order=order,
            target_movement=0.001,
            target_movement_type="P",
        )
        second = order_db.persist_filled_follow_up_atomic(
            order=order,
            target_movement=0.001,
            target_movement_type="P",
        )
        parent_rows = order_db.DB_CLIENT.execute_query(
            "SELECT client_order_id FROM order_parent WHERE client_order_id = %s",
            (child_id,),
        )
        stealth_rows = order_db.DB_CLIENT.execute_query(
            "SELECT stealth_order_id FROM stealth_orders WHERE stealth_order_id = %s",
            (child_id,),
        )

        assert first[1] is True
        assert second == (first[0], False)
        assert parent_rows == [{"client_order_id": child_id}]
        assert str(stealth_rows[0]["stealth_order_id"]) == child_id
    finally:
        with order_db.DB_CLIENT.get_cursor() as cursor:
            cursor.execute(
                "DELETE FROM stealth_orders WHERE stealth_order_id = %s",
                (child_id,),
            )
            cursor.execute(
                "DELETE FROM order_parent WHERE client_order_id IN (%s, %s)",
                (child_id, root_id),
            )
