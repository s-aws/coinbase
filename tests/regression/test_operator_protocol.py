"""Regression contracts for the versioned operator JSON-RPC boundary."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest

import dashboard_server
from core.enums import (
    EngineState,
    OperatorNotificationMethod,
    OperatorOutcome,
    OperatorRpcErrorCode,
    OperatorRpcMethod,
    OrderSide,
)
from core.execution_core import (
    ImportStealthOrdersResult,
    ImportedStealthOrderResult,
    OriginatingCommandResult,
)
from operator_api.protocol import (
    STEALTH_EXPORT_SCHEMA,
    STEALTH_EXPORT_VERSION,
    OperatorRpcError,
    decode_request,
    encode_notification,
    encode_success,
    load_protocol_schema,
)
from tests.regression.operator_rpc_test_support import rpc_request, rpc_result


pytestmark = pytest.mark.regression
REPO_ROOT = Path(__file__).resolve().parents[2]


def _error_for(raw_message: str) -> OperatorRpcError:
    with pytest.raises(OperatorRpcError) as raised:
        decode_request(raw_message)
    return raised.value


@pytest.mark.parametrize(
    ("raw_message", "expected_code"),
    [
        ("{", OperatorRpcErrorCode.PARSE_ERROR),
        (
            '{"jsonrpc":"2.0","id":"00000000-0000-4000-8000-000000000000",'
            '"method":"v1.runtime.shutdown","params":{"timeout_seconds":NaN}}',
            OperatorRpcErrorCode.PARSE_ERROR,
        ),
        (
            '{"jsonrpc":"2.0","id":"00000000-0000-4000-8000-000000000000",'
            '"method":"v1.runtime.shutdown","params":{"timeout_seconds":1e999}}',
            OperatorRpcErrorCode.PARSE_ERROR,
        ),
        ("[]", OperatorRpcErrorCode.INVALID_REQUEST),
        (
            json.dumps({"jsonrpc": "2.0", "method": "v1.runtime.status"}),
            OperatorRpcErrorCode.INVALID_REQUEST,
        ),
        (
            json.dumps({
                "jsonrpc": "2.0",
                "id": str(uuid4()).upper(),
                "method": "v1.runtime.status",
                "params": {},
            }),
            OperatorRpcErrorCode.INVALID_REQUEST,
        ),
    ],
)
def test_decoder_rejects_malformed_batch_and_client_notifications(
    raw_message,
    expected_code,
):
    assert _error_for(raw_message).code is expected_code


def test_invalid_correlation_id_is_never_reflected_as_a_response_id():
    invalid = _error_for(json.dumps({
        "jsonrpc": "1.0",
        "id": str(uuid4()).upper(),
        "method": "v1.runtime.status",
        "params": {},
    }))
    assert invalid.request_id is None


def test_encoder_rejects_non_finite_json_numbers():
    with pytest.raises(ValueError):
        encode_success(str(uuid4()), {"outcome": "succeeded", "value": float("inf")})


def test_decoder_rejects_unknown_method_and_invalid_method_params():
    request_id = str(uuid4())
    unknown = _error_for(json.dumps({
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "v1.unknown",
        "params": {},
    }))
    assert unknown.code is OperatorRpcErrorCode.METHOD_NOT_FOUND
    assert unknown.request_id == request_id

    invalid = _error_for(rpc_request(
        OperatorRpcMethod.STEALTH_CANCEL,
        {"stealth_order_id": "legacy-wire-name"},
        request_id=request_id,
    ))
    assert invalid.code is OperatorRpcErrorCode.INVALID_PARAMS
    assert invalid.request_id == request_id
    assert invalid.data["fields"]


def test_schema_enum_and_explicit_dispatch_have_the_same_method_inventory():
    expected = {method.value for method in OperatorRpcMethod}
    schema_methods = set(
        load_protocol_schema()["$defs"]["methodParams"]
    )
    schema_results = set(
        load_protocol_schema()["$defs"]["methodResults"]
    )
    assert schema_methods == expected
    assert schema_results == expected
    assert {method.value for method in dashboard_server._RPC_HANDLERS} == expected


def test_runtime_status_returns_one_correlated_terminal_response():
    websocket = Mock(send=AsyncMock())
    controller = Mock()
    controller.state = EngineState.PAUSED
    controller.is_admitting.return_value = False
    controller.is_stopping.return_value = False
    controller.startup_pause_pending.return_value = False
    controller.inflight_snapshot.return_value = {}
    controller.total_inflight.return_value = 0
    request_id = str(uuid4())

    with patch.object(
        dashboard_server,
        "get_runtime_controller",
        return_value=controller,
    ):
        asyncio.run(dashboard_server.handle_client_message(
            websocket,
            rpc_request(
                OperatorRpcMethod.RUNTIME_STATUS,
                request_id=request_id,
            ),
        ))

    websocket.send.assert_awaited_once()
    payload = json.loads(websocket.send.await_args.args[0])
    assert payload["id"] == request_id
    result = rpc_result(payload)
    assert result["outcome"] == OperatorOutcome.SUCCEEDED.value
    assert result["engine_state"] == EngineState.PAUSED.value


def test_unserializable_handler_result_returns_one_correlated_internal_error():
    websocket = Mock(send=AsyncMock())
    request_id = str(uuid4())
    handler = AsyncMock(return_value=dashboard_server._rpc_result({
        "value": float("inf"),
    }))

    with patch.dict(
        dashboard_server._RPC_HANDLERS,
        {OperatorRpcMethod.RUNTIME_STATUS: handler},
    ):
        asyncio.run(dashboard_server.handle_client_message(
            websocket,
            rpc_request(
                OperatorRpcMethod.RUNTIME_STATUS,
                request_id=request_id,
            ),
        ))

    websocket.send.assert_awaited_once()
    payload = json.loads(websocket.send.await_args.args[0])
    assert payload["id"] == request_id
    assert payload["error"]["code"] == OperatorRpcErrorCode.INTERNAL_ERROR


def test_server_notifications_are_named_and_never_have_correlation_ids():
    payload = json.loads(encode_notification(
        OperatorNotificationMethod.STEALTH_ORDERS_PROJECTION,
        {"orders": {}},
    ))
    assert payload == {
        "jsonrpc": "2.0",
        "method": "v1.projection.stealth_orders",
        "params": {"orders": {}},
    }
    assert "id" not in payload


def _export_manager():
    serialized = {
        "product_id": "BTC-USD",
        "side": "BUY",
        "total_size": 1.0,
        "limit_price": 100.0,
        "reveal_condition_json": {
            "type": "price",
            "price_threshold": 99.0,
            "direction": "below",
        },
        "follow_up_reveal_direction": "opposite",
        "target_movement": 0.002,
        "target_movement_type": "P",
        "allow_partial_fills": True,
        "enable_hotpoint_replication": True,
    }
    manager = Mock()
    manager.in_memory_orders = {
        "root-client-order": {
            "status": "HIDDEN",
            "parent_order_id": None,
        },
    }
    manager._serialize_order_for_json.return_value = serialized
    return manager


def test_export_v2_round_trips_hotpoint_replication_without_loss():
    websocket = Mock(send=AsyncMock())
    manager = _export_manager()
    bridge = Mock(stealth_manager=manager)

    with patch.object(dashboard_server, "stealth_order_bridge", bridge), patch(
        "database.order.get_parent_order",
        return_value={"enable_hotpoint_replication": True},
    ):
        asyncio.run(dashboard_server.handle_client_message(
            websocket,
            rpc_request(OperatorRpcMethod.STEALTH_EXPORT),
        ))

    export_result = rpc_result(json.loads(websocket.send.await_args.args[0]))
    document = export_result["document"]
    assert document["schema"] == STEALTH_EXPORT_SCHEMA
    assert document["version"] == STEALTH_EXPORT_VERSION
    assert document["orders"][0]["enable_hotpoint_replication"] is True

    imported = ImportedStealthOrderResult(
        requested_client_order_id="root-client-order",
        client_order_id="root-client-order",
        product_id="BTC-USD",
        side=OrderSide.BUY,
    )
    core = Mock()
    core.import_stealth_orders.return_value = OriginatingCommandResult(
        value=ImportStealthOrdersResult(orders=(imported,)),
    )
    import_websocket = Mock(send=AsyncMock())
    with patch.object(dashboard_server, "EXECUTION_CORE", core), patch.object(
        dashboard_server,
        "_broadcast_stealth_orders_projection",
        new=AsyncMock(),
    ):
        asyncio.run(dashboard_server.handle_client_message(
            import_websocket,
            rpc_request(
                OperatorRpcMethod.STEALTH_IMPORT,
                {"document": document},
            ),
        ))

    request = core.import_stealth_orders.call_args.args[0]
    assert request.orders[0].enable_hotpoint_replication is True
    import_result = rpc_result(
        json.loads(import_websocket.send.await_args.args[0])
    )
    assert import_result["warnings"] == []


def test_version_one_import_defaults_unrepresented_hotpoint_flag_with_warning():
    legacy_order = {
        "stealth_order_id": "legacy-client-order",
        "product_id": "BTC-USD",
        "side": "BUY",
        "total_size": 1.0,
        "limit_price": 100.0,
        "reveal_condition": {"type": "price", "price_threshold": 99.0},
        "enable_hotpoint_replication": True,
    }
    normalized = dashboard_server._normalize_import_order(
        legacy_order,
        document_version=1,
    )
    assert normalized["client_order_id"] == "legacy-client-order"
    assert normalized["enable_hotpoint_replication"] is False

    imported = ImportedStealthOrderResult(
        requested_client_order_id="legacy-client-order",
        client_order_id="legacy-client-order",
        product_id="BTC-USD",
        side=OrderSide.BUY,
    )
    core = Mock()
    core.import_stealth_orders.return_value = OriginatingCommandResult(
        value=ImportStealthOrdersResult(orders=(imported,)),
    )
    websocket = Mock(send=AsyncMock())
    with patch.object(dashboard_server, "EXECUTION_CORE", core), patch.object(
        dashboard_server,
        "_broadcast_stealth_orders_projection",
        new=AsyncMock(),
    ):
        asyncio.run(dashboard_server.handle_client_message(
            websocket,
            rpc_request(
                OperatorRpcMethod.STEALTH_IMPORT,
                {
                    "document": {
                        "type": "export_active_stealth_orders_response",
                        "status": "success",
                        "count": 1,
                        "orders": [legacy_order],
                    }
                },
            ),
        ))

    request = core.import_stealth_orders.call_args.args[0]
    assert request.orders[0].enable_hotpoint_replication is False
    result = rpc_result(json.loads(websocket.send.await_args.args[0]))
    assert result["warnings"]


def test_operator_projection_uses_explicit_client_order_id_names():
    projection = dashboard_server._normalize_stealth_orders_for_operator({
        "logical-id": {
            "stealth_order_id": "logical-id",
            "parent_order_id": "parent-id",
            "revealed_orders": [{"placed_order_id": "placement-id"}],
        }
    })
    order = projection["logical-id"]
    assert order["client_order_id"] == "logical-id"
    assert order["parent_client_order_id"] == "parent-id"
    assert order["revealed_orders"] == [{
        "placement_client_order_id": "placement-id",
    }]
    assert "stealth_order_id" not in order
    assert "parent_order_id" not in order


def test_operator_pages_contain_only_the_versioned_wire_contract():
    manager = (REPO_ROOT / "ui_stealth_orders_manager.html").read_text(
        encoding="utf-8"
    )
    span = (REPO_ROOT / "ui_order_span_builder.html").read_text(
        encoding="utf-8"
    )
    for page in (manager, span):
        assert "jsonrpc: '2.0'" in page
        assert "v1.session.bootstrap" in page
        assert "data.type" not in page
        assert "request_stealth_orders" not in page
        assert "order_update" not in page
        assert "stealth_order_update" not in page
    assert "client_order_id: newRpcRequestId()" in manager
    assert "sendRpc(RPC_METHODS.CREATE_SPAN" in span
