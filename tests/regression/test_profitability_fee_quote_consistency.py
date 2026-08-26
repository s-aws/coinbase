"""Regression coverage for atomic profitability fee sampling."""

from types import SimpleNamespace

import pytest

from calculation.profit_validator import ProfitValidator
from core.enums import FeeScheduleSource, ProductType


class _QuoteFeeManager:
    def __init__(self) -> None:
        self.quote_calls = 0
        self.rate_calls = 0

    def get_profit_validation_fee_quote(
        self,
        product_id=None,
        post_only=False,
        product_type=None,
    ):
        self.quote_calls += 1
        return SimpleNamespace(
            validation_fee_rate=0.001,
            exchange_fee_rate=0.0009,
            product_type=ProductType.SPOT,
            product_multiplier=1.1,
            raw_fee_regime_factor=0.8,
            applied_fee_regime_factor=1.0,
            pricing_tier="Advanced 8",
            source=FeeScheduleSource.COINBASE,
            has_cost_plus_commission=False,
        )

    def get_profit_validation_fee_rate(
        self,
        product_id=None,
        post_only=False,
        product_type=None,
    ):
        self.rate_calls += 1
        raise AssertionError("atomic quote path must not re-sample the rate")


class _LegacyCountingFeeManager:
    def __init__(self) -> None:
        self.calls = 0

    def get_profit_validation_fee_rate(
        self,
        product_id=None,
        post_only=False,
        product_type=None,
    ):
        self.calls += 1
        return 0.001


@pytest.mark.regression
def test_validate_order_profitability_uses_one_immutable_quote():
    fee_manager = _QuoteFeeManager()
    validator = ProfitValidator(fee_manager=fee_manager)

    result = validator.validate_order_profitability(
        parent_filled_price=100.0,
        parent_side="BUY",
        follow_up_price=101.0,
        order_size=1.0,
        product_type="SPOT",
        product_id="BTC-USDC",
        post_only=False,
    )

    assert fee_manager.quote_calls == 1
    assert fee_manager.rate_calls == 0
    assert result["percentage_fees"] == pytest.approx((100.0 + 101.0) * 0.001)
    assert result["fee_rate_applied"] == pytest.approx(0.001)
    assert result["fee_rate_effective"] == pytest.approx(0.001)
    assert result["exchange_fee_rate"] == pytest.approx(0.0009)
    assert result["liquidity_assumption"] == "taker"
    assert result["fee_validation_factor"] == pytest.approx(1.0)
    assert result["fee_schedule_source"] == "coinbase"


@pytest.mark.regression
def test_legacy_fee_manager_is_sampled_once_per_validation():
    fee_manager = _LegacyCountingFeeManager()
    validator = ProfitValidator(fee_manager=fee_manager)

    result = validator.validate_order_profitability(
        parent_filled_price=100.0,
        parent_side="BUY",
        follow_up_price=101.0,
        order_size=1.0,
        product_type="SPOT",
        product_id="BTC-USDC",
    )

    assert result["is_valid"] is True
    assert fee_manager.calls == 1
