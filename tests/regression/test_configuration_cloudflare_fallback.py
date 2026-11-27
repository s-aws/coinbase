"""Regression coverage for transient malformed Coinbase gateway responses."""

import logging

import pytest

import main
from configuration import ProductConfiguration
from core.exceptions import CoinbaseAPIError
from core.orderbook import OrderBook
from external.runtime import fetch_products


def _product_configuration(tmp_path, *, metadata):
    return ProductConfiguration(
        spot_product_ids=("BTC-USDC",),
        derivatives_product_ids=(),
        metadata=metadata,
        ticker_to_trading={},
        path=tmp_path / "products.json",
    )


def test_rest_get_products_rejects_malformed_gateway_response():
    class MalformedRestClient:
        @staticmethod
        def get_product_dict(_product_id):
            return None

    with pytest.raises(CoinbaseAPIError, match="malformed product response"):
        fetch_products(MalformedRestClient(), ("TEST-CDE",))


def test_composition_falls_back_to_cached_products_on_gateway_failure(
    tmp_path,
    caplog,
):
    settings = _product_configuration(
        tmp_path,
        metadata={
            "BTC-USDC": {
                "type": "SPOT",
                "base_increment": "0.00000001",
                "price_increment": "0.01",
                "trading_disabled": False,
            }
        },
    )

    class UnavailableRestClient:
        @staticmethod
        def get_product_dict(_product_id):
            raise CoinbaseAPIError("temporary upstream failure", status_code=502)

        @staticmethod
        def list_futures_positions():
            raise CoinbaseAPIError("temporary upstream failure", status_code=502)

    rest_client = UnavailableRestClient()
    with caplog.at_level(logging.WARNING):
        products = main._load_startup_products(rest_client, settings)
        positions = main._load_startup_positions(rest_client)

    orderbook = OrderBook(products=products, positions={"FUTURE": positions})
    assert orderbook.product["BTC-USDC"]["product_type"] == "SPOT"
    assert orderbook.get_product_metadata("BTC-USDC")["price_increment"] == "0.01"
    assert orderbook.positions == {"FUTURE": {}}
    assert "using cached products.json metadata" in caplog.text
    assert "starting with an empty position snapshot" in caplog.text


def test_composition_installs_live_catalog_for_canonical_price_reads(tmp_path):
    live_product = {
        "product_id": "BTC-USDC",
        "product_type": "SPOT",
        "base_increment": "0.01",
        "base_min_size": "0.01",
        "quote_min_size": "1",
        "price_increment": "5",
        "trading_disabled": False,
    }
    settings = _product_configuration(
        tmp_path,
        metadata={"BTC-USDC": {"price_increment": "0.01"}},
    )

    class LiveRestClient:
        @staticmethod
        def get_product_dict(_product_id):
            return live_product

    products = main._load_startup_products(LiveRestClient(), settings)
    orderbook = OrderBook(products=products)

    assert orderbook.product["BTC-USDC"]["price_increment"] == "5"
    assert orderbook.get_product_metadata("BTC-USDC")["price_increment"] == "5"
