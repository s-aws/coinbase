"""Regression coverage for revealed anchor repricing.

A fully revealed order has ``remaining_size == 0`` because that field tracks
hidden inventory, not the size of the live exchange placement. Repricing must
therefore derive the cancellable size from the accepted reveal event, persist
its intent before REST, and wait for authenticated cancellation truth before
restoring the order to ``HIDDEN``.
"""

from datetime import datetime
from unittest.mock import MagicMock, call

import pytest

from core.enums import EngineState, StealthOrderStatus
from core.runtime_controller import RuntimeController
from core.stealth_order_manager import StealthOrderManager


def _revealed_order(*, executed_size: float = 0.0) -> dict:
    return {
        "stealth_order_id": "stealth-1",
        "product_id": "BIP-20DEC30-CDE",
        "side": "SELL",
        "total_size": 25.0,
        "revealed_size": 25.0,
        "remaining_size": 0.0,
        "executed_size": executed_size,
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
            "fixed_interval_seconds": 60,
            "min_price_change": 0.01,
            "hysteresis_bps": 0,
            "min_reprice_interval_seconds": 0,
            "max_reprices_per_hour": 20,
        },
        "anchor_repricing_state_json": {
            "active_exchange_order_id": "exchange-1",
            "active_exchange_price": 77150.0,
            "active_placement_client_order_id": "placement-1",
        },
        "parent_order_id": None,
        "notes": "",
    }


def _manager_for(order: dict) -> StealthOrderManager:
    manager = StealthOrderManager(db_client=None, log_callback=MagicMock())
    manager.in_memory_orders[order["stealth_order_id"]] = order
    manager._placed_order_index["placement-1"] = order
    manager._quantize_reprice_price = lambda _product, _side, price, **_kwargs: price
    manager._record_reveal_event = MagicMock(return_value=True)
    manager._dispatch_lifecycle_event = MagicMock()
    return manager


@pytest.mark.regression
def test_fully_revealed_reprice_persists_cancel_intent_without_replacement(
    monkeypatch,
):
    order = _revealed_order()
    manager = _manager_for(order)
    operations = []

    def persist(current):
        assert current["status"] == StealthOrderStatus.REVEALED.value
        assert current["anchor_repricing_state_json"]["pending_rearm"][
            "placement_client_order_id"
        ] == "placement-1"
        operations.append("persist")
        return True

    def cancel_orders(order_ids):
        assert operations == ["persist"]
        operations.append("cancel")
        return [{"success": True, "order_id": order_ids[0]}]

    manager._update_stealth_order = MagicMock(side_effect=persist)
    rest_client = MagicMock()
    rest_client.cancel_orders.side_effect = cancel_orders
    monkeypatch.setattr("configuration.REST_CLIENT", rest_client)

    result = manager._apply_revealed_anchor_reprice(
        order=order,
        policy=order["anchor_repricing_policy_json"],
        state=order["anchor_repricing_state_json"],
        market_data={"bid": 77105.0, "ask": 77115.0, "price": 77110.0},
        desired_price=77110.0,
        target_price=77110.0,
        max_boundary_price=77200.0,
        reprice_reason="reference_price_updated_slide_step",
    )

    assert result is True
    assert operations == ["persist", "cancel"]
    assert order["status"] == StealthOrderStatus.REVEALED.value
    assert order["remaining_size"] == 0.0
    assert order["revealed_size"] == 25.0
    state = order["anchor_repricing_state_json"]
    assert state["active_placement_client_order_id"] == "placement-1"
    assert state["active_exchange_order_id"] == "exchange-1"
    assert state["pending_rearm"]["placement_size"] == 25.0
    rest_client.place_limit_order.assert_not_called()

    # The durable placement client_order_id is also the duplicate-work guard.
    assert manager._apply_revealed_anchor_reprice(
        order,
        order["anchor_repricing_policy_json"],
        state,
        {},
        77100.0,
        77100.0,
        77200.0,
        "duplicate",
    ) is False
    rest_client.cancel_orders.assert_called_once()


@pytest.mark.regression
def test_reprice_skips_terminal_fill_truth(monkeypatch):
    order = _revealed_order(executed_size=25.0)
    manager = _manager_for(order)
    manager._update_stealth_order = MagicMock(return_value=True)
    rest_client = MagicMock()
    monkeypatch.setattr("configuration.REST_CLIENT", rest_client)

    result = manager._apply_revealed_anchor_reprice(
        order,
        order["anchor_repricing_policy_json"],
        order["anchor_repricing_state_json"],
        {},
        77110.0,
        77110.0,
        77200.0,
        "reference_price_updated_slide_step",
    )

    assert result is False
    assert "pending_rearm" not in order["anchor_repricing_state_json"]
    rest_client.cancel_orders.assert_not_called()
    rest_client.place_limit_order.assert_not_called()


@pytest.mark.regression
def test_reprice_refuses_to_hide_when_one_cancel_cannot_cover_revealed_size(
    monkeypatch,
):
    order = _revealed_order()
    order["revealed_orders"][0]["revealed_size"] = 15.0
    manager = _manager_for(order)
    manager._update_stealth_order = MagicMock(return_value=True)
    rest_client = MagicMock()
    monkeypatch.setattr("configuration.REST_CLIENT", rest_client)

    result = manager._apply_revealed_anchor_reprice(
        order,
        order["anchor_repricing_policy_json"],
        order["anchor_repricing_state_json"],
        {},
        77110.0,
        77110.0,
        77200.0,
        "reference_price_updated_slide_step",
    )

    assert result is False
    assert order["status"] == StealthOrderStatus.REVEALED.value
    assert "pending_rearm" not in order["anchor_repricing_state_json"]
    rest_client.cancel_orders.assert_not_called()


@pytest.mark.regression
@pytest.mark.parametrize(
    ("cancel_outcome", "expected_result", "pending_retained"),
    (
        ([{"success": False, "order_id": "exchange-1"}], False, True),
        (TimeoutError("cancel response lost"), True, True),
    ),
)
def test_cancel_outcome_retains_intent_until_exact_terminal_truth(
    monkeypatch,
    cancel_outcome,
    expected_result,
    pending_retained,
):
    order = _revealed_order()
    manager = _manager_for(order)
    manager._update_stealth_order = MagicMock(return_value=True)
    rest_client = MagicMock()
    if isinstance(cancel_outcome, Exception):
        rest_client.cancel_orders.side_effect = cancel_outcome
    else:
        rest_client.cancel_orders.return_value = cancel_outcome
    monkeypatch.setattr("configuration.REST_CLIENT", rest_client)

    result = manager._apply_revealed_anchor_reprice(
        order,
        order["anchor_repricing_policy_json"],
        order["anchor_repricing_state_json"],
        {},
        77110.0,
        77110.0,
        77200.0,
        "reference_price_updated_slide_step",
    )

    assert result is expected_result
    assert (
        "pending_rearm" in order["anchor_repricing_state_json"]
    ) is pending_retained
    assert order["status"] == StealthOrderStatus.REVEALED.value
    assert order["anchor_repricing_state_json"][
        "active_exchange_order_id"
    ] == "exchange-1"
    rest_client.place_limit_order.assert_not_called()


@pytest.mark.regression
def test_cancel_ack_restores_hidden_inventory_and_is_idempotent(monkeypatch):
    order = _revealed_order()
    state = order["anchor_repricing_state_json"]
    state["pending_rearm"] = {
        "placement_client_order_id": "placement-1",
        "placement_size": 25.0,
        "desired_limit_price": 77110.0,
        "target_price": 77110.0,
        "max_boundary_price": 77200.0,
        "reprice_reason": "reference_price_updated_slide_step",
        "next_reprice_at": "2026-09-13T12:01:00",
    }
    manager = _manager_for(order)
    manager.db_client = object()
    manager._update_stealth_order = MagicMock(return_value=True)
    update_parent_status = MagicMock(return_value=1)
    monkeypatch.setattr(
        "core.stealth_order_manager.update_order_parent_status",
        update_parent_status,
    )

    result = manager.consume_anchor_rearm_cancellation(
        "placement-1",
        exchange_order_id="exchange-1",
    )

    assert result is StealthOrderStatus.HIDDEN
    assert order["status"] == StealthOrderStatus.HIDDEN.value
    assert order["revealed_size"] == 0.0
    assert order["remaining_size"] == 25.0
    assert order["visibility_score"] == 0.0
    assert order["limit_price"] == 77110.0
    assert order["condition_first_met_at"] is None
    assert order["condition_confirmed_at"] is None
    state = order["anchor_repricing_state_json"]
    assert "pending_rearm" not in state
    assert state["active_placement_client_order_id"] is None
    assert state["active_exchange_order_id"] is None
    assert state["reveal_armed_at"]
    assert order["revealed_orders"][0]["cancelled_for_reprice"] is True
    assert update_parent_status.call_args_list == [
        call("placement-1", "CANCELLED"),
        call("stealth-1", "PENDING"),
    ]

    # A replayed terminal event cannot restore the same quantity twice.
    assert manager.consume_anchor_rearm_cancellation(
        "placement-1",
        exchange_order_id="exchange-1",
    ) is StealthOrderStatus.HIDDEN
    assert order["remaining_size"] == 25.0
    assert order["revealed_size"] == 0.0
    assert order["visibility_score"] == 0.0
    assert manager._update_stealth_order.call_count == 1


@pytest.mark.regression
def test_cancel_ack_retains_rearm_if_parent_projection_is_incomplete(
    monkeypatch,
):
    order = _revealed_order()
    order["anchor_repricing_state_json"]["pending_rearm"] = {
        "placement_client_order_id": "placement-1",
        "placement_size": 25.0,
        "desired_limit_price": 77110.0,
        "reprice_reason": "reference_price_updated_slide_step",
    }
    manager = _manager_for(order)
    manager.db_client = object()
    manager._update_stealth_order = MagicMock(return_value=True)
    update_parent_status = MagicMock(side_effect=(1, 0))
    monkeypatch.setattr(
        "core.stealth_order_manager.update_order_parent_status",
        update_parent_status,
    )
    controller = RuntimeController()
    assert controller.complete_startup() is True
    monkeypatch.setattr(
        "core.stealth_order_manager.get_runtime_controller",
        lambda: controller,
    )

    result = manager.consume_anchor_rearm_cancellation(
        "placement-1",
        exchange_order_id="exchange-1",
    )

    assert result is StealthOrderStatus.REVEALED
    assert order["status"] == StealthOrderStatus.REVEALED.value
    assert "pending_rearm" in order["anchor_repricing_state_json"]
    manager._update_stealth_order.assert_not_called()
    assert controller.state is EngineState.PAUSED


@pytest.mark.regression
def test_root_backed_placement_can_rearm_into_fresh_child_cycle(monkeypatch):
    order = _revealed_order()
    event = order["revealed_orders"][0]
    event["placed_order_id"] = "stealth-1"
    event["placement_client_order_id"] = "stealth-1"
    state = order["anchor_repricing_state_json"]
    state["active_placement_client_order_id"] = "stealth-1"
    state["pending_rearm"] = {
        "placement_client_order_id": "stealth-1",
        "placement_size": 25.0,
        "desired_limit_price": 77110.0,
        "reprice_reason": "reference_price_updated_slide_step",
    }
    manager = _manager_for(order)
    manager._placed_order_index["stealth-1"] = order
    manager.db_client = object()
    manager._update_stealth_order = MagicMock(return_value=True)
    update_parent_status = MagicMock(return_value=1)
    monkeypatch.setattr(
        "core.stealth_order_manager.update_order_parent_status",
        update_parent_status,
    )

    result = manager.consume_anchor_rearm_cancellation(
        "stealth-1",
        exchange_order_id="exchange-1",
    )

    assert result is StealthOrderStatus.HIDDEN
    assert order["remaining_size"] == 25.0
    update_parent_status.assert_called_once_with("stealth-1", "PENDING")
    assert manager._placement_client_order_id_for_order(order) != "stealth-1"


@pytest.mark.regression
def test_fill_observed_on_cancel_ack_wins_over_rearm():
    order = _revealed_order()
    order["anchor_repricing_state_json"]["pending_rearm"] = {
        "placement_client_order_id": "placement-1",
        "placement_size": 25.0,
        "desired_limit_price": 77110.0,
        "reprice_reason": "reference_price_updated_slide_step",
    }
    manager = _manager_for(order)
    manager._update_stealth_order = MagicMock(return_value=True)

    result = manager.consume_anchor_rearm_cancellation(
        "placement-1",
        exchange_order_id="exchange-1",
        cumulative_filled_size=2.0,
        number_of_fills=1,
    )

    assert result is StealthOrderStatus.CANCELLED
    assert order["status"] == StealthOrderStatus.CANCELLED.value
    assert order["executed_size"] == 2.0
    assert order["remaining_size"] == 0.0
    assert "pending_rearm" not in order["anchor_repricing_state_json"]
    assert order["revealed_orders"][0]["rearm_aborted_for_fill"] is True


@pytest.mark.regression
def test_filled_event_consumes_pending_rearm_before_later_cancel_replay():
    order = _revealed_order()
    order["anchor_repricing_state_json"]["pending_rearm"] = {
        "placement_client_order_id": "placement-1",
        "placement_size": 25.0,
        "desired_limit_price": 77110.0,
        "reprice_reason": "reference_price_updated_slide_step",
    }
    manager = _manager_for(order)
    manager._update_stealth_order = MagicMock(return_value=True)

    manager.update_execution(
        "stealth-1",
        executed_size=25.0,
        order_status=StealthOrderStatus.EXECUTED.value,
        placement_client_order_id="placement-1",
    )

    assert order["status"] == StealthOrderStatus.EXECUTED.value
    assert "pending_rearm" not in order["anchor_repricing_state_json"]
    assert order["anchor_repricing_state_json"][
        "active_placement_client_order_id"
    ] is None
    assert order["revealed_orders"][0]["rearm_aborted_for_fill"] is True
    assert manager.consume_anchor_rearm_cancellation(
        "placement-1",
        exchange_order_id="exchange-1",
    ) is StealthOrderStatus.EXECUTED
    assert order["remaining_size"] == 0.0


@pytest.mark.regression
def test_filled_event_retains_pending_when_parent_projection_is_incomplete(
    monkeypatch,
):
    order = _revealed_order()
    order["anchor_repricing_state_json"]["pending_rearm"] = {
        "placement_client_order_id": "placement-1",
        "exchange_order_id": "exchange-1",
        "placement_size": 25.0,
        "desired_limit_price": 77110.0,
    }
    manager = _manager_for(order)
    manager.db_client = object()
    manager._update_stealth_order = MagicMock(return_value=True)
    update_parent_status = MagicMock(side_effect=(1, 0))
    monkeypatch.setattr(
        "core.stealth_order_manager.update_order_parent_status",
        update_parent_status,
    )

    assert manager.update_execution(
        "stealth-1",
        executed_size=25.0,
        order_status=StealthOrderStatus.EXECUTED.value,
        placement_client_order_id="placement-1",
    ) is False

    assert order["status"] == StealthOrderStatus.REVEALED.value
    assert order["executed_size"] == 0.0
    assert "pending_rearm" in order["anchor_repricing_state_json"]
    update_parent_status.assert_has_calls(
        [
            call("placement-1", "FILLED"),
            call("stealth-1", "FILLED"),
        ]
    )
    manager._update_stealth_order.assert_not_called()


@pytest.mark.regression
def test_cancel_ack_refuses_corrupt_multi_live_inventory(monkeypatch):
    order = _revealed_order()
    order["anchor_repricing_state_json"]["pending_rearm"] = {
        "placement_client_order_id": "placement-1",
        "placement_size": 20.0,
        "desired_limit_price": 77110.0,
        "reprice_reason": "reference_price_updated_slide_step",
    }
    manager = _manager_for(order)
    manager._update_stealth_order = MagicMock(return_value=True)
    controller = RuntimeController()
    assert controller.complete_startup() is True
    monkeypatch.setattr(
        "core.stealth_order_manager.get_runtime_controller",
        lambda: controller,
    )

    result = manager.consume_anchor_rearm_cancellation(
        "placement-1",
        exchange_order_id="exchange-1",
    )

    assert result is StealthOrderStatus.REVEALED
    assert order["status"] == StealthOrderStatus.REVEALED.value
    assert order["remaining_size"] == 0.0
    assert "pending_rearm" in order["anchor_repricing_state_json"]
    assert controller.state is EngineState.PAUSED
    manager._update_stealth_order.assert_not_called()


@pytest.mark.regression
def test_fill_count_without_size_never_restores_inventory(monkeypatch):
    order = _revealed_order()
    order["anchor_repricing_state_json"]["pending_rearm"] = {
        "placement_client_order_id": "placement-1",
        "placement_size": 25.0,
        "desired_limit_price": 77110.0,
        "reprice_reason": "reference_price_updated_slide_step",
    }
    manager = _manager_for(order)
    manager._update_stealth_order = MagicMock(return_value=True)
    controller = RuntimeController()
    assert controller.complete_startup() is True
    monkeypatch.setattr(
        "core.stealth_order_manager.get_runtime_controller",
        lambda: controller,
    )

    result = manager.consume_anchor_rearm_cancellation(
        "placement-1",
        exchange_order_id="exchange-1",
        cumulative_filled_size=0.0,
        number_of_fills=1,
    )

    assert result is StealthOrderStatus.REVEALED
    assert order["revealed_size"] == 25.0
    assert "pending_rearm" in order["anchor_repricing_state_json"]
    assert controller.state is EngineState.PAUSED


@pytest.mark.regression
def test_late_fill_evidence_after_rearm_persists_fail_closed_terminal_state(
    monkeypatch,
):
    order = _revealed_order()
    order["anchor_repricing_state_json"]["pending_rearm"] = {
        "placement_client_order_id": "placement-1",
        "placement_size": 25.0,
        "desired_limit_price": 77110.0,
        "reprice_reason": "reference_price_updated_slide_step",
    }
    manager = _manager_for(order)
    manager._update_stealth_order = MagicMock(return_value=True)
    controller = RuntimeController()
    assert controller.complete_startup() is True
    monkeypatch.setattr(
        "core.stealth_order_manager.get_runtime_controller",
        lambda: controller,
    )

    assert manager.consume_anchor_rearm_cancellation(
        "placement-1",
        exchange_order_id="exchange-1",
    ) is StealthOrderStatus.HIDDEN
    assert manager.consume_anchor_rearm_cancellation(
        "placement-1",
        exchange_order_id="exchange-1",
        cumulative_filled_size=1.0,
        number_of_fills=1,
    ) is StealthOrderStatus.CANCELLED

    assert order["remaining_size"] == 0.0
    assert order["executed_size"] == 1.0
    assert order["status"] == StealthOrderStatus.CANCELLED.value
    assert order["failure_reason"]
    assert order["revealed_orders"][0]["late_fill_contained"] is True
    assert manager._update_stealth_order.call_count == 2
    assert controller.state is EngineState.PAUSED


@pytest.mark.regression
def test_late_fill_cancels_a_newer_live_placement_before_stopping(
    monkeypatch,
):
    order = _revealed_order()
    order["anchor_repricing_state_json"]["pending_rearm"] = {
        "placement_client_order_id": "placement-1",
        "exchange_order_id": "exchange-1",
        "placement_size": 25.0,
        "desired_limit_price": 77110.0,
    }
    manager = _manager_for(order)
    manager._update_stealth_order = MagicMock(return_value=True)

    assert manager.consume_anchor_rearm_cancellation(
        "placement-1",
        exchange_order_id="exchange-1",
    ) is StealthOrderStatus.HIDDEN

    order["status"] = StealthOrderStatus.REVEALED.value
    order["revealed_size"] = 25.0
    order["remaining_size"] = 0.0
    order["visibility_score"] = 1.0
    order["revealed_orders"].append(
        {
            "revealed_size": 25.0,
            "placed_order_id": "placement-2",
            "exchange_order_id": "exchange-2",
            "placement_success": True,
        }
    )
    state = order["anchor_repricing_state_json"]
    state["active_placement_client_order_id"] = "placement-2"
    state["active_exchange_order_id"] = "exchange-2"
    state["active_exchange_price"] = 77110.0
    manager._placed_order_index["placement-2"] = order
    rest_client = MagicMock()
    rest_client.cancel_orders.return_value = [
        {"success": True, "order_id": "exchange-2"}
    ]
    monkeypatch.setattr("configuration.REST_CLIENT", rest_client)

    assert manager.consume_anchor_rearm_cancellation(
        "placement-1",
        exchange_order_id="exchange-1",
        cumulative_filled_size=1.0,
        number_of_fills=1,
    ) is StealthOrderStatus.ERROR

    state = order["anchor_repricing_state_json"]
    assert order["status"] == StealthOrderStatus.ERROR.value
    assert state["active_placement_client_order_id"] == "placement-2"
    assert state["pending_rearm"]["placement_client_order_id"] == "placement-2"
    assert state["pending_rearm"]["return_to_hidden"] is False
    rest_client.cancel_orders.assert_called_once_with(order_ids=["exchange-2"])


@pytest.mark.regression
def test_malformed_terminal_cancel_mode_is_retained_and_pauses(monkeypatch):
    order = _revealed_order()
    order["anchor_repricing_state_json"]["pending_rearm"] = {
        "placement_client_order_id": "placement-1",
        "exchange_order_id": "exchange-1",
        "placement_size": 25.0,
        "desired_limit_price": 77110.0,
        "return_to_hidden": "false",
    }
    manager = _manager_for(order)
    manager._update_stealth_order = MagicMock(return_value=True)
    controller = RuntimeController()
    assert controller.complete_startup() is True
    monkeypatch.setattr(
        "core.stealth_order_manager.get_runtime_controller",
        lambda: controller,
    )

    assert manager.consume_anchor_rearm_cancellation(
        "placement-1",
        exchange_order_id="exchange-1",
    ) is StealthOrderStatus.REVEALED
    assert "pending_rearm" in order["anchor_repricing_state_json"]
    manager._update_stealth_order.assert_not_called()
    assert controller.state is EngineState.PAUSED


@pytest.mark.regression
def test_terminal_local_status_cannot_be_resurrected_by_pending_rearm():
    order = _revealed_order()
    order["status"] = StealthOrderStatus.EXECUTED.value
    order["anchor_repricing_state_json"]["pending_rearm"] = {
        "placement_client_order_id": "placement-1",
        "placement_size": 25.0,
        "desired_limit_price": 77110.0,
    }
    manager = _manager_for(order)
    manager._update_stealth_order = MagicMock(return_value=True)

    result = manager.consume_anchor_rearm_cancellation(
        "placement-1",
        exchange_order_id="exchange-1",
    )

    assert result is StealthOrderStatus.EXECUTED
    assert order["status"] == StealthOrderStatus.EXECUTED.value
    assert "pending_rearm" not in order["anchor_repricing_state_json"]
    assert order["remaining_size"] == 0.0


@pytest.mark.regression
def test_operator_cancel_persists_rearm_supersession_before_rest(monkeypatch):
    order = _revealed_order()
    order["anchor_repricing_state_json"]["pending_rearm"] = {
        "placement_client_order_id": "placement-1",
        "placement_size": 25.0,
        "desired_limit_price": 77110.0,
    }
    manager = _manager_for(order)
    manager.db_client = object()
    operations = []

    def persist(current):
        operations.append(
            (
                "persist",
                current["status"],
                "pending_rearm"
                in current["anchor_repricing_state_json"],
            )
        )
        return True

    rest_client = MagicMock()
    rest_client.cancel_orders.side_effect = lambda **_kwargs: operations.append(
        ("cancel",)
    )
    update_parent_status = MagicMock(
        side_effect=lambda client_order_id, status: (
            operations.append(("parent", client_order_id, status)) or 1
        )
    )
    manager._update_stealth_order = MagicMock(side_effect=persist)
    monkeypatch.setattr("configuration.REST_CLIENT", rest_client)
    monkeypatch.setattr(
        "core.stealth_order_manager.update_order_parent_status",
        update_parent_status,
    )

    assert manager.cancel_stealth_order("stealth-1") is True

    assert operations == [
        ("persist", StealthOrderStatus.CANCELLED.value, True),
        ("cancel",),
    ]

    assert manager.consume_anchor_rearm_cancellation(
        "placement-1",
        exchange_order_id="exchange-1",
    ) is None
    assert operations == [
        ("persist", StealthOrderStatus.CANCELLED.value, True),
        ("cancel",),
        ("parent", "placement-1", "CANCELLED"),
        ("parent", "stealth-1", "CANCELLED"),
        ("persist", StealthOrderStatus.CANCELLED.value, False),
    ]
    event = order["revealed_orders"][0]
    assert event["rearm_cancel_consumed"] is True
    assert event["operator_cancel_consumed"] is True
    assert manager.consume_anchor_rearm_cancellation(
        "placement-1",
        exchange_order_id="exchange-1",
    ) is None
    assert manager._update_stealth_order.call_count == 2


@pytest.mark.regression
def test_operator_cancel_with_fill_evidence_stops_without_generic_follow_up(
    monkeypatch,
):
    order = _revealed_order()
    order["status"] = StealthOrderStatus.CANCELLED.value
    order["anchor_repricing_state_json"]["pending_rearm"] = {
        "placement_client_order_id": "placement-1",
        "exchange_order_id": "exchange-1",
        "placement_size": 25.0,
        "desired_limit_price": 77110.0,
        "return_to_hidden": False,
    }
    manager = _manager_for(order)
    manager.db_client = object()
    manager._update_stealth_order = MagicMock(return_value=True)
    update_parent_status = MagicMock(return_value=1)
    monkeypatch.setattr(
        "core.stealth_order_manager.update_order_parent_status",
        update_parent_status,
    )
    controller = RuntimeController()
    assert controller.complete_startup() is True
    monkeypatch.setattr(
        "core.stealth_order_manager.get_runtime_controller",
        lambda: controller,
    )

    assert manager.consume_anchor_rearm_cancellation(
        "placement-1",
        exchange_order_id="exchange-1",
        cumulative_filled_size=2.0,
        number_of_fills=1,
    ) is StealthOrderStatus.CANCELLED

    assert order["status"] == StealthOrderStatus.CANCELLED.value
    assert order["executed_size"] == 2.0
    assert order["remaining_size"] == 0.0
    assert "pending_rearm" not in order["anchor_repricing_state_json"]
    assert order["failure_reason"]
    event = order["revealed_orders"][0]
    assert event["rearm_aborted_for_fill"] is True
    assert event["operator_cancel_consumed"] is True
    assert update_parent_status.call_args_list == [
        call("placement-1", "CANCELLED"),
        call("stealth-1", "CANCELLED"),
    ]
    assert controller.state is EngineState.PAUSED


@pytest.mark.regression
def test_operator_cancel_with_fill_count_but_no_size_retains_intent(
    monkeypatch,
):
    order = _revealed_order()
    order["status"] = StealthOrderStatus.CANCELLED.value
    order["anchor_repricing_state_json"]["pending_rearm"] = {
        "placement_client_order_id": "placement-1",
        "exchange_order_id": "exchange-1",
        "placement_size": 25.0,
        "desired_limit_price": 77110.0,
        "return_to_hidden": False,
    }
    manager = _manager_for(order)
    manager._update_stealth_order = MagicMock(return_value=True)
    controller = RuntimeController()
    assert controller.complete_startup() is True
    monkeypatch.setattr(
        "core.stealth_order_manager.get_runtime_controller",
        lambda: controller,
    )

    assert manager.consume_anchor_rearm_cancellation(
        "placement-1",
        exchange_order_id="exchange-1",
        cumulative_filled_size=0.0,
        number_of_fills=1,
    ) is StealthOrderStatus.CANCELLED

    assert "pending_rearm" in order["anchor_repricing_state_json"]
    assert order["executed_size"] == 0.0
    manager._update_stealth_order.assert_not_called()
    assert controller.state is EngineState.PAUSED


@pytest.mark.regression
def test_operator_cancel_does_not_call_rest_if_supersession_write_fails(
    monkeypatch,
):
    order = _revealed_order()
    order["anchor_repricing_state_json"]["pending_rearm"] = {
        "placement_client_order_id": "placement-1",
        "placement_size": 25.0,
        "desired_limit_price": 77110.0,
    }
    manager = _manager_for(order)
    manager._update_stealth_order = MagicMock(return_value=False)
    rest_client = MagicMock()
    monkeypatch.setattr("configuration.REST_CLIENT", rest_client)
    controller = RuntimeController()
    assert controller.complete_startup() is True
    monkeypatch.setattr(
        "core.stealth_order_manager.get_runtime_controller",
        lambda: controller,
    )

    assert manager.cancel_stealth_order("stealth-1") is False

    assert "pending_rearm" in order["anchor_repricing_state_json"]
    rest_client.cancel_orders.assert_not_called()
    assert controller.state is EngineState.PAUSED


@pytest.mark.regression
def test_delayed_old_fill_keeps_new_placement_identity_and_fill_monotonic(
    monkeypatch,
):
    order = _revealed_order()
    order["executed_size"] = 5.0
    order["revealed_orders"].append(
        {
            "revealed_size": 25.0,
            "placed_order_id": "placement-2",
            "exchange_order_id": "exchange-2",
            "placement_success": True,
        }
    )
    state = order["anchor_repricing_state_json"]
    state["active_placement_client_order_id"] = "placement-2"
    state["active_exchange_order_id"] = "exchange-2"
    manager = _manager_for(order)
    manager._placed_order_index["placement-2"] = order
    manager._update_stealth_order = MagicMock(return_value=True)
    rest_client = MagicMock()
    rest_client.cancel_orders.return_value = [
        {"success": True, "order_id": "exchange-2"}
    ]
    monkeypatch.setattr("configuration.REST_CLIENT", rest_client)
    controller = RuntimeController()
    assert controller.complete_startup() is True
    monkeypatch.setattr(
        "core.stealth_order_manager.get_runtime_controller",
        lambda: controller,
    )

    assert manager.update_execution(
        "stealth-1",
        executed_size=2.0,
        order_status=StealthOrderStatus.EXECUTED.value,
        placement_client_order_id="placement-1",
    ) is True

    assert order["executed_size"] == 5.0
    state = order["anchor_repricing_state_json"]
    assert state["active_placement_client_order_id"] == "placement-2"
    assert state["active_exchange_order_id"] == "exchange-2"
    assert state["pending_rearm"]["placement_client_order_id"] == "placement-2"
    assert state["pending_rearm"]["return_to_hidden"] is False
    rest_client.cancel_orders.assert_called_once_with(order_ids=["exchange-2"])
    assert controller.state is EngineState.PAUSED

    assert manager.consume_anchor_rearm_cancellation(
        "placement-2",
        exchange_order_id="exchange-2",
        cumulative_filled_size=3.0,
        number_of_fills=1,
    ) is StealthOrderStatus.EXECUTED
    state = order["anchor_repricing_state_json"]
    assert "pending_rearm" not in state
    assert state["active_placement_client_order_id"] is None
    assert state["active_exchange_order_id"] is None
    assert order["executed_size"] == 5.0
    active_event = order["revealed_orders"][1]
    assert active_event["terminal_cancel_cumulative_filled_size"] == 3.0
    assert active_event["terminal_cancel_number_of_fills"] == 1


@pytest.mark.regression
def test_execution_persistence_failure_restores_pending_rearm(monkeypatch):
    order = _revealed_order()
    order["anchor_repricing_state_json"]["pending_rearm"] = {
        "placement_client_order_id": "placement-1",
        "exchange_order_id": "exchange-1",
        "placement_size": 25.0,
        "desired_limit_price": 77110.0,
    }
    previous_order = {
        **order,
        "revealed_orders": [dict(order["revealed_orders"][0])],
        "anchor_repricing_state_json": dict(
            order["anchor_repricing_state_json"]
        ),
    }
    manager = _manager_for(order)
    manager._update_stealth_order = MagicMock(return_value=False)
    controller = RuntimeController()
    assert controller.complete_startup() is True
    monkeypatch.setattr(
        "core.stealth_order_manager.get_runtime_controller",
        lambda: controller,
    )

    assert manager.update_execution(
        "stealth-1",
        executed_size=25.0,
        order_status=StealthOrderStatus.EXECUTED.value,
        placement_client_order_id="placement-1",
    ) is False

    assert order == previous_order
    manager._update_stealth_order.assert_called_once()
    manager._dispatch_lifecycle_event.assert_not_called()
    assert controller.state is EngineState.PAUSED


@pytest.mark.regression
def test_stale_fill_with_unprovable_active_identity_persists_error(
    monkeypatch,
):
    order = _revealed_order()
    order["revealed_orders"].append(
        {
            "revealed_size": 25.0,
            "placed_order_id": "placement-2",
            "exchange_order_id": "different-exchange-id",
            "placement_success": True,
        }
    )
    state = order["anchor_repricing_state_json"]
    state["active_placement_client_order_id"] = "placement-2"
    state["active_exchange_order_id"] = "exchange-2"
    manager = _manager_for(order)
    manager._placed_order_index["placement-2"] = order
    manager._update_stealth_order = MagicMock(return_value=True)
    rest_client = MagicMock()
    monkeypatch.setattr("configuration.REST_CLIENT", rest_client)
    controller = RuntimeController()
    assert controller.complete_startup() is True
    monkeypatch.setattr(
        "core.stealth_order_manager.get_runtime_controller",
        lambda: controller,
    )

    assert manager.update_execution(
        "stealth-1",
        executed_size=1.0,
        order_status=StealthOrderStatus.EXECUTED.value,
        placement_client_order_id="placement-1",
    ) is False

    state = order["anchor_repricing_state_json"]
    assert order["status"] == StealthOrderStatus.ERROR.value
    assert order["failure_reason"]
    assert state["active_placement_client_order_id"] == "placement-2"
    assert state["active_exchange_order_id"] == "exchange-2"
    assert "pending_rearm" not in state
    manager._update_stealth_order.assert_called_once()
    rest_client.cancel_orders.assert_not_called()
    assert controller.state is EngineState.PAUSED
