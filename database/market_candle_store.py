"""1-minute OHLC candle persistence for slide-calibration backfill.

Provides a tiny table + insert helper used by
``genai_tools/backfill_candles.py`` to populate historical market context
before the live ``MarketTickRecorder`` has accumulated a day of data.

Why a separate table from ``market_tick``
-----------------------------------------
* ``market_tick`` is high-frequency (~1 row/sec/product) and authoritative
  for what *the engine actually saw*. Subject to a 7-day retention sweep.
* ``market_candle_1m`` is low-frequency (1 row/min/product), populated
  from Coinbase's public REST endpoint, and intended as a long-lived
  archival fallback. The chart prefers ticks when present and falls back
  to candle close prices for any minute where no tick exists.

Schema
------
    market_candle_1m (
        product_id  VARCHAR(32) NOT NULL,
        bucket_ts   TIMESTAMP   NOT NULL,   -- minute boundary, UTC
        open        NUMERIC(16,2),
        high        NUMERIC(16,2),
        low         NUMERIC(16,2),
        close       NUMERIC(16,2),
        volume      NUMERIC(20,8),
        PRIMARY KEY (product_id, bucket_ts)
    )

Idempotent: re-running the backfill for an overlapping window does
``ON CONFLICT DO UPDATE`` so values are refreshed without duplicates.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Iterable, Mapping, Optional

from logging_service import get_logger
from database.database import PostgresDB

logger = get_logger("MarketCandleStore")


_TABLE_READY = False
_TABLE_LOCK = threading.Lock()


def _ensure_table(db: PostgresDB) -> None:
    """Lazy DDL: create ``market_candle_1m`` if missing."""
    global _TABLE_READY
    if _TABLE_READY:
        return
    with _TABLE_LOCK:
        if _TABLE_READY:
            return
        ddl = """
            CREATE TABLE IF NOT EXISTS market_candle_1m (
                product_id  VARCHAR(32) NOT NULL,
                bucket_ts   TIMESTAMP   NOT NULL,
                open        NUMERIC(16,2),
                high        NUMERIC(16,2),
                low         NUMERIC(16,2),
                close       NUMERIC(16,2),
                volume      NUMERIC(20,8),
                PRIMARY KEY (product_id, bucket_ts)
            );
            CREATE INDEX IF NOT EXISTS idx_market_candle_1m_bucket_ts
                ON market_candle_1m (bucket_ts);
        """
        with db.get_cursor() as cursor:
            cursor.execute(ddl)
        _TABLE_READY = True


def _reset_for_tests() -> None:
    """Test hook: undo the sticky DDL flag."""
    global _TABLE_READY
    with _TABLE_LOCK:
        _TABLE_READY = False


def _coerce(v):
    """Coinbase candle fields arrive as strings; convert to float / None."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def upsert_candles(
    product_id: str,
    candles: Iterable[Mapping[str, object]],
    db: Optional[PostgresDB] = None,
) -> int:
    """Persist a batch of Coinbase candles for ``product_id``.

    Args:
        product_id: Instrument id (e.g. ``"BTC-USDC"``).
        candles: Iterable of dicts shaped per ``CoinbaseRestClient.get_candles``
            return value: ``{"start": "<unix-seconds>", "open": "...",
            "high": "...", "low": "...", "close": "...", "volume": "..."}``.
        db: Optional PostgresDB; defaults to the shared ``DB_CLIENT``.

    Returns:
        Number of rows written / updated. Skips rows missing ``start`` or
        ``close`` (both required for the calibration chart).
    """
    if not product_id:
        return 0
    if db is None:
        from database.order import DB_CLIENT
        db = DB_CLIENT

    rows: list[tuple] = []
    for c in candles:
        start = c.get("start")
        close = c.get("close")
        if start is None or close is None:
            continue
        try:
            bucket_ts = datetime.fromtimestamp(int(start), tz=timezone.utc).replace(tzinfo=None)
        except (TypeError, ValueError):
            continue
        rows.append((
            product_id,
            bucket_ts,
            _coerce(c.get("open")),
            _coerce(c.get("high")),
            _coerce(c.get("low")),
            _coerce(close),
            _coerce(c.get("volume")),
        ))
    if not rows:
        return 0

    _ensure_table(db)
    with db.get_cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO market_candle_1m
                (product_id, bucket_ts, open, high, low, close, volume)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (product_id, bucket_ts) DO UPDATE SET
                open   = EXCLUDED.open,
                high   = EXCLUDED.high,
                low    = EXCLUDED.low,
                close  = EXCLUDED.close,
                volume = EXCLUDED.volume
            """,
            rows,
        )
    logger.info(f"Upserted {len(rows)} 1m candles for {product_id}")
    return len(rows)
