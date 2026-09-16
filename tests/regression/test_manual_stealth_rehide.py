"""Manual Rehide reuses authenticated rearm without repricing or duplication."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, call
from uuid import UUID

import pytest

from bridges.stealth_order_bridge import StealthOrderBridge
from business.stealth_condition_evaluator import TimeDelayEvaluator
from core.enums import EngineState, RevealConditionType, StealthMutationKind, StealthOrderStatus
from core.runtime_controller import RuntimeController
from core.stealth_order_manager import resolve_stealth_chain_root
from tests.regression.test_anchor_reprice_phantom_parent import _manager_for, _revealed_order


pytestmark = pytest.mark.regression

SID = "11111111-1111-4111-8111-111111111111"
PLACEMENT_ID = "22222222-2222-4222-8222-222222222222"
ROOT_ID = "33333333-3333-4333-8333-333333333333"


@pytest.fixture
def rehide_case(monkeypatch):
    order = _revealed_order()
    order["stealth_order_id"] = SID
    order["created_at"] = datetime(2026, 9, 1)
    order["anchor_repricing_policy_json"]["enabled"] = False
    order["anchor_repricing_policy_json"]["allow_revealed_reprice"] = False
    event = order["revealed_orders"][0]
    event["placed_order_id"] = PLACEMENT_ID
    event["placement_client_order_id"] = PLACEMENT_ID
    state = order["anchor_repricing_state_json"]
    state["active_placement_client_order_id"] = PLACEMENT_ID
    state["last_reprice_at"] = "2026-09-01T00:00:00"
    state["next_reprice_at"] = "2026-09-20T00:00:00"
    state["reprice_history"] = ["2026-09-01T00:00:00"]
    manager = _manager_for(order)
    manager._placed_order_index = {PLACEMENT_ID: order}
    manager._update_stealth_order = MagicMock(return_value=True)
    rest_client = MagicMock()
    rest_client.cancel_orders.return_value = [{"success": True, "order_id": "exchange-1"}]
    monkeypatch.setattr("configuration.REST_CLIENT", rest_client)
    controller = RuntimeController()
    assert controller.complete_startup() is True
    monkeypatch.setattr("core.stealth_order_manager.get_runtime_controller", lambda: controller)
    monkeypatch.setattr("bridges.stealth_order_bridge.get_runtime_controller", lambda: controller)
    return order, manager, rest_client, controller


def test_manual_rehide_persists_before_cancel_without_repricing_guards(rehide_case):
    order, manager, rest_client, _ = rehide_case
    operations = []
    manager._should_skip_anchor_reprice = MagicMock(side_effect=AssertionError("not repricing"))
    manager._quantize_reprice_price = MagicMock(side_effect=AssertionError("price unchanged"))
    manager._apply_reveal_condition_price_tracking = MagicMock(
        side_effect=AssertionError("condition configuration unchanged")
    )

    def persist(current):
        assert current["status"] == StealthOrderStatus.REVEALED.value
        pending = current["anchor_repricing_state_json"]["pending_rearm"]
        assert pending["reprice_reason"] == StealthMutationKind.REHIDE.value
        assert pending["placement_client_order_id"] == PLACEMENT_ID
        assert pending["desired_limit_price"] == current["limit_price"]
        operations.append("persist")
        return True

    def cancel(order_ids):
        assert operations == ["persist"]
        operations.append("cancel")
        return [{"success": True, "order_id": order_ids[0]}]

    manager._update_stealth_order.side_effect = persist
    rest_client.cancel_orders.side_effect = cancel

    assert manager.rehide_revealed_order(SID) is True

    assert operations == ["persist", "cancel"]
    assert order["status"] == StealthOrderStatus.REVEALED.value
    assert order["revealed_size"] == 25.0
    assert order["remaining_size"] == 0.0
    assert set(manager.in_memory_orders) == {SID}
    rest_client.cancel_orders.assert_called_once_with(order_ids=["exchange-1"])
    rest_client.place_limit_order.assert_not_called()


@pytest.mark.parametrize("outcome", ([{"success": False}], TimeoutError("cancel reply lost")))
def test_unconfirmed_manual_cancel_is_accepted_pending_not_hidden(rehide_case, outcome):
    order, manager, rest_client, _ = rehide_case
    if isinstance(outcome, Exception):
        rest_client.cancel_orders.side_effect = outcome
    else:
        rest_client.cancel_orders.return_value = outcome

    assert manager.rehide_revealed_order(SID) is True
    assert order["status"] == StealthOrderStatus.REVEALED.value
    assert order["anchor_repricing_state_json"]["pending_rearm"]
    assert order["anchor_repricing_state_json"]["active_exchange_order_id"] == "exchange-1"
    rest_client.place_limit_order.assert_not_called()


@pytest.mark.parametrize("status", (StealthOrderStatus.HIDDEN, StealthOrderStatus.CANCELLED, StealthOrderStatus.EXECUTED))
def test_manual_rehide_does_not_revive_non_revealed_orders(rehide_case, status):
    order, manager, rest_client, _ = rehide_case
    order["status"] = status.value

    with pytest.raises(ValueError):
        manager.rehide_revealed_order(SID)

    assert order["status"] == status.value
    rest_client.cancel_orders.assert_not_called()
    manager._update_stealth_order.assert_not_called()


@pytest.mark.parametrize("invalid_truth", ("filled", "missing_exchange_id", "unaccounted_size"))
def test_manual_rehide_requires_one_zero_fill_fully_accounted_placement(rehide_case, invalid_truth):
    order, manager, rest_client, _ = rehide_case
    if invalid_truth == "filled":
        order["executed_size"] = 1.0
    elif invalid_truth == "missing_exchange_id":
        order["anchor_repricing_state_json"]["active_exchange_order_id"] = None
    else:
        order["revealed_orders"][0]["revealed_size"] = 15.0

    assert manager.rehide_revealed_order(SID) is False

    assert order["status"] == StealthOrderStatus.REVEALED.value
    assert "pending_rearm" not in order["anchor_repricing_state_json"]
    rest_client.cancel_orders.assert_not_called()
    manager._update_stealth_order.assert_not_called()


@pytest.mark.parametrize("field", ("executed_size", "limit_price", "revealed_size"))
@pytest.mark.parametrize("invalid_value", (float("nan"), -1.0))
def test_manual_rehide_rejects_invalid_numeric_truth(rehide_case, field, invalid_value):
    order, manager, rest_client, _ = rehide_case
    order[field] = invalid_value

    assert manager.rehide_revealed_order(SID) is False

    assert "pending_rearm" not in order["anchor_repricing_state_json"]
    rest_client.cancel_orders.assert_not_called()
    manager._update_stealth_order.assert_not_called()


def test_manual_rehide_intent_write_failure_pauses_without_rest(rehide_case):
    order, manager, rest_client, controller = rehide_case
    previous_state = deepcopy(order["anchor_repricing_state_json"])
    manager._update_stealth_order.return_value = False

    assert manager.rehide_revealed_order(SID) is False

    assert order["status"] == StealthOrderStatus.REVEALED.value
    assert order["anchor_repricing_state_json"] == previous_state
    assert controller.state is EngineState.PAUSED
    rest_client.cancel_orders.assert_not_called()


def test_pending_manual_rehide_cannot_duplicate_cancel_request(rehide_case):
    order, manager, rest_client, _ = rehide_case
    assert manager.rehide_revealed_order(SID) is True
    pending = deepcopy(order["anchor_repricing_state_json"]["pending_rearm"])

    with pytest.raises(ValueError):
        manager.rehide_revealed_order(SID)

    assert order["anchor_repricing_state_json"]["pending_rearm"] == pending
    rest_client.cancel_orders.assert_called_once()


@pytest.mark.parametrize("other_kind", (StealthMutationKind.MOVE, StealthMutationKind.REPRICE))
def test_manual_rehide_claim_excludes_other_live_mutations(rehide_case, other_kind):
    _, manager, rest_client, _ = rehide_case
    assert manager.try_claim_mutation(other_kind, SID) is True
    with pytest.raises(ValueError):
        manager.rehide_revealed_order(SID)
    rest_client.cancel_orders.assert_not_called()

    manager.release_mutation(other_kind, SID)
    assert manager.try_claim_mutation(StealthMutationKind.REHIDE, SID) is True
    assert manager.try_claim_mutation(other_kind, SID) is False
    manager.release_mutation(StealthMutationKind.REHIDE, SID)
    assert manager.rehide_revealed_order(SID) is True
    # Durable pending intent protects the cancellation after the short claim ends.
    assert manager.try_claim_mutation(StealthMutationKind.REHIDE, SID) is True
    manager.release_mutation(StealthMutationKind.REHIDE, SID)


def test_manual_cancel_ack_preserves_price_policies_and_reprice_budget(rehide_case, monkeypatch):
    order, manager, rest_client, _ = rehide_case
    order["parent_order_id"] = ROOT_ID
    order["reveal_condition_type"] = RevealConditionType.PRICE_THRESHOLD.value
    order["reveal_condition_json"] = {
        "type": RevealConditionType.PRICE_THRESHOLD.value,
        "direction": "below",
        "price_threshold": 77160.0,
        "hold_duration_seconds": 0,
    }
    # A stale offset would alter this threshold if Rehide reused price tracking.
    order["anchor_repricing_state_json"]["reveal_condition_price_offsets"] = {"price_threshold": 1000.0}
    original = deepcopy(order)
    manager.db_client = object()
    parent_status = MagicMock(return_value=1)
    monkeypatch.setattr("core.stealth_order_manager.update_order_parent_status", parent_status)
    assert manager.rehide_revealed_order(SID) is True

    assert manager.consume_anchor_rearm_cancellation(
        PLACEMENT_ID, exchange_order_id="exchange-1"
    ) is StealthOrderStatus.HIDDEN

    assert order["stealth_order_id"] == SID
    assert order["parent_order_id"] == ROOT_ID
    assert resolve_stealth_chain_root(order) == ROOT_ID
    for field in ("limit_price", "reveal_condition_json", "anchor_repricing_policy_json"):
        assert order[field] == original[field]
    state = order["anchor_repricing_state_json"]
    for field in ("last_reprice_at", "next_reprice_at", "reprice_history", "reveal_condition_price_offsets"):
        assert state[field] == original["anchor_repricing_state_json"][field]
    assert state["reveal_armed_at"]
    assert "pending_rearm" not in state
    assert state["active_placement_client_order_id"] is None
    assert state["active_exchange_order_id"] is None
    assert order["remaining_size"] == 25.0
    assert order["revealed_size"] == 0.0
    assert order["condition_first_met_at"] is None
    assert order["condition_confirmed_at"] is None
    assert parent_status.call_args_list == [call(PLACEMENT_ID, "CANCELLED"), call(ROOT_ID, "PENDING")]
    assert manager.is_anchor_rearm_placement_tombstoned(PLACEMENT_ID) is True
    persisted_count = manager._update_stealth_order.call_count
    assert manager.consume_anchor_rearm_cancellation(PLACEMENT_ID) is StealthOrderStatus.HIDDEN
    assert manager._update_stealth_order.call_count == persisted_count
    rest_client.place_limit_order.assert_not_called()

    # No special manual pause/re-arm policy: a satisfied condition triggers again.
    condition_met, _ = manager.evaluate_conditions(
        SID,
        market_data={"source": "ticker", "price": 77150.0, "time": datetime.utcnow()},
    )
    assert condition_met is True
    assert order["status"] == StealthOrderStatus.TRIGGERED.value


def test_manual_rehide_audit_is_not_classified_as_a_reprice(rehide_case):
    order, manager, _, _ = rehide_case
    assert manager.rehide_revealed_order(SID) is True
    assert manager.consume_anchor_rearm_cancellation(PLACEMENT_ID) is StealthOrderStatus.HIDDEN
    event = order["revealed_orders"][0]
    assert event["cancelled_for_reprice"] is False
    assert event["reprice_reason"] == StealthMutationKind.REHIDE.value
    manager.db_client = MagicMock()
    manager.db_client.execute_update.return_value = 1

    assert type(manager)._record_reveal_event(manager, order, event) is True

    _, parameters = manager.db_client.execute_update.call_args.args
    # Existing audit columns: cancelled_for_reprice, reprice_reason, event type.
    assert parameters[16:19] == (False, "rehide", "rehide")


def test_manual_rehide_time_policy_restarts_at_confirmed_hidden_transition(rehide_case):
    order, manager, _, _ = rehide_case
    assert manager.rehide_revealed_order(SID) is True
    assert "reveal_armed_at" not in order["anchor_repricing_state_json"]
    assert manager.consume_anchor_rearm_cancellation(PLACEMENT_ID) is StealthOrderStatus.HIDDEN
    armed = datetime.fromisoformat(order["anchor_repricing_state_json"]["reveal_armed_at"]).replace(tzinfo=timezone.utc)
    evaluator = TimeDelayEvaluator()
    condition = order["reveal_condition_json"]
    assert evaluator.evaluate_truth({}, condition, order, now_utc=armed).truth is False
    assert evaluator.evaluate_truth({}, condition, order, now_utc=armed + timedelta(seconds=60)).truth is True


@pytest.mark.parametrize("root_backed", (False, True))
def test_manual_rehide_never_reuses_cancelled_placement_uuid(rehide_case, root_backed):
    order, manager, _, _ = rehide_case
    placement_id = PLACEMENT_ID
    if root_backed:
        placement_id = SID
        event = order["revealed_orders"][0]
        event["placed_order_id"] = SID
        event["placement_client_order_id"] = SID
        order["anchor_repricing_state_json"]["active_placement_client_order_id"] = SID
        manager._placed_order_index[SID] = order
    assert manager.rehide_revealed_order(SID) is True
    assert manager.consume_anchor_rearm_cancellation(placement_id) is StealthOrderStatus.HIDDEN

    next_id = manager._placement_client_order_id_for_order(order)
    assert str(UUID(next_id)) == next_id
    assert next_id not in (SID, PLACEMENT_ID)
    assert resolve_stealth_chain_root(order) == SID
    assert order["anchor_repricing_policy_json"]["enabled"] is False


def test_fill_racing_manual_rehide_never_restores_hidden_inventory(rehide_case):
    order, manager, rest_client, controller = rehide_case
    assert manager.rehide_revealed_order(SID) is True

    assert manager.consume_anchor_rearm_cancellation(
        PLACEMENT_ID, exchange_order_id="exchange-1", cumulative_filled_size=2.0, number_of_fills=1
    ) is StealthOrderStatus.CANCELLED

    assert order["remaining_size"] == 0.0
    assert order["executed_size"] == 2.0
    assert order["revealed_orders"][0]["rearm_aborted_for_fill"] is True
    assert "reveal_armed_at" not in order["anchor_repricing_state_json"]
    assert controller.state is EngineState.PAUSED
    rest_client.place_limit_order.assert_not_called()


@pytest.fixture
def rehide_bridge(rehide_case):
    _, _, _, controller = rehide_case
    manager = MagicMock()
    manager.rehide_revealed_order.return_value = True
    bridge = StealthOrderBridge(manager, order_engine=None)
    bridge._decisions_ready.set()
    yield bridge, manager, controller
    bridge.scheduler.stop()


@pytest.mark.parametrize("blocker", ("startup", "paused"))
def test_bridge_rehide_requires_readiness_and_running_admission(rehide_bridge, blocker):
    bridge, manager, controller = rehide_bridge
    if blocker == "startup":
        bridge._decisions_ready.clear()
    else:
        controller.request_pause()
    with pytest.raises(RuntimeError):
        bridge.rehide_stealth_order(SID)
    manager.rehide_revealed_order.assert_not_called()
    assert controller.total_inflight() == 0


def test_bridge_rehide_tracks_admitted_work_inside_sid_lock(rehide_bridge):
    bridge, manager, controller = rehide_bridge
    lock_held = False
    original_lock = bridge._get_order_action_lock(SID)

    @contextmanager
    def action_lock(_sid):
        nonlocal lock_held
        assert _sid == SID
        with original_lock:
            lock_held = True
            try:
                yield
            finally:
                lock_held = False

    def rehide(sid):
        assert sid == SID
        assert lock_held
        assert controller.total_inflight() == 1
        return True

    bridge._get_order_action_lock = action_lock
    manager.rehide_revealed_order.side_effect = rehide
    assert bridge.rehide_stealth_order(SID) is True
    assert controller.total_inflight() == 0
    assert lock_held is False


@pytest.mark.parametrize("blocker", ("readiness", "pause"))
def test_bridge_rechecks_gates_after_waiting_for_sid_lock(rehide_bridge, blocker):
    bridge, manager, controller = rehide_bridge

    @contextmanager
    def delayed_lock(_sid):
        if blocker == "readiness":
            bridge._decisions_ready.clear()
        else:
            controller.request_pause()
        yield

    bridge._get_order_action_lock = delayed_lock
    with pytest.raises(RuntimeError):
        bridge.rehide_stealth_order(SID)
    manager.rehide_revealed_order.assert_not_called()
    assert controller.total_inflight() == 0
