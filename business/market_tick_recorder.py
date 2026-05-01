"""Persistent market-tick recorder for slide-calibration analytics.

Subscribes to the existing WebSocket ticker fan-out in ``core/order_engine``
and writes one downsampled row per product per second to ``market_tick``.
Used by the (forthcoming) slide-calibration chart to draw a market-mid
reference line and a "miss-distance" band around the anchor.

Why this module exists
----------------------
* The engine already receives ticker updates many times per second per
  product (Coinbase's ticker channel), but doesn't persist them. The
  slide-calibration view needs a market reference to compare against
  ``stealth_orders.anchor_repricing_state_json -> reprice_history``.
* We deliberately downsample at the recorder rather than backfilling
  from the public REST API: persisting what *the engine actually saw*
  matches the prices the anchor reacted to, while REST trades/candles
  are subtly different (trade prints, not ticker snapshots).

Design
------
* Lazy table creation on first ``record()`` call (mirrors the
  ``business/fill_ledger.py`` pattern). One DDL per process.
* In-memory throttle keyed by ``product_id``: at most one row per
  ``min_interval_seconds`` (default 1.0) per product. Cheap dict lookup,
  no DB round-trip on the hot path.
* Best-effort write: any exception is logged and swallowed. Tick recording
  must never delay or crash the ticker worker.
* Reads use the shared ``DB_CLIENT`` (whose cursor lock from 2026-04-28
  serialises cross-thread access).
* Retention sweep runs in a daemon thread, deleting rows older than
  ``retention_days`` every ``sweep_interval_seconds``. Default 7 days.

Schema
------
Single row per (product_id, ts_floor_seconds):

    market_tick (
        id          BIGSERIAL PRIMARY KEY,
        product_id  VARCHAR(32) NOT NULL,
        ts          TIMESTAMP   NOT NULL,
        price       NUMERIC(16,2),
        best_bid    NUMERIC(16,2),
        best_ask    NUMERIC(16,2)
    )

with a (product_id, ts) descending index for "last N minutes" queries.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Optional

from logging_service import get_logger
from database.database import PostgresDB

logger = get_logger("MarketTickRecorder")


_DEFAULT_MIN_INTERVAL_S = 1.0
_DEFAULT_RETENTION_DAYS = 7
_DEFAULT_SWEEP_INTERVAL_S = 3600


class MarketTickRecorder:
    """Downsampled persister for ticker updates.

    Thread-safe. Construct once, share across the ticker worker.
    """

    def __init__(
        self,
        db: Optional[PostgresDB] = None,
        min_interval_seconds: float = _DEFAULT_MIN_INTERVAL_S,
        retention_days: int = _DEFAULT_RETENTION_DAYS,
        sweep_interval_seconds: int = _DEFAULT_SWEEP_INTERVAL_S,
    ) -> None:
        if min_interval_seconds < 0:
            raise ValueError("min_interval_seconds must be non-negative")
        if retention_days <= 0:
            raise ValueError("retention_days must be positive")
        if sweep_interval_seconds <= 0:
            raise ValueError("sweep_interval_seconds must be positive")

        # Defer the default to call time so test fixtures can monkeypatch
        # ``database.order.DB_CLIENT`` and have us pick it up.
        if db is None:
            from database.order import DB_CLIENT
            db = DB_CLIENT
        self._db = db
        self._min_interval_seconds = float(min_interval_seconds)
        self._retention_days = int(retention_days)
        self._sweep_interval_seconds = int(sweep_interval_seconds)

        self._last_recorded_at: dict[str, float] = {}
        self._throttle_lock = threading.Lock()
        self._table_ready = False
        self._table_lock = threading.Lock()

        self._sweep_thread: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()

    # ------------------------------------------------------------------ DDL

    def _ensure_table(self) -> None:
        """Idempotently create ``market_tick`` and its index.

        Guarded by a lock + sticky boolean so concurrent ticker workers
        don't race to issue the DDL repeatedly.
        """
        if self._table_ready:
            return
        with self._table_lock:
            if self._table_ready:
                return
            ddl = """
                CREATE TABLE IF NOT EXISTS market_tick (
                    id          BIGSERIAL PRIMARY KEY,
                    product_id  VARCHAR(32) NOT NULL,
                    ts          TIMESTAMP   NOT NULL,
                    price       NUMERIC(16,2),
                    best_bid    NUMERIC(16,2),
                    best_ask    NUMERIC(16,2)
                );
                CREATE INDEX IF NOT EXISTS idx_market_tick_product_ts
                    ON market_tick (product_id, ts DESC);
                CREATE INDEX IF NOT EXISTS idx_market_tick_ts
                    ON market_tick (ts);
            """
            with self._db.get_cursor() as cursor:
                cursor.execute(ddl)
            self._table_ready = True

    # ------------------------------------------------------------------ hot path

    def record(
        self,
        product_id: str,
        price: Optional[float],
        best_bid: Optional[float] = None,
        best_ask: Optional[float] = None,
        now: Optional[float] = None,
    ) -> bool:
        """Persist a single tick if the per-product throttle allows.

        Args:
            product_id: e.g. ``"BTC-USDC"`` or ``"BIT-29MAY26-CDE"``.
            price: Last/mark price from the ticker payload.
            best_bid: L1 best bid, optional.
            best_ask: L1 best ask, optional.
            now: Override "now" (seconds, monotonic-comparable). Used by tests.

        Returns:
            True if a row was written, False if throttled or skipped.
        """
        if not product_id or price is None or price <= 0:
            return False

        ts = time.time() if now is None else float(now)

        with self._throttle_lock:
            last = self._last_recorded_at.get(product_id, 0.0)
            if (ts - last) < self._min_interval_seconds:
                return False
            self._last_recorded_at[product_id] = ts

        try:
            self._ensure_table()
            wall_ts = datetime.utcfromtimestamp(ts)
            with self._db.get_cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO market_tick
                        (product_id, ts, price, best_bid, best_ask)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (product_id, wall_ts, price, best_bid, best_ask),
                )
            return True
        except Exception as e:
            # Best-effort: never let tick persistence break the engine.
            logger.warning(
                f"market_tick insert failed for {product_id}: "
                f"{type(e).__name__}: {e}"
            )
            return False

    # ------------------------------------------------------------------ retention

    def sweep_once(self) -> int:
        """Delete rows older than ``retention_days``. Returns row count."""
        try:
            self._ensure_table()
            with self._db.get_cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM market_tick
                     WHERE ts < NOW() - (%s || ' days')::interval
                    """,
                    (str(self._retention_days),),
                )
                return cursor.rowcount or 0
        except Exception as e:
            logger.warning(f"market_tick retention sweep failed: {e}")
            return 0

    def start_retention_sweeper(self) -> None:
        """Spawn a daemon thread that periodically deletes stale rows."""
        if self._sweep_thread and self._sweep_thread.is_alive():
            return

        def _loop() -> None:
            # Windows main-thread signal handling: short polling waits so
            # SIGINT can wake the sweeper without an unbounded park.
            # See /memories/windows-signal-event-wait.md.
            while not self._shutdown_event.is_set():
                deleted = self.sweep_once()
                if deleted:
                    logger.info(f"market_tick retention: removed {deleted} rows")
                # Poll in 0.5s slices up to the configured interval.
                slept = 0.0
                while slept < self._sweep_interval_seconds:
                    if self._shutdown_event.wait(timeout=0.5):
                        return
                    slept += 0.5

        self._sweep_thread = threading.Thread(
            target=_loop,
            name="market-tick-retention",
            daemon=True,
        )
        self._sweep_thread.start()

    def stop(self) -> None:
        """Signal the retention sweeper to exit."""
        self._shutdown_event.set()


# Module-level singleton for the running engine. ``None`` when no engine
# is wired (e.g. test imports). Accessed via ``get_recorder()`` so callers
# get a no-op when the engine isn't running.
_RECORDER: Optional[MarketTickRecorder] = None
_RECORDER_LOCK = threading.Lock()


def get_recorder() -> Optional[MarketTickRecorder]:
    """Return the process-wide recorder, or ``None`` if not initialised."""
    return _RECORDER


def init_recorder(
    min_interval_seconds: float = _DEFAULT_MIN_INTERVAL_S,
    retention_days: int = _DEFAULT_RETENTION_DAYS,
    sweep_interval_seconds: int = _DEFAULT_SWEEP_INTERVAL_S,
    start_sweeper: bool = True,
) -> MarketTickRecorder:
    """Initialise (or reuse) the singleton recorder and start its sweeper.

    Idempotent: subsequent calls return the existing instance and do not
    re-spawn the sweep thread.
    """
    global _RECORDER
    with _RECORDER_LOCK:
        if _RECORDER is None:
            _RECORDER = MarketTickRecorder(
                min_interval_seconds=min_interval_seconds,
                retention_days=retention_days,
                sweep_interval_seconds=sweep_interval_seconds,
            )
            if start_sweeper:
                _RECORDER.start_retention_sweeper()
        return _RECORDER


def reset_recorder_for_tests() -> None:
    """Tear down the singleton. Tests only."""
    global _RECORDER
    with _RECORDER_LOCK:
        if _RECORDER is not None:
            _RECORDER.stop()
        _RECORDER = None
