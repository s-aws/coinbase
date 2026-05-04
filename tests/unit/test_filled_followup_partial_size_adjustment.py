"""Unit tests for FILLED follow-up sizing when partial follow-ups already exist."""

from unittest.mock import Mock, patch

from configuration import OrderBook
from core.enums import OrderStatus
from core.order_engine import OrderEngine


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
        "allow_partial_fills": True,
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


def _filled_order() -> dict:
    return {
        "client_order_id": "placed-1",
        "order_id": "exchange-1",
        "product_id": "BTC-USDC",
        "order_side": "BUY",
        "side": "BUY",
        "price": "100.0",
        "avg_price": "100.0",
        "size": "40.0",
        "filled_size": "40.0",
        "status": OrderStatus.FILLED.value,
        "outstanding_hold_amount": "0",
    }


def _attach_stealth_bridge(engine: OrderEngine) -> Mock:
    stealth_manager = Mock()
    stealth_manager._market_cache = {}
    stealth_manager.find_stealth_order_by_placed_order_id.return_value = {
        "stealth_order_id": "stealth-parent-1",
        "parent_order_id": "parent-1",
        "reveal_condition_json": {"type": "price", "direction": "below"},
        "follow_up_reveal_direction": "opposite",
    }
    stealth_manager.create_follow_up_stealth_order.return_value = "stealth-child-1"
    engine.stealth_order_bridge = Mock(stealth_manager=stealth_manager)
    return stealth_manager


def _configure_common_followup_mocks(engine: OrderEngine) -> None:
    engine.claim_follow_up_processing = Mock(return_value=True)
    engine.complete_follow_up_processing = Mock()
    engine.release_follow_up_processing = Mock()
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
            "order_base_size": "40.0",
            "product_id": "BTC-USDC",
        }
    )
    engine.child_order_already_exists = Mock(return_value=False)
    engine.normalize_product_type = Mock(return_value="SPOT")
    engine.register_child_order = Mock()


def test_filled_follow_up_size_reduced_by_partial_progress():
    engine = _build_engine()
    stealth_manager = _attach_stealth_bridge(engine)
    _configure_common_followup_mocks(engine)

    with patch(
        "database.order.get_partial_fill_progress",
        return_value={
            "client_order_id": "placed-1",
            "original_order_size": 40.0,
            "min_order_size": 1.0,
            "partial_follow_ups_created": 21,
        },
    ), patch(
        "database.order.get_parent_order",
        return_value={"target_movement": 0.001, "target_movement_type": "P"},
    ):
        engine.handle_filled_order(_filled_order())

    stealth_manager.create_follow_up_stealth_order.assert_called_once()
    assert stealth_manager.create_follow_up_stealth_order.call_args.kwargs["total_size"] == 19.0


def test_filled_follow_up_skipped_when_partial_progress_already_covers_size():
    engine = _build_engine()
    stealth_manager = _attach_stealth_bridge(engine)
    _configure_common_followup_mocks(engine)

    with patch(
        "database.order.get_partial_fill_progress",
        return_value={
            "client_order_id": "placed-1",
            "original_order_size": 40.0,
            "min_order_size": 1.0,
            "partial_follow_ups_created": 40,
        },
    ), patch(
        "database.order.get_parent_order",
        return_value={"target_movement": 0.001, "target_movement_type": "P"},
    ):
        engine.handle_filled_order(_filled_order())

    stealth_manager.create_follow_up_stealth_order.assert_not_called()
    engine.complete_follow_up_processing.assert_called_once_with("filled", "placed-1")
