"""Unit test proving duplicate FILLED events do not create duplicate follow-up orders."""

from unittest.mock import Mock, patch

from configuration import OrderBook
from core.enums import FollowUpKind, OrderOwnershipProvenance, OrderStatus
from core.order_engine import OrderEngine
from core.orderbook import ClaimLedger


def _build_engine() -> OrderEngine:
    orderbook = Mock(spec=OrderBook)
    orderbook.parent_order_ids = {}
    orderbook.child_order_ids = {}
    orderbook.order = {}
    orderbook.positions = {"FUTURE": {}}
    orderbook.should_replace = {"FILLED": True, "CANCELLED": True}
    orderbook.default_max_order_replacement = 11
    orderbook.product = {"BTC-USDC": {"future_product_details": {"contract_size": "1"}}}
    orderbook.profit = {"SPOT": {"BUY": 0.001, "SELL": 0.001}}
    orderbook.mandatory_fee_per_contract = {}
    orderbook.get_position_side = Mock(return_value=None)

    db_module = Mock()
    db_module.get_parent_order.return_value = {
        "id": 1,
        "target_movement": 0.001,
        "target_movement_type": "P",
        "max_order_replacement": 11,
        "current_order_replacement": 0,
        "allow_partial_fills": False,
    }

    subscription = Mock()
    subscription.channels = []

    engine = OrderEngine(
        orderbook=orderbook,
        db_module=db_module,
        subscription=subscription,
        api_key="test_key",
        api_secret="test_secret",
        order_post_only={"BUY": False, "SELL": False},
    )
    return engine


def test_duplicate_filled_event_creates_follow_up_once(monkeypatch):
    import dashboard_server

    from application.admin_api.command_runtime import (
        get_admin_api_fill_follow_up_executor,
    )

    engine = _build_engine()

    # Exercise the production wrappers against the real three-state claim kernel.
    claim_ledger = ClaimLedger(FollowUpKind)
    engine.orderbook.try_claim_follow_up = claim_ledger.try_claim
    engine.orderbook.complete_follow_up = claim_ledger.complete
    engine.orderbook.release_follow_up = claim_ledger.release
    engine.orderbook.follow_up_claim_state = claim_ledger.state
    engine.fill_repo = None
    engine.profit_validator = None

    engine._seed_parent_order_cache_from_db = Mock(return_value=True)
    engine.resolve_parent_client_order_id = Mock(return_value=(True, "parent-1"))
    engine.can_create_follow_up_order = Mock(
        return_value=(True, {"max_order_replacement": 11, "current_order_replacement": 0})
    )
    engine.resolve_parent_target_movement = Mock(return_value={"movement": 0.001, "type": "P"})
    engine.compute_order_template = Mock(
        return_value={
            "start_price": "100.0",
            "side": "BUY",
            "order_base_size": "0.01",
            "product_id": "BTC-USDC",
        }
    )
    engine.child_order_already_exists = Mock(return_value=False)
    engine._resolve_filled_follow_up_size_after_partials = Mock(
        return_value=(0.01, {})
    )
    engine.normalize_product_type = Mock(return_value="SPOT")
    engine.register_child_order = Mock()

    stealth_manager = Mock()
    stealth_manager._market_cache = {}
    stealth_manager.find_stealth_order_by_placed_order_id.return_value = {
        "stealth_order_id": "stealth-parent-1",
        "parent_order_id": "parent-1",
        "reveal_condition_json": {"type": "price", "direction": "below"},
        "follow_up_reveal_direction": "opposite",
    }
    stealth_manager.create_follow_up_stealth_order.return_value = "stealth-child-1"

    stealth_bridge = Mock(stealth_manager=stealth_manager)
    stealth_bridge.order_engine = engine
    engine.stealth_order_bridge = stealth_bridge
    monkeypatch.setattr(dashboard_server, "stealth_order_bridge", stealth_bridge)

    filled_order = {
        "client_order_id": "placed-1",
        "order_id": "exchange-1",
        "product_id": "BTC-USDC",
        "order_side": "BUY",
        "side": "BUY",
        "price": "100.0",
        "avg_price": "100.0",
        "size": "0.01",
        "filled_size": "0.01",
        "status": OrderStatus.FILLED.value,
        "outstanding_hold_amount": "0",
    }

    with patch(
        "database.order.get_parent_order",
        return_value={
            "target_movement": 0.001,
            "target_movement_type": "P",
        },
    ):
        executor = get_admin_api_fill_follow_up_executor()
        assert executor is not None
        assert executor.order_engine is engine
        executor.trigger_filled_follow_up(order=filled_order, context={})
        executor.trigger_filled_follow_up(order=filled_order, context={})

    # First FILLED creates the follow-up, second is dedup-blocked by claim flag.
    stealth_manager.create_follow_up_stealth_order.assert_called_once()
    assert (
        stealth_manager.create_follow_up_stealth_order.call_args.kwargs[
            "source_client_order_id"
        ]
        == "placed-1"
    )
    assert claim_ledger.state("filled", "placed-1") == "done"


def test_duplicate_filled_event_for_owned_direct_root_creates_one_child():
    engine = _build_engine()
    root_id = "880e8400-e29b-41d4-a716-446655440000"
    child_id = "990e8400-e29b-41d4-a716-446655440000"
    claim_ledger = ClaimLedger(FollowUpKind)
    engine.orderbook.try_claim_follow_up = claim_ledger.try_claim
    engine.orderbook.complete_follow_up = claim_ledger.complete
    engine.orderbook.release_follow_up = claim_ledger.release
    engine.orderbook.follow_up_claim_state = claim_ledger.state
    engine.orderbook.parent_order_ids[root_id] = {
        "orders": [],
        "target_movement": {"movement": 0.001, "type": "P"},
        "max_order_replacement": 11,
        "current_order_replacement": 0,
        "retail_portfolio_id": "11111111-2222-4333-8444-555555555555",
        "ownership_provenance": (
            OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value
        ),
    }
    engine.fill_repo = None
    engine.profit_validator = None
    engine.resolve_parent_client_order_id = Mock(return_value=(True, root_id))
    engine.can_create_follow_up_order = Mock(return_value=(True, {}))
    engine.resolve_parent_target_movement = Mock(
        return_value={"movement": 0.001, "type": "P"}
    )
    engine.compute_order_template = Mock(
        return_value={
            "start_price": "101.0",
            "side": "SELL",
            "order_base_size": "0.01",
            "product_id": "BTC-USDC",
        }
    )
    engine.child_order_already_exists = Mock(return_value=False)
    engine._resolve_filled_follow_up_size_after_partials = Mock(
        return_value=(0.01, {})
    )
    engine.register_child_order = Mock()

    stealth_manager = Mock()
    stealth_manager.find_stealth_order_by_placed_order_id.return_value = None
    stealth_manager.create_direct_root_fill_follow_up_stealth_order.return_value = (
        child_id
    )
    engine.stealth_order_bridge = Mock(stealth_manager=stealth_manager)
    filled_order = {
        "client_order_id": root_id,
        "order_id": "exchange-direct-root",
        "product_id": "BTC-USDC",
        "order_side": "BUY",
        "side": "BUY",
        "price": "100.0",
        "avg_price": "100.0",
        "size": "0.01",
        "filled_size": "0.01",
        "status": OrderStatus.FILLED.value,
        "outstanding_hold_amount": "0",
        "retail_portfolio_id": "11111111-2222-4333-8444-555555555555",
    }

    engine.handle_filled_order(filled_order)
    engine.handle_filled_order(filled_order)

    (
        stealth_manager.create_direct_root_fill_follow_up_stealth_order
        .assert_called_once()
    )
    kwargs = (
        stealth_manager.create_direct_root_fill_follow_up_stealth_order
        .call_args.kwargs
    )
    assert kwargs["root_parent_client_order_id"] == root_id
    assert kwargs["source_client_order_id"] == root_id
    assert kwargs["side"] == "SELL"
    engine.register_child_order.assert_called_once_with(
        child_id,
        root_id,
        bypass_replacement_cap=True,
    )
    assert claim_ledger.state("filled", root_id) == "done"


def test_external_filled_root_completes_no_follow_up_decision_once():
    engine = _build_engine()
    root_id = "770e8400-e29b-41d4-a716-446655440000"
    claim_ledger = ClaimLedger(FollowUpKind)
    engine.orderbook.try_claim_follow_up = claim_ledger.try_claim
    engine.orderbook.complete_follow_up = claim_ledger.complete
    engine.orderbook.release_follow_up = claim_ledger.release
    engine.orderbook.follow_up_claim_state = claim_ledger.state
    engine.orderbook.parent_order_ids[root_id] = {
        "orders": [],
        "target_movement": {"movement": 0.001, "type": "P"},
        "max_order_replacement": 11,
        "current_order_replacement": 0,
        "ownership_provenance": (
            OrderOwnershipProvenance.EXTERNAL_WS_OBSERVED.value
        ),
    }
    engine.fill_repo = None
    stealth_manager = Mock()
    stealth_manager.find_stealth_order_by_placed_order_id.return_value = None
    engine.stealth_order_bridge = Mock(stealth_manager=stealth_manager)

    filled_order = {
        "client_order_id": root_id,
        "order_id": "exchange-external-root",
        "product_id": "BTC-USDC",
        "order_side": "BUY",
        "side": "BUY",
        "price": "100.0",
        "avg_price": "100.0",
        "size": "0.01",
        "filled_size": "0.01",
        "status": OrderStatus.FILLED.value,
        "outstanding_hold_amount": "0",
    }

    engine.handle_filled_order(filled_order)
    engine.handle_filled_order(filled_order)

    assert claim_ledger.state("filled", root_id) == "done"
    stealth_manager.create_direct_root_fill_follow_up_stealth_order.assert_not_called()


def _build_failed_follow_up_attempt(*, creation_error=None):
    engine = _build_engine()
    claim_ledger = ClaimLedger(FollowUpKind)
    engine.orderbook.try_claim_follow_up = claim_ledger.try_claim
    engine.orderbook.complete_follow_up = claim_ledger.complete
    engine.orderbook.release_follow_up = claim_ledger.release
    engine.orderbook.follow_up_claim_state = claim_ledger.state
    engine.fill_repo = None
    engine.profit_validator = None
    engine._seed_parent_order_cache_from_db = Mock(return_value=True)
    engine.resolve_parent_client_order_id = Mock(return_value=(True, "parent-1"))
    engine.can_create_follow_up_order = Mock(
        return_value=(True, {"max_order_replacement": 11, "current_order_replacement": 0})
    )
    engine.resolve_parent_target_movement = Mock(
        return_value={"movement": 0.001, "type": "P"}
    )
    engine.compute_order_template = Mock(
        return_value={
            "start_price": "101.0",
            "side": "SELL",
            "order_base_size": "0.01",
            "product_id": "BTC-USDC",
        }
    )
    engine.child_order_already_exists = Mock(return_value=False)
    engine._resolve_filled_follow_up_size_after_partials = Mock(
        return_value=(0.01, {})
    )
    engine.register_child_order = Mock()

    stealth_manager = Mock()
    stealth_manager._market_cache = {}
    stealth_manager.find_stealth_order_by_placed_order_id.return_value = {
        "stealth_order_id": "stealth-parent-1",
        "parent_order_id": "parent-1",
        "reveal_condition_json": {"type": "price", "direction": "below"},
        "follow_up_reveal_direction": "opposite",
    }
    if creation_error is None:
        stealth_manager.create_follow_up_stealth_order.return_value = None
    else:
        stealth_manager.create_follow_up_stealth_order.side_effect = creation_error
    engine.stealth_order_bridge = Mock(stealth_manager=stealth_manager)

    filled_order = {
        "client_order_id": "placed-1",
        "order_id": "exchange-1",
        "product_id": "BTC-USDC",
        "order_side": "BUY",
        "side": "BUY",
        "price": "100.0",
        "avg_price": "100.0",
        "size": "0.01",
        "filled_size": "0.01",
        "status": OrderStatus.FILLED.value,
        "outstanding_hold_amount": "0",
    }
    return engine, stealth_manager, filled_order, claim_ledger


def test_blocked_filled_follow_up_releases_claim_when_no_child_was_created():
    engine, _manager, filled_order, claim_ledger = _build_failed_follow_up_attempt()

    with patch(
        "database.order.get_parent_order",
        return_value={
            "target_movement": 0.001,
            "target_movement_type": "P",
        },
    ):
        engine.handle_filled_order(filled_order)

    assert claim_ledger.state("filled", "placed-1") is None


def test_failed_filled_follow_up_leaves_claim_processing_without_ambiguous_readback():
    engine, _manager, filled_order, claim_ledger = _build_failed_follow_up_attempt(
        creation_error=RuntimeError("synthetic persistence failure"),
    )

    with patch(
        "database.order.get_parent_order",
        return_value={
            "target_movement": 0.001,
            "target_movement_type": "P",
        },
    ):
        engine.handle_filled_order(filled_order)

    assert claim_ledger.state("filled", "placed-1") == "processing"
    assert engine.child_order_already_exists.call_count == 1
