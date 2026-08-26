"""Regression: fee schedule and cushion must both be product-type aware."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from calculation.fee_manager import FeeManager
from core.enums import ContractExpiryType, ProductType, ProductVenue


_SRC = (
    Path(__file__).resolve().parents[2]
    / "calculation"
    / "fee_manager.py"
).read_text(encoding="utf-8")


class _StubRestClient:
    """Strict client exposing intentionally distinct spot/futures rates."""

    def get_transaction_summary(
        self,
        product_type=None,
        contract_expiry_type=None,
        product_venue=None,
    ):
        if product_type == ProductType.SPOT:
            assert contract_expiry_type is None
            assert product_venue == ProductVenue.CBE
            return deepcopy({
                "fee_tier": {
                    "maker_fee_rate": "0.0040",
                    "taker_fee_rate": "0.0060",
                    "pricing_tier": "spot-test",
                },
                "has_cost_plus_commission": False,
                "has_promo_fee": False,
            })
        if product_type == ProductType.FUTURE:
            assert contract_expiry_type == ContractExpiryType.EXPIRING
            assert product_venue == ProductVenue.FCM
            return deepcopy({
                "fee_tier": {
                    "maker_fee_rate": "0.0004",
                    "taker_fee_rate": "0.0006",
                    "pricing_tier": "future-test",
                },
                "has_cost_plus_commission": True,
                "has_promo_fee": False,
            })
        raise AssertionError(f"unexpected transaction-summary filters: {product_type!r}")


def _make_orderbook(product_type_by_id: dict[str, str]):
    return SimpleNamespace(
        product={
            product_id: {"product_type": product_type}
            for product_id, product_type in product_type_by_id.items()
        }
    )


def _manager(orderbook=None) -> FeeManager:
    manager = FeeManager(
        _StubRestClient(),
        log_callback=lambda *_: None,
        orderbook=orderbook,
    )
    assert manager._refresh_fee_rate() is True
    return manager


@pytest.mark.regression
def test_split_multipliers_are_named_constants():
    assert "FUTURES_FEE_MULTIPLIER" in _SRC
    assert "SPOT_FEE_MULTIPLIER" in _SRC


@pytest.mark.regression
def test_legacy_default_multiplier_alias_preserved():
    assert FeeManager.DEFAULT_MULTIPLIER == FeeManager.SPOT_FEE_MULTIPLIER


@pytest.mark.regression
def test_futures_product_uses_futures_schedule_and_multiplier():
    manager = _manager(
        _make_orderbook({"BIT-29MAY26-CDE": ProductType.FUTURE.value})
    )

    quote = manager.get_profit_validation_fee_quote("BIT-29MAY26-CDE")

    assert quote.product_type == ProductType.FUTURE
    assert quote.exchange_fee_rate == pytest.approx(0.0006)
    assert quote.product_multiplier == FeeManager.FUTURES_FEE_MULTIPLIER
    assert quote.validation_fee_rate == pytest.approx(
        0.0006 * FeeManager.FUTURES_FEE_MULTIPLIER
    )


@pytest.mark.regression
def test_spot_product_uses_spot_schedule_and_multiplier():
    manager = _manager(
        _make_orderbook({"BTC-USD": ProductType.SPOT.value})
    )

    quote = manager.get_profit_validation_fee_quote("BTC-USD")

    assert quote.product_type == ProductType.SPOT
    assert quote.exchange_fee_rate == pytest.approx(0.0060)
    assert quote.product_multiplier == FeeManager.SPOT_FEE_MULTIPLIER
    assert quote.validation_fee_rate == pytest.approx(
        0.0060 * FeeManager.SPOT_FEE_MULTIPLIER
    )


@pytest.mark.regression
@pytest.mark.parametrize("product_id", [None, "DOES-NOT-EXIST"])
def test_unknown_or_missing_product_falls_back_to_spot_schedule(product_id):
    manager = _manager(orderbook=None)

    quote = manager.get_profit_validation_fee_quote(product_id)

    assert quote.product_type == ProductType.SPOT
    assert quote.exchange_fee_rate == pytest.approx(0.0060)
    assert quote.product_multiplier == FeeManager.SPOT_FEE_MULTIPLIER


@pytest.mark.regression
def test_get_fee_info_reports_selected_schedule_and_multiplier():
    manager = _manager(
        _make_orderbook({
            "BIT-29MAY26-CDE": ProductType.FUTURE.value,
            "BTC-USD": ProductType.SPOT.value,
        })
    )

    futures_info = manager.get_fee_info("BIT-29MAY26-CDE")
    spot_info = manager.get_fee_info("BTC-USD")

    assert futures_info["product_type"] == ProductType.FUTURE.value
    assert futures_info["taker_fee_rate"] == pytest.approx(0.0006)
    assert futures_info["multiplier"] == FeeManager.FUTURES_FEE_MULTIPLIER
    assert spot_info["product_type"] == ProductType.SPOT.value
    assert spot_info["taker_fee_rate"] == pytest.approx(0.0060)
    assert spot_info["multiplier"] == FeeManager.SPOT_FEE_MULTIPLIER
    assert (
        futures_info["profit_validation_fee_rate"]
        < spot_info["profit_validation_fee_rate"]
    )
