"""Regression coverage for the canonical exchange-price grid boundary."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

import configuration
from calculation.price_validation import normalize_price_for_product
from calculation.size_validation import validate_and_quantize_size
from core.enums import (
    OrderSide,
    PriceRoundingPolicy,
    RoundingDirection,
)


@pytest.fixture(autouse=True)
def restore_product_metadata():
    original = configuration.get_product_metadata_snapshot()
    try:
        yield
    finally:
        configuration.update_product_metadata(original)


def _install_tick(product_id: str = "TEST-PRODUCT", increment: str = "5") -> None:
    configuration.update_product_metadata(
        {product_id: {"price_increment": increment}}
    )


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
    _install_tick()

    result = normalize_price_for_product(
        77119,
        product_id="TEST-PRODUCT",
        side=side,
        policy=PriceRoundingPolicy.SIDE_CONSERVATIVE,
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
    _install_tick(increment="0.001")

    result = normalize_price_for_product(
        "1.2345",
        product_id="TEST-PRODUCT",
        policy=policy,
    )

    assert result.ok is True
    assert result.effective_price == expected
    assert result.rounding_direction == direction
    assert result.adjusted is True


def test_already_aligned_price_is_not_reported_as_adjusted():
    _install_tick(increment="0.01")

    result = normalize_price_for_product(
        "100.120",
        product_id="TEST-PRODUCT",
        side="BUY",
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
    configuration.update_product_metadata({"TEST-PRODUCT": metadata})

    result = normalize_price_for_product(
        100.12,
        product_id="TEST-PRODUCT",
        side=OrderSide.BUY,
    )

    assert result.ok is False
    assert result.effective_price is None
    assert result.adjusted is False
    assert reason_fragment in result.reason


@pytest.mark.parametrize("price", [None, "bad", "NaN", "Infinity", 0, -1])
def test_invalid_price_fails_closed(price):
    _install_tick(increment="0.01")

    result = normalize_price_for_product(
        price,
        product_id="TEST-PRODUCT",
        side=OrderSide.BUY,
    )

    assert result.ok is False
    assert result.effective_price is None
    assert result.adjusted is False


def test_side_conservative_policy_requires_a_known_side():
    _install_tick()

    result = normalize_price_for_product(
        77119,
        product_id="TEST-PRODUCT",
        side="UNKNOWN",
    )

    assert result.ok is False
    assert result.effective_price is None
    assert "requires side BUY or SELL" in result.reason


def test_metadata_update_preserves_legacy_reference_and_isolates_snapshots():
    legacy_reference = configuration.PRODUCT_METADATA
    source = {"TEST-PRODUCT": {"price_increment": "0.25"}}

    installed = configuration.update_product_metadata(source)
    source["TEST-PRODUCT"]["price_increment"] = "999"
    installed["TEST-PRODUCT"]["price_increment"] = "888"

    assert configuration.PRODUCT_METADATA is legacy_reference
    assert configuration.get_product_metadata("TEST-PRODUCT") == {
        "price_increment": "0.25"
    }

    isolated = configuration.get_product_metadata_snapshot()
    isolated["TEST-PRODUCT"]["price_increment"] = "777"
    assert configuration.get_product_metadata("TEST-PRODUCT")[
        "price_increment"
    ] == "0.25"


def test_accessor_never_observes_a_partially_replaced_catalog():
    catalog_a = {
        f"A-{index}": {"price_increment": "1"} for index in range(25)
    }
    catalog_b = {
        f"B-{index}": {"price_increment": "5"} for index in range(25)
    }
    configuration.update_product_metadata(catalog_a)

    observed = []

    def writer():
        for index in range(100):
            configuration.update_product_metadata(
                catalog_a if index % 2 == 0 else catalog_b
            )

    def reader():
        for _ in range(200):
            observed.append(configuration.get_product_metadata_snapshot())

    with ThreadPoolExecutor(max_workers=2) as executor:
        writer_future = executor.submit(writer)
        reader_future = executor.submit(reader)
        writer_future.result()
        reader_future.result()

    assert observed
    assert all(snapshot == catalog_a or snapshot == catalog_b for snapshot in observed)


def test_size_boundary_never_observes_empty_catalog_during_live_swap():
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
    configuration.update_product_metadata(catalog_a)
    observed_sizes = []

    def writer():
        for index in range(200):
            configuration.update_product_metadata(
                catalog_a if index % 2 == 0 else catalog_b
            )

    def reader():
        for _ in range(400):
            result = validate_and_quantize_size(
                3.5,
                product_id="TEST-PRODUCT",
                price=10,
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

    products_path = tmp_path / "products.json"
    products_path.write_text(
        json.dumps({"ticker_to_trading": {"BTC-USD": "BTC-USDC"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        dashboard_server,
        "__file__",
        str(tmp_path / "dashboard_server.py"),
    )
    monkeypatch.setattr(
        dashboard_server,
        "rest_get_products",
        lambda: {
            "BIP-TEST-CDE": {
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
        },
    )

    result = dashboard_server.update_products_json_from_api()

    assert result["success"] is True
    assert configuration.get_product_metadata("BIP-TEST-CDE")[
        "price_increment"
    ] == "5"
    assert json.loads(products_path.read_text(encoding="utf-8"))["metadata"][
        "BIP-TEST-CDE"
    ]["price_increment"] == "5"
