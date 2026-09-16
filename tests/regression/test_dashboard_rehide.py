"""Manual Rehide uses the bridge and reports intent, never inferred exchange truth."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from unittest.mock import AsyncMock, Mock, call, patch

import pytest

import dashboard_server
from core.enums import EngineState, StealthOrderStatus
from core.runtime_controller import EngineNotAdmittingError


pytestmark = pytest.mark.regression
STEALTH_ID = "cb95208b-31f6-46c6-8aeb-78390489ec86"


def _invoke(bridge, *, state=EngineState.RUNNING, stealth_id=STEALTH_ID):
    websocket = Mock()
    websocket.send = AsyncMock()
    controller = Mock()
    controller.state = state
    controller.is_admitting.return_value = state is EngineState.RUNNING
    cache = {
        "stealth_orders": {
            STEALTH_ID: {
                "stealth_order_id": STEALTH_ID,
                "status": StealthOrderStatus.REVEALED.value,
                "limit_price": 100,
                "parent_order_id": "49c491ea-a9a5-4a04-a333-095417811778",
            },
        },
    }
    original = deepcopy(cache)
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    with (
        patch.object(dashboard_server, "stealth_order_bridge", bridge),
        patch.object(dashboard_server, "get_runtime_controller", return_value=controller),
        patch.object(dashboard_server, "engine_state", cache),
        patch.object(dashboard_server, "add_log_entry"),
    ):
        loop.run_until_complete(
            dashboard_server.handle_client_message(
                websocket,
                json.dumps({"type": "rehide_stealth_order", "stealth_order_id": stealth_id}),
            )
        )
    assert cache == original, "The command handler must not infer HIDDEN or change cached identity"
    responses = [json.loads(item.args[0]) for item in websocket.send.await_args_list]
    assert len(responses) == 1
    return responses[0]


def test_rehide_acceptance_is_pending_intent_and_uses_bridge_only():
    bridge = Mock()
    bridge.rehide_stealth_order.return_value = True

    response = _invoke(bridge)

    assert bridge.mock_calls == [call.rehide_stealth_order(STEALTH_ID)]
    assert response["type"] == "stealth_order_rehide_result"
    assert response["stealth_order_id"] == STEALTH_ID
    assert response["accepted"] is True
    assert "pending" in response["message"].lower()
    assert "reveal again" in response["message"].lower()
    assert "status" not in response
    assert "error" not in response


def test_rehide_false_result_is_not_reported_as_accepted():
    bridge = Mock()
    bridge.rehide_stealth_order.return_value = False

    response = _invoke(bridge)

    bridge.rehide_stealth_order.assert_called_once_with(STEALTH_ID)
    assert response["type"] == "stealth_order_rehide_result"
    assert response["accepted"] is False
    assert "not accepted" in response["message"].lower()
    assert response["error"]


@pytest.mark.parametrize("stealth_id", [None, "", "   ", 123, {}, []])
def test_rehide_rejects_invalid_identity_before_bridge_call(stealth_id):
    bridge = Mock()

    response = _invoke(bridge, stealth_id=stealth_id)

    assert bridge.mock_calls == []
    assert response["type"] == "stealth_order_rehide_result"
    assert response["accepted"] is False
    assert "stealth_order_id" in response["error"]


def test_rehide_rejects_missing_bridge():
    response = _invoke(None)

    assert response["accepted"] is False
    assert "not initialized" in response["error"]


@pytest.mark.parametrize(
    "error",
    [
        ValueError("Only zero-fill revealed orders are eligible"),
        RuntimeError("Stealth bridge startup is not ready"),
        RuntimeError("Failed to persist rehide intent"),
        EngineNotAdmittingError(EngineState.PAUSED, "stealth_rehide"),
    ],
)
def test_rehide_validation_persistence_readiness_and_admission_races_are_rejections(error):
    bridge = Mock()
    bridge.rehide_stealth_order.side_effect = error

    response = _invoke(bridge)

    bridge.rehide_stealth_order.assert_called_once_with(STEALTH_ID)
    assert response["type"] == "stealth_order_rehide_result"
    assert response["stealth_order_id"] == STEALTH_ID
    assert response["accepted"] is False
    assert response["error"] == str(error)


@pytest.mark.parametrize(
    "state",
    [EngineState.STARTING, EngineState.PAUSING, EngineState.PAUSED, EngineState.DRAINING, EngineState.STOPPED],
)
def test_rehide_is_originating_work_and_cannot_run_outside_running(state):
    bridge = Mock()
    assert "rehide_stealth_order" in dashboard_server._ORIGINATING_MSG_TYPES

    response = _invoke(bridge, state=state)

    assert response["type"] == "admission_rejected"
    assert response["rejected_type"] == "rehide_stealth_order"
    assert response["engine_state"] == state.value
    assert bridge.mock_calls == []
