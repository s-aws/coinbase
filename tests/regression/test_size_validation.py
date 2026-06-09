"""Regression tests for calculation.size_validation.

The validator is the single chokepoint for size hygiene before an
order leaves the engine. These tests pin:

* Quantize direction defaults to ``"down"`` (never silently inflate).
* Sub-increment sizes are rejected, not rounded to zero silently.
* ``base_min_size`` is enforced when present in product metadata.
* ``quote_min_size`` is enforced when a price is supplied.
* Missing metadata degrades gracefully (no crash, no enforcement).
* Bad inputs (None, NaN, negative) return ``ok=False`` not raise.

Producer/consumer contract: this module reads
``configuration.PRODUCT_METADATA[product_id]`` keys
``base_increment``, ``base_min_size``, ``quote_min_size``. If you
rename any of these, both the dashboard's
``update_products_json_from_api`` populator AND this validator must
move together (P2 rule #12).
"""

from unittest.mock import patch

import pytest

from calculation.size_validation import (
    SizeValidationResult,
    validate_and_quantize_size,
    validate_quote_size,
)


@pytest.fixture
def metadata_btc():
    """Realistic spot product metadata."""
    return {
        "BTC-USDC": {
            "base_increment":  "0.001",
            "base_min_size":   "0.001",
            "quote_min_size":  "10",
            "price_increment": "1",
        }
    }


@pytest.fixture
def metadata_future():
    """Realistic futures product metadata (1-contract increment, no min)."""
    return {
        "BIT-29MAY26-CDE": {
            "base_increment":  "1",
            "base_min_size":   "1",
            "quote_min_size":  "",
            "price_increment": "5",
        }
    }


@pytest.fixture
def metadata_empty():
    """No metadata at all (fresh checkout, dashboard never ran)."""
    return {}


def _patched(metadata: dict):
    return patch("calculation.size_validation.PRODUCT_METADATA", metadata)


def test_valid_size_passes(metadata_btc):
    with _patched(metadata_btc):
        r = validate_and_quantize_size(0.123, product_id="BTC-USDC", price=50_000.0)
    assert r.ok
    assert r.size == 0.123


def test_btc_eight_decimal_precision_preserved():
    """BTC base_increment can be as fine as 1e-8. Decimal-based
    quantize must not drift / shave ticks at that scale (regression
    for the float-modulo bug that turned 0.123 into 0.122)."""
    meta = {
        "BTC-USDC": {
            "base_increment": "0.00000001",
            "base_min_size":  "0.00000001",
            "quote_min_size": "",
        }
    }
    with _patched(meta):
        # An exact 8-decimal value must come back exactly.
        r = validate_and_quantize_size(0.12345678, product_id="BTC-USDC")
    assert r.ok
    assert r.size == 0.12345678

    # A 9-decimal value must snap DOWN to 8 decimals, never inflate.
    with _patched(meta):
        r = validate_and_quantize_size(0.123456789, product_id="BTC-USDC")
    assert r.ok
    assert r.size == 0.12345678


def test_quantize_default_rounds_down(metadata_btc):
    """0.0019 BTC -> 0.001 BTC (snap down to base_increment)."""
    with _patched(metadata_btc):
        r = validate_and_quantize_size(0.0019, product_id="BTC-USDC", price=50_000.0)
    assert r.ok
    assert r.size == pytest.approx(0.001)


def test_sub_increment_size_rejected(metadata_btc):
    """0.0001 BTC quantized down = 0; must be rejected, not silently zeroed."""
    with _patched(metadata_btc):
        r = validate_and_quantize_size(0.0001, product_id="BTC-USDC", price=50_000.0)
    assert not r.ok
    assert "below base_increment" in r.reason


def test_below_base_min_size_rejected():
    """When base_min_size > base_increment (rare but legal), enforce min."""
    meta = {"X-USD": {"base_increment": "0.0001", "base_min_size": "0.01"}}
    with _patched(meta):
        r = validate_and_quantize_size(0.005, product_id="X-USD")
    assert not r.ok
    assert "base_min_size" in r.reason


def test_below_quote_min_size_rejected(metadata_btc):
    """0.001 BTC * $5 = $0.005 notional, well below $10 quote_min_size."""
    with _patched(metadata_btc):
        r = validate_and_quantize_size(0.001, product_id="BTC-USDC", price=5.0)
    assert not r.ok
    assert "quote_min_size" in r.reason


def test_quote_min_size_skipped_when_price_none(metadata_btc):
    """Market orders don't have a known price; only base_min_size applies."""
    with _patched(metadata_btc):
        r = validate_and_quantize_size(0.001, product_id="BTC-USDC", price=None)
    assert r.ok


def test_quote_sized_market_buy_enforces_quote_min_size(metadata_btc):
    with _patched(metadata_btc):
        r = validate_quote_size(5, product_id="BTC-USDC")
    assert not r.ok
    assert "quote_min_size" in r.reason


def test_quote_sized_market_buy_quantizes_quote_increment(metadata_btc):
    metadata_btc["BTC-USDC"]["quote_increment"] = "0.01"
    with _patched(metadata_btc):
        r = validate_quote_size("10.019", product_id="BTC-USDC")
    assert r.ok
    assert r.size == 10.01


def test_futures_whole_contracts(metadata_future):
    with _patched(metadata_future):
        r = validate_and_quantize_size(2.7, product_id="BIT-29MAY26-CDE", price=50_000.0)
    assert r.ok
    assert r.size == 2.0  # snapped down to whole contract


def test_zero_contracts_rejected(metadata_future):
    with _patched(metadata_future):
        r = validate_and_quantize_size(0.5, product_id="BIT-29MAY26-CDE", price=50_000.0)
    assert not r.ok


def test_missing_metadata_degrades_gracefully(metadata_empty):
    """No metadata: no quantize, no enforcement. Must not raise."""
    with _patched(metadata_empty):
        r = validate_and_quantize_size(0.5, product_id="UNKNOWN-USD", price=50_000.0)
    # Still passes the basic > 0 check.
    assert r.ok
    assert r.size == 0.5


def test_none_size_rejected():
    r = validate_and_quantize_size(None, product_id="BTC-USDC")
    assert not r.ok
    assert "None" in r.reason


def test_nan_size_rejected():
    r = validate_and_quantize_size(float("nan"), product_id="BTC-USDC")
    assert not r.ok


def test_negative_size_rejected():
    r = validate_and_quantize_size(-0.5, product_id="BTC-USDC")
    assert not r.ok


def test_non_numeric_size_rejected():
    r = validate_and_quantize_size("not-a-number", product_id="BTC-USDC")
    assert not r.ok
    assert "not numeric" in r.reason


def test_result_is_truthy_only_when_ok():
    assert bool(SizeValidationResult(True, 1.0))
    assert not bool(SizeValidationResult(False, 0.0, "x"))


def test_metadata_keys_match_dashboard_populator():
    """Producer/consumer contract guard. The dashboard's
    ``update_products_json_from_api`` writes these exact keys; the
    validator reads them. If either side renames a key, this guard
    will trip (P2 rule #12)."""
    import inspect
    import dashboard_server

    src = inspect.getsource(dashboard_server.update_products_json_from_api)
    for required_key in ("base_increment", "base_min_size", "quote_min_size"):
        assert f'"{required_key}"' in src, (
            f"dashboard_server.update_products_json_from_api no longer "
            f"writes {required_key!r}; validator will silently degrade."
        )


def test_product_catalog_type_alias_resolves_for_spot_and_futures():
    """products.json stores ``type``; runtime consumers need canonical ProductType values."""
    from configuration import normalize_product_type
    from core.enums import ProductType

    products = {
        "BTC-USD": {"type": "SPOT"},
        "BIP-20DEC30-CDE": {"type": "FUTURE"},
        "ETP-20DEC30-CDE": {"type": "PERPETUAL_FUTURE"},
    }

    assert normalize_product_type({"product_id": "BTC-USD"}, products) == ProductType.SPOT.value
    assert normalize_product_type({"product_id": "BIP-20DEC30-CDE"}, products) == ProductType.FUTURE.value
    assert normalize_product_type({"product_id": "ETP-20DEC30-CDE"}, products) == ProductType.FUTURE.value


def test_calculation_resolver_uses_catalog_type_alias():
    from calculation.resolver import normalize_product_type
    from core.enums import ProductType

    products = {"BIP-20DEC30-CDE": {"type": "FUTURE"}}

    assert normalize_product_type({"product_id": "BIP-20DEC30-CDE"}, products) == ProductType.FUTURE.value


def test_btc_spot_ticker_does_not_remap_to_delisted_usdc_pair():
    """BTC-USD market data must place BTC-USD orders unless the catalog says otherwise."""
    from configuration import get_trading_product_id

    assert get_trading_product_id("BTC-USD") == "BTC-USD"
