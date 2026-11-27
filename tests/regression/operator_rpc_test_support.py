"""Small helpers for exercising the strict operator JSON-RPC boundary."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

from core.enums import OperatorRpcMethod


def rpc_request(
    method: OperatorRpcMethod,
    params: dict[str, Any] | None = None,
    *,
    request_id: str | None = None,
) -> str:
    correlation_id = request_id or str(uuid4())
    UUID(correlation_id)
    return json.dumps({
        "jsonrpc": "2.0",
        "id": correlation_id,
        "method": method.value,
        "params": params or {},
    })


def rpc_result(payload: dict[str, Any]) -> dict[str, Any]:
    assert payload["jsonrpc"] == "2.0"
    assert isinstance(payload["id"], str)
    assert "error" not in payload
    return payload["result"]


def rpc_error(payload: dict[str, Any]) -> dict[str, Any]:
    assert payload["jsonrpc"] == "2.0"
    assert "result" not in payload
    return payload["error"]
