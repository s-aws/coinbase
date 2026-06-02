from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch
from pathlib import Path

import pytest

from business.cancel_reentry_policy import CancelReentryRuntimeState
from core.enums import CancelReentryState, StealthOrderStatus
from core.stealth_order_manager import StealthOrderManager
from tests.unit.test_partial_fill_followups import _build_engine_for_partial_fill_tests


def _manager():
    manager = StealthOrderManager(db_client=None, log_callback=MagicMock())
    manager._save_stealth_order_to_db = MagicMock()
    manager._update_stealth_order = MagicMock()
    return manager


def _revealed_order():
    return {
        "stealth_order_id": "stealth-1",
        "product_id": "BTC-USDC",
        "side": "SELL",
        "total_size": 1.0,
        "remaining_size": 0.0,
        "revealed_size": 1.0,
        "executed_size": 0.0,
        "limit_price": 100.0,
        "status": StealthOrderStatus.REVEALED.value,
        "reveal_condition_json": {"type": "time_delay", "delay_seconds": 0},
        "anchor_repricing_state_json": {
            "active_placement_client_order_id": "placement-1",
            "active_exchange_order_id": "exchange-1",
            "active_exchange_price": 100.0,
        },
        "cancel_reentry_state_json": {"state": "resting"},
        "revealed_orders": [
            {
                "client_order_id": "placement-1",
                "order_id": "exchange-1",
                "price": 100.0,
                "size": 1.0,
            }
        ],
    }


def _evaluation():
    return SimpleNamespace(reason="distance 8 <= cancel_distance 8", reference_price=92.0, distance=8.0)


@pytest.mark.regression
def test_create_stealth_order_stores_cancel_reentry_policy(monkeypatch):
    manager = _manager()
    monkeypatch.setattr("core.stealth_order_manager.insert_order_parent", lambda **kwargs: None)

    stealth_id = manager.create_stealth_order(
        product_id="BTC-USDC",
        side="SELL",
        total_size=1.0,
        limit_price=100.0,
        reveal_condition={"type": "time_delay", "delay_seconds": 0},
        target_movement=0.0,
        cancel_reentry_policy={
            "enabled": True,
            "reference_price_source": "midpoint",
            "distance_type": "A",
            "cancel_distance": 8,
            "reentry_distance": 9,
        },
    )

    order = manager.in_memory_orders[stealth_id]
    assert order["cancel_reentry_policy_json"]["enabled"] is True
    assert order["cancel_reentry_policy_json"]["cancel_distance"] == 8
    assert order["cancel_reentry_state_json"]["state"] == CancelReentryState.RESTING.value


@pytest.mark.regression
def test_policy_cancel_hides_order_and_clears_active_exchange_pointer(monkeypatch):
    manager = _manager()
    order = _revealed_order()
    rest_client = MagicMock()
    monkeypatch.setattr("configuration.REST_CLIENT", rest_client, raising=True)
    manager._mark_reveal_event_cancelled_for_reprice = MagicMock()

    assert manager._apply_cancel_reentry_cancel(order, CancelReentryRuntimeState(), _evaluation()) is True

    rest_client.cancel_orders.assert_called_once_with(order_ids=["exchange-1"])
    assert order["status"] == StealthOrderStatus.HIDDEN.value
    assert order["remaining_size"] == 1.0
    assert order["revealed_size"] == 0.0
    assert order["anchor_repricing_state_json"]["active_exchange_order_id"] is None
    assert order["anchor_repricing_state_json"]["active_placement_client_order_id"] is None
    assert order["cancel_reentry_state_json"]["state"] == CancelReentryState.CANCELLED_BY_POLICY.value
    assert order["cancel_reentry_state_json"]["cancelled_placement_client_order_id"] == "placement-1"
    manager._update_stealth_order.assert_called_once_with(order)


@pytest.mark.regression
def test_policy_cancel_failure_leaves_revealed_order_intact(monkeypatch):
    manager = _manager()
    order = _revealed_order()
    rest_client = MagicMock()
    rest_client.cancel_orders.side_effect = RuntimeError("cancel failed")
    monkeypatch.setattr("configuration.REST_CLIENT", rest_client, raising=True)

    assert manager._apply_cancel_reentry_cancel(order, CancelReentryRuntimeState(), _evaluation()) is False

    assert order["status"] == StealthOrderStatus.REVEALED.value
    assert order["anchor_repricing_state_json"]["active_exchange_order_id"] == "exchange-1"
    assert order["cancel_reentry_state_json"]["state"] == CancelReentryState.RESTING.value
    manager._update_stealth_order.assert_not_called()


@pytest.mark.regression
def test_policy_reentry_uses_existing_reveal_path():
    manager = _manager()
    order = _revealed_order()
    order["status"] = StealthOrderStatus.HIDDEN.value
    order["remaining_size"] = 1.0
    order["revealed_size"] = 0.0
    order["cancel_reentry_state_json"] = {
        "state": CancelReentryState.CANCELLED_BY_POLICY.value,
        "cancelled_placement_client_order_id": "placement-1",
        "cancelled_exchange_order_id": "exchange-1",
        "reentry_count": 1,
    }
    manager.in_memory_orders[order["stealth_order_id"]] = order
    manager.reveal_order_slice = MagicMock(return_value="placement-2")

    state = CancelReentryRuntimeState.from_cancel_reentry_runtime_state_dict(
        order["cancel_reentry_state_json"]
    )
    assert manager._apply_cancel_reentry_reenter(order, state, _evaluation()) is True

    manager.reveal_order_slice.assert_called_once_with("stealth-1")
    assert order["cancel_reentry_state_json"]["state"] == CancelReentryState.RESTING.value
    assert order["cancel_reentry_state_json"]["reentry_count"] == 2


@pytest.mark.regression
def test_should_trigger_reveal_blocks_policy_cancelled_order():
    manager = _manager()
    order = _revealed_order()
    order["status"] = StealthOrderStatus.HIDDEN.value
    order["remaining_size"] = 1.0
    order["cancel_reentry_state_json"] = {
        "state": CancelReentryState.CANCELLED_BY_POLICY.value,
    }
    manager.in_memory_orders[order["stealth_order_id"]] = order

    should_reveal, reason = manager.should_trigger_reveal("stealth-1")

    assert should_reveal is False
    assert reason == "Order is waiting for cancel/re-entry threshold"


@pytest.mark.regression
def test_cancel_ack_for_policy_cancel_does_not_spawn_follow_up():
    engine = _build_engine_for_partial_fill_tests()
    placement_uuid = "placement-policy"
    stealth_root_id = "stealth-policy"
    engine.orderbook.child_order_ids[placement_uuid] = stealth_root_id
    engine.orderbook.parent_order_ids[stealth_root_id] = {
        "allow_partial_fills": False,
        "orders": [placement_uuid],
        "target_movement": {"movement": 0.001, "type": "P"},
        "max_order_replacement": 1,
        "current_order_replacement": 0,
        "externally_created": False,
    }
    engine.orderbook.should_replace = {"FILLED": True, "CANCELLED": True}

    stealth_record = {
        "stealth_order_id": stealth_root_id,
        "product_id": "BTC-USDC",
        "side": "SELL",
    }
    stealth_manager = Mock()
    stealth_manager.find_stealth_order_by_placed_order_id.return_value = stealth_record
    stealth_manager.is_policy_cancelled_placement.return_value = True
    stealth_manager.create_follow_up_stealth_order = Mock()
    stealth_bridge = Mock()
    stealth_bridge.stealth_manager = stealth_manager
    engine.stealth_order_bridge = stealth_bridge
    engine.complete_follow_up_processing = Mock(wraps=engine.complete_follow_up_processing)

    with patch("database.order.has_pending_move", return_value=False):
        engine.handle_cancelled_order(
            {
                "client_order_id": placement_uuid,
                "product_id": "BTC-USDC",
                "side": "SELL",
                "status": "CANCELLED",
                "price": 100.0,
            }
        )

    stealth_manager.create_follow_up_stealth_order.assert_not_called()
    engine.complete_follow_up_processing.assert_called_once_with("cancelled", placement_uuid)


@pytest.mark.regression
def test_stealth_manager_ui_sends_cancel_reentry_policy():
    repo_root = Path(__file__).resolve().parents[2]
    html = (repo_root / "ui_stealth_orders_manager.html").read_text(encoding="utf-8")

    assert 'id="enable_cancel_reentry_policy"' in html
    assert "function buildCancelReentryPolicy()" in html
    assert "cancel_reentry_policy: cancelReentryPolicy" in html
    assert "cancel_reentry_policy: order.cancel_reentry_policy_json" in html


@pytest.mark.regression
def test_cancel_reentry_runs_before_anchor_repricing_on_ticker():
    repo_root = Path(__file__).resolve().parents[2]
    source = (repo_root / "bridges" / "stealth_order_bridge.py").read_text(encoding="utf-8")

    cancel_idx = source.index("process_cancel_reentry_for_product")
    anchor_idx = source.index("process_anchor_repricing_for_product")
    assert cancel_idx < anchor_idx
