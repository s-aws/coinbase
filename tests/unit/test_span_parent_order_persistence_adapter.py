"""Contracts for deterministic span parent-row persistence access."""

from unittest.mock import MagicMock, patch

import pytest

from core.exceptions import DatabaseConnectionError
from database import order as order_db
from database.execution_persistence import DatabaseOrderPersistenceAdapter


CLIENT_ORDER_ID = "11111111-1111-4111-8111-111111111111"


def test_adapter_delegates_parent_lookup_to_explicit_database_client() -> None:
    db_client = MagicMock()
    parent_row = {"client_order_id": CLIENT_ORDER_ID}
    adapter = DatabaseOrderPersistenceAdapter(db_client)

    with patch.object(
        order_db,
        "get_parent_order",
        return_value=parent_row,
    ) as get_parent_order:
        result = adapter.get_parent_order(CLIENT_ORDER_ID)

    assert result == parent_row
    get_parent_order.assert_called_once_with(
        CLIENT_ORDER_ID,
        db_client=db_client,
    )


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        (
            [{"client_order_id": CLIENT_ORDER_ID}],
            {"client_order_id": CLIENT_ORDER_ID},
        ),
        ([], None),
    ],
)
def test_canonical_parent_lookup_uses_explicit_database_client(
    rows,
    expected,
) -> None:
    db_client = MagicMock()
    db_client.execute_query.return_value = rows

    result = order_db.get_parent_order(
        CLIENT_ORDER_ID,
        db_client=db_client,
    )

    assert result == expected
    db_client.execute_query.assert_called_once_with(
        "SELECT * FROM order_parent WHERE client_order_id = %s",
        (CLIENT_ORDER_ID,),
    )


def test_canonical_parent_lookup_preserves_connection_error_mapping() -> None:
    db_client = MagicMock()
    db_client.execute_query.side_effect = TimeoutError("connection timeout")

    with pytest.raises(DatabaseConnectionError):
        order_db.get_parent_order(
            CLIENT_ORDER_ID,
            db_client=db_client,
        )
