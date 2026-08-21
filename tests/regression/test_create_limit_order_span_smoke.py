"""Smoke tests for ``order.create_limit_order_span``.

This function had two bugs that survived for an unknown amount of
time because no test imported it:

1. ``from datetime import dateeffective_time as dt`` — corrupted
   import from a botched search/replace, would raise ImportError
   on the first call.
2. The camouflage block computed ``effective_start_price`` but the
   ``create_stealth_order`` call still passed ``start_price``,
   silently disabling the camouflage feature for this code path.

These tests pin the wire-up so future regressions surface
immediately:

* The function is importable and callable.
* The stealth bridge is invoked with the camouflaged price (when
  ``camouflage_round_numbers=True``), not the raw input price.
* The returned response dict echoes the camouflaged price too.
* The default path (no camouflage) preserves an already aligned price.
* Off-grid prices are side-conservatively normalized before the bridge and
  the returned response reports that same effective price.
* Bridge errors propagate as the documented ``error_response``
  shape, not as raw exceptions.
"""

from unittest.mock import MagicMock, patch

import pytest

import order as order_module
from order import create_limit_order_span


@pytest.fixture(autouse=True)
def canonical_product_metadata():
    with patch(
        "calculation.price_validation.get_product_metadata",
        return_value={"price_increment": "1"},
    ):
        yield


@pytest.fixture
def fake_bridge():
    bridge = MagicMock()
    bridge.create_stealth_order.return_value = "fake-stealth-uuid"
    return bridge


def test_smoke_default_path_does_not_explode(fake_bridge):
    """If this test fails with ImportError, the most likely cause is
    another corrupted ``from datetime import ...`` line."""
    with patch.object(order_module, "get_stealth_order_bridge", return_value=fake_bridge):
        result = create_limit_order_span(
            product_id="BTC-USDC",
            side="BUY",
            order_base_size=0.5,
            start_price=42_000.0,
            max_order_count=1,
        )
    assert isinstance(result, list) and len(result) == 1
    assert result[0]["success"] is True
    fake_bridge.create_stealth_order.assert_called_once()


def test_no_camouflage_passes_raw_price(fake_bridge):
    """``camouflage_round_numbers=False`` (the default) MUST pass the
    already aligned start_price through unchanged."""
    with patch.object(order_module, "get_stealth_order_bridge", return_value=fake_bridge):
        create_limit_order_span(
            product_id="BTC-USDC",
            side="SELL",
            order_base_size=0.5,
            start_price=42_000.0,
            max_order_count=1,
            camouflage_round_numbers=False,
        )
    kwargs = fake_bridge.create_stealth_order.call_args.kwargs
    assert kwargs["limit_price"] == 42_000.0


@pytest.mark.parametrize(
    ("side", "expected_price"),
    (("BUY", 42_015.0), ("SELL", 42_020.0)),
)
def test_off_grid_price_is_normalized_before_bridge_and_response(
    fake_bridge,
    side,
    expected_price,
):
    with patch.object(order_module, "get_stealth_order_bridge", return_value=fake_bridge), \
         patch(
             "calculation.price_validation.get_product_metadata",
             return_value={"price_increment": "5"},
         ):
        result = create_limit_order_span(
            product_id="BTC-USDC",
            side=side,
            order_base_size=0.5,
            start_price=42_019.0,
            max_order_count=1,
        )

    sent_price = fake_bridge.create_stealth_order.call_args.kwargs["limit_price"]
    assert sent_price == expected_price
    assert result[0]["success_response"]["price"] == str(expected_price)


def test_camouflage_actually_shifts_price(fake_bridge):
    """Regression for the dead-code bug: the camouflage block
    computed ``effective_start_price`` but the bridge call still
    received the raw ``start_price``. With the fix, opting in must
    move the price off the magnet."""
    fake_metadata = {"BTC-USDC": {"price_increment": "1"}}
    with patch.object(order_module, "get_stealth_order_bridge", return_value=fake_bridge), \
         patch("configuration.PRODUCT_METADATA", fake_metadata):
        create_limit_order_span(
            product_id="BTC-USDC",
            side="SELL",
            order_base_size=0.5,
            start_price=42_000.0,  # exact magnet number
            max_order_count=1,
            camouflage_round_numbers=True,
        )
    kwargs = fake_bridge.create_stealth_order.call_args.kwargs
    # camouflage moves the price by at least one tick off the magnet.
    assert kwargs["limit_price"] != 42_000.0


def test_camouflaged_price_echoed_in_response(fake_bridge):
    """The response dict's ``price`` field must report what was
    actually sent to the bridge, not the operator's raw input —
    otherwise downstream consumers see a phantom price."""
    fake_metadata = {"BTC-USDC": {"price_increment": "1"}}
    with patch.object(order_module, "get_stealth_order_bridge", return_value=fake_bridge), \
         patch("configuration.PRODUCT_METADATA", fake_metadata):
        result = create_limit_order_span(
            product_id="BTC-USDC",
            side="SELL",
            order_base_size=0.5,
            start_price=42_000.0,
            max_order_count=1,
            camouflage_round_numbers=True,
        )
    sent_price = fake_bridge.create_stealth_order.call_args.kwargs["limit_price"]
    assert result[0]["success_response"]["price"] == str(sent_price)


def test_bridge_failure_returns_error_dict(fake_bridge):
    """Bridge exceptions must be caught and surfaced as the documented
    ``error_response`` shape, not raised."""
    fake_bridge.create_stealth_order.side_effect = RuntimeError("boom")
    with patch.object(order_module, "get_stealth_order_bridge", return_value=fake_bridge):
        result = create_limit_order_span(
            product_id="BTC-USDC",
            side="BUY",
            order_base_size=0.5,
            start_price=42_000.0,
            max_order_count=1,
        )
    assert result[0]["success"] is False
    assert result[0]["error_response"]["error"] == "ORDER_CREATION_FAILED"
    assert "boom" in result[0]["error_response"]["message"]


def test_no_bridge_raises_runtime_error():
    """Documented RuntimeError when the order system isn't initialized."""
    with patch.object(order_module, "get_stealth_order_bridge", return_value=None):
        with pytest.raises(RuntimeError, match="Order system not initialized"):
            create_limit_order_span(
                product_id="BTC-USDC",
                side="BUY",
                order_base_size=0.5,
                start_price=42_000.0,
                max_order_count=1,
            )
