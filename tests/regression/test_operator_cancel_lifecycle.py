"""Intentional stealth cancellation stops automation without losing venue truth."""

import json
from copy import deepcopy
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from core.enums import EngineState, StealthOrderStatus
from core.runtime_controller import RuntimeController
from core.stealth_order_manager import StealthOrderManager, resolve_stealth_chain_root
from tests.regression.test_anchor_reprice_phantom_parent import _manager_for, _revealed_order


pytestmark = pytest.mark.regression

SID = "11111111-1111-4111-8111-111111111111"
PLACEMENT_ID = "22222222-2222-4222-8222-222222222222"
ROOT_ID = "33333333-3333-4333-8333-333333333333"
EXCHANGE_ID = "exchange-operator-cancel"


def _manager_with_order(order):
    manager = _manager_for(order)
    manager._placed_order_index = {PLACEMENT_ID: order}
    manager._update_stealth_order = MagicMock(return_value=True)
    manager._notify_schedule_invalidated = MagicMock()
    return manager


@pytest.fixture
def cancel_case(monkeypatch):
    order = _revealed_order()
    order["stealth_order_id"] = SID
    order["parent_order_id"] = ROOT_ID
    event = order["revealed_orders"][0]
    event.update(
        placed_order_id=PLACEMENT_ID,
        placement_client_order_id=PLACEMENT_ID,
        exchange_order_id=EXCHANGE_ID,
    )
    state = order["anchor_repricing_state_json"]
    state.update(
        active_placement_client_order_id=PLACEMENT_ID,
        active_exchange_order_id=EXCHANGE_ID,
    )
    manager = _manager_with_order(order)
    rest_client = MagicMock()
    rest_client.cancel_orders.return_value = [{"success": True, "order_id": EXCHANGE_ID}]
    monkeypatch.setattr("configuration.REST_CLIENT", rest_client)
    controller = RuntimeController()
    assert controller.complete_startup() is True
    monkeypatch.setattr("core.stealth_order_manager.get_runtime_controller", lambda: controller)
    return order, manager, rest_client, controller


def _pending_rehide(order):
    pending = {
        "placement_client_order_id": PLACEMENT_ID,
        "exchange_order_id": EXCHANGE_ID,
        "placement_size": order["revealed_size"],
        "desired_limit_price": order["limit_price"] - 10,
        "reprice_reason": "reference_price_updated_slide_step",
        "requested_at": "2026-09-18T01:00:00",
        "return_to_hidden": True,
    }
    order["anchor_repricing_state_json"]["pending_rearm"] = pending
    return deepcopy(pending)


def test_operator_cancel_persists_stop_and_recovery_intent_before_rest(cancel_case):
    order, manager, rest_client, _ = cancel_case
    operations = []

    def persist(current):
        assert current["status"] == StealthOrderStatus.CANCELLED.value
        state = current["anchor_repricing_state_json"]
        datetime.fromisoformat(state["operator_cancel_requested_at"])
        assert state["pending_rearm"]["return_to_hidden"] is False
        assert state["pending_rearm"]["placement_client_order_id"] == PLACEMENT_ID
        assert state["pending_rearm"]["exchange_order_id"] == EXCHANGE_ID
        assert state["active_exchange_order_id"] == EXCHANGE_ID
        operations.append("persist")
        return True

    def cancel(order_ids):
        assert operations == ["persist"]
        assert order_ids == [EXCHANGE_ID]
        operations.append("cancel")
        return [{"success": True, "order_id": EXCHANGE_ID}]

    manager._update_stealth_order.side_effect = persist
    rest_client.cancel_orders.side_effect = cancel

    assert manager.cancel_stealth_order(SID) is True

    assert operations == ["persist", "cancel"]
    assert order["revealed_size"] == 25.0
    assert order["anchor_repricing_state_json"]["active_placement_client_order_id"] == PLACEMENT_ID
    assert manager.is_operator_cancel_requested(order) is True
    assert resolve_stealth_chain_root(order) == ROOT_ID
    assert set(manager.in_memory_orders) == {SID}
    rest_client.place_limit_order.assert_not_called()


@pytest.mark.parametrize("persistence_result", [False, RuntimeError("intent write failed")])
def test_operator_cancel_failed_intent_write_rolls_back_without_rest(cancel_case, persistence_result):
    order, manager, rest_client, controller = cancel_case
    original = deepcopy(order)
    if isinstance(persistence_result, Exception):
        manager._update_stealth_order.side_effect = persistence_result
    else:
        manager._update_stealth_order.return_value = persistence_result

    assert manager.cancel_stealth_order(SID) is False

    assert order == original
    assert controller.state is EngineState.PAUSED
    rest_client.cancel_orders.assert_not_called()
    assert manager.is_operator_cancel_requested(order) is False


@pytest.mark.parametrize("cancel_result", [TimeoutError("reply lost"), [{"success": False, "order_id": EXCHANGE_ID}]])
def test_operator_cancel_unconfirmed_rest_retains_tracking_and_durable_stop(cancel_case, cancel_result):
    order, manager, rest_client, _ = cancel_case
    if isinstance(cancel_result, Exception):
        rest_client.cancel_orders.side_effect = cancel_result
    else:
        rest_client.cancel_orders.return_value = cancel_result

    assert manager.cancel_stealth_order(SID) is True

    assert order["status"] == StealthOrderStatus.CANCELLED.value
    state = order["anchor_repricing_state_json"]
    assert state["operator_cancel_requested_at"]
    assert state["active_placement_client_order_id"] == PLACEMENT_ID
    assert state["active_exchange_order_id"] == EXCHANGE_ID
    assert state["pending_rearm"]["return_to_hidden"] is False
    assert manager.find_stealth_order_by_placed_order_id(PLACEMENT_ID) is order
    assert order["revealed_size"] == 25.0
    rest_client.place_limit_order.assert_not_called()


def test_operator_cancel_without_live_placement_is_local_only(cancel_case):
    order, manager, rest_client, _ = cancel_case
    order["status"] = StealthOrderStatus.HIDDEN.value
    order["revealed_orders"] = []
    order["revealed_size"] = 0.0
    order["remaining_size"] = order["total_size"]
    order["anchor_repricing_state_json"] = {}
    manager._placed_order_index.clear()

    assert manager.cancel_stealth_order(SID) is True

    assert order["status"] == StealthOrderStatus.CANCELLED.value
    assert order["anchor_repricing_state_json"]["operator_cancel_requested_at"]
    assert "pending_rearm" not in order["anchor_repricing_state_json"]
    manager._update_stealth_order.assert_called_once()
    manager._notify_schedule_invalidated.assert_called_with(SID)
    rest_client.cancel_orders.assert_not_called()
    assert resolve_stealth_chain_root(order) == ROOT_ID


def test_operator_cancel_without_rest_still_retains_active_recovery_intent(cancel_case):
    order, manager, rest_client, _ = cancel_case

    assert manager.cancel_stealth_order(SID, cancel_exchange=False) is True

    state = order["anchor_repricing_state_json"]
    assert manager.is_operator_cancel_requested(order) is True
    assert state["pending_rearm"]["return_to_hidden"] is False
    assert state["active_exchange_order_id"] == EXCHANGE_ID
    rest_client.cancel_orders.assert_not_called()


def test_incomplete_live_identity_stops_automation_without_discarding_exposure(cancel_case):
    order, manager, rest_client, controller = cancel_case
    order["anchor_repricing_state_json"]["active_exchange_order_id"] = None
    original_event = deepcopy(order["revealed_orders"][0])

    assert manager.cancel_stealth_order(SID) is False

    assert order["status"] == StealthOrderStatus.CANCELLED.value
    assert manager.is_operator_cancel_requested(order) is True
    assert order["anchor_repricing_state_json"]["active_placement_client_order_id"] == PLACEMENT_ID
    assert order["revealed_size"] == 25.0
    assert order["revealed_orders"][0] == original_event
    assert order["failure_reason"]
    assert controller.state is EngineState.PAUSED
    manager._update_stealth_order.assert_called_once()
    rest_client.cancel_orders.assert_not_called()


def test_repeated_pending_operator_cancel_is_idempotent_and_recovery_owns_retry(cancel_case):
    order, manager, rest_client, _ = cancel_case
    assert manager.cancel_stealth_order(SID) is True
    stopped = deepcopy(order)

    assert manager.cancel_stealth_order(SID) is True

    assert order == stopped
    manager._update_stealth_order.assert_called_once()
    rest_client.cancel_orders.assert_called_once_with(order_ids=[EXCHANGE_ID])


def test_operator_cancel_rejects_one_placement_that_cannot_cover_exposure(cancel_case):
    order, manager, rest_client, controller = cancel_case
    order["revealed_orders"][0]["revealed_size"] = 15.0
    # Aggregate fills do not prove that the extra ten revealed units belong
    # to a closed placement. An outstanding-only bound would incorrectly pass.
    order["executed_size"] = 10.0

    assert manager.cancel_stealth_order(SID) is False

    state = order["anchor_repricing_state_json"]
    assert order["status"] == StealthOrderStatus.CANCELLED.value
    assert manager.is_operator_cancel_requested(order) is True
    assert order["revealed_size"] == 25.0
    assert state["active_placement_client_order_id"] == PLACEMENT_ID
    assert state["active_exchange_order_id"] == EXCHANGE_ID
    assert "pending_rearm" not in state
    assert controller.state is EngineState.PAUSED
    manager._update_stealth_order.assert_called_once()
    rest_client.cancel_orders.assert_not_called()


def test_operator_cancel_supersedes_existing_rehide_without_new_placement(cancel_case):
    order, manager, rest_client, _ = cancel_case
    original_intent = _pending_rehide(order)

    assert manager.cancel_stealth_order(SID) is True

    state = order["anchor_repricing_state_json"]
    pending = state["pending_rearm"]
    assert pending["return_to_hidden"] is False
    assert pending["placement_client_order_id"] == original_intent["placement_client_order_id"]
    assert pending["exchange_order_id"] == original_intent["exchange_order_id"]
    assert state["operator_cancel_requested_at"]
    assert "reveal_armed_at" not in state
    rest_client.cancel_orders.assert_called_once_with(order_ids=[EXCHANGE_ID])
    rest_client.place_limit_order.assert_not_called()


def test_failed_operator_supersession_preserves_previous_rehide_intent(cancel_case):
    order, manager, rest_client, controller = cancel_case
    _pending_rehide(order)
    original = deepcopy(order)
    manager._update_stealth_order.return_value = False

    assert manager.cancel_stealth_order(SID) is False

    assert order == original
    assert order["anchor_repricing_state_json"]["pending_rearm"]["return_to_hidden"] is True
    assert manager.is_operator_cancel_requested(order) is False
    assert controller.state is EngineState.PAUSED
    rest_client.cancel_orders.assert_not_called()


def test_operator_cancel_ack_and_duplicate_are_consumed_without_reentry(cancel_case):
    order, manager, rest_client, _ = cancel_case
    assert manager.cancel_stealth_order(SID) is True

    assert manager.consume_anchor_rearm_cancellation(
        PLACEMENT_ID, exchange_order_id=EXCHANGE_ID
    ) is StealthOrderStatus.CANCELLED

    state = order["anchor_repricing_state_json"]
    assert "pending_rearm" not in state
    assert "reveal_armed_at" not in state
    assert state["active_placement_client_order_id"] is None
    assert state["active_exchange_order_id"] is None
    assert state["operator_cancel_requested_at"]
    assert order["remaining_size"] == order["revealed_size"] == 0.0
    persisted_calls = manager._update_stealth_order.call_count
    assert manager.consume_anchor_rearm_cancellation(
        PLACEMENT_ID, exchange_order_id=EXCHANGE_ID
    ) is StealthOrderStatus.CANCELLED
    assert manager._update_stealth_order.call_count == persisted_calls
    rest_client.cancel_orders.assert_called_once()
    rest_client.place_limit_order.assert_not_called()


def test_operator_cancel_intent_survives_json_reload_and_exact_ack(cancel_case):
    order, manager, rest_client, _ = cancel_case
    assert manager.cancel_stealth_order(SID) is True
    persisted = json.loads(json.dumps(order, default=lambda value: value.isoformat()))
    restarted = _manager_with_order(persisted)

    assert restarted.is_operator_cancel_requested(persisted) is True
    assert restarted.consume_anchor_rearm_cancellation(
        PLACEMENT_ID, exchange_order_id=EXCHANGE_ID
    ) is StealthOrderStatus.CANCELLED

    assert persisted["status"] == StealthOrderStatus.CANCELLED.value
    assert restarted.is_operator_cancel_requested(persisted) is True
    assert "pending_rearm" not in persisted["anchor_repricing_state_json"]
    assert resolve_stealth_chain_root(persisted) == ROOT_ID
    rest_client.cancel_orders.assert_called_once()


@pytest.mark.parametrize("legacy_pending", [False, True], ids=["durable-stop", "legacy-intent"])
def test_fill_wins_exchange_truth_without_removing_operator_stop(cancel_case, legacy_pending):
    order, manager, rest_client, _ = cancel_case
    if legacy_pending:
        _pending_rehide(order)
        order["anchor_repricing_state_json"]["pending_rearm"]["return_to_hidden"] = False
        order["status"] = StealthOrderStatus.CANCELLED.value
        marker = None
    else:
        assert manager.cancel_stealth_order(SID) is True
        marker = order["anchor_repricing_state_json"]["operator_cancel_requested_at"]

    assert manager.update_execution(
        SID,
        25.0,
        order_status=StealthOrderStatus.EXECUTED.value,
        placement_client_order_id=PLACEMENT_ID,
    ) is True

    assert order["status"] == StealthOrderStatus.EXECUTED.value
    assert order["executed_size"] == 25.0
    state = order["anchor_repricing_state_json"]
    assert state["operator_cancel_requested_at"]
    if marker is not None:
        assert state["operator_cancel_requested_at"] == marker
    assert "pending_rearm" not in state
    assert state["active_exchange_order_id"] is None
    assert manager.is_operator_cancel_requested(order) is True
    assert manager.consume_anchor_rearm_cancellation(
        PLACEMENT_ID, exchange_order_id=EXCHANGE_ID
    ) is StealthOrderStatus.EXECUTED
    rest_client.place_limit_order.assert_not_called()


def test_operator_stop_recognizes_durable_and_legacy_intent_shapes():
    assert StealthOrderManager.is_operator_cancel_requested(None) is False
    assert StealthOrderManager.is_operator_cancel_requested([]) is False
    shapes = {
        "durable_after_fill": {
            "status": StealthOrderStatus.EXECUTED.value,
            "anchor_repricing_state_json": {"operator_cancel_requested_at": "2026-09-18T01:00:00"},
        },
        "legacy_pending": {
            "status": StealthOrderStatus.CANCELLED.value,
            "anchor_repricing_state_json": {"pending_rearm": {"return_to_hidden": False}},
        },
        "legacy_consumed": {"revealed_orders": [{"operator_cancel_consumed": True}]},
        "legacy_supersession": {"revealed_orders": [{"operator_cancel_supersession": True}]},
    }
    for label, order in shapes.items():
        assert StealthOrderManager.is_operator_cancel_requested(order) is True, label

    for status in (StealthOrderStatus.EXECUTED, StealthOrderStatus.ERROR):
        safety_cancel = {
            "status": status.value,
            "anchor_repricing_state_json": {"pending_rearm": {"return_to_hidden": False}},
        }
        assert StealthOrderManager.is_operator_cancel_requested(safety_cancel) is False


def test_unmarked_exchange_cancel_keeps_ordinary_routing(cancel_case):
    order, manager, rest_client, _ = cancel_case
    original = deepcopy(order)

    assert manager.is_operator_cancel_requested(order) is False
    assert manager.consume_anchor_rearm_cancellation(
        PLACEMENT_ID, exchange_order_id=EXCHANGE_ID
    ) is None

    assert order == original
    manager._update_stealth_order.assert_not_called()
    rest_client.cancel_orders.assert_not_called()
