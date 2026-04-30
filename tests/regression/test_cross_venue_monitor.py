"""Regression tests for the ui_console CrossVenueMonitor lifecycle.

Covers:
- Start spins up all 3 venue clients in order
- Fail-soft: one venue raising during start does NOT abort the others
- Start raises when EVERY venue fails (so the caller can fall back
  to the disabled-feed UI path)
- Stop calls stop() on every started client even if one raises
- ``observe_coinbase_mids`` is no-op when disabled
- ``observe_coinbase_mids`` rate-limits writes to ~1Hz per product
- ``snapshot`` returns empty when disabled

These tests do NOT touch the network: every venue WS client is
patched to a fake that records calls and returns immediately.
"""

from __future__ import annotations

import sys
import time
import types
from typing import List, Optional

import pytest


@pytest.fixture
def fake_clients(monkeypatch):
    """Replace every external WS client class with a fake recorder.

    Returns a dict keyed by venue name with the list of constructed
    instances (each instance has ``started`` and ``stopped`` flags).
    """
    constructed: dict = {"binance_perp": [], "bybit_perp": [], "okx_swap": []}

    def _make_fake(name: str, *, raise_on_start: bool = False,
                   raise_on_construct: bool = False,
                   raise_on_stop: bool = False):
        class _FakeClient:
            def __init__(self, aggregator, **kwargs):
                if raise_on_construct:
                    raise RuntimeError(f"{name}: construct failed")
                self.aggregator = aggregator
                self.started = False
                self.stopped = False
                constructed[name].append(self)

            def start(self):
                if raise_on_start:
                    raise RuntimeError(f"{name}: start failed")
                self.started = True

            def stop(self, timeout=2.0):
                if raise_on_stop:
                    raise RuntimeError(f"{name}: stop failed")
                self.stopped = True

        return _FakeClient

    # Default: all 3 succeed. Individual tests override by re-patching.
    binance_mod = types.ModuleType("external.binance_perp_ws")
    binance_mod.BinancePerpTickerClient = _make_fake("binance_perp")
    bybit_mod = types.ModuleType("external.bybit_perp_ws")
    bybit_mod.BybitPerpTickerClient = _make_fake("bybit_perp")
    okx_mod = types.ModuleType("external.okx_swap_ws")
    okx_mod.OkxSwapTickerClient = _make_fake("okx_swap")

    monkeypatch.setitem(sys.modules, "external.binance_perp_ws", binance_mod)
    monkeypatch.setitem(sys.modules, "external.bybit_perp_ws", bybit_mod)
    monkeypatch.setitem(sys.modules, "external.okx_swap_ws", okx_mod)

    return {
        "constructed": constructed,
        "make_fake": _make_fake,
        "binance_mod": binance_mod,
        "bybit_mod": bybit_mod,
        "okx_mod": okx_mod,
    }


def _import_monitor():
    """Importing ui_console pulls in rich + websockets etc.; do it
    lazily inside each test so the monkeypatch order is right."""
    import importlib

    import ui_console
    importlib.reload(ui_console)
    return ui_console.CrossVenueMonitor


@pytest.mark.regression
def test_start_spins_up_all_three_venues(fake_clients):
    Monitor = _import_monitor()
    m = Monitor()
    m.start()
    try:
        assert m._enabled is True
        assert len(m._clients) == 3
        assert len(fake_clients["constructed"]["binance_perp"]) == 1
        assert len(fake_clients["constructed"]["bybit_perp"]) == 1
        assert len(fake_clients["constructed"]["okx_swap"]) == 1
        for venue in ("binance_perp", "bybit_perp", "okx_swap"):
            assert fake_clients["constructed"][venue][0].started is True
    finally:
        m.stop()


@pytest.mark.regression
def test_start_fail_soft_when_one_venue_raises(fake_clients, capsys):
    """Bybit construction failure must NOT prevent Binance + OKX
    from starting. Monitor stays enabled with 2/3 venues."""
    fake_clients["bybit_mod"].BybitPerpTickerClient = fake_clients[
        "make_fake"
    ]("bybit_perp", raise_on_construct=True)

    Monitor = _import_monitor()
    m = Monitor()
    m.start()
    try:
        assert m._enabled is True
        assert len(m._clients) == 2
        # The two healthy venues started; the failing one didn't get
        # appended to _clients.
        assert len(fake_clients["constructed"]["binance_perp"]) == 1
        assert len(fake_clients["constructed"]["okx_swap"]) == 1
        # Warning surfaced to stderr so the operator sees it.
        err = capsys.readouterr().err
        assert "bybit_perp" in err
    finally:
        m.stop()


@pytest.mark.regression
def test_start_raises_when_all_venues_fail(fake_clients):
    """Every venue failing must raise so the caller can render the
    'feed disabled' panel instead of an empty grid."""
    for venue, mod_key, attr in (
        ("binance_perp", "binance_mod", "BinancePerpTickerClient"),
        ("bybit_perp",   "bybit_mod",   "BybitPerpTickerClient"),
        ("okx_swap",     "okx_mod",     "OkxSwapTickerClient"),
    ):
        setattr(
            fake_clients[mod_key], attr,
            fake_clients["make_fake"](venue, raise_on_construct=True),
        )

    Monitor = _import_monitor()
    m = Monitor()
    with pytest.raises(RuntimeError, match="no external venue"):
        m.start()
    assert m._enabled is False
    assert m._clients == []


@pytest.mark.regression
def test_stop_stops_every_client_even_if_one_raises(fake_clients):
    """A buggy client raising in stop() must not prevent the other
    clients' stop() from being called."""
    fake_clients["bybit_mod"].BybitPerpTickerClient = fake_clients[
        "make_fake"
    ]("bybit_perp", raise_on_stop=True)

    Monitor = _import_monitor()
    m = Monitor()
    m.start()
    m.stop()
    assert fake_clients["constructed"]["binance_perp"][0].stopped is True
    assert fake_clients["constructed"]["okx_swap"][0].stopped is True
    # bybit raised; that's fine — the monitor swallowed it.
    assert m._enabled is False
    assert m._clients == []


@pytest.mark.regression
def test_observe_is_noop_when_disabled(fake_clients):
    Monitor = _import_monitor()
    m = Monitor()  # never start()ed
    m.observe_coinbase_mids({"BIP-20DEC30-CDE": 70_000.0})
    assert m._history == {}
    assert m.snapshot({"BIP-20DEC30-CDE": 70_000.0}) == {}


@pytest.mark.regression
def test_observe_rate_limits_to_1hz_per_product(fake_clients, monkeypatch):
    """Multiple observe calls within a 1-second window for the same
    product must produce at most one history entry."""
    Monitor = _import_monitor()

    # Stub the aggregator to always return a fresh intel snapshot, so
    # the rate-limit gate (not the data-availability gate) is what's
    # under test.
    class _StubIntel:
        consensus_mid = 70_010.0
        coinbase_premium_bps = 1.4
        cross_venue_dispersion_bps = 0.5
        fresh_venue_count = 3
        used_proxy = False

    class _StubAggregator:
        def get_intel(self, product_id, coinbase_mid=None):
            return _StubIntel()

    m = Monitor()
    m._enabled = True
    m._aggregator = _StubAggregator()

    # Freeze monotonic so all calls land in the same sample window.
    fake_now = [1_000.0]
    monkeypatch.setattr(time, "monotonic", lambda: fake_now[0])

    for _ in range(10):
        m.observe_coinbase_mids({"BIP-20DEC30-CDE": 70_000.0})

    history = m._history.get("BIP-20DEC30-CDE")
    assert history is not None
    assert len(history) == 1, "rate-limit gate should suppress repeats"

    # Advance past the 1-second sample interval; the next call should
    # add exactly one new entry.
    fake_now[0] += 1.5
    m.observe_coinbase_mids({"BIP-20DEC30-CDE": 70_000.0})
    assert len(history) == 2
