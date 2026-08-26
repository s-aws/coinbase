"""Regression contract for filtered, isolated Coinbase fee schedules."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from calculation.fee_manager import FeeManager
from calculation.profit_validator import ProfitValidator
from core.enums import (
    ContractExpiryType,
    FeeScheduleSource,
    LiquidityAssumption,
    ProductType,
    ProductVenue,
)


SPOT_PRODUCT_ID = "BTC-USD"
FUTURE_PRODUCT_ID = "BIP-20DEC30-CDE"


def _summary(
    *,
    maker: str,
    taker: str,
    pricing_tier: str,
    cost_plus: bool,
) -> dict:
    return {
        "fee_tier": {
            "maker_fee_rate": maker,
            "taker_fee_rate": taker,
            "pricing_tier": pricing_tier,
        },
        "has_cost_plus_commission": cost_plus,
        "has_promo_fee": False,
    }


def _valid_spot_summary(maker="0.0004", taker="0.00085"):
    return _summary(
        maker=maker,
        taker=taker,
        pricing_tier="VIP 3",
        cost_plus=False,
    )


def _valid_future_summary(maker="0.00025", taker="0.0003"):
    return _summary(
        maker=maker,
        taker=taker,
        pricing_tier="Advanced 8",
        cost_plus=True,
    )


class _ScriptedRestClient:
    """Strict fake whose outcomes can change independently by schedule."""

    def __init__(self):
        self.outcomes = {
            ProductType.SPOT: _valid_spot_summary(),
            ProductType.FUTURE: _valid_future_summary(),
        }
        self.calls = []

    def get_transaction_summary(
        self,
        product_type=None,
        contract_expiry_type=None,
        product_venue=None,
    ):
        call = {
            "product_type": product_type,
            "product_venue": product_venue,
        }
        if contract_expiry_type is not None:
            call["contract_expiry_type"] = contract_expiry_type
        self.calls.append(call)

        if product_type == ProductType.SPOT:
            assert product_venue == ProductVenue.CBE
            assert contract_expiry_type is None
        elif product_type == ProductType.FUTURE:
            assert product_venue == ProductVenue.FCM
            assert contract_expiry_type == ContractExpiryType.EXPIRING
        else:
            raise AssertionError(f"unexpected product_type: {product_type!r}")

        outcome = self.outcomes[product_type]
        if isinstance(outcome, BaseException):
            raise outcome
        return deepcopy(outcome)


def _orderbook():
    return SimpleNamespace(
        product={
            SPOT_PRODUCT_ID: {"product_type": ProductType.SPOT.value},
            FUTURE_PRODUCT_ID: {"product_type": ProductType.FUTURE.value},
        }
    )


def _manager(client=None):
    client = client or _ScriptedRestClient()
    manager = FeeManager(
        client,
        log_callback=lambda *_: None,
        orderbook=_orderbook(),
    )
    return manager, client


@pytest.mark.regression
def test_refresh_uses_exact_filters_and_keeps_distinct_schedules():
    manager, client = _manager()

    assert manager._refresh_fee_rate() is True

    assert client.calls == [
        {
            "product_type": ProductType.SPOT,
            "product_venue": ProductVenue.CBE,
        },
        {
            "product_type": ProductType.FUTURE,
            "product_venue": ProductVenue.FCM,
            "contract_expiry_type": ContractExpiryType.EXPIRING,
        },
    ]
    spot = manager.get_fee_schedule_snapshot(SPOT_PRODUCT_ID)
    future = manager.get_fee_schedule_snapshot(FUTURE_PRODUCT_ID)
    assert spot.product_type == ProductType.SPOT
    assert spot.product_venue == ProductVenue.CBE
    assert spot.contract_expiry_type is None
    assert spot.maker_fee_rate == pytest.approx(0.0004)
    assert spot.taker_fee_rate == pytest.approx(0.00085)
    assert spot.has_cost_plus_commission is False
    assert future.product_type == ProductType.FUTURE
    assert future.product_venue == ProductVenue.FCM
    assert future.contract_expiry_type == ContractExpiryType.EXPIRING
    assert future.maker_fee_rate == pytest.approx(0.00025)
    assert future.taker_fee_rate == pytest.approx(0.0003)
    assert future.has_cost_plus_commission is True


@pytest.mark.regression
@pytest.mark.parametrize(
    "product_id,expected_maker,expected_taker",
    [
        (SPOT_PRODUCT_ID, 0.0004, 0.00085),
        (FUTURE_PRODUCT_ID, 0.00025, 0.0003),
    ],
)
def test_maker_selected_if_and_only_if_post_only(
    product_id,
    expected_maker,
    expected_taker,
):
    manager, _ = _manager()
    assert manager._refresh_fee_rate() is True

    maker = manager.get_profit_validation_fee_quote(product_id, post_only=True)
    taker = manager.get_profit_validation_fee_quote(product_id, post_only=False)
    default = manager.get_profit_validation_fee_quote(product_id)

    assert maker.liquidity_assumption == LiquidityAssumption.MAKER
    assert maker.exchange_fee_rate == pytest.approx(expected_maker)
    assert taker.liquidity_assumption == LiquidityAssumption.TAKER
    assert taker.exchange_fee_rate == pytest.approx(expected_taker)
    assert default.liquidity_assumption == LiquidityAssumption.TAKER
    assert default.exchange_fee_rate == pytest.approx(expected_taker)


@pytest.mark.regression
@pytest.mark.parametrize("product_id", [None, "LOCAL-FUTURE-ALIAS"])
def test_explicit_future_hint_selects_one_coherent_fcm_quote(product_id):
    manager, _ = _manager()
    assert manager._refresh_fee_rate() is True

    result = ProfitValidator(fee_manager=manager).validate_order_profitability(
        parent_filled_price=100.0,
        parent_side="BUY",
        follow_up_price=101.0,
        order_size=1.0,
        product_type=ProductType.FUTURE.value,
        product_id=product_id,
        contract_size=0.01,
        post_only=False,
    )

    assert result["fee_product_type"] == ProductType.FUTURE.value
    assert result["exchange_fee_rate"] == pytest.approx(0.0003)
    assert result["fee_product_multiplier"] == pytest.approx(
        manager.FUTURES_FEE_MULTIPLIER
    )
    assert result["fee_has_cost_plus_commission"] is True


@pytest.mark.regression
def test_explicit_spot_hint_wins_over_future_suffix():
    manager, _ = _manager()
    assert manager._refresh_fee_rate() is True

    quote = manager.get_profit_validation_fee_quote(
        product_id="LOCAL-SPOT-CDE",
        product_type=ProductType.SPOT.value,
    )

    assert quote.product_type is ProductType.SPOT
    assert quote.exchange_fee_rate == pytest.approx(0.00085)
    assert quote.product_multiplier == pytest.approx(manager.SPOT_FEE_MULTIPLIER)


@pytest.mark.regression
@pytest.mark.parametrize(
    "malformed_future",
    [
        {
            "fee_tier": {
                "maker_fee_rate": "0.0004",
                "taker_fee_rate": "not-a-rate",
            },
            "has_cost_plus_commission": True,
        },
        {
            "fee_tier": {
                "maker_fee_rate": "0.0007",
                "taker_fee_rate": "0.0006",
            },
            "has_cost_plus_commission": True,
        },
        {
            "fee_tier": {"taker_fee_rate": "0.0006"},
            "has_cost_plus_commission": True,
        },
        {
            "fee_tier": {"maker_fee_rate": "0.0004"},
            "has_cost_plus_commission": True,
        },
    ],
)
def test_malformed_inverted_or_missing_rates_retain_last_good(malformed_future):
    manager, client = _manager()
    assert manager._refresh_fee_rate() is True
    before = manager.get_fee_schedule_snapshot(FUTURE_PRODUCT_ID)

    client.outcomes[ProductType.FUTURE] = malformed_future

    assert manager._refresh_fee_rate() is False
    after = manager.get_fee_schedule_snapshot(FUTURE_PRODUCT_ID)
    assert after.maker_fee_rate == before.maker_fee_rate
    assert after.taker_fee_rate == before.taker_fee_rate
    assert after.pricing_tier == before.pricing_tier
    assert after.source == FeeScheduleSource.COINBASE
    assert after.last_success_at == before.last_success_at
    assert after.consecutive_errors == 1
    assert after.last_error


@pytest.mark.regression
@pytest.mark.parametrize("failed_type", [ProductType.SPOT, ProductType.FUTURE])
def test_partial_refresh_failure_is_isolated_to_failed_schedule(failed_type):
    manager, client = _manager()
    assert manager._refresh_fee_rate() is True
    old_spot = manager.get_fee_schedule_snapshot(SPOT_PRODUCT_ID)
    old_future = manager.get_fee_schedule_snapshot(FUTURE_PRODUCT_ID)

    client.outcomes[ProductType.SPOT] = _valid_spot_summary(
        maker="0.0005",
        taker="0.0009",
    )
    client.outcomes[ProductType.FUTURE] = _valid_future_summary(
        maker="0.0003",
        taker="0.0004",
    )
    client.outcomes[failed_type] = RuntimeError(f"{failed_type.value} unavailable")

    assert manager._refresh_fee_rate() is False
    new_spot = manager.get_fee_schedule_snapshot(SPOT_PRODUCT_ID)
    new_future = manager.get_fee_schedule_snapshot(FUTURE_PRODUCT_ID)

    if failed_type == ProductType.SPOT:
        assert new_spot.maker_fee_rate == old_spot.maker_fee_rate
        assert new_spot.taker_fee_rate == old_spot.taker_fee_rate
        assert new_spot.consecutive_errors == 1
        assert new_future.maker_fee_rate == pytest.approx(0.0003)
        assert new_future.taker_fee_rate == pytest.approx(0.0004)
        assert new_future.consecutive_errors == 0
    else:
        assert new_future.maker_fee_rate == old_future.maker_fee_rate
        assert new_future.taker_fee_rate == old_future.taker_fee_rate
        assert new_future.consecutive_errors == 1
        assert new_spot.maker_fee_rate == pytest.approx(0.0005)
        assert new_spot.taker_fee_rate == pytest.approx(0.0009)
        assert new_spot.consecutive_errors == 0


@pytest.mark.regression
def test_future_without_cost_plus_confirmation_retains_last_good():
    manager, client = _manager()
    assert manager._refresh_fee_rate() is True
    before = manager.get_fee_schedule_snapshot(FUTURE_PRODUCT_ID)
    client.outcomes[ProductType.FUTURE] = _summary(
        maker="0.0002",
        taker="0.00025",
        pricing_tier="unconfirmed",
        cost_plus=False,
    )

    assert manager._refresh_fee_rate() is False
    after = manager.get_fee_schedule_snapshot(FUTURE_PRODUCT_ID)
    assert after.maker_fee_rate == before.maker_fee_rate
    assert after.taker_fee_rate == before.taker_fee_rate
    assert after.last_success_at == before.last_success_at
    assert after.consecutive_errors == 1


@pytest.mark.regression
def test_fee_quote_is_immutable():
    manager, _ = _manager()
    assert manager._refresh_fee_rate() is True
    quote = manager.get_profit_validation_fee_quote(FUTURE_PRODUCT_ID)

    with pytest.raises(FrozenInstanceError):
        quote.exchange_fee_rate = 1.0
