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
import database.order_dashboard_helpers as dashboard_db
from core.enums import EngineState, StealthOrderStatus


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
    rest = Mock()
    rest.cancel_orders.return_value = [{"success": True}]
    clear = Mock(return_value={"success": True, "rows_deleted": 1, "message": "Cleared"})
    monkeypatch.setattr(dashboard_server, "stealth_order_bridge", bridge)
    monkeypatch.setattr(dashboard_server, "engine_state", cache)
    monkeypatch.setattr(dashboard_server, "connected_clients", {websocket})
    monkeypatch.setattr(dashboard_server, "get_runtime_controller", lambda: controller)
    monkeypatch.setattr(dashboard_server, "add_log_entry", Mock())
    monkeypatch.setattr(dashboard_server, "REST_CLIENT", rest)
    monkeypatch.setattr(dashboard_server, "REST_CLIENT_AVAILABLE", True)
    monkeypatch.setattr(order_db, "clear_all_stealth_orders", clear)

    def invoke(payload):
        with asyncio.Runner() as runner:
            runner.run(dashboard_server.handle_client_message(websocket, json.dumps(payload)))
        return json.loads(websocket.send.await_args_list[-1].args[0])

    return SimpleNamespace(order=order, orders=orders, manager=manager, bridge=bridge,
                           cache=cache, rest=rest, clear=clear, invoke=invoke)


@pytest.mark.parametrize("message_type,identity", [
    ("cancel_stealth_order", SID), ("cancel_order", SID), ("cancel_order", PLACEMENT),
])
def test_managed_cancel_routes_to_bridge_and_reports_pending_while_paused(command_case, message_type, identity):
    case = command_case
    key = "stealth_order_id" if message_type == "cancel_stealth_order" else "client_order_id"

    response = case.invoke({"type": message_type, key: identity})

    case.bridge.cancel_stealth_order.assert_called_once_with(SID, "user_cancelled")
    case.rest.cancel_orders.assert_not_called()
    assert response["accepted"] is True
    assert response["exchange_cancel_pending"] is True
    assert response["order"] == case.order == case.cache["stealth_orders"][SID]
    assert response["order"]["status"] == StealthOrderStatus.CANCELLED.value
    assert "pending" in response["message"].lower()


def test_hidden_cancel_reports_no_exchange_confirmation_needed(command_case):
    case = command_case
    case.order.update(status=StealthOrderStatus.HIDDEN.value, revealed_size=0.0,
                      anchor_repricing_state_json={})

    response = case.invoke({"type": "cancel_stealth_order", "stealth_order_id": SID})

    assert response["accepted"] is True
    assert response["exchange_cancel_pending"] is False


def test_failed_cancel_is_not_success_and_publishes_retained_incomplete_exposure(command_case):
    case = command_case

    def incomplete(*_):
        case.order.update(status=StealthOrderStatus.CANCELLED.value, failure_reason="Missing placement identity")
        case.order["anchor_repricing_state_json"] = {"operator_cancel_requested_at": "2026-09-18T12:00:00"}
        return False

    case.bridge.cancel_stealth_order.side_effect = incomplete
    response = case.invoke({"type": "cancel_stealth_order", "stealth_order_id": SID})

    assert response["accepted"] is False
    assert response["exchange_cancel_pending"] is True
    assert response["error"] == "Missing placement identity"
    assert response["order"] == case.order
    case.rest.cancel_orders.assert_not_called()


def test_managed_lookup_failure_does_not_fall_back_to_raw_rest(command_case):
    case = command_case
    case.manager._get_stealth_order.side_effect = RuntimeError("Lookup unavailable")

    response = case.invoke({"type": "cancel_order", "client_order_id": SID})

    assert response["status"] == "error"
    case.rest.cancel_orders.assert_not_called()


def test_unmapped_cancel_preserves_existing_rest_path(command_case):
    case = command_case
    external_id = "ad91ff11-be59-4b8b-ac17-2e71d15e9faf"

    response = case.invoke({"type": "cancel_order", "client_order_id": external_id})

    assert response["status"] == "success"
    case.bridge.cancel_stealth_order.assert_not_called()
    case.rest.cancel_orders.assert_called_once_with(order_ids=[external_id])


@pytest.mark.parametrize("accepted", [False, True])
def test_clear_all_retains_memory_and_durable_recovery_until_settled(command_case, accepted):
    case = command_case
    if not accepted:
        case.bridge.cancel_stealth_order.side_effect = None
        case.bridge.cancel_stealth_order.return_value = False

    response = case.invoke({"type": "clear_all_stealth_orders"})

    assert response["type"] == "stealth_orders_clear_result"
    assert response["cleared"] is False
    assert response["exchange_cancel_pending"] is True
    assert SID in case.orders
    assert PLACEMENT in case.manager._placed_order_index
    case.manager.clear_in_memory_orders.assert_not_called()
    case.clear.assert_not_called()


def test_clear_all_skips_settled_terminal_orders_and_clears_only_after_db_success(command_case):
    case = command_case
    case.order.update(status=StealthOrderStatus.EXECUTED.value, executed_size=2.0,
                      anchor_repricing_state_json={})

    response = case.invoke({"type": "clear_all_stealth_orders"})

    assert response["type"] == "stealth_orders_cleared"
    case.bridge.cancel_stealth_order.assert_not_called()
    case.clear.assert_called_once_with()
    assert case.orders == {}
    assert case.manager._placed_order_index == {}


def test_database_refusal_leaves_memory_and_index_intact(command_case):
    case = command_case
    case.order.update(status=StealthOrderStatus.EXECUTED.value, executed_size=2.0,
                      anchor_repricing_state_json={})
    case.clear.return_value = {"success": False, "error": "Unresolved durable intent"}

    response = case.invoke({"type": "clear_all_stealth_orders"})

    assert response["type"] == "error"
    case.manager.clear_in_memory_orders.assert_not_called()
    assert PLACEMENT in case.manager._placed_order_index


def test_parent_delete_refusal_is_not_announced_as_deleted(command_case, monkeypatch):
    delete = Mock(return_value=False)
    monkeypatch.setattr(dashboard_db, "delete_parent_order", delete)

    response = command_case.invoke({"type": "delete_parent_order", "client_order_id": SID})

    assert response["type"] == "error"
    delete.assert_called_once_with(SID)
