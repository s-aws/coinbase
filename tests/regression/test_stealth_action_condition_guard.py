from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.enums import (
    ActionConditionType,
    ActionGuardPhase,
    InventoryAuthorityStatus,
    OrderSide,
    ProductType,
    StealthOrderStatus,
)
from core.exceptions import OrderCreationError
from core.models import RevealExecutionPlan
from core.stealth_order_manager import StealthOrderManager


def _manager(policy=None):
    manager = StealthOrderManager(
        db_client=None,
        log_callback=MagicMock(),
        action_condition_guard_policy=policy or {},
    )
    manager._save_stealth_order_to_db = MagicMock()
    manager._update_stealth_order = MagicMock()
    return manager


@pytest.mark.regression
def test_action_guard_blocks_planning_before_persistence():
    manager = _manager({
        "limits": [
            {
                "name": "tiny_spot_notional",
                "product_type": ProductType.SPOT.value,
                "max_notional": 50.0,
            }
        ]
    })

    with pytest.raises(OrderCreationError, match="action-condition guard"):
        manager.create_stealth_order(
            product_id="BTC-USD",
            side=OrderSide.BUY.value,
            total_size=0.001,
            limit_price=100000.0,
            reveal_condition={"type": "time_delay", "delay_seconds": 0},
            target_movement=0.0,
        )

    assert manager.in_memory_orders == {}
    manager._save_stealth_order_to_db.assert_not_called()


@pytest.mark.regression
def test_action_guard_blocks_reveal_before_rest_and_parent_preinsert(monkeypatch):
    manager = _manager()
    sid = "sid-wallet-drained"
    order = {
        "stealth_order_id": sid,
        "product_id": "BTC-USD",
        "side": OrderSide.SELL.value,
        "total_size": 1.0,
        "remaining_size": 1.0,
        "revealed_size": 0.0,
        "executed_size": 0.0,
        "limit_price": 100000.0,
        "status": StealthOrderStatus.TRIGGERED.value,
        "reveal_condition_json": {"type": "time_delay", "delay_seconds": 0},
        "reveal_condition_type": "time_delay",
        "revealed_orders": [],
        "parent_order_id": None,
    }
    manager.in_memory_orders[sid] = order
    manager.profit_validator = None
    manager._calculate_reveal_size = MagicMock(return_value=1.0)
    manager.build_reveal_execution_plan = MagicMock(
        return_value=RevealExecutionPlan(
            configured_limit_price=100000.0,
            submitted_limit_price=100000.0,
            reveal_pricing_policy="configured_limit",
            reveal_price_source="configured_limit",
            fallback_used=False,
        )
    )
    manager._dispatch_lifecycle_event = MagicMock()
    manager.order_placement_hooks = SimpleNamespace(
        call_pre_submission_hooks=MagicMock(),
        call_post_submission_hooks=MagicMock(),
    )
    manager._rest_credentials_configured = MagicMock(return_value=True)
    manager._get_account_wallets_for_action_guard = MagicMock(
        return_value={"BTC": {"available_balance": {"value": "0.25"}}}
    )
    insert_parent = MagicMock()
    monkeypatch.setattr(
        "core.stealth_order_manager.insert_order_parent",
        insert_parent,
    )

    assert manager.reveal_order_slice(sid) is None

    insert_parent.assert_not_called()
    manager.order_placement_hooks.call_pre_submission_hooks.assert_not_called()
    manager._dispatch_lifecycle_event.assert_called_once()
    _, lifecycle_kwargs = manager._dispatch_lifecycle_event.call_args
    assert lifecycle_kwargs["event"].value == "PLACEMENT_BLOCKED"
    assert lifecycle_kwargs["extra"]["block_category"] == "wallet_available"


@pytest.mark.regression
def test_action_guard_configured_limits_apply_to_futures():
    manager = _manager({
        "limits": [
            {
                "name": "future_contract_cap",
                "product_type": ProductType.FUTURE.value,
                "max_base_size": 10,
            }
        ]
    })

    ok, failure = manager._evaluate_action_condition_guard(
        phase=ActionGuardPhase.PLANNING,
        product_id="BIP-20DEC30-CDE",
        side=OrderSide.SELL.value,
        size=11.0,
        limit_price=78000.0,
        stealth_order_id="sid-future-limit",
    )

    assert ok is False
    assert failure["condition"] == "max_base_size"
    assert failure["product_type"] == ProductType.FUTURE.value


@pytest.mark.regression
def test_action_guard_spot_buy_checks_quote_wallet_when_credentials_exist():
    manager = _manager()
    manager._rest_credentials_configured = MagicMock(return_value=True)
    manager._get_account_wallets_for_action_guard = MagicMock(
        return_value={"USD": {"available_balance": {"value": "50"}}}
    )

    ok, failure = manager._evaluate_action_condition_guard(
        phase=ActionGuardPhase.PLANNING,
        product_id="BTC-USD",
        side=OrderSide.BUY.value,
        size=0.1,
        limit_price=1000.0,
        stealth_order_id="sid-spot-buy",
    )

    assert ok is False
    assert failure["condition"] == "wallet_available"
    assert failure["currency"] == "USD"
    assert failure["required"] == 100.0


@pytest.mark.regression
def test_known_inventory_guard_blocks_spot_sell_before_persistence():
    manager = _manager({
        ActionConditionType.WALLET_AVAILABLE.value: {"enabled": False},
        ActionConditionType.KNOWN_INVENTORY_AVAILABLE.value: {"enabled": True},
    })

    with pytest.raises(OrderCreationError, match="fill ledger repository") as exc:
        manager.create_stealth_order(
            product_id="BTC-USD",
            side=OrderSide.SELL.value,
            total_size=0.1,
            limit_price=100000.0,
            reveal_condition={"type": "time_delay", "delay_seconds": 0},
            target_movement=0.0,
        )

    assert manager.in_memory_orders == {}
    manager._save_stealth_order_to_db.assert_not_called()
    assert exc.value.context["product_id"] == "BTC-USD"
    assert exc.value.context["guard"]["block_category"] == (
        ActionConditionType.KNOWN_INVENTORY_AVAILABLE.value
    )
    log_args, _ = manager.log_callback.call_args
    log_payload = log_args[1]
    assert log_payload["block_category"] == (
        ActionConditionType.KNOWN_INVENTORY_AVAILABLE.value
    )
    assert log_payload["inventory_authority"]["status"] == (
        InventoryAuthorityStatus.UNAVAILABLE.value
    )
