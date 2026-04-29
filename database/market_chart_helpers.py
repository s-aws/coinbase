"""Chart-data reader for the slide-calibration phase-2 view.

Returns a per-product time series payload combining:

* **Live ticks** from ``market_tick`` (authoritative for what the engine saw)
* **1-minute candle closes** from ``market_candle_1m`` for any minute
  in the window where no tick exists (fallback, populated by
  ``genai_tools/backfill_candles.py``)
* **Anchor reprice events** from
  ``stealth_orders.anchor_repricing_state_json -> 'reprice_history'``,
  one entry per reprice with from/to prices and source tag

The chart UI overlays the market price (ticks/candle closes) against the
anchor step-line so the operator can see how often the market left the
anchor's slide envelope.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from database.database import PostgresDB


def _f(v, default: float = 0.0) -> float:
    if v is None:
        return default
    if isinstance(v, Decimal):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _iso(ts) -> Optional[str]:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts.isoformat()
    return str(ts)


def _read_ticks(
    db: PostgresDB,
    product_id: str,
    window_minutes: int,
    max_points: int,
) -> List[Dict[str, Any]]:
    """Last ``window_minutes`` of recorded ticks, oldest-first.

    Hard caps the row count to ``max_points`` for transport sanity. If
    the window holds more, we read every Nth row by selecting the most
    recent ``max_points`` and reversing.
    """
    sql = """
        SELECT ts, price, best_bid, best_ask
          FROM market_tick
         WHERE product_id = %s
           AND ts >= NOW() - (%s || ' minutes')::interval
         ORDER BY ts DESC
         LIMIT %s
    """
    rows = db.execute_query(sql, (product_id, str(window_minutes), int(max_points)))
    rows.reverse()
    return [
        {
            "ts": _iso(r["ts"]),
            "price": _f(r["price"]),
            "best_bid": _f(r["best_bid"]) if r["best_bid"] is not None else None,
            "best_ask": _f(r["best_ask"]) if r["best_ask"] is not None else None,
        }
        for r in rows
    ]


def _read_candles(
    db: PostgresDB,
    product_id: str,
    window_minutes: int,
) -> List[Dict[str, Any]]:
    """1-minute candle closes within the window, oldest-first."""
    sql = """
        SELECT bucket_ts, open, high, low, close, volume
          FROM market_candle_1m
         WHERE product_id = %s
           AND bucket_ts >= NOW() - (%s || ' minutes')::interval
         ORDER BY bucket_ts ASC
    """
    rows = db.execute_query(sql, (product_id, str(window_minutes)))
    return [
        {
            "ts": _iso(r["bucket_ts"]),
            "open": _f(r["open"]),
            "high": _f(r["high"]),
            "low": _f(r["low"]),
            "close": _f(r["close"]),
            "volume": _f(r["volume"]),
        }
        for r in rows
    ]


def _read_anchor_reprices(
    db: PostgresDB,
    product_id: str,
    window_minutes: int,
) -> List[Dict[str, Any]]:
    """Per-stealth-root reprice events within the window.

    Reads ``stealth_orders.anchor_repricing_state_json -> 'reprice_history'``
    and unnests it. Returns one row per reprice with the stealth root id,
    timestamp, from/to prices, and source tag (last_trade / midpoint /
    top_of_book) — whatever the bridge writes into the JSON.
    """
    sql = """
        SELECT
            so.stealth_order_id::text                       AS stealth_order_id,
            (evt ->> 'timestamp')::timestamp                AS ts,
            (evt ->> 'from')::numeric                       AS from_price,
            (evt ->> 'to')::numeric                         AS to_price,
            evt ->> 'source'                                AS source
        FROM stealth_orders so,
             jsonb_array_elements(
                 COALESCE(so.anchor_repricing_state_json -> 'reprice_history',
                          '[]'::jsonb)
             ) AS evt
        WHERE so.product_id = %s
          AND so.parent_order_id IS NULL
          AND evt ? 'timestamp'
          AND (evt ->> 'timestamp')::timestamp
              >= NOW() - (%s || ' minutes')::interval
        ORDER BY ts ASC
    """
    rows = db.execute_query(sql, (product_id, str(window_minutes)))
    return [
        {
            "stealth_order_id": r["stealth_order_id"],
            "ts": _iso(r["ts"]),
            "from_price": _f(r["from_price"]),
            "to_price": _f(r["to_price"]),
            "source": r["source"],
        }
        for r in rows
    ]


def get_market_chart_history(
    product_id: str,
    window_minutes: int = 360,
    max_tick_points: int = 5000,
) -> Dict[str, Any]:
    """Build the chart payload for one product.

    Args:
        product_id: Required; the chart is per-product.
        window_minutes: Lookback window for ticks, candles, and reprices.
        max_tick_points: Hard cap on tick-row count returned (default 5000).

    Returns:
        ``{"product_id": str, "window_minutes": int,
            "ticks": [...], "candles": [...], "anchor_reprices": [...]}``.
    """
    if not product_id:
        raise ValueError("product_id is required")
    if window_minutes <= 0:
        raise ValueError("window_minutes must be positive")
    if max_tick_points <= 0:
        raise ValueError("max_tick_points must be positive")

    db = PostgresDB()
    try:
        ticks = _read_ticks(db, product_id, window_minutes, max_tick_points)
        candles = _read_candles(db, product_id, window_minutes)
        reprices = _read_anchor_reprices(db, product_id, window_minutes)
    finally:
        db.disconnect()

    return {
        "product_id": product_id,
        "window_minutes": window_minutes,
        "ticks": ticks,
        "candles": candles,
        "anchor_reprices": reprices,
    }
