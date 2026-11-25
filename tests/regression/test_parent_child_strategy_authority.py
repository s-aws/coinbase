"""Regression coverage for root strategy / child execution ownership."""

import inspect
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from configuration import PRODUCT_METADATA
from core.enums import StealthOrderStatus
from core.order_engine import OrderEngine
from core.stealth_order_manager import StealthOrderManager


ROOT = "root-strategy"
CHILD = "span-child"


@pytest.fixture(autouse=True)
def _product_metadata(monkeypatch):
    monkeypatch.setitem(
        PRODUCT_METADATA,
        "BTC-USDC",
        {
            "price_increment": "0.01",
            "base_increment": "0.00000001",
            "base_min_size": "0.00000001",
            "quote_min_size": "0",
        },
    )


def _price_order(
    stealth_order_id,
    *,
    limit_price,
    threshold,
    direction,
    parent_order_id=None,
    reason="normal_placement",
    follow_up_direction="opposite",
    policy=None,
):
    return {
        "stealth_order_id": stealth_order_id,
        "product_id": "BTC-USDC",
        "side": "BUY" if direction == "below" else "SELL",
        "total_size": 1.0,
        "remaining_size": 1.0,
        "limit_price": float(limit_price),
        "status": StealthOrderStatus.HIDDEN.value,
        "reveal_condition_type": "price",
        "reveal_condition_json": {
            "type": "price",
            "price_threshold": float(threshold),
            "direction": direction,
            "hold_duration_seconds": 3,
        },
        "sizing_strategy_json": {"type": "fixed"},
        "reveal_pricing_policy": "configured_limit",
        "follow_up_reveal_direction": follow_up_direction,
        "parent_order_id": parent_order_id,
        "reason": reason,
        "anchor_repricing_policy_json": policy or {"enabled": False},
        "anchor_repricing_state_json": {},
    }


@pytest.mark.regression
def test_child_target_movement_resolves_current_root_definition(monkeypatch):
    manager = StealthOrderManager(db_client=None)
    root = _price_order(
        ROOT, limit_price=100, threshold=80, direction="below"
    )
    child = _price_order(
        CHILD,
        limit_price=95,
        threshold=80,
        direction="below",
        parent_order_id=ROOT,
    )
    manager.in_memory_orders.update({ROOT: root, CHILD: child})

    rows = {
        ROOT: {"target_movement": 0.02, "target_movement_type": "P"},
        CHILD: {"target_movement": 0.01, "target_movement_type": "P"},
    }
    monkeypatch.setattr(
        "core.stealth_order_manager.get_parent_order",
        lambda client_order_id: rows.get(client_order_id),
    )

    assert manager._resolve_target_movement_for_plan(CHILD, child) == (
        0.02,
        "P",
        "order_parent",
    )

    # Clearing the root is also an immediate strategy edit. A stale child copy
    # must not silently resurrect the old value.
    rows[ROOT] = {"target_movement": None, "target_movement_type": None}
    assert manager._resolve_target_movement_for_plan(CHILD, child) == (
        None,
        None,
        "order_parent",
    )


@pytest.mark.regression
def test_order_template_target_resolution_reads_current_root_row():
    engine = OrderEngine.__new__(OrderEngine)
    engine.orderbook_lock = threading.RLock()
    engine.orderbook = SimpleNamespace(
        child_order_ids={CHILD: ROOT},
        parent_order_ids={
            ROOT: {"target_movement": {"movement": 0.01, "type": "P"}}
        },
        order={ROOT: {"product_id": "BTC-USDC"}},
    )
    engine.db_module = Mock()
    engine.db_module.get_parent_order.return_value = {
        "target_movement": 0.03,
        "target_movement_type": "P",
    }
    engine.fee_manager = None

    assert engine.resolve_parent_target_movement(CHILD) == {
        "movement": 0.03,
        "type": "P",
    }

    engine.db_module.get_parent_order.return_value = {
        "target_movement": None,
        "target_movement_type": None,
    }
    assert engine.resolve_parent_target_movement(CHILD) is None


@pytest.mark.regression
def test_follow_up_threshold_mirrors_child_relative_percentage():
    manager = StealthOrderManager(db_client=None)
    root = _price_order(
        ROOT, limit_price=100, threshold=80, direction="below"
    )
    child = _price_order(
        CHILD,
        limit_price=95,
        threshold=80,
        direction="below",
        parent_order_id=ROOT,
        # A stale child copy must not override the current root policy.
        follow_up_direction="same",
    )
    manager.in_memory_orders.update({ROOT: root, CHILD: child})
    create_order = Mock(return_value="follow-up")
    manager.create_stealth_order = create_order

    manager.create_follow_up_stealth_order(
        original_stealth_order_id=CHILD,
        side="SELL",
        total_size=1.0,
        limit_price=105.0,
        target_movement=0.02,
        target_movement_type="P",
    )

    created = create_order.call_args.kwargs
    condition = created["reveal_condition"]
    expected_distance = abs(80.0 / 95.0 - 1.0)
    assert created["limit_price"] == 105.0
    assert condition["direction"] == "above"
    assert condition["price_threshold"] == pytest.approx(
        105.0 * (1.0 + expected_distance)
    )
    assert condition["hold_duration_seconds"] == 3
    assert created["follow_up_reveal_direction"] == "opposite"


@pytest.mark.regression
def test_buy_follow_up_mirrors_above_threshold_below_new_target():
    manager = StealthOrderManager(db_client=None)
    root = _price_order(
        ROOT, limit_price=110, threshold=120, direction="above"
    )
    child = _price_order(
        CHILD,
        limit_price=105,
        threshold=120,
        direction="above",
        parent_order_id=ROOT,
    )
    manager.in_memory_orders.update({ROOT: root, CHILD: child})
    create_order = Mock(return_value="follow-up")
    manager.create_stealth_order = create_order

    manager.create_follow_up_stealth_order(
        original_stealth_order_id=CHILD,
        side="BUY",
        total_size=1.0,
        limit_price=95.0,
        target_movement=0.02,
        target_movement_type="P",
    )

    condition = create_order.call_args.kwargs["reveal_condition"]
    expected_distance = abs(120.0 / 105.0 - 1.0)
    assert condition["direction"] == "below"
    assert condition["price_threshold"] == pytest.approx(
        95.0 * (1.0 - expected_distance)
    )


@pytest.mark.regression
def test_follow_up_threshold_uses_final_retreated_target():
    manager = StealthOrderManager(db_client=None)
    root = _price_order(
        ROOT, limit_price=100, threshold=80, direction="below"
    )
    child = _price_order(
        CHILD,
        limit_price=95,
        threshold=80,
        direction="below",
        parent_order_id=ROOT,
        policy={
            "enabled": True,
            "target_distance": 0.001,
            "max_distance": 0.01,
            "follow_up_retreat_distance": 0.1,
            "follow_up_retreat_jitter": 0.0,
            "inherit_to_follow_ups": True,
        },
    )
    manager.in_memory_orders.update({ROOT: root, CHILD: child})
    create_order = Mock(return_value="follow-up")
    manager.create_stealth_order = create_order

    manager.create_follow_up_stealth_order(
        original_stealth_order_id=CHILD,
        side="SELL",
        total_size=1.0,
        limit_price=105.0,
        target_movement=0.02,
        target_movement_type="P",
    )

    created = create_order.call_args.kwargs
    final_target = 115.5
    expected_distance = abs(80.0 / 95.0 - 1.0)
    assert created["limit_price"] == final_target
    assert created["reveal_condition"]["price_threshold"] == pytest.approx(
        final_target * (1.0 + expected_distance)
    )


@pytest.mark.regression
def test_root_threshold_edit_updates_initial_and_derived_hidden_children():
    manager = StealthOrderManager(db_client=None)
    root = _price_order(
        ROOT, limit_price=100, threshold=80, direction="below"
    )
    initial_child = _price_order(
        CHILD,
        limit_price=90,
        threshold=80,
        direction="below",
        parent_order_id=ROOT,
    )
    manager.in_memory_orders.update({ROOT: root, CHILD: initial_child})

    derived_condition = manager._derive_follow_up_reveal_condition(
        source_order=initial_child,
        strategy_order=root,
        final_target_price=105.0,
        direction_choice=manager._coerce_follow_up_direction("opposite"),
    )
    derived_child = _price_order(
        "derived-child",
        limit_price=105,
        threshold=derived_condition["price_threshold"],
        direction=derived_condition["direction"],
        parent_order_id=ROOT,
        reason="follow_up_replacement",
    )
    derived_child["reveal_condition_json"] = derived_condition
    manager.in_memory_orders["derived-child"] = derived_child

    manager._update_stealth_order = Mock(return_value=True)
    manager.reset_continuous_condition = Mock(return_value=False)

    assert manager.update_price_condition(
        ROOT,
        price_threshold=75.0,
        hold_duration_seconds=5,
    )

    assert initial_child["reveal_condition_json"]["price_threshold"] == 75.0
    assert initial_child["reveal_condition_json"]["direction"] == "below"
    expected_distance = abs(75.0 / 90.0 - 1.0)
    assert derived_child["reveal_condition_json"]["direction"] == "above"
    assert derived_child["reveal_condition_json"][
        "price_threshold"
    ] == pytest.approx(105.0 * (1.0 + expected_distance))
    assert derived_child["reveal_condition_json"]["hold_duration_seconds"] == 5


@pytest.mark.regression
def test_full_and_partial_fill_paths_delegate_condition_derivation():
    partial_source = inspect.getsource(
        OrderEngine._create_partial_fill_follow_up
    )
    full_source = inspect.getsource(OrderEngine.handle_filled_order)

    for source in (partial_source, full_source):
        assert "follow_up_reveal_condition" not in source
        assert '"price_threshold"] = float(follow_up_price)' not in source
