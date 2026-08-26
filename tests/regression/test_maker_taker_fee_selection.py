"""Regression: maker/taker selection is schedule-specific and post-only driven."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from calculation.fee_manager import FeeManager
from core.enums import ContractExpiryType, ProductType, ProductVenue


_FEE_MANAGER_SRC = (
    Path(__file__).resolve().parents[2]
    / "calculation"
    / "fee_manager.py"
).read_text(encoding="utf-8")


def _summary(*, maker: str, taker: str, cost_plus: bool) -> dict:
    return {
        "fee_tier": {
            "maker_fee_rate": maker,
            "taker_fee_rate": taker,
            "pricing_tier": "test-tier",
        },
        "has_cost_plus_commission": cost_plus,
        "has_promo_fee": False,
    }


class _StubRestClientBoth:
    """Strict filtered client returning independently configurable schedules."""

    def __init__(self, maker: str = "0.0004", taker: str = "0.0006"):
        self.spot_summary = _summary(
            maker="0.0040",
            taker="0.0060",
            cost_plus=False,
        )
        self.future_summary = _summary(
            maker=maker,
            taker=taker,
            cost_plus=True,
        )

    def get_transaction_summary(
        self,
        product_type=None,
        contract_expiry_type=None,
        product_venue=None,
    ):
        if product_type == ProductType.SPOT:
            assert contract_expiry_type is None
            assert product_venue == ProductVenue.CBE
            return deepcopy(self.spot_summary)
        if product_type == ProductType.FUTURE:
            assert contract_expiry_type == ContractExpiryType.EXPIRING
            assert product_venue == ProductVenue.FCM
            return deepcopy(self.future_summary)
        raise AssertionError(f"unexpected transaction-summary filters: {product_type!r}")


def _make_orderbook():
    return SimpleNamespace(
        product={
            "BTC-USD": {"product_type": ProductType.SPOT.value},
            "BIT-29MAY26-CDE": {"product_type": ProductType.FUTURE.value},
        }
    )


def _refreshed_manager(client=None) -> FeeManager:
    manager = FeeManager(
        client or _StubRestClientBoth(),
        log_callback=lambda *_: None,
        orderbook=_make_orderbook(),
    )
    assert manager._refresh_fee_rate() is True
    return manager


@pytest.mark.regression
def test_default_maker_constant_exists():
    assert "DEFAULT_MAKER_FEE_RATE" in _FEE_MANAGER_SRC


@pytest.mark.regression
def test_refresh_extracts_both_rates_from_fee_tier():
    assert 'fee_tier.get("maker_fee_rate")' in _FEE_MANAGER_SRC
    assert 'fee_tier.get("taker_fee_rate")' in _FEE_MANAGER_SRC


@pytest.mark.regression
@pytest.mark.parametrize(
    "product_id,expected_maker,expected_taker",
    [
        ("BTC-USD", 0.0040, 0.0060),
        ("BIT-29MAY26-CDE", 0.0004, 0.0006),
    ],
)
def test_maker_is_selected_if_and_only_if_post_only(
    product_id,
    expected_maker,
    expected_taker,
):
    manager = _refreshed_manager()

    default_quote = manager.get_profit_validation_fee_quote(product_id=product_id)
    taker_quote = manager.get_profit_validation_fee_quote(
        product_id=product_id,
        post_only=False,
    )
    maker_quote = manager.get_profit_validation_fee_quote(
        product_id=product_id,
        post_only=True,
    )

    assert default_quote.exchange_fee_rate == pytest.approx(expected_taker)
    assert taker_quote.exchange_fee_rate == pytest.approx(expected_taker)
    assert maker_quote.exchange_fee_rate == pytest.approx(expected_maker)
    assert maker_quote.validation_fee_rate < taker_quote.validation_fee_rate


@pytest.mark.regression
def test_inverted_rates_retain_last_good_schedule():
    client = _StubRestClientBoth(maker="0.0004", taker="0.0006")
    manager = _refreshed_manager(client)
    before = manager.get_fee_schedule_snapshot("BIT-29MAY26-CDE")

    client.future_summary = _summary(
        maker="0.0009",
        taker="0.0006",
        cost_plus=True,
    )

    assert manager._refresh_fee_rate() is False
    after = manager.get_fee_schedule_snapshot("BIT-29MAY26-CDE")
    assert after.maker_fee_rate == before.maker_fee_rate
    assert after.taker_fee_rate == before.taker_fee_rate
    assert after.last_success_at == before.last_success_at
    assert after.consecutive_errors == 1


@pytest.mark.regression
def test_missing_maker_rate_retains_last_good_schedule():
    client = _StubRestClientBoth(maker="0.0004", taker="0.0006")
    manager = _refreshed_manager(client)
    before = manager.get_fee_schedule_snapshot("BIT-29MAY26-CDE")

    client.future_summary = {
        "fee_tier": {
            "taker_fee_rate": "0.0007",
            "pricing_tier": "malformed",
        },
        "has_cost_plus_commission": True,
        "has_promo_fee": False,
    }

    assert manager._refresh_fee_rate() is False
    after = manager.get_fee_schedule_snapshot("BIT-29MAY26-CDE")
    assert after.maker_fee_rate == before.maker_fee_rate
    assert after.taker_fee_rate == before.taker_fee_rate
    assert after.last_success_at == before.last_success_at
    assert after.consecutive_errors == 1
