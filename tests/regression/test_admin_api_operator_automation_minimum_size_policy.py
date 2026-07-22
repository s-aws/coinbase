from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from application.admin_api.operator_spot_minimum_size_policy import (
    MinimumSizePolicyBlocked,
    derive_minimum_size_buy_plan,
)


NOW = datetime(2026, 7, 22, 2, 0, tzinfo=timezone.utc)


def _derive(**overrides):
    values = {
        "product_id": "BTC-USDC",
        "best_bid": "100000.00",
        "best_ask": "100000.01",
        "market_observed_at": NOW,
        "evaluated_at": NOW,
        "base_increment": "0.00000001",
        "quote_increment": "0.01",
        "price_increment": "0.01",
        "base_min_size": "0.00000001",
        "quote_min_size": "1.00",
        "available_usdc": "10.00",
        "maker_fee_rate": "0.006",
    }
    values.update(overrides)
    return derive_minimum_size_buy_plan(**values)


def test_derives_smallest_fee_reserved_cap_and_localizes_v4_fee_conflict():
    plan = _derive()

    assert plan.policy_revision == "BTC_USDC_POST_ONLY_BEST_BID_MINIMUM_SIZE_V2"
    assert plan.base_size == "0.00001"
    assert plan.limit_price == "100000"
    assert plan.submitted_notional_usdc == "1"
    assert plan.possible_execution_notional_usdc == "1"
    assert plan.max_submitted_notional_usdc == "3.10"
    assert plan.max_possible_execution_notional_usdc == "1.01"
    assert plan.v4_boundary_classification == "minimum_size_v4_fee_reserve_conflict"
    assert plan.post_only is True


@pytest.mark.parametrize(
    ("overrides", "classification", "base_size", "submitted"),
    [
        (
            {"base_min_size": "0.00002"},
            "minimum_size_v4_base_minimum_conflict",
            "0.00002",
            "2",
        ),
        (
            {"quote_min_size": "1.50"},
            "minimum_size_v4_quote_minimum_conflict",
            "0.000015",
            "1.5",
        ),
        (
            {
                "best_bid": "200000.00",
                "best_ask": "200000.01",
                "base_increment": "0.000006",
            },
            "minimum_size_v4_increment_conflict",
            "0.000006",
            "1.2",
        ),
    ],
)
def test_localizes_product_and_increment_conflicts(
    overrides,
    classification,
    base_size,
    submitted,
):
    plan = _derive(**overrides)

    assert plan.v4_boundary_classification == classification
    assert plan.base_size == base_size
    assert plan.submitted_notional_usdc == submitted
    assert Decimal(plan.max_possible_execution_notional_usdc) < Decimal("3.10")


def test_reports_when_the_v4_boundary_is_not_reproduced():
    plan = _derive(quote_min_size="0.50", maker_fee_rate="0")

    assert plan.v4_boundary_classification == "minimum_size_v4_boundary_not_reproduced"
    assert plan.max_possible_execution_notional_usdc == "0.5"


def test_requires_wallet_to_cover_the_rounded_fee_reserved_cap():
    with pytest.raises(
        MinimumSizePolicyBlocked,
        match="^minimum_size_wallet_insufficient$",
    ):
        _derive(available_usdc="1.005", maker_fee_rate="0.004")


def test_zero_maker_fee_accepts_an_exact_one_usdc_wallet_and_cap():
    plan = _derive(available_usdc="1.00", maker_fee_rate="0")

    assert plan.submitted_notional_usdc == "1"
    assert plan.max_possible_execution_notional_usdc == "1"


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"available_usdc": "0.50"}, "minimum_size_wallet_insufficient"),
        ({"quote_min_size": "3.10"}, "minimum_size_submitted_cap_conflict"),
        (
            {"quote_min_size": "3.05", "maker_fee_rate": "0.02"},
            "minimum_size_fee_reserve_cap_conflict",
        ),
        (
            {"market_observed_at": NOW - timedelta(seconds=31)},
            "minimum_size_snapshot_stale",
        ),
        (
            {"market_observed_at": NOW + timedelta(seconds=2)},
            "minimum_size_snapshot_future",
        ),
        (
            {"base_increment": "0"},
            "minimum_size_product_metadata_invalid",
        ),
    ],
)
def test_blocks_with_one_fixed_value_blind_reason(overrides, code):
    with pytest.raises(MinimumSizePolicyBlocked, match=f"^{code}$"):
        _derive(**overrides)
