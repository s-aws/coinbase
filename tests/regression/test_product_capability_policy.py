"""Regression tests for product capability policy gates."""

from unittest.mock import MagicMock

import pytest

from business.hotpoint_detector import HotpointTriggerEvent
from business.hotpoint_placer import (
    STATUS_PRODUCT_CAPABILITY_BLOCKED,
    place_hotpoint_order,
)
from business.hotpoint_rate_limiter import HotpointRateLimiter
from core.enums import (
    HotpointPlacementPolicy,
    ProductCapability,
    ProductCapabilityMode,
)
from core.exceptions import OrderCreationError, StealthMoveError
from core.product_capability import evaluate_product_capability
from core.stealth_order_manager import StealthOrderManager


pytestmark = pytest.mark.regression


def _manager():
    manager = StealthOrderManager(db_client=None, log_callback=MagicMock())
    manager._save_stealth_order_to_db = MagicMock()
    manager._update_stealth_order = MagicMock()
    return manager


def test_spot_capability_defaults_are_conservative():
    direct = evaluate_product_capability(
        product_id="BTC-USD",
        capability=ProductCapability.DIRECT_PLACEMENT,
    )
    move = evaluate_product_capability(
        product_id="BTC-USD",
        capability=ProductCapability.MOVE_REVEALED,
    )
    follow_up = evaluate_product_capability(
        product_id="BTC-USD",
        capability=ProductCapability.FILLED_FOLLOW_UP,
    )
    conditional_follow_up = evaluate_product_capability(
        product_id="BTC-USD",
        capability=ProductCapability.FILLED_FOLLOW_UP,
        allow_conditional=True,
    )

    assert direct.allowed is True
    assert move.allowed is False
    assert move.mode == ProductCapabilityMode.DISABLED.value
    assert follow_up.allowed is False
    assert follow_up.mode == ProductCapabilityMode.CONDITIONAL.value
    assert conditional_follow_up.allowed is True


def test_futures_capability_defaults_remain_enabled():
    move = evaluate_product_capability(
        product_id="BIP-20DEC30-CDE",
        capability=ProductCapability.MOVE_REVEALED,
    )
    hotpoint = evaluate_product_capability(
        product_id="BIP-20DEC30-CDE",
        capability=ProductCapability.HOTPOINT_AUTO_PLACEMENT,
    )

    assert move.allowed is True
    assert hotpoint.allowed is True


def test_product_capability_override_can_enable_spot_specific_action():
    decision = evaluate_product_capability(
        product_id="BTC-USD",
        capability=ProductCapability.MOVE_REVEALED,
        policy={
            "product_type": {
                "SPOT": {
                    ProductCapability.MOVE_REVEALED.value: (
                        ProductCapabilityMode.ENABLED.value
                    ),
                }
            }
        },
    )

    assert decision.allowed is True


def test_spot_cancel_reentry_policy_rejected_before_persistence(monkeypatch):
    manager = _manager()
    insert_parent = MagicMock()
    monkeypatch.setattr(
        "core.stealth_order_manager.insert_order_parent",
        insert_parent,
        raising=True,
    )

    with pytest.raises(OrderCreationError, match="cancel_reentry"):
        manager.create_stealth_order(
            product_id="BTC-USD",
            side="SELL",
            total_size=0.01,
            limit_price=100000.0,
            reveal_condition={"type": "time_delay", "delay_seconds": 0},
            cancel_reentry_policy={
                "enabled": True,
                "reference_price_source": "midpoint",
                "distance_type": "A",
                "cancel_distance": 8,
                "reentry_distance": 9,
            },
        )

    manager._save_stealth_order_to_db.assert_not_called()
    insert_parent.assert_not_called()


def test_spot_hotpoint_opt_in_rejected_before_persistence(monkeypatch):
    manager = _manager()
    insert_parent = MagicMock()
    monkeypatch.setattr(
        "core.stealth_order_manager.insert_order_parent",
        insert_parent,
        raising=True,
    )

    with pytest.raises(OrderCreationError, match="hotpoint_auto_placement"):
        manager.create_stealth_order(
            product_id="BTC-USD",
            side="BUY",
            total_size=0.01,
            limit_price=100000.0,
            reveal_condition={"type": "time_delay", "delay_seconds": 0},
            enable_hotpoint_replication=True,
        )

    manager._save_stealth_order_to_db.assert_not_called()
    insert_parent.assert_not_called()


def test_spot_anchor_reprice_short_circuits_before_reprice_work():
    manager = _manager()
    manager._get_current_market_data = MagicMock()
    manager._get_active_stealth_orders = MagicMock(return_value=["sid"])

    assert manager.process_anchor_repricing_for_product("BTC-USD") == 0
    manager._get_current_market_data.assert_not_called()
    manager._get_active_stealth_orders.assert_not_called()


def test_spot_move_revealed_rejected_by_capability_policy():
    manager = _manager()
    manager.in_memory_orders["sid"] = {
        "stealth_order_id": "sid",
        "product_id": "BTC-USD",
        "side": "SELL",
        "status": "REVEALED",
        "executed_size": 0.0,
        "limit_price": 100000.0,
        "anchor_repricing_state_json": {
            "active_exchange_order_id": "exchange-1",
            "active_exchange_price": 100000.0,
        },
    }

    with pytest.raises(StealthMoveError, match="move_revealed"):
        manager.build_stealth_move_plan("sid", 100100.0)


def test_hotpoint_placer_blocks_spot_before_slot_or_rest():
    event = HotpointTriggerEvent(
        product_id="BTC-USD",
        side="BUY",
        bucket_id=42,
        bucket_center=100000.0,
        fills_in_window=3,
        last_fill_price=99950.0,
        mean_fill_price=100010.0,
        triggered_at=0.0,
    )
    rate_limiter = HotpointRateLimiter(cap_n=1, window_seconds=60)
    rest = MagicMock()
    insert = MagicMock()

    result = place_hotpoint_order(
        event=event,
        rate_limiter=rate_limiter,
        product_meta={
            "base_min_size": 0.00000001,
            "base_increment": 0.00000001,
            "price_increment": 0.01,
        },
        policy=HotpointPlacementPolicy.WINDOW_CENTER,
        rest_client=rest,
        insert_order_parent_fn=insert,
        kill_switch_enabled=True,
        log_callback=MagicMock(),
        now_epoch=0.0,
    )

    assert result.status == STATUS_PRODUCT_CAPABILITY_BLOCKED
    assert rate_limiter.current_count(
        product_id="BTC-USD",
        side="BUY",
        bucket_id=42,
        now=0.0,
    ) == 0
    rest.limit_order_gtc.assert_not_called()
    insert.assert_not_called()
