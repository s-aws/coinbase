"""Destructive cleanup keeps durable cancellation and parent recovery evidence."""

from contextlib import nullcontext
from unittest.mock import Mock

import pytest

import database.order as order_db


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


def test_shared_guard_protects_terminal_pending_and_identity_incomplete_exposure():
    sql = order_db.STEALTH_UNRESOLVED_SQL
    for term in ("s.status NOT IN", "pending_rearm", "active_placement_client_order_id",
                 "active_exchange_order_id", "s.revealed_size", "s.executed_size"):
        assert term in sql
