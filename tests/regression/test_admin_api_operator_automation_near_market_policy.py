from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from application.admin_api.operator_spot_near_market_policy import (
    NEAR_MARKET_POLICY_REVISION,
    NearMarketPolicyBlocked,
    derive_near_market_buy_plan,
    evaluate_near_market_post_only_limit,
)


NOW = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)


def _derive(**overrides: object):
    values: dict[str, object] = {
        "product_id": "BTC-USDC",
        "best_bid": "65000.123",
        "best_ask": "65000.13",
        "market_observed_at": NOW - timedelta(seconds=2),
        "evaluated_at": NOW,
        "base_increment": "0.00000001",
        "price_increment": "0.01",
        "base_min_size": "0.00000001",
        "quote_min_size": "0.01",
        "available_usdc": "2.00",
        "maker_fee_rate": "0.004",
    }
    values.update(overrides)
    return derive_near_market_buy_plan(**values)


def test_near_market_policy_derives_quantized_post_only_plan_with_caps() -> None:
    plan = _derive()

    assert plan.policy_revision == NEAR_MARKET_POLICY_REVISION
    assert plan.product_id == "BTC-USDC"
    assert plan.side == "BUY"
    assert plan.limit_price == "65000.12"
    assert Decimal(plan.base_size) % Decimal("0.00000001") == 0
    assert plan.post_only is True
    assert Decimal(plan.submitted_notional_usdc) == (
        Decimal(plan.base_size) * Decimal(plan.limit_price)
    )
    assert Decimal(plan.submitted_notional_usdc) <= Decimal("1.00")
    assert Decimal(plan.possible_execution_notional_usdc) == Decimal(
        plan.submitted_notional_usdc
    )
    assert Decimal(plan.submitted_notional_usdc) * Decimal("1.004") <= Decimal(
        "2.00"
    )
    assert plan.max_submitted_notional_usdc == "3.10"
    assert plan.max_possible_execution_notional_usdc == "1.00"


def test_near_market_standing_rule_is_narrow_and_does_not_use_fifty_percent_guard() -> None:
    evidence = evaluate_near_market_post_only_limit(
        side="BUY",
        limit_price="99999.99",
        post_only=True,
        best_bid="100000.00",
        best_ask="100000.01",
        market_source="coinbase_rest_market_trade_snapshot",
    )
    assert evidence["allowed"] is True
    assert evidence["policy"] == "BTC_USDC_POST_ONLY_BEST_BID_V1"

    for changed in (
        {"post_only": False},
        {"limit_price": "100000.01"},
        {"market_source": "coinbase_rest_best_bid"},
    ):
        rejected = evaluate_near_market_post_only_limit(
            side="BUY",
            limit_price=changed.get("limit_price", "100000.00"),
            post_only=changed.get("post_only", True),
            best_bid="100000.00",
            best_ask="100000.01",
            market_source=changed.get(
                "market_source",
                "coinbase_rest_market_trade_snapshot",
            ),
        )
        assert rejected["allowed"] is False


def test_near_market_policy_uses_wallet_after_maker_fee_reserve() -> None:
    plan = _derive(available_usdc="0.50", maker_fee_rate="0.01")

    notional = Decimal(plan.submitted_notional_usdc)
    assert notional * Decimal("1.01") <= Decimal("0.50")
    assert notional <= Decimal("1.00")


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"product_id": "ETH-USDC"}, "near_market_product_blocked"),
        (
            {"market_observed_at": NOW - timedelta(seconds=31)},
            "near_market_snapshot_stale",
        ),
        (
            {"market_observed_at": NOW + timedelta(seconds=2)},
            "near_market_snapshot_future",
        ),
        (
            {"best_bid": "65000.12", "best_ask": "65000.12"},
            "near_market_post_only_crossing",
        ),
        ({"price_increment": "0"}, "near_market_product_metadata_invalid"),
        ({"available_usdc": "0"}, "near_market_wallet_insufficient"),
        (
            {"base_min_size": "0.0001", "available_usdc": "1.00"},
            "near_market_no_valid_size",
        ),
        (
            {"quote_min_size": "1.01", "available_usdc": "5.00"},
            "near_market_no_valid_size",
        ),
    ],
)
def test_near_market_policy_fails_closed(
    overrides: dict[str, object],
    code: str,
) -> None:
    with pytest.raises(NearMarketPolicyBlocked, match=f"^{code}$"):
        _derive(**overrides)
