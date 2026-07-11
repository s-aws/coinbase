from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.enums import (
    ActionConditionType,
    ActionGuardPhase,
    InventoryAuthorityStatus,
    OrderOwnershipProvenance,
    OrderSide,
    ProductType,
    StealthLifecycleEvent,
    StealthOrderStatus,
)
from core.action_condition_guard import evaluate_spot_standing_price_limit
from core.exceptions import OrderCreationError
from core.models import RevealExecutionPlan
from core.stealth_order_manager import StealthOrderManager


TEST_PORTFOLIO_ID = "11111111-2222-4333-8444-555555555555"


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
        "product_id": "BTC-USDC",
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
def test_spot_standing_price_limit_is_shared_and_fail_closed():
    evaluated_at = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)
    sell = evaluate_spot_standing_price_limit(
        side=OrderSide.SELL.value,
        limit_price="101",
        best_bid="100",
        market_source="ticker",
        market_observed_at=evaluated_at,
        evaluated_at=evaluated_at,
    )
    assert sell == {
        "allowed": False,
        "source": "ticker",
        "best_bid": "100",
        "requested_limit_price": "101",
        "maximum_limit_price": "50.0",
        "minimum_limit_price": "150.0",
        "buy_limit_ratio": "0.5",
        "sell_limit_ratio": "1.5",
        "market_observed_at": "2026-07-11T12:00:00+00:00",
        "evaluated_at": "2026-07-11T12:00:00+00:00",
        "market_age_seconds": "0.0",
        "max_market_age_seconds": "30",
        "blocker": "standing_price_limit_not_authorized",
    }

    missing_ticker = evaluate_spot_standing_price_limit(
        side=OrderSide.BUY.value,
        limit_price="50",
        best_bid="100",
        market_source="unavailable",
    )
    assert missing_ticker["allowed"] is False
    assert missing_ticker["blocker"] == "live_ticker_bid_unavailable"

    fresh_rest_top_of_book = evaluate_spot_standing_price_limit(
        side=OrderSide.BUY.value,
        limit_price="50",
        best_bid="100",
        market_source="coinbase_rest_best_bid",
        market_observed_at=evaluated_at,
        evaluated_at=evaluated_at,
    )
    assert fresh_rest_top_of_book["allowed"] is True
    assert fresh_rest_top_of_book["source"] == "coinbase_rest_best_bid"

    stale_rest_top_of_book = evaluate_spot_standing_price_limit(
        side=OrderSide.BUY.value,
        limit_price="50",
        best_bid="100",
        market_source="coinbase_rest_best_bid",
        market_observed_at=evaluated_at - timedelta(seconds=31),
        evaluated_at=evaluated_at,
    )
    assert stale_rest_top_of_book["allowed"] is False
    assert stale_rest_top_of_book["blocker"] == "live_ticker_bid_stale"


@pytest.mark.regression
def test_spot_standing_price_limit_rejects_stale_or_missing_ticker_time():
    evaluated_at = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)

    stale = evaluate_spot_standing_price_limit(
        side=OrderSide.BUY.value,
        limit_price="50",
        best_bid="100",
        market_source="ticker",
        market_observed_at=evaluated_at - timedelta(seconds=31),
        evaluated_at=evaluated_at,
    )
    missing = evaluate_spot_standing_price_limit(
        side=OrderSide.BUY.value,
        limit_price="50",
        best_bid="100",
        market_source="ticker",
        market_observed_at=None,
        evaluated_at=evaluated_at,
    )
    future = evaluate_spot_standing_price_limit(
        side=OrderSide.BUY.value,
        limit_price="50",
        best_bid="100",
        market_source="ticker",
        market_observed_at=evaluated_at + timedelta(seconds=1),
        evaluated_at=evaluated_at,
    )

    assert stale["allowed"] is False
    assert stale["blocker"] == "live_ticker_bid_stale"
    assert stale["market_age_seconds"] == "31.0"
    assert missing["allowed"] is False
    assert missing["blocker"] == "live_ticker_timestamp_unavailable"
    assert future["allowed"] is False
    assert future["blocker"] == "live_ticker_timestamp_future"


@pytest.mark.parametrize(
    ("side", "limit_price", "best_bid", "expected_blocker"),
    [
        (
            OrderSide.SELL.value,
            "Infinity",
            "100",
            "standing_price_limit_invalid_order",
        ),
        (
            OrderSide.BUY.value,
            "1",
            "Infinity",
            "live_ticker_bid_unavailable",
        ),
        (
            OrderSide.SELL.value,
            "NaN",
            "100",
            "standing_price_limit_invalid_order",
        ),
        (
            OrderSide.BUY.value,
            "1",
            "NaN",
            "live_ticker_bid_unavailable",
        ),
    ],
)
def test_spot_standing_price_limit_rejects_non_finite_values(
    side,
    limit_price,
    best_bid,
    expected_blocker,
):
    evidence = evaluate_spot_standing_price_limit(
        side=side,
        limit_price=limit_price,
        best_bid=best_bid,
        market_source="ticker",
        market_observed_at=datetime.now(timezone.utc),
    )

    assert evidence["allowed"] is False
    assert evidence["blocker"] == expected_blocker


@pytest.mark.regression
def test_direct_admin_root_child_reveal_stays_pre_exchange_outside_standing_limit(
    monkeypatch,
):
    manager = _manager()
    sid = "sid-direct-admin-child"
    order = {
        "stealth_order_id": sid,
        "product_id": "BTC-USDC",
        "side": OrderSide.SELL.value,
        "total_size": 0.01,
        "remaining_size": 0.01,
        "revealed_size": 0.0,
        "executed_size": 0.0,
        "limit_price": 101.0,
        "status": StealthOrderStatus.TRIGGERED.value,
        "reveal_condition_json": {
            "type": "price_threshold",
            "price_threshold": 101.0,
            "direction": "above",
            "hold_duration_seconds": 0,
            "standing_price_limit_policy": "admin_test_profile",
        },
        "reveal_condition_type": "price_threshold",
        "revealed_orders": [],
        "parent_order_id": "11111111-1111-4111-8111-111111111111",
        "reason": "follow_up_replacement",
    }
    manager.in_memory_orders[sid] = order
    manager.expected_retail_portfolio_id = TEST_PORTFOLIO_ID
    parent_rows = {
        sid: {
            "client_order_id": sid,
            "product_id": "BTC-USDC",
            "side": OrderSide.SELL.value,
            "size": 0.01,
            "price": 101.0,
            "status": "PENDING",
            "parent_order_id": order["parent_order_id"],
            "ownership_provenance": (
                OrderOwnershipProvenance.ADMIN_FILL_FOLLOW_UP.value
            ),
            "retail_portfolio_id": TEST_PORTFOLIO_ID,
            "correlation_id": "corr-direct-child",
            "audit_id": "audit-direct-child",
        },
        order["parent_order_id"]: {
            "client_order_id": order["parent_order_id"],
            "product_id": "BTC-USDC",
            "side": OrderSide.BUY.value,
            "size": 0.01,
            "price": 100.0,
            "status": "FILLED",
            "parent_order_id": None,
            "ownership_provenance": (
                OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value
            ),
            "retail_portfolio_id": TEST_PORTFOLIO_ID,
            "correlation_id": "corr-direct-child",
            "audit_id": "audit-direct-child",
        },
    }
    monkeypatch.setattr(
        "core.stealth_order_manager.get_parent_order",
        lambda client_order_id: parent_rows.get(client_order_id),
    )
    authority_resolver = MagicMock(
        wraps=manager._resolve_admin_fill_follow_up_reveal_authority
    )
    manager._resolve_admin_fill_follow_up_reveal_authority = authority_resolver
    manager.profit_validator = None
    manager._calculate_reveal_size = MagicMock(return_value=0.01)
    manager.build_reveal_execution_plan = MagicMock(
        return_value=RevealExecutionPlan(
            configured_limit_price=101.0,
            submitted_limit_price=101.0,
            reveal_pricing_policy="configured_limit",
            reveal_price_source="configured_limit",
            fallback_used=False,
            market_source="ticker",
            market_bid=100.0,
            market_ask=100.1,
        )
    )
    manager._evaluate_action_condition_guard = MagicMock(return_value=(True, None))
    manager._get_current_market_data = MagicMock(
        return_value={
            "price": 100.05,
            "bid": 100.0,
            "ask": 100.1,
            "volume_1m": 5.0,
            "time": datetime.now(timezone.utc),
            "source": "ticker",
        }
    )
    manager._dispatch_lifecycle_event = MagicMock()
    manager.order_placement_hooks = SimpleNamespace(
        call_pre_submission_hooks=MagicMock(
            side_effect=lambda payload: payload["reveal_condition_json"].pop(
                "standing_price_limit_policy",
                None,
            )
        ),
        call_post_submission_hooks=MagicMock(),
    )
    rest_client = SimpleNamespace(place_limit_order=MagicMock())
    monkeypatch.setattr("configuration.REST_CLIENT", rest_client, raising=True)
    insert_parent = MagicMock()
    monkeypatch.setattr(
        "core.stealth_order_manager.insert_order_parent",
        insert_parent,
    )

    assert manager.reveal_order_slice(sid) is None
    assert manager.reveal_order_slice(sid) is None

    rest_client.place_limit_order.assert_not_called()
    insert_parent.assert_not_called()
    authority_resolver.assert_called_once_with(
        stealth_order_id=sid,
        order=order,
    )
    assert manager._evaluate_action_condition_guard.call_count == 2
    assert manager.order_placement_hooks.call_pre_submission_hooks.call_count == 1
    assert manager._dispatch_lifecycle_event.call_count == 1
    assert manager._get_action_guard_blocked_until(sid) > 0
    _, lifecycle_kwargs = manager._dispatch_lifecycle_event.call_args
    assert lifecycle_kwargs["event"] == StealthLifecycleEvent.PLACEMENT_BLOCKED
    assert lifecycle_kwargs["extra"]["block_category"] == (
        "standing_price_limit_not_authorized"
    )
    assert lifecycle_kwargs["extra"]["standing_price_limit"]["allowed"] is False
    assert order["status"] == StealthOrderStatus.TRIGGERED.value
    assert order["remaining_size"] == 0.01
    assert order["revealed_orders"] == []
    assert order["reveal_condition_json"]["standing_price_limit_policy"] == (
        "admin_test_profile"
    )
    assert order["last_lifecycle_event"] == "PLACEMENT_BLOCKED"
    assert order["anchor_repricing_state_json"][
        "standing_price_limit_blocker"
    ] == "standing_price_limit_not_authorized"


@pytest.mark.parametrize(
    ("marker", "child_provenance", "child_profile", "expected_blocker"),
    [
        (
            None,
            OrderOwnershipProvenance.ADMIN_FILL_FOLLOW_UP.value,
            TEST_PORTFOLIO_ID,
            "admin_child_standing_price_policy_missing",
        ),
        (
            "admin_test_profile",
            OrderOwnershipProvenance.EXTERNAL_WS_OBSERVED.value,
            TEST_PORTFOLIO_ID,
            "admin_child_ownership_provenance_mismatch",
        ),
        (
            "admin_test_profile",
            OrderOwnershipProvenance.ADMIN_FILL_FOLLOW_UP.value,
            "0b50f1c5-c897-4b22-84c1-c7a1b8bc164a",
            "admin_child_portfolio_scope_mismatch",
        ),
    ],
)
def test_admin_child_reveal_authority_requires_policy_provenance_and_test_scope(
    monkeypatch,
    marker,
    child_provenance,
    child_profile,
    expected_blocker,
):
    manager = _manager()
    manager.expected_retail_portfolio_id = TEST_PORTFOLIO_ID
    child_id = "22222222-2222-4222-8222-222222222222"
    root_id = "11111111-1111-4111-8111-111111111111"
    reveal_condition = {"type": "price_threshold"}
    if marker is not None:
        reveal_condition["standing_price_limit_policy"] = marker
    order = {
        "stealth_order_id": child_id,
        "product_id": "BTC-USDC",
        "side": OrderSide.SELL.value,
        "total_size": 0.01,
        "limit_price": 101.0,
        "parent_order_id": root_id,
        "reveal_condition_json": reveal_condition,
    }
    rows = {
        child_id: {
            "client_order_id": child_id,
            "product_id": "BTC-USDC",
            "side": OrderSide.SELL.value,
            "size": 0.01,
            "price": 101.0,
            "parent_order_id": root_id,
            "ownership_provenance": child_provenance,
            "retail_portfolio_id": child_profile,
            "correlation_id": "corr-authority",
            "audit_id": "audit-authority",
        },
        root_id: {
            "client_order_id": root_id,
            "product_id": "BTC-USDC",
            "side": OrderSide.BUY.value,
            "size": 0.01,
            "price": 100.0,
            "parent_order_id": None,
            "ownership_provenance": (
                OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value
            ),
            "retail_portfolio_id": TEST_PORTFOLIO_ID,
            "correlation_id": "corr-authority",
            "audit_id": "audit-authority",
        },
    }
    monkeypatch.setattr(
        "core.stealth_order_manager.get_parent_order",
        lambda client_order_id: rows.get(client_order_id),
    )

    authority = manager._resolve_admin_fill_follow_up_reveal_authority(
        stealth_order_id=child_id,
        order=order,
    )

    assert authority["required"] is True
    assert authority["ready"] is False
    assert expected_blocker in authority["blockers"]


def test_admin_child_block_retries_atomic_lifecycle_persistence_after_db_error():
    class _FlakyDbClient:
        def __init__(self):
            self.calls = []

        def execute_update(self, query, params):
            self.calls.append((query, params))
            if len(self.calls) == 1:
                raise RuntimeError("transient database failure")
            return 1

    manager = StealthOrderManager(db_client=None, log_callback=MagicMock())
    manager.db_client = _FlakyDbClient()
    manager._dispatch_lifecycle_event = MagicMock()
    order = {
        "stealth_order_id": "22222222-2222-4222-8222-222222222222",
        "status": StealthOrderStatus.TRIGGERED.value,
        "revealed_size": 0.0,
        "remaining_size": 0.01,
        "executed_size": 0.0,
        "limit_price": 101.0,
        "revealed_orders": [],
        "anchor_repricing_state_json": {},
        "cancel_reentry_policy_json": {},
        "cancel_reentry_state_json": {},
        "post_fill_retreat_policy_json": {"enabled": False},
    }
    evidence = {
        "required": True,
        "ready": False,
        "blockers": ["admin_child_portfolio_scope_mismatch"],
    }

    for _ in range(2):
        manager._record_admin_fill_follow_up_reveal_block(
            stealth_order_id=order["stealth_order_id"],
            order=order,
            block_category="admin_child_portfolio_scope_mismatch",
            failure_reason="profile mismatch; child remains pre-exchange",
            evidence=evidence,
        )

    assert len(manager.db_client.calls) == 2
    update_query, update_params = manager.db_client.calls[-1]
    assert "last_lifecycle_event = %s" in update_query
    assert "failure_reason = %s" in update_query
    assert StealthLifecycleEvent.PLACEMENT_BLOCKED.value in update_params
    assert "profile mismatch; child remains pre-exchange" in update_params
    assert manager._dispatch_lifecycle_event.call_count == 1


def test_admin_child_reveal_rejects_exchange_payload_drift_after_hooks(monkeypatch):
    manager = _manager()
    sid = "22222222-2222-4222-8222-222222222222"
    root_id = "11111111-1111-4111-8111-111111111111"
    order = {
        "stealth_order_id": sid,
        "product_id": "BTC-USDC",
        "side": OrderSide.SELL.value,
        "total_size": 0.01,
        "remaining_size": 0.01,
        "revealed_size": 0.0,
        "executed_size": 0.0,
        "limit_price": 200.0,
        "status": StealthOrderStatus.TRIGGERED.value,
        "reveal_condition_json": {
            "type": "price_threshold",
            "standing_price_limit_policy": "admin_test_profile",
        },
        "reveal_condition_type": "price_threshold",
        "revealed_orders": [],
        "parent_order_id": root_id,
        "reason": "follow_up_replacement",
    }
    manager.in_memory_orders[sid] = order
    manager.profit_validator = None
    manager._calculate_reveal_size = MagicMock(return_value=0.01)
    manager.build_reveal_execution_plan = MagicMock(
        return_value=RevealExecutionPlan(
            configured_limit_price=200.0,
            submitted_limit_price=200.0,
            reveal_pricing_policy="configured_limit",
            reveal_price_source="configured_limit",
            fallback_used=False,
            market_source="ticker",
            market_bid=100.0,
            market_ask=100.1,
            post_only=False,
        )
    )
    manager._resolve_admin_fill_follow_up_reveal_authority = MagicMock(
        return_value={
            "required": True,
            "ready": True,
            "blockers": [],
            "policy": "admin_test_profile",
        }
    )
    manager._evaluate_action_condition_guard = MagicMock(return_value=(True, None))
    manager._get_current_market_data = MagicMock(
        return_value={
            "price": 100.05,
            "bid": 100.0,
            "ask": 100.1,
            "time": datetime.now(timezone.utc),
            "source": "ticker",
        }
    )

    def mutate_exchange_fields(payload):
        payload.update(
            {
                "product_id": "ETH-USDC",
                "base_size": 999,
                "limit_price": 300,
                "client_order_id": "33333333-3333-4333-8333-333333333333",
                "post_only": True,
            }
        )

    manager.order_placement_hooks = SimpleNamespace(
        call_pre_submission_hooks=MagicMock(side_effect=mutate_exchange_fields),
        call_post_submission_hooks=MagicMock(),
    )
    manager._dispatch_lifecycle_event = MagicMock()
    rest_client = SimpleNamespace(
        place_limit_order=MagicMock(
            return_value={
                "success": True,
                "success_response": {
                    "order_id": "must-not-submit",
                    "client_order_id": sid,
                },
            }
        )
    )
    monkeypatch.setattr("configuration.REST_CLIENT", rest_client, raising=True)
    insert_parent = MagicMock()
    monkeypatch.setattr(
        "core.stealth_order_manager.insert_order_parent",
        insert_parent,
    )

    assert manager.reveal_order_slice(sid) is None

    rest_client.place_limit_order.assert_not_called()
    insert_parent.assert_not_called()
    _, lifecycle_kwargs = manager._dispatch_lifecycle_event.call_args
    assert lifecycle_kwargs["extra"]["block_category"] == (
        "admin_child_submission_payload_drift"
    )
    assert set(
        lifecycle_kwargs["extra"]["admin_fill_follow_up_reveal_authority"][
            "drifted_fields"
        ]
    ) == {
        "product_id",
        "base_size",
        "limit_price",
        "client_order_id",
        "post_only",
    }


def test_embedded_test_runtime_blocks_unscoped_legacy_stealth_reveal(monkeypatch):
    manager = _manager()
    manager.expected_retail_portfolio_id = TEST_PORTFOLIO_ID
    sid = "44444444-4444-4444-8444-444444444444"
    manager.in_memory_orders[sid] = {
        "stealth_order_id": sid,
        "product_id": "BTC-USDC",
        "side": OrderSide.SELL.value,
        "total_size": 0.01,
        "remaining_size": 0.01,
        "revealed_size": 0.0,
        "executed_size": 0.0,
        "limit_price": 200.0,
        "status": StealthOrderStatus.TRIGGERED.value,
        "reveal_condition_json": {
            "type": "price_threshold",
            "price_threshold": 200.0,
        },
        "reveal_condition_type": "price_threshold",
        "revealed_orders": [],
        "parent_order_id": None,
    }
    manager.profit_validator = None
    manager._calculate_reveal_size = MagicMock(return_value=0.01)
    manager.build_reveal_execution_plan = MagicMock(
        return_value=RevealExecutionPlan(
            configured_limit_price=200.0,
            submitted_limit_price=200.0,
            reveal_pricing_policy="configured_limit",
            reveal_price_source="configured_limit",
            fallback_used=False,
            market_source="ticker",
            market_bid=100.0,
            market_ask=100.1,
        )
    )
    manager._dispatch_lifecycle_event = MagicMock()
    manager.order_placement_hooks = SimpleNamespace(
        call_pre_submission_hooks=MagicMock(),
        call_post_submission_hooks=MagicMock(),
    )
    monkeypatch.setattr(
        "core.stealth_order_manager.get_parent_order",
        lambda _client_order_id: None,
    )
    rest_client = SimpleNamespace(place_limit_order=MagicMock())
    monkeypatch.setattr("configuration.REST_CLIENT", rest_client, raising=True)

    assert manager.reveal_order_slice(sid) is None

    rest_client.place_limit_order.assert_not_called()
    manager.order_placement_hooks.call_pre_submission_hooks.assert_not_called()
    _, lifecycle_kwargs = manager._dispatch_lifecycle_event.call_args
    assert lifecycle_kwargs["extra"]["block_category"] == (
        "admin_child_order_parent_missing"
    )
    assert "admin_child_standing_price_policy_missing" in (
        lifecycle_kwargs["extra"]["admin_fill_follow_up_reveal_authority"][
            "blockers"
        ]
    )


def test_authorized_admin_child_success_clears_prior_blocker_evidence():
    manager = _manager()
    sid = "55555555-5555-4555-8555-555555555555"
    manager._action_guard_blocked_until[sid] = 999999999.0
    order = {
        "anchor_repricing_state_json": {
            "admin_fill_follow_up_reveal_block": {"block_category": "old"},
            "standing_price_limit_policy": "admin_test_profile",
            "standing_price_limit": {"allowed": False},
            "standing_price_limit_blocker": "old",
            "unrelated_state": "preserved",
        },
        "last_lifecycle_event": StealthLifecycleEvent.PLACEMENT_BLOCKED.value,
        "failure_reason": "old blocker",
    }

    manager._clear_admin_fill_follow_up_reveal_block(
        stealth_order_id=sid,
        order=order,
    )

    assert order["anchor_repricing_state_json"] == {
        "unrelated_state": "preserved"
    }
    assert order["last_lifecycle_event"] == (
        StealthLifecycleEvent.REVEAL_SUCCEEDED.value
    )
    assert order["failure_reason"] is None
    assert sid not in manager._action_guard_blocked_until


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
        return_value={"USDC": {"available_balance": {"value": "50"}}}
    )

    ok, failure = manager._evaluate_action_condition_guard(
        phase=ActionGuardPhase.PLANNING,
        product_id="BTC-USDC",
        side=OrderSide.BUY.value,
        size=0.1,
        limit_price=1000.0,
        stealth_order_id="sid-spot-buy",
    )

    assert ok is False
    assert failure["condition"] == "wallet_available"
    assert failure["currency"] == "USDC"
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
