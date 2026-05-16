"""Regression: order_parent writes must reject non-UUID tracking ids."""

import uuid
from unittest.mock import Mock

import pytest

from core.exceptions import OrderPersistenceError
from database import order as order_db


@pytest.mark.regression
def test_insert_order_parent_rejects_non_uuid_client_order_id_before_db_lookup(monkeypatch):
    monkeypatch.setattr(
        order_db,
        "get_parent_order",
        Mock(side_effect=AssertionError("bad ids must not reach the database")),
    )

    with pytest.raises(OrderPersistenceError) as exc_info:
        order_db.insert_order_parent(
            client_order_id="test_order_6",
            product_id="BTC-USDC",
            side="BUY",
            size=1.0,
            price=42000.0,
            target_movement=0.005,
        )

    assert exc_info.value.error_type == "ValidationError"
    assert "client_order_id must be a valid UUID" in str(exc_info.value)
    order_db.get_parent_order.assert_not_called()


@pytest.mark.regression
def test_insert_order_parent_rejects_non_uuid_parent_order_id_before_db_lookup(monkeypatch):
    monkeypatch.setattr(
        order_db,
        "get_parent_order",
        Mock(side_effect=AssertionError("bad parent ids must not reach the database")),
    )

    client_order_id = str(uuid.uuid4())
    with pytest.raises(OrderPersistenceError) as exc_info:
        order_db.insert_order_parent(
            client_order_id=client_order_id,
            parent_order_id="test_parent_1",
            product_id="BTC-USDC",
            side="BUY",
            size=1.0,
            price=42000.0,
            target_movement=0.005,
        )

    assert exc_info.value.error_type == "ValidationError"
    assert "parent_order_id must be a valid UUID" in str(exc_info.value)
    order_db.get_parent_order.assert_not_called()

