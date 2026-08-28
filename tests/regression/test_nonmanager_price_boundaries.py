"""Regression coverage for exchange-bound prices outside the stealth manager."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


pytestmark = pytest.mark.regression


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _websocket() -> MagicMock:
    websocket = MagicMock()
    websocket.send = AsyncMock()
    return websocket


def _admitting_controller() -> MagicMock:
    controller = MagicMock()
    controller.is_admitting.return_value = True
    controller.state = MagicMock(value="RUNNING")
    return controller


def _last_payload(websocket: MagicMock) -> dict:
    return json.loads(websocket.send.await_args_list[-1].args[0])


def _accepted_response(**kwargs) -> dict:
    return {
        "success": True,
        "success_response": {
            "order_id": "exchange-order-id",
            "client_order_id": kwargs["client_order_id"],
        },
    }


def _direct_order_message(*, side: str = "BUY", price: str = "101.9") -> str:
    return json.dumps({
        "type": "place_order",
        "params": {
            "product_id": "TEST-USD",
            "side": side,
            "order_configuration": {
                "limit_limit_gtc": {
                    "base_size": "1",
                    "limit_price": price,
                    "post_only": False,
                },
            },
        },
    })


def _hotpoint_message(*, side: str = "BUY", price: float = 101.9) -> str:
    return json.dumps({
        "type": "place_hotpoint_test_order",
        "order": {
            "product_id": "TEST-USD",
            "side": side,
            "price": price,
            "size": 1,
        },
    })


def test_direct_limit_uses_one_normalized_price_for_validation_and_rest():
    import dashboard_server

    websocket = _websocket()
    rest = MagicMock()
    rest.create_order.side_effect = _accepted_response

    with patch.object(dashboard_server, "REST_CLIENT_AVAILABLE", True), \
         patch.object(dashboard_server, "REST_CLIENT", rest), \
         patch.object(
             dashboard_server,
             "get_runtime_controller",
             return_value=_admitting_controller(),
         ), \
         patch("calculation.price_validation.get_product_metadata",
               return_value={"price_increment": "5"}), \
         patch.object(dashboard_server, "add_log_entry"):
        _run(dashboard_server.handle_client_message(
            websocket,
            _direct_order_message(side="BUY", price="101.9"),
        ))

    submitted = rest.create_order.call_args.kwargs
    assert submitted["order_configuration"]["limit_limit_gtc"]["limit_price"] == "100.0"
    assert _last_payload(websocket) == {
        "type": "order_response",
        "status": "success",
        "message": "Order created",
        "order_id": "exchange-order-id",
    }


def test_direct_limit_explicit_rejection_is_an_error_response():
    import dashboard_server

    websocket = _websocket()
    rest = MagicMock()
    rest.create_order.return_value = {
        "success": False,
        "failure_reason": "INVALID_PRICE_PRECISION",
    }

    with patch.object(dashboard_server, "REST_CLIENT_AVAILABLE", True), \
         patch.object(dashboard_server, "REST_CLIENT", rest), \
         patch.object(
             dashboard_server,
             "get_runtime_controller",
             return_value=_admitting_controller(),
         ), \
         patch("calculation.price_validation.get_product_metadata",
               return_value={"price_increment": "5"}), \
         patch.object(dashboard_server, "add_log_entry"):
        _run(dashboard_server.handle_client_message(
            websocket,
            _direct_order_message(),
        ))

    payload = _last_payload(websocket)
    assert payload["status"] == "error"
    assert payload["client_order_id"] == rest.create_order.call_args.kwargs[
        "client_order_id"
    ]
    assert "REJECTED" in payload["message"]
    assert "INVALID_PRICE_PRECISION" in payload["message"]


def test_direct_limit_missing_tick_fails_before_rest_with_error_response():
    import dashboard_server

    websocket = _websocket()
    rest = MagicMock()

    with patch.object(dashboard_server, "REST_CLIENT_AVAILABLE", True), \
         patch.object(dashboard_server, "REST_CLIENT", rest), \
         patch.object(
             dashboard_server,
             "get_runtime_controller",
             return_value=_admitting_controller(),
         ), \
         patch("calculation.price_validation.get_product_metadata",
               return_value={}), \
         patch.object(dashboard_server, "add_log_entry"):
        _run(dashboard_server.handle_client_message(
            websocket,
            _direct_order_message(),
        ))

    rest.create_order.assert_not_called()
    payload = _last_payload(websocket)
    assert payload["status"] == "error"
    assert payload["client_order_id"]
    assert "missing price_increment" in payload["message"]


def test_hotpoint_test_order_persists_and_submits_the_same_price():
    import dashboard_server

    websocket = _websocket()
    rest = MagicMock()
    rest.limit_order_gtc.side_effect = _accepted_response
    insert_parent = MagicMock(return_value=1)

    with patch.object(
             dashboard_server,
             "get_runtime_controller",
             return_value=_admitting_controller(),
         ), \
         patch.object(dashboard_server, "REST_CLIENT", rest), \
         patch("database.order.insert_order_parent", insert_parent), \
         patch("database.order.update_order_parent_status") as update_status, \
         patch("calculation.price_validation.get_product_metadata",
               return_value={"price_increment": "5"}), \
         patch.object(dashboard_server, "add_log_entry"):
        _run(dashboard_server.handle_client_message(
            websocket,
            _hotpoint_message(side="SELL", price=101.9),
        ))

    assert insert_parent.call_args.kwargs["price"] == 105.0
    assert rest.limit_order_gtc.call_args.kwargs["limit_price"] == "105.0"
    update_status.assert_not_called()
    payload = _last_payload(websocket)
    assert payload["success"] is True
    assert payload["order_id"] == "exchange-order-id"


def test_hotpoint_test_rejection_marks_preinserted_parent_failed():
    import dashboard_server
    from core.enums import OrderStatus

    websocket = _websocket()
    rest = MagicMock()
    rest.limit_order_gtc.return_value = {
        "success": False,
        "failure_reason": "INVALID_PRICE_PRECISION",
    }
    insert_parent = MagicMock(return_value=1)

    with patch.object(
             dashboard_server,
             "get_runtime_controller",
             return_value=_admitting_controller(),
         ), \
         patch.object(dashboard_server, "REST_CLIENT", rest), \
         patch("database.order.insert_order_parent", insert_parent), \
         patch("database.order.update_order_parent_status") as update_status, \
         patch("calculation.price_validation.get_product_metadata",
               return_value={"price_increment": "5"}), \
         patch.object(dashboard_server, "add_log_entry"):
        _run(dashboard_server.handle_client_message(
            websocket,
            _hotpoint_message(),
        ))

    update_status.assert_called_once()
    assert update_status.call_args.args[1] == OrderStatus.FAILED.value
    payload = _last_payload(websocket)
    assert payload["success"] is False
    assert payload["client_order_id"] == rest.limit_order_gtc.call_args.kwargs[
        "client_order_id"
    ]
    assert "REJECTED" in payload["error"]
    assert "INVALID_PRICE_PRECISION" in payload["error"]


def test_hotpoint_test_missing_tick_fails_before_db_and_rest():
    import dashboard_server

    websocket = _websocket()
    rest = MagicMock()
    insert_parent = MagicMock(return_value=1)

    with patch.object(
             dashboard_server,
             "get_runtime_controller",
             return_value=_admitting_controller(),
         ), \
         patch.object(dashboard_server, "REST_CLIENT", rest), \
         patch("database.order.insert_order_parent", insert_parent), \
         patch("database.order.update_order_parent_status") as update_status, \
         patch("calculation.price_validation.get_product_metadata",
               return_value={}), \
         patch.object(dashboard_server, "add_log_entry"):
        _run(dashboard_server.handle_client_message(
            websocket,
            _hotpoint_message(),
        ))

    insert_parent.assert_not_called()
    rest.limit_order_gtc.assert_not_called()
    update_status.assert_not_called()
    payload = _last_payload(websocket)
    assert payload["success"] is False
    assert "missing price_increment" in payload["error"]


def test_hotpoint_test_parent_insert_failure_prevents_rest_submission():
    import dashboard_server

    websocket = _websocket()
    rest = MagicMock()
    insert_parent = MagicMock(return_value=None)

    with patch.object(
             dashboard_server,
             "get_runtime_controller",
             return_value=_admitting_controller(),
         ), \
         patch.object(dashboard_server, "REST_CLIENT", rest), \
         patch("database.order.insert_order_parent", insert_parent), \
         patch("database.order.update_order_parent_status") as update_status, \
         patch("calculation.price_validation.get_product_metadata",
               return_value={"price_increment": "5"}), \
         patch.object(dashboard_server, "add_log_entry"):
        _run(dashboard_server.handle_client_message(
            websocket,
            _hotpoint_message(),
        ))

    rest.limit_order_gtc.assert_not_called()
    update_status.assert_not_called()
    payload = _last_payload(websocket)
    assert payload["success"] is False
    assert "insert returned no row id" in payload["error"]


def test_error_stealth_orders_are_not_active_or_exportable():
    import dashboard_server
    from core.enums import StealthOrderStatus

    assert StealthOrderStatus.ERROR.value in dashboard_server._TERMINAL_STEALTH_STATUSES
    assert StealthOrderStatus.ERROR.value not in dashboard_server._ACTIVE_STEALTH_STATUSES


def test_move_manager_normalizes_pending_parent_price_before_db_write():
    from business.move_manager import MoveManager

    manager = MoveManager.__new__(MoveManager)
    manager.orderbook = None
    insert_parent = MagicMock(return_value=11)

    with patch.object(
             manager,
             "can_move_order",
             return_value=(True, "eligible"),
         ), \
         patch("business.move_manager.insert_order_parent", insert_parent), \
         patch("business.move_manager.insert_order_move", return_value=22), \
         patch("calculation.price_validation.get_product_metadata",
               return_value={"price_increment": "5"}):
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
    manager.orderbook = None
    create_pending = MagicMock(return_value=12)

    with patch("business.move_manager.get_parent_order", return_value={"id": 1}), \
         patch("business.move_manager.has_pending_move", return_value=False), \
         patch("business.move_manager.create_pending_move", create_pending), \
         patch("calculation.price_validation.get_product_metadata",
               return_value={"price_increment": "5"}):
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


def test_dashboard_parent_insert_normalizes_before_repository_write():
    import database.order_dashboard_helpers as helpers

    insert_parent = MagicMock(return_value=1)
    with patch.object(helpers, "insert_order_parent", insert_parent), \
         patch("calculation.price_validation.get_product_metadata",
               return_value={"price_increment": "5"}):
        result = helpers.insert_parent_order(
            client_order_id="parent-id",
            product_id="TEST-USD",
            side="BUY",
            size=1,
            price=101.9,
        )

    assert result == 1
    assert insert_parent.call_args.kwargs["price"] == 100.0


def test_dashboard_parent_update_normalizes_before_repository_write():
    import database.order_dashboard_helpers as helpers

    db = MagicMock()
    db.execute_update.return_value = 1
    with patch.object(
             helpers,
             "get_parent_order",
             return_value={"product_id": "TEST-USD", "side": "SELL"},
         ), \
         patch("database.database.PostgresDB", return_value=db), \
         patch("calculation.price_validation.get_product_metadata",
               return_value={"price_increment": "5"}):
        result = helpers.update_parent_order(
            "parent-id",
            {"price": 101.9},
        )

    assert result is True
    query, params = db.execute_update.call_args.args
    assert "price = %s" in query
    assert params[0] == 105.0


def test_dashboard_premark_routes_through_canonical_move_manager():
    import dashboard_server

    websocket = _websocket()
    move_manager = MagicMock()
    move_manager.pre_mark_for_move.return_value = {
        "success": True,
        "move_id": 17,
        "message": "scheduled",
        "error": None,
    }
    message = json.dumps({
        "type": "premark_move",
        "move": {
            "parent_client_order_id": "parent-id",
            "new_order_details": {
                "product_id": "TEST-USD",
                "side": "BUY",
                "size": 1,
                "price": 101.9,
                "target_movement": 1,
            },
            "reason": "operator_move",
            "notes": "test",
        },
    })

    with patch(
             "business.move_manager.MoveManager",
             return_value=move_manager,
         ), \
         patch.object(
             dashboard_server,
             "get_runtime_controller",
             return_value=_admitting_controller(),
         ), \
         patch.object(dashboard_server, "connected_clients", {websocket}), \
         patch.object(dashboard_server, "add_log_entry"):
        _run(dashboard_server.handle_client_message(websocket, message))

    move_manager.pre_mark_for_move.assert_called_once_with(
        original_parent_client_order_id="parent-id",
        new_order_details={
            "product_id": "TEST-USD",
            "side": "BUY",
            "size": 1,
            "price": 101.9,
            "target_movement": 1,
        },
        reason="operator_move",
        notes="test",
    )
    payload = _last_payload(websocket)
    assert payload["type"] == "order_premarked"
    assert payload["success"] is True
    assert payload["move_id"] == 17
