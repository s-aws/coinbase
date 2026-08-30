"""Dashboard admission remains fail-closed through runtime startup."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

import dashboard_server
from core.enums import EngineState
from core.runtime_controller import RuntimeController


pytestmark = pytest.mark.regression


def _websocket() -> Mock:
    websocket = Mock()
    websocket.send = AsyncMock()
    return websocket


def _payloads(websocket: Mock) -> list[dict]:
    return [json.loads(call.args[0]) for call in websocket.send.await_args_list]


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def test_every_originating_message_is_rejected_while_starting() -> None:
    controller = RuntimeController()

    async def exercise() -> None:
        for msg_type in sorted(dashboard_server._ORIGINATING_MSG_TYPES):
            websocket = _websocket()
            await dashboard_server.handle_client_message(
                websocket,
                json.dumps({"type": msg_type}),
            )
            assert _payloads(websocket) == [
                {
                    "type": "admission_rejected",
                    "rejected_type": msg_type,
                    "engine_state": EngineState.STARTING.value,
                    "message": (
                        "Engine startup is still completing; new orders are "
                        "not being accepted yet."
                    ),
                }
            ]

    with patch.object(
        dashboard_server,
        "get_runtime_controller",
        return_value=controller,
    ), patch.object(dashboard_server, "add_log_entry"):
        _run(exercise())


def test_hotpoint_test_order_cannot_preinsert_or_submit_while_starting() -> None:
    controller = RuntimeController()
    websocket = _websocket()
    parent_insert = Mock(name="insert_order_parent")
    rest_client = Mock(name="rest_client")
    message = json.dumps(
        {
            "type": "place_hotpoint_test_order",
            "order": {
                "product_id": "BTC-USDC",
                "side": "BUY",
                "price": 100.0,
                "size": 0.001,
            },
        }
    )

    assert "place_hotpoint_test_order" in dashboard_server._ORIGINATING_MSG_TYPES
    with patch.object(
        dashboard_server,
        "get_runtime_controller",
        return_value=controller,
    ), patch.object(
        dashboard_server,
        "REST_CLIENT",
        rest_client,
    ), patch(
        "database.order.insert_order_parent",
        parent_insert,
    ), patch.object(dashboard_server, "add_log_entry"):
        _run(dashboard_server.handle_client_message(websocket, message))

    assert _payloads(websocket)[0]["type"] == "admission_rejected"
    parent_insert.assert_not_called()
    rest_client.limit_order_gtc.assert_not_called()


def test_admin_pause_is_visible_and_sticky_during_startup() -> None:
    controller = RuntimeController()
    status_ws = _websocket()
    pause_ws = _websocket()
    resume_ws = _websocket()

    async def exercise() -> None:
        await dashboard_server.handle_client_message(
            status_ws,
            json.dumps({"type": "admin_status"}),
        )
        await dashboard_server.handle_client_message(
            pause_ws,
            json.dumps({"type": "admin_pause"}),
        )
        await dashboard_server.handle_client_message(
            resume_ws,
            json.dumps({"type": "admin_resume"}),
        )

    with patch.object(
        dashboard_server,
        "get_runtime_controller",
        return_value=controller,
    ), patch.object(dashboard_server, "add_log_entry"):
        _run(exercise())

    status = _payloads(status_ws)[0]
    assert status["engine_state"] == EngineState.STARTING.value
    assert status["is_admitting"] is False
    assert status["startup_pause_pending"] is False

    pause = _payloads(pause_ws)[0]
    assert pause == {
        "type": "admin_pause_response",
        "changed": True,
        "engine_state": EngineState.STARTING.value,
        "startup_pause_pending": True,
    }
    assert controller.state is EngineState.STARTING
    assert controller.startup_pause_pending() is True

    resume = _payloads(resume_ws)[0]
    assert resume == {
        "type": "admin_resume_response",
        "changed": False,
        "engine_state": EngineState.STARTING.value,
        "startup_pause_pending": True,
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
                json.dumps(
                    {
                        "type": "admin_shutdown",
                        "timeout_seconds": 5.0,
                    }
                ),
            )
        )

    assert _payloads(websocket) == [
        {
            "type": "admin_shutdown_response",
            "accepted": True,
            "timeout_seconds": 5.0,
            "engine_state_before": EngineState.STARTING.value,
        }
    ]
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
                    json.dumps({"type": "admin_shutdown"}),
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
                json.dumps({"type": "admin_shutdown"}),
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
                json.dumps({"type": "admin_shutdown"}),
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
                json.dumps({
                    "type": "admin_shutdown",
                    "timeout_seconds": timeout,
                }),
            )
        )

    assert _payloads(websocket) == [{
        "type": "admin_shutdown_response",
        "accepted": False,
        "engine_state_before": EngineState.STARTING.value,
        "message": (
            "drain timeout must be a finite non-negative number within the "
            "platform wait limit"
        ),
    }]
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
    assert "ws.send(JSON.stringify({ type: 'admin_resume' }));" in controls
    assert 'type: "admin_status"' in websocket_handler
    assert 'data.type === "admin_status_response"' in websocket_handler
    assert 'data.type === "admin_resume_response"' in websocket_handler
