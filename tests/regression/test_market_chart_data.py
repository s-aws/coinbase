"""Regression: 1m candle store + chart-history reader.

Pins:
* ``upsert_candles`` skips malformed rows, normalises ``start`` to a UTC
  bucket timestamp, and uses ``ON CONFLICT DO UPDATE``.
* ``get_market_chart_history`` validates inputs, returns oldest-first
  ticks/candles, and unpacks reprice events from the JSONB column.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List

import pytest


# ----- Fake DB ----------------------------------------------------------------

class _FakeCursor:
    def __init__(self, store, query_results):
        self._store = store
        self._query_results = query_results

    def execute(self, sql, params=None):
        self._store.append(("execute", sql, params))
        # Hand back queued results for read queries.
        for matcher, rows in self._query_results:
            if matcher in sql:
                self._last_rows = rows
                self._last_cols = list(rows[0].keys()) if rows else []
                return
        self._last_rows = []
        self._last_cols = []

    def executemany(self, sql, seq):
        self._store.append(("executemany", sql, list(seq)))

    @property
    def description(self):
        return [(c,) for c in getattr(self, "_last_cols", [])]

    def fetchall(self):
        rows = getattr(self, "_last_rows", [])
        return [tuple(r[c] for c in self._last_cols) for r in rows]


class _FakeDB:
    def __init__(self, query_results=None):
        self.calls: List = []
        self._query_results = query_results or []

    @contextmanager
    def get_cursor(self):
        yield _FakeCursor(self.calls, self._query_results)

    def execute_query(self, sql, params=None):
        self.calls.append(("execute_query", sql, params))
        for matcher, rows in self._query_results:
            if matcher in sql:
                return rows
        return []

    def disconnect(self):
        pass


# ----- candle store -----------------------------------------------------------

def test_upsert_candles_skips_malformed_rows():
    from database import market_candle_store as mod
    mod._reset_for_tests()
    db = _FakeDB()

    candles = [
        {"start": "1714377600", "open": "100", "high": "101", "low": "99",
         "close": "100.5", "volume": "12.5"},
        {"start": "1714377660", "open": "100.5", "high": "102", "low": "100",
         "close": "101", "volume": "9.0"},
        {"open": "1", "close": "2"},               # missing start
        {"start": "1714377720", "open": "1"},       # missing close
        {"start": "not-a-number", "close": "5"},   # bad start
    ]
    n = mod.upsert_candles("BTC-USDC", candles, db=db)
    assert n == 2
    # One DDL + one executemany batch.
    kinds = [c[0] for c in db.calls]
    assert "execute" in kinds        # DDL
    assert "executemany" in kinds
    batch = next(c for c in db.calls if c[0] == "executemany")[2]
    assert len(batch) == 2
    # bucket_ts should be a naive UTC datetime.
    for row in batch:
        assert isinstance(row[1], datetime)
        assert row[1].tzinfo is None


def test_upsert_candles_returns_zero_for_empty_input():
    from database import market_candle_store as mod
    mod._reset_for_tests()
    db = _FakeDB()
    assert mod.upsert_candles("BTC-USDC", [], db=db) == 0
    # No DDL needed when there's nothing to write.
    assert db.calls == []


def test_upsert_candles_uses_on_conflict_do_update():
    """Idempotency rule pinned at the SQL level."""
    from database import market_candle_store as mod
    mod._reset_for_tests()
    db = _FakeDB()
    mod.upsert_candles("BTC-USDC", [
        {"start": "1714377600", "open": "1", "high": "1", "low": "1",
         "close": "1", "volume": "1"},
    ], db=db)
    em = next(c for c in db.calls if c[0] == "executemany")
    sql = em[1]
    assert "ON CONFLICT (product_id, bucket_ts) DO UPDATE" in sql


def test_upsert_candles_rejects_blank_product_id():
    from database import market_candle_store as mod
    mod._reset_for_tests()
    db = _FakeDB()
    assert mod.upsert_candles("", [{"start": "1", "close": "1"}], db=db) == 0


# ----- chart history reader ---------------------------------------------------

def test_get_market_chart_history_validates_inputs(monkeypatch):
    from database import market_chart_helpers as mod
    monkeypatch.setattr(mod, "PostgresDB", lambda: _FakeDB())

    with pytest.raises(ValueError):
        mod.get_market_chart_history("")
    with pytest.raises(ValueError):
        mod.get_market_chart_history("BTC-USDC", window_minutes=0)
    with pytest.raises(ValueError):
        mod.get_market_chart_history("BTC-USDC", max_tick_points=0)


def test_get_market_chart_history_shapes_payload(monkeypatch):
    from database import market_chart_helpers as mod

    now = datetime(2026, 4, 29, 12, 0, 0)
    tick_rows = [
        {"ts": now,                     "price": Decimal("78000"),
         "best_bid": Decimal("77995"),  "best_ask": Decimal("78005")},
        {"ts": now - timedelta(seconds=30), "price": Decimal("77990"),
         "best_bid": Decimal("77985"),  "best_ask": Decimal("77995")},
    ]
    candle_rows = [
        {"bucket_ts": now - timedelta(minutes=5),
         "open": Decimal("77900"), "high": Decimal("78010"),
         "low": Decimal("77890"),  "close": Decimal("78000"),
         "volume": Decimal("1.5")},
    ]
    reprice_rows = [
        {"stealth_order_id": "abc-123",
         "ts": now - timedelta(minutes=2),
         "from_price": Decimal("77800"), "to_price": Decimal("77850"),
         "source": "midpoint"},
    ]
    fake = _FakeDB(query_results=[
        ("FROM market_tick", tick_rows),
        ("FROM market_candle_1m", candle_rows),
        ("FROM stealth_orders", reprice_rows),
    ])
    monkeypatch.setattr(mod, "PostgresDB", lambda: fake)

    out = mod.get_market_chart_history("BTC-USDC", window_minutes=30)
    assert out["product_id"] == "BTC-USDC"
    assert out["window_minutes"] == 30
    # Ticks must be returned oldest-first (the SQL is DESC + reverse).
    assert len(out["ticks"]) == 2
    assert out["ticks"][0]["ts"] < out["ticks"][1]["ts"]
    assert out["ticks"][0]["price"] == 77990.0
    assert out["ticks"][0]["best_bid"] == 77985.0
    # Candles oldest-first by SQL order.
    assert len(out["candles"]) == 1
    assert out["candles"][0]["close"] == 78000.0
    # Reprices unpacked from JSONB.
    assert len(out["anchor_reprices"]) == 1
    assert out["anchor_reprices"][0]["stealth_order_id"] == "abc-123"
    assert out["anchor_reprices"][0]["from_price"] == 77800.0
    assert out["anchor_reprices"][0]["to_price"] == 77850.0
    assert out["anchor_reprices"][0]["source"] == "midpoint"
