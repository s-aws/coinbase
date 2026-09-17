"""Repricing offsets follow operator edits and identify each composite field."""

import json
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime
from unittest.mock import Mock

import pytest

import core.stealth_order_manager as manager_module
from core.enums import RevealConditionType, StealthOrderStatus
from core.exceptions import StealthOrderPersistenceError
from core.stealth_order_manager import (
    StealthOrderManager,
    _iter_reveal_condition_price_fields,
)


pytestmark = pytest.mark.regression
SID = "392aa4af-b330-442b-9aed-bf15ac1e985f"
BASE_TIME = datetime(2026, 9, 17, 12, 0)
OFFSETS = "reveal_condition_price_offsets"


def _price(threshold):
    return {
        "type": RevealConditionType.PRICE_THRESHOLD.value,
        "price_threshold": threshold,
        "direction": "below",
        "hold_duration_seconds": 2,
    }


def _composite():
    return {
        "type": RevealConditionType.COMPOSITE.value,
        "operator": "AND",
        "conditions": [
            _price(90.0),
            {
                "type": RevealConditionType.COMPOSITE.value,
                "operator": "OR",
                "conditions": [
                    _price(120.0),
                    {"type": RevealConditionType.CUMULATIVE_VOLUME.value,
                     "price_level": 80.0, "required_volume": 25.0},
                    {"type": RevealConditionType.CUMULATIVE_VOLUME.value,
                     "price_level": 130.0, "required_volume": 50.0},
                ],
            },
            {"type": RevealConditionType.SPREAD.value, "max_spread": 2.0},
            {"type": RevealConditionType.TIME_DELAY.value, "delay_seconds": 30},
            {"type": RevealConditionType.PRODUCT_RATIO.value, "ratio_threshold": 1.2},
        ],
    }


def _manager(condition=None, status=StealthOrderStatus.HIDDEN):
    manager = StealthOrderManager.__new__(StealthOrderManager)
    manager.log_callback = Mock()
    manager._update_stealth_order = Mock(return_value=True)
    manager._dispatch_lifecycle_event = Mock()
    manager._notify_schedule_invalidated = Mock()
    condition = deepcopy(condition if condition is not None else _price(110.0))
    order = {
        "stealth_order_id": SID,
        "limit_price": 100.0,
        "status": status.value,
        "reveal_condition_type": condition["type"],
        "reveal_condition_json": condition,
        "condition_first_met_at": BASE_TIME if status is StealthOrderStatus.PENDING else None,
        "condition_confirmed_at": None,
        "updated_at": BASE_TIME,
        "anchor_repricing_state_json": {
            "reprice_history": ["2026-09-17T11:00:00"],
            "reveal_armed_at": "2026-09-17T11:00:00",
        },
    }
    manager.in_memory_orders = {SID: order}
    return manager, order


def _reprice(manager, order, new_limit):
    state = manager._normalize_anchor_repricing_state(order.get("anchor_repricing_state_json"))
    changed = manager._apply_reveal_condition_price_tracking(order, state, new_limit)
    order["limit_price"] = new_limit
    order["anchor_repricing_state_json"] = state
    return changed


def _values(condition):
    return {path: parent[key] for parent, key, path in _iter_reveal_condition_price_fields(condition)}


def test_manual_threshold_edit_invalidates_before_persistence_and_rebases_reprices():
    manager, order = _manager(status=StealthOrderStatus.PENDING)
    order["anchor_repricing_state_json"][OFFSETS] = {"price_threshold": 10.0}
    persisted = []
    manager._update_stealth_order.side_effect = lambda row: persisted.append(deepcopy(row)) or True

    assert manager.update_price_condition(SID, price_threshold=130.0)

    assert len(persisted) == 1
    assert OFFSETS not in persisted[0]["anchor_repricing_state_json"]
    assert persisted[0]["reveal_condition_json"]["price_threshold"] == 130.0
    assert order["status"] == StealthOrderStatus.HIDDEN.value
    assert _reprice(manager, order, 200.0)
    assert order["reveal_condition_json"]["price_threshold"] == 230.0
    assert _reprice(manager, order, 250.0)
    assert order["reveal_condition_json"]["price_threshold"] == 280.0
    assert order["anchor_repricing_state_json"][OFFSETS] == {"price_threshold": 30.0}
    assert order["anchor_repricing_state_json"]["reprice_history"] == ["2026-09-17T11:00:00"]


def test_manual_edit_without_prior_anchor_state_still_captures_new_offset():
    manager, order = _manager()
    order.pop("anchor_repricing_state_json")

    assert manager.update_price_condition(SID, price_threshold=95.0)
    assert _reprice(manager, order, 120.0)

    assert order["reveal_condition_json"]["price_threshold"] == 115.0
    assert order["anchor_repricing_state_json"][OFFSETS] == {"price_threshold": -5.0}


def test_hold_only_edit_preserves_existing_price_offsets():
    manager, order = _manager()
    order["anchor_repricing_state_json"][OFFSETS] = {"price_threshold": 10.0}
    previous_state = deepcopy(order["anchor_repricing_state_json"])

    assert manager.update_price_condition(SID, price_threshold=110.0, hold_duration_seconds=5)

    assert order["anchor_repricing_state_json"] == previous_state
    assert order["reveal_condition_json"]["hold_duration_seconds"] == 5


@pytest.mark.parametrize(
    ("status", "raises"),
    [(StealthOrderStatus.PENDING, False), (StealthOrderStatus.HIDDEN, False),
     (StealthOrderStatus.REVEALED, False), (StealthOrderStatus.HIDDEN, True)],
)
def test_failed_edit_restores_condition_anchor_state_and_lifecycle(monkeypatch, status, raises):
    manager, order = _manager(status=status)
    order["anchor_repricing_state_json"][OFFSETS] = {"price_threshold": 10.0}
    if raises:
        order.pop("anchor_repricing_state_json")
    original_anchor_state = order.get("anchor_repricing_state_json")
    before = deepcopy(order)
    controller = Mock()
    monkeypatch.setattr(manager_module, "get_runtime_controller", lambda: controller)
    manager._update_stealth_order = Mock(
        side_effect=RuntimeError("database unavailable") if raises else None,
        return_value=False,
    )

    with pytest.raises(RuntimeError if raises else StealthOrderPersistenceError):
        manager.update_price_condition(SID, price_threshold=130.0, hold_duration_seconds=5)

    assert order == before
    assert order.get("anchor_repricing_state_json") is original_anchor_state
    assert controller.request_pause.called
    manager._notify_schedule_invalidated.assert_not_called()
    manager._dispatch_lifecycle_event.assert_not_called()


def test_nested_composite_prices_move_independently_and_nonprice_fields_stay_unchanged():
    manager, order = _manager(_composite())
    before = deepcopy(order["reveal_condition_json"])

    assert _reprice(manager, order, 110.0)

    condition = order["reveal_condition_json"]
    assert _values(condition) == {
        "conditions.0.price_threshold": 100.0,
        "conditions.1.conditions.0.price_threshold": 130.0,
        "conditions.1.conditions.1.price_level": 90.0,
        "conditions.1.conditions.2.price_level": 140.0,
    }
    assert condition["conditions"][2:] == before["conditions"][2:]
    nested = condition["conditions"][1]["conditions"]
    assert [nested[1]["required_volume"], nested[2]["required_volume"]] == [25.0, 50.0]
    assert condition["conditions"][0]["hold_duration_seconds"] == 2


def test_new_nested_path_captures_offset_without_replacing_existing_paths():
    manager, order = _manager(_composite())
    order["anchor_repricing_state_json"][OFFSETS] = {"conditions.0.price_threshold": -12.0}

    assert _reprice(manager, order, 110.0)

    offsets = order["anchor_repricing_state_json"][OFFSETS]
    assert offsets["conditions.0.price_threshold"] == -12.0
    assert offsets["conditions.1.conditions.0.price_threshold"] == 20.0
    assert _values(order["reveal_condition_json"])["conditions.0.price_threshold"] == 98.0


def test_legacy_composite_field_only_offsets_are_rebuilt_from_each_current_field():
    manager, order = _manager(_composite())
    order["anchor_repricing_state_json"][OFFSETS] = {"price_threshold": 20.0, "price_level": 30.0}

    assert _reprice(manager, order, 110.0)

    assert order["anchor_repricing_state_json"][OFFSETS] == {
        "conditions.0.price_threshold": -10.0,
        "conditions.1.conditions.0.price_threshold": 20.0,
        "conditions.1.conditions.1.price_level": -20.0,
        "conditions.1.conditions.2.price_level": 30.0,
    }


def test_composite_offset_paths_survive_json_restart_and_another_reprice():
    manager, order = _manager(_composite())
    assert _reprice(manager, order, 110.0)
    restored = json.loads(json.dumps({key: order[key] for key in (
        "limit_price", "reveal_condition_json", "anchor_repricing_state_json"
    )}))
    restarted, restarted_order = _manager()
    restarted_order.update(restored)

    assert _reprice(restarted, restarted_order, 130.0)

    assert _values(restarted_order["reveal_condition_json"]) == {
        "conditions.0.price_threshold": 120.0,
        "conditions.1.conditions.0.price_threshold": 150.0,
        "conditions.1.conditions.1.price_level": 110.0,
        "conditions.1.conditions.2.price_level": 160.0,
    }
    assert restarted_order["anchor_repricing_state_json"][OFFSETS] == restored["anchor_repricing_state_json"][OFFSETS]


def test_existing_root_offset_shape_remains_authoritative():
    manager, order = _manager()
    order["anchor_repricing_state_json"][OFFSETS] = {"price_threshold": 7.0}

    assert _reprice(manager, order, 120.0)

    assert order["reveal_condition_json"]["price_threshold"] == 127.0
    assert order["anchor_repricing_state_json"][OFFSETS] == {"price_threshold": 7.0}


def test_nonprice_condition_is_not_changed_by_tracking():
    manager, order = _manager({"type": RevealConditionType.SPREAD.value, "max_spread": 2.0})
    before = deepcopy(order["reveal_condition_json"])

    assert not _reprice(manager, order, 120.0)
    assert order["reveal_condition_json"] == before


def test_pending_rearm_rejects_edit_without_invalidating_offsets():
    manager, order = _manager(status=StealthOrderStatus.REVEALED)
    order["anchor_repricing_state_json"].update({OFFSETS: {"price_threshold": 10.0}, "pending_rearm": {}})
    before = deepcopy(order)

    assert not manager.update_price_condition(SID, price_threshold=130.0)

    assert order == before
    manager._update_stealth_order.assert_not_called()
    manager._notify_schedule_invalidated.assert_not_called()


def test_iterator_uses_root_compatible_and_distinct_nested_paths():
    root = _price(110.0)
    assert list(_iter_reveal_condition_price_fields(root)) == [(root, "price_threshold", "price_threshold")]
    condition = _composite()
    fields = list(_iter_reveal_condition_price_fields(condition))

    assert [path for _, _, path in fields] == [
        "conditions.0.price_threshold",
        "conditions.1.conditions.0.price_threshold",
        "conditions.1.conditions.1.price_level",
        "conditions.1.conditions.2.price_level",
    ]
    assert fields[0][0] is condition["conditions"][0]


def test_revealed_composite_offsets_change_only_after_matching_cancel_ack(monkeypatch):
    from tests.regression.test_anchor_reprice_phantom_parent import _revealed_order

    manager, _ = _manager()
    order = _revealed_order()
    order.update({
        "stealth_order_id": SID,
        "limit_price": 100.0,
        "reveal_condition_type": RevealConditionType.COMPOSITE.value,
        "reveal_condition_json": _composite(),
    })
    placement_id = "50e47ed6-90a4-4b38-86e0-7666e6c6dac5"
    order["revealed_orders"][0].update({
        "placed_order_id": placement_id,
        "placement_client_order_id": placement_id,
        "placement_price": 100.0,
    })
    state = order["anchor_repricing_state_json"]
    state.update({
        "active_placement_client_order_id": placement_id,
        "active_exchange_price": 100.0,
        OFFSETS: {"price_threshold": 20.0, "price_level": 30.0},
    })
    manager.in_memory_orders = {SID: order}
    manager._placed_order_index = {placement_id: order}
    manager._quantize_reprice_price = lambda _product, _side, price, **kwargs: price
    manager._record_reveal_event = Mock(return_value=True)
    persisted = []
    manager._update_stealth_order.side_effect = lambda row: persisted.append(deepcopy(row)) or True
    rest_client = Mock()
    rest_client.cancel_orders.return_value = [{"success": True, "order_id": "exchange-1"}]
    monkeypatch.setattr("configuration.REST_CLIENT", rest_client)
    controller = Mock()
    controller.track_inflight.return_value = nullcontext()
    monkeypatch.setattr(manager_module, "get_runtime_controller", lambda: controller)
    before_condition = deepcopy(order["reveal_condition_json"])
    before_offsets = deepcopy(state[OFFSETS])

    assert manager._apply_revealed_anchor_reprice(
        order, order["anchor_repricing_policy_json"], state, {},
        110.0, 110.0, 120.0, "reference_price_updated_slide_step",
    )

    assert order["status"] == StealthOrderStatus.REVEALED.value
    assert order["limit_price"] == 100.0
    assert order["reveal_condition_json"] == persisted[0]["reveal_condition_json"] == before_condition
    assert state[OFFSETS] == persisted[0]["anchor_repricing_state_json"][OFFSETS] == before_offsets
    assert state["pending_rearm"]["desired_limit_price"] == 110.0
    rest_client.cancel_orders.assert_called_once_with(order_ids=["exchange-1"])

    assert manager.consume_anchor_rearm_cancellation(
        placement_id, exchange_order_id="exchange-1"
    ) is StealthOrderStatus.HIDDEN

    assert order["limit_price"] == 110.0
    assert _values(order["reveal_condition_json"]) == {
        "conditions.0.price_threshold": 100.0,
        "conditions.1.conditions.0.price_threshold": 130.0,
        "conditions.1.conditions.1.price_level": 90.0,
        "conditions.1.conditions.2.price_level": 140.0,
    }
    assert len(persisted) == 2
    assert persisted[-1]["reveal_condition_json"] == order["reveal_condition_json"]
    assert "pending_rearm" not in order["anchor_repricing_state_json"]
    rest_client.place_limit_order.assert_not_called()
    controller.request_pause.assert_not_called()
