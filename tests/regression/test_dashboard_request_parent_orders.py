"""Regression: dashboard parent-orders transport must preserve projected root/placement fields."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_websocket() -> MagicMock:
    ws = MagicMock()
    ws.send = AsyncMock()
    return ws


def _sent_payloads(ws: MagicMock) -> list[dict]:
    return [json.loads(call.args[0]) for call in ws.send.await_args_list]


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.mark.regression
def test_request_parent_orders_preserves_root_projection_fields():
    import dashboard_server

    ws = _make_websocket()
    projected_orders = [
        {
            "client_order_id": "root-1",
            "logical_root_client_order_id": "root-1",
            "is_root_order": True,
            "status_scope": "logical_root",
            "placement_status": "FILLED",
            "logical_root_status": "FILLED",
        },
        {
            "client_order_id": "child-1",
            "parent_order_id": "root-1",
            "logical_root_client_order_id": "root-1",
            "is_root_order": False,
            "status_scope": "placement",
            "placement_status": "PENDING",
            "logical_root_status": "FILLED",
        },
    ]

    message = json.dumps({"type": "request_parent_orders"})

    with patch(
        "database.order_dashboard_helpers.get_all_parent_orders",
        return_value=projected_orders,
    ):
        _run(dashboard_server.handle_client_message(ws, message))

    payloads = _sent_payloads(ws)
    assert payloads, "expected a websocket response"
    response = payloads[-1]
    assert response["type"] == "parent_orders_list"
    assert response["orders"]["root-1"]["logical_root_client_order_id"] == "root-1"
    assert response["orders"]["root-1"]["status_scope"] == "logical_root"
    assert response["orders"]["child-1"]["logical_root_client_order_id"] == "root-1"
    assert response["orders"]["child-1"]["status_scope"] == "placement"
    assert response["orders"]["child-1"]["logical_root_status"] == "FILLED"