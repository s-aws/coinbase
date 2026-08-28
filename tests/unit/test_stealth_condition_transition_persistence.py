"""Fail-closed persistence contracts for stealth condition transitions."""

from __future__ import annotations

from datetime import datetime, timedelta
import random
from unittest.mock import Mock

import pytest

import core.stealth_order_manager as manager_module
from core.enums import RevealConditionType, StealthOrderStatus
from core.exceptions import StealthOrderPersistenceError
from core.stealth_order_manager import StealthOrderManager


STEALTH_ORDER_ID = "condition-persistence-order"
PRODUCT_ID = "CONDITION-PERSISTENCE-PRODUCT"


def _manager_with_condition(
    condition_type: RevealConditionType,
    condition_config: dict,
) -> tuple[StealthOrderManager, dict]:
    log_callback = Mock()
    manager = StealthOrderManager(db_client=None, log_callback=log_callback)
    manager._dispatch_lifecycle_event = Mock()
    manager._schedule_invalidation_callback = Mock()
    manager._update_stealth_order = Mock(return_value=True)
    order = {
        "stealth_order_id": STEALTH_ORDER_ID,
        "product_id": PRODUCT_ID,
        "side": "BUY",
        "total_size": 1.0,
        "revealed_size": 0.0,
        "remaining_size": 1.0,
        "executed_size": 0.0,
        "limit_price": 100.0,
        "status": StealthOrderStatus.HIDDEN.value,
        "reveal_condition_type": condition_type.value,
        "reveal_condition_json": condition_config,
        "created_at": datetime.utcnow() - timedelta(seconds=30),
        "condition_first_met_at": None,
        "condition_confirmed_at": None,
        "revealed_orders": [],
        "reason": "condition_transition_persistence_test",
    }
    manager.in_memory_orders[STEALTH_ORDER_ID] = order
    log_callback.reset_mock()
    return manager, order


def _ticker() -> dict:
    return {
        "product_id": PRODUCT_ID,
        "price": 99.0,
        "bid": 98.0,
        "ask": 100.0,
        "volume_1m": 0.0,
        "time": datetime.utcnow(),
        "source": "ticker",
    }


@pytest.mark.parametrize("jitter_seconds", (0.0, 1.0))
def test_time_delay_trigger_failure_rolls_back_and_pauses(
    monkeypatch,
    jitter_seconds: float,
) -> None:
    manager, order = _manager_with_condition(
        RevealConditionType.TIME_DELAY,
        {
            "type": RevealConditionType.TIME_DELAY.value,
            "delay_seconds": 0.0,
            "jitter_seconds": jitter_seconds,
        },
    )
    manager._update_stealth_order.return_value = False
    controller = Mock()
    monkeypatch.setattr(
        manager_module,
        "get_runtime_controller",
        lambda: controller,
    )
    monkeypatch.setattr(random, "uniform", lambda _low, _high: 0.0)

    with pytest.raises(
        StealthOrderPersistenceError,
        match=(
            "condition TRIGGERED transition for time_delay stealth order "
            f"{STEALTH_ORDER_ID}"
        ),
    ):
        manager.evaluate_conditions(
            STEALTH_ORDER_ID,
            market_data=_ticker(),
        )

    assert order["status"] == StealthOrderStatus.HIDDEN.value
    assert order["condition_first_met_at"] is None
    assert order["condition_confirmed_at"] is None
    controller.request_pause.assert_called_once_with()
    manager.log_callback.assert_not_called()
    manager._dispatch_lifecycle_event.assert_not_called()
    manager._schedule_invalidation_callback.assert_not_called()


def test_composite_watching_failure_rolls_back_and_pauses(monkeypatch) -> None:
    manager, order = _manager_with_condition(
        RevealConditionType.COMPOSITE,
        {
            "type": RevealConditionType.COMPOSITE.value,
            "operator": "AND",
            "conditions": [
                {
                    "type": RevealConditionType.PRICE_THRESHOLD.value,
                    "direction": "below",
                    "price_threshold": 100.0,
                    "hold_duration_seconds": 2.0,
                }
            ],
        },
    )
    manager._update_stealth_order.return_value = False
    controller = Mock()
    monkeypatch.setattr(
        manager_module,
        "get_runtime_controller",
        lambda: controller,
    )

    with pytest.raises(
        StealthOrderPersistenceError,
        match=(
            "condition PENDING transition for composite stealth order "
            f"{STEALTH_ORDER_ID}"
        ),
    ):
        manager.evaluate_conditions(
            STEALTH_ORDER_ID,
            market_data=_ticker(),
        )

    assert order["status"] == StealthOrderStatus.HIDDEN.value
    assert order["condition_first_met_at"] is None
    assert order["condition_confirmed_at"] is None
    controller.request_pause.assert_called_once_with()
    manager.log_callback.assert_not_called()
    manager._dispatch_lifecycle_event.assert_not_called()
    manager._schedule_invalidation_callback.assert_not_called()


def test_condition_persistence_exception_restores_and_reraises(
    monkeypatch,
) -> None:
    manager, order = _manager_with_condition(
        RevealConditionType.TIME_DELAY,
        {
            "type": RevealConditionType.TIME_DELAY.value,
            "delay_seconds": 0.0,
            "jitter_seconds": 0.0,
        },
    )
    persistence_error = RuntimeError("synthetic persistence exception")
    manager._update_stealth_order.side_effect = persistence_error
    controller = Mock()
    monkeypatch.setattr(
        manager_module,
        "get_runtime_controller",
        lambda: controller,
    )

    with pytest.raises(RuntimeError) as raised:
        manager.evaluate_conditions(
            STEALTH_ORDER_ID,
            market_data=_ticker(),
        )

    assert raised.value is persistence_error
    assert order["status"] == StealthOrderStatus.HIDDEN.value
    assert order["condition_first_met_at"] is None
    assert order["condition_confirmed_at"] is None
    controller.request_pause.assert_called_once_with()
    manager.log_callback.assert_not_called()
    manager._dispatch_lifecycle_event.assert_not_called()
    manager._schedule_invalidation_callback.assert_not_called()
