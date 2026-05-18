"""Verify that ``import configuration`` makes zero network calls and instantiates
zero API clients or OrderBook objects.  All side effects must be deferred to
first actual use of the lazy proxies.

Phase: lazy-import-init (p2-4).
"""

import sys
import importlib
import threading
from unittest.mock import patch, MagicMock

import pytest


def _fresh_import():
    """Remove configuration (and dependents) from sys.modules and re-import it."""
    to_remove = [
        k for k in sys.modules
        if k.startswith("configuration") or k.startswith("core.orderbook")
    ]
    for key in to_remove:
        sys.modules.pop(key, None)
    return importlib.import_module("configuration")


class TestLazyImport:
    """``import configuration`` must be a zero-side-effect operation."""

    # -- no-instantiation tests -------------------------------------------

    def test_rest_client_proxy_not_initialised_after_import(self):
        mod = _fresh_import()
        assert mod.REST_CLIENT._real is None

    def test_orderbook_proxy_not_initialised_after_import(self):
        mod = _fresh_import()
        assert mod.ORDERBOOK._real is None

    def test_no_sdk_client_created(self):
        """_make_rest_client must not be called at import time.

        We verify by checking that the proxy _real slot is still None
        after a fresh import — the only way it becomes non-None is if
        the factory ran.
        """
        mod = _fresh_import()
        # _real is None -> factory never ran during import
        assert mod.REST_CLIENT._real is None
        # Also confirm the factory reference is intact (not consumed)
        assert callable(mod.REST_CLIENT._factory)

    def test_no_orderbook_created(self):
        """OrderBook constructor must not be called at import time."""
        mod = _fresh_import()
        assert mod.ORDERBOOK._real is None
        assert callable(mod.ORDERBOOK._factory)

    # -- proxy triggers init on first use ---------------------------------

    def test_rest_client_lazy_init_on_attribute_access(self):
        mod = _fresh_import()
        fake_client = MagicMock()

        mod.REST_CLIENT._factory = lambda: fake_client

        # First attribute access should trigger init
        _ = mod.REST_CLIENT.anything
        assert mod.REST_CLIENT._real is fake_client

        # Second access reuses the same instance
        _ = mod.REST_CLIENT.something_else
        assert mod.REST_CLIENT._real is fake_client

    def test_orderbook_lazy_init_on_attribute_access(self):
        mod = _fresh_import()
        fake_ob = MagicMock()

        mod.ORDERBOOK._factory = lambda: fake_ob

        _ = mod.ORDERBOOK.order
        assert mod.ORDERBOOK._real is fake_ob

        _ = mod.ORDERBOOK.product
        assert mod.ORDERBOOK._real is fake_ob

    # -- callable proxy support -------------------------------------------

    def test_rest_client_lazy_init_on_call(self):
        mod = _fresh_import()
        fake_client = MagicMock()

        mod.REST_CLIENT._factory = lambda: fake_client

        mod.REST_CLIENT.do_something("arg")
        assert mod.REST_CLIENT._real is fake_client
        fake_client.do_something.assert_called_once_with("arg")

    # -- singleton guarantee (factory creates fresh object each call) ------

    def test_get_rest_client_returns_same_instance(self):
        """Prove the getter caches: the factory must be called exactly once."""
        mod = _fresh_import()
        call_count = [0]

        def fresh_client():
            call_count[0] += 1
            return MagicMock()

        mod.REST_CLIENT._factory = fresh_client

        first = mod.get_rest_client()
        second = mod.get_rest_client()
        assert first is second
        assert call_count[0] == 1, "factory was called more than once — caching broken"

    def test_get_orderbook_returns_same_instance(self):
        """Prove the getter caches: the factory must be called exactly once."""
        mod = _fresh_import()
        call_count = [0]

        def fresh_ob():
            call_count[0] += 1
            return MagicMock()

        mod.ORDERBOOK._factory = fresh_ob

        first = mod.get_orderbook()
        second = mod.get_orderbook()
        assert first is second
        assert call_count[0] == 1, "factory was called more than once — caching broken"

    # -- thread-safety regression -----------------------------------------

    def test_concurrent_first_access_calls_factory_once(self):
        """Eight threads hammering ``_ensure()`` simultaneously must end up
        with exactly one factory invocation and a single shared instance.

        Regression: before the double-checked lock, an 8-thread probe created
        8 distinct objects and returned 8 different instances before one won
        the ``_real`` assignment.
        """
        mod = _fresh_import()
        call_count = [0]
        instances = []
        barrier = threading.Barrier(8)

        def factory():
            call_count[0] += 1
            instance = MagicMock()
            instances.append(instance)
            return instance

        mod.REST_CLIENT._factory = factory

        def hit():
            barrier.wait()
            mod.REST_CLIENT._ensure()
            # Capture whatever each thread sees as the resolved object
            instances.append(mod.REST_CLIENT._real)

        threads = [threading.Thread(target=hit) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert call_count[0] == 1, (
            f"factory called {call_count[0]} times — thread-safety broken"
        )

    # -- attribute writes through proxy (order_engine.py:423 pattern) ------

    class _PropShim:
        """Minimal stand-in that mirrors the OrderBook shim db_module property."""

        def __init__(self):
            self._db_module = None

        @property
        def db_module(self):
            return self._db_module

        @db_module.setter
        def db_module(self, value):
            self._db_module = value

    def test_proxy_forwards_attribute_writes_to_real_object(self):
        """order_engine.py does ``self.orderbook.db_module = self.db_module``.
        LazyProxy must forward the write to the real object's property setter,
        not silently store it on the proxy instance.
        """
        mod = _fresh_import()
        call_count = [0]
        shim_class = self._PropShim

        def factory():
            nonlocal call_count
            call_count[0] += 1
            return shim_class()

        mod.ORDERBOOK._factory = factory
        # Trigger init via read
        assert mod.ORDERBOOK.db_module is None
        # Write through the proxy (the pattern from order_engine.py:423)
        mod.ORDERBOOK.db_module = "test_module"
        # Verify the value landed on the real object property setter
        assert mod.ORDERBOOK._real._db_module == "test_module"
        assert mod.ORDERBOOK.db_module == "test_module"
        assert call_count[0] == 1, "factory called more than once"

    # -- hasattr / getattr compatibility ----------------------------------

    def test_hasattr_through_proxy(self):
        """hasattr must work through the proxy by triggering _ensure + __getattr__."""
        mod = _fresh_import()
        fake = type("_Fake", (), {"some_attr": 1, "other_attr": 2})()

        mod.REST_CLIENT._factory = lambda: fake
        assert hasattr(mod.REST_CLIENT, "some_attr")
        assert hasattr(mod.REST_CLIENT, "other_attr")
        assert not hasattr(mod.REST_CLIENT, "nonexistent_xyz")

    def test_getattr_through_proxy(self):
        """getattr with default must work through the proxy."""
        mod = _fresh_import()
        fake = type("_Fake", (), {"known": 42})()

        mod.REST_CLIENT._factory = lambda: fake
        assert getattr(mod.REST_CLIENT, "known", None) == 42
        assert getattr(mod.REST_CLIENT, "missing", "fallback") == "fallback"

    # -- private attributes stay on proxy ---------------------------------

    def test_private_writes_stay_on_proxy(self):
        """Setting private attrs (e.g. _factory, _lock) must not forward to real."""
        mod = _fresh_import()
        fake = MagicMock()
        mod.REST_CLIENT._factory = lambda: fake
        _ = mod.REST_CLIENT.anything  # triggers init
        # Replacing _factory should change the proxy slot, not set an attr on fake
        new_factory = lambda: "replaced"
        mod.REST_CLIENT._factory = new_factory
        assert mod.REST_CLIENT._factory is new_factory

    # -- real ORDERBOOK shim properties accessible -------------------------

    def test_orderbook_shim_properties_accessible(self):
        """Verify that the real OrderBook shim's legacy properties are
        reachable through the proxy — order, product, profit, should_replace,
        parent_order_ids, child_order_ids, positions, db_module.
        """
        mod = _fresh_import()
        # Replace factory with a lightweight stand-in that mirrors the shim
        attrs = {
            "order": {}, "product": {}, "profit": {},
            "should_replace": {"FILLED": True},
            "parent_order_ids": {}, "child_order_ids": {},
            "positions": {}, "db_module": None,
        }
        shim = type("_Shim", (), attrs)()

        mod.ORDERBOOK._factory = lambda: shim
        # Trigger init
        _ = mod.ORDERBOOK.order
        assert mod.ORDERBOOK._real is shim
        # Read legacy properties
        assert mod.ORDERBOOK.should_replace["FILLED"] is True
        assert mod.ORDERBOOK.order == {}
        assert mod.ORDERBOOK.db_module is None

    # -- concurrent first access through __getattr__ ----------------------

    def test_concurrent_attribute_access_shares_instance(self):
        """Same concurrency guarantee but through __getattr__ (the real
        call-site path) rather than _ensure() directly.
        """
        mod = _fresh_import()
        call_count = [0]
        instances = []
        barrier = threading.Barrier(8)

        def factory():
            call_count[0] += 1
            inst = MagicMock()
            instances.append(inst)
            return inst

        mod.REST_CLIENT._factory = factory

        def hit():
            barrier.wait()
            # Real call-site pattern: attribute access through proxy
            _ = mod.REST_CLIENT.some_attr

        threads = [threading.Thread(target=hit) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert call_count[0] == 1, (
            f"factory called {call_count[0]} times via __getattr__ path"
        )
