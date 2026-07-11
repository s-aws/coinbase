"""Focused persistence tests for authoritative parent exchange evidence."""

from database import order as order_db


class _RecordingDb:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute_update(self, query: str, params: tuple[object, ...]) -> int:
        self.calls.append((query, params))
        return 1


def test_parent_status_update_atomically_binds_exchange_order_id(
    monkeypatch,
) -> None:
    database = _RecordingDb()
    monkeypatch.setattr(order_db, "DB_CLIENT", database)

    updated = order_db.update_order_parent_status(
        "client-root-1",
        "OPEN",
        exchange_order_id="exchange-root-1",
    )

    assert updated == 1
    query, params = database.calls[-1]
    assert "SET status = %s, exchange_order_id = %s" in query
    assert "exchange_order_id IS NULL OR exchange_order_id = %s" in query
    assert params == (
        "OPEN",
        "exchange-root-1",
        "client-root-1",
        "exchange-root-1",
    )


def test_parent_status_only_update_preserves_existing_exchange_evidence(
    monkeypatch,
) -> None:
    database = _RecordingDb()
    monkeypatch.setattr(order_db, "DB_CLIENT", database)

    updated = order_db.update_order_parent_status("client-root-1", "FILLED")

    assert updated == 1
    query, params = database.calls[-1]
    assert "exchange_order_id" not in query
    assert params == ("FILLED", "client-root-1")
