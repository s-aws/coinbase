"""Regression tests for spot follow-up intent classification."""

from unittest.mock import MagicMock

import pytest

from core.enums import (
    OrderSide,
    SpotFollowUpIntent,
    SpotFollowUpTrigger,
)
from core.spot_follow_up_policy import evaluate_spot_follow_up_policy
from core.stealth_order_manager import (
    StealthOrderManager,
    _filled_follow_up_stealth_order_id,
)


pytestmark = pytest.mark.regression


def _manager_with_original(*, side=OrderSide.SELL.value, product_id="BTC-USD"):
    manager = StealthOrderManager(db_client=None, log_callback=MagicMock())
    original_id = "original-spot-follow-up"
    manager.in_memory_orders[original_id] = {
        "stealth_order_id": original_id,
        "product_id": product_id,
        "side": side,
        "total_size": 0.01,
        "remaining_size": 0.0,
        "revealed_size": 0.01,
        "executed_size": 0.01,
        "limit_price": 100000.0,
        "reveal_condition_json": {"type": "time_delay", "delay_seconds": 0},
        "sizing_strategy_json": {"type": "fixed"},
        "reveal_pricing_policy": "configured_limit",
        "follow_up_reveal_direction": "opposite",
        "parent_order_id": "root-parent",
    }
    return manager, original_id


def test_spot_buy_fill_to_sell_follow_up_is_exit_by_default():
    decision = evaluate_spot_follow_up_policy(
        product_id="BTC-USD",
        source_side=OrderSide.BUY.value,
        follow_up_side=OrderSide.SELL.value,
        trigger=SpotFollowUpTrigger.FILLED,
    )

    assert decision.allowed is True
    assert decision.intent == SpotFollowUpIntent.EXIT.value


def test_spot_sell_fill_to_buy_follow_up_is_rebuy_blocked_by_default():
    decision = evaluate_spot_follow_up_policy(
        product_id="BTC-USD",
        source_side=OrderSide.SELL.value,
        follow_up_side=OrderSide.BUY.value,
        trigger=SpotFollowUpTrigger.FILLED,
    )

    assert decision.allowed is False
    assert decision.intent == SpotFollowUpIntent.REBUY.value
    assert "not enabled" in decision.reason


def test_spot_rebuy_can_be_enabled_by_explicit_policy():
    decision = evaluate_spot_follow_up_policy(
        product_id="BTC-USD",
        source_side=OrderSide.SELL.value,
        follow_up_side=OrderSide.BUY.value,
        trigger=SpotFollowUpTrigger.FILLED,
        policy={"allow_rebuy": True},
    )

    assert decision.allowed is True
    assert decision.intent == SpotFollowUpIntent.REBUY.value


def test_spot_same_side_replacement_is_blocked_without_policy():
    decision = evaluate_spot_follow_up_policy(
        product_id="BTC-USD",
        source_side=OrderSide.BUY.value,
        follow_up_side=OrderSide.BUY.value,
        trigger=SpotFollowUpTrigger.CANCELLED,
    )

    assert decision.allowed is False
    assert decision.intent == SpotFollowUpIntent.SAME_SIDE_REPLACEMENT.value


def test_futures_follow_up_policy_does_not_change_existing_behavior():
    decision = evaluate_spot_follow_up_policy(
        product_id="BIP-20DEC30-CDE",
        source_side=OrderSide.SELL.value,
        follow_up_side=OrderSide.BUY.value,
        trigger=SpotFollowUpTrigger.FILLED,
    )

    assert decision.allowed is True
    assert decision.product_type == "FUTURE"


def test_stealth_manager_blocks_unsupported_spot_follow_up_before_creation():
    manager, original_id = _manager_with_original(side=OrderSide.SELL.value)
    manager.create_stealth_order = MagicMock(return_value="should-not-create")

    follow_up_id = manager.create_follow_up_stealth_order(
        original_stealth_order_id=original_id,
        side=OrderSide.BUY.value,
        total_size=0.01,
        limit_price=99000.0,
        follow_up_trigger=SpotFollowUpTrigger.FILLED.value,
    )

    assert follow_up_id is None
    manager.create_stealth_order.assert_not_called()
    manager.log_callback.assert_called()
    payload = manager.log_callback.call_args.args[1]
    assert payload["event"] == "spot_follow_up_blocked"
    assert payload["intent"] == SpotFollowUpIntent.REBUY.value


def test_stealth_manager_allows_spot_exit_follow_up_to_existing_path():
    manager, original_id = _manager_with_original(side=OrderSide.BUY.value)
    manager.create_stealth_order = MagicMock(return_value="new-exit-follow-up")
    source_client_order_id = "placed-fill-1"

    follow_up_id = manager.create_follow_up_stealth_order(
        original_stealth_order_id=original_id,
        side=OrderSide.SELL.value,
        total_size=0.01,
        limit_price=101000.0,
        follow_up_trigger=SpotFollowUpTrigger.FILLED.value,
        source_client_order_id=source_client_order_id,
    )

    assert follow_up_id == "new-exit-follow-up"
    manager.create_stealth_order.assert_called_once()
    assert (
        manager.create_stealth_order.call_args.kwargs["require_persistence"]
        is True
    )
    assert manager.create_stealth_order.call_args.kwargs["stealth_order_id"] == (
        _filled_follow_up_stealth_order_id(
            original_stealth_order_id=original_id,
            source_client_order_id=source_client_order_id,
        )
    )
