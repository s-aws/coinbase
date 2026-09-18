"""Destructive cleanup keeps durable cancellation and parent recovery evidence."""

from contextlib import nullcontext
from unittest.mock import Mock

import pytest

import database.order as order_db
from database.order_dashboard_helpers import delete_parent_order


pytestmark = pytest.mark.regression
SID = "203e541b-4801-4e21-b947-4d1ba6e3a465"


@pytest.mark.parametrize("unresolved", [0, 1])
def test_clear_checks_durable_exposure_under_same_transaction_lock(monkeypatch, unresolved):
    cursor = Mock(rowcount=3)
    cursor.fetchone.return_value = (unresolved,)
    db = Mock()
    db.get_cursor.return_value = nullcontext(cursor)
    monkeypatch.setattr(order_db, "DB_CLIENT", db)

    result = order_db.clear_all_stealth_orders()

    statements = [call.args[0] for call in cursor.execute.call_args_list]
    assert statements[0] == "LOCK TABLE stealth_orders IN SHARE ROW EXCLUSIVE MODE"
    assert order_db.STEALTH_UNRESOLVED_SQL in statements[1]
    assert cursor.execute.call_args_list[1].args[1] == order_db.STEALTH_TERMINAL_STATUSES
    assert result["success"] is (not unresolved)
    assert ("DELETE FROM stealth_orders" in statements) is (not unresolved)
    db.get_cursor.assert_called_once_with()


@pytest.mark.parametrize("rows_deleted", [0, 1])
def test_parent_delete_uses_same_durable_guard_for_all_identity_links(monkeypatch, rows_deleted):
    cursor = Mock(rowcount=rows_deleted)
    db = Mock()
    db.get_cursor.return_value = nullcontext(cursor)
    monkeypatch.setattr("database.database.PostgresDB", Mock(return_value=db))

    assert delete_parent_order(SID) is bool(rows_deleted)

    calls = cursor.execute.call_args_list
    assert calls[0].args[0] == "LOCK TABLE stealth_orders IN SHARE MODE"
    sql, params = calls[1].args
    assert order_db.STEALTH_UNRESOLVED_SQL in sql
    assert params == (SID, *order_db.STEALTH_TERMINAL_STATUSES)
    for reference in ("s.stealth_order_id::text", "s.parent_order_id::text",
                      "active_placement_client_order_id", "pending_rearm", "jsonb_array_elements"):
        assert reference in sql
    assert "p.client_order_id::text" in sql


def test_shared_guard_protects_terminal_pending_and_identity_incomplete_exposure():
    sql = order_db.STEALTH_UNRESOLVED_SQL
    for term in ("s.status NOT IN", "pending_rearm", "active_placement_client_order_id",
                 "active_exchange_order_id", "s.revealed_size", "s.executed_size"):
        assert term in sql
