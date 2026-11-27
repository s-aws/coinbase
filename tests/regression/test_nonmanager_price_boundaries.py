"""Regression coverage for exchange-bound prices outside the stealth manager."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


pytestmark = pytest.mark.regression


def test_error_stealth_orders_are_not_active_or_exportable():
    import dashboard_server
    from core.enums import StealthOrderStatus

    assert StealthOrderStatus.ERROR.value in dashboard_server._TERMINAL_STEALTH_STATUSES
    assert StealthOrderStatus.ERROR.value not in dashboard_server._ACTIVE_STEALTH_STATUSES


def test_move_manager_normalizes_pending_parent_price_before_db_write():
    from business.move_manager import MoveManager

    manager = MoveManager.__new__(MoveManager)
    manager.orderbook = MagicMock()
    manager.orderbook.get_product_metadata.return_value = {
        "price_increment": "5"
    }
    insert_parent = MagicMock(return_value=11)

    with patch.object(
             manager,
             "can_move_order",
             return_value=(True, "eligible"),
         ), \
         patch("business.move_manager.insert_order_parent", insert_parent), \
         patch("business.move_manager.insert_order_move", return_value=22):
        result = manager.move_order(
            "original-parent",
            {
                "product_id": "TEST-USD",
                "side": "BUY",
                "size": 1,
                "price": 101.9,
                "target_movement": 1,
            },
        )

    assert result["success"] is True
    assert insert_parent.call_args.kwargs["price"] == 100.0


def test_pending_move_configuration_is_normalized_before_db_write():
    from business.move_manager import MoveManager

    manager = MoveManager.__new__(MoveManager)
    manager.orderbook = MagicMock()
    manager.orderbook.get_product_metadata.return_value = {
        "price_increment": "5"
    }
    create_pending = MagicMock(return_value=12)

    with patch("business.move_manager.get_parent_order", return_value={"id": 1}), \
         patch("business.move_manager.has_pending_move", return_value=False), \
         patch("business.move_manager.create_pending_move", create_pending):
        result = manager.pre_mark_for_move(
            "original-parent",
            {
                "product_id": "TEST-USD",
                "side": "SELL",
                "size": 1,
                "price": 101.9,
                "target_movement": 1,
            },
        )

    assert result["success"] is True
    assert (
        create_pending.call_args.kwargs["new_order_details"]["price"]
        == 105.0
    )


def test_dashboard_parent_update_normalizes_before_repository_write():
    import database.order_dashboard_helpers as helpers

    db = MagicMock()
    db.execute_update.return_value = 1
    with patch.object(
             helpers,
             "get_parent_order",
             return_value={"product_id": "TEST-USD", "side": "SELL"},
         ), \
         patch("database.database.PostgresDB", return_value=db):
        result = helpers.update_parent_order(
            "parent-id",
            {"price": 101.9},
            metadata_reader=lambda _product_id: {"price_increment": "5"},
        )

    assert result is True
    query, params = db.execute_update.call_args.args
    assert "price = %s" in query
    assert params[0] == 105.0
