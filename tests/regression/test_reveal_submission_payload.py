"""Regression tests for stealth reveal submission payload construction."""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from core.enums import OrderSide
from core.models import RevealExecutionPlan
from core.stealth_order_manager import StealthOrderManager


@pytest.mark.regression
def test_reveal_submission_payload_preserves_plan_and_order_context():
    manager = StealthOrderManager(db_client=None, log_callback=MagicMock())
    confirmed_at = datetime(2026, 6, 10, 12, 34, 56)
    order = {
        "stealth_order_id": "stealth-root",
        "product_id": "BTC-USDC",
        "side": OrderSide.BUY.value,
        "parent_order_id": "root-parent",
        "reason": "entry",
        "revealed_orders": [{"reveal_number": 1}, {"reveal_number": 2}],
        "reveal_condition_type": "price_threshold",
        "reveal_condition_json": {
            "type": "price_threshold",
            "price_threshold": 100.0,
            "direction": "below",
        },
        "condition_confirmed_at": confirmed_at,
    }
    reveal_plan = RevealExecutionPlan(
        configured_limit_price=100.0,
        submitted_limit_price=99.5,
        reveal_pricing_policy="top_of_book",
        reveal_price_source="ticker_best_bid",
        fallback_used=False,
        post_only=True,
    )

    payload = manager._build_reveal_order_submission_payload(
        order=order,
        stealth_order_id="stealth-root",
        reveal_plan=reveal_plan,
        slice_size=0.01,
        client_order_id="placement-client-id",
    )

    assert payload == {
        "product_id": "BTC-USDC",
        "side": OrderSide.BUY.value,
        "limit_price": 99.5,
        "base_size": 0.01,
        "client_order_id": "placement-client-id",
        "post_only": True,
        "stealth_order_id": "stealth-root",
        "parent_order_id": "root-parent",
        "reason": "entry",
        "reveal_number": 3,
        "reveal_condition_type": "price_threshold",
        "reveal_condition_json": {
            "type": "price_threshold",
            "price_threshold": 100.0,
            "direction": "below",
        },
        "condition_confirmed_at": confirmed_at.isoformat(),
        "reveal_pricing_policy": "top_of_book",
        "reveal_price_source": "ticker_best_bid",
    }
