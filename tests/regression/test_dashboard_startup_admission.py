"""Dashboard admission remains fail-closed through runtime startup."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

import dashboard_server
from core.enums import (
    EngineState,
    OperatorErrorReason,
    OperatorOutcome,
    OperatorRpcErrorCode,
    OperatorRpcMethod,
)
from core.execution_core import AdmissionRejection, OriginatingCommandResult
from core.runtime_controller import INFLIGHT_APPLICATION_COMMAND
from core.runtime_controller import RuntimeController
from tests.regression.operator_rpc_test_support import (
    rpc_error,
    rpc_request,
    rpc_result,
)


pytestmark = pytest.mark.regression


def _websocket() -> Mock:
    websocket = Mock()
    websocket.send = AsyncMock()
    return websocket


def _payloads(websocket: Mock) -> list[dict]:
    return [json.loads(call.args[0]) for call in websocket.send.await_args_list]


def _run(coro):
    return asyncio.run(coro)


def test_originating_surface_contains_only_supported_strategy_commands() -> None:
    assert dashboard_server._ORIGINATING_METHODS == frozenset({
        OperatorRpcMethod.STEALTH_CREATE,
        OperatorRpcMethod.STEALTH_CREATE_SPAN,
        OperatorRpcMethod.STEALTH_REPRICE_NOW,
        OperatorRpcMethod.STEALTH_REHIDE,
        OperatorRpcMethod.STEALTH_MOVE_REVEALED,
        OperatorRpcMethod.STEALTH_IMPORT,
    })


def test_every_originating_message_is_rejected_while_starting() -> None:
    controller = RuntimeController()
    application_core = Mock(name="execution_core")
    rejection = OriginatingCommandResult(
        rejection=AdmissionRejection(
            state=EngineState.STARTING,
            category=INFLIGHT_APPLICATION_COMMAND,
        )
    )
    for method_name in (
        "create_stealth_order",
        "create_stealth_order_span",
        "import_stealth_orders",
        "rehide_stealth_order",
        "reprice_stealth_order_now",
        "move_revealed_stealth_order",
    ):
        getattr(application_core, method_name).return_value = rejection

    bridge = Mock(name="stealth_order_bridge")
    bridge.stealth_manager.in_memory_orders = {
        "sid-starting": {
            "status": "HIDDEN",
            "anchor_repricing_policy_json": {"enabled": True},
        }
    }
    params = {
        OperatorRpcMethod.STEALTH_CREATE: {
            "client_order_id": "create-starting",
            "product_id": "BTC-USD",
            "side": "BUY",
            "total_size": 1.0,
            "limit_price": 100.0,
            "reveal_condition": {
                "type": "time_delay",
                "delay_seconds": 0,
            },
        },
        OperatorRpcMethod.STEALTH_CREATE_SPAN: {
            "span_id": "span-starting",
            "product_id": "BTC-USD",
            "side": "BUY",
            "total_size": 1.0,
            "start_price": 100.0,
            "price_step": 0.0,
            "order_count": 1,
            "size_distribution": "equal",
            "creation_mode": "independent_parents",
            "reveal_condition": {"type": "time_delay", "delay_seconds": 0},
        },
        OperatorRpcMethod.STEALTH_IMPORT: {
            "document": {"version": 1, "count": 0, "orders": []},
        },
        OperatorRpcMethod.STEALTH_REHIDE: {
            "client_order_id": "sid-starting",
        },
        OperatorRpcMethod.STEALTH_REPRICE_NOW: {
            "client_order_id": "sid-starting",
        },
        OperatorRpcMethod.STEALTH_MOVE_REVEALED: {
            "client_order_id": "sid-starting",
            "new_limit_price": 101.0,
        },
    }

    async def exercise() -> None:
        for method in sorted(
            dashboard_server._ORIGINATING_METHODS,
            key=lambda item: item.value,
        ):
            websocket = _websocket()
            await dashboard_server.handle_client_message(
                websocket,
                rpc_request(method, params[method]),
            )
            payload = _payloads(websocket)[0]
            error = rpc_error(payload)
            assert error["code"] == int(
                OperatorRpcErrorCode.ENGINE_NOT_ADMITTING
            )
            assert error["message"] == (
                "Engine startup is still completing; new orders are "
                "not being accepted yet."
            )
            assert error["data"]["reason"] == (
                OperatorErrorReason.ENGINE_NOT_ADMITTING.value
            )
            assert error["data"]["engine_state"] == EngineState.STARTING.value

    with patch.object(
        dashboard_server,
        "get_runtime_controller",
        return_value=controller,
    ), patch.object(
        dashboard_server,
        "EXECUTION_CORE",
        application_core,
    ), patch.object(
        dashboard_server,
        "stealth_order_bridge",
        bridge,
    ), patch.object(dashboard_server, "add_log_entry"):
        _run(exercise())


def test_admin_pause_is_visible_and_sticky_during_startup() -> None:
    controller = RuntimeController()
    status_ws = _websocket()
    pause_ws = _websocket()
    resume_ws = _websocket()

    async def exercise() -> None:
        await dashboard_server.handle_client_message(
            status_ws,
            rpc_request(OperatorRpcMethod.RUNTIME_STATUS),
        )
        await dashboard_server.handle_client_message(
            pause_ws,
            rpc_request(OperatorRpcMethod.RUNTIME_PAUSE),
        )
        await dashboard_server.handle_client_message(
            resume_ws,
            rpc_request(OperatorRpcMethod.RUNTIME_RESUME),
        )

    with patch.object(
        dashboard_server,
        "get_runtime_controller",
        return_value=controller,
    ), patch.object(dashboard_server, "add_log_entry"):
        _run(exercise())

    status = rpc_result(_payloads(status_ws)[0])
    assert status["engine_state"] == EngineState.STARTING.value
    assert status["is_admitting"] is False
    assert status["startup_pause_pending"] is False

    pause = rpc_result(_payloads(pause_ws)[0])
    assert pause == {
        "changed": True,
        "engine_state": EngineState.STARTING.value,
        "startup_pause_pending": True,
        "outcome": OperatorOutcome.SUCCEEDED.value,
    }
    assert controller.state is EngineState.STARTING
    assert controller.startup_pause_pending() is True

    resume = rpc_result(_payloads(resume_ws)[0])
    assert resume == {
        "changed": False,
        "engine_state": EngineState.STARTING.value,
        "startup_pause_pending": True,
        "outcome": OperatorOutcome.SUCCEEDED.value,
    }
    assert controller.complete_startup() is True
    assert controller.state is EngineState.PAUSED
    assert controller.is_admitting() is False


def test_admin_shutdown_closes_startup_before_acknowledging() -> None:
    controller = RuntimeController()
    websocket = _websocket()
    drain_thread = Mock(name="drain_thread")
    thread_factory = Mock(name="Thread", return_value=drain_thread)

    async def assert_closed_before_send(_payload: str) -> None:
        assert controller.state is EngineState.DRAINING
        assert controller.is_admitting() is False
        drain_thread.start.assert_called_once_with()

    websocket.send.side_effect = assert_closed_before_send

    with patch.object(
        dashboard_server,
        "get_runtime_controller",
        return_value=controller,
    ), patch.object(
        dashboard_server,
        "Thread",
        thread_factory,
    ), patch.object(dashboard_server, "add_log_entry"):
        _run(
            dashboard_server.handle_client_message(
                websocket,
                rpc_request(
                    OperatorRpcMethod.RUNTIME_SHUTDOWN,
                    {"timeout_seconds": 5.0},
                ),
            )
        )

    result = rpc_result(_payloads(websocket)[0])
    assert result == {
        "accepted": True,
        "timeout_seconds": 5.0,
        "engine_state_before": EngineState.STARTING.value,
        "outcome": OperatorOutcome.ACCEPTED_PENDING.value,
    }
    assert controller.state is EngineState.DRAINING
    thread_factory.assert_called_once()
    drain_thread.start.assert_called_once_with()


def test_admin_shutdown_starts_cleanup_even_if_acknowledgement_fails() -> None:
    controller = RuntimeController()
    websocket = _websocket()
    websocket.send.side_effect = RuntimeError("dashboard disconnected")
    drain_thread = Mock(name="drain_thread")

    with patch.object(
        dashboard_server,
        "get_runtime_controller",
        return_value=controller,
    ), patch.object(
        dashboard_server,
        "Thread",
        return_value=drain_thread,
    ), patch.object(dashboard_server, "add_log_entry"):
        with pytest.raises(RuntimeError, match="dashboard disconnected"):
            _run(
                dashboard_server.handle_client_message(
                    websocket,
                    rpc_request(OperatorRpcMethod.RUNTIME_SHUTDOWN),
                )
            )

    assert controller.state is EngineState.DRAINING
    drain_thread.start.assert_called_once_with()


def test_admin_shutdown_drains_synchronously_if_worker_cannot_start() -> None:
    controller = RuntimeController()
    websocket = _websocket()
    stop_hook = Mock(name="stop_hook")
    controller.register_stop_hook("owned-component", stop_hook)
    drain_thread = Mock(name="drain_thread")
    drain_thread.start.side_effect = RuntimeError("cannot create thread")

    with patch.object(
        dashboard_server,
        "get_runtime_controller",
        return_value=controller,
    ), patch.object(
        dashboard_server,
        "Thread",
        return_value=drain_thread,
    ), patch.object(dashboard_server, "add_log_entry"):
        _run(
            dashboard_server.handle_client_message(
                websocket,
                rpc_request(OperatorRpcMethod.RUNTIME_SHUTDOWN),
            )
        )

    drain_thread.start.assert_called_once_with()
    stop_hook.assert_called_once_with()
    assert controller.state is EngineState.STOPPED


def test_admin_shutdown_drains_synchronously_if_worker_cannot_be_created() -> None:
    controller = RuntimeController()
    websocket = _websocket()
    stop_hook = Mock(name="stop_hook")
    controller.register_stop_hook("owned-component", stop_hook)

    with patch.object(
        dashboard_server,
        "get_runtime_controller",
        return_value=controller,
    ), patch.object(
        dashboard_server,
        "Thread",
        side_effect=RuntimeError("cannot construct thread"),
    ), patch.object(dashboard_server, "add_log_entry"):
        _run(
            dashboard_server.handle_client_message(
                websocket,
                rpc_request(OperatorRpcMethod.RUNTIME_SHUTDOWN),
            )
        )

    stop_hook.assert_called_once_with()
    assert controller.state is EngineState.STOPPED


@pytest.mark.parametrize(
    "timeout",
    ("nan", "inf", "1e308", "-1", True, "not-a-number"),
)
def test_admin_shutdown_rejects_invalid_timeout_without_closing_runtime(
    timeout,
) -> None:
    controller = RuntimeController()
    websocket = _websocket()

    with patch.object(
        dashboard_server,
        "get_runtime_controller",
        return_value=controller,
    ), patch.object(dashboard_server, "Thread") as thread_factory, patch.object(
        dashboard_server,
        "add_log_entry",
    ):
        _run(
            dashboard_server.handle_client_message(
                websocket,
                rpc_request(
                    OperatorRpcMethod.RUNTIME_SHUTDOWN,
                    {"timeout_seconds": timeout},
                ),
            )
        )

    error = rpc_error(_payloads(websocket)[0])
    assert error["code"] in {
        int(OperatorRpcErrorCode.INVALID_PARAMS),
        int(OperatorRpcErrorCode.APPLICATION_REJECTED),
    }
    assert error["data"]["reason"] == OperatorErrorReason.INVALID_PARAMS.value
    assert controller.state is EngineState.STARTING
    thread_factory.assert_not_called()


def test_stealth_manager_resume_control_is_fail_closed() -> None:
    html = (
        Path(__file__).resolve().parents[2] / "ui_stealth_orders_manager.html"
    ).read_text(encoding="utf-8")

    button = html[
        html.index('id="resume-engine-button"'):
        html.index('>Resume Engine</button>')
    ]
    controls = html[
        html.index("function updateEngineControls(engineState)"):
        html.index("function formatPercent(")
    ]
    websocket_handler = html[
        html.index("ws.onopen = () => {"):
        html.index("ws.onclose = () => {")
    ]

    assert "disabled" in button
    assert "normalizedState === 'PAUSED'" in controls
    assert "resumeButton.disabled = !canResume;" in controls
    assert "Resume the engine and enable new order placement?" in controls
    assert "sendRpc(RPC_METHODS.RUNTIME_RESUME)" in controls
    assert "sendRpc(RPC_METHODS.BOOTSTRAP);" in websocket_handler
    assert "message.jsonrpc !== '2.0'" in websocket_handler
    assert "pendingRpcRequests.get(message.id)" in websocket_handler
    assert "data.type" not in websocket_handler
