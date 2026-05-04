"""Integration test for adaptive follow-up spacing through OrderEngine flow."""

from unittest.mock import Mock

from core.order_engine import OrderEngine
from configuration import OrderBook


def _build_engine_with_mocked_orderbook() -> OrderEngine:
    """Create an OrderEngine with mocked collaborators for integration-style flow tests."""
    orderbook = Mock(spec=OrderBook)
    orderbook.parent_order_ids = {}
    orderbook.child_order_ids = {}
    orderbook.positions = {"FUTURE": {}}
    orderbook.should_replace = {"FILLED": True, "CANCELLED": True}
    orderbook.default_max_order_replacement = 11

    # Product configuration needed by calculate_new_order_move_from_snapshot.
    orderbook.product = {
        "BTC-USDC": {
            "product_id": "BTC-USDC",
            "product_type": "SPOT",
            "base_increment": "0.00000001",
            "quote_increment": "0.01",
            "price_increment": "0.01",
        }
    }

    # Base fallback profit config.
    orderbook.profit = {
        "SPOT": {"BUY": 0.001, "SELL": 0.001},
        "BTC-USDC": {"BUY": 0.001, "SELL": 0.001},
    }
    orderbook.mandatory_fee_per_contract = {"BTC-USDC": {"mandatory_fee_per_contract": 0.0}}

    # Mock the v2 ``diagnostic_snapshot`` method to return a dict assembled
    # from the attributes above.  ``compute_order_template`` (and friends) now
    # call this method instead of reading attributes individually.
    orderbook.diagnostic_snapshot.side_effect = lambda: {
        "order": orderbook.order,
        "positions": orderbook.positions,
        "product": orderbook.product,
        "profit": orderbook.profit,
        "mandatory_fee_per_contract": orderbook.mandatory_fee_per_contract,
        "parent_order_ids": orderbook.parent_order_ids,
        "child_order_ids": orderbook.child_order_ids,
    }

    # FILLED BUY parent order used for follow-up template computation.
    parent_client_order_id = "parent-btc-1"
    orderbook.order = {
        parent_client_order_id: {
            "client_order_id": parent_client_order_id,
            "product_id": "BTC-USDC",
            "product_type": "SPOT",
            "status": "FILLED",
            "order_side": "BUY",
            "filled_size": "1.0",
            "limit_price": "100.00",
            "avg_price": "100.00",
        }
    }

    # Parent target movement source of truth.
    orderbook.parent_order_ids[parent_client_order_id] = {
        "orders": [],
        "target_movement": {"type": "P", "movement": 0.01},
        "max_order_replacement": 11,
        "current_order_replacement": 0,
    }

    db_module = Mock()
    db_module.DB_CLIENT = Mock()

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


def _extract_price_diff(order_template: dict) -> float:
    """Get absolute order price difference as float from order template payload."""
    return float(order_template["order_price_difference"])


def test_follow_up_spacing_adapts_to_volume_and_overnight_margin():
    """Follow-up spacing should widen on high volume and tighten overnight/low volume."""
    engine = _build_engine_with_mocked_orderbook()
    parent_id = "parent-btc-1"

    # Baseline spacing from current parent target movement path.
    baseline_target = engine.resolve_parent_target_movement(parent_id)
    baseline_template = engine.compute_order_template(parent_id, target_movement=baseline_target)
    baseline_diff = _extract_price_diff(baseline_template)

    # Build a stable baseline volume, then push high-volume regime.
    for _ in range(30):
        engine.fee_manager.update_volume_signal("BTC-USDC", volume_24h=144000.0)
    for _ in range(20):
        engine.fee_manager.update_volume_signal("BTC-USDC", volume_24h=1440000.0)

    high_target = engine.resolve_parent_target_movement(parent_id)
    high_template = engine.compute_order_template(parent_id, target_movement=high_target)
    high_diff = _extract_price_diff(high_template)

    assert high_target["movement"] > baseline_target["movement"]
    assert high_diff > baseline_diff

    # Switch to overnight margin and push low-volume regime.
    engine.process_futures_balance_summary_event({
        "fcm_balance_summary": {
            "margin_window_type": "FCM_MARGIN_WINDOW_TYPE_OVERNIGHT"
        }
    })
    for _ in range(40):
        engine.fee_manager.update_volume_signal("BTC-USDC", volume_24h=14400.0)

    low_target = engine.resolve_parent_target_movement(parent_id)
    low_template = engine.compute_order_template(parent_id, target_movement=low_target)
    low_diff = _extract_price_diff(low_template)

    assert low_target["movement"] < baseline_target["movement"]
    assert low_diff < baseline_diff
