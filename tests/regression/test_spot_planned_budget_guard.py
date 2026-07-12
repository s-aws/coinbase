"""Regression tests for spot planned-budget action guards."""

import asyncio
import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.action_condition_guard import (
    ActionConditionGuard,
    collect_spot_planned_budget_commitments,
    estimate_spot_replacement_budget_delta,
)
from core.enums import (
    ActionConditionType,
    ActionGuardPhase,
    OrderSide,
    ProductType,
    StealthOrderStatus,
)
from core.exceptions import OrderCreationError
from core.models import RevealExecutionPlan
from core.stealth_order_manager import StealthOrderManager


pytestmark = pytest.mark.regression


def _manager():
    manager = StealthOrderManager(db_client=None, log_callback=MagicMock())
    manager._save_stealth_order_to_db = MagicMock()
    manager._update_stealth_order = MagicMock()
    return manager


def _spot_order(
    stealth_order_id,
    *,
    status=StealthOrderStatus.HIDDEN.value,
    side=OrderSide.SELL.value,
    remaining_size=1.0,
    limit_price=100000.0,
):
    return {
        "stealth_order_id": stealth_order_id,
        "product_id": "BTC-USDC",
        "side": side,
        "total_size": remaining_size,
        "remaining_size": remaining_size,
        "revealed_size": 0.0,
        "executed_size": 0.0,
        "limit_price": limit_price,
        "status": status,
        "reveal_condition_json": {"type": "time_delay", "delay_seconds": 0},
        "reveal_condition_type": "time_delay",
        "revealed_orders": [],
        "parent_order_id": None,
    }


def _spot_metadata():
    return {
        "BTC-USDC": {
            "product_id": "BTC-USDC",
            "product_type": "SPOT",
            "base_currency": "BTC",
            "quote_currency": "USDC",
        },
    }


def _wire_reveal(manager, sid, *, slice_size, submitted_price=100000.0):
    manager.profit_validator = None
    manager._calculate_reveal_size = MagicMock(return_value=slice_size)
    manager.build_reveal_execution_plan = MagicMock(
        return_value=RevealExecutionPlan(
            configured_limit_price=submitted_price,
            submitted_limit_price=submitted_price,
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
    return manager.in_memory_orders[sid]


def test_planned_budget_collects_only_pre_exchange_spot_commitments():
    orders = {
        "hidden-sell": _spot_order("hidden-sell", remaining_size=0.25),
        "pending-buy": _spot_order(
            "pending-buy",
            status=StealthOrderStatus.PENDING.value,
            side=OrderSide.BUY.value,
            remaining_size=0.01,
            limit_price=100000.0,
        ),
        "triggered-sell": _spot_order(
            "triggered-sell",
            status=StealthOrderStatus.TRIGGERED.value,
            remaining_size=0.5,
        ),
        "revealed-sell": _spot_order(
            "revealed-sell",
            status=StealthOrderStatus.REVEALED.value,
            remaining_size=9.0,
        ),
        "cancelled-sell": _spot_order(
            "cancelled-sell",
            status=StealthOrderStatus.CANCELLED.value,
            remaining_size=9.0,
        ),
        "future-sell": {
            **_spot_order("future-sell", remaining_size=9.0),
            "product_id": "BIP-20DEC30-CDE",
        },
    }

    commitments = collect_spot_planned_budget_commitments(
        orders,
        exclude_stealth_order_id="triggered-sell",
    )

    assert commitments == {
        "BTC": 0.25,
        "USDC": 1000.0,
    }


def test_spot_buy_replacement_budget_delta_credits_existing_quote_hold():
    delta = estimate_spot_replacement_budget_delta(
        product_id="BTC-USDC",
        side=OrderSide.BUY.value,
        size=0.1,
        limit_price=110000.0,
        existing_size=0.1,
        existing_limit_price=100000.0,
        product_metadata=_spot_metadata(),
        spot_product_ids=["BTC-USDC"],
    )

    assert delta["currency"] == "USDC"
    assert delta["new_required"] == pytest.approx(11000.0)
    assert delta["existing_credit"] == pytest.approx(10000.0)
    assert delta["amount"] == pytest.approx(1000.0)


def test_spot_sell_replacement_budget_delta_credits_existing_base_hold():
    delta = estimate_spot_replacement_budget_delta(
        product_id="BTC-USDC",
        side=OrderSide.SELL.value,
        size=1.0,
        limit_price=110000.0,
        existing_size=1.0,
        existing_limit_price=100000.0,
        product_metadata=_spot_metadata(),
        spot_product_ids=["BTC-USDC"],
    )

    assert delta["currency"] == "BTC"
    assert delta["new_required"] == pytest.approx(1.0)
    assert delta["existing_credit"] == pytest.approx(1.0)
    assert delta["amount"] == pytest.approx(0.0)


def test_spot_replacement_guard_subtracts_planned_budget_from_delta():
    guard = ActionConditionGuard(
        policy={ActionConditionType.WALLET_AVAILABLE.value: {"enabled": True}},
        credentials_configured=lambda: True,
        wallet_fetcher=lambda: {
            "USDC": {"available_balance": {"value": "15.0"}},
        },
        planned_budget_fetcher=lambda: {"USDC": 6.0},
        product_metadata=_spot_metadata(),
        spot_product_ids=["BTC-USDC"],
    )

    ok, failure = guard.evaluate_replacement(
        phase=ActionGuardPhase.REVEAL,
        product_id="BTC-USDC",
        side=OrderSide.BUY.value,
        size=0.1,
        limit_price=200.0,
        existing_size=0.1,
        existing_limit_price=100.0,
        stealth_order_id="sid-replace",
        replaced_client_order_id="old-placement",
        replaced_exchange_order_id="old-exchange",
    )

    assert ok is False
    assert failure["block_category"] == (
        ActionConditionType.PLANNED_BUDGET_AVAILABLE.value
    )
    assert failure["required_delta"] == pytest.approx(10.0)
    assert failure["available_after_planned"] == pytest.approx(9.0)
    assert failure["replacement"] is True


def test_spot_planning_blocks_when_hidden_budget_would_overcommit():
    manager = _manager()
    manager._rest_credentials_configured = MagicMock(return_value=True)
    manager._get_account_wallets_for_action_guard = MagicMock(
        return_value={"BTC": {"available_balance": {"value": "1.0"}}}
    )
    manager.in_memory_orders["existing"] = _spot_order(
        "existing",
        remaining_size=0.8,
    )

    existing_ids = set(manager.in_memory_orders)

    with pytest.raises(OrderCreationError, match="planned commitment"):
        manager.create_stealth_order(
            product_id="BTC-USDC",
            side=OrderSide.SELL.value,
            total_size=0.3,
            limit_price=100000.0,
            reveal_condition={"type": "time_delay", "delay_seconds": 0},
            target_movement=0.0,
        )

    assert set(manager.in_memory_orders) == existing_ids
    manager._save_stealth_order_to_db.assert_not_called()


def test_spot_reveal_blocks_after_external_wallet_drain_before_rest(monkeypatch):
    manager = _manager()
    sid = "sid-drained"
    manager.in_memory_orders[sid] = _spot_order(
        sid,
        status=StealthOrderStatus.TRIGGERED.value,
        remaining_size=1.0,
    )
    _wire_reveal(manager, sid, slice_size=1.0)
    manager._get_account_wallets_for_action_guard = MagicMock(
        return_value={"BTC": {"available_balance": {"value": "0.5"}}}
    )
    insert_parent = MagicMock()
    monkeypatch.setattr(
        "core.stealth_order_manager.insert_order_parent",
        insert_parent,
    )

    assert manager.reveal_order_slice(sid) is None

    insert_parent.assert_not_called()
    manager.order_placement_hooks.call_pre_submission_hooks.assert_not_called()
    _, lifecycle_kwargs = manager._dispatch_lifecycle_event.call_args
    assert lifecycle_kwargs["extra"]["block_category"] == (
        ActionConditionType.WALLET_AVAILABLE.value
    )
    assert lifecycle_kwargs["extra"]["currency"] == "BTC"


def test_spot_reveal_counts_other_hidden_budget_before_rest(monkeypatch):
    manager = _manager()
    sid = "sid-triggered"
    manager.in_memory_orders[sid] = _spot_order(
        sid,
        status=StealthOrderStatus.TRIGGERED.value,
        remaining_size=0.75,
    )
    manager.in_memory_orders["other-hidden"] = _spot_order(
        "other-hidden",
        status=StealthOrderStatus.HIDDEN.value,
        remaining_size=0.4,
    )
    _wire_reveal(manager, sid, slice_size=0.75)
    manager._get_account_wallets_for_action_guard = MagicMock(
        return_value={"BTC": {"available_balance": {"value": "1.0"}}}
    )
    insert_parent = MagicMock()
    monkeypatch.setattr(
        "core.stealth_order_manager.insert_order_parent",
        insert_parent,
    )

    assert manager.reveal_order_slice(sid) is None

    insert_parent.assert_not_called()
    _, lifecycle_kwargs = manager._dispatch_lifecycle_event.call_args
    assert lifecycle_kwargs["extra"]["block_category"] == (
        ActionConditionType.PLANNED_BUDGET_AVAILABLE.value
    )
    assert lifecycle_kwargs["extra"]["planned_commitment"] == 0.4
    assert lifecycle_kwargs["extra"]["available_after_planned"] == 0.6


def _make_websocket():
    ws = MagicMock()
    ws.send = AsyncMock()
    return ws


def _run(coro):
    return asyncio.run(coro)


def _sent_payload(ws):
    assert ws.send.await_args_list
    return json.loads(ws.send.await_args_list[-1].args[0])


def _admitting_controller():
    ctrl = MagicMock()
    ctrl.is_admitting.return_value = True
    ctrl.state = MagicMock(value="RUNNING")

    @contextmanager
    def _track(_category):
        yield

    ctrl.track_inflight.side_effect = _track
    return ctrl


def test_dashboard_direct_spot_order_subtracts_hidden_stealth_budget(monkeypatch):
    import configuration
    import application.admin_api.command_service as command_service
    import core.action_condition_guard as guard_module
    import dashboard_server
    from application.admin_api.spot_portfolio_binding import (
        EXPECTED_SPOT_PORTFOLIO_TYPE,
        SpotPortfolioBindingEvidence,
    )

    test_portfolio_id = "11111111-2222-4333-8444-555555555555"
    monkeypatch.setattr(
        command_service,
        "evaluate_spot_test_portfolio_binding",
        lambda **_kwargs: SpotPortfolioBindingEvidence(
            ready=True,
            blocker=None,
            expected_portfolio_id=test_portfolio_id,
            expected_portfolio_label="Test",
            expected_portfolio_type=EXPECTED_SPOT_PORTFOLIO_TYPE,
            observed_portfolio_id=test_portfolio_id,
            observed_portfolio_label="Test",
            observed_portfolio_type=EXPECTED_SPOT_PORTFOLIO_TYPE,
            can_view=True,
            can_trade=True,
        ),
    )

    monkeypatch.setattr(
        configuration,
        "ACTION_CONDITION_GUARDS",
        {
            "limits": [{
                "name": "direct_spot_cap",
                "product_type": ProductType.SPOT.value,
                "max_notional": 1000,
                "phases": [ActionGuardPhase.PLANNING.value],
            }]
        },
    )
    monkeypatch.setattr(guard_module, "rest_credentials_configured", lambda: True)
    monkeypatch.setattr(
        guard_module,
        "fetch_account_wallets",
        lambda: {"USDC": {"available_balance": {"value": "1000"}}},
    )

    manager = MagicMock()
    manager._get_spot_planned_budget_commitments.return_value = {"USDC": 900.0}
    bridge = MagicMock()
    bridge.stealth_manager = manager

    ws = _make_websocket()
    rest_client = MagicMock()
    message = json.dumps({
        "type": "place_order",
        "params": {
            "product_id": "BTC-USDC",
            "side": OrderSide.BUY.value,
            "manual_live_acknowledgement": True,
            "order_configuration": {
                "limit_limit_gtc": {
                    "base_size": "0.2",
                    "limit_price": "1000",
                },
            },
        },
    })

    with patch.object(dashboard_server, "REST_CLIENT_AVAILABLE", True), \
         patch.object(dashboard_server, "REST_CLIENT", rest_client), \
         patch.object(dashboard_server, "stealth_order_bridge", bridge), \
         patch.object(dashboard_server, "get_runtime_controller",
                      return_value=_admitting_controller()), \
         patch.object(dashboard_server, "add_log_entry"):
        _run(dashboard_server.handle_client_message(ws, message))

    payload = _sent_payload(ws)
    assert payload["status"] == "error"
    assert payload["guard"]["block_category"] == (
        ActionConditionType.PLANNED_BUDGET_AVAILABLE.value
    )
    assert payload["guard"]["planned_commitment"] == 900.0
    rest_client.create_order.assert_not_called()
