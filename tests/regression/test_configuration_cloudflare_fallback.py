"""Regression coverage for transient malformed Coinbase gateway responses."""

import logging

import pytest

import configuration
from core.exceptions import CoinbaseAPIError


def test_rest_get_products_rejects_malformed_gateway_response(monkeypatch):
    class MalformedRestClient:
        @staticmethod
        def get_product_dict(_product_id):
            return None

    monkeypatch.setattr(configuration, "REST_CLIENT", MalformedRestClient())
    monkeypatch.setattr(configuration, "DERIVATIVES_PRODUCT_IDS", ["TEST-CDE"])
    monkeypatch.setattr(configuration, "SPOT_PRODUCT_IDS", [])

    with pytest.raises(CoinbaseAPIError, match="malformed product response"):
        configuration.rest_get_products()


def test_orderbook_falls_back_to_cached_products_on_gateway_failure(
    monkeypatch,
    caplog,
):
    monkeypatch.setattr(configuration, "DERIVATIVES_PRODUCT_IDS", [])
    monkeypatch.setattr(configuration, "SPOT_PRODUCT_IDS", ["BTC-USDC"])
    monkeypatch.setattr(
        configuration,
        "PRODUCT_METADATA",
        {
            "BTC-USDC": {
                "type": "SPOT",
                "base_increment": "0.00000001",
                "price_increment": "0.01",
                "trading_disabled": False,
            }
        },
    )

    def unavailable_products():
        raise CoinbaseAPIError("temporary upstream failure", status_code=502)

    def unavailable_positions():
        raise CoinbaseAPIError("temporary upstream failure", status_code=502)

    monkeypatch.setattr(configuration, "rest_get_products", unavailable_products)
    monkeypatch.setattr(configuration, "get_futures_positions", unavailable_positions)

    with caplog.at_level(logging.WARNING):
        orderbook = configuration.OrderBook()

    assert orderbook.product["BTC-USDC"]["product_type"] == "SPOT"
    assert orderbook.product["BTC-USDC"]["price_increment"] == "0.01"
    assert orderbook.positions == {"FUTURE": {}}
    assert "using cached products.json metadata" in caplog.text
    assert "starting with an empty position snapshot" in caplog.text


def test_orderbook_installs_live_catalog_for_canonical_price_reads(monkeypatch):
    live_product = {
        "product_id": "TEST-USD",
        "product_type": "SPOT",
        "base_increment": "0.01",
        "base_min_size": "0.01",
        "quote_min_size": "1",
        "price_increment": "5",
        "trading_disabled": False,
    }
    monkeypatch.setattr(
        configuration,
        "PRODUCT_METADATA",
        {"TEST-USD": {"price_increment": "0.01"}},
    )
    monkeypatch.setattr(
        configuration,
        "rest_get_products",
        lambda: {"TEST-USD": live_product},
    )
    monkeypatch.setattr(configuration, "get_futures_positions", lambda: {})

    orderbook = configuration.OrderBook()

    assert orderbook.product["TEST-USD"]["price_increment"] == "5"
    assert configuration.get_product_metadata("TEST-USD")["price_increment"] == "5"
