"""Manual Rehide uses the bridge and reports intent, never inferred exchange truth."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from unittest.mock import AsyncMock, Mock, call, patch

import pytest

import dashboard_server
from core.enums import (
    EngineState,
    OperatorErrorReason,
    OperatorOutcome,
    OperatorRpcErrorCode,
    OperatorRpcMethod,
    StealthOrderStatus,
)
from core.execution_core import AdmissionRejection, OriginatingCommandResult
from core.runtime_controller import EngineNotAdmittingError
from core.runtime_controller import INFLIGHT_APPLICATION_COMMAND
from tests.regression.operator_rpc_test_support import (
    rpc_error,
    rpc_request,
    rpc_result,
)


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
    application_core = None
    if bridge is not None:
        application_core = Mock(name="execution_core")
        if state is EngineState.RUNNING:
            application_core.rehide_stealth_order.side_effect = (
                lambda request: OriginatingCommandResult(
                    value=bridge.rehide_stealth_order(
                        request.client_order_id
                    )
                )
            )
        else:
            application_core.rehide_stealth_order.return_value = (
                OriginatingCommandResult(
                    rejection=AdmissionRejection(
                        state=state,
                        category=INFLIGHT_APPLICATION_COMMAND,
                    )
                )
            )
    with (
        patch.object(dashboard_server, "stealth_order_bridge", bridge),
        patch.object(dashboard_server, "EXECUTION_CORE", application_core),
        patch.object(dashboard_server, "get_runtime_controller", return_value=controller),
        patch.object(dashboard_server, "engine_state", cache),
        patch.object(dashboard_server, "add_log_entry"),
    ):
        asyncio.run(
            dashboard_server.handle_client_message(
                websocket,
                rpc_request(
                    OperatorRpcMethod.STEALTH_REHIDE,
                    {"client_order_id": stealth_id},
                ),
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
    result = rpc_result(response)
    assert result["client_order_id"] == STEALTH_ID
    assert result["accepted"] is True
    assert result["outcome"] == OperatorOutcome.ACCEPTED_PENDING.value
    assert "pending" in result["message"].lower()
    assert "reveal again" in result["message"].lower()
    assert "status" not in result


def test_rehide_false_result_is_not_reported_as_accepted():
    bridge = Mock()
    bridge.rehide_stealth_order.return_value = False

    response = _invoke(bridge)

    bridge.rehide_stealth_order.assert_called_once_with(STEALTH_ID)
    error = rpc_error(response)
    assert error["code"] == int(OperatorRpcErrorCode.APPLICATION_REJECTED)
    assert "not accepted" in error["message"].lower()
    assert error["data"]["client_order_id"] == STEALTH_ID


@pytest.mark.parametrize("stealth_id", [None, "", "   ", 123, {}, []])
def test_rehide_rejects_invalid_identity_before_bridge_call(stealth_id):
    bridge = Mock()

    response = _invoke(bridge, stealth_id=stealth_id)

    assert bridge.mock_calls == []
    error = rpc_error(response)
    assert error["code"] == int(OperatorRpcErrorCode.INVALID_PARAMS)
    assert error["data"]["reason"] == OperatorErrorReason.INVALID_PARAMS.value


def test_rehide_rejects_missing_bridge():
    response = _invoke(None)

    error = rpc_error(response)
    assert error["code"] == int(OperatorRpcErrorCode.APPLICATION_FAILED)
    assert "not initialized" in error["message"]


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
    rpc_failure = rpc_error(response)
    assert rpc_failure["code"] == int(OperatorRpcErrorCode.APPLICATION_REJECTED)
    assert rpc_failure["data"]["client_order_id"] == STEALTH_ID
    assert str(error) in rpc_failure["message"]


@pytest.mark.parametrize(
    "state",
    [EngineState.STARTING, EngineState.PAUSING, EngineState.PAUSED, EngineState.DRAINING, EngineState.STOPPED],
)
def test_rehide_is_originating_work_and_cannot_run_outside_running(state):
    bridge = Mock()
    assert OperatorRpcMethod.STEALTH_REHIDE in dashboard_server._ORIGINATING_METHODS

    response = _invoke(bridge, state=state)

    error = rpc_error(response)
    assert error["code"] == int(OperatorRpcErrorCode.ENGINE_NOT_ADMITTING)
    assert error["data"]["engine_state"] == state.value
    assert bridge.mock_calls == []
