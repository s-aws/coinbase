"""Behavioral contracts for continuous price/spread reveal holds.

These tests exercise ``StealthOrderManager.evaluate_conditions`` directly.
They deliberately avoid scheduler implementation details: the manager remains
the lifecycle authority, while the market snapshot's UTC ``time`` establishes
whether a qualifying condition has held continuously through its deadline.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import Mock

import pytest

import core.stealth_order_manager as manager_module
from business.stealth_condition_evaluator import get_evaluator
from core.enums import (
    RevealConditionType,
    StealthLifecycleEvent,
    StealthOrderStatus,
)
from core.exceptions import StealthOrderPersistenceError
from core.stealth_order_manager import StealthOrderManager


STEALTH_ORDER_ID = "11111111-2222-4333-8444-555555555555"
PRODUCT_ID = "TEST-HOLD-PRODUCT"
BASE_EVENT_TIME = datetime(2026, 8, 27, 12, 0, 0)


def _build_manager(condition_type: str, *, hold_seconds: float) -> StealthOrderManager:
    manager = StealthOrderManager(db_client=None, log_callback=Mock())
    manager._update_stealth_order = Mock(return_value=True)
    manager._dispatch_lifecycle_event = Mock()

    if condition_type == RevealConditionType.PRICE_THRESHOLD.value:
        condition = {
            "type": condition_type,
            "direction": "below",
            "price_threshold": 100.0,
            "hold_duration_seconds": hold_seconds,
        }
    elif condition_type == RevealConditionType.SPREAD.value:
        condition = {
            "type": condition_type,
            "max_spread": 1.0,
            "hold_duration_seconds": hold_seconds,
        }
    else:  # pragma: no cover - helper misuse is a test-author error
        raise AssertionError(f"Unsupported fixture condition: {condition_type}")

    manager.in_memory_orders[STEALTH_ORDER_ID] = {
        "stealth_order_id": STEALTH_ORDER_ID,
        "product_id": PRODUCT_ID,
        "side": "BUY",
        "total_size": 1.0,
        "revealed_size": 0.0,
        "remaining_size": 1.0,
        "executed_size": 0.0,
        "limit_price": 100.0,
        "status": StealthOrderStatus.HIDDEN.value,
        "reveal_condition_type": condition_type,
        "reveal_condition_json": condition,
        "revealed_orders": [],
        "reason": "continuous_hold_test",
        "parent_order_id": None,
        "condition_first_met_at": None,
        "condition_confirmed_at": None,
    }
    return manager


def _market_snapshot(
    condition_type: str,
    *,
    condition_true: bool,
    event_time: datetime,
) -> dict[str, Any]:
    if condition_type == RevealConditionType.PRICE_THRESHOLD.value:
        price = 99.0 if condition_true else 101.0
        return {
            "product_id": PRODUCT_ID,
            "price": price,
            "bid": price - 0.5,
            "ask": price + 0.5,
            "volume_1m": 1.0,
            "time": event_time,
            "source": "ticker",
        }

    spread = 0.5 if condition_true else 2.0
    return {
        "product_id": PRODUCT_ID,
        "price": 100.0,
        "bid": 100.0,
        "ask": 100.0 + spread,
        "volume_1m": 1.0,
        "time": event_time,
        "source": "ticker",
    }


def _publish(
    manager: StealthOrderManager,
    condition_type: str,
    *,
    condition_true: bool,
    event_time: datetime,
) -> None:
    manager.publish_market_data(
        PRODUCT_ID,
        _market_snapshot(
            condition_type,
            condition_true=condition_true,
            event_time=event_time,
        ),
    )


def _lifecycle_events(manager: StealthOrderManager) -> list[StealthLifecycleEvent]:
    return [
        call.kwargs["event"]
        for call in manager._dispatch_lifecycle_event.call_args_list
    ]


@pytest.mark.parametrize(
    "condition_type",
    (
        RevealConditionType.PRICE_THRESHOLD.value,
        RevealConditionType.SPREAD.value,
    ),
)
def test_first_true_event_arms_pending_hold(condition_type: str) -> None:
    manager = _build_manager(condition_type, hold_seconds=2)
    _publish(
        manager,
        condition_type,
        condition_true=True,
        event_time=BASE_EVENT_TIME,
    )

    condition_met, _ = manager.evaluate_conditions(STEALTH_ORDER_ID)

    order = manager.in_memory_orders[STEALTH_ORDER_ID]
    assert condition_met is False
    assert order["status"] == StealthOrderStatus.PENDING.value
    assert order["condition_first_met_at"] == BASE_EVENT_TIME
    assert order["condition_confirmed_at"] is None
    assert _lifecycle_events(manager) == [
        StealthLifecycleEvent.CONDITION_WATCHING
    ]
    manager._update_stealth_order.assert_called_once_with(order)


def test_lifecycle_audit_uses_causal_fifo_snapshot_not_newer_cache() -> None:
    manager = _build_manager(
        RevealConditionType.PRICE_THRESHOLD.value,
        hold_seconds=2,
    )
    causal_snapshot = _market_snapshot(
        RevealConditionType.PRICE_THRESHOLD.value,
        condition_true=True,
        event_time=BASE_EVENT_TIME,
    )
    newer_snapshot = dict(causal_snapshot)
    newer_snapshot.update(
        {
            "price": 97.0,
            "bid": 96.5,
            "ask": 97.5,
            "time": BASE_EVENT_TIME + timedelta(seconds=1),
        }
    )
    manager.publish_market_data(PRODUCT_ID, newer_snapshot)

    manager.evaluate_conditions(
        STEALTH_ORDER_ID,
        market_data=causal_snapshot,
        evaluation_time=BASE_EVENT_TIME,
    )

    lifecycle_call = manager._dispatch_lifecycle_event.call_args
    assert lifecycle_call.kwargs["event"] == (
        StealthLifecycleEvent.CONDITION_WATCHING
    )
    assert lifecycle_call.kwargs["extra"]["market_price"] == 99.0
    assert lifecycle_call.kwargs["extra"]["market_bid"] == 98.5
    assert lifecycle_call.kwargs["extra"]["market_ask"] == 99.5
    assert lifecycle_call.kwargs["extra"]["timestamp"] == BASE_EVENT_TIME


@pytest.mark.parametrize(
    "condition_type",
    (
        RevealConditionType.PRICE_THRESHOLD.value,
        RevealConditionType.SPREAD.value,
    ),
)
def test_false_event_resets_pending_hold_and_dispatches_reset(
    condition_type: str,
) -> None:
    manager = _build_manager(condition_type, hold_seconds=2)
    _publish(
        manager,
        condition_type,
        condition_true=True,
        event_time=BASE_EVENT_TIME,
    )
    manager.evaluate_conditions(STEALTH_ORDER_ID)

    _publish(
        manager,
        condition_type,
        condition_true=False,
        event_time=BASE_EVENT_TIME + timedelta(seconds=1),
    )
    condition_met, _ = manager.evaluate_conditions(STEALTH_ORDER_ID)

    order = manager.in_memory_orders[STEALTH_ORDER_ID]
    assert condition_met is False
    assert order["status"] == StealthOrderStatus.HIDDEN.value
    assert order["condition_first_met_at"] is None
    assert order["condition_confirmed_at"] is None
    assert _lifecycle_events(manager) == [
        StealthLifecycleEvent.CONDITION_WATCHING,
        StealthLifecycleEvent.CONDITION_RESET,
    ]
    assert manager._update_stealth_order.call_count == 2


@pytest.mark.parametrize(
    "condition_type",
    (
        RevealConditionType.PRICE_THRESHOLD.value,
        RevealConditionType.SPREAD.value,
    ),
)
def test_unusable_ordered_market_event_resets_pending_hold(
    condition_type: str,
) -> None:
    manager = _build_manager(condition_type, hold_seconds=2)
    _publish(
        manager,
        condition_type,
        condition_true=True,
        event_time=BASE_EVENT_TIME,
    )
    manager.evaluate_conditions(STEALTH_ORDER_ID)

    unusable = _market_snapshot(
        condition_type,
        condition_true=True,
        event_time=BASE_EVENT_TIME + timedelta(seconds=1),
    )
    if condition_type == RevealConditionType.PRICE_THRESHOLD.value:
        unusable["price"] = 0
    else:
        unusable["bid"] = 0
    manager.publish_market_data(PRODUCT_ID, unusable)

    condition_met, _ = manager.evaluate_conditions(STEALTH_ORDER_ID)

    order = manager.in_memory_orders[STEALTH_ORDER_ID]
    assert condition_met is False
    assert order["status"] == StealthOrderStatus.HIDDEN.value
    assert order["condition_first_met_at"] is None
    assert order["condition_confirmed_at"] is None
    assert _lifecycle_events(manager)[-1] == (
        StealthLifecycleEvent.CONDITION_RESET
    )


@pytest.mark.parametrize(
    "condition_type",
    (
        RevealConditionType.PRICE_THRESHOLD.value,
        RevealConditionType.SPREAD.value,
    ),
)
def test_true_false_true_starts_a_new_hold_deadline(condition_type: str) -> None:
    manager = _build_manager(condition_type, hold_seconds=2)
    second_true_at = BASE_EVENT_TIME + timedelta(seconds=1)

    _publish(
        manager,
        condition_type,
        condition_true=True,
        event_time=BASE_EVENT_TIME,
    )
    manager.evaluate_conditions(STEALTH_ORDER_ID)
    _publish(
        manager,
        condition_type,
        condition_true=False,
        event_time=BASE_EVENT_TIME + timedelta(milliseconds=500),
    )
    manager.evaluate_conditions(STEALTH_ORDER_ID)
    _publish(
        manager,
        condition_type,
        condition_true=True,
        event_time=second_true_at,
    )
    condition_met, _ = manager.evaluate_conditions(STEALTH_ORDER_ID)

    order = manager.in_memory_orders[STEALTH_ORDER_ID]
    deadline = get_evaluator(condition_type).resolve_stable_deadline(
        order["reveal_condition_json"],
        order,
    )
    assert condition_met is False
    assert order["status"] == StealthOrderStatus.PENDING.value
    assert order["condition_first_met_at"] == second_true_at
    assert deadline.available is True
    assert deadline.deadline_utc == second_true_at + timedelta(seconds=2)
    assert _lifecycle_events(manager) == [
        StealthLifecycleEvent.CONDITION_WATCHING,
        StealthLifecycleEvent.CONDITION_RESET,
        StealthLifecycleEvent.CONDITION_WATCHING,
    ]


@pytest.mark.parametrize(
    "condition_type",
    (
        RevealConditionType.PRICE_THRESHOLD.value,
        RevealConditionType.SPREAD.value,
    ),
)
def test_zero_hold_triggers_on_first_qualifying_market_event(
    condition_type: str,
) -> None:
    manager = _build_manager(condition_type, hold_seconds=0)
    _publish(
        manager,
        condition_type,
        condition_true=True,
        event_time=BASE_EVENT_TIME,
    )

    condition_met, _ = manager.evaluate_conditions(STEALTH_ORDER_ID)

    order = manager.in_memory_orders[STEALTH_ORDER_ID]
    assert condition_met is True
    assert order["status"] == StealthOrderStatus.TRIGGERED.value
    assert order["condition_first_met_at"] == BASE_EVENT_TIME
    assert order["condition_confirmed_at"] == BASE_EVENT_TIME
    assert _lifecycle_events(manager) == [StealthLifecycleEvent.CONDITION_MET]
    manager._update_stealth_order.assert_called_once_with(order)


@pytest.mark.parametrize(
    "condition_type",
    (
        RevealConditionType.PRICE_THRESHOLD.value,
        RevealConditionType.SPREAD.value,
    ),
)
def test_stale_market_event_at_due_wake_cannot_confirm(
    condition_type: str,
) -> None:
    manager = _build_manager(condition_type, hold_seconds=2)
    order = manager.in_memory_orders[STEALTH_ORDER_ID]
    order["status"] = StealthOrderStatus.PENDING.value
    order["condition_first_met_at"] = BASE_EVENT_TIME
    _publish(
        manager,
        condition_type,
        condition_true=True,
        event_time=BASE_EVENT_TIME,
    )

    condition_met, _ = manager.evaluate_conditions(STEALTH_ORDER_ID)

    assert condition_met is False
    assert order["status"] == StealthOrderStatus.PENDING.value
    assert order["condition_first_met_at"] == BASE_EVENT_TIME
    assert order["condition_confirmed_at"] is None
    assert _lifecycle_events(manager) == []
    manager._update_stealth_order.assert_not_called()


@pytest.mark.parametrize(
    "condition_type",
    (
        RevealConditionType.PRICE_THRESHOLD.value,
        RevealConditionType.SPREAD.value,
    ),
)
def test_market_event_at_exact_hold_deadline_confirms(condition_type: str) -> None:
    manager = _build_manager(condition_type, hold_seconds=2)
    order = manager.in_memory_orders[STEALTH_ORDER_ID]
    order["status"] = StealthOrderStatus.PENDING.value
    order["condition_first_met_at"] = BASE_EVENT_TIME
    exact_deadline = BASE_EVENT_TIME + timedelta(seconds=2)
    _publish(
        manager,
        condition_type,
        condition_true=True,
        event_time=exact_deadline,
    )

    condition_met, _ = manager.evaluate_conditions(STEALTH_ORDER_ID)

    assert condition_met is True
    assert order["status"] == StealthOrderStatus.TRIGGERED.value
    assert order["condition_first_met_at"] == BASE_EVENT_TIME
    assert order["condition_confirmed_at"] == exact_deadline
    assert _lifecycle_events(manager) == [StealthLifecycleEvent.CONDITION_MET]
    manager._update_stealth_order.assert_called_once_with(order)


def test_price_condition_edit_resets_an_in_progress_hold() -> None:
    manager = _build_manager(
        RevealConditionType.PRICE_THRESHOLD.value,
        hold_seconds=2,
    )
    order = manager.in_memory_orders[STEALTH_ORDER_ID]
    order["status"] = StealthOrderStatus.PENDING.value
    order["condition_first_met_at"] = BASE_EVENT_TIME

    assert manager.sync_price_condition_to_cache(
        STEALTH_ORDER_ID,
        price_threshold=98.0,
        hold_duration_seconds=5,
    )

    assert order["reveal_condition_json"]["price_threshold"] == 98.0
    assert order["reveal_condition_json"]["hold_duration_seconds"] == 5
    assert order["status"] == StealthOrderStatus.HIDDEN.value
    assert order["condition_first_met_at"] is None
    assert order["condition_confirmed_at"] is None
    assert _lifecycle_events(manager) == [StealthLifecycleEvent.CONDITION_RESET]
    manager._update_stealth_order.assert_called_once_with(order)


def test_price_condition_edit_does_not_rollback_a_committed_trigger() -> None:
    manager = _build_manager(
        RevealConditionType.PRICE_THRESHOLD.value,
        hold_seconds=2,
    )
    schedule_change = Mock()
    manager.set_schedule_invalidation_callback(schedule_change)
    order = manager.in_memory_orders[STEALTH_ORDER_ID]
    order["status"] = StealthOrderStatus.TRIGGERED.value
    order["condition_first_met_at"] = BASE_EVENT_TIME
    order["condition_confirmed_at"] = BASE_EVENT_TIME + timedelta(seconds=2)

    assert manager.sync_price_condition_to_cache(
        STEALTH_ORDER_ID,
        price_threshold=98.0,
        hold_duration_seconds=5,
    )

    assert order["status"] == StealthOrderStatus.TRIGGERED.value
    assert order["condition_first_met_at"] == BASE_EVENT_TIME
    assert order["condition_confirmed_at"] == BASE_EVENT_TIME + timedelta(
        seconds=2
    )
    assert _lifecycle_events(manager) == []
    manager._update_stealth_order.assert_called_once_with(order)
    schedule_change.assert_called_once_with(STEALTH_ORDER_ID)


def test_price_condition_update_failure_restores_config_and_pauses(
    monkeypatch,
) -> None:
    manager = _build_manager(
        RevealConditionType.PRICE_THRESHOLD.value,
        hold_seconds=2,
    )
    order = manager.in_memory_orders[STEALTH_ORDER_ID]
    original_condition = dict(order["reveal_condition_json"])
    original_updated_at = order.get("updated_at")
    manager._update_stealth_order = Mock(return_value=False)
    controller = Mock()
    monkeypatch.setattr(
        manager_module,
        "get_runtime_controller",
        lambda: controller,
    )

    with pytest.raises(
        StealthOrderPersistenceError,
        match="Failed to persist price-condition update",
    ):
        manager.update_price_condition(
            STEALTH_ORDER_ID,
            price_threshold=98.0,
            hold_duration_seconds=5,
        )

    assert order["reveal_condition_json"] == original_condition
    assert order.get("updated_at") == original_updated_at
    controller.request_pause.assert_called_once_with()


def test_revealed_order_cannot_be_rehidden_by_continuity_reset() -> None:
    manager = _build_manager(
        RevealConditionType.PRICE_THRESHOLD.value,
        hold_seconds=2,
    )
    order = manager.in_memory_orders[STEALTH_ORDER_ID]
    order["status"] = StealthOrderStatus.REVEALED.value
    order["remaining_size"] = 0.0
    order["revealed_size"] = 1.0
    order["condition_first_met_at"] = BASE_EVENT_TIME
    order["condition_confirmed_at"] = BASE_EVENT_TIME + timedelta(seconds=2)
    order["anchor_repricing_state_json"] = {
        "active_exchange_order_id": "exchange-live",
        "active_placement_client_order_id": "placement-live",
    }

    assert manager.reset_continuous_condition(
        STEALTH_ORDER_ID,
        reason="synthetic continuity loss",
    ) is False

    assert order["status"] == StealthOrderStatus.REVEALED.value
    assert order["condition_first_met_at"] == BASE_EVENT_TIME
    assert order["condition_confirmed_at"] == (
        BASE_EVENT_TIME + timedelta(seconds=2)
    )
    assert order["anchor_repricing_state_json"][
        "active_exchange_order_id"
    ] == "exchange-live"


def test_continuity_reset_persistence_failure_rolls_back_and_pauses(
    monkeypatch,
) -> None:
    manager = _build_manager(
        RevealConditionType.PRICE_THRESHOLD.value,
        hold_seconds=2,
    )
    order = manager.in_memory_orders[STEALTH_ORDER_ID]
    order["status"] = StealthOrderStatus.PENDING.value
    order["condition_first_met_at"] = BASE_EVENT_TIME
    order["condition_confirmed_at"] = BASE_EVENT_TIME + timedelta(seconds=2)
    manager._update_stealth_order = Mock(return_value=False)
    manager._schedule_invalidation_callback = Mock()
    controller = Mock()
    monkeypatch.setattr(
        manager_module,
        "get_runtime_controller",
        lambda: controller,
    )

    with pytest.raises(
        StealthOrderPersistenceError,
        match="Failed to persist continuous-condition reset",
    ):
        manager.reset_continuous_condition(
            STEALTH_ORDER_ID,
            reason="synthetic continuity loss",
        )

    assert order["status"] == StealthOrderStatus.PENDING.value
    assert order["condition_first_met_at"] == BASE_EVENT_TIME
    assert order["condition_confirmed_at"] == (
        BASE_EVENT_TIME + timedelta(seconds=2)
    )
    controller.request_pause.assert_called_once_with()
    manager._dispatch_lifecycle_event.assert_not_called()
    manager._schedule_invalidation_callback.assert_not_called()


def test_pending_transition_persistence_failure_rolls_back_and_pauses(
    monkeypatch,
) -> None:
    manager = _build_manager(
        RevealConditionType.PRICE_THRESHOLD.value,
        hold_seconds=2,
    )
    order = manager.in_memory_orders[STEALTH_ORDER_ID]
    manager._update_stealth_order = Mock(return_value=False)
    manager._schedule_invalidation_callback = Mock()
    controller = Mock()
    monkeypatch.setattr(
        manager_module,
        "get_runtime_controller",
        lambda: controller,
    )
    _publish(
        manager,
        RevealConditionType.PRICE_THRESHOLD.value,
        condition_true=True,
        event_time=BASE_EVENT_TIME,
    )

    with pytest.raises(
        StealthOrderPersistenceError,
        match="condition PENDING transition for price stealth order",
    ):
        manager.evaluate_conditions(STEALTH_ORDER_ID)

    assert order["status"] == StealthOrderStatus.HIDDEN.value
    assert order["condition_first_met_at"] is None
    assert order["condition_confirmed_at"] is None
    controller.request_pause.assert_called_once_with()
    manager._dispatch_lifecycle_event.assert_not_called()
    manager._schedule_invalidation_callback.assert_not_called()


def test_triggered_transition_persistence_failure_rolls_back_and_pauses(
    monkeypatch,
) -> None:
    manager = _build_manager(
        RevealConditionType.PRICE_THRESHOLD.value,
        hold_seconds=2,
    )
    order = manager.in_memory_orders[STEALTH_ORDER_ID]
    order["status"] = StealthOrderStatus.PENDING.value
    order["condition_first_met_at"] = BASE_EVENT_TIME
    manager._update_stealth_order = Mock(return_value=False)
    manager._schedule_invalidation_callback = Mock()
    controller = Mock()
    monkeypatch.setattr(
        manager_module,
        "get_runtime_controller",
        lambda: controller,
    )
    _publish(
        manager,
        RevealConditionType.PRICE_THRESHOLD.value,
        condition_true=True,
        event_time=BASE_EVENT_TIME + timedelta(seconds=2),
    )

    with pytest.raises(
        StealthOrderPersistenceError,
        match="condition TRIGGERED transition for price stealth order",
    ):
        manager.evaluate_conditions(STEALTH_ORDER_ID)

    assert order["status"] == StealthOrderStatus.PENDING.value
    assert order["condition_first_met_at"] == BASE_EVENT_TIME
    assert order["condition_confirmed_at"] is None
    controller.request_pause.assert_called_once_with()
    manager._dispatch_lifecycle_event.assert_not_called()
    manager._schedule_invalidation_callback.assert_not_called()


def test_fixed_time_delay_ignores_future_exchange_event_time() -> None:
    manager = StealthOrderManager(db_client=None, log_callback=Mock())
    manager._update_stealth_order = Mock(return_value=True)
    manager._dispatch_lifecycle_event = Mock()
    created_at = datetime.utcnow() + timedelta(seconds=30)
    manager.in_memory_orders[STEALTH_ORDER_ID] = {
        "stealth_order_id": STEALTH_ORDER_ID,
        "product_id": PRODUCT_ID,
        "side": "BUY",
        "total_size": 1.0,
        "revealed_size": 0.0,
        "remaining_size": 1.0,
        "executed_size": 0.0,
        "limit_price": 100.0,
        "status": StealthOrderStatus.HIDDEN.value,
        "reveal_condition_type": RevealConditionType.TIME_DELAY.value,
        "reveal_condition_json": {
            "type": RevealConditionType.TIME_DELAY.value,
            "delay_seconds": 0,
            "jitter_seconds": 0,
        },
        "created_at": created_at,
        "condition_first_met_at": None,
        "condition_confirmed_at": None,
        "revealed_orders": [],
        "reason": "fixed_time_clock_test",
    }
    future_exchange_time = created_at + timedelta(hours=1)
    snapshot = {
        "product_id": PRODUCT_ID,
        "price": 100.0,
        "bid": 99.0,
        "ask": 101.0,
        "time": future_exchange_time,
        "source": "ticker",
    }

    condition_met, _reason = manager.evaluate_conditions(
        STEALTH_ORDER_ID,
        market_data=snapshot,
        evaluation_time=future_exchange_time,
    )

    assert condition_met is False
    assert manager.in_memory_orders[STEALTH_ORDER_ID]["status"] == (
        StealthOrderStatus.HIDDEN.value
    )
    manager._update_stealth_order.assert_not_called()


def test_fixed_time_confirmation_uses_host_time_not_exchange_time() -> None:
    manager = StealthOrderManager(db_client=None, log_callback=Mock())
    manager._validate_local_price_read_only = Mock(return_value=True)
    manager._update_stealth_order = Mock(return_value=True)
    manager._dispatch_lifecycle_event = Mock()
    created_at = datetime.utcnow() - timedelta(seconds=1)
    manager.in_memory_orders[STEALTH_ORDER_ID] = {
        "stealth_order_id": STEALTH_ORDER_ID,
        "product_id": PRODUCT_ID,
        "side": "BUY",
        "total_size": 1.0,
        "revealed_size": 0.0,
        "remaining_size": 1.0,
        "executed_size": 0.0,
        "limit_price": 100.0,
        "status": StealthOrderStatus.HIDDEN.value,
        "reveal_condition_type": RevealConditionType.TIME_DELAY.value,
        "reveal_condition_json": {
            "type": RevealConditionType.TIME_DELAY.value,
            "delay_seconds": 0,
            "jitter_seconds": 0,
        },
        "created_at": created_at,
        "condition_first_met_at": None,
        "condition_confirmed_at": None,
        "revealed_orders": [],
        "reason": "fixed_time_confirmation_clock_test",
    }
    exchange_time = created_at + timedelta(hours=4)
    snapshot = {
        "product_id": PRODUCT_ID,
        "price": 100.0,
        "bid": 99.0,
        "ask": 101.0,
        "volume_1m": 0.0,
        "time": exchange_time,
        "source": "ticker",
    }
    before = datetime.utcnow()

    condition_met, _reason = manager.evaluate_conditions(
        STEALTH_ORDER_ID,
        market_data=snapshot,
        evaluation_time=exchange_time,
    )
    after = datetime.utcnow()

    assert condition_met is True
    assert before <= manager.in_memory_orders[STEALTH_ORDER_ID][
        "condition_confirmed_at"
    ] <= after
