"""Operator commands retain cancellation truth until exchange confirmation."""

import asyncio
from contextlib import nullcontext
from copy import deepcopy
import json
from threading import RLock
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import dashboard_server
import database.order as order_db
from core.enums import (
    EngineState,
    OperatorRpcErrorCode,
    OperatorRpcMethod,
    StealthOrderStatus,
)
from tests.regression.operator_rpc_test_support import (
    rpc_error,
    rpc_request,
    rpc_result,
)


pytestmark = pytest.mark.regression
SID = "203e541b-4801-4e21-b947-4d1ba6e3a465"
PLACEMENT = "8a2a834d-12aa-4151-9b3e-0a9b947e15df"


@pytest.fixture
def command_case(monkeypatch):
    order = {
        "stealth_order_id": SID,
        "status": StealthOrderStatus.REVEALED.value,
        "revealed_size": 2.0, "executed_size": 0.0,
        "anchor_repricing_state_json": {
            "active_placement_client_order_id": PLACEMENT,
            "active_exchange_order_id": "exchange-test",
        },
    }
    orders = {SID: order}
    index = {PLACEMENT: order}
    manager = SimpleNamespace(
        in_memory_orders=orders, _placed_order_index=index, _creation_lock=RLock(),
        _get_stealth_order=Mock(side_effect=orders.get),
        find_stealth_order_by_placed_order_id=Mock(side_effect=index.get),
        clear_in_memory_orders=Mock(side_effect=orders.clear),
    )
    action_lock = RLock()

    def cancel(sid, reason):
        current = orders[sid]
        current["status"] = StealthOrderStatus.CANCELLED.value
        current["anchor_repricing_state_json"]["operator_cancel_requested_at"] = "2026-09-18T12:00:00"
        return True

    bridge = SimpleNamespace(
        stealth_manager=manager,
        _get_order_action_lock=Mock(return_value=action_lock),
        cancel_stealth_order=Mock(side_effect=cancel),
        get_stealth_orders=lambda: dict(orders),
    )
    controller = Mock()
    controller.state = EngineState.PAUSED
    controller.is_admitting.return_value = False
    controller.track_inflight.side_effect = lambda *_: nullcontext()
    websocket = Mock(send=AsyncMock())
    cache = {"stealth_orders": deepcopy(orders)}
    clear = Mock(return_value={"success": True, "rows_deleted": 1, "message": "Cleared"})
    monkeypatch.setattr(dashboard_server, "stealth_order_bridge", bridge)
    monkeypatch.setattr(dashboard_server, "engine_state", cache)
    monkeypatch.setattr(dashboard_server, "connected_clients", {websocket})
    monkeypatch.setattr(dashboard_server, "get_runtime_controller", lambda: controller)
    monkeypatch.setattr(dashboard_server, "add_log_entry", Mock())
    monkeypatch.setattr(
        dashboard_server,
        "_broadcast_stealth_orders_projection",
        AsyncMock(),
    )
    monkeypatch.setattr(order_db, "clear_all_stealth_orders", clear)

    def invoke(method, params=None):
        with asyncio.Runner() as runner:
            runner.run(dashboard_server.handle_client_message(
                websocket,
                rpc_request(method, params),
            ))
        return json.loads(websocket.send.await_args_list[-1].args[0])

    return SimpleNamespace(order=order, orders=orders, manager=manager, bridge=bridge,
                           cache=cache, clear=clear, invoke=invoke)


def test_managed_cancel_routes_to_bridge_and_reports_pending_while_paused(command_case):
    case = command_case

    response = rpc_result(case.invoke(
        OperatorRpcMethod.STEALTH_CANCEL,
        {"client_order_id": SID},
    ))

    case.bridge.cancel_stealth_order.assert_called_once_with(SID, "user_cancelled")
    assert response["accepted"] is True
    assert response["exchange_cancel_pending"] is True
    assert response["order"]["client_order_id"] == SID
    assert "stealth_order_id" not in response["order"]
    assert case.order == case.cache["stealth_orders"][SID]
    assert response["order"]["status"] == StealthOrderStatus.CANCELLED.value
    assert "pending" in response["message"].lower()


def test_hidden_cancel_reports_no_exchange_confirmation_needed(command_case):
    case = command_case
    case.order.update(status=StealthOrderStatus.HIDDEN.value, revealed_size=0.0,
                      anchor_repricing_state_json={})

    response = rpc_result(case.invoke(
        OperatorRpcMethod.STEALTH_CANCEL,
        {"client_order_id": SID},
    ))

    assert response["accepted"] is True
    assert response["exchange_cancel_pending"] is False


def test_failed_cancel_is_not_success_and_publishes_retained_incomplete_exposure(command_case):
    case = command_case

    def incomplete(*_):
        case.order.update(status=StealthOrderStatus.CANCELLED.value, failure_reason="Missing placement identity")
        case.order["anchor_repricing_state_json"] = {"operator_cancel_requested_at": "2026-09-18T12:00:00"}
        return False

    case.bridge.cancel_stealth_order.side_effect = incomplete
    response = rpc_error(case.invoke(
        OperatorRpcMethod.STEALTH_CANCEL,
        {"client_order_id": SID},
    ))

    assert response["code"] == int(OperatorRpcErrorCode.APPLICATION_REJECTED)
    assert response["data"]["accepted"] is False
    assert response["data"]["exchange_cancel_pending"] is True
    assert response["message"] == "Missing placement identity"
    assert response["data"]["order"]["client_order_id"] == SID
    assert "stealth_order_id" not in response["data"]["order"]


@pytest.mark.parametrize("accepted", [False, True])
def test_clear_all_retains_memory_and_durable_recovery_until_settled(command_case, accepted):
    case = command_case
    if not accepted:
        case.bridge.cancel_stealth_order.side_effect = None
        case.bridge.cancel_stealth_order.return_value = False

    response = rpc_error(case.invoke(OperatorRpcMethod.STEALTH_CLEAR_ALL))

    assert response["code"] == int(OperatorRpcErrorCode.APPLICATION_REJECTED)
    assert response["data"]["cleared"] is False
    assert response["data"]["exchange_cancel_pending"] is True
    assert SID in case.orders
    assert PLACEMENT in case.manager._placed_order_index
    case.manager.clear_in_memory_orders.assert_not_called()
    case.clear.assert_not_called()


def test_clear_all_skips_settled_terminal_orders_and_clears_only_after_db_success(command_case):
    case = command_case
    case.order.update(status=StealthOrderStatus.EXECUTED.value, executed_size=2.0,
                      anchor_repricing_state_json={})

    response = rpc_result(case.invoke(OperatorRpcMethod.STEALTH_CLEAR_ALL))

    assert response["rows_deleted"] == 1
    case.bridge.cancel_stealth_order.assert_not_called()
    case.clear.assert_called_once_with()
    assert case.orders == {}
    assert case.manager._placed_order_index == {}


def test_database_refusal_leaves_memory_and_index_intact(command_case):
    case = command_case
    case.order.update(status=StealthOrderStatus.EXECUTED.value, executed_size=2.0,
                      anchor_repricing_state_json={})
    case.clear.return_value = {"success": False, "error": "Unresolved durable intent"}

    response = rpc_error(case.invoke(OperatorRpcMethod.STEALTH_CLEAR_ALL))

    assert response["code"] == int(OperatorRpcErrorCode.APPLICATION_FAILED)
    case.manager.clear_in_memory_orders.assert_not_called()
    assert PLACEMENT in case.manager._placed_order_index
