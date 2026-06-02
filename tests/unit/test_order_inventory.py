"""Unit tests for the Order Inventory feature.

Tests cover:
1. OrderStateHookRegistry — registration, dispatch, exception isolation
2. StealthLifecycleHookRegistry — registration, dispatch, exception isolation
3. OrderInventory (exchange side) — on_order_opened, on_order_closed, idempotency,
   aggregate counts, get_for_product, get_all, get_total_open_count
4. OrderInventory (stealth side) — on_stealth_transition, status mapping,
   failure_reason tracking, get_stealth_* query methods
5. OrderInventory.rebuild_from_database — restart resilience via mock DB rows
6. StateManager integration — hooks dispatched OUTSIDE lock; confirmed via threading
7. Deadlock safety — no nested acquisition between StateManager._lock and
   OrderInventory._lock
8. Singleton lifecycle — get/reset global functions

Run:
    pytest tests/unit/test_order_inventory.py -v

Design contract being tested:
- Hooks called OUTSIDE StateManager._lock (verified by checking lock state in callback)
- Hook exceptions never propagate to caller
- OrderInventory._lock is an RLock (leaf lock — never held while calling external code)
- rebuild_from_database does not acquire _lock (startup-thread only)
- All query methods return copies, not references to internal dicts/sets
"""

import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from core.enums import (
    OrderSide,
    OrderStateEvent,
    OrderStatus,
    ProductType,
    StealthLifecycleEvent,
    StealthOrderStatus,
)
from core.models import Order
from data.order_inventory import (
    OrderInventory,
    OrderInventoryEntry,
    StealthInventoryEntry,
    get_global_order_inventory,
    reset_global_order_inventory,
)
from integration.order_state_hooks import (
    OrderStateHookRegistry,
    get_global_order_state_hook_registry,
    reset_global_order_state_hook_registry,
)
from integration.stealth_lifecycle_hooks import (
    StealthLifecycleHookRegistry,
    get_global_stealth_lifecycle_hook_registry,
    reset_global_stealth_lifecycle_hook_registry,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_order(
    client_order_id: str = "test-cid-001",
    product_id: str = "BTC-USDC",
    side: OrderSide = OrderSide.BUY,
    size: float = 1.0,
    price: float = 50000.0,
    product_type: ProductType = ProductType.SPOT,
    status: OrderStatus = OrderStatus.OPEN,
) -> Order:
    return Order(
        client_order_id=client_order_id,
        product_id=product_id,
        order_side=side,
        status=status,
        size=size,
        price=price,
        product_type=product_type,
        created_at=datetime.utcnow(),
    )


def _make_stealth_context(
    product_id: str = "BTC-USDC",
    side: str = "BUY",
    total_size: float = 1.0,
    size: float = 0.5,
    limit_price: float = 50000.0,
    failure_reason: Optional[str] = None,
    placed_order_id: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "product_id": product_id,
        "side": side,
        "total_size": total_size,
        "size": size,
        "limit_price": limit_price,
        "failure_reason": failure_reason,
        "placed_order_id": placed_order_id,
        "timestamp": datetime.utcnow(),
        "reason": "test",
        "parent_order_id": None,
    }


@pytest.fixture(autouse=True)
def reset_all_singletons():
    """Reset all global singletons before and after each test."""
    reset_global_order_state_hook_registry()
    reset_global_stealth_lifecycle_hook_registry()
    reset_global_order_inventory()
    yield
    reset_global_order_state_hook_registry()
    reset_global_stealth_lifecycle_hook_registry()
    reset_global_order_inventory()


# ===========================================================================
# 1. OrderStateHookRegistry
# ===========================================================================

class TestOrderStateHookRegistry:
    def test_register_and_call_on_opened(self):
        registry = OrderStateHookRegistry()
        received: List[Order] = []
        registry.register_on_opened(lambda o: received.append(o))

        order = _make_order()
        registry.call_on_opened(order)

        assert len(received) == 1
        assert received[0].client_order_id == order.client_order_id

    def test_register_and_call_on_closed(self):
        registry = OrderStateHookRegistry()
        received: List[tuple] = []
        registry.register_on_closed(lambda o, e: received.append((o, e)))

        order = _make_order()
        registry.call_on_closed(order, OrderStateEvent.FILLED)

        assert len(received) == 1
        assert received[0][1] == OrderStateEvent.FILLED

    def test_multiple_opened_hooks_all_called(self):
        registry = OrderStateHookRegistry()
        calls: List[str] = []
        registry.register_on_opened(lambda o: calls.append("A"))
        registry.register_on_opened(lambda o: calls.append("B"))

        registry.call_on_opened(_make_order())

        assert calls == ["A", "B"]

    def test_exception_in_hook_does_not_propagate(self):
        registry = OrderStateHookRegistry()

        def bad_hook(order):
            raise RuntimeError("hook failure")

        registry.register_on_opened(bad_hook)
        # Must not raise
        registry.call_on_opened(_make_order())

    def test_exception_in_on_closed_does_not_propagate(self):
        registry = OrderStateHookRegistry()

        def bad_hook(order, event):
            raise ValueError("closed hook failure")

        registry.register_on_closed(bad_hook)
        registry.call_on_closed(_make_order(), OrderStateEvent.CANCELLED)

    def test_subsequent_hooks_called_after_bad_hook(self):
        """A failing hook must not prevent later hooks from running."""
        registry = OrderStateHookRegistry()
        calls: List[str] = []

        registry.register_on_opened(lambda o: (_ for _ in ()).throw(RuntimeError("bad")))
        registry.register_on_opened(lambda o: calls.append("second"))

        registry.call_on_opened(_make_order())
        assert "second" in calls

    def test_thread_safe_concurrent_registration(self):
        registry = OrderStateHookRegistry()
        results: List[int] = []

        def worker(i):
            registry.register_on_opened(lambda o, idx=i: results.append(idx))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        registry.call_on_opened(_make_order())
        assert len(results) == 20

    def test_global_singleton_returns_same_instance(self):
        r1 = get_global_order_state_hook_registry()
        r2 = get_global_order_state_hook_registry()
        assert r1 is r2

    def test_reset_clears_singleton(self):
        r1 = get_global_order_state_hook_registry()
        reset_global_order_state_hook_registry()
        r2 = get_global_order_state_hook_registry()
        assert r1 is not r2


# ===========================================================================
# 2. StealthLifecycleHookRegistry
# ===========================================================================

class TestStealthLifecycleHookRegistry:
    def test_register_and_call_on_transition(self):
        registry = StealthLifecycleHookRegistry()
        received: List[tuple] = []

        def handler(oid, event, ctx):
            received.append((oid, event, ctx))

        registry.register_on_transition(handler)
        ctx = _make_stealth_context()
        registry.call_on_transition("stealth-001", StealthLifecycleEvent.CREATED, ctx)

        assert len(received) == 1
        assert received[0][0] == "stealth-001"
        assert received[0][1] == StealthLifecycleEvent.CREATED

    def test_exception_in_hook_does_not_propagate(self):
        registry = StealthLifecycleHookRegistry()

        def bad_hook(oid, event, ctx):
            raise RuntimeError("bad lifecycle hook")

        registry.register_on_transition(bad_hook)
        # Must not raise
        registry.call_on_transition("oid", StealthLifecycleEvent.REVEAL_FAILED, {})

    def test_all_hooks_called_even_after_exception(self):
        registry = StealthLifecycleHookRegistry()
        calls: List[str] = []

        registry.register_on_transition(
            lambda o, e, c: (_ for _ in ()).throw(RuntimeError("bad"))
        )
        registry.register_on_transition(lambda o, e, c: calls.append("ok"))

        registry.call_on_transition("oid", StealthLifecycleEvent.CREATED, {})
        assert "ok" in calls

    def test_global_singleton(self):
        r1 = get_global_stealth_lifecycle_hook_registry()
        r2 = get_global_stealth_lifecycle_hook_registry()
        assert r1 is r2

    def test_reset_clears_singleton(self):
        r1 = get_global_stealth_lifecycle_hook_registry()
        reset_global_stealth_lifecycle_hook_registry()
        r2 = get_global_stealth_lifecycle_hook_registry()
        assert r1 is not r2


# ===========================================================================
# 3. OrderInventory — exchange side
# ===========================================================================

class TestOrderInventoryExchangeSide:
    def test_on_order_opened_increments_count(self):
        inv = OrderInventory()
        order = _make_order()
        inv.on_order_opened(order)
        assert inv.get_count("BTC-USDC", OrderSide.BUY, ProductType.SPOT) == 1

    def test_on_order_opened_accumulates_size(self):
        inv = OrderInventory()
        inv.on_order_opened(_make_order(client_order_id="a", size=1.0))
        inv.on_order_opened(_make_order(client_order_id="b", size=2.5))
        entry = inv.get_entry("BTC-USDC", OrderSide.BUY, ProductType.SPOT)
        assert entry.count == 2
        assert entry.total_size == pytest.approx(3.5)

    def test_on_order_opened_idempotent_same_client_id(self):
        inv = OrderInventory()
        order = _make_order()
        inv.on_order_opened(order)
        inv.on_order_opened(order)  # duplicate
        assert inv.get_count("BTC-USDC", OrderSide.BUY, ProductType.SPOT) == 1

    def test_on_order_closed_decrements_count(self):
        inv = OrderInventory()
        order = _make_order()
        inv.on_order_opened(order)
        inv.on_order_closed(order, OrderStateEvent.FILLED)
        assert inv.get_count("BTC-USDC", OrderSide.BUY, ProductType.SPOT) == 0

    def test_on_order_closed_for_unknown_order_no_crash(self):
        inv = OrderInventory()
        # No opened orders — closed should be a no-op
        inv.on_order_closed(_make_order(), OrderStateEvent.CANCELLED)

    def test_count_not_below_zero(self):
        inv = OrderInventory()
        order = _make_order()
        inv.on_order_opened(order)
        inv.on_order_closed(order, OrderStateEvent.FILLED)
        inv.on_order_closed(order, OrderStateEvent.FILLED)  # extra close
        assert inv.get_count("BTC-USDC", OrderSide.BUY, ProductType.SPOT) == 0

    def test_separate_buckets_for_different_sides(self):
        inv = OrderInventory()
        inv.on_order_opened(_make_order(client_order_id="buy", side=OrderSide.BUY))
        inv.on_order_opened(_make_order(client_order_id="sell", side=OrderSide.SELL))
        assert inv.get_count("BTC-USDC", OrderSide.BUY, ProductType.SPOT) == 1
        assert inv.get_count("BTC-USDC", OrderSide.SELL, ProductType.SPOT) == 1

    def test_separate_buckets_for_different_products(self):
        inv = OrderInventory()
        inv.on_order_opened(_make_order(client_order_id="btc", product_id="BTC-USDC"))
        inv.on_order_opened(_make_order(client_order_id="eth", product_id="ETH-USDC"))
        assert inv.get_count("BTC-USDC", OrderSide.BUY, ProductType.SPOT) == 1
        assert inv.get_count("ETH-USDC", OrderSide.BUY, ProductType.SPOT) == 1

    def test_get_for_product_returns_all_sides(self):
        inv = OrderInventory()
        inv.on_order_opened(_make_order(client_order_id="buy", side=OrderSide.BUY))
        inv.on_order_opened(_make_order(client_order_id="sell", side=OrderSide.SELL))
        entries = inv.get_for_product("BTC-USDC")
        assert len(entries) == 2

    def test_get_all_returns_all_entries(self):
        inv = OrderInventory()
        inv.on_order_opened(_make_order(client_order_id="btc"))
        inv.on_order_opened(_make_order(client_order_id="eth", product_id="ETH-USDC"))
        assert len(inv.get_all()) == 2

    def test_get_total_open_count(self):
        inv = OrderInventory()
        inv.on_order_opened(_make_order(client_order_id="a"))
        inv.on_order_opened(_make_order(client_order_id="b", product_id="ETH-USDC"))
        assert inv.get_total_open_count() == 2

    def test_entry_to_dict_is_json_safe(self):
        inv = OrderInventory()
        inv.on_order_opened(_make_order())
        entry = inv.get_entry("BTC-USDC", OrderSide.BUY, ProductType.SPOT)
        d = entry.to_order_inventory_entry_dict()
        assert isinstance(d["side"], str)
        assert isinstance(d["product_type"], str)
        assert isinstance(d["count"], int)


# ===========================================================================
# 4. OrderInventory — stealth side
# ===========================================================================

class TestOrderInventoryStealthSide:
    def test_created_event_adds_entry(self):
        inv = OrderInventory()
        ctx = _make_stealth_context()
        inv.on_stealth_transition("so-001", StealthLifecycleEvent.CREATED, ctx)
        entry = inv.get_stealth_entry("so-001")
        assert entry is not None
        assert entry.status == StealthOrderStatus.HIDDEN

    def test_condition_watching_updates_status(self):
        inv = OrderInventory()
        inv.on_stealth_transition("so-001", StealthLifecycleEvent.CREATED, _make_stealth_context())
        inv.on_stealth_transition("so-001", StealthLifecycleEvent.CONDITION_WATCHING, _make_stealth_context())
        assert inv.get_stealth_entry("so-001").status == StealthOrderStatus.PENDING

    def test_condition_met_updates_to_triggered(self):
        inv = OrderInventory()
        inv.on_stealth_transition("so-001", StealthLifecycleEvent.CREATED, _make_stealth_context())
        inv.on_stealth_transition("so-001", StealthLifecycleEvent.CONDITION_MET, _make_stealth_context())
        assert inv.get_stealth_entry("so-001").status == StealthOrderStatus.TRIGGERED

    def test_reveal_succeeded_updates_to_revealed(self):
        inv = OrderInventory()
        ctx = _make_stealth_context()
        inv.on_stealth_transition("so-001", StealthLifecycleEvent.CREATED, ctx)
        reveal_ctx = _make_stealth_context(placed_order_id="placed-001")
        inv.on_stealth_transition("so-001", StealthLifecycleEvent.REVEAL_SUCCEEDED, reveal_ctx)
        entry = inv.get_stealth_entry("so-001")
        assert entry.status == StealthOrderStatus.REVEALED
        assert entry.placed_order_id == "placed-001"
        assert entry.failure_reason is None

    def test_placement_blocked_stores_failure_reason(self):
        inv = OrderInventory()
        inv.on_stealth_transition("so-001", StealthLifecycleEvent.CREATED, _make_stealth_context())
        fail_ctx = _make_stealth_context(failure_reason="Risk limit exceeded")
        inv.on_stealth_transition("so-001", StealthLifecycleEvent.PLACEMENT_BLOCKED, fail_ctx)
        entry = inv.get_stealth_entry("so-001")
        assert entry.failure_reason == "Risk limit exceeded"
        assert entry.status == StealthOrderStatus.TRIGGERED

    def test_reveal_failed_stores_failure_reason(self):
        inv = OrderInventory()
        inv.on_stealth_transition("so-001", StealthLifecycleEvent.CREATED, _make_stealth_context())
        fail_ctx = _make_stealth_context(failure_reason="Connection timeout")
        inv.on_stealth_transition("so-001", StealthLifecycleEvent.REVEAL_FAILED, fail_ctx)
        entry = inv.get_stealth_entry("so-001")
        assert entry.failure_reason == "Connection timeout"

    def test_reveal_succeeded_clears_prior_failure(self):
        inv = OrderInventory()
        inv.on_stealth_transition("so-001", StealthLifecycleEvent.CREATED, _make_stealth_context())
        inv.on_stealth_transition("so-001", StealthLifecycleEvent.REVEAL_FAILED,
                                  _make_stealth_context(failure_reason="timeout"))
        inv.on_stealth_transition("so-001", StealthLifecycleEvent.REVEAL_SUCCEEDED,
                                  _make_stealth_context(placed_order_id="placed-001"))
        assert inv.get_stealth_entry("so-001").failure_reason is None

    def test_executed_terminal_status(self):
        inv = OrderInventory()
        inv.on_stealth_transition("so-001", StealthLifecycleEvent.CREATED, _make_stealth_context())
        inv.on_stealth_transition("so-001", StealthLifecycleEvent.EXECUTED, _make_stealth_context())
        assert inv.get_stealth_entry("so-001").status == StealthOrderStatus.EXECUTED

    def test_cancelled_terminal_status(self):
        inv = OrderInventory()
        inv.on_stealth_transition("so-001", StealthLifecycleEvent.CREATED, _make_stealth_context())
        inv.on_stealth_transition("so-001", StealthLifecycleEvent.CANCELLED, _make_stealth_context())
        assert inv.get_stealth_entry("so-001").status == StealthOrderStatus.CANCELLED

    def test_get_stealth_pending_filters_hidden_and_pending(self):
        inv = OrderInventory()
        inv.on_stealth_transition("so-hidden", StealthLifecycleEvent.CREATED, _make_stealth_context())
        inv.on_stealth_transition("so-pending", StealthLifecycleEvent.CONDITION_WATCHING, _make_stealth_context())
        inv.on_stealth_transition("so-pending", StealthLifecycleEvent.CONDITION_WATCHING, _make_stealth_context())

        inv.on_stealth_transition("so-revealed", StealthLifecycleEvent.REVEAL_SUCCEEDED, _make_stealth_context())

        pending = inv.get_stealth_pending()
        ids = {e.stealth_order_id for e in pending}
        assert "so-hidden" in ids
        assert "so-pending" in ids
        assert "so-revealed" not in ids

    def test_get_stealth_on_exchange_filters_revealed(self):
        inv = OrderInventory()
        inv.on_stealth_transition("so-001", StealthLifecycleEvent.REVEAL_SUCCEEDED, _make_stealth_context())
        inv.on_stealth_transition("so-002", StealthLifecycleEvent.CREATED, _make_stealth_context())
        on_ex = inv.get_stealth_on_exchange()
        assert len(on_ex) == 1
        assert on_ex[0].stealth_order_id == "so-001"

    def test_get_stealth_failures_returns_entries_with_failure_reason(self):
        inv = OrderInventory()
        inv.on_stealth_transition("so-fail", StealthLifecycleEvent.CREATED, _make_stealth_context())
        inv.on_stealth_transition("so-fail", StealthLifecycleEvent.REVEAL_FAILED,
                                  _make_stealth_context(failure_reason="timeout"))
        inv.on_stealth_transition("so-ok", StealthLifecycleEvent.CREATED, _make_stealth_context())
        failures = inv.get_stealth_failures()
        ids = {e.stealth_order_id for e in failures}
        assert "so-fail" in ids
        assert "so-ok" not in ids

    def test_get_stealth_count_by_product(self):
        inv = OrderInventory()
        inv.on_stealth_transition("so-btc-1", StealthLifecycleEvent.CREATED,
                                  _make_stealth_context(product_id="BTC-USDC"))
        inv.on_stealth_transition("so-btc-2", StealthLifecycleEvent.CREATED,
                                  _make_stealth_context(product_id="BTC-USDC"))
        inv.on_stealth_transition("so-eth-1", StealthLifecycleEvent.CREATED,
                                  _make_stealth_context(product_id="ETH-USDC"))
        assert inv.get_stealth_count_by_product("BTC-USDC") == 2
        assert inv.get_stealth_count_by_product("ETH-USDC") == 1

    def test_get_stealth_count_by_product_and_status(self):
        inv = OrderInventory()
        inv.on_stealth_transition("so-1", StealthLifecycleEvent.CREATED,
                                  _make_stealth_context(product_id="BTC-USDC"))
        inv.on_stealth_transition("so-2", StealthLifecycleEvent.REVEAL_SUCCEEDED,
                                  _make_stealth_context(product_id="BTC-USDC"))
        assert inv.get_stealth_count_by_product("BTC-USDC", StealthOrderStatus.HIDDEN) == 1
        assert inv.get_stealth_count_by_product("BTC-USDC", StealthOrderStatus.REVEALED) == 1

    def test_get_summary_shape(self):
        inv = OrderInventory()
        inv.on_order_opened(_make_order())
        inv.on_stealth_transition("so-001", StealthLifecycleEvent.CREATED, _make_stealth_context())
        summary = inv.get_summary()
        assert "exchange_orders" in summary
        assert "stealth_orders" in summary
        assert "total_open_count" in summary
        assert "stealth_counts" in summary

    def test_stealth_entry_to_dict_is_json_safe(self):
        inv = OrderInventory()
        inv.on_stealth_transition("so-001", StealthLifecycleEvent.CREATED, _make_stealth_context())
        entry = inv.get_stealth_entry("so-001")
        d = entry.to_stealth_inventory_entry_dict()
        assert isinstance(d["side"], str)
        assert isinstance(d["status"], str)
        assert isinstance(d["last_event"], str)


# ===========================================================================
# 5. OrderInventory.rebuild_from_database
# ===========================================================================

class TestOrderInventoryRebuildFromDatabase:
    def _mock_db_with_rows(self, exchange_rows, stealth_rows):
        db = MagicMock()

        def execute_query_side_effect(sql, *args, **kwargs):
            if "order_parent" in sql:
                return exchange_rows
            if "stealth_orders" in sql:
                return stealth_rows
            return []

        db.execute_query.side_effect = execute_query_side_effect
        return db

    def test_rebuild_loads_exchange_working_orders(self):
        rows = [
            {
                "client_order_id": "cid-001",
                "product_id": "BTC-USDC",
                "side": "BUY",
                "size": "1.5",
                "price": "50000",
                "status": "OPEN",
                "created_at": datetime.utcnow(),
            }
        ]
        db = self._mock_db_with_rows(rows, [])
        inv = OrderInventory()
        inv.rebuild_from_database(db)

        assert inv.get_count("BTC-USDC", OrderSide.BUY, ProductType.SPOT) == 1
        entry = inv.get_entry("BTC-USDC", OrderSide.BUY, ProductType.SPOT)
        assert entry.total_size == pytest.approx(1.5)

    def test_rebuild_loads_stealth_entries(self):
        stealth_rows = [
            {
                "stealth_order_id": "so-001",
                "product_id": "BTC-USDC",
                "side": "BUY",
                "status": "REVEALED",
                "total_size": "2.0",
                "revealed_size": "1.0",
                "limit_price": "50000",
                "last_lifecycle_event": "REVEAL_SUCCEEDED",
                "failure_reason": None,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
        ]
        db = self._mock_db_with_rows([], stealth_rows)
        inv = OrderInventory()
        inv.rebuild_from_database(db)

        entry = inv.get_stealth_entry("so-001")
        assert entry is not None
        assert entry.status == StealthOrderStatus.REVEALED
        assert entry.last_event == StealthLifecycleEvent.REVEAL_SUCCEEDED
        assert entry.total_size == pytest.approx(2.0)

    def test_rebuild_with_failure_reason_restored(self):
        stealth_rows = [
            {
                "stealth_order_id": "so-fail",
                "product_id": "BTC-USDC",
                "side": "SELL",
                "status": "TRIGGERED",
                "total_size": "1.0",
                "revealed_size": "0.0",
                "limit_price": "49000",
                "last_lifecycle_event": "REVEAL_FAILED",
                "failure_reason": "Connection refused",
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
        ]
        db = self._mock_db_with_rows([], stealth_rows)
        inv = OrderInventory()
        inv.rebuild_from_database(db)

        entry = inv.get_stealth_entry("so-fail")
        assert entry.failure_reason == "Connection refused"
        assert entry.last_event == StealthLifecycleEvent.REVEAL_FAILED
        failures = inv.get_stealth_failures()
        assert any(e.stealth_order_id == "so-fail" for e in failures)

    def test_rebuild_skips_malformed_rows_without_crash(self):
        bad_rows = [{"not_a_valid_key": "garbage"}]
        db = self._mock_db_with_rows(bad_rows, bad_rows)
        inv = OrderInventory()
        inv.rebuild_from_database(db)  # Must not raise

    def test_rebuild_handles_db_exception_gracefully(self):
        db = MagicMock()
        db.execute_query.side_effect = Exception("DB connection failed")
        inv = OrderInventory()
        inv.rebuild_from_database(db)  # Must not raise
        assert inv.get_total_open_count() == 0

    def test_rebuild_unknown_lifecycle_event_defaults_to_created(self):
        stealth_rows = [
            {
                "stealth_order_id": "so-unknown",
                "product_id": "BTC-USDC",
                "side": "BUY",
                "status": "HIDDEN",
                "total_size": "1.0",
                "revealed_size": "0.0",
                "limit_price": "50000",
                "last_lifecycle_event": "NOT_A_REAL_EVENT",
                "failure_reason": None,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
        ]
        db = self._mock_db_with_rows([], stealth_rows)
        inv = OrderInventory()
        inv.rebuild_from_database(db)
        entry = inv.get_stealth_entry("so-unknown")
        assert entry.last_event == StealthLifecycleEvent.CREATED

    def test_rebuild_null_lifecycle_event_defaults_to_created(self):
        stealth_rows = [
            {
                "stealth_order_id": "so-null",
                "product_id": "BTC-USDC",
                "side": "BUY",
                "status": "HIDDEN",
                "total_size": "1.0",
                "revealed_size": "0.0",
                "limit_price": "50000",
                "last_lifecycle_event": None,
                "failure_reason": None,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
        ]
        db = self._mock_db_with_rows([], stealth_rows)
        inv = OrderInventory()
        inv.rebuild_from_database(db)
        entry = inv.get_stealth_entry("so-null")
        assert entry.last_event == StealthLifecycleEvent.CREATED


# ===========================================================================
# 6. StateManager integration — hooks dispatched OUTSIDE lock
# ===========================================================================

class TestStateManagerHookDispatch:
    """Verify that StateManager dispatches hooks AFTER releasing _lock.

    This is the core deadlock-safety guarantee: if the hook callback tries to
    acquire any other lock, StateManager._lock must already be released.
    We verify this by inspecting the lock state inside the callback.
    """

    def test_add_active_order_dispatches_opened_hook(self):
        from data.state_manager import StateManager

        registry = get_global_order_state_hook_registry()
        received: List[Order] = []
        registry.register_on_opened(lambda o: received.append(o))

        state = StateManager()
        order = _make_order()
        state.add_active_order(order)

        assert len(received) == 1
        assert received[0].client_order_id == order.client_order_id

    def test_mark_order_filled_dispatches_closed_hook(self):
        from data.state_manager import StateManager

        registry = get_global_order_state_hook_registry()
        events: List[OrderStateEvent] = []
        registry.register_on_closed(lambda o, e: events.append(e))

        state = StateManager()
        order = _make_order()
        state.add_active_order(order)
        state.mark_order_filled(order)

        assert OrderStateEvent.FILLED in events

    def test_mark_order_cancelled_dispatches_closed_hook(self):
        from data.state_manager import StateManager

        registry = get_global_order_state_hook_registry()
        events: List[OrderStateEvent] = []
        registry.register_on_closed(lambda o, e: events.append(e))

        state = StateManager()
        order = _make_order()
        state.add_active_order(order)
        state.mark_order_cancelled(order)

        assert OrderStateEvent.CANCELLED in events

    def test_hook_exception_does_not_crash_state_manager(self):
        """A broken hook must never prevent StateManager from recording the order."""
        from data.state_manager import StateManager

        registry = get_global_order_state_hook_registry()
        registry.register_on_opened(lambda o: 1 / 0)  # ZeroDivisionError

        state = StateManager()
        order = _make_order()
        state.add_active_order(order)  # Must not raise

        # Order should still be tracked internally
        assert state.get_order(order.client_order_id) is not None

    def test_hook_called_outside_state_manager_lock(self):
        """Verify StateManager._lock is NOT held when the hook callback fires.

        We check this by attempting to acquire the lock inside the callback.
        If the hook is called while the lock is held (non-recursive Lock), the
        second acquire would deadlock. We use a threading.Event + timeout to
        detect that case.
        """
        from data.state_manager import StateManager

        state = StateManager()
        lock_was_free = threading.Event()

        def check_lock(order):
            # Try to acquire StateManager's internal _lock from within the hook.
            # If called inside the lock, this would block (non-recursive Lock).
            acquired = state._lock.acquire(blocking=False)
            if acquired:
                state._lock.release()
                lock_was_free.set()

        registry = get_global_order_state_hook_registry()
        registry.register_on_opened(check_lock)

        state.add_active_order(_make_order())

        assert lock_was_free.is_set(), (
            "StateManager._lock was held during hook dispatch — potential deadlock!"
        )


# ===========================================================================
# 7. Deadlock safety — no nested acquisition
# ===========================================================================

class TestDeadlockSafety:
    def test_order_inventory_lock_is_rlock(self):
        """OrderInventory._lock must be RLock (recursive) to allow re-entrant queries."""
        inv = OrderInventory()
        assert isinstance(inv._lock, type(threading.RLock()))

    def test_hook_registry_locks_are_rlock(self):
        """Hook registries must use RLock to be re-entrant safe."""
        state_reg = OrderStateHookRegistry()
        stealth_reg = StealthLifecycleHookRegistry()
        assert isinstance(state_reg._lock, type(threading.RLock()))
        assert isinstance(stealth_reg._lock, type(threading.RLock()))

    def test_inventory_methods_safe_under_concurrent_access(self):
        """Stress-test concurrent opens and closes from multiple threads."""
        inv = OrderInventory()
        errors: List[Exception] = []

        def open_and_close(i):
            try:
                order = _make_order(client_order_id=f"stress-{i}")
                inv.on_order_opened(order)
                time.sleep(0.001)
                inv.on_order_closed(order, OrderStateEvent.FILLED)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=open_and_close, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent access raised: {errors}"
        # All closes matched opens, so count should be 0
        assert inv.get_total_open_count() == 0

    def test_stealth_transitions_concurrent_no_race(self):
        """Multiple threads updating stealth inventory simultaneously must not corrupt state."""
        inv = OrderInventory()
        errors: List[Exception] = []

        def add_transitions(i):
            try:
                oid = f"so-stress-{i}"
                inv.on_stealth_transition(oid, StealthLifecycleEvent.CREATED, _make_stealth_context())
                inv.on_stealth_transition(oid, StealthLifecycleEvent.CONDITION_MET, _make_stealth_context())
                inv.on_stealth_transition(oid, StealthLifecycleEvent.REVEAL_SUCCEEDED,
                                          _make_stealth_context(placed_order_id=f"p-{i}"))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=add_transitions, args=(i,)) for i in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent stealth transitions raised: {errors}"
        assert len(inv.get_all_stealth()) == 30


# ===========================================================================
# 8. Global singleton wiring end-to-end
# ===========================================================================

class TestEndToEndWiring:
    def test_full_wiring_exchange_order_lifecycle(self):
        """Simulate full exchange-order lifecycle through wired hooks."""
        inventory = get_global_order_inventory()
        state_hooks = get_global_order_state_hook_registry()

        state_hooks.register_on_opened(inventory.on_order_opened)
        state_hooks.register_on_closed(inventory.on_order_closed)

        order = _make_order(client_order_id="e2e-001")
        state_hooks.call_on_opened(order)
        assert inventory.get_count("BTC-USDC", OrderSide.BUY, ProductType.SPOT) == 1

        state_hooks.call_on_closed(order, OrderStateEvent.FILLED)
        assert inventory.get_count("BTC-USDC", OrderSide.BUY, ProductType.SPOT) == 0

    def test_full_wiring_stealth_lifecycle(self):
        """Simulate full stealth lifecycle through wired hooks."""
        inventory = get_global_order_inventory()
        lc_hooks = get_global_stealth_lifecycle_hook_registry()

        lc_hooks.register_on_transition(inventory.on_stealth_transition)

        oid = "e2e-stealth-001"
        ctx = _make_stealth_context()

        lc_hooks.call_on_transition(oid, StealthLifecycleEvent.CREATED, ctx)
        assert inventory.get_stealth_entry(oid).status == StealthOrderStatus.HIDDEN

        lc_hooks.call_on_transition(oid, StealthLifecycleEvent.CONDITION_MET, ctx)
        assert inventory.get_stealth_entry(oid).status == StealthOrderStatus.TRIGGERED

        lc_hooks.call_on_transition(oid, StealthLifecycleEvent.REVEAL_SUCCEEDED,
                                    _make_stealth_context(placed_order_id="placed-e2e"))
        assert inventory.get_stealth_entry(oid).status == StealthOrderStatus.REVEALED
        assert inventory.get_stealth_entry(oid).placed_order_id == "placed-e2e"

        lc_hooks.call_on_transition(oid, StealthLifecycleEvent.EXECUTED, ctx)
        assert inventory.get_stealth_entry(oid).status == StealthOrderStatus.EXECUTED

    def test_failure_then_retry_lifecycle(self):
        """REVEAL_FAILED followed by successful REVEAL_SUCCEEDED clears failure_reason."""
        inventory = get_global_order_inventory()
        lc_hooks = get_global_stealth_lifecycle_hook_registry()
        lc_hooks.register_on_transition(inventory.on_stealth_transition)

        oid = "e2e-retry-001"

        lc_hooks.call_on_transition(oid, StealthLifecycleEvent.CREATED, _make_stealth_context())
        lc_hooks.call_on_transition(oid, StealthLifecycleEvent.REVEAL_FAILED,
                                    _make_stealth_context(failure_reason="Timeout"))

        assert inventory.get_stealth_entry(oid).failure_reason == "Timeout"

        lc_hooks.call_on_transition(oid, StealthLifecycleEvent.REVEAL_SUCCEEDED,
                                    _make_stealth_context(placed_order_id="retry-placed"))

        entry = inventory.get_stealth_entry(oid)
        assert entry.failure_reason is None
        assert entry.status == StealthOrderStatus.REVEALED
        assert len(inventory.get_stealth_failures()) == 0
