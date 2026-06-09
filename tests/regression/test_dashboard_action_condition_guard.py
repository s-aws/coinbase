import asyncio
import json
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.exceptions import OrderCreationError
from core.enums import ActionConditionType


def _make_websocket() -> MagicMock:
    ws = MagicMock()
    ws.send = AsyncMock()
    return ws


def _admitting_controller() -> MagicMock:
    ctrl = MagicMock()
    ctrl.is_admitting.return_value = True
    ctrl.state = MagicMock(value="RUNNING")

    @contextmanager
    def _track(_category):
        yield

    ctrl.track_inflight.side_effect = _track
    return ctrl


def _run(coro):
    return asyncio.run(coro)


def _sent_payload(ws: MagicMock) -> dict:
    assert ws.send.await_args_list
    return json.loads(ws.send.await_args_list[-1].args[0])


def _place_order_message(order_configuration, side="BUY") -> str:
    return json.dumps({
        "type": "place_order",
        "params": {
            "product_id": "BTC-USD",
            "side": side,
            "order_configuration": order_configuration,
        },
    })


@pytest.mark.regression
def test_direct_place_order_blocks_max_notional_before_rest(monkeypatch):
    import configuration
    import dashboard_server

    monkeypatch.setattr(configuration, "ACTION_CONDITION_GUARDS", {
        "limits": [{
            "name": "direct_spot_cap",
            "product_id": "BTC-USD",
            "max_notional": 50.0,
        }],
    })
    ws = _make_websocket()
    rest_client = MagicMock()
    message = _place_order_message({
        "limit_limit_gtc": {
            "base_size": "0.001",
            "limit_price": "100000",
        },
    })

    with patch.object(dashboard_server, "REST_CLIENT_AVAILABLE", True), \
         patch.object(dashboard_server, "REST_CLIENT", rest_client), \
         patch.object(dashboard_server, "get_runtime_controller",
                      return_value=_admitting_controller()), \
         patch.object(dashboard_server, "add_log_entry"):
        _run(dashboard_server.handle_client_message(ws, message))

    payload = _sent_payload(ws)
    assert payload["type"] == "order_response"
    assert payload["status"] == "error"
    assert payload["guard"]["block_category"] == "max_notional"
    rest_client.create_order.assert_not_called()


@pytest.mark.regression
def test_direct_place_order_blocks_spot_sell_wallet_before_rest(monkeypatch):
    import core.action_condition_guard as guard_module
    import dashboard_server

    monkeypatch.setattr(guard_module, "rest_credentials_configured", lambda: True)
    monkeypatch.setattr(
        guard_module,
        "fetch_account_wallets",
        lambda: {"BTC": {"available_balance": {"value": "0.25"}}},
    )
    ws = _make_websocket()
    rest_client = MagicMock()
    message = _place_order_message({
        "limit_limit_gtc": {
            "base_size": "1.0",
            "limit_price": "100000",
        },
    }, side="SELL")

    with patch.object(dashboard_server, "REST_CLIENT_AVAILABLE", True), \
         patch.object(dashboard_server, "REST_CLIENT", rest_client), \
         patch.object(dashboard_server, "get_runtime_controller",
                      return_value=_admitting_controller()), \
         patch.object(dashboard_server, "add_log_entry"):
        _run(dashboard_server.handle_client_message(ws, message))

    payload = _sent_payload(ws)
    assert payload["status"] == "error"
    assert payload["guard"]["block_category"] == "wallet_available"
    assert payload["guard"]["currency"] == "BTC"
    rest_client.create_order.assert_not_called()


@pytest.mark.regression
def test_direct_place_order_reports_known_inventory_guard_before_rest(monkeypatch):
    import configuration
    import dashboard_server

    monkeypatch.setattr(configuration, "ACTION_CONDITION_GUARDS", {
        ActionConditionType.WALLET_AVAILABLE.value: {"enabled": False},
        ActionConditionType.KNOWN_INVENTORY_AVAILABLE.value: {
            "enabled": True,
        },
    })
    ws = _make_websocket()
    rest_client = MagicMock()
    message = _place_order_message({
        "limit_limit_gtc": {
            "base_size": "0.1",
            "limit_price": "100000",
        },
    }, side="SELL")

    with patch.object(dashboard_server, "REST_CLIENT_AVAILABLE", True), \
         patch.object(dashboard_server, "REST_CLIENT", rest_client), \
         patch.object(dashboard_server, "stealth_order_bridge", None), \
         patch.object(dashboard_server, "get_runtime_controller",
                      return_value=_admitting_controller()), \
         patch.object(dashboard_server, "add_log_entry"):
        _run(dashboard_server.handle_client_message(ws, message))

    payload = _sent_payload(ws)
    assert payload["status"] == "error"
    assert payload["guard"]["block_category"] == (
        ActionConditionType.KNOWN_INVENTORY_AVAILABLE.value
    )
    assert payload["guard"]["phase"] == "planning"
    assert "evaluator is unavailable" in payload["guard"]["reason"]
    rest_client.create_order.assert_not_called()


@pytest.mark.regression
def test_direct_market_buy_quote_size_blocks_max_notional(monkeypatch):
    import configuration
    import dashboard_server

    monkeypatch.setattr(configuration, "ACTION_CONDITION_GUARDS", {
        "limits": [{
            "name": "direct_quote_cap",
            "product_id": "BTC-USD",
            "max_notional": 100.0,
        }],
    })
    ws = _make_websocket()
    rest_client = MagicMock()
    message = _place_order_message({
        "market_market_ioc": {
            "quote_size": "250",
        },
    })

    with patch.object(dashboard_server, "REST_CLIENT_AVAILABLE", True), \
         patch.object(dashboard_server, "REST_CLIENT", rest_client), \
         patch.object(dashboard_server, "get_runtime_controller",
                      return_value=_admitting_controller()), \
         patch.object(dashboard_server, "add_log_entry"):
        _run(dashboard_server.handle_client_message(ws, message))

    payload = _sent_payload(ws)
    assert payload["status"] == "error"
    assert payload["guard"]["block_category"] == "max_notional"
    assert payload["guard"]["quote_size"] == 250.0
    rest_client.create_order.assert_not_called()


@pytest.mark.regression
def test_direct_place_order_size_validation_runs_before_action_guard():
    import dashboard_server

    ws = _make_websocket()
    rest_client = MagicMock()
    guard_cls = MagicMock()
    guard_cls.return_value.evaluate.side_effect = AssertionError(
        "action guard should not run after size rejection"
    )
    message = _place_order_message({
        "limit_limit_gtc": {
            "base_size": "0.000000001",
            "limit_price": "100000",
        },
    })

    with patch.object(dashboard_server, "REST_CLIENT_AVAILABLE", True), \
         patch.object(dashboard_server, "REST_CLIENT", rest_client), \
         patch.object(dashboard_server, "ActionConditionGuard", guard_cls), \
         patch.object(dashboard_server, "get_runtime_controller",
                      return_value=_admitting_controller()), \
         patch.object(dashboard_server, "add_log_entry"), \
         pytest.raises(OrderCreationError, match="Order rejected at boundary"):
        _run(dashboard_server.handle_client_message(ws, message))

    guard_cls.assert_not_called()
    rest_client.create_order.assert_not_called()
