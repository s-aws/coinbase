import asyncio
import atexit
import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.enums import (
    ActionConditionType,
    ActionGuardPhase,
    EventSourceChannel,
    EventStreamType,
    ProductCapability,
    ProductCapabilityMode,
    ProductType,
)
from core.exceptions import OrderCreationError
from application.admin_api.spot_portfolio_binding import (
    EXPECTED_SPOT_PORTFOLIO_TYPE,
    SpotPortfolioBindingEvidence,
)


_ASYNC_RUNNER = None
_TEST_PORTFOLIO_ID = "11111111-2222-4333-8444-555555555555"


@pytest.fixture
def matched_spot_profile(monkeypatch):
    """Clear only the already-covered Test-profile prerequisite."""
    import application.admin_api.command_service as command_service

    monkeypatch.setattr(
        command_service,
        "evaluate_spot_test_portfolio_binding",
        lambda **_kwargs: SpotPortfolioBindingEvidence(
            ready=True,
            blocker=None,
            expected_portfolio_id=_TEST_PORTFOLIO_ID,
            expected_portfolio_label="Test",
            expected_portfolio_type=EXPECTED_SPOT_PORTFOLIO_TYPE,
            observed_portfolio_id=_TEST_PORTFOLIO_ID,
            observed_portfolio_label="Test",
            observed_portfolio_type=EXPECTED_SPOT_PORTFOLIO_TYPE,
            can_view=True,
            can_trade=True,
        ),
    )


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


def _shared_service_response(
    *,
    accepted: bool,
    client_order_id: str,
    message: str,
    coinbase_order_id: str | None = None,
    submission_event_recorded: bool | None = None,
    audit_command: str | None = None,
    guard: dict | None = None,
    data=None,
):
    from core.enums import AdminApiCommandStatus

    return SimpleNamespace(
        status=(
            AdminApiCommandStatus.ACCEPTED
            if accepted
            else AdminApiCommandStatus.REJECTED
        ),
        message=message,
        client_order_id=client_order_id,
        coinbase_order_id=coinbase_order_id,
        submission_event_recorded=submission_event_recorded,
        audit_command=audit_command,
        guard=guard,
        data=data,
    )


def _place_order_message(
    order_configuration,
    side="BUY",
    *,
    manual_live_acknowledgement=True,
) -> str:
    return json.dumps({
        "type": "place_order",
        "params": {
            "product_id": "BTC-USDC",
            "side": side,
            "order_configuration": order_configuration,
            "manual_live_acknowledgement": manual_live_acknowledgement,
        },
    })


def _direct_spot_cap_policy(
    *,
    max_notional=1000.0,
    known_inventory=False,
) -> dict:
    policy = {
        "limits": [{
            "name": "direct_spot_cap",
            "product_type": ProductType.SPOT.value,
            ActionConditionType.MAX_NOTIONAL.value: max_notional,
            "phases": [ActionGuardPhase.PLANNING.value],
        }],
    }
    if known_inventory:
        policy[ActionConditionType.KNOWN_INVENTORY_AVAILABLE.value] = {
            "enabled": True,
            "phases": [ActionGuardPhase.PLANNING.value],
        }
    return policy


@pytest.mark.regression
def test_direct_spot_place_order_requires_manual_live_ack_before_rest(
    monkeypatch,
    matched_spot_profile,
):
    import dashboard_server

    ws = _make_websocket()
    rest_client = MagicMock()
    message = _place_order_message({
        "market_market_ioc": {
            "quote_size": "5",
        },
    }, manual_live_acknowledgement=False)

    with patch.object(dashboard_server, "REST_CLIENT_AVAILABLE", True), \
         patch.object(dashboard_server, "REST_CLIENT", rest_client), \
         patch.object(dashboard_server, "get_runtime_controller",
                      return_value=_admitting_controller()), \
         patch.object(dashboard_server, "add_log_entry"):
        _run(dashboard_server.handle_client_message(ws, message))

    payload = _sent_payload(ws)
    assert payload["type"] == "order_response"
    assert payload["status"] == "error"
    assert payload["guard"]["block_category"] == (
        ActionConditionType.MANUAL_LIVE_ACKNOWLEDGEMENT.value
    )
    assert payload["guard"]["manual_live_acknowledgement_required"] is True
    rest_client.create_order.assert_not_called()


@pytest.mark.regression
def test_direct_spot_place_order_requires_configured_notional_cap(
    monkeypatch,
    matched_spot_profile,
):
    import configuration
    import core.action_condition_guard as guard_module
    import dashboard_server

    monkeypatch.setattr(configuration, "ACTION_CONDITION_GUARDS", {})
    monkeypatch.setattr(guard_module, "rest_credentials_configured", lambda: False)
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
         patch.object(dashboard_server, "add_log_entry"):
        _run(dashboard_server.handle_client_message(ws, message))

    payload = _sent_payload(ws)
    assert payload["type"] == "order_response"
    assert payload["status"] == "error"
    assert payload["guard"]["block_category"] == (
        ActionConditionType.DIRECT_SPOT_CAP_REQUIRED.value
    )
    assert payload["guard"]["max_notional_cap_required"] is True
    rest_client.create_order.assert_not_called()


@pytest.mark.regression
def test_direct_spot_sell_requires_known_inventory_policy_before_rest(
    monkeypatch,
    matched_spot_profile,
):
    import configuration
    import core.action_condition_guard as guard_module
    import dashboard_server

    monkeypatch.setattr(
        configuration,
        "ACTION_CONDITION_GUARDS",
        _direct_spot_cap_policy(),
    )
    monkeypatch.setattr(guard_module, "rest_credentials_configured", lambda: False)
    ws = _make_websocket()
    rest_client = MagicMock()
    message = _place_order_message({
        "limit_limit_gtc": {
            "base_size": "0.001",
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
    assert payload["type"] == "order_response"
    assert payload["status"] == "error"
    assert payload["guard"]["block_category"] == (
        ActionConditionType.KNOWN_INVENTORY_AVAILABLE.value
    )
    assert payload["guard"]["known_inventory_available_required"] is True
    rest_client.create_order.assert_not_called()


@pytest.mark.regression
def test_direct_place_order_blocks_max_notional_before_rest(
    monkeypatch,
    matched_spot_profile,
):
    import configuration
    import dashboard_server

    monkeypatch.setattr(configuration, "ACTION_CONDITION_GUARDS", {
        "limits": [{
            "name": "direct_spot_cap",
            "product_id": "BTC-USDC",
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
    assert payload["guard"]["block_category"] == (
        ActionConditionType.MAX_NOTIONAL.value
    )
    rest_client.create_order.assert_not_called()


@pytest.mark.regression
def test_direct_place_order_blocks_spot_sell_wallet_before_rest(
    monkeypatch,
    matched_spot_profile,
):
    import configuration
    import core.action_condition_guard as guard_module
    import dashboard_server

    monkeypatch.setattr(
        configuration,
        "ACTION_CONDITION_GUARDS",
        _direct_spot_cap_policy(max_notional=200000.0, known_inventory=True),
    )
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
def test_direct_place_order_reports_known_inventory_guard_before_rest(
    monkeypatch,
    matched_spot_profile,
):
    import configuration
    import dashboard_server

    policy = _direct_spot_cap_policy(max_notional=20000.0, known_inventory=True)
    policy[ActionConditionType.WALLET_AVAILABLE.value] = {"enabled": False}
    monkeypatch.setattr(configuration, "ACTION_CONDITION_GUARDS", policy)
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
def test_direct_market_buy_quote_size_blocks_max_notional(
    monkeypatch,
    matched_spot_profile,
):
    import configuration
    import dashboard_server

    monkeypatch.setattr(configuration, "ACTION_CONDITION_GUARDS", {
        "limits": [{
            "name": "direct_quote_cap",
            "product_id": "BTC-USDC",
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
    assert payload["guard"]["block_category"] == (
        ActionConditionType.MAX_NOTIONAL.value
    )
    assert payload["guard"]["quote_size"] == 250.0
    rest_client.create_order.assert_not_called()


@pytest.mark.regression
def test_direct_market_buy_quote_size_blocks_below_quote_min_before_rest(
    monkeypatch,
    matched_spot_profile,
):
    import calculation.size_validation as size_validation
    import dashboard_server

    monkeypatch.setattr(size_validation, "PRODUCT_METADATA", {
        "BTC-USDC": {
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
def test_direct_place_order_forwards_and_renders_shared_success_client_order_id():
    import dashboard_server

    ws = _make_websocket()
    service = MagicMock()

    def accept(command):
        client_order_id = "generated-client-order-1"
        return _shared_service_response(
            accepted=True,
            client_order_id=client_order_id,
            message="Order accepted by shared command service",
            coinbase_order_id="exchange-1",
            submission_event_recorded=True,
            audit_command=(
                "python tools\\run_spot_direct_order_audit.py "
                f"--client-order-id {client_order_id}"
            ),
        )

    service.place_manual_order.side_effect = accept
    message = _place_order_message({
        "limit_limit_gtc": {
            "base_size": "0.02",
            "limit_price": "50.00",
        },
    })

    with patch.object(dashboard_server, "_dashboard_command_service",
                      return_value=service), \
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
    assert payload["audit_command"] == (
        "python tools\\run_spot_direct_order_audit.py "
        f"--client-order-id {payload['client_order_id']}"
    )
    service.place_manual_order.assert_called_once()
    forwarded = service.place_manual_order.call_args.args[0]
    assert forwarded.request.client_order_id is None
    assert payload["client_order_id"] == "generated-client-order-1"
    assert forwarded.request.product_id == "BTC-USDC"


@pytest.mark.regression
def test_direct_spot_place_order_renders_shared_durable_audit_rejection():
    import dashboard_server

    ws = _make_websocket()
    service = MagicMock()

    def reject(command):
        return _shared_service_response(
            accepted=False,
            client_order_id=command.request.client_order_id,
            message="Durable submission audit is required",
            guard={
                "block_category": ActionConditionType.DURABLE_AUDIT_AVAILABLE.value,
                "durable_audit_required": True,
            },
        )

    service.place_manual_order.side_effect = reject
    message = _place_order_message({
        "limit_limit_gtc": {
            "base_size": "0.02",
            "limit_price": "50.00",
        },
    })

    with patch.object(dashboard_server, "_dashboard_command_service",
                      return_value=service), \
         patch.object(dashboard_server, "get_runtime_controller",
                      return_value=_admitting_controller()), \
         patch.object(dashboard_server, "add_log_entry"):
        _run(dashboard_server.handle_client_message(ws, message))

    payload = _sent_payload(ws)
    assert payload["type"] == "order_response"
    assert payload["status"] == "error"
    assert payload["guard"]["block_category"] == (
        ActionConditionType.DURABLE_AUDIT_AVAILABLE.value
    )
    assert payload["guard"]["durable_audit_required"] is True
    service.place_manual_order.assert_called_once()


@pytest.mark.regression
def test_direct_place_order_renders_shared_normalized_exchange_evidence():
    import dashboard_server

    ws = _make_websocket()
    service = MagicMock()

    def accept(command):
        return _shared_service_response(
            accepted=True,
            client_order_id=command.request.client_order_id,
            message="Nested Coinbase response normalized by shared service",
            coinbase_order_id="exchange-nested-1",
        )

    service.place_manual_order.side_effect = accept
    message = _place_order_message({
        "limit_limit_gtc": {
            "base_size": "0.02",
            "limit_price": "50.00",
        },
    })

    with patch.object(dashboard_server, "_dashboard_command_service",
                      return_value=service), \
         patch.object(dashboard_server, "get_runtime_controller",
                      return_value=_admitting_controller()), \
         patch.object(dashboard_server, "add_log_entry"):
        _run(dashboard_server.handle_client_message(ws, message))

    payload = _sent_payload(ws)
    assert payload["status"] == "success"
    assert payload["order_id"] == "exchange-nested-1"
    service.place_manual_order.assert_called_once()


@pytest.mark.regression
def test_direct_place_order_size_validation_runs_before_action_guard(
    matched_spot_profile,
):
    import application.admin_api.command_service as command_service
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
         patch.object(command_service, "ActionConditionGuard", guard_cls), \
         patch.object(dashboard_server, "get_runtime_controller",
                      return_value=_admitting_controller()), \
         patch.object(dashboard_server, "add_log_entry"), \
         pytest.raises(OrderCreationError, match="Order rejected at boundary"):
        _run(dashboard_server.handle_client_message(ws, message))

    guard_cls.assert_not_called()
    rest_client.create_order.assert_not_called()


@pytest.mark.regression
def test_cancel_order_calls_cancel_order_with_client_order_id():
    import dashboard_server

    ws = _make_websocket()
    service = MagicMock()

    def accept(command):
        return _shared_service_response(
            accepted=True,
            client_order_id=command.client_order_id,
            message="Order cancellation confirmed by terminal readback",
            data={
                "cancellation_readback": {
                    "operator_identity_key": "client_order_id",
                    "terminal_status_proven": True,
                    "authoritative_status": "CANCELLED",
                }
            },
        )

    service.cancel_order_by_client_order_id.side_effect = accept
    message = json.dumps({
        "type": "cancel_order",
        "client_order_id": "client-order-1",
    })

    with patch.object(dashboard_server, "_dashboard_command_service",
                      return_value=service), \
         patch.object(dashboard_server, "get_runtime_controller",
                      return_value=_admitting_controller()), \
         patch.object(dashboard_server, "add_log_entry"):
        _run(dashboard_server.handle_client_message(ws, message))

    payload = _sent_payload(ws)
    assert payload["type"] == "cancel_response"
    assert payload["status"] == "success"
    assert payload["client_order_id"] == "client-order-1"
    assert payload["data"]["cancellation_readback"] == {
        "operator_identity_key": "client_order_id",
        "terminal_status_proven": True,
        "authoritative_status": "CANCELLED",
    }
    service.cancel_order_by_client_order_id.assert_called_once()
    forwarded = service.cancel_order_by_client_order_id.call_args.args[0]
    assert forwarded.client_order_id == "client-order-1"


@pytest.mark.regression
def test_cancel_order_surfaces_shared_unknown_result_as_error():
    import dashboard_server

    ws = _make_websocket()
    service = MagicMock()

    def reject(command):
        return _shared_service_response(
            accepted=False,
            client_order_id=command.client_order_id,
            message=(
                "Canonical client_order_id cancellation returned no explicit "
                "outcome; exchange-id fallback is forbidden."
            ),
            data={
                "cancellation_readback": {
                    "operator_identity_key": "client_order_id",
                    "canonical_cancel_attempted": True,
                    "fallback_attempted": False,
                    "terminal_status_proven": False,
                }
            },
        )

    service.cancel_order_by_client_order_id.side_effect = reject
    message = json.dumps({
        "type": "cancel_order",
        "client_order_id": "client-order-false",
    })

    with patch.object(dashboard_server, "_dashboard_command_service",
                      return_value=service), \
         patch.object(dashboard_server, "get_runtime_controller",
                      return_value=_admitting_controller()), \
         patch.object(dashboard_server, "add_log_entry"):
        _run(dashboard_server.handle_client_message(ws, message))

    payload = _sent_payload(ws)
    assert payload["type"] == "cancel_response"
    assert payload["status"] == "error"
    assert payload["client_order_id"] == "client-order-false"
    assert payload["data"]["cancellation_readback"]["fallback_attempted"] is False
    assert "no explicit outcome" in payload["message"]
    service.cancel_order_by_client_order_id.assert_called_once()


@pytest.mark.regression
def test_cancel_order_accepts_nested_params_client_order_id():
    import dashboard_server

    ws = _make_websocket()
    service = MagicMock()
    service.cancel_order_by_client_order_id.side_effect = lambda command: (
        _shared_service_response(
            accepted=True,
            client_order_id=command.client_order_id,
            message="Order cancellation confirmed by terminal readback",
            data={"cancellation_readback": {"terminal_status_proven": True}},
        )
    )
    message = json.dumps({
        "type": "cancel_order",
        "params": {"client_order_id": "client-order-params"},
    })

    with patch.object(dashboard_server, "_dashboard_command_service",
                      return_value=service), \
         patch.object(dashboard_server, "get_runtime_controller",
                      return_value=_admitting_controller()), \
         patch.object(dashboard_server, "add_log_entry"):
        _run(dashboard_server.handle_client_message(ws, message))

    payload = _sent_payload(ws)
    assert payload["status"] == "success"
    assert payload["client_order_id"] == "client-order-params"
    forwarded = service.cancel_order_by_client_order_id.call_args.args[0]
    assert forwarded.client_order_id == "client-order-params"


@pytest.mark.regression
def test_cancel_order_requires_client_order_id_before_rest():
    import dashboard_server

    ws = _make_websocket()
    rest_client = MagicMock()
    message = json.dumps({"type": "cancel_order"})

    with patch.object(dashboard_server, "REST_CLIENT_AVAILABLE", True), \
         patch.object(dashboard_server, "REST_CLIENT", rest_client), \
         patch.object(dashboard_server, "get_runtime_controller",
                      return_value=_admitting_controller()), \
         patch.object(dashboard_server, "add_log_entry"):
        _run(dashboard_server.handle_client_message(ws, message))

    payload = _sent_payload(ws)
    assert payload["type"] == "cancel_response"
    assert payload["status"] == "error"
    assert payload["message"] == (
        "Missing client_order_id; pass client_order_id, not order_id, "
        "to dashboard cancel_order."
    )
    rest_client.cancel_order.assert_not_called()


@pytest.mark.regression
def test_cancel_order_rejects_order_id_without_client_order_id():
    import dashboard_server

    ws = _make_websocket()
    rest_client = MagicMock()
    message = json.dumps({
        "type": "cancel_order",
        "order_id": "exchange-order-id",
    })

    with patch.object(dashboard_server, "REST_CLIENT_AVAILABLE", True), \
         patch.object(dashboard_server, "REST_CLIENT", rest_client), \
         patch.object(dashboard_server, "get_runtime_controller",
                      return_value=_admitting_controller()), \
         patch.object(dashboard_server, "add_log_entry"):
        _run(dashboard_server.handle_client_message(ws, message))

    payload = _sent_payload(ws)
    assert payload["type"] == "cancel_response"
    assert payload["status"] == "error"
    assert payload["message"] == (
        "Missing client_order_id; pass client_order_id, not order_id, "
        "to dashboard cancel_order."
    )
    rest_client.cancel_order.assert_not_called()
    rest_client.cancel_orders.assert_not_called()


@pytest.mark.regression
def test_request_spot_direct_order_audit_uses_client_order_id():
    import dashboard_server

    ws = _make_websocket()
    message = json.dumps({
        "type": "request_spot_direct_order_audit",
        "params": {"client_order_id": "client-order-audit-1"},
    })
    helper = MagicMock(return_value={
        "type": "spot_direct_order_audit",
        "status": "success",
        "client_order_id": "client-order-audit-1",
        "audit": {"client_order_id": "client-order-audit-1"},
    })

    with patch.object(
        dashboard_server,
        "_build_spot_direct_order_audit_payload",
        helper,
    ):
        _run(dashboard_server.handle_client_message(ws, message))

    payload = _sent_payload(ws)
    assert payload["type"] == "spot_direct_order_audit"
    assert payload["status"] == "success"
    assert payload["client_order_id"] == "client-order-audit-1"
    helper.assert_called_once_with(
        client_order_id="client-order-audit-1",
        include_events=True,
        include_fills=True,
        event_limit=100,
        fill_limit=1000,
    )


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
