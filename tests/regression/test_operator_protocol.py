"""Regression contracts for the versioned operator JSON-RPC boundary."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker

import dashboard_server
from core.enums import (
    EngineState,
    FollowUpRevealDirection,
    OperatorErrorReason,
    OperatorNotificationMethod,
    OperatorOutcome,
    OperatorRpcErrorCode,
    OperatorRpcMethod,
    OrderSide,
    RepricingReferenceSource,
    RevealPricingPolicy,
    StealthMoveReason,
    StealthOrderStatus,
    StealthSpanCreationMode,
    StealthSpanOrderResultStatus,
    StealthSpanResultStatus,
    StealthSpanSizeDistribution,
    TargetMovementType,
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
    encode_error,
    encode_notification,
    encode_success,
    load_protocol_schema,
    validate_method_result,
    validate_notification_params,
)
from tests.regression.operator_rpc_test_support import rpc_request, rpc_result


pytestmark = pytest.mark.regression
REPO_ROOT = Path(__file__).resolve().parents[2]
TIMESTAMP = "2026-11-27T12:00:00+00:00"


def _runtime_status():
    return {
        "engine_state": EngineState.PAUSED.value,
        "is_admitting": False,
        "is_stopping": False,
        "startup_pause_pending": False,
        "inflight": {},
        "total_inflight": 0,
        "timestamp": TIMESTAMP,
    }


def _repricing_stats():
    return {
        "active_repricing_count": 0,
        "total_reprices_executed": 0,
        "breakdown_by_source": {
            "last_trade": 0,
            "midpoint": 0,
            "top_of_book": 0,
        },
    }


def _operator_order():
    return {
        "client_order_id": "logical-order",
        "parent_client_order_id": None,
        "product_id": "BTC-USD",
        "side": OrderSide.BUY.value,
        "total_size": 1.0,
        "limit_price": 100.0,
        "revealed_size": 0.0,
        "remaining_size": 1.0,
        "executed_size": 0.0,
        "status": StealthOrderStatus.HIDDEN.value,
        "visibility_score": 0.0,
        "reveal_condition_type": "price",
        "reveal_condition_json": {
            "type": "price",
            "price_threshold": 99.0,
        },
        "reveal_pricing_policy": RevealPricingPolicy.CONFIGURED_LIMIT.value,
        "follow_up_reveal_direction": FollowUpRevealDirection.OPPOSITE.value,
        "sizing_strategy_json": {"type": "fixed"},
        "reason": None,
        "notes": None,
        "revealed_orders": [],
        "anchor_repricing_policy_json": {},
        "anchor_repricing_state_json": {},
        "created_at": TIMESTAMP,
        "updated_at": TIMESTAMP,
        "condition_first_met_at": None,
        "condition_confirmed_at": None,
        "last_placement_at": None,
        "failure_reason": None,
        "allow_partial_fills": True,
        "max_order_replacements": 3,
        "target_movement": 0.002,
        "target_movement_type": TargetMovementType.PERCENTAGE.value,
    }


def _stealth_projection():
    return {
        "orders": {"logical-order": _operator_order()},
        "repricing_stats": _repricing_stats(),
        "timestamp": TIMESTAMP,
    }


def _dashboard_engine_status():
    return {
        "running": False,
        "threads_active": 0,
        "event_queue_depth": 0,
        "taker_fee_rate": None,
        "effective_fee_rate": None,
        "target_movement_factor": None,
        "fee_regime_factor": None,
        "volume_ratio": None,
        "overnight_margin_active": None,
        "margin_window_type": None,
        "last_update": None,
        "user_feed": {"processed": 0},
        **_runtime_status(),
    }


def _dashboard_state():
    return {
        "orders": {
            "exchange-order": {
                "client_order_id": "logical-order",
                "status": "OPEN",
            }
        },
        "positions": {"BTC-USD": {"quantity": 1.0}},
        "stealth_orders": {"logical-order": _operator_order()},
        "engine_status": _dashboard_engine_status(),
        "logs": [{
            "timestamp": TIMESTAMP,
            "level": "INFO",
            "message": "Engine paused",
            "context": {},
        }],
        "market_metrics": {
            "BTC-USD": {
                "price": 100.0,
                "as_of": 1.0,
                "windows": [{"minutes": 1, "avg": 100.0, "delta_pct": 0.0}],
            }
        },
    }


def _product_catalog():
    return {
        "derivatives": [],
        "spot": ["BTC-USD"],
        "metadata": {
            "BTC-USD": {
                "type": "SPOT",
                "base_currency": "BTC",
                "quote_currency": "USD",
                "base_increment": "0.00000001",
                "quote_increment": "0.01",
                "price_increment": "0.01",
                "base_min_size": "0.00000001",
                "quote_min_size": "1",
                "display_name": "BTC-USD",
                "status": "online",
                "mid_price": None,
                "trading_disabled": False,
                "contract_size": None,
                "expiry": None,
            }
        },
    }


def _parent_order_record():
    return {
        "id": 1,
        "target_movement": 0.002,
        "target_movement_type": TargetMovementType.PERCENTAGE.value,
        "max_order_replacement": 3,
        "current_order_replacement": 0,
        "client_order_id": "logical-order",
        "product_id": "BTC-USD",
        "side": OrderSide.BUY.value,
        "size": 1.0,
        "price": 100.0,
        "status": "OPEN",
        "parent_client_order_id": None,
        "execution_owner_client_order_id": "logical-order",
        "allow_partial_fills": True,
        "enable_hotpoint_replication": False,
        "auto_placed_by_hotpoint": False,
        "externally_created": False,
        "created_at": TIMESTAMP,
    }


def _result_fixtures():
    runtime_status = _runtime_status()
    stealth_projection = _stealth_projection()
    create_order = {
        "client_order_id": "logical-order",
        "product_id": "BTC-USD",
        "side": "BUY",
        "total_size": 1.0,
        "limit_price": 100.0,
        "reveal_condition": {"type": "price", "price_threshold": 99.0},
    }
    return {
        OperatorRpcMethod.SESSION_BOOTSTRAP: {
            "outcome": "succeeded",
            "protocol_version": 1,
            "server_time": TIMESTAMP,
            "capabilities": {
                "methods": [method.value for method in OperatorRpcMethod],
                "notifications": [
                    method.value for method in OperatorNotificationMethod
                ],
                "client_notifications": False,
                "batch_requests": False,
                "generic_idempotent_replay": False,
            },
            "runtime": runtime_status,
            "products": _product_catalog(),
            "stealth_orders": stealth_projection,
            "dashboard_state": _dashboard_state(),
        },
        OperatorRpcMethod.RUNTIME_STATUS: {
            "outcome": "succeeded",
            **runtime_status,
        },
        OperatorRpcMethod.RUNTIME_PAUSE: {
            "outcome": "succeeded",
            "changed": True,
            "engine_state": "PAUSED",
            "startup_pause_pending": False,
        },
        OperatorRpcMethod.RUNTIME_RESUME: {
            "outcome": "succeeded",
            "changed": True,
            "engine_state": "RUNNING",
            "startup_pause_pending": False,
        },
        OperatorRpcMethod.RUNTIME_SHUTDOWN: {
            "outcome": "accepted_pending",
            "accepted": True,
            "timeout_seconds": 30.0,
            "engine_state_before": "PAUSED",
        },
        OperatorRpcMethod.STEALTH_LIST: {
            "outcome": "succeeded",
            **stealth_projection,
        },
        OperatorRpcMethod.STEALTH_EXPORT: {
            "outcome": "succeeded",
            "document": {
                "schema": STEALTH_EXPORT_SCHEMA,
                "version": STEALTH_EXPORT_VERSION,
                "exported_at": TIMESTAMP,
                "count": 1,
                "orders": [create_order],
            },
        },
        OperatorRpcMethod.STEALTH_IMPORT: {
            "outcome": "succeeded",
            "imported": 1,
            "total": 1,
            "results": [{
                "succeeded": True,
                "requested_client_order_id": "logical-order",
                "client_order_id": "logical-order",
                "product_id": "BTC-USD",
                "side": "BUY",
                "error": None,
            }],
            "warnings": [],
        },
        OperatorRpcMethod.STEALTH_CREATE: {
            "outcome": "succeeded",
            "client_order_id": "logical-order",
            "order": _operator_order(),
        },
        OperatorRpcMethod.STEALTH_CREATE_SPAN: {
            "outcome": "succeeded",
            "span": {
                "span_id": "span-1",
                "status": "success",
                "creation_mode": "independent_parents",
                "size_distribution": "equal",
                "requested_count": 1,
                "requested_total_size": 1.0,
                "effective_total_size": 1.0,
                "created_count": 1,
                "existing_count": 0,
                "failed_count": 0,
                "orders": [{
                    "index": 0,
                    "client_order_id": "span-1-0",
                    "parent_order_id": None,
                    "product_id": "BTC-USD",
                    "side": "BUY",
                    "size": 1.0,
                    "price": 100.0,
                    "reveal_condition": {"type": "price"},
                    "anchor_repricing_policy": {},
                    "status": "created",
                }],
            },
        },
        OperatorRpcMethod.STEALTH_CANCEL: {
            "outcome": "accepted_pending",
            "client_order_id": "logical-order",
            "accepted": True,
            "exchange_cancel_pending": True,
            "order": _operator_order(),
            "message": "Cancellation is pending.",
        },
        OperatorRpcMethod.STEALTH_REHIDE: {
            "outcome": "accepted_pending",
            "client_order_id": "logical-order",
            "accepted": True,
            "message": "Rehide is pending.",
        },
        OperatorRpcMethod.STEALTH_REPRICE_NOW: {
            "outcome": "succeeded",
            "client_order_id": "logical-order",
            "processed": 1,
        },
        OperatorRpcMethod.STEALTH_MOVE_REVEALED: {
            "outcome": "succeeded",
            "client_order_id": "logical-order",
            "old_exchange_order_id": "exchange-old",
            "new_placement_client_order_id": "placement-new",
            "new_exchange_order_id": None,
            "new_submitted_price": 101.0,
        },
        OperatorRpcMethod.STEALTH_UPDATE_PRICE_CONDITION: {
            "outcome": "succeeded",
            "client_order_id": "logical-order",
            "price_threshold": 99.0,
            "hold_duration_seconds": None,
            "affected_conditions": {},
        },
        OperatorRpcMethod.STEALTH_CLEAR_ALL: {
            "outcome": "succeeded",
            "rows_deleted": 1,
            "in_memory_cancelled": 1,
            "in_memory_cancel_failures": 0,
            "message": "Cleared.",
        },
        OperatorRpcMethod.STRATEGY_UPDATE_TARGET: {
            "outcome": "succeeded",
            "parent_client_order_id": "logical-order",
            "target_movement": 0.002,
            "target_movement_type": "P",
        },
        OperatorRpcMethod.STRATEGY_UPDATE_PARENT: {
            "outcome": "succeeded",
            "client_order_id": "logical-order",
            "order": _parent_order_record(),
        },
    }


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
    result = _result_fixtures()[OperatorRpcMethod.STEALTH_MOVE_REVEALED]
    result["new_submitted_price"] = float("inf")
    with pytest.raises(ValueError):
        encode_success(
            str(uuid4()),
            OperatorRpcMethod.STEALTH_MOVE_REVEALED,
            result,
        )


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


def test_unknown_method_error_envelope_matches_committed_schema():
    error = _error_for(json.dumps({
        "jsonrpc": "2.0",
        "id": str(uuid4()),
        "method": "v1.unknown",
        "params": {},
    }))
    payload = json.loads(encode_error(error.request_id, error))
    Draft202012Validator(
        load_protocol_schema(),
        format_checker=FormatChecker(),
    ).validate(payload)
    assert payload["error"]["data"]["method"] == "v1.unknown"


@pytest.mark.parametrize(
    "document",
    [
        {
            "schema": STEALTH_EXPORT_SCHEMA,
            "version": STEALTH_EXPORT_VERSION,
            "orders": [{
                "client_order_id": "v2-order",
                "product_id": "BTC-USD",
                "side": "BUY",
                "total_size": 1.0,
                "limit_price": 100.0,
                "reveal_condition": {"type": "price"},
            }],
        },
        {"version": 1, "count": 0, "orders": []},
        {
            "type": "export_active_stealth_orders_response",
            "status": "success",
            "count": 0,
            "orders": [],
        },
    ],
    ids=["v2", "explicit-v1", "legacy-unversioned"],
)
def test_all_supported_backup_document_variants_remain_valid(document):
    request = decode_request(rpc_request(
        OperatorRpcMethod.STEALTH_IMPORT,
        {"document": document},
    ))
    assert request.params["document"] == document


def test_schema_enum_and_explicit_dispatch_have_the_same_method_inventory():
    schema_defs = load_protocol_schema()["$defs"]
    expected = {method.value for method in OperatorRpcMethod}
    schema_methods = set(schema_defs["methodParams"]["properties"])
    schema_results = set(schema_defs["methodResults"]["properties"])
    assert schema_methods == expected
    assert schema_results == expected
    assert set(schema_defs["operatorMethod"]["enum"]) == expected
    assert set(schema_defs["methodParams"]["required"]) == expected
    assert set(schema_defs["methodResults"]["required"]) == expected
    assert {method.value for method in dashboard_server._RPC_HANDLERS} == expected

    expected_notifications = {
        method.value for method in OperatorNotificationMethod
    }
    notification_params = schema_defs["notificationParams"]
    assert set(notification_params["properties"]) == expected_notifications
    assert set(notification_params["required"]) == expected_notifications
    assert set(
        schema_defs["operatorNotificationMethod"]["enum"]
    ) == expected_notifications


def test_schema_fixed_vocabularies_match_python_enums():
    schema_defs = load_protocol_schema()["$defs"]
    assert set(schema_defs["operatorOutcome"]["enum"]) == {
        item.value for item in OperatorOutcome
    }
    assert set(schema_defs["operatorErrorReason"]["enum"]) == {
        item.value for item in OperatorErrorReason
    }
    assert set(schema_defs["operatorErrorCode"]["enum"]) == {
        int(item) for item in OperatorRpcErrorCode
    }
    assert set(schema_defs["engineState"]["enum"]) == {
        item.value for item in EngineState
    }
    assert set(schema_defs["orderSide"]["enum"]) == {
        item.value for item in OrderSide
    }
    assert set(schema_defs["followUpRevealDirection"]["enum"]) == {
        item.value for item in FollowUpRevealDirection
    }
    assert set(schema_defs["targetMovementType"]["enum"]) == {
        item.value for item in TargetMovementType
    }
    assert set(schema_defs["stealthSpanCreationMode"]["enum"]) == {
        item.value for item in StealthSpanCreationMode
    }
    assert set(schema_defs["stealthSpanSizeDistribution"]["enum"]) == {
        item.value for item in StealthSpanSizeDistribution
    }
    assert set(schema_defs["stealthSpanResultStatus"]["enum"]) == {
        item.value for item in StealthSpanResultStatus
    }
    assert set(schema_defs["stealthSpanOrderResultStatus"]["enum"]) == {
        item.value for item in StealthSpanOrderResultStatus
    }
    assert set(schema_defs["stealthMoveReason"]["enum"]) == {
        item.value for item in StealthMoveReason
    }
    assert set(schema_defs["revealPricingPolicy"]["enum"]) == {
        *(item.value for item in RevealPricingPolicy),
        None,
    }
    assert set(
        schema_defs["operatorStealthOrder"]["properties"]["status"]["enum"]
    ) == {item.value for item in StealthOrderStatus}
    assert set(
        schema_defs["repricingStatistics"]["properties"]
        ["breakdown_by_source"]["required"]
    ) == {item.value for item in RepricingReferenceSource}


@pytest.mark.parametrize(
    ("method", "result"),
    list(_result_fixtures().items()),
    ids=lambda value: value.value if isinstance(value, OperatorRpcMethod) else None,
)
def test_every_method_has_a_valid_representative_result(method, result):
    validate_method_result(method, result)
    request_id = str(uuid4())
    payload = json.loads(encode_success(request_id, method, result))
    assert payload == {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result,
    }
    assert "method" not in payload
    Draft202012Validator(
        load_protocol_schema(),
        format_checker=FormatChecker(),
    ).validate(payload)


def test_date_time_formats_are_enforced_for_results_and_v2_imports():
    invalid_result = deepcopy(
        _result_fixtures()[OperatorRpcMethod.RUNTIME_STATUS]
    )
    invalid_result["timestamp"] = "not-a-date"
    with pytest.raises(ValueError, match="date-time"):
        validate_method_result(
            OperatorRpcMethod.RUNTIME_STATUS,
            invalid_result,
        )

    error = _error_for(rpc_request(
        OperatorRpcMethod.STEALTH_IMPORT,
        {
            "document": {
                "schema": STEALTH_EXPORT_SCHEMA,
                "version": STEALTH_EXPORT_VERSION,
                "exported_at": "not-a-date",
                "orders": [],
            }
        },
    ))
    assert error.code is OperatorRpcErrorCode.INVALID_PARAMS

    with pytest.raises(ValueError, match="date-time"):
        validate_notification_params(
            OperatorNotificationMethod.RUNTIME_PROJECTION,
            {"state": _dashboard_state(), "timestamp": "not-a-date"},
        )


def test_result_discriminants_reject_impossible_span_and_cancel_states():
    valid_cancel = deepcopy(
        _result_fixtures()[OperatorRpcMethod.STEALTH_CANCEL]
    )
    valid_cancel["outcome"] = OperatorOutcome.SUCCEEDED.value
    valid_cancel["exchange_cancel_pending"] = False
    validate_method_result(OperatorRpcMethod.STEALTH_CANCEL, valid_cancel)

    impossible_cancel = deepcopy(valid_cancel)
    impossible_cancel["exchange_cancel_pending"] = True
    with pytest.raises(ValueError, match="v1.stealth.cancel"):
        validate_method_result(
            OperatorRpcMethod.STEALTH_CANCEL,
            impossible_cancel,
        )

    valid_partial = deepcopy(
        _result_fixtures()[OperatorRpcMethod.STEALTH_CREATE_SPAN]
    )
    valid_partial["outcome"] = OperatorOutcome.PARTIAL.value
    valid_partial["span"].update({
        "status": StealthSpanResultStatus.PARTIAL.value,
        "requested_count": 2,
        "created_count": 1,
        "failed_count": 1,
    })
    failed_rung = deepcopy(valid_partial["span"]["orders"][0])
    failed_rung.update({
        "index": 1,
        "client_order_id": "span-1-1",
        "status": StealthSpanOrderResultStatus.FAILED.value,
        "error": "injected failure",
    })
    valid_partial["span"]["orders"].append(failed_rung)
    validate_method_result(
        OperatorRpcMethod.STEALTH_CREATE_SPAN,
        valid_partial,
    )

    impossible_span = deepcopy(valid_partial)
    impossible_span["outcome"] = OperatorOutcome.SUCCEEDED.value
    with pytest.raises(ValueError, match="v1.stealth.create_span"):
        validate_method_result(
            OperatorRpcMethod.STEALTH_CREATE_SPAN,
            impossible_span,
        )

    missing_rung_error = deepcopy(valid_partial)
    del missing_rung_error["span"]["orders"][1]["error"]
    with pytest.raises(ValueError, match="v1.stealth.create_span"):
        validate_method_result(
            OperatorRpcMethod.STEALTH_CREATE_SPAN,
            missing_rung_error,
        )


def test_all_import_result_entry_variants_match_the_result_contract():
    result = {
        "outcome": OperatorOutcome.PARTIAL.value,
        "imported": 1,
        "total": 3,
        "results": [
            {"succeeded": False, "error": "Entry must be an object"},
            {
                "succeeded": False,
                "requested_client_order_id": None,
                "product_id": None,
                "side": None,
                "error": "Missing required fields",
            },
            {
                "succeeded": True,
                "requested_client_order_id": "logical-order",
                "client_order_id": "logical-order",
                "product_id": "BTC-USD",
                "side": OrderSide.BUY.value,
                "error": None,
            },
        ],
        "warnings": ["Legacy import defaults were applied."],
    }
    validate_method_result(OperatorRpcMethod.STEALTH_IMPORT, result)


def test_result_validation_uses_the_json_normalized_wire_value():
    result = {
        "outcome": "succeeded",
        "client_order_id": "logical-order",
        "accepted": True,
        "exchange_cancel_pending": False,
        "order": {
            "client_order_id": "logical-order",
            "created_at": datetime(2026, 11, 27, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc),
        },
        "message": "Order cancelled.",
    }
    validate_method_result(OperatorRpcMethod.STEALTH_CANCEL, result)
    payload = json.loads(encode_success(
        str(uuid4()),
        OperatorRpcMethod.STEALTH_CANCEL,
        result,
    ))
    assert payload["result"]["order"]["created_at"].endswith("+00:00")
    assert payload["result"]["order"]["updated_at"].endswith("+00:00")


@pytest.mark.parametrize(
    "invalid_result",
    [
        {
            key: value
            for key, value in _result_fixtures()[
                OperatorRpcMethod.RUNTIME_STATUS
            ].items()
            if key != "timestamp"
        },
        {
            **_result_fixtures()[OperatorRpcMethod.RUNTIME_STATUS],
            "unexpected": True,
        },
        {
            **_result_fixtures()[OperatorRpcMethod.RUNTIME_STATUS],
            "engine_state": 1,
        },
    ],
    ids=["missing", "extra", "wrong-type"],
)
def test_method_result_validation_rejects_top_level_contract_drift(
    invalid_result,
):
    with pytest.raises(ValueError, match="v1.runtime.status"):
        validate_method_result(
            OperatorRpcMethod.RUNTIME_STATUS,
            invalid_result,
        )


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


def test_invalid_handler_result_returns_one_correlated_internal_error():
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
    assert payload["error"]["data"] == {
        "retryable": False,
        "reason": OperatorErrorReason.INDETERMINATE.value,
    }


def test_invalid_handler_result_sends_error_before_requested_projections():
    events = []

    async def record_response(_message):
        events.append("response")

    async def fail_runtime_projection():
        events.append("runtime")
        raise RuntimeError("runtime projection failed")

    async def record_stealth_projection():
        events.append("stealth_orders")

    websocket = Mock(send=AsyncMock(side_effect=record_response))
    request_id = str(uuid4())
    handler = AsyncMock(return_value=dashboard_server._rpc_result(
        {"value": float("inf")},
        broadcast_runtime=True,
        broadcast_stealth_orders=True,
    ))
    runtime_projection = AsyncMock(side_effect=fail_runtime_projection)
    stealth_projection = AsyncMock(side_effect=record_stealth_projection)

    with patch.dict(
        dashboard_server._RPC_HANDLERS,
        {OperatorRpcMethod.RUNTIME_STATUS: handler},
    ), patch.object(
        dashboard_server,
        "broadcast_state",
        runtime_projection,
    ), patch.object(
        dashboard_server,
        "_broadcast_stealth_orders_projection",
        stealth_projection,
    ):
        asyncio.run(dashboard_server.handle_client_message(
            websocket,
            rpc_request(
                OperatorRpcMethod.RUNTIME_STATUS,
                request_id=request_id,
            ),
        ))

    assert events == ["response", "runtime", "stealth_orders"]
    websocket.send.assert_awaited_once()
    runtime_projection.assert_awaited_once_with()
    stealth_projection.assert_awaited_once_with()
    payload = json.loads(websocket.send.await_args.args[0])
    assert payload["id"] == request_id
    assert payload["error"]["code"] == OperatorRpcErrorCode.INTERNAL_ERROR
    assert payload["error"]["data"] == {
        "retryable": False,
        "reason": OperatorErrorReason.INDETERMINATE.value,
    }


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


def test_current_notification_builders_match_method_specific_contracts():
    dashboard_state = _dashboard_state()
    with patch.object(
        dashboard_server,
        "engine_state",
        dashboard_state,
    ), patch.object(
        dashboard_server,
        "_build_market_metrics_payload",
        return_value={},
    ), patch.object(
        dashboard_server,
        "_runtime_status_payload",
        return_value=_runtime_status(),
    ):
        runtime_message = json.loads(
            dashboard_server._build_state_update_message()
        )

    with patch.object(
        dashboard_server,
        "engine_state",
        _dashboard_state(),
    ), patch.object(
        dashboard_server,
        "_enrich_stealth_orders_with_parent_data",
        side_effect=lambda orders: orders,
    ):
        stealth_params = dashboard_server._stealth_orders_snapshot_payload()

    ticker_broadcast = AsyncMock()
    with patch.object(
        dashboard_server,
        "_broadcast_dashboard_message",
        ticker_broadcast,
    ):
        asyncio.run(dashboard_server._async_broadcast_ticker({
            "product_id": "BTC-USD",
            "price": 100.0,
            "time": 1.0,
            "server_time_ms": 1000,
        }))
    ticker_message = json.loads(ticker_broadcast.await_args.args[0])

    spread_broadcast = AsyncMock()
    with patch.object(
        dashboard_server,
        "_broadcast_dashboard_message",
        spread_broadcast,
    ):
        asyncio.run(dashboard_server._async_broadcast_spread([{
            "product_id": "BTC-USD",
            "bid": 99.0,
            "ask": 101.0,
            "mid": 100.0,
        }]))
    spread_message = json.loads(spread_broadcast.await_args.args[0])

    fixtures = {
        OperatorNotificationMethod.RUNTIME_PROJECTION: runtime_message[
            "params"
        ],
        OperatorNotificationMethod.STEALTH_ORDERS_PROJECTION: stealth_params,
        OperatorNotificationMethod.MARKET_TICKER: ticker_message["params"],
        OperatorNotificationMethod.MARKET_SPREAD_SNAPSHOT: spread_message[
            "params"
        ],
    }
    root_validator = Draft202012Validator(load_protocol_schema())
    for method, params in fixtures.items():
        validate_notification_params(method, params)
        root_validator.validate(json.loads(encode_notification(method, params)))


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
