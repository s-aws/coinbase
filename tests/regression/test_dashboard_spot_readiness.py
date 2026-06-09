"""Regression tests for dashboard spot readiness feedback."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.enums import ActionConditionType, ProductCapability, ProductCapabilityMode
from core.exceptions import OrderCreationError


pytestmark = pytest.mark.regression


def _make_websocket():
    ws = MagicMock()
    ws.send = AsyncMock()
    return ws


def _run(coro):
    return asyncio.run(coro)


def _sent_payload(ws):
    assert ws.send.await_args_list
    return json.loads(ws.send.await_args_list[-1].args[0])


def test_spot_readiness_payload_reports_capabilities_budget_and_wallet(
    monkeypatch,
):
    import configuration
    import dashboard_server

    monkeypatch.setattr(configuration, "ACTION_CONDITION_GUARDS", {
        "wallet_available": {"enabled": True},
        "known_inventory_available": {"enabled": True},
    })
    monkeypatch.setattr(configuration, "SPOT_INVENTORY_BASELINES", [
        {
            "product_id": "BTC-USD",
            "quantity": 0.25,
            "entry_price": 90000.0,
            "source_id": "known-baseline",
        },
        {
            "product_id": "BTC-USD",
            "quantity": 0.1,
            "source_id": "unknown-baseline",
        },
    ])
    monkeypatch.setattr(
        dashboard_server,
        "rest_credentials_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        dashboard_server,
        "fetch_account_wallets",
        lambda: {
            "BTC": {"available_balance": {"value": "0.5"}},
            "USD": {"available_balance": {"value": "1000"}},
        },
    )

    manager = MagicMock()
    manager._get_spot_planned_budget_commitments.return_value = {
        "USD": 250.0,
    }
    bridge = MagicMock()
    bridge.stealth_manager = manager

    with patch.object(dashboard_server, "stealth_order_bridge", bridge):
        payload = dashboard_server._build_spot_readiness_payload(
            product_ids=["BTC-USD"],
        )

    assert payload["type"] == "spot_readiness"
    assert payload["planned_budget"] == {"USD": 250.0}
    assert payload["wallet_snapshot"]["available"] is True
    assert payload["wallet_snapshot"]["age_seconds"] == 0.0
    assert payload["wallet_snapshot"]["currencies"]["BTC"][
        "available_balance"
    ] == 0.5
    assert payload["action_guards"]["known_inventory_available"]["enabled"] is True
    guard_summary = {
        item["condition"]: item for item in payload["action_guard_summary"]
    }
    assert guard_summary[
        ActionConditionType.PLANNED_BUDGET_AVAILABLE.value
    ]["mode"] == (
        ProductCapabilityMode.ENABLED.value
    )
    assert "triggered spot commitments" in (
        guard_summary[
            ActionConditionType.PLANNED_BUDGET_AVAILABLE.value
        ]["reason"]
    )

    product = payload["products"][0]
    assert product["product_id"] == "BTC-USD"
    direct = product["capabilities"][ProductCapability.DIRECT_PLACEMENT.value]
    move = product["capabilities"][ProductCapability.MOVE_REVEALED.value]
    assert direct["mode"] == ProductCapabilityMode.ENABLED.value
    assert move["mode"] == ProductCapabilityMode.DISABLED.value
    baselines = product["inventory"]["imported_baselines"]
    assert baselines["known_quantity"] == pytest.approx(0.25)
    assert baselines["unknown_cost_basis_quantity"] == pytest.approx(0.1)
    assert {lot["source_id"] for lot in baselines["lots"]} == {
        "known-baseline",
        "unknown-baseline",
    }


def test_request_spot_readiness_message_sends_payload(monkeypatch):
    import dashboard_server

    monkeypatch.setattr(
        dashboard_server,
        "_build_spot_readiness_payload",
        lambda product_ids=None: {
            "type": "spot_readiness",
            "status": "success",
            "product_ids": product_ids,
        },
    )
    ws = _make_websocket()

    _run(dashboard_server.handle_client_message(
        ws,
        json.dumps({
            "type": "request_spot_readiness",
            "params": {"product_ids": "BTC-USD"},
        }),
    ))

    payload = _sent_payload(ws)
    assert payload == {
        "type": "spot_readiness",
        "status": "success",
        "product_ids": ["BTC-USD"],
    }


def test_create_stealth_order_error_preserves_guard_context(monkeypatch):
    import dashboard_server

    bridge = MagicMock()
    bridge.create_stealth_order.side_effect = OrderCreationError(
        "blocked by guard",
        product_id="BTC-USD",
        guard={
            "condition": ActionConditionType.PLANNED_BUDGET_AVAILABLE.value,
            "block_category": (
                ActionConditionType.PLANNED_BUDGET_AVAILABLE.value
            ),
            "reason": "wallet drain",
            "currency": "USD",
            "available": 50.0,
            "planned_commitment": 25.0,
            "available_after_planned": 25.0,
            "required": 30.0,
        },
    )
    monkeypatch.setattr(dashboard_server, "stealth_order_bridge", bridge)
    ws = _make_websocket()

    _run(dashboard_server.handle_client_message(
        ws,
        json.dumps({
            "type": "create_stealth_order",
            "order": {
                "product_id": "BTC-USD",
                "side": "BUY",
                "total_size": 0.1,
                "limit_price": 100.0,
                "reveal_condition": {"type": "time_delay", "delay_seconds": 0},
            },
        }),
    ))

    payload = _sent_payload(ws)
    assert payload["type"] == "error"
    assert payload["product_id"] == "BTC-USD"
    assert payload["guard"]["block_category"] == (
        ActionConditionType.PLANNED_BUDGET_AVAILABLE.value
    )
    assert payload["guard"]["available_after_planned"] == 25.0
