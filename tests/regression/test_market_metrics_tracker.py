"""Regression tests for business.market_metrics.MarketMetricsTracker.

The tracker is a pure-in-memory aggregator with no external dependencies.
These tests pin down:
 - bucket aggregation across minutes
 - window math (mean of all samples whose minute falls inside the window)
 - delta_pct sign (current vs avg)
 - empty-product / unknown-window behavior
 - producer/consumer contract — keys returned by ``snapshot()`` are exactly
   what ``ui_console.render_market_metrics_panel`` reads. If you rename
   any of these, both ends must move together (P2 rule #12).
"""

import pytest

from business.market_metrics import (
    FIBONACCI_WINDOWS_MINUTES,
    STANDARD_WINDOWS_MINUTES,
    MarketMetricsTracker,
    resolve_windows_preset,
)


@pytest.fixture
def tracker():
    return MarketMetricsTracker()


def _ts_minute(m: int) -> float:
    """Return a unix-second value whose floor//60 == ``m``."""
    return float(m * 60 + 30)  # mid-minute to avoid boundary surprises


def test_record_and_snapshot_single_product(tracker):
    # 1m ago: 100, 102. now: 110.
    tracker.record("BTC-USDC", 100.0, ts=_ts_minute(99))
    tracker.record("BTC-USDC", 102.0, ts=_ts_minute(99))
    tracker.record("BTC-USDC", 110.0, ts=_ts_minute(100))

    # Pin Fibonacci to retain the original 1m / 2m verification — those
    # windows aren't both in the standard preset (which has 1m and 5m).
    snap = tracker.snapshot(
        windows_minutes=FIBONACCI_WINDOWS_MINUTES,
        now_ts=_ts_minute(100),
    )
    assert "BTC-USDC" in snap
    entry = snap["BTC-USDC"]
    assert entry["price"] == 110.0
    # 1-minute window: only the current minute's bucket -> 110.
    win1 = next(w for w in entry["windows"] if w["minutes"] == 1)
    assert win1["avg"] == pytest.approx(110.0)
    assert win1["delta_pct"] == pytest.approx(0.0)
    # 2-minute window: includes minutes 99 and 100 -> (100+102+110)/3 = 104.
    win2 = next(w for w in entry["windows"] if w["minutes"] == 2)
    assert win2["avg"] == pytest.approx(104.0)
    # Current price 110 vs avg 104 -> +5.769%.
    assert win2["delta_pct"] == pytest.approx(((110 - 104) / 104) * 100.0)


def test_snapshot_keys_match_consumer_contract(tracker):
    """Producer/consumer contract guard.

    ``ui_console.render_market_metrics_panel`` reads these exact keys.
    If this test fails, you renamed a field on the producer side and
    must update the console consumer too.
    """
    tracker.record("ETH-USDC", 50.0, ts=_ts_minute(0))
    snap = tracker.snapshot(now_ts=_ts_minute(0))
    entry = snap["ETH-USDC"]
    assert set(entry.keys()) == {"price", "as_of", "windows"}
    win = entry["windows"][0]
    assert set(win.keys()) == {"minutes", "avg", "delta_pct"}


def test_negative_delta_when_price_below_average(tracker):
    tracker.record("BTC-USDC", 100.0, ts=_ts_minute(0))
    tracker.record("BTC-USDC", 200.0, ts=_ts_minute(0))
    tracker.record("BTC-USDC", 90.0, ts=_ts_minute(0))  # last
    snap = tracker.snapshot(now_ts=_ts_minute(0))
    win1 = next(w for w in snap["BTC-USDC"]["windows"] if w["minutes"] == 1)
    # avg = 130, price = 90 -> negative delta.
    assert win1["delta_pct"] < 0


def test_unknown_product_omitted(tracker):
    snap = tracker.snapshot()
    assert snap == {}


def test_non_positive_price_ignored(tracker):
    tracker.record("BTC-USDC", 0, ts=_ts_minute(0))
    tracker.record("BTC-USDC", -1, ts=_ts_minute(0))
    tracker.record("BTC-USDC", None, ts=_ts_minute(0))
    assert tracker.snapshot() == {}


def test_old_buckets_dont_affect_short_windows(tracker):
    # Big spike 100 minutes ago, calm price now.
    tracker.record("BTC-USDC", 1000.0, ts=_ts_minute(0))
    tracker.record("BTC-USDC", 50.0, ts=_ts_minute(100))
    snap = tracker.snapshot(
        windows_minutes=FIBONACCI_WINDOWS_MINUTES,
        now_ts=_ts_minute(100),
    )
    win1 = next(w for w in snap["BTC-USDC"]["windows"] if w["minutes"] == 1)
    assert win1["avg"] == pytest.approx(50.0)
    # 144-minute window covers both samples -> avg=525, big delta.
    win144 = next(w for w in snap["BTC-USDC"]["windows"] if w["minutes"] == 144)
    assert win144["avg"] == pytest.approx(525.0)


def test_windows_are_canonical_fibonacci_set(tracker):
    """Pin the Fibonacci sequence so a refactor can't silently change
    the legacy preset."""
    assert FIBONACCI_WINDOWS_MINUTES == (
        1, 2, 3, 5, 8, 13, 21, 34, 55, 89,
        144, 233, 377, 610, 987, 1597, 2584, 4181, 6765, 10080,
    )


def test_standard_windows_are_conventional_timeframes():
    """Standard preset = the timeframes every other tool speaks."""
    assert STANDARD_WINDOWS_MINUTES == (1, 5, 15, 30, 60, 240, 1440, 10080)


def test_default_preset_is_standard(monkeypatch):
    monkeypatch.delenv("MARKET_METRICS_WINDOWS", raising=False)
    assert resolve_windows_preset() == STANDARD_WINDOWS_MINUTES


def test_env_var_selects_fibonacci(monkeypatch):
    monkeypatch.setenv("MARKET_METRICS_WINDOWS", "fibonacci")
    assert resolve_windows_preset() == FIBONACCI_WINDOWS_MINUTES


def test_env_var_case_insensitive(monkeypatch):
    monkeypatch.setenv("MARKET_METRICS_WINDOWS", "  FIBONACCI  ")
    assert resolve_windows_preset() == FIBONACCI_WINDOWS_MINUTES


def test_unknown_preset_falls_back_to_standard(monkeypatch):
    monkeypatch.setenv("MARKET_METRICS_WINDOWS", "definitely-not-real")
    # Falls back rather than raising — dashboard must never crash on a
    # typo'd env var.
    assert resolve_windows_preset() == STANDARD_WINDOWS_MINUTES


def test_explicit_arg_overrides_env(monkeypatch):
    monkeypatch.setenv("MARKET_METRICS_WINDOWS", "fibonacci")
    assert resolve_windows_preset("standard") == STANDARD_WINDOWS_MINUTES


def test_snapshot_uses_resolved_preset_by_default(tracker, monkeypatch):
    """With no override, snapshot must produce the standard 8 windows."""
    monkeypatch.delenv("MARKET_METRICS_WINDOWS", raising=False)
    tracker.record("BTC-USDC", 100.0, ts=_ts_minute(0))
    snap = tracker.snapshot(now_ts=_ts_minute(0))
    minutes = {w["minutes"] for w in snap["BTC-USDC"]["windows"]}
    assert minutes == set(STANDARD_WINDOWS_MINUTES)


def test_singleton_returns_same_instance():
    from business.market_metrics import get_market_metrics_tracker
    a = get_market_metrics_tracker()
    b = get_market_metrics_tracker()
    assert a is b


def test_warm_load_replays_rows_into_tracker(monkeypatch):
    """warm_load_from_market_tick should fold every persisted row into
    the singleton tracker without touching the live DB."""
    from datetime import datetime, timedelta
    from business import market_metrics

    fake_now = datetime.utcnow()
    fake_rows = [
        {"product_id": "BTC-USDC", "ts": fake_now - timedelta(minutes=10), "price": 50_000.0},
        {"product_id": "BTC-USDC", "ts": fake_now - timedelta(minutes=5),  "price": 50_500.0},
        {"product_id": "BTC-USDC", "ts": fake_now,                          "price": 50_250.0},
    ]

    class _FakeDB:
        def execute_query(self, sql, params):
            assert "market_tick" in sql.lower()
            return fake_rows

        def disconnect(self):
            pass

    market_metrics._singleton = None  # force fresh singleton
    n = market_metrics.warm_load_from_market_tick(db=_FakeDB())
    assert n == len(fake_rows)

    snap = market_metrics.get_market_metrics_tracker().snapshot(
        windows_minutes=(1, 5, 15),
        now_ts=fake_now.timestamp(),
    )
    assert "BTC-USDC" in snap
    # Current price is the most-recent replayed row.
    assert snap["BTC-USDC"]["price"] == pytest.approx(50_250.0)


def test_warm_load_returns_zero_on_db_error():
    from business import market_metrics

    class _BrokenDB:
        def execute_query(self, sql, params):
            raise RuntimeError("simulated DB outage")

        def disconnect(self):
            pass

    market_metrics._singleton = None
    # Must not raise; returns 0 so the engine can start anyway.
    assert market_metrics.warm_load_from_market_tick(db=_BrokenDB()) == 0
