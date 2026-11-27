"""Regression coverage for the canonical exchange-price grid boundary."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from calculation.price_validation import normalize_price_for_product
from calculation.size_validation import validate_and_quantize_size
from core.enums import (
    OrderSide,
    PriceRoundingPolicy,
    RoundingDirection,
)


def _metadata(increment: str = "5") -> dict[str, str]:
    return {"price_increment": increment}


@pytest.mark.parametrize(
    ("side", "expected", "direction"),
    [
        (OrderSide.BUY, 77115.0, RoundingDirection.DOWN),
        (OrderSide.SELL, 77120.0, RoundingDirection.UP),
    ],
)
def test_side_conservative_normalization_preserves_order_intent(
    side,
    expected,
    direction,
):
    result = normalize_price_for_product(
        77119,
        product_id="TEST-PRODUCT",
        side=side,
        policy=PriceRoundingPolicy.SIDE_CONSERVATIVE,
        product_metadata=_metadata(),
    )

    assert result.ok is True
    assert result.requested_price == 77119.0
    assert result.effective_price == expected
    assert result.increment == "5"
    assert result.policy == PriceRoundingPolicy.SIDE_CONSERVATIVE
    assert result.rounding_direction == direction
    assert result.adjusted is True
    assert result.reason == ""


@pytest.mark.parametrize(
    ("policy", "expected", "direction"),
    [
        (PriceRoundingPolicy.NEAREST, 1.235, RoundingDirection.NEAREST),
        (PriceRoundingPolicy.DOWN, 1.234, RoundingDirection.DOWN),
        (PriceRoundingPolicy.UP, 1.235, RoundingDirection.UP),
    ],
)
def test_explicit_policies_share_decimal_quantization(
    policy,
    expected,
    direction,
):
    result = normalize_price_for_product(
        "1.2345",
        product_id="TEST-PRODUCT",
        policy=policy,
        product_metadata=_metadata("0.001"),
    )

    assert result.ok is True
    assert result.effective_price == expected
    assert result.rounding_direction == direction
    assert result.adjusted is True


def test_already_aligned_price_is_not_reported_as_adjusted():
    result = normalize_price_for_product(
        "100.120",
        product_id="TEST-PRODUCT",
        side="BUY",
        product_metadata=_metadata("0.01"),
    )

    assert result.ok is True
    assert result.effective_price == 100.12
    assert result.adjusted is False


@pytest.mark.parametrize(
    ("metadata", "reason_fragment"),
    [
        ({}, "missing price_increment"),
        ({"price_increment": ""}, "missing price_increment"),
        ({"price_increment": "not-a-number"}, "invalid price_increment"),
        ({"price_increment": "0"}, "invalid price_increment"),
        ({"price_increment": "-0.01"}, "invalid price_increment"),
    ],
)
def test_missing_or_invalid_tick_fails_closed(metadata, reason_fragment):
    result = normalize_price_for_product(
        100.12,
        product_id="TEST-PRODUCT",
        side=OrderSide.BUY,
        product_metadata=metadata,
    )

    assert result.ok is False
    assert result.effective_price is None
    assert result.adjusted is False
    assert reason_fragment in result.reason


@pytest.mark.parametrize("price", [None, "bad", "NaN", "Infinity", 0, -1])
def test_invalid_price_fails_closed(price):
    result = normalize_price_for_product(
        price,
        product_id="TEST-PRODUCT",
        side=OrderSide.BUY,
        product_metadata=_metadata("0.01"),
    )

    assert result.ok is False
    assert result.effective_price is None
    assert result.adjusted is False


def test_side_conservative_policy_requires_a_known_side():
    result = normalize_price_for_product(
        77119,
        product_id="TEST-PRODUCT",
        side="UNKNOWN",
        product_metadata=_metadata(),
    )

    assert result.ok is False
    assert result.effective_price is None
    assert "requires side BUY or SELL" in result.reason


def test_orderbook_catalog_install_isolates_source_and_reader_snapshots():
    from core.orderbook import OrderBook

    source = {"TEST-PRODUCT": {"price_increment": "0.25"}}
    orderbook = OrderBook(products=source)
    source["TEST-PRODUCT"]["price_increment"] = "999"

    isolated = orderbook.get_product_metadata("TEST-PRODUCT")
    isolated["price_increment"] = "777"
    assert orderbook.get_product_metadata("TEST-PRODUCT") == {
        "price_increment": "0.25"
    }


def test_accessor_never_observes_a_partially_replaced_catalog():
    from core.orderbook import OrderBook

    catalog_a = {
        f"A-{index}": {"price_increment": "1"} for index in range(25)
    }
    catalog_b = {
        f"B-{index}": {"price_increment": "5"} for index in range(25)
    }
    orderbook = OrderBook(products=catalog_a)

    observed = []

    def writer():
        for index in range(100):
            orderbook.set_products(
                catalog_a if index % 2 == 0 else catalog_b
            )

    def reader():
        for _ in range(200):
            observed.append(dict(orderbook.products))

    with ThreadPoolExecutor(max_workers=2) as executor:
        writer_future = executor.submit(writer)
        reader_future = executor.submit(reader)
        writer_future.result()
        reader_future.result()

    assert observed
    assert all(snapshot == catalog_a or snapshot == catalog_b for snapshot in observed)


def test_size_boundary_never_observes_empty_catalog_during_live_swap():
    from core.orderbook import OrderBook

    catalog_a = {
        "TEST-PRODUCT": {
            "price_increment": "1",
            "base_increment": "1",
            "base_min_size": "1",
        }
    }
    catalog_b = {
        "TEST-PRODUCT": {
            "price_increment": "5",
            "base_increment": "2",
            "base_min_size": "2",
        }
    }
    orderbook = OrderBook(products=catalog_a)
    observed_sizes = []

    def writer():
        for index in range(200):
            orderbook.set_products(
                catalog_a if index % 2 == 0 else catalog_b
            )

    def reader():
        for _ in range(400):
            result = validate_and_quantize_size(
                3.5,
                product_id="TEST-PRODUCT",
                price=10,
                metadata_reader=orderbook.get_product_metadata,
            )
            assert result.ok
            observed_sizes.append(result.size)

    with ThreadPoolExecutor(max_workers=2) as executor:
        writer_future = executor.submit(writer)
        reader_future = executor.submit(reader)
        writer_future.result()
        reader_future.result()

    assert observed_sizes
    assert set(observed_sizes) <= {2.0, 3.0}


def test_dashboard_product_refresh_replaces_runtime_metadata(monkeypatch, tmp_path):
    import dashboard_server
    from configuration import ProductConfiguration, RuntimeSettings
    from core.orderbook import OrderBook
    from main import _catalog_refresh_callback

    products_path = tmp_path / "products.json"
    products_path.write_text(
        json.dumps({"ticker_to_trading": {"BTC-USD": "BTC-USDC"}}),
        encoding="utf-8",
    )
    product = {
                "product_id": "BIP-TEST-CDE",
                "product_type": "FUTURE",
                "base_currency": "BIP",
                "quote_currency": "USD",
                "base_increment": "1",
                "quote_increment": "0.01",
                "price_increment": "5",
                "base_min_size": "1",
                "quote_min_size": "",
                "trading_disabled": False,
    }

    class FakeRestClient:
        def get_product_dict(self, _product_id):
            return product

    products = ProductConfiguration(
        spot_product_ids=(),
        derivatives_product_ids=("BIP-TEST-CDE",),
        metadata={},
        ticker_to_trading={"BTC-USD": "BTC-USDC"},
        path=products_path,
    )
    settings = RuntimeSettings(
        api_key=None,
        api_secret=None,
        products=products,
        dashboard_host="localhost",
        dashboard_port=8765,
        dashboard_state_publish_interval_seconds=0.25,
        order_post_only={"BUY": False, "SELL": False},
    )
    rest_client = FakeRestClient()
    orderbook = OrderBook()
    dashboard_server.configure_runtime_dependencies(
        rest_client=rest_client,
        orderbook=orderbook,
        product_catalog_refresher=_catalog_refresh_callback(
            rest_client=rest_client,
            settings=settings,
            orderbook=orderbook,
        ),
        state_publish_interval_seconds=0.25,
    )

    result = dashboard_server.update_products_json_from_api()

    assert result["success"] is True
    assert orderbook.get_product_metadata("BIP-TEST-CDE")[
        "price_increment"
    ] == "5"
    assert json.loads(products_path.read_text(encoding="utf-8"))["metadata"][
        "BIP-TEST-CDE"
    ]["price_increment"] == "5"


def test_dashboard_product_refresh_does_not_mutate_runtime_when_cache_write_fails(
    monkeypatch,
    tmp_path,
):
    import main
    from configuration import ProductConfiguration, RuntimeSettings
    from core.orderbook import OrderBook

    product = {
        "product_id": "TEST-USD",
        "product_type": "SPOT",
        "price_increment": "5",
        "trading_disabled": False,
    }

    class FakeRestClient:
        def get_product_dict(self, _product_id):
            return product

    products = ProductConfiguration(
        spot_product_ids=("TEST-USD",),
        derivatives_product_ids=(),
        metadata={},
        ticker_to_trading={},
        path=tmp_path / "products.json",
    )
    settings = RuntimeSettings(
        api_key=None,
        api_secret=None,
        products=products,
        dashboard_host="localhost",
        dashboard_port=8765,
        dashboard_state_publish_interval_seconds=0.25,
        order_post_only={"BUY": False, "SELL": False},
    )
    orderbook = OrderBook(
        products={"TEST-USD": {"price_increment": "0.01"}},
    )

    def fail_persistence(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(
        main,
        "persist_product_configuration",
        fail_persistence,
    )

    refresh = main._catalog_refresh_callback(
        rest_client=FakeRestClient(),
        settings=settings,
        orderbook=orderbook,
    )
    with pytest.raises(OSError, match="disk full"):
        refresh()

    assert orderbook.get_product_metadata("TEST-USD")["price_increment"] == "0.01"
