"""Regression coverage for canonical stealth placement truth.

These tests pin the approved invariants: one canonical price reaches both
local persistence and REST, and no rejected/indeterminate response is allowed
to consume reveal size or create accepted-placement state.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.enums import (
    OrderStatus,
    RevealPricingPolicy,
    StealthLifecycleEvent,
    StealthOrderStatus,
)
from core.exceptions import OrderCreationError, StealthOrderPersistenceError
from core.stealth_order_manager import StealthOrderManager


@pytest.fixture
def five_tick_product(monkeypatch):
    from configuration import PRODUCT_METADATA

    product_id = "TEST-5-CDE"
    monkeypatch.setitem(
        PRODUCT_METADATA,
        product_id,
        {
            "price_increment": "5",
            "base_increment": "1",
            "base_min_size": "1",
            "quote_min_size": "0",
        },
    )
    return product_id


def _triggered_order(product_id: str, *, side: str = "BUY"):
    sid = "11111111-2222-4333-8444-555555555555"
    return sid, {
        "stealth_order_id": sid,
        "product_id": product_id,
        "side": side,
        "total_size": 5.0,
        "revealed_size": 0.0,
        "remaining_size": 5.0,
        "executed_size": 0.0,
        "limit_price": 77115.0 if side == "BUY" else 77120.0,
        "status": StealthOrderStatus.TRIGGERED.value,
        "reveal_condition_type": "time_delay",
        "reveal_condition_json": {"type": "time_delay", "delay_seconds": 0},
        "reveal_pricing_policy": "configured_limit",
        "sizing_strategy_json": {"type": "fixed"},
        "revealed_orders": [],
        "reason": "normal_placement",
        "parent_order_id": None,
        "condition_confirmed_at": None,
        "anchor_repricing_state_json": {},
    }


def _manager_for_reveal(product_id: str, response_or_exception, monkeypatch):
    manager = StealthOrderManager(db_client=None)
    sid, order = _triggered_order(product_id)
    manager.in_memory_orders[sid] = order
    post_calls = []
    lifecycle = []
    parent_statuses = []

    manager.order_placement_hooks = SimpleNamespace(
        call_pre_submission_hooks=lambda payload: None,
        call_post_submission_hooks=lambda payload, response: post_calls.append(
            (dict(payload), response)
        ),
    )
    manager._get_current_market_data = lambda _product_id: {
        "price": 77110.0,
        "bid": 77105.0,
        "ask": 77115.0,
        "volume_1m": 1.0,
        "source": "ticker",
    }
    manager._resolve_target_movement_for_plan = lambda *args, **kwargs: (
        0.0,
        "P",
        "test",
    )
    manager._dispatch_lifecycle_event = (
        lambda stealth_order_id, event, order_data, extra=None: lifecycle.append(
            (event, dict(extra or {}), order_data.get("status"))
        )
    )
    monkeypatch.setattr(
        "core.stealth_order_manager.update_order_parent_status",
        lambda client_order_id, status: parent_statuses.append(
            (client_order_id, status)
        ),
    )
    monkeypatch.setattr(
        "core.stealth_order_manager.update_order_parent_price",
        lambda client_order_id, price: True,
    )

    def place_limit_order(**kwargs):
        if isinstance(response_or_exception, BaseException):
            raise response_or_exception
        if callable(response_or_exception):
            return response_or_exception(kwargs)
        return response_or_exception

    monkeypatch.setattr(
        "configuration.REST_CLIENT",
        SimpleNamespace(place_limit_order=place_limit_order),
    )
    return manager, sid, order, post_calls, lifecycle, parent_statuses


@pytest.mark.regression
@pytest.mark.parametrize(
    ("side", "requested", "expected"),
    (("BUY", 77119.0, 77115.0), ("SELL", 77119.0, 77120.0)),
)
def test_create_normalizes_before_every_local_write(
    five_tick_product,
    monkeypatch,
    side,
    requested,
    expected,
):
    parent_rows = []
    monkeypatch.setattr(
        "core.stealth_order_manager.insert_order_parent",
        lambda **kwargs: parent_rows.append(dict(kwargs)) or 1,
    )
    manager = StealthOrderManager(db_client=None)
    manager._dispatch_lifecycle_event = lambda *args, **kwargs: None
    condition = {
        "type": "price",
        "direction": "below",
        "price_threshold": requested,
    }

    sid = manager.create_stealth_order(
        product_id=five_tick_product,
        side=side,
        total_size=5.0,
        limit_price=requested,
        reveal_condition=condition,
    )

    assert manager.in_memory_orders[sid]["limit_price"] == expected
    assert parent_rows[0]["price"] == expected
    assert parent_rows[0]["reject_existing"] is True
    assert condition["price_threshold"] == requested, (
        "trigger thresholds are reference data and must not be price-normalized"
    )


@pytest.mark.regression
def test_creation_parent_persistence_failure_never_activates_order(
    five_tick_product,
    monkeypatch,
):
    stealth_order_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    manager = StealthOrderManager(db_client=None)
    saved_orders = []
    manager._save_stealth_order_to_db = (
        lambda order: saved_orders.append(dict(order)) or True
    )
    monkeypatch.setattr(
        "core.stealth_order_manager.insert_order_parent",
        lambda **kwargs: None,
    )

    with pytest.raises(OrderCreationError, match="returned no row id"):
        manager.create_stealth_order(
            product_id=five_tick_product,
            side="BUY",
            total_size=5.0,
            limit_price=77119.0,
            reveal_condition={"type": "time_delay", "delay_seconds": 0},
            stealth_order_id=stealth_order_id,
        )

    assert stealth_order_id not in manager.in_memory_orders
    assert saved_orders[0]["status"] == StealthOrderStatus.ERROR.value


@pytest.mark.regression
def test_creation_stealth_persistence_failure_never_touches_parent(
    five_tick_product,
    monkeypatch,
):
    stealth_order_id = "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff"
    manager = StealthOrderManager(db_client=None)
    manager._save_stealth_order_to_db = lambda order: False
    parent_inserts = []
    monkeypatch.setattr(
        "core.stealth_order_manager.insert_order_parent",
        lambda **kwargs: parent_inserts.append(kwargs) or 1,
    )

    with pytest.raises(OrderCreationError, match="persistence failed"):
        manager.create_stealth_order(
            product_id=five_tick_product,
            side="BUY",
            total_size=5.0,
            limit_price=77119.0,
            reveal_condition={"type": "time_delay", "delay_seconds": 0},
            stealth_order_id=stealth_order_id,
        )

    assert stealth_order_id not in manager.in_memory_orders
    assert parent_inserts == []


@pytest.mark.regression
def test_creation_activation_failure_marks_new_parent_failed_and_inactive(
    five_tick_product,
    monkeypatch,
):
    stealth_order_id = "cccccccc-dddd-4eee-8fff-aaaaaaaaaaaa"
    manager = StealthOrderManager(db_client=None)
    manager._save_stealth_order_to_db = lambda order: True
    manager._update_stealth_order = lambda order: False
    parent_statuses = []
    monkeypatch.setattr(
        "core.stealth_order_manager.insert_order_parent",
        lambda **kwargs: 1,
    )
    monkeypatch.setattr(
        "core.stealth_order_manager.update_order_parent_status",
        lambda client_order_id, status: parent_statuses.append(
            (client_order_id, status)
        ),
    )

    with pytest.raises(OrderCreationError, match="activation persistence failed"):
        manager.create_stealth_order(
            product_id=five_tick_product,
            side="BUY",
            total_size=5.0,
            limit_price=77119.0,
            reveal_condition={"type": "time_delay", "delay_seconds": 0},
            stealth_order_id=stealth_order_id,
        )

    assert stealth_order_id not in manager.in_memory_orders
    assert parent_statuses == [(stealth_order_id, OrderStatus.FAILED.value)]


@pytest.mark.regression
def test_duplicate_creation_does_not_terminalize_existing_parent(
    five_tick_product,
    monkeypatch,
):
    stealth_order_id = "dddddddd-eeee-4fff-8aaa-bbbbbbbbbbbb"
    manager = StealthOrderManager(db_client=None)
    manager._save_stealth_order_to_db = lambda order: True
    persisted_statuses = []
    manager._update_stealth_order = lambda order: persisted_statuses.append(
        order["status"]
    ) or True
    parent_statuses = []

    def duplicate_parent(**kwargs):
        assert kwargs["reject_existing"] is True
        raise RuntimeError("client_order_id already exists")

    monkeypatch.setattr(
        "core.stealth_order_manager.insert_order_parent",
        duplicate_parent,
    )
    monkeypatch.setattr(
        "core.stealth_order_manager.update_order_parent_status",
        lambda client_order_id, status: parent_statuses.append(
            (client_order_id, status)
        ),
    )

    with pytest.raises(OrderCreationError, match="already exists"):
        manager.create_stealth_order(
            product_id=five_tick_product,
            side="BUY",
            total_size=5.0,
            limit_price=77119.0,
            reveal_condition={"type": "time_delay", "delay_seconds": 0},
            stealth_order_id=stealth_order_id,
        )

    assert stealth_order_id not in manager.in_memory_orders
    assert persisted_statuses == [StealthOrderStatus.ERROR.value]
    assert parent_statuses == []


@pytest.mark.regression
@pytest.mark.parametrize(
    "response_or_exception",
    (
        {"success": False, "failure_reason": "INVALID_PRICE_INCREMENT"},
        {"success": True, "success_response": {}},
        {
            "success": True,
            "success_response": {
                "order_id": "exchange-id",
                "client_order_id": "wrong-client-id",
            },
        },
        TimeoutError("response lost"),
    ),
)
def test_unaccepted_reveal_becomes_error_without_success_side_effects(
    five_tick_product,
    monkeypatch,
    response_or_exception,
):
    manager, sid, order, post_calls, lifecycle, parent_statuses = (
        _manager_for_reveal(
            five_tick_product,
            response_or_exception,
            monkeypatch,
        )
    )

    result = manager.reveal_order_slice(sid)

    assert result is None
    assert order["status"] == StealthOrderStatus.ERROR.value
    assert order["revealed_size"] == 0.0
    assert order["remaining_size"] == 5.0
    assert order["revealed_orders"][-1]["revealed_size"] == 0.0
    assert order["revealed_orders"][-1]["placement_success"] is False
    assert sid not in manager._placed_order_index
    assert post_calls == []
    assert parent_statuses[-1] == (sid, OrderStatus.FAILED.value)
    assert lifecycle[-1][0] is StealthLifecycleEvent.REVEAL_FAILED
    assert sid not in manager._get_active_stealth_orders()
    should_reveal, reason = manager.should_trigger_reveal(sid)
    assert should_reveal is False
    assert StealthOrderStatus.ERROR.value in reason


@pytest.mark.regression
def test_explicit_acceptance_consumes_size_and_indexes_order(
    five_tick_product,
    monkeypatch,
):
    def accepted(kwargs):
        return {
            "success": True,
            "success_response": {
                "order_id": "exchange-id",
                "client_order_id": kwargs["client_order_id"],
            },
        }

    manager, sid, order, post_calls, lifecycle, parent_statuses = (
        _manager_for_reveal(five_tick_product, accepted, monkeypatch)
    )

    result = manager.reveal_order_slice(sid)

    assert result == sid
    assert order["status"] == StealthOrderStatus.REVEALED.value
    assert order["revealed_size"] == 5.0
    assert order["remaining_size"] == 0.0
    assert order["revealed_orders"][-1]["placement_success"] is True
    assert order["revealed_orders"][-1]["exchange_order_id"] == "exchange-id"
    assert manager._placed_order_index[sid] is order
    assert len(post_calls) == 1
    assert parent_statuses == []
    assert lifecycle[-1][0] is StealthLifecycleEvent.REVEAL_SUCCEEDED
    assert lifecycle[-1][2] == StealthOrderStatus.REVEALED.value


@pytest.mark.regression
def test_post_only_ladder_uses_one_flat_child_row_per_attempt(
    five_tick_product,
    monkeypatch,
):
    attempts = []

    def reject_then_accept(kwargs):
        attempts.append(dict(kwargs))
        if len(attempts) == 1:
            return {
                "success": False,
                "failure_reason": "POST_ONLY",
            }
        return {
            "success": True,
            "success_response": {
                "order_id": "exchange-retry-id",
                "client_order_id": kwargs["client_order_id"],
            },
        }

    manager, sid, order, post_calls, lifecycle, parent_statuses = (
        _manager_for_reveal(
            five_tick_product,
            reject_then_accept,
            monkeypatch,
        )
    )
    order["reveal_pricing_policy"] = "top_of_book"
    parent_rows = []

    def insert_parent(**kwargs):
        parent_rows.append(dict(kwargs))
        return len(parent_rows)

    monkeypatch.setattr(
        "core.stealth_order_manager.insert_order_parent",
        insert_parent,
    )

    result = manager.reveal_order_slice(sid)

    attempt_ids = [attempt["client_order_id"] for attempt in attempts]
    assert len(attempt_ids) == 2
    assert len(set(attempt_ids)) == 2
    assert sid not in attempt_ids
    assert result == attempt_ids[-1]
    assert [row["client_order_id"] for row in parent_rows] == attempt_ids
    assert all(row["parent_order_id"] == sid for row in parent_rows)
    assert parent_statuses == [(attempt_ids[0], OrderStatus.FAILED.value)]
    assert manager._placed_order_index[attempt_ids[-1]] is order
    assert len(post_calls) == 1
    assert lifecycle[-1][0] is StealthLifecycleEvent.REVEAL_SUCCEEDED


@pytest.mark.regression
def test_post_only_retry_price_is_revalidated_before_parent_or_rest_write(
    five_tick_product,
    monkeypatch,
):
    attempts = []

    def reject_post_only(kwargs):
        attempts.append(dict(kwargs))
        return {
            "success": False,
            "failure_reason": "POST_ONLY",
        }

    manager, sid, order, post_calls, lifecycle, parent_statuses = (
        _manager_for_reveal(
            five_tick_product,
            reject_post_only,
            monkeypatch,
        )
    )
    order["reveal_pricing_policy"] = "top_of_book"
    manager._resolve_target_movement_for_plan = lambda *args, **kwargs: (
        0.001,
        "P",
        "test",
    )
    validation_calls = []

    def validate_order_profitability(**kwargs):
        validation_calls.append(dict(kwargs))
        return {
            "is_profitable": kwargs["parent_filled_price"] == 77115.0,
            "net_profit": 1.0 if kwargs["parent_filled_price"] == 77115.0 else -1.0,
            "gross_profit": 1.0,
            "total_fees": 0.0,
            "percentage_fees": 0.0,
            "mandatory_fees": 0.0,
        }

    manager.profit_validator = SimpleNamespace(
        derive_follow_up_price_from_target=lambda **_kwargs: 77200.0,
        validate_order_profitability=validate_order_profitability,
    )
    parent_rows = []
    monkeypatch.setattr(
        "core.stealth_order_manager.insert_order_parent",
        lambda **kwargs: parent_rows.append(dict(kwargs)) or len(parent_rows),
    )

    result = manager.reveal_order_slice(sid)

    assert result is None
    assert [call["parent_filled_price"] for call in validation_calls] == [
        77115.0,
        77110.0,
    ]
    assert [call["post_only"] for call in validation_calls] == [True, True]
    assert len(parent_rows) == 1
    assert parent_rows[0]["price"] == 77115.0
    assert len(attempts) == 1
    assert attempts[0]["limit_price"] == "77115.0"
    assert parent_statuses
    assert all(
        status_update
        == (attempts[0]["client_order_id"], OrderStatus.FAILED.value)
        for status_update in parent_statuses
    )
    assert order["status"] == StealthOrderStatus.ERROR.value
    assert order["revealed_size"] == 0.0
    assert post_calls == []
    assert lifecycle[-1][0] is StealthLifecycleEvent.REVEAL_FAILED
    assert "post-only retry blocked by profitability" in (
        lifecycle[-1][1]["failure_reason"]
    )


@pytest.mark.regression
def test_pre_submission_hook_can_enable_post_only_before_rest(
    five_tick_product,
    monkeypatch,
):
    attempts = []

    def accepted(kwargs):
        attempts.append(dict(kwargs))
        return {
            "success": True,
            "success_response": {
                "order_id": "exchange-id",
                "client_order_id": kwargs["client_order_id"],
            },
        }

    manager, sid, _, _, _, _ = _manager_for_reveal(
        five_tick_product,
        accepted,
        monkeypatch,
    )
    manager.order_placement_hooks.call_pre_submission_hooks = (
        lambda payload: payload.__setitem__("post_only", True)
    )
    monkeypatch.setattr(
        "core.stealth_order_manager.insert_order_parent",
        lambda **kwargs: 1,
    )

    result = manager.reveal_order_slice(sid)

    assert len(attempts) == 1
    assert attempts[0]["post_only"] is True
    assert attempts[0]["client_order_id"] != sid
    assert result == attempts[0]["client_order_id"]


@pytest.mark.regression
def test_pre_submission_hook_can_disable_post_only_before_rest(
    five_tick_product,
    monkeypatch,
):
    attempts = []

    def accepted(kwargs):
        attempts.append(dict(kwargs))
        return {
            "success": True,
            "success_response": {
                "order_id": "exchange-id",
                "client_order_id": kwargs["client_order_id"],
            },
        }

    manager, sid, order, _, _, _ = _manager_for_reveal(
        five_tick_product,
        accepted,
        monkeypatch,
    )
    order["reveal_pricing_policy"] = "top_of_book"
    manager.order_placement_hooks.call_pre_submission_hooks = (
        lambda payload: payload.__setitem__("post_only", False)
    )

    result = manager.reveal_order_slice(sid)

    assert len(attempts) == 1
    assert attempts[0]["post_only"] is False
    assert attempts[0]["client_order_id"] == sid
    assert result == sid


@pytest.mark.regression
def test_hook_post_only_mutation_is_revalidated_before_local_or_rest_write(
    five_tick_product,
    monkeypatch,
):
    manager, sid, order, post_calls, lifecycle, parent_statuses = (
        _manager_for_reveal(
            five_tick_product,
            lambda _kwargs: pytest.fail(
                "REST must not run when final taker economics are unprofitable"
            ),
            monkeypatch,
        )
    )
    order["reveal_pricing_policy"] = "top_of_book"
    manager._resolve_target_movement_for_plan = lambda *args, **kwargs: (
        0.001,
        "P",
        "test",
    )
    validation_calls = []

    def validate_order_profitability(**kwargs):
        validation_calls.append(dict(kwargs))
        is_profitable = bool(kwargs["post_only"])
        return {
            "is_profitable": is_profitable,
            "net_profit": 1.0 if is_profitable else -1.0,
            "gross_profit": 1.0,
            "total_fees": 0.0,
            "percentage_fees": 0.0,
            "mandatory_fees": 0.0,
        }

    manager.profit_validator = SimpleNamespace(
        derive_follow_up_price_from_target=lambda **_kwargs: 77200.0,
        validate_order_profitability=validate_order_profitability,
    )
    manager.order_placement_hooks.call_pre_submission_hooks = (
        lambda payload: payload.__setitem__("post_only", False)
    )
    monkeypatch.setattr(
        "core.stealth_order_manager.update_order_parent_price",
        lambda *_args, **_kwargs: pytest.fail(
            "order_parent must not be written before final profitability passes"
        ),
    )
    monkeypatch.setattr(
        "core.stealth_order_manager.insert_order_parent",
        lambda **_kwargs: pytest.fail(
            "order_parent must not be inserted before final profitability passes"
        ),
    )

    result = manager.reveal_order_slice(sid)

    assert result is None
    assert [call["post_only"] for call in validation_calls] == [True, False]
    assert order["status"] == StealthOrderStatus.TRIGGERED.value
    assert order["revealed_size"] == 0.0
    assert post_calls == []
    assert parent_statuses == []
    assert lifecycle[-1][0] is StealthLifecycleEvent.PLACEMENT_BLOCKED
    assert lifecycle[-1][1]["validation_stage"] == "post_hook"


@pytest.mark.regression
def test_hook_price_mutation_revalidates_final_normalized_price(
    five_tick_product,
    monkeypatch,
):
    attempts = []

    def accepted(kwargs):
        attempts.append(dict(kwargs))
        return {
            "success": True,
            "success_response": {
                "order_id": "exchange-id",
                "client_order_id": kwargs["client_order_id"],
            },
        }

    manager, sid, _, _, _, _ = _manager_for_reveal(
        five_tick_product,
        accepted,
        monkeypatch,
    )
    manager._resolve_target_movement_for_plan = lambda *args, **kwargs: (
        0.001,
        "P",
        "test",
    )
    validation_calls = []

    def validate_order_profitability(**kwargs):
        validation_calls.append(dict(kwargs))
        return {"is_profitable": True}

    manager.profit_validator = SimpleNamespace(
        derive_follow_up_price_from_target=lambda **_kwargs: 77200.0,
        validate_order_profitability=validate_order_profitability,
    )
    manager.order_placement_hooks.call_pre_submission_hooks = (
        lambda payload: payload.__setitem__("limit_price", 77114.0)
    )

    assert manager.reveal_order_slice(sid) == sid

    assert [
        call["parent_filled_price"] for call in validation_calls
    ] == [77115.0, 77110.0]
    assert [call["post_only"] for call in validation_calls] == [False, False]
    assert attempts[0]["limit_price"] == "77110.0"


@pytest.mark.regression
def test_invalid_hook_price_is_retriable_pre_rest_block(
    five_tick_product,
    monkeypatch,
):
    manager, sid, order, post_calls, lifecycle, parent_statuses = (
        _manager_for_reveal(
            five_tick_product,
            lambda kwargs: pytest.fail("REST must not run for invalid hook price"),
            monkeypatch,
        )
    )
    manager.order_placement_hooks.call_pre_submission_hooks = (
        lambda payload: payload.__setitem__("limit_price", "not-a-price")
    )

    result = manager.reveal_order_slice(sid)

    assert result is None
    assert order["status"] == StealthOrderStatus.TRIGGERED.value
    assert order["revealed_size"] == 0.0
    assert order["remaining_size"] == 5.0
    assert post_calls == []
    assert parent_statuses == []
    assert lifecycle[-1][0] is StealthLifecycleEvent.PLACEMENT_BLOCKED
    assert lifecycle[-1][1]["block_category"] == "invalid_submission_price"


@pytest.mark.regression
def test_hook_modified_price_uses_one_canonical_value_for_db_rest_and_state(
    five_tick_product,
    monkeypatch,
):
    submitted = {}

    def accepted(kwargs):
        submitted.update(kwargs)
        return {
            "success": True,
            "success_response": {
                "order_id": "exchange-id",
                "client_order_id": kwargs["client_order_id"],
            },
        }

    manager, sid, order, _, _, _ = _manager_for_reveal(
        five_tick_product,
        accepted,
        monkeypatch,
    )
    manager.order_placement_hooks.call_pre_submission_hooks = (
        lambda payload: payload.__setitem__("limit_price", 77114.0)
    )
    parent_price_updates = []
    monkeypatch.setattr(
        "core.stealth_order_manager.update_order_parent_price",
        lambda client_order_id, price: parent_price_updates.append(
            (client_order_id, price)
        ) or True,
    )

    assert manager.reveal_order_slice(sid) == sid

    assert parent_price_updates == [(sid, 77110.0)]
    assert submitted["limit_price"] == "77110.0"
    assert order["revealed_orders"][-1]["placement_price"] == 77110.0
    assert order["anchor_repricing_state_json"]["active_exchange_price"] == 77110.0


@pytest.mark.regression
def test_post_hook_failure_does_not_downgrade_accepted_order(
    five_tick_product,
    monkeypatch,
):
    def accepted(kwargs):
        return {
            "success": True,
            "success_response": {
                "order_id": "exchange-id",
                "client_order_id": kwargs["client_order_id"],
            },
        }

    manager, sid, order, _, lifecycle, _ = _manager_for_reveal(
        five_tick_product,
        accepted,
        monkeypatch,
    )
    manager.order_placement_hooks.call_post_submission_hooks = (
        lambda payload, response: (_ for _ in ()).throw(RuntimeError("audit down"))
    )

    result = manager.reveal_order_slice(sid)

    assert result == sid
    assert order["status"] == StealthOrderStatus.REVEALED.value
    assert order["revealed_size"] == 5.0
    event = order["revealed_orders"][-1]
    assert event["placement_success"] is True
    assert "reveal.post_submission_hook: audit down" in event["placement_error"]
    assert lifecycle[-1][0] is StealthLifecycleEvent.REVEAL_SUCCEEDED


@pytest.mark.regression
def test_real_post_hook_registry_surfaces_errors_without_stopping_later_hooks(
    five_tick_product,
    monkeypatch,
):
    from integration.order_placement_hooks import OrderPlacementHookRegistry

    def accepted(kwargs):
        return {
            "success": True,
            "success_response": {
                "order_id": "exchange-id",
                "client_order_id": kwargs["client_order_id"],
            },
        }

    manager, sid, order, _, lifecycle, _ = _manager_for_reveal(
        five_tick_product,
        accepted,
        monkeypatch,
    )
    registry = OrderPlacementHookRegistry()
    later_hook_calls = []
    registry.register_post_submission(
        lambda payload, response: (_ for _ in ()).throw(
            RuntimeError("event publisher down")
        )
    )
    registry.register_post_submission(
        lambda payload, response: later_hook_calls.append(payload["client_order_id"])
    )
    manager.order_placement_hooks = registry

    result = manager.reveal_order_slice(sid)

    assert result == sid
    assert later_hook_calls == [sid]
    assert order["status"] == StealthOrderStatus.REVEALED.value
    assert order["revealed_orders"][-1]["placement_success"] is True
    assert "event publisher down" in order["revealed_orders"][-1]["placement_error"]
    assert lifecycle[-1][0] is StealthLifecycleEvent.REVEAL_SUCCEEDED


@pytest.mark.regression
def test_local_persistence_failure_does_not_downgrade_or_unindex_acceptance(
    five_tick_product,
    monkeypatch,
):
    def accepted(kwargs):
        return {
            "success": True,
            "success_response": {
                "order_id": "exchange-id",
                "client_order_id": kwargs["client_order_id"],
            },
        }

    manager, sid, order, _, lifecycle, _ = _manager_for_reveal(
        five_tick_product,
        accepted,
        monkeypatch,
    )
    logs = []
    manager.log_callback = lambda level, payload: logs.append((level, payload))
    manager._update_stealth_order = lambda _order: False
    manager._record_reveal_event = lambda _order, _event: False

    result = manager.reveal_order_slice(sid)

    assert result == sid
    assert order["status"] == StealthOrderStatus.REVEALED.value
    assert order["revealed_size"] == 5.0
    assert manager._placed_order_index[sid] is order
    assert order["revealed_orders"][-1]["placement_success"] is True
    assert "persist_reveal_event" in order["revealed_orders"][-1][
        "local_finalization_error"
    ]
    assert sum(
        payload.get("event") == "stealth_order_slice_local_finalization_error"
        for _, payload in logs
        if isinstance(payload, dict)
    ) == 2
    assert lifecycle[-1][0] is StealthLifecycleEvent.REVEAL_SUCCEEDED


class _ReadOnlyDB:
    def __init__(self, rows):
        self.rows = rows
        self.updates = []

    def execute_query(self, query, params=None):
        return list(self.rows)

    def execute_update(self, query, params=None):
        self.updates.append((query, params))
        return 1


def _stored_row(
    product_id: str,
    *,
    price=77119.0,
    status="HIDDEN",
    failure_reason=None,
):
    return {
        "stealth_order_id": "stored-sid",
        "product_id": product_id,
        "side": "BUY",
        "total_size": 5.0,
        "revealed_size": 0.0,
        "remaining_size": 5.0,
        "executed_size": 0.0,
        "limit_price": price,
        "status": status,
        "failure_reason": failure_reason,
        "reveal_condition_type": "time_delay",
        "reveal_condition_json": {},
        "sizing_strategy_json": {"type": "fixed"},
        "revealed_orders": [],
        "anchor_repricing_policy_json": {},
        "anchor_repricing_state_json": {},
    }


@pytest.mark.regression
def test_reveal_pricing_policy_schema_migration_is_additive(monkeypatch):
    from database import order as order_db

    cursor = MagicMock()
    db_client = MagicMock()
    db_client.get_cursor.return_value.__enter__.return_value = cursor
    monkeypatch.setattr(order_db, "DB_CLIENT", db_client)

    order_db.create_stealth_orders_table()

    statements = [call.args[0] for call in cursor.execute.call_args_list]
    assert any(
        "reveal_pricing_policy VARCHAR(32) NOT NULL DEFAULT 'configured_limit'"
        in statement
        for statement in statements
    )
    assert any(
        "ALTER TABLE stealth_orders ADD COLUMN IF NOT EXISTS reveal_pricing_policy"
        in statement
        for statement in statements
    )


@pytest.mark.regression
def test_reveal_pricing_policy_write_paths_normalize_and_preserve_absence(
    five_tick_product,
):
    db = _ReadOnlyDB([])
    manager = StealthOrderManager(db_client=None)
    manager.db_client = db
    _, order = _triggered_order(five_tick_product)
    order["reveal_pricing_policy"] = " TOP_OF_BOOK "

    assert manager._save_stealth_order_to_db(order) is True
    insert_query, insert_params = db.updates[-1]
    assert "reveal_pricing_policy" in insert_query
    assert RevealPricingPolicy.TOP_OF_BOOK.value in insert_params

    assert manager._update_stealth_order(order) is True
    update_query, update_params = db.updates[-1]
    assert (
        "reveal_pricing_policy = CASE WHEN %s THEN %s "
        "ELSE reveal_pricing_policy END"
        in update_query
    )
    assert update_params[9] is True
    assert update_params[10] == RevealPricingPolicy.TOP_OF_BOOK.value

    order_without_policy = dict(order)
    order_without_policy.pop("reveal_pricing_policy")
    assert manager._update_stealth_order(order_without_policy) is True
    _, absent_params = db.updates[-1]
    assert absent_params[9] is False
    assert absent_params[10] is None


@pytest.mark.regression
@pytest.mark.parametrize("load_mode", ("startup", "lazy"))
def test_hydration_restores_reveal_pricing_policy_and_post_only(
    five_tick_product,
    load_mode,
):
    row = _stored_row(five_tick_product, price=77115.0)
    row["reveal_pricing_policy"] = RevealPricingPolicy.TOP_OF_BOOK.value
    db = _ReadOnlyDB([row])
    manager = StealthOrderManager(db_client=None)
    manager.db_client = db
    manager._get_current_market_data = lambda _product_id: {
        "price": 77110.0,
        "bid": 77110.0,
        "ask": 77115.0,
        "source": "ticker",
    }
    manager._resolve_target_movement_for_plan = lambda *_args, **_kwargs: (
        None,
        None,
        "test",
    )

    if load_mode == "startup":
        assert manager.load_all_active_orders_from_db() == 1
    else:
        assert manager._get_stealth_order("stored-sid") is not None

    hydrated = manager.in_memory_orders["stored-sid"]
    plan = manager.build_reveal_execution_plan("stored-sid")
    assert hydrated["reveal_pricing_policy"] == RevealPricingPolicy.TOP_OF_BOOK.value
    assert plan is not None
    assert plan.reveal_pricing_policy == RevealPricingPolicy.TOP_OF_BOOK.value
    assert plan.post_only is True


@pytest.mark.regression
def test_hydration_missing_reveal_pricing_policy_fails_safe(
    five_tick_product,
):
    row = _stored_row(five_tick_product, price=77115.0)
    db = _ReadOnlyDB([row])
    manager = StealthOrderManager(db_client=None)
    manager.db_client = db

    assert manager.load_all_active_orders_from_db() == 1
    assert (
        manager.in_memory_orders["stored-sid"]["reveal_pricing_policy"]
        == RevealPricingPolicy.CONFIGURED_LIMIT.value
    )


@pytest.mark.regression
def test_hydration_flags_off_grid_price_without_database_write(five_tick_product):
    db = _ReadOnlyDB([_stored_row(five_tick_product)])
    manager = StealthOrderManager(db_client=None)
    manager.db_client = db

    assert manager.load_all_active_orders_from_db() == 1

    loaded = manager.in_memory_orders["stored-sid"]
    assert loaded["limit_price"] == 77119.0
    assert loaded["status"] == StealthOrderStatus.ERROR.value
    assert "Database row was not modified" in loaded["failure_reason"]
    assert db.updates == []


@pytest.mark.regression
def test_hydration_preserves_persisted_error(five_tick_product):
    db = _ReadOnlyDB([
        _stored_row(
            five_tick_product,
            price=77115.0,
            status=StealthOrderStatus.ERROR.value,
            failure_reason="INVALID_PRICE_INCREMENT",
        )
    ])
    manager = StealthOrderManager(db_client=None)
    manager.db_client = db

    manager.load_all_active_orders_from_db()

    assert (
        manager.in_memory_orders["stored-sid"]["status"]
        == StealthOrderStatus.ERROR.value
    )
    assert (
        manager.in_memory_orders["stored-sid"]["failure_reason"]
        == "INVALID_PRICE_INCREMENT"
    )
    assert db.updates == []


@pytest.mark.regression
def test_hydration_restores_only_explicitly_accepted_placement_ownership(
    five_tick_product,
):
    row = _stored_row(
        five_tick_product,
        price=77115.0,
        status=StealthOrderStatus.REVEALED.value,
    )
    row["remaining_size"] = 0.0
    row["revealed_size"] = 5.0
    row["revealed_orders"] = [
        {
            "placement_success": False,
            "placed_order_id": "failed-placement",
            "exchange_order_id": None,
        },
        {
            "placement_success": True,
            "placement_client_order_id": "accepted-placement",
            "placed_order_id": "accepted-placement",
            "exchange_order_id": "exchange-id",
        },
        {
            "placement_success": True,
            "placement_client_order_id": "missing-exchange-proof",
            "placed_order_id": "missing-exchange-proof",
            "exchange_order_id": None,
        },
    ]
    db = _ReadOnlyDB([row])
    manager = StealthOrderManager(db_client=None)
    manager.db_client = db

    manager.load_all_active_orders_from_db()

    loaded = manager.in_memory_orders["stored-sid"]
    assert (
        manager.find_stealth_order_by_placed_order_id("accepted-placement")
        is loaded
    )
    assert manager.find_stealth_order_by_placed_order_id("failed-placement") is None
    assert (
        manager.find_stealth_order_by_placed_order_id("missing-exchange-proof")
        is None
    )
    assert db.updates == []


@pytest.mark.regression
@pytest.mark.parametrize(
    "status",
    (
        StealthOrderStatus.REVEALED.value,
        StealthOrderStatus.EXECUTED.value,
        StealthOrderStatus.CANCELLED.value,
    ),
)
def test_hydration_does_not_erase_live_or_terminal_truth_for_off_grid_history(
    five_tick_product,
    status,
):
    db = _ReadOnlyDB([
        _stored_row(five_tick_product, price=77119.0, status=status)
    ])
    manager = StealthOrderManager(db_client=None)
    manager.db_client = db

    manager.load_all_active_orders_from_db()

    loaded = manager.in_memory_orders["stored-sid"]
    assert loaded["status"] == status
    assert "off the" in loaded["price_validation_error"]
    assert db.updates == []


@pytest.mark.regression
def test_hydration_defers_when_metadata_is_unavailable_without_claiming_invalidity():
    product_id = "METADATA-NOT-LOADED"
    db = _ReadOnlyDB([_stored_row(product_id, price=101.0)])
    manager = StealthOrderManager(db_client=None)
    manager.db_client = db

    manager.load_all_active_orders_from_db()

    loaded = manager.in_memory_orders["stored-sid"]
    assert loaded["status"] == StealthOrderStatus.HIDDEN.value
    assert loaded["_price_validation_pending"] is True
    should_reveal, reason = manager.should_trigger_reveal("stored-sid")
    assert should_reveal is False
    assert "metadata is unavailable" in reason
    assert db.updates == []


@pytest.mark.regression
def test_persistence_boundary_rejects_off_grid_without_correction(
    five_tick_product,
):
    db = _ReadOnlyDB([])
    manager = StealthOrderManager(db_client=None)
    manager.db_client = db
    _, order = _triggered_order(five_tick_product)
    order["limit_price"] = 77119.0

    with pytest.raises(StealthOrderPersistenceError, match="Refusing"):
        manager._update_stealth_order(order)

    assert order["limit_price"] == 77119.0
    assert db.updates == []


@pytest.mark.regression
def test_terminal_failure_reason_uses_primary_stealth_order_persistence(
    five_tick_product,
):
    db = _ReadOnlyDB([])
    manager = StealthOrderManager(db_client=None)
    manager.db_client = db
    _, order = _triggered_order(five_tick_product)
    order["status"] = StealthOrderStatus.ERROR.value
    order["failure_reason"] = "INVALID_PRICE_INCREMENT"

    assert manager._update_stealth_order(order) is True

    query, params = db.updates[-1]
    assert (
        "failure_reason = CASE WHEN %s THEN %s ELSE failure_reason END"
        in query
    )
    assert "INVALID_PRICE_INCREMENT" in params


@pytest.mark.regression
def test_accepted_reveal_clears_stale_retriable_failure_reason(
    five_tick_product,
    monkeypatch,
):
    def accepted(kwargs):
        return {
            "success": True,
            "success_response": {
                "order_id": "exchange-id",
                "client_order_id": kwargs["client_order_id"],
            },
        }

    manager, sid, order, _, _, _ = _manager_for_reveal(
        five_tick_product,
        accepted,
        monkeypatch,
    )
    order["failure_reason"] = "temporary placement block"

    assert manager.reveal_order_slice(sid) == sid
    assert order["failure_reason"] is None


@pytest.mark.regression
def test_non_price_lifecycle_update_does_not_rewrite_price_when_metadata_drops(
    five_tick_product,
    monkeypatch,
):
    from configuration import PRODUCT_METADATA

    db = _ReadOnlyDB([])
    manager = StealthOrderManager(db_client=None)
    manager.db_client = db
    _, order = _triggered_order(five_tick_product)
    order["_persisted_limit_price"] = order["limit_price"]
    order["status"] = StealthOrderStatus.EXECUTED.value
    monkeypatch.delitem(PRODUCT_METADATA, five_tick_product)

    assert manager._update_stealth_order(order) is True

    query, params = db.updates[-1]
    assert "limit_price = CASE WHEN %s THEN %s ELSE limit_price END" in query
    assert params[6] is False
    assert params[7] == 77115.0
    assert order["limit_price"] == 77115.0
