"""Regression coverage for stale rows after authenticated anchor rearming."""

from __future__ import annotations

import threading
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from bridges.stealth_order_bridge import StealthOrderBridge
from core.enums import EngineState, OrderStatus, StealthOrderStatus
from core.order_engine import OrderEngine
from core.runtime_controller import RuntimeController
from core.stealth_order_manager import StealthOrderManager


pytestmark = pytest.mark.regression


def _revealed_order() -> dict:
    return {
        "stealth_order_id": "stealth-1",
        "product_id": "BIP-20DEC30-CDE",
        "side": "SELL",
        "total_size": 25.0,
        "revealed_size": 25.0,
        "remaining_size": 0.0,
        "executed_size": 0.0,
        "visibility_score": 1.0,
        "limit_price": 77150.0,
        "status": StealthOrderStatus.REVEALED.value,
        "reveal_condition_type": "time_delay",
        "reveal_condition_json": {
            "type": "time_delay",
            "delay_seconds": 60,
        },
        "condition_first_met_at": datetime(2026, 9, 1),
        "condition_confirmed_at": datetime(2026, 9, 1),
        "revealed_orders": [
            {
                "reveal_number": 1,
                "revealed_size": 25.0,
                "placement_price": 77150.0,
                "placed_order_id": "placement-1",
                "placement_client_order_id": "placement-1",
                "exchange_order_id": "exchange-1",
                "placement_success": True,
            }
        ],
        "anchor_repricing_policy_json": {
            "enabled": True,
            "allow_revealed_reprice": True,
        },
        "anchor_repricing_state_json": {
            "active_exchange_order_id": "exchange-1",
            "active_exchange_price": 77150.0,
            "active_placement_client_order_id": "placement-1",
            "pending_rearm": {
                "placement_client_order_id": "placement-1",
                "exchange_order_id": "exchange-1",
                "placement_size": 25.0,
                "desired_limit_price": 77110.0,
                "reprice_reason": "reference_price_updated_slide_step",
            },
        },
        "parent_order_id": None,
        "notes": "",
    }


def _manager_and_bridge(order: dict) -> tuple[StealthOrderManager, StealthOrderBridge]:
    manager = StealthOrderManager(db_client=None, log_callback=MagicMock())
    manager.db_client = object()
    manager.in_memory_orders[order["stealth_order_id"]] = order
    manager._placed_order_index["placement-1"] = order
    manager._update_stealth_order = MagicMock(return_value=True)
    manager._record_reveal_event = MagicMock(return_value=True)
    manager._dispatch_lifecycle_event = MagicMock()

    bridge = StealthOrderBridge.__new__(StealthOrderBridge)
    bridge.stealth_manager = manager
    bridge._order_action_locks_guard = threading.Lock()
    bridge._order_action_locks = {}
    return manager, bridge


def _guard_only_engine(bridge: StealthOrderBridge) -> OrderEngine:
    """Build only the ingress surface needed before the replay guard returns."""

    engine = OrderEngine.__new__(OrderEngine)
    engine.stealth_order_bridge = bridge
    engine.websocket_hooks = MagicMock()
    engine.normalize_product_type = MagicMock(return_value="FUTURE")
    engine._sync_stealth_exchange_order_id = MagicMock()
    engine.log_message = MagicMock()
    engine.build_event_log_payload = (
        lambda event, **details: {"event": event, **details}
    )
    engine._update_dashboard_order_status = MagicMock()
    return engine


def _stale_order(status: str, *, exchange_order_id: str = "exchange-1") -> dict:
    return {
        "client_order_id": "placement-1",
        "order_id": exchange_order_id,
        "product_id": "BIP-20DEC30-CDE",
        "status": status,
    }


@pytest.mark.parametrize(
    "stale_status",
    (
        OrderStatus.OPEN.value,
        OrderStatus.UPDATE.value,
        OrderStatus.PENDING.value,
    ),
)
@pytest.mark.parametrize("rerevealed", (False, True), ids=("hidden", "rerevealed"))
def test_exact_cancel_tombstone_blocks_stale_nonterminal_parent_replay(
    monkeypatch,
    stale_status,
    rerevealed,
):
    order = _revealed_order()
    manager, bridge = _manager_and_bridge(order)
    parent_statuses = {
        "placement-1": OrderStatus.OPEN.value,
        "stealth-1": OrderStatus.OPEN.value,
    }

    def update_parent_status(client_order_id, status):
        parent_statuses[str(client_order_id)] = status
        return 1

    monkeypatch.setattr(
        "core.stealth_order_manager.update_order_parent_status",
        update_parent_status,
    )

    # Exact/authenticated zero-fill cancellation owns the old child terminal
    # projection and returns the logical root to its hidden lifecycle.
    assert bridge.consume_anchor_rearm_cancellation(
        "placement-1",
        exchange_order_id="exchange-1",
    ) is StealthOrderStatus.HIDDEN
    assert order["revealed_orders"][0]["rearm_cancel_consumed"] is True
    assert parent_statuses == {
        "placement-1": OrderStatus.CANCELLED.value,
        "stealth-1": OrderStatus.PENDING.value,
    }

    expected_stealth_status = StealthOrderStatus.HIDDEN
    expected_root_status = OrderStatus.PENDING.value
    if rerevealed:
        order["status"] = StealthOrderStatus.REVEALED.value
        order["revealed_size"] = 25.0
        order["remaining_size"] = 0.0
        order["visibility_score"] = 1.0
        order["revealed_orders"].append(
            {
                "reveal_number": 2,
                "revealed_size": 25.0,
                "placement_price": 77110.0,
                "placed_order_id": "placement-2",
                "placement_client_order_id": "placement-2",
                "exchange_order_id": "exchange-2",
                "placement_success": True,
            }
        )
        state = order["anchor_repricing_state_json"]
        state["active_placement_client_order_id"] = "placement-2"
        state["active_exchange_order_id"] = "exchange-2"
        state["active_exchange_price"] = 77110.0
        manager._placed_order_index["placement-2"] = order
        parent_statuses["placement-2"] = OrderStatus.OPEN.value
        parent_statuses["stealth-1"] = OrderStatus.OPEN.value
        expected_stealth_status = StealthOrderStatus.REVEALED
        expected_root_status = OrderStatus.OPEN.value

    statuses_before_replay = dict(parent_statuses)
    engine = _guard_only_engine(bridge)
    engine.process_user_order(_stale_order(stale_status))

    # The stale row never reaches orderbook/progress/parent/dashboard routing.
    assert parent_statuses == statuses_before_replay
    assert parent_statuses["placement-1"] == OrderStatus.CANCELLED.value
    assert parent_statuses["stealth-1"] == expected_root_status
    engine._update_dashboard_order_status.assert_not_called()
    engine.websocket_hooks.call_post_order_status.assert_not_called()
    assert engine.log_message.call_args.args[1]["event"] == (
        "tombstoned_anchor_rearm_nonterminal_replay_ignored"
    )

    # A duplicate terminal cancellation is not suppressed. The canonical
    # consumer recognizes the same tombstone without rewriting current root
    # state or returning hidden inventory twice.
    assert bridge.consume_anchor_rearm_cancellation(
        "placement-1",
        exchange_order_id="exchange-1",
    ) is expected_stealth_status
    assert parent_statuses == statuses_before_replay


def test_tombstone_exchange_mismatch_pauses_and_still_suppresses_replay(
    monkeypatch,
):
    order = _revealed_order()
    order["anchor_repricing_state_json"].pop("pending_rearm")
    order["revealed_orders"][0]["rearm_cancel_consumed"] = True
    manager, bridge = _manager_and_bridge(order)
    controller = RuntimeController()
    assert controller.complete_startup() is True
    monkeypatch.setattr(
        "core.stealth_order_manager.get_runtime_controller",
        lambda: controller,
    )

    engine = _guard_only_engine(bridge)
    engine.process_user_order(
        _stale_order(OrderStatus.OPEN.value, exchange_order_id="exchange-other")
    )

    assert controller.state is EngineState.PAUSED
    assert engine.log_message.call_args.args[1]["event"] == (
        "tombstoned_anchor_rearm_nonterminal_replay_ignored"
    )
    assert any(
        call.args[1].get("event")
        == "stealth_anchor_rearm_tombstone_exchange_mismatch"
        for call in manager.log_callback.call_args_list
    )


def test_unauthenticated_move_audit_marker_is_not_a_rearm_tombstone():
    order = _revealed_order()
    order["anchor_repricing_state_json"].pop("pending_rearm")
    order["revealed_orders"][0]["cancelled_for_reprice"] = True
    manager, bridge = _manager_and_bridge(order)

    assert bridge.is_anchor_rearm_placement_tombstoned(
        "placement-1",
        exchange_order_id="exchange-1",
    ) is False

