"""Strict JSON-RPC 2.0 framing for the operator WebSocket.

This module owns transport parsing and serialization only. It does not own
application admission, order lifecycle, persistence, or exchange behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from functools import lru_cache
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping
from uuid import UUID

from jsonschema import Draft202012Validator, FormatChecker

from core.enums import (
    OperatorErrorReason,
    OperatorNotificationMethod,
    OperatorRpcErrorCode,
    OperatorRpcMethod,
)


JSONRPC_VERSION = "2.0"
STEALTH_EXPORT_SCHEMA = "coinbase.stealth-orders"
STEALTH_EXPORT_VERSION = 2
_RFC3339_DATETIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$"
)


def _is_rfc3339_datetime(value: object) -> bool:
    if not isinstance(value, str) or not _RFC3339_DATETIME.fullmatch(value):
        return False
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00"
            if value.endswith(("Z", "z"))
            else value
        )
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


_FORMAT_CHECKER = FormatChecker()
_FORMAT_CHECKER.checks("date-time")(_is_rfc3339_datetime)


@dataclass(frozen=True)
class OperatorRpcRequest:
    """One validated client request.

    ``request_id`` is correlation only. It does not grant replay or generic
    idempotency semantics to the requested operation.
    """

    request_id: str
    method: OperatorRpcMethod
    params: dict[str, Any]


class OperatorRpcError(Exception):
    """Structured error that can be serialized as a JSON-RPC response."""

    def __init__(
        self,
        code: OperatorRpcErrorCode,
        message: str,
        *,
        request_id: str | None = None,
        reason: OperatorErrorReason | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.request_id = request_id
        payload = dict(data or {})
        if reason is not None:
            payload["reason"] = reason.value
        self.data = payload


@lru_cache(maxsize=1)
def load_protocol_schema() -> dict[str, Any]:
    """Load the committed schema used by Python and reserved for bindings."""

    schema_path = Path(__file__).with_name("schema.json")
    with schema_path.open("r", encoding="utf-8") as schema_file:
        schema = json.load(schema_file)
    Draft202012Validator.check_schema(schema)
    return schema


@lru_cache(maxsize=None)
def _params_validator(method: OperatorRpcMethod) -> Draft202012Validator:
    schema = load_protocol_schema()
    # Validate through the root document so method schemas can resolve shared
    # definitions such as ``emptyParams`` and ``clientOrderId``.
    return Draft202012Validator(
        {
            "$schema": schema["$schema"],
            "$ref": f"#/$defs/methodParams/properties/{method.value}",
            "$defs": schema["$defs"],
        },
        format_checker=_FORMAT_CHECKER,
    )


@lru_cache(maxsize=None)
def _result_validator(method: OperatorRpcMethod) -> Draft202012Validator:
    schema = load_protocol_schema()
    return Draft202012Validator(
        {
            "$schema": schema["$schema"],
            "$ref": f"#/$defs/methodResults/properties/{method.value}",
            "$defs": schema["$defs"],
        },
        format_checker=_FORMAT_CHECKER,
    )


@lru_cache(maxsize=None)
def _notification_params_validator(
    method: OperatorNotificationMethod,
) -> Draft202012Validator:
    schema = load_protocol_schema()
    return Draft202012Validator(
        {
            "$schema": schema["$schema"],
            "$ref": f"#/$defs/notificationParams/properties/{method.value}",
            "$defs": schema["$defs"],
        },
        format_checker=_FORMAT_CHECKER,
    )


def _field_errors(
    validator: Draft202012Validator,
    value: Any,
) -> list[dict[str, str]]:
    errors = sorted(
        validator.iter_errors(value),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    return [
        {
            "path": ".".join(str(item) for item in error.absolute_path) or "$",
            "message": error.message,
            "rule": str(error.validator),
        }
        for error in errors
    ]


def validate_method_result(
    method: OperatorRpcMethod,
    result: Mapping[str, Any],
) -> None:
    """Reject a normalized wire result that violates its method contract."""

    wire_result = _normalize_json_value(dict(result))
    fields = _field_errors(_result_validator(method), wire_result)
    if fields:
        raise ValueError(
            f"Invalid result for {method.value}: "
            + json.dumps(fields, separators=(",", ":"))
        )


def validate_notification_params(
    method: OperatorNotificationMethod,
    params: Mapping[str, Any],
) -> None:
    """Validate one notification payload without imposing hot-path checks."""

    wire_params = _normalize_json_value(dict(params))
    fields = _field_errors(_notification_params_validator(method), wire_params)
    if fields:
        raise ValueError(
            f"Invalid notification params for {method.value}: "
            + json.dumps(fields, separators=(",", ":"))
        )


def _canonical_request_id(value: Any) -> str | None:
    """Return a trustworthy correlation ID or ``None``."""

    if not isinstance(value, str) or not value:
        return None
    try:
        parsed_id = UUID(value)
    except (TypeError, ValueError, AttributeError):
        return None
    return value if str(parsed_id) == value else None


def _reject_non_finite_numbers(value: Any) -> None:
    """Reject JSON numbers that Python decoded outside the finite domain."""

    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("JSON numbers must be finite")
    if isinstance(value, dict):
        for child in value.values():
            _reject_non_finite_numbers(child)
    elif isinstance(value, list):
        for child in value:
            _reject_non_finite_numbers(child)


def decode_request(raw_message: str) -> OperatorRpcRequest:
    """Decode one non-batch, correlated JSON-RPC request.

    Client notifications are deliberately unsupported: every operator action
    must receive one correlated terminal response from the application layer.
    """

    def _reject_non_json_number(value: str) -> None:
        raise ValueError(f"non-JSON numeric constant: {value}")

    try:
        payload = json.loads(
            raw_message,
            parse_constant=_reject_non_json_number,
        )
        _reject_non_finite_numbers(payload)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise OperatorRpcError(
            OperatorRpcErrorCode.PARSE_ERROR,
            "Invalid JSON",
            data={"detail": str(exc)},
        ) from exc

    if not isinstance(payload, dict):
        raise OperatorRpcError(
            OperatorRpcErrorCode.INVALID_REQUEST,
            "JSON-RPC batch and non-object requests are not supported",
        )

    request_id = payload.get("id")
    response_id = _canonical_request_id(request_id)
    if payload.get("jsonrpc") != JSONRPC_VERSION:
        raise OperatorRpcError(
            OperatorRpcErrorCode.INVALID_REQUEST,
            "jsonrpc must be exactly '2.0'",
            request_id=response_id,
        )
    if set(payload) - {"jsonrpc", "id", "method", "params"}:
        raise OperatorRpcError(
            OperatorRpcErrorCode.INVALID_REQUEST,
            "Request contains unsupported top-level fields",
            request_id=response_id,
        )
    if response_id is None:
        raise OperatorRpcError(
            OperatorRpcErrorCode.INVALID_REQUEST,
            (
                "A caller-generated UUID string id is required"
                if not isinstance(request_id, str) or not request_id
                else "id must be a canonical UUID string"
            ),
        )

    raw_method = payload.get("method")
    if not isinstance(raw_method, str):
        raise OperatorRpcError(
            OperatorRpcErrorCode.INVALID_REQUEST,
            "method must be a string",
            request_id=request_id,
        )
    try:
        method = OperatorRpcMethod(raw_method)
    except ValueError as exc:
        raise OperatorRpcError(
            OperatorRpcErrorCode.METHOD_NOT_FOUND,
            f"Unknown operator method: {raw_method}",
            request_id=request_id,
            data={"method": raw_method},
        ) from exc

    params = payload.get("params", {})
    if not isinstance(params, dict):
        raise OperatorRpcError(
            OperatorRpcErrorCode.INVALID_PARAMS,
            "params must be an object",
            request_id=request_id,
            reason=OperatorErrorReason.INVALID_PARAMS,
            data={
                "fields": [{
                    "path": "$",
                    "message": "params must be an object",
                    "rule": "type",
                }]
            },
        )

    fields = _field_errors(_params_validator(method), params)
    if fields:
        raise OperatorRpcError(
            OperatorRpcErrorCode.INVALID_PARAMS,
            "Invalid method parameters",
            request_id=request_id,
            reason=OperatorErrorReason.INVALID_PARAMS,
            data={"fields": fields},
        )

    return OperatorRpcRequest(
        request_id=request_id,
        method=method,
        params=dict(params),
    )


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _encode(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        payload,
        allow_nan=False,
        default=_json_default,
        separators=(",", ":"),
    )


def _normalize_json_value(value: Any) -> Any:
    """Return the exact JSON value produced by the protocol encoder."""

    return json.loads(_encode({"value": value}))["value"]


def encode_success(
    request_id: str,
    method: OperatorRpcMethod,
    result: Mapping[str, Any],
) -> str:
    """Validate and serialize one successful correlated response.

    ``method`` selects the result schema but is not echoed on the wire. JSON-RPC
    correlation remains the caller-generated request id and the client's
    pending-request method map.
    """

    validate_method_result(method, result)

    return _encode({
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "result": dict(result),
    })


def encode_error(
    request_id: str | None,
    error: OperatorRpcError,
) -> str:
    """Serialize one standard or application JSON-RPC error response."""

    error_payload: dict[str, Any] = {
        "code": int(error.code),
        "message": str(error),
    }
    if error.data:
        error_payload["data"] = error.data
    return _encode({
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "error": error_payload,
    })


def encode_notification(
    method: OperatorNotificationMethod,
    params: Mapping[str, Any],
) -> str:
    """Serialize a server-pushed projection or market notification."""

    return _encode({
        "jsonrpc": JSONRPC_VERSION,
        "method": method.value,
        "params": dict(params),
    })
