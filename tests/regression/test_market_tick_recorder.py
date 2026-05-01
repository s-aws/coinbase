"""Regression: market-tick recorder throttle, table creation, and retention.

The recorder feeds the slide-calibration chart. Its contract is:
1. Throttle: at most one row per ``min_interval_seconds`` per product.
2. Lazy DDL: ``market_tick`` table is created on first ``record()`` call,
   not at import time.
3. Best-effort: any DB exception is swallowed (never breaks the engine).
4. Idempotent init: ``init_recorder()`` returns the same singleton.
5. Retention: ``sweep_once()`` issues a parameterised DELETE.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, List

import pytest


# ----- Fake DB ----------------------------------------------------------------

class _FakeCursor:
    def __init__(self, store: list[tuple[str, tuple]]):
        self._store = store
        self.rowcount = 0

    def execute(self, sql: str, params: tuple = ()) -> None:
        self._store.append((sql, params))
        # DELETE returns a rowcount; everything else is treated as 0.
        if sql.strip().upper().startswith("DELETE"):
            self.rowcount = 3


class _FakeDB:
    def __init__(self) -> None:
        self.executed: List[tuple[str, tuple]] = []
        self.fail_next = False

    @contextmanager
    def get_cursor(self):
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("simulated DB failure")
        yield _FakeCursor(self.executed)


@pytest.fixture
def fake_db():
    return _FakeDB()


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Ensure each test starts with a clean module-level recorder."""
    from business.market_tick_recorder import reset_recorder_for_tests
    reset_recorder_for_tests()
    yield
    reset_recorder_for_tests()


# ----- Tests ------------------------------------------------------------------

def test_throttle_allows_one_row_per_interval(fake_db):
    from business.market_tick_recorder import MarketTickRecorder
    rec = MarketTickRecorder(db=fake_db, min_interval_seconds=1.0)

    assert rec.record("BTC-USDC", price=100.0, now=10.0) is True
    # Second call within 1s window: throttled.
    assert rec.record("BTC-USDC", price=101.0, now=10.5) is False
    # Beyond the window: writes again.
    assert rec.record("BTC-USDC", price=102.0, now=11.5) is True

    inserts = [s for s, _ in fake_db.executed if "INSERT INTO market_tick" in s]
    assert len(inserts) == 2


def test_throttle_is_per_product(fake_db):
    """One product's recent write must not block another product."""
    from business.market_tick_recorder import MarketTickRecorder
    rec = MarketTickRecorder(db=fake_db, min_interval_seconds=1.0)

    assert rec.record("BTC-USDC", price=100.0, now=10.0) is True
    assert rec.record("ETH-USDC", price=3000.0, now=10.1) is True
    assert rec.record("BIT-29MAY26-CDE", price=78000.0, now=10.2) is True

    inserts = [s for s, _ in fake_db.executed if "INSERT INTO market_tick" in s]
    assert len(inserts) == 3


def test_lazy_table_creation_runs_once(fake_db):
    """DDL is issued the first time record() runs and not again."""
    from business.market_tick_recorder import MarketTickRecorder
    rec = MarketTickRecorder(db=fake_db, min_interval_seconds=0.0)

    rec.record("BTC-USDC", price=100.0, now=1.0)
    rec.record("BTC-USDC", price=101.0, now=2.0)
    rec.record("BTC-USDC", price=102.0, now=3.0)

    ddl = [s for s, _ in fake_db.executed if "CREATE TABLE IF NOT EXISTS market_tick" in s]
    assert len(ddl) == 1


def test_invalid_inputs_skip_silently(fake_db):
    from business.market_tick_recorder import MarketTickRecorder
    rec = MarketTickRecorder(db=fake_db, min_interval_seconds=0.0)
    assert rec.record("", price=100.0) is False
    assert rec.record("BTC-USDC", price=None) is False
    assert rec.record("BTC-USDC", price=0.0) is False
    assert rec.record("BTC-USDC", price=-1.0) is False
    assert fake_db.executed == []


def test_db_failure_is_swallowed(fake_db):
    """Recorder must never propagate exceptions to the ticker worker."""
    from business.market_tick_recorder import MarketTickRecorder
    rec = MarketTickRecorder(db=fake_db, min_interval_seconds=0.0)
    fake_db.fail_next = True
    # Should not raise.
    assert rec.record("BTC-USDC", price=100.0, now=1.0) is False
    # Subsequent call still works.
    assert rec.record("BTC-USDC", price=101.0, now=2.0) is True


def test_init_recorder_is_idempotent(monkeypatch, fake_db):
    """Multiple init calls return the same instance and don't double-spawn."""
    from business import market_tick_recorder as mod
    # Patch the default-DB resolution path so the singleton uses fake_db.
    import database.order as order_mod
    monkeypatch.setattr(order_mod, "DB_CLIENT", fake_db, raising=True)

    a = mod.init_recorder(start_sweeper=False)
    b = mod.init_recorder(start_sweeper=False)
    assert a is b
    assert isinstance(a, mod.MarketTickRecorder)


def test_sweep_once_issues_parameterised_delete(fake_db):
    from business.market_tick_recorder import MarketTickRecorder
    rec = MarketTickRecorder(db=fake_db, retention_days=7)
    deleted = rec.sweep_once()
    # _FakeCursor returns 3 for DELETE statements (see fixture).
    assert deleted == 3
    deletes = [(s, p) for s, p in fake_db.executed if "DELETE FROM market_tick" in s]
    assert len(deletes) == 1
    sql, params = deletes[0]
    assert params == ("7",)


def test_constructor_validates_args(fake_db):
    from business.market_tick_recorder import MarketTickRecorder
    with pytest.raises(ValueError):
        MarketTickRecorder(db=fake_db, min_interval_seconds=-1)
    with pytest.raises(ValueError):
        MarketTickRecorder(db=fake_db, retention_days=0)
    with pytest.raises(ValueError):
        MarketTickRecorder(db=fake_db, sweep_interval_seconds=0)


def test_get_recorder_returns_none_until_init():
    from business.market_tick_recorder import get_recorder
    assert get_recorder() is None
