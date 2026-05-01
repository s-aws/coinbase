"""In-memory market metrics tracker — per-product Fibonacci-window averages.

Every ticker tick from the Coinbase WS feed is folded into a 1-minute bucket
per product. On request, ``snapshot()`` produces the current price and the
mean price over a curated set of Fibonacci-minute lookback windows
(``FIBONACCI_WINDOWS_MINUTES``).

Window presets
--------------
The default preset (``STANDARD_WINDOWS_MINUTES``) uses the conventional
trading timeframes — 1m, 5m, 15m, 30m, 1h, 4h, 1d, 7d — because they're
the ones every other tool (TradingView, exchange UIs, research notes)
speaks. Standard windows are easier to reason about, easier to compare
against external sources, and don't carry numerology.

A secondary preset (``FIBONACCI_WINDOWS_MINUTES``) is retained for
legacy use. It is selectable via the ``MARKET_METRICS_WINDOWS`` env var
but intentionally not surfaced in any user-facing doc — it exists for
the operator who specifically wants the older telescoping view.

Threading model
---------------
- Single ``RLock`` per tracker instance guards all internal state.
- Producers (engine ticker worker thread) call ``record(...)``.
- Consumers (dashboard server broadcast thread) call ``snapshot(...)``.
- Both methods take the lock for the duration of the call; the lock is
  never held across I/O so contention is bounded.

Data shape returned by ``snapshot()`` (verified shape — keep aligned with
``ui_console.render_market_metrics_panel`` and any other consumer)::

    {
        "BTC-USDC": {
            "price": 50_000.0,
            "as_of": 1714300000.0,        # unix seconds, last record() ts
            "windows": [
                {"minutes": 1,   "avg": 49_980.0, "delta_pct": 0.04},
                {"minutes": 3,   "avg": 49_900.0, "delta_pct": 0.20},
                ...
            ],
        },
        ...
    }

A window with no samples is omitted from ``windows``. A product with no
samples at all is omitted from the top-level dict. ``delta_pct`` is the
percent change of ``price`` vs the window mean; positive = price above
average, negative = below.
"""

from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional


# Standard trading-timeframe windows. Default for every consumer.
# 1m, 5m, 15m, 30m, 1h, 4h, 1d, 7d. If you change this, update the
# regression test in ``tests/regression/test_market_metrics_tracker.py``.
STANDARD_WINDOWS_MINUTES: tuple = (1, 5, 15, 30, 60, 240, 1440, 10080)

# Legacy Fibonacci preset, ascending. Capped at 7 days (10080m) — the
# longest window the original console showed. Not a default; selectable
# via the ``MARKET_METRICS_WINDOWS=fibonacci`` env var.
FIBONACCI_WINDOWS_MINUTES: tuple = (
    1, 2, 3, 5, 8, 13, 21, 34, 55, 89,
    144, 233, 377, 610, 987, 1597, 2584, 4181, 6765, 10080,
)

# Registry of selectable presets. Single source of truth — the resolver
# below and every consumer (server snapshot builder, console grid) MUST
# go through ``resolve_windows_preset()`` so a new preset added here
# becomes available everywhere automatically.
_PRESETS = {
    "standard":  STANDARD_WINDOWS_MINUTES,
    "fibonacci": FIBONACCI_WINDOWS_MINUTES,
}
_DEFAULT_PRESET = "standard"
_PRESET_ENV_VAR = "MARKET_METRICS_WINDOWS"

# Hard cap on retained per-product minute buckets. Anything older than
# this is pruned on the next ``record()`` so the dict stays bounded.
# Sized to the largest window across ALL presets so swapping presets
# at runtime never strands history that the new preset would have used.
_MAX_BUCKETS = max(
    max(windows) for windows in _PRESETS.values()
)


def resolve_windows_preset(name: Optional[str] = None) -> tuple:
    """Resolve a window preset by name (env-var-overridable).

    Resolution order:
        1. Explicit ``name`` argument (case-insensitive).
        2. ``$MARKET_METRICS_WINDOWS`` environment variable.
        3. ``STANDARD_WINDOWS_MINUTES``.

    Unknown names fall back to standard with a warning at import time
    rather than raising — the dashboard should never crash because
    someone typo'd an env var.
    """
    import os
    raw = name if name is not None else os.environ.get(_PRESET_ENV_VAR)
    if not raw:
        return _PRESETS[_DEFAULT_PRESET]
    key = str(raw).strip().lower()
    return _PRESETS.get(key, _PRESETS[_DEFAULT_PRESET])


class MarketMetricsTracker:
    """Thread-safe per-product price aggregator over Fibonacci windows."""

    def __init__(self) -> None:
        # product_id -> { epoch_minute -> [count, sum_price, last_price] }
        # List (not tuple) so we can mutate in place under the lock without
        # allocating a new object on every tick.
        self._buckets: Dict[str, Dict[int, List[float]]] = {}
        # product_id -> (last_price, last_ts_unix_seconds)
        self._last: Dict[str, tuple] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ record

    def record(
        self,
        product_id: str,
        price: float,
        ts: Optional[float] = None,
    ) -> None:
        """Fold one tick into the per-product buckets.

        Args:
            product_id: Trading product id (e.g. ``"BTC-USDC"``).
            price: Last traded price. Non-positive prices are ignored.
            ts: Unix seconds. Defaults to ``time.time()``.
        """
        if not product_id or price is None:
            return
        try:
            price_f = float(price)
        except (TypeError, ValueError):
            return
        if price_f <= 0:
            return

        ts_f = float(ts) if ts is not None else time.time()
        epoch_minute = int(ts_f // 60)

        with self._lock:
            product_buckets = self._buckets.get(product_id)
            if product_buckets is None:
                product_buckets = {}
                self._buckets[product_id] = product_buckets

            agg = product_buckets.get(epoch_minute)
            if agg is None:
                agg = [0.0, 0.0, price_f]  # count, sum, last
                product_buckets[epoch_minute] = agg
            agg[0] += 1.0
            agg[1] += price_f
            agg[2] = price_f

            self._last[product_id] = (price_f, ts_f)

            # Prune. ``epoch_minute`` is the latest "now"; anything older
            # than the largest window can no longer affect any snapshot.
            cutoff = epoch_minute - _MAX_BUCKETS
            if len(product_buckets) > _MAX_BUCKETS + 8:
                # Only walk the dict when it's grown past the bound;
                # otherwise the membership is already trimmed and the
                # walk is wasted work on every tick.
                stale = [m for m in product_buckets if m < cutoff]
                for m in stale:
                    product_buckets.pop(m, None)

    # ---------------------------------------------------------------- snapshot

    def snapshot(
        self,
        windows_minutes: Optional[tuple] = None,
        now_ts: Optional[float] = None,
    ) -> Dict[str, dict]:
        """Build the per-product metrics payload (see module docstring).

        Args:
            windows_minutes: Lookback windows to compute. Defaults to
                the curated Fibonacci set.
            now_ts: Unix seconds reference. Defaults to ``time.time()``.
        """
        ts_f = float(now_ts) if now_ts is not None else time.time()
        now_minute = int(ts_f // 60)
        if windows_minutes is None:
            windows_minutes = resolve_windows_preset()

        out: Dict[str, dict] = {}
        with self._lock:
            for product_id, buckets in self._buckets.items():
                if not buckets:
                    continue

                last = self._last.get(product_id)
                if not last:
                    continue
                price, last_ts = last

                windows_payload: List[dict] = []
                for w in windows_minutes:
                    # Window covers minutes [now_minute - w + 1, now_minute].
                    # Inclusive of both ends so a 1-minute window contains
                    # the current minute's bucket only.
                    lo = now_minute - int(w) + 1
                    total_count = 0.0
                    total_sum = 0.0
                    for m, agg in buckets.items():
                        if lo <= m <= now_minute:
                            total_count += agg[0]
                            total_sum += agg[1]
                    if total_count <= 0:
                        continue
                    avg = total_sum / total_count
                    delta_pct = ((price - avg) / avg) * 100.0 if avg else 0.0
                    windows_payload.append({
                        "minutes": int(w),
                        "avg": avg,
                        "delta_pct": delta_pct,
                    })

                if not windows_payload:
                    continue

                out[product_id] = {
                    "price": price,
                    "as_of": last_ts,
                    "windows": windows_payload,
                }

        return out

    # -------------------------------------------------------------- test hooks

    def _reset_for_tests(self) -> None:
        """Clear all state. Tests only — never call from production code."""
        with self._lock:
            self._buckets.clear()
            self._last.clear()


# ---------------------------------------------------------------- module-level

_singleton: Optional[MarketMetricsTracker] = None
_singleton_lock = threading.Lock()


def get_market_metrics_tracker() -> MarketMetricsTracker:
    """Return the process-wide tracker singleton.

    Engine threads (producers) and the dashboard broadcast thread
    (consumer) both go through this getter so they're guaranteed to
    share state. Lazy-init under a lock to avoid races during startup.
    """
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = MarketMetricsTracker()
    return _singleton


def warm_load_from_market_tick(
    lookback_minutes: Optional[int] = None,
    db=None,
) -> int:
    """Replay persisted ticks from ``market_tick`` into the tracker.

    Decision-support warm-up: at engine startup the in-memory tracker is
    empty, so the longer windows (1d, 7d) report nothing for hours. The
    ``business/market_tick_recorder`` already persists one downsampled
    row per product per second; replaying those rows gives the operator
    a populated view from the first broadcast.

    Caveats (these matter for honesty, not for daily ops):
      * The recorder downsamples to <=1 row/sec/product, so the recovered
        averages are *similar* but not identical to what live ticks would
        have built. Fine for decision-support, NOT for backtesting.
      * If the engine was offline for a while, the missing minutes are
        gaps. The tracker treats absent buckets as "no sample", not zero,
        so this is correct rather than misleading.
      * This function blocks the caller while it queries + replays. The
        engine startup path runs it in a worker thread for that reason
        (see ``core/order_engine.py``).

    Args:
        lookback_minutes: How far back to pull. Defaults to the largest
            window in any preset (so all configured windows can populate).
        db: Optional ``PostgresDB`` instance. Defaults to a fresh one;
            we close it on exit only if we created it.

    Returns:
        Number of rows replayed (0 on any error, by design).
    """
    if lookback_minutes is None:
        lookback_minutes = _MAX_BUCKETS

    own_db = False
    try:
        if db is None:
            from database.database import PostgresDB
            db = PostgresDB()
            own_db = True

        rows = db.execute_query(
            """
            SELECT product_id, ts, price
              FROM market_tick
             WHERE ts >= NOW() - (%s || ' minutes')::interval
               AND price IS NOT NULL
               AND price > 0
             ORDER BY ts ASC
            """,
            (str(int(lookback_minutes)),),
        ) or []
    except Exception as e:
        # Best-effort: missing table, no DB, schema drift, etc. Log and
        # return 0 — the tracker simply starts empty as it would have
        # without warm-load.
        try:
            from logging_service import get_logger
            get_logger("MarketMetrics").warning(
                f"warm_load_from_market_tick: query failed: "
                f"{type(e).__name__}: {e}"
            )
        except Exception:
            pass
        return 0
    finally:
        if own_db and db is not None:
            try:
                db.disconnect()
            except Exception:
                pass

    tracker = get_market_metrics_tracker()
    replayed = 0
    for row in rows:
        try:
            product_id = row.get("product_id")
            price = row.get("price")
            ts = row.get("ts")
            if not product_id or price is None or ts is None:
                continue
            # ``ts`` is a datetime; convert to unix seconds. Recorder
            # writes UTC (datetime.utcfromtimestamp), so timestamp() is
            # unambiguous here even on hosts in non-UTC zones.
            tracker.record(product_id, float(price), ts=ts.timestamp())
            replayed += 1
        except Exception:
            continue
    return replayed
