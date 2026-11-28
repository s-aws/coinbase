"""Canonical product-type resolution must not depend on month substrings."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from calculation.resolver import normalize_product_type
from core.enums import ProductType, StealthLifecycleEvent
from core.models import Product


pytestmark = pytest.mark.regression
_MONTHS = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()


@pytest.mark.parametrize("month", _MONTHS)
def test_unlisted_cde_contract_is_future_for_every_month(month):
    product_id = f"SYNTH-28{month}99-CDE"

    assert normalize_product_type({"product_id": product_id}) == ProductType.FUTURE.value


@pytest.mark.parametrize("month", "DEC JAN FEB MAR APR".split())
def test_month_substring_in_spot_symbol_is_not_a_futures_indicator(month):
    product_id = f"SYNTH{month}-USD"

    assert normalize_product_type({"product_id": product_id}) == ProductType.SPOT.value


@pytest.mark.parametrize("use_product_model", [False, True], ids=["dict", "Product"])
@pytest.mark.parametrize(
    ("product_id", "expected"),
    [
        ("SYNTH-PERP", ProductType.FUTURE),
        ("SYNTH-28JUN99-CDE", ProductType.SPOT),
    ],
)
def test_canonical_resolver_honors_supplied_product_metadata(
    product_id, expected, use_product_model
):
    metadata = {"product_type": expected.value}
    if use_product_model:
        metadata = Product(
            product_id=product_id,
            product_type=expected,
            base_increment="1",
            quote_increment="0.01",
            price_increment="0.01",
        )

    resolved = normalize_product_type(
        {"product_id": product_id},
        products={product_id: metadata},
    )

    assert resolved == expected.value


def test_explicit_order_product_type_precedes_configured_metadata():
    product_id = "SYNTH-28JUN99-CDE"

    resolved = normalize_product_type(
        {"product_id": product_id, "product_type": ProductType.SPOT.value},
        products={product_id: {"product_type": ProductType.FUTURE.value}},
    )

    assert resolved == ProductType.SPOT.value


@pytest.mark.parametrize(
    ("order_data", "expected"),
    [
        ({"product_id": f"SYNTH-28{month}99-CDE"}, ProductType.FUTURE)
        for month in _MONTHS
    ]
    + [
        ({"product_id": f"SYNTH{month}-USD"}, ProductType.SPOT)
        for month in "DEC JAN FEB MAR APR".split()
    ]
    + [
        (
            {"product_id": "SYNTH-PERP", "product_type": ProductType.FUTURE.value},
            ProductType.FUTURE,
        ),
        (
            {
                "product_id": "SYNTH-28JUN99-CDE",
                "product_type": ProductType.SPOT.value,
            },
            ProductType.SPOT,
        ),
    ],
)
def test_stealth_lifecycle_context_uses_product_type_resolver(
    order_data, expected
):
    from core.stealth_order_manager import StealthOrderManager
    manager = StealthOrderManager.__new__(StealthOrderManager)
    manager._get_current_market_data = Mock(return_value={})
    manager.log_callback = Mock()
    registry = SimpleNamespace(call_on_transition=Mock())
    manager.stealth_lifecycle_hooks = registry

    manager._dispatch_lifecycle_event(
        "4b998090-3fbb-472c-8f87-47df60e2d568",
        StealthLifecycleEvent.CREATED,
        order_data,
    )

    registry.call_on_transition.assert_called_once()
    context = registry.call_on_transition.call_args.kwargs["context"]
    assert context["product_type"] == expected.value
    manager.log_callback.assert_not_called()
