from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.enums import OrderSide, StealthLifecycleEvent, StealthOrderStatus
from core.models import RevealExecutionPlan
from core.stealth_order_manager import StealthOrderManager


def _manager_with_triggered_order():
    manager = StealthOrderManager(db_client=None, log_callback=MagicMock())
    sid = "sid-reveal-failure"
    order = {
        "stealth_order_id": sid,
        "product_id": "BTC-USD",
        "side": OrderSide.BUY.value,
        "total_size": 1.0,
        "remaining_size": 1.0,
        "revealed_size": 0.0,
        "executed_size": 0.0,
        "limit_price": 100.0,
        "status": StealthOrderStatus.TRIGGERED.value,
        "reveal_condition_json": {"type": "time_delay", "delay_seconds": 0},
        "reveal_condition_type": "time_delay",
        "revealed_orders": [],
        "parent_order_id": None,
        "anchor_repricing_state_json": {},
    }
    manager.in_memory_orders[sid] = order
    manager.profit_validator = None
    manager._calculate_reveal_size = MagicMock(return_value=1.0)
    manager.build_reveal_execution_plan = MagicMock(
        return_value=RevealExecutionPlan(
            configured_limit_price=100.0,
            submitted_limit_price=100.0,
            reveal_pricing_policy="configured_limit",
            reveal_price_source="configured_limit",
            fallback_used=False,
        )
    )
    manager._evaluate_action_condition_guard = MagicMock(return_value=(True, None))
    manager._get_current_market_data = MagicMock(
        return_value={
            "price": 100.0,
            "bid": 99.9,
            "ask": 100.1,
            "volume_1m": 5.0,
            "source": "test",
        }
    )
    manager.order_placement_hooks = SimpleNamespace(
        call_pre_submission_hooks=MagicMock(),
        call_post_submission_hooks=MagicMock(),
    )
    manager._update_stealth_order = MagicMock()
    manager._record_reveal_event = MagicMock()
    manager._dispatch_lifecycle_event = MagicMock()
    return manager, sid, order


def _assert_failed_reveal_did_not_create_live_local_state(manager, sid, order):
    assert order["status"] == StealthOrderStatus.TRIGGERED.value
    assert order["revealed_size"] == 0.0
    assert order["remaining_size"] == 1.0
    if "visibility_score" in order:
        assert order["visibility_score"] == 0.0

    state = order.get("anchor_repricing_state_json") or {}
    assert state.get("active_placement_client_order_id") is None
    assert state.get("active_exchange_order_id") is None
    assert state.get("active_exchange_price") is None
    assert manager._placed_order_index == {}

    assert len(order["revealed_orders"]) == 1
    reveal_event = order["revealed_orders"][0]
    assert reveal_event["revealed_size"] == 0
    assert reveal_event["placement_success"] is False
    assert reveal_event["placement_status"] == "failed"
    assert reveal_event["exchange_order_id"] is None

    manager._record_reveal_event.assert_called_once_with(order, reveal_event)
    lifecycle_events = [
        call.kwargs["event"] for call in manager._dispatch_lifecycle_event.call_args_list
    ]
    assert StealthLifecycleEvent.REVEAL_FAILED in lifecycle_events


@pytest.mark.regression
def test_reveal_rest_exception_records_failure_without_live_state(monkeypatch):
    manager, sid, order = _manager_with_triggered_order()
    rest_client = SimpleNamespace(
        place_limit_order=MagicMock(side_effect=RuntimeError("network down"))
    )
    monkeypatch.setattr("configuration.REST_CLIENT", rest_client, raising=True)

    assert manager.reveal_order_slice(sid) is None

    rest_client.place_limit_order.assert_called_once()
    assert "network down" in order["revealed_orders"][0]["placement_error"]
    _assert_failed_reveal_did_not_create_live_local_state(manager, sid, order)


@pytest.mark.regression
def test_reveal_exchange_rejection_records_failure_without_live_state(monkeypatch):
    manager, sid, order = _manager_with_triggered_order()
    rest_client = SimpleNamespace(
        place_limit_order=MagicMock(
            return_value={
                "success": False,
                "failure_reason": "INSUFFICIENT_FUNDS",
            }
        )
    )
    monkeypatch.setattr("configuration.REST_CLIENT", rest_client, raising=True)

    assert manager.reveal_order_slice(sid) is None

    rest_client.place_limit_order.assert_called_once()
    assert "INSUFFICIENT_FUNDS" in order["revealed_orders"][0]["placement_error"]
    _assert_failed_reveal_did_not_create_live_local_state(manager, sid, order)
