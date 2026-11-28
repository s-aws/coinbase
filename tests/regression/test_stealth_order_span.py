"""Regression contracts for canonical, resumable stealth-order spans."""

from __future__ import annotations

import asyncio
import json
import threading
from unittest.mock import AsyncMock, Mock, patch
import uuid

import pytest

import dashboard_server
from bridges.stealth_order_bridge import StealthOrderBridge
from business.stealth_order_span import (
    StealthSpanValidationError,
    plan_stealth_order_span,
)
from core.execution_core import ExecutionCore
from core.enums import OperatorRpcMethod
from core.runtime_controller import RuntimeController
from tests.regression.operator_rpc_test_support import rpc_request, rpc_result


pytestmark = pytest.mark.regression


_PRODUCT_METADATA = {
        "price_increment": "1",
        "base_increment": "1",
        "base_min_size": "1",
        "quote_min_size": "0",
}


def _metadata_reader(_product_id):
    return _PRODUCT_METADATA


def _plan(request):
    return plan_stealth_order_span(
        request,
        metadata_reader=_metadata_reader,
    )


def _request(**overrides):
    request = {
        "span_id": str(uuid.uuid4()),
        "product_id": "BTC-USDC",
        "side": "SELL",
        "order_count": 3,
        "start_price": 100,
        "price_step": 10,
        "total_size": 6,
        "size_distribution": "equal",
        "creation_mode": "independent_parents",
        "reveal_condition": {
            "type": "price",
            "price_threshold": 95,
            "direction": "below",
            "hold_duration_seconds": 0,
        },
        "reveal_pricing_policy": "configured_limit",
        "sizing_strategy": {"type": "fixed"},
        "follow_up_reveal_direction": "opposite",
        "max_order_replacements": 2,
        "target_movement": 0,
        "target_movement_type": "P",
        "allow_partial_fills": False,
        "anchor_repricing_policy": {"enabled": False},
        "enable_hotpoint_replication": False,
        "notes": "regression",
    }
    request.update(overrides)
    return request


def test_planner_materializes_independent_thresholds_and_deterministic_ids():
    request = _request()
    first = _plan(request)
    second = _plan(request)

    assert [order.client_order_id for order in first.orders] == [
        order.client_order_id for order in second.orders
    ]
    assert [order.limit_price for order in first.orders] == [100.0, 110.0, 120.0]
    assert [order.reveal_condition["price_threshold"] for order in first.orders] == [
        95.0,
        105.0,
        115.0,
    ]
    assert all(
        order.reveal_condition["direction"] == "above" for order in first.orders
    )
    assert all(order.parent_order_id is None for order in first.orders)


def test_parent_children_share_root_strategy_and_flat_parent_id():
    plan = _plan(
        _request(creation_mode="parent_children")
    )

    root_id = plan.orders[0].client_order_id
    assert plan.orders[0].parent_order_id is None
    assert [order.parent_order_id for order in plan.orders[1:]] == [root_id, root_id]
    assert [order.reveal_condition["price_threshold"] for order in plan.orders] == [
        95.0,
        95.0,
        95.0,
    ]


def test_buy_span_steps_prices_downward():
    plan = _plan(_request(side="BUY"))

    assert [order.limit_price for order in plan.orders] == [100.0, 90.0, 80.0]
    assert all(
        order.reveal_condition["direction"] == "below" for order in plan.orders
    )


@pytest.mark.parametrize(
    ("distance_type", "target_distance", "max_distance", "expected_targets"),
    [
        ("A", 1.0, 5.0, [1.0, 11.0, 21.0]),
        ("P", 0.01, 0.05, [0.01, 0.11, 0.21]),
    ],
)
def test_anchor_distances_are_materialized_in_their_declared_units(
    distance_type,
    target_distance,
    max_distance,
    expected_targets,
):
    plan = _plan(
        _request(
            anchor_repricing_policy={
                "enabled": True,
                "distance_type": distance_type,
                "target_distance": target_distance,
                "max_distance": max_distance,
            }
        )
    )

    assert [
        order.anchor_repricing_policy["target_distance"] for order in plan.orders
    ] == pytest.approx(expected_targets)


def test_even_pyramid_has_exact_count_and_preserves_effective_total():
    plan = _plan(
        _request(order_count=4, total_size=6, size_distribution="pyramid")
    )

    assert [order.total_size for order in plan.orders] == [1.0, 2.0, 2.0, 1.0]
    assert len(plan.orders) == 4
    assert plan.effective_total_size == 6.0


def test_effective_duplicate_prices_are_rejected_before_creation():
    with pytest.raises(StealthSpanValidationError, match="duplicate effective span prices"):
        _plan(_request(price_step=0))


class _FakeSpanManager:
    def __init__(self, *, fail_on_create_index=None):
        self.in_memory_orders = {}
        self.parent_rows = {}
        self.fail_on_create_index = fail_on_create_index
        self.create_calls = 0

    def _get_stealth_order(self, client_order_id):
        return self.in_memory_orders.get(client_order_id)

    def get_product_metadata(self, _product_id):
        return _PRODUCT_METADATA

    def create_stealth_order(self, **kwargs):
        call_index = self.create_calls
        self.create_calls += 1
        if call_index == self.fail_on_create_index:
            raise RuntimeError("injected rung failure")

        client_order_id = kwargs["stealth_order_id"]
        self.in_memory_orders[client_order_id] = {
            "stealth_order_id": client_order_id,
            "status": "HIDDEN",
            "product_id": kwargs["product_id"],
            "side": kwargs["side"],
            "total_size": kwargs["total_size"],
            "limit_price": kwargs["limit_price"],
            "reveal_condition_json": kwargs["reveal_condition"],
            "reveal_pricing_policy": kwargs["reveal_pricing_policy"],
            "sizing_strategy_json": kwargs["sizing_strategy"],
            "parent_order_id": kwargs["parent_order_id"],
            "follow_up_reveal_direction": kwargs["follow_up_reveal_direction"],
            "notes": kwargs["notes"],
            "anchor_repricing_policy_json": kwargs["anchor_repricing_policy"],
        }
        is_child = kwargs["parent_order_id"] is not None
        self.parent_rows[client_order_id] = {
            "product_id": kwargs["product_id"],
            "side": kwargs["side"],
            "size": kwargs["total_size"],
            "price": kwargs["limit_price"],
            "parent_order_id": kwargs["parent_order_id"],
            "target_movement": kwargs["target_movement"],
            "target_movement_type": kwargs["target_movement_type"],
            "max_order_replacement": 0 if is_child else kwargs["max_order_replacements"],
            "allow_partial_fills": False if is_child else kwargs["allow_partial_fills"],
            "enable_hotpoint_replication": (
                False if is_child else kwargs["enable_hotpoint_replication"]
            ),
        }
        return client_order_id


class _FakeSpanParentOrderReader:
    def __init__(self, parent_rows):
        self.parent_rows = parent_rows
        self.failure = None

    def get_parent_order(self, client_order_id):
        if self.failure is not None:
            raise self.failure
        return self.parent_rows.get(client_order_id)


def _bridge(manager):
    bridge = StealthOrderBridge.__new__(StealthOrderBridge)
    bridge.stealth_manager = manager
    bridge._span_parent_order_reader = _FakeSpanParentOrderReader(
        manager.parent_rows
    )
    bridge._order_action_locks_guard = threading.Lock()
    bridge._order_action_locks = {}
    return bridge


def test_bridge_retry_returns_existing_rungs_without_duplicate_creation():
    manager = _FakeSpanManager()
    bridge = _bridge(manager)
    request = _request()

    first = bridge.create_stealth_order_span(request)
    second = bridge.create_stealth_order_span(request)

    assert first["status"] == "success"
    assert first["created_count"] == 3
    assert second["status"] == "success"
    assert second["created_count"] == 0
    assert second["existing_count"] == 3
    assert manager.create_calls == 3


def test_reusing_span_id_with_changed_immutable_fields_is_a_conflict():
    manager = _FakeSpanManager()
    bridge = _bridge(manager)
    request = _request()

    bridge.create_stealth_order_span(request)
    conflict = bridge.create_stealth_order_span({**request, "notes": "changed"})

    assert conflict["status"] == "error"
    assert conflict["orders"][0]["status"] == "failed"
    assert "notes" in conflict["orders"][0]["error"]
    assert manager.create_calls == 3


def test_parent_lookup_failure_stops_span_retry_before_any_new_write():
    manager = _FakeSpanManager()
    bridge = _bridge(manager)
    request = _request()
    bridge.create_stealth_order_span(request)
    bridge._span_parent_order_reader.failure = RuntimeError(
        "parent lookup unavailable"
    )

    retry = bridge.create_stealth_order_span(request)

    assert retry["status"] == "error"
    assert retry["orders"][0]["status"] == "failed"
    assert "parent lookup unavailable" in retry["orders"][0]["error"]
    assert [order["status"] for order in retry["orders"][1:]] == [
        "not_attempted",
        "not_attempted",
    ]
    assert manager.create_calls == 3


def test_bridge_reports_runtime_partial_and_stops_later_rungs():
    manager = _FakeSpanManager(fail_on_create_index=1)
    result = _bridge(manager).create_stealth_order_span(_request())

    assert result["status"] == "partial"
    assert result["created_count"] == 1
    assert result["failed_count"] == 1
    assert [order["status"] for order in result["orders"]] == [
        "created",
        "failed",
        "not_attempted",
    ]
    assert manager.create_calls == 2


def test_dashboard_span_message_returns_one_aggregate_result():
    websocket = Mock()
    websocket.send = AsyncMock()
    bridge = Mock()
    bridge.stealth_manager.in_memory_orders = {}
    bridge.create_stealth_order_span.return_value = {
        "span_id": "span-id",
        "status": "success",
        "creation_mode": "independent_parents",
        "size_distribution": "equal",
        "requested_count": 1,
        "requested_total_size": 1.0,
        "effective_total_size": 1.0,
        "created_count": 1,
        "existing_count": 0,
        "failed_count": 0,
        "orders": [],
    }
    controller = RuntimeController()
    assert controller.complete_startup() is True
    execution_core = ExecutionCore(
        runtime_controller=controller,
        stealth_commands=bridge,
        stealth_queries=bridge,
    )

    with patch.object(dashboard_server, "stealth_order_bridge", bridge), patch.object(
        dashboard_server,
        "get_runtime_controller",
        return_value=controller,
    ), patch.object(
        dashboard_server,
        "EXECUTION_CORE",
        execution_core,
    ), patch.object(
        dashboard_server,
        "_broadcast_stealth_orders_projection",
        new=AsyncMock(),
    ) as broadcast, patch.object(
        dashboard_server,
        "add_log_entry",
    ):
        span_request = _request(span_id="span-id", order_count=1, total_size=1)
        asyncio.run(
            dashboard_server.handle_client_message(
                websocket,
                rpc_request(
                    OperatorRpcMethod.STEALTH_CREATE_SPAN,
                    span_request,
                ),
            )
        )

    payloads = [json.loads(call.args[0]) for call in websocket.send.await_args_list]
    assert len(payloads) == 1
    assert rpc_result(payloads[0])["span"] == bridge.create_stealth_order_span.return_value
    bridge.create_stealth_order_span.assert_called_once_with(span_request)
    broadcast.assert_awaited_once_with()
    assert OperatorRpcMethod.STEALTH_CREATE_SPAN in dashboard_server._ORIGINATING_METHODS
