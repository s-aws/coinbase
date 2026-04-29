"""Slide-calibration analytics for the dashboard.

Pure-SQL helpers that summarise fill activity, reprice cadence, and a naive
realised P&L over a rolling time window — per product. Consumed by the
``request_slide_calibration_summary`` WebSocket handler in
``dashboard_server.py``.

Design notes
------------
* No new tables, no schema changes. Everything reads from existing
  ``fill_ledger``, ``order_parent``, and ``stealth_orders`` rows whose
  schema is verified in ``database/order.py``.
* ``stealth_order_id == client_order_id`` for the root order (per
  ``core/stealth_order_manager.py`` lines 21, 176). Child orders reference
  the root through ``order_parent.parent_order_id``. So fills attributable
  to a stealth root span the root's own ``client_order_id`` *plus* every
  child whose ``parent_order_id`` is that root — the flat hierarchy from
  ``agent.md``.
* Reprice cadence comes from
  ``stealth_orders.anchor_repricing_state_json -> 'reprice_history'``, a
  JSONB list of reprice events appended to by the bridge.
* **No P&L field.** ``sell_notional - buy_notional`` over a window is not
  a realised P&L (ignores open inventory mark-to-market and fees) and was
  removed rather than displayed with a misleading label. Realised P&L
  needs a per-product lot tracker — out of scope here.
* **Contract size:** for FUTURE products, ``fill_ledger.quantity`` records
  the *contract count*, not the underlying unit count. True notional is
  ``quantity * price * contract_size`` (e.g. ``BIT-29MAY26-CDE`` has
  ``contract_size=0.01`` BTC, so 11 contracts at $78,065 = $8,587 notional,
  not $858,715). The authoritative source for contract size is
  ``orderbook.product[product_id]['future_product_details']['contract_size']``
  — the same path used by ``calculation/profit_validator.py``. This module
  doesn't have access to a live OrderBook, so callers must supply
  ``contract_size_by_product``; the dashboard handler resolves it from
  ``stealth_order_bridge.order_engine.orderbook.product``. SPOT products
  and unknown contracts default to 1.0.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from database.database import PostgresDB
from core.enums import StealthOrderStatus


# Active stealth statuses derived from the canonical enum (excluding terminal
# states). Same rule as ``dashboard_server._ACTIVE_STEALTH_STATUSES`` — kept
# local rather than imported to avoid the helper depending on the dashboard
# module (which would create a circular import).
_TERMINAL_STEALTH_STATUSES = frozenset({
    StealthOrderStatus.EXECUTED.value,
    StealthOrderStatus.CANCELLED.value,
})
_ACTIVE_STEALTH_STATUSES = frozenset(
    s.value for s in StealthOrderStatus if s.value not in _TERMINAL_STEALTH_STATUSES
)


def _f(v: Any, default: float = 0.0) -> float:
    """Coerce a Decimal / None / numeric-str into float for JSON transport."""
    if v is None:
        return default
    if isinstance(v, Decimal):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _contract_size_for(
    product_id: str,
    contract_size_by_product: Optional[Dict[str, float]],
) -> float:
    """Return the contract size for ``product_id``, defaulting to 1.0.

    SPOT products and unknown instruments use 1.0 (i.e. ``quantity`` is
    already in underlying units). FUTURE products without an entry in the
    supplied lookup also default to 1.0 — better to under-report than to
    silently invent a multiplier.
    """
    if not contract_size_by_product:
        return 1.0
    raw = contract_size_by_product.get(product_id)
    if raw is None:
        return 1.0
    try:
        size = float(raw)
    except (TypeError, ValueError):
        return 1.0
    return size if size > 0 else 1.0


def _per_product_fill_metrics(
    db: PostgresDB,
    window_minutes: int,
    product_id: Optional[str],
    contract_size_by_product: Optional[Dict[str, float]],
) -> List[Dict[str, Any]]:
    """Aggregate fill_ledger over the window, grouped by instrument.

    Returns one row per product with notional, side breakdown, and a
    fill-price stdev (used as a rough realised-vol proxy). Notional figures
    are scaled by ``contract_size_by_product`` so FUTURE products report
    underlying-unit notional, not contract-count notional.
    """
    sql = """
        SELECT
            instrument                                                   AS product_id,
            COUNT(*)                                                     AS fills_count,
            COUNT(DISTINCT client_order_id)                              AS distinct_orders_filled,
            COUNT(*) FILTER (WHERE side = 'BUY')                         AS buy_count,
            COUNT(*) FILTER (WHERE side = 'SELL')                        AS sell_count,
            COALESCE(SUM(quantity * price), 0)                           AS raw_notional,
            COALESCE(SUM(quantity * price)
                FILTER (WHERE side = 'BUY'), 0)                          AS raw_buy_notional,
            COALESCE(SUM(quantity * price)
                FILTER (WHERE side = 'SELL'), 0)                         AS raw_sell_notional,
            COALESCE(SUM(quantity), 0)                                   AS total_quantity,
            COALESCE(SUM(fees), 0)                                       AS total_fees,
            AVG(price)                                                   AS avg_price,
            MIN(price)                                                   AS min_price,
            MAX(price)                                                   AS max_price,
            STDDEV_SAMP(price)                                           AS price_stdev,
            MIN(timestamp)                                               AS first_fill_at,
            MAX(timestamp)                                               AS last_fill_at
        FROM fill_ledger
        WHERE timestamp >= NOW() - (%s || ' minutes')::interval
          AND (%s IS NULL OR instrument = %s)
        GROUP BY instrument
        ORDER BY raw_notional DESC
    """
    rows = db.execute_query(sql, (str(window_minutes), product_id, product_id))
    out: List[Dict[str, Any]] = []
    for r in rows:
        product = r["product_id"]
        contract_size = _contract_size_for(product, contract_size_by_product)
        avg_price = _f(r["avg_price"])
        stdev = _f(r["price_stdev"])
        # Convert stdev into basis points of the average price so the number
        # is comparable across instruments at very different price levels.
        # bps is unitless so contract size doesn't matter here.
        price_stdev_bps = (stdev / avg_price * 10_000.0) if avg_price > 0 else 0.0
        fills = int(r["fills_count"])
        distinct = int(r["distinct_orders_filled"])
        # Notional in underlying-unit dollars. ``raw_notional`` from SQL is
        # contracts × price; multiplying by contract_size yields true USD.
        total_notional = _f(r["raw_notional"]) * contract_size
        buy_notional = _f(r["raw_buy_notional"]) * contract_size
        sell_notional = _f(r["raw_sell_notional"]) * contract_size
        out.append({
            "product_id": product,
            "contract_size": contract_size,
            "fills_count": fills,
            "distinct_orders_filled": distinct,
            "avg_fills_per_order": (fills / distinct) if distinct else 0.0,
            "buy_count": int(r["buy_count"]),
            "sell_count": int(r["sell_count"]),
            "total_notional_usd": total_notional,
            "buy_notional_usd": buy_notional,
            "sell_notional_usd": sell_notional,
            "total_quantity": _f(r["total_quantity"]),
            "total_fees": _f(r["total_fees"]),
            "avg_price": avg_price,
            "min_price": _f(r["min_price"]),
            "max_price": _f(r["max_price"]),
            "price_stdev_bps": round(price_stdev_bps, 2),
            "first_fill_at": r["first_fill_at"].isoformat() if r["first_fill_at"] else None,
            "last_fill_at": r["last_fill_at"].isoformat() if r["last_fill_at"] else None,
        })
    # Re-sort by *true* notional, since the SQL ordered by raw notional.
    out.sort(key=lambda x: x["total_notional_usd"], reverse=True)
    return out


def _per_product_stealth_metrics(
    db: PostgresDB,
    window_minutes: int,
    product_id: Optional[str],
) -> Dict[str, Dict[str, Any]]:
    """Return stealth/reprice activity per product within the window.

    Reprice cadence is derived from
    ``stealth_orders.anchor_repricing_state_json -> 'reprice_history'``,
    counting only entries with a ``timestamp`` field that falls inside the
    window. Roots only — follow-ups inherit the root's repricing config.
    """
    # First pass: simple counts by status, no JSONB work.
    counts_sql = """
        SELECT
            product_id,
            COUNT(*)                                              AS active_orders,
            COUNT(*) FILTER (WHERE status = 'REVEALED')           AS revealed_orders,
            COUNT(*) FILTER (WHERE status IN ('HIDDEN','PENDING','TRIGGERED'))
                                                                  AS unrevealed_orders
        FROM stealth_orders
        WHERE parent_order_id IS NULL
          AND status = ANY(%s)
          AND (%s IS NULL OR product_id = %s)
        GROUP BY product_id
    """
    active_list = sorted(_ACTIVE_STEALTH_STATUSES)
    rows = db.execute_query(counts_sql, (active_list, product_id, product_id))
    by_product: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        by_product[r["product_id"]] = {
            "active_orders": int(r["active_orders"]),
            "revealed_orders": int(r["revealed_orders"]),
            "unrevealed_orders": int(r["unrevealed_orders"]),
            "reprices_in_window": 0,
        }

    # Second pass: count reprice_history entries within the window. We pull
    # the JSONB and unnest in SQL so the per-row work stays in Postgres.
    # ``reprice_history`` entries are objects shaped like
    #   {"timestamp": "...iso8601...", "from": .., "to": ..., "source": ..}
    # so we filter on the ``timestamp`` key; entries without it are skipped.
    reprice_sql = """
        SELECT
            so.product_id                                       AS product_id,
            COUNT(*)                                            AS reprices_in_window
        FROM stealth_orders so,
             jsonb_array_elements(
                 COALESCE(so.anchor_repricing_state_json -> 'reprice_history', '[]'::jsonb)
             ) AS evt
        WHERE so.parent_order_id IS NULL
          AND (%s IS NULL OR so.product_id = %s)
          AND evt ? 'timestamp'
          AND (evt ->> 'timestamp')::timestamp >= NOW() - (%s || ' minutes')::interval
        GROUP BY so.product_id
    """
    reprice_rows = db.execute_query(
        reprice_sql, (product_id, product_id, str(window_minutes))
    )
    for r in reprice_rows:
        bucket = by_product.setdefault(r["product_id"], {
            "active_orders": 0,
            "revealed_orders": 0,
            "unrevealed_orders": 0,
            "reprices_in_window": 0,
        })
        bucket["reprices_in_window"] = int(r["reprices_in_window"])
    return by_product


def get_slide_calibration_summary(
    window_minutes: int = 1440,
    product_id: Optional[str] = None,
    daily_notional_target_usd: float = 1_000_000.0,
    account_balance_usd: float = 250_000.0,
    contract_size_by_product: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Build the slide-calibration summary payload.

    Args:
        window_minutes: Lookback window for fills + reprices. Default 1 day.
        product_id: If set, restrict to a single instrument.
        daily_notional_target_usd: Goal-tracking volume target (default $1M).
        account_balance_usd: Used for capital-turnover ratio.
        contract_size_by_product: Mapping of ``product_id`` → contract size
            in underlying units (e.g. ``{"BIT-29MAY26-CDE": 0.01}``). Used
            to scale FUTURE notional from contract count to true USD. Any
            product not present defaults to ``1.0``. SPOT products should
            either be omitted or mapped to ``1.0``. Caller is responsible
            for sourcing this from
            ``orderbook.product[pid]['future_product_details']['contract_size']``
            — see the dashboard handler in ``dashboard_server.py``.

    Returns:
        ``{"window_minutes": int, "products": [...], "totals": {...},
            "targets": {...}}``
    """
    if window_minutes <= 0:
        raise ValueError("window_minutes must be positive")

    db = PostgresDB()
    try:
        fill_rows = _per_product_fill_metrics(
            db, window_minutes, product_id, contract_size_by_product
        )
        stealth_by_product = _per_product_stealth_metrics(
            db, window_minutes, product_id
        )
    finally:
        db.disconnect()

    # Merge stealth metrics into each fill row, and surface stealth-only
    # products (no fills in window but live orders) with zero-fill rows.
    fill_keys = {r["product_id"] for r in fill_rows}
    merged: List[Dict[str, Any]] = []
    for row in fill_rows:
        s = stealth_by_product.get(row["product_id"], {
            "active_orders": 0,
            "revealed_orders": 0,
            "unrevealed_orders": 0,
            "reprices_in_window": 0,
        })
        fills = row["fills_count"]
        reprices = s["reprices_in_window"]
        row.update({
            "active_stealth_orders": s["active_orders"],
            "revealed_stealth_orders": s["revealed_orders"],
            "unrevealed_stealth_orders": s["unrevealed_orders"],
            "reprices_in_window": reprices,
            "avg_reprices_per_fill": (reprices / fills) if fills else 0.0,
        })
        merged.append(row)

    for product, s in stealth_by_product.items():
        if product in fill_keys:
            continue
        merged.append({
            "product_id": product,
            "contract_size": _contract_size_for(product, contract_size_by_product),
            "fills_count": 0,
            "distinct_orders_filled": 0,
            "avg_fills_per_order": 0.0,
            "buy_count": 0,
            "sell_count": 0,
            "total_notional_usd": 0.0,
            "buy_notional_usd": 0.0,
            "sell_notional_usd": 0.0,
            "total_quantity": 0.0,
            "total_fees": 0.0,
            "avg_price": 0.0,
            "min_price": 0.0,
            "max_price": 0.0,
            "price_stdev_bps": 0.0,
            "first_fill_at": None,
            "last_fill_at": None,
            "active_stealth_orders": s["active_orders"],
            "revealed_stealth_orders": s["revealed_orders"],
            "unrevealed_stealth_orders": s["unrevealed_orders"],
            "reprices_in_window": s["reprices_in_window"],
            "avg_reprices_per_fill": 0.0,
        })

    merged.sort(key=lambda r: r["total_notional_usd"], reverse=True)

    # Roll-up totals across products.
    totals = {
        "fills_count": sum(r["fills_count"] for r in merged),
        "total_notional_usd": sum(r["total_notional_usd"] for r in merged),
        "buy_notional_usd": sum(r["buy_notional_usd"] for r in merged),
        "sell_notional_usd": sum(r["sell_notional_usd"] for r in merged),
        "total_fees": sum(r["total_fees"] for r in merged),
        "active_stealth_orders": sum(r["active_stealth_orders"] for r in merged),
        "reprices_in_window": sum(r["reprices_in_window"] for r in merged),
    }

    notional_progress_pct = (
        (totals["total_notional_usd"] / daily_notional_target_usd * 100.0)
        if daily_notional_target_usd > 0 else 0.0
    )
    capital_turnover = (
        (totals["total_notional_usd"] / account_balance_usd)
        if account_balance_usd > 0 else 0.0
    )

    targets = {
        "window_minutes": window_minutes,
        "daily_notional_target_usd": daily_notional_target_usd,
        "account_balance_usd": account_balance_usd,
        "notional_progress_pct": round(notional_progress_pct, 2),
        "capital_turnover": round(capital_turnover, 4),
    }

    return {
        "window_minutes": window_minutes,
        "products": merged,
        "totals": totals,
        "targets": targets,
    }
