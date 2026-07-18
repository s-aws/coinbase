"""Regression coverage for the source-disabled legacy dashboard mutations."""

from __future__ import annotations

import asyncio
import atexit
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.coinbase_execution_authority import (
    SOURCE_DISABLED_COINBASE_EXECUTION_ERROR,
)


_ASYNC_RUNNER: asyncio.Runner | None = None


def _make_websocket() -> MagicMock:
    websocket = MagicMock()
    websocket.send = AsyncMock()
    return websocket


def _run(coro):
    global _ASYNC_RUNNER
    if _ASYNC_RUNNER is None:
        _ASYNC_RUNNER = asyncio.Runner()
        atexit.register(_ASYNC_RUNNER.close)
    return _ASYNC_RUNNER.run(coro)


def _sent_payload(websocket: MagicMock) -> dict:
    assert websocket.send.await_args_list
    return json.loads(websocket.send.await_args_list[-1].args[0])


@pytest.mark.regression
@pytest.mark.parametrize(
    ("message", "response_type"),
    [
        (
            {
                "type": "place_order",
                "params": {
                    "product_id": "BTC-USDC",
                    "side": "BUY",
                    "order_configuration": {
                        "limit_limit_gtc": {
                            "base_size": "0.0001",
                            "limit_price": "10000",
                        }
                    },
                },
            },
            "place_order_response",
        ),
        (
            {
                "type": "cancel_order",
                "params": {"client_order_id": "client-order-id"},
            },
            "cancel_response",
        ),
        (
            {"type": "cancel_order", "order_id": "exchange-order-id"},
            "cancel_response",
        ),
        (
            {
                "type": "place_hotpoint_test_order",
                "order": {
                    "product_id": "BTC-USDC",
                    "side": "BUY",
                    "price": "10000",
                    "size": "0.0001",
                },
            },
            "place_hotpoint_test_order_response",
        ),
    ],
)
def test_legacy_dashboard_exchange_mutations_are_source_disabled_before_runtime(
    message: dict,
    response_type: str,
) -> None:
    import dashboard_server

    websocket = _make_websocket()
    rest_client = MagicMock()

    def unexpected_runtime_lookup():
        raise AssertionError("source-disabled mutation must not inspect runtime")

    with (
        patch.object(dashboard_server, "REST_CLIENT_AVAILABLE", True),
        patch.object(dashboard_server, "REST_CLIENT", rest_client),
        patch.object(
            dashboard_server,
            "get_runtime_controller",
            side_effect=unexpected_runtime_lookup,
        ),
        patch.object(dashboard_server, "add_log_entry") as add_log_entry,
    ):
        _run(
            dashboard_server.handle_client_message(
                websocket,
                json.dumps(message),
            )
        )

    payload = _sent_payload(websocket)
    assert payload == {
        "type": response_type,
        "status": "error",
        "success": False,
        "error": SOURCE_DISABLED_COINBASE_EXECUTION_ERROR,
        "message": (
            "Legacy dashboard exchange mutation is source-disabled; use the "
            "authenticated Admin API operator workflow."
        ),
    }
    assert rest_client.mock_calls == []
    add_log_entry.assert_called_once()


@pytest.mark.regression
def test_request_spot_direct_order_audit_uses_client_order_id() -> None:
    import dashboard_server

    websocket = _make_websocket()
    message = json.dumps(
        {
            "type": "request_spot_direct_order_audit",
            "params": {"client_order_id": "client-order-audit-1"},
        }
    )
    helper = MagicMock(
        return_value={
            "type": "spot_direct_order_audit",
            "status": "success",
            "client_order_id": "client-order-audit-1",
            "audit": {"client_order_id": "client-order-audit-1"},
        }
    )

    with patch.object(
        dashboard_server,
        "_build_spot_direct_order_audit_payload",
        helper,
    ):
        _run(dashboard_server.handle_client_message(websocket, message))

    payload = _sent_payload(websocket)
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
