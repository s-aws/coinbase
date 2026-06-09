import asyncio
import atexit
import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.enums import (
    ActionConditionType,
    EventSourceChannel,
    EventStreamType,
    OrderStatus,
    ProductCapability,
    ProductCapabilityMode,
)
from core.exceptions import OrderCreationError


_ASYNC_RUNNER = None


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
    global _ASYNC_RUNNER
    if _ASYNC_RUNNER is None:
        _ASYNC_RUNNER = asyncio.Runner()
        atexit.register(_ASYNC_RUNNER.close)
    return _ASYNC_RUNNER.run(coro)


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
def test_direct_market_buy_quote_size_blocks_below_quote_min_before_rest(monkeypatch):
    import calculation.size_validation as size_validation
    import dashboard_server

    monkeypatch.setattr(size_validation, "PRODUCT_METADATA", {
        "BTC-USD": {
            "base_increment": "0.00000001",
            "base_min_size": "0.00000001",
            "quote_increment": "0.01",
            "quote_min_size": "10",
        }
    })
    ws = _make_websocket()
    rest_client = MagicMock()
    message = _place_order_message({
        "market_market_ioc": {
            "quote_size": "5",
        },
    })

    with patch.object(dashboard_server, "REST_CLIENT_AVAILABLE", True), \
         patch.object(dashboard_server, "REST_CLIENT", rest_client), \
         patch.object(dashboard_server, "get_runtime_controller",
                      return_value=_admitting_controller()), \
         patch.object(dashboard_server, "add_log_entry"), \
         pytest.raises(OrderCreationError, match="quote_min_size"):
        _run(dashboard_server.handle_client_message(ws, message))

    rest_client.create_order.assert_not_called()


@pytest.mark.regression
def test_direct_place_order_success_returns_client_order_id(monkeypatch):
    import core.action_condition_guard as guard_module
    import dashboard_server

    monkeypatch.setattr(guard_module, "rest_credentials_configured", lambda: False)
    ws = _make_websocket()
    rest_client = MagicMock()
    rest_client.create_order.return_value = SimpleNamespace(
        success=True,
        order_id="exchange-1",
    )
    event_publisher = SimpleNamespace(enabled=True, publish_event=MagicMock(return_value=True))
    message = _place_order_message({
        "market_market_ioc": {
            "quote_size": "5",
        },
    })

    with patch.object(dashboard_server, "REST_CLIENT_AVAILABLE", True), \
         patch.object(dashboard_server, "REST_CLIENT", rest_client), \
         patch.object(dashboard_server, "_get_dashboard_order_event_stream_publisher",
                      return_value=event_publisher), \
         patch.object(dashboard_server, "get_runtime_controller",
                      return_value=_admitting_controller()), \
         patch.object(dashboard_server, "add_log_entry"):
        _run(dashboard_server.handle_client_message(ws, message))

    payload = _sent_payload(ws)
    assert payload["type"] == "order_response"
    assert payload["status"] == "success"
    assert payload["client_order_id"]
    assert payload["order_id"] == "exchange-1"
    assert payload["submission_event_recorded"] is True
    rest_client.create_order.assert_called_once()
    assert rest_client.create_order.call_args.kwargs["client_order_id"] == (
        payload["client_order_id"]
    )
    event_publisher.publish_event.assert_called_once()
    event_kwargs = event_publisher.publish_event.call_args.kwargs
    assert event_kwargs["event_type"] == EventStreamType.ORDER_SUBMITTED.value
    assert event_kwargs["source_channel"] == EventSourceChannel.REST_SUBMIT.value
    assert event_kwargs["status_to"] == OrderStatus.PENDING.value
    assert event_kwargs["payload"]["client_order_id"] == payload["client_order_id"]
    assert event_kwargs["payload"]["order_id"] == "exchange-1"


@pytest.mark.regression
def test_direct_place_order_normalizes_nested_success_response(monkeypatch):
    import core.action_condition_guard as guard_module
    import dashboard_server

    class NestedResponse:
        def to_dict(self):
            return {
                "success": True,
                "success_response": {"order_id": "exchange-nested-1"},
            }

    monkeypatch.setattr(guard_module, "rest_credentials_configured", lambda: False)
    ws = _make_websocket()
    rest_client = MagicMock()
    rest_client.create_order.return_value = NestedResponse()
    event_publisher = SimpleNamespace(enabled=True, publish_event=MagicMock(return_value=True))
    message = _place_order_message({
        "market_market_ioc": {
            "quote_size": "5",
        },
    })

    with patch.object(dashboard_server, "REST_CLIENT_AVAILABLE", True), \
         patch.object(dashboard_server, "REST_CLIENT", rest_client), \
         patch.object(dashboard_server, "_get_dashboard_order_event_stream_publisher",
                      return_value=event_publisher), \
         patch.object(dashboard_server, "get_runtime_controller",
                      return_value=_admitting_controller()), \
         patch.object(dashboard_server, "add_log_entry"):
        _run(dashboard_server.handle_client_message(ws, message))

    payload = _sent_payload(ws)
    assert payload["status"] == "success"
    assert payload["order_id"] == "exchange-nested-1"
    event_kwargs = event_publisher.publish_event.call_args.kwargs
    assert event_kwargs["payload"]["order_id"] == "exchange-nested-1"


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


@pytest.mark.regression
def test_hotpoint_test_order_blocks_spot_capability_before_parent_insert_or_rest(
    monkeypatch,
):
    import configuration
    import dashboard_server

    monkeypatch.setattr(configuration, "PRODUCT_METADATA", {
        "BTC-USD": {"product_type": "SPOT"},
    }, raising=False)
    monkeypatch.setattr(configuration, "PRODUCT_CAPABILITIES", {}, raising=False)
    ws = _make_websocket()
    rest_client = MagicMock()
    insert_parent = MagicMock()
    message = json.dumps({
        "type": "place_hotpoint_test_order",
        "order": {
            "product_id": "BTC-USD",
            "side": "BUY",
            "price": "100000",
            "size": "0.001",
        },
    })

    with patch.object(dashboard_server, "REST_CLIENT_AVAILABLE", True), \
         patch.object(dashboard_server, "REST_CLIENT", rest_client), \
         patch("database.order.insert_order_parent", insert_parent), \
         patch.object(dashboard_server, "get_runtime_controller",
                      return_value=_admitting_controller()), \
         patch.object(dashboard_server, "add_log_entry"):
        _run(dashboard_server.handle_client_message(ws, message))

    payload = _sent_payload(ws)
    assert payload["type"] == "place_hotpoint_test_order_response"
    assert payload["success"] is False
    assert payload["error"] == "product_capability_blocked"
    assert payload["capability"]["capability"] == (
        ProductCapability.HOTPOINT_AUTO_PLACEMENT.value
    )
    insert_parent.assert_not_called()
    rest_client.limit_order_gtc.assert_not_called()


@pytest.mark.regression
def test_hotpoint_test_order_runs_action_guard_before_parent_insert_or_rest(
    monkeypatch,
):
    import configuration
    import dashboard_server

    monkeypatch.setattr(configuration, "PRODUCT_METADATA", {
        "BTC-USD": {"product_type": "SPOT"},
    }, raising=False)
    monkeypatch.setattr(configuration, "PRODUCT_CAPABILITIES", {
        "product_type": {
            "SPOT": {
                ProductCapability.HOTPOINT_AUTO_PLACEMENT.value: (
                    ProductCapabilityMode.ENABLED.value
                ),
            },
        },
    }, raising=False)
    monkeypatch.setattr(configuration, "ACTION_CONDITION_GUARDS", {
        "limits": [{
            "name": "hotpoint_seed_cap",
            "product_id": "BTC-USD",
            "max_notional": 50.0,
        }],
    })
    ws = _make_websocket()
    rest_client = MagicMock()
    insert_parent = MagicMock()
    message = json.dumps({
        "type": "place_hotpoint_test_order",
        "order": {
            "product_id": "BTC-USD",
            "side": "BUY",
            "price": "100000",
            "size": "0.001",
        },
    })

    with patch.object(dashboard_server, "REST_CLIENT_AVAILABLE", True), \
         patch.object(dashboard_server, "REST_CLIENT", rest_client), \
         patch("database.order.insert_order_parent", insert_parent), \
         patch.object(dashboard_server, "get_runtime_controller",
                      return_value=_admitting_controller()), \
         patch.object(dashboard_server, "add_log_entry"):
        _run(dashboard_server.handle_client_message(ws, message))

    payload = _sent_payload(ws)
    assert payload["success"] is False
    assert payload["error"] == "action_condition_guard_blocked"
    assert payload["guard"]["block_category"] == "max_notional"
    insert_parent.assert_not_called()
    rest_client.limit_order_gtc.assert_not_called()


@pytest.mark.regression
def test_hotpoint_test_order_success_records_submission_evidence(monkeypatch):
    import configuration
    import core.action_condition_guard as guard_module
    import dashboard_server

    monkeypatch.setattr(configuration, "PRODUCT_METADATA", {
        "BTC-USD": {"product_type": "SPOT"},
    }, raising=False)
    monkeypatch.setattr(configuration, "PRODUCT_CAPABILITIES", {
        "product_type": {
            "SPOT": {
                ProductCapability.HOTPOINT_AUTO_PLACEMENT.value: (
                    ProductCapabilityMode.ENABLED.value
                ),
            },
        },
    }, raising=False)
    monkeypatch.setattr(configuration, "ACTION_CONDITION_GUARDS", {}, raising=False)
    monkeypatch.setattr(guard_module, "rest_credentials_configured", lambda: False)
    ws = _make_websocket()
    rest_client = MagicMock()
    rest_client.limit_order_gtc.return_value = SimpleNamespace(
        success=True,
        order_id="exchange-hotpoint-1",
    )
    insert_parent = MagicMock(return_value=1)
    update_parent = MagicMock()
    event_publisher = SimpleNamespace(enabled=True, publish_event=MagicMock(return_value=True))
    message = json.dumps({
        "type": "place_hotpoint_test_order",
        "order": {
            "product_id": "BTC-USD",
            "side": "BUY",
            "price": "100000",
            "size": "0.001",
        },
    })

    with patch.object(dashboard_server, "REST_CLIENT_AVAILABLE", True), \
         patch.object(dashboard_server, "REST_CLIENT", rest_client), \
         patch.object(dashboard_server, "_get_dashboard_order_event_stream_publisher",
                      return_value=event_publisher), \
         patch("database.order.insert_order_parent", insert_parent), \
         patch("database.order.update_order_parent_status", update_parent), \
         patch.object(dashboard_server, "get_runtime_controller",
                      return_value=_admitting_controller()), \
         patch.object(dashboard_server, "add_log_entry"):
        _run(dashboard_server.handle_client_message(ws, message))

    payload = _sent_payload(ws)
    assert payload["success"] is True
    assert payload["order_id"] == "exchange-hotpoint-1"
    assert payload["submission_event_recorded"] is True
    insert_parent.assert_called_once()
    rest_client.limit_order_gtc.assert_called_once()
    event_publisher.publish_event.assert_called_once()
    event_kwargs = event_publisher.publish_event.call_args.kwargs
    assert event_kwargs["event_type"] == EventStreamType.ORDER_SUBMITTED.value
    assert event_kwargs["source_channel"] == EventSourceChannel.REST_SUBMIT.value
    assert event_kwargs["payload"]["order_id"] == "exchange-hotpoint-1"
    assert event_kwargs["payload"]["client_order_id"] == payload["client_order_id"]
    update_parent.assert_not_called()


@pytest.mark.regression
def test_hotpoint_test_order_is_runtime_admission_gated():
    import dashboard_server

    assert "place_hotpoint_test_order" in dashboard_server._ORIGINATING_MSG_TYPES
