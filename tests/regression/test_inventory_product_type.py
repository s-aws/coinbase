"""Inventory, state, and lifecycle types must not depend on month substrings."""

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from calculation.formatter import safe_float
from core.enums import OrderSide, OrderStatus, ProductType, StealthLifecycleEvent, StealthOrderStatus
from core.models import Product
from data import order_inventory, state_manager


pytestmark = pytest.mark.regression
_MONTHS = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()


@pytest.mark.parametrize("month", _MONTHS)
def test_unlisted_cde_contract_is_future_for_every_month(month):
    product_id = f"SYNTH-28{month}99-CDE"

    assert product_id not in order_inventory.DERIVATIVES_PRODUCT_IDS
    assert order_inventory._infer_product_type(product_id) is ProductType.FUTURE
    assert state_manager.StateManager()._infer_product_type(product_id) == ProductType.FUTURE.value


@pytest.mark.parametrize("month", "DEC JAN FEB MAR APR".split())
def test_month_substring_in_spot_symbol_is_not_a_futures_indicator(month):
    product_id = f"SYNTH{month}-USD"

    assert order_inventory._infer_product_type(product_id) is ProductType.SPOT
    assert state_manager.StateManager()._infer_product_type(product_id) == ProductType.SPOT.value


@pytest.mark.parametrize(
    ("product_id", "spot_ids", "future_ids", "expected"),
    [
        # Explicit spot membership retains priority even over an overlapping list.
        ("SYNTH-CDE", ("SYNTH-CDE",), ("SYNTH-CDE",), ProductType.SPOT),
        ("SYNTH-PERP", (), ("SYNTH-PERP",), ProductType.FUTURE),
    ],
)
def test_explicit_product_list_precedence_is_preserved(
    monkeypatch, product_id, spot_ids, future_ids, expected
):
    for module in (order_inventory, state_manager):
        monkeypatch.setattr(module, "SPOT_PRODUCT_IDS", spot_ids)
        monkeypatch.setattr(module, "DERIVATIVES_PRODUCT_IDS", future_ids)

    assert order_inventory._infer_product_type(product_id) is expected
    assert state_manager.StateManager()._infer_product_type(product_id) == expected.value


@pytest.mark.parametrize("use_product_model", [False, True], ids=["dict", "Product"])
@pytest.mark.parametrize(
    ("product_id", "expected"),
    [
        ("SYNTH-PERP", ProductType.FUTURE),
        ("SYNTH-28JUN99-CDE", ProductType.SPOT),
    ],
)
def test_state_fallback_honors_supplied_product_metadata(
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
    state = state_manager.StateManager(product_config={product_id: metadata})

    assert state._infer_product_type(product_id) == expected.value


def test_inventory_rebuild_restores_unlisted_future_multiplier_and_stealth_type(monkeypatch):
    product_id = "SYNTH-28JUN99-CDE"
    client_id = "28dcb347-1207-4bd7-91db-4eb296e6b7d3"
    stealth_id = "353a7d3e-247f-4b28-ad17-5d4e33407632"
    # The rebuild's local import sees only this isolated in-memory configuration.
    config = ModuleType("configuration")
    config.ORDERBOOK = SimpleNamespace(
        product={product_id: {"future_product_details": {"contract_size": "0.01"}}}
    )
    config.safe_float = safe_float
    monkeypatch.setitem(sys.modules, "configuration", config)
    exchange_rows = [{
        "client_order_id": client_id,
        "product_id": product_id,
        "side": OrderSide.BUY.value,
        "size": "3",
        "price": "100",
        "status": OrderStatus.OPEN.value,
    }]
    stealth_rows = [{
        "stealth_order_id": stealth_id,
        "product_id": product_id,
        "side": OrderSide.BUY.value,
        "status": StealthOrderStatus.HIDDEN.value,
        "total_size": "3",
        "revealed_size": "0",
        "limit_price": "100",
    }]

    def query(sql):
        if "FROM   order_parent" in sql:
            return exchange_rows
        if "FROM   stealth_orders" in sql:
            return stealth_rows
        raise AssertionError(f"Unexpected inventory query: {sql}")

    db = SimpleNamespace(execute_query=Mock(side_effect=query))
    inventory = order_inventory.OrderInventory()
    inventory.rebuild_from_database(db)

    entry = inventory.get_entry(product_id, OrderSide.BUY, ProductType.FUTURE)
    assert entry is not None
    assert entry.client_order_ids == {client_id}
    assert entry.count == 1
    assert entry.contract_size == pytest.approx(0.01)
    assert entry.get_notional() == pytest.approx(3.0)
    assert inventory.get_count(product_id, OrderSide.BUY, ProductType.SPOT) == 0
    stealth = inventory.get_stealth_entry(stealth_id)
    assert stealth is not None
    assert stealth.product_type is ProductType.FUTURE
    assert db.execute_query.call_count == 2


@pytest.mark.parametrize(
    ("order_data", "expected"),
    [
        ({"product_id": f"SYNTH-28{month}99-CDE"}, ProductType.FUTURE)
        for month in _MONTHS
    ] + [
        ({"product_id": f"SYNTH{month}-USD"}, ProductType.SPOT)
        for month in "DEC JAN FEB MAR APR".split()
    ] + [
        ({"product_id": "SYNTH-PERP", "product_type": ProductType.FUTURE.value}, ProductType.FUTURE),
        ({"product_id": "SYNTH-28JUN99-CDE", "product_type": ProductType.SPOT.value}, ProductType.SPOT),
    ],
)
def test_stealth_lifecycle_context_uses_product_type_resolver(monkeypatch, order_data, expected):
    from core.stealth_order_manager import StealthOrderManager
    from integration import stealth_lifecycle_hooks

    # Bypass manager initialization and all real event subscribers or market feeds.
    manager = StealthOrderManager.__new__(StealthOrderManager)
    manager._get_current_market_data = Mock(return_value={})
    manager.log_callback = Mock()
    registry = SimpleNamespace(call_on_transition=Mock())
    monkeypatch.setattr(
        stealth_lifecycle_hooks, "get_global_stealth_lifecycle_hook_registry", lambda: registry
    )

    manager._dispatch_lifecycle_event(
        "4b998090-3fbb-472c-8f87-47df60e2d568", StealthLifecycleEvent.CREATED, order_data
    )

    registry.call_on_transition.assert_called_once()
    context = registry.call_on_transition.call_args.kwargs["context"]
    assert context["product_type"] == expected.value
    manager.log_callback.assert_not_called()
