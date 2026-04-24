"""Unit tests for adaptive fee and target-movement regime integration."""

from unittest.mock import Mock

from calculation.fee_manager import FeeManager
from core.order_engine import OrderEngine
from configuration import OrderBook


class StubRestClient:
    """Simple REST client stub for FeeManager tests."""

    def get_transaction_summary(self):
        return {"fee_tier": {"taker_fee_rate": "0.0060"}}


def _create_engine_for_unit_tests() -> OrderEngine:
    """Create an OrderEngine with lightweight mocked collaborators."""
    orderbook = Mock(spec=OrderBook)
    orderbook.parent_order_ids = {}
    orderbook.child_order_ids = {}
    orderbook.order = {}
    orderbook.positions = {"FUTURE": {}}
    orderbook.should_replace = {"FILLED": True, "CANCELLED": True}
    orderbook.default_max_order_replacement = 11
    orderbook.product = {}
    orderbook.profit = {"SPOT": {"BUY": 0.001, "SELL": 0.001}}
    orderbook.mandatory_fee_per_contract = {}

    db_helper = Mock()
    db_helper.DB_CLIENT = Mock()

    subscription = Mock()
    subscription.channels = []

    return OrderEngine(
        orderbook=orderbook,
        db_helper=db_helper,
        subscription=subscription,
        api_key="test_key",
        api_secret="test_secret",
        order_post_only={"BUY": False, "SELL": False},
    )


def test_fee_manager_high_volume_increases_factors():
    manager = FeeManager(StubRestClient(), log_callback=lambda *_: None)

    baseline_fee = manager.get_profit_validation_fee_rate(product_id="BTC-USDC")
    baseline_target_factor = manager.get_target_movement_multiplier(product_id="BTC-USDC")

    # Build long-term baseline then shock higher short-term volume.
    for _ in range(30):
        manager.update_volume_signal("BTC-USDC", volume_24h=144000.0)
    for _ in range(20):
        manager.update_volume_signal("BTC-USDC", volume_24h=1440000.0)

    elevated_fee = manager.get_profit_validation_fee_rate(product_id="BTC-USDC")
    elevated_target_factor = manager.get_target_movement_multiplier(product_id="BTC-USDC")

    assert elevated_fee > baseline_fee
    assert elevated_target_factor > baseline_target_factor


def test_fee_manager_overnight_and_low_volume_reduce_target_factor():
    manager = FeeManager(StubRestClient(), log_callback=lambda *_: None)

    for _ in range(30):
        manager.update_volume_signal("BTC-USDC", volume_24h=1440000.0)
    manager.update_margin_window_type("FCM_MARGIN_WINDOW_TYPE_OVERNIGHT")
    for _ in range(30):
        manager.update_volume_signal("BTC-USDC", volume_24h=14400.0)

    factor = manager.get_target_movement_multiplier(product_id="BTC-USDC")
    info = manager.get_fee_info(product_id="BTC-USDC")

    assert factor < 1.0
    assert info["overnight_margin_active"] is True


def test_order_engine_resolve_parent_target_movement_applies_fee_manager_multiplier():
    engine = _create_engine_for_unit_tests()

    parent_id = "parent-client-id"
    engine.orderbook.parent_order_ids[parent_id] = {
        "target_movement": {"type": "P", "movement": 0.01}
    }
    engine.orderbook.order[parent_id] = {"product_id": "BTC-USDC"}

    fee_manager = Mock()
    fee_manager.get_target_movement_multiplier.return_value = 0.8
    engine.fee_manager = fee_manager

    result = engine.resolve_parent_target_movement(parent_id)

    assert result["type"] == "P"
    assert result["movement"] == 0.008
    fee_manager.get_target_movement_multiplier.assert_called_once_with("BTC-USDC")


def test_order_engine_process_futures_balance_summary_updates_margin_state():
    engine = _create_engine_for_unit_tests()
    manager = FeeManager(StubRestClient(), log_callback=lambda *_: None)
    engine.fee_manager = manager

    event = {
        "fcm_balance_summary": {
            "margin_window_type": "FCM_MARGIN_WINDOW_TYPE_OVERNIGHT"
        }
    }

    engine.process_futures_balance_summary_event(event)

    info = manager.get_fee_info()
    assert info["overnight_margin_active"] is True
    assert info["margin_window_type"] == "FCM_MARGIN_WINDOW_TYPE_OVERNIGHT"


def test_order_engine_process_futures_balance_summary_prefers_active_window_type():
    engine = _create_engine_for_unit_tests()
    manager = FeeManager(StubRestClient(), log_callback=lambda *_: None)
    engine.fee_manager = manager

    event = {
        "fcm_balance_summary": {
            "margin_window_type": "FCM_MARGIN_WINDOW_TYPE_INTRADAY",
            "active_margin_window_type": "FCM_MARGIN_WINDOW_TYPE_OVERNIGHT",
        }
    }

    engine.process_futures_balance_summary_event(event)

    info = manager.get_fee_info()
    assert info["overnight_margin_active"] is True
    assert info["margin_window_type"] == "FCM_MARGIN_WINDOW_TYPE_OVERNIGHT"


def test_engine_status_payload_includes_fee_regime_metrics():
    engine = _create_engine_for_unit_tests()
    manager = FeeManager(StubRestClient(), log_callback=lambda *_: None)
    manager.update_margin_window_type("FCM_MARGIN_WINDOW_TYPE_OVERNIGHT")
    for _ in range(10):
        manager.update_volume_signal("BTC-USDC", volume_24h=14400.0)
    engine.fee_manager = manager

    payload = engine._build_engine_status_payload(event_queue_depth=7)

    assert payload["event_queue_depth"] == 7
    assert "target_movement_factor" in payload
    assert "fee_regime_factor" in payload
    assert "overnight_margin_active" in payload
