from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from database.database import PostgresDB


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _table_exists(db: PostgresDB, table_name: str) -> bool:
    rows = db.execute_query(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = %s
        ) AS exists
        """,
        (table_name,),
    )
    return bool(rows and rows[0]["exists"])


def _build_filters(args: argparse.Namespace) -> tuple[str, tuple[Any, ...]]:
    predicates: List[str] = []
    params: List[Any] = []

    if args.client_order_id:
        predicates.append("rh.placed_order_id = %s")
        params.append(args.client_order_id)

    if args.exchange_order_id:
        predicates.append("rh.exchange_order_id = %s")
        params.append(args.exchange_order_id)

    if args.stealth_order_id:
        predicates.append("rh.stealth_order_id = %s::uuid")
        params.append(args.stealth_order_id)

    where_clause = ""
    if predicates:
        where_clause = "WHERE " + " AND ".join(predicates)

    return where_clause, tuple(params)


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _print_rows(title: str, rows: List[Dict[str, Any]]) -> None:
    print(f"\n=== {title} ===")
    if not rows:
        print("<no rows>")
        return
    for row in rows:
        print(json.dumps({k: _to_jsonable(v) for k, v in row.items()}, sort_keys=True, default=str))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Correlate stealth reveal timestamps with available market evidence. "
            "Uses reveal history + lifecycle + fill ledger and reports deltas."
        )
    )
    parser.add_argument("--client-order-id", help="Filter by internal client order ID.")
    parser.add_argument("--exchange-order-id", help="Filter by exchange order ID.")
    parser.add_argument("--stealth-order-id", help="Filter by stealth order ID.")
    parser.add_argument("--limit", type=int, default=25, help="Max rows to return (default: 25).")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args()

    db = PostgresDB()
    where_clause, filter_params = _build_filters(args)

    fill_table_exists = _table_exists(db, "fill_ledger")
    snapshots_table_exists = _table_exists(db, "stealth_order_snapshots")
    ticker_tick_table_exists = _table_exists(db, "ticker_ticks")

    base_query = f"""
    SELECT
        rh.stealth_order_id,
        rh.placed_order_id AS client_order_id,
        rh.exchange_order_id,
        rh.reveal_number,
        rh.created_at AS reveal_recorded_at,
        COALESCE((rh.reveal_trigger_data ->> 'reveal_time')::timestamp, rh.created_at) AS reveal_time,
        (rh.reveal_trigger_data ->> 'market_price')::numeric AS reveal_market_price,
        so.product_id,
        so.side,
        so.status AS stealth_status,
        (so.reveal_condition_json ->> 'price_threshold')::numeric AS price_threshold,
        so.reveal_condition_json ->> 'direction' AS reveal_direction
    FROM stealth_order_reveal_history rh
    LEFT JOIN stealth_orders so
           ON so.stealth_order_id = rh.stealth_order_id
    {where_clause}
    ORDER BY rh.created_at DESC
    LIMIT %s
    """

    reveal_rows = db.execute_query(base_query, filter_params + (args.limit,))
    enriched_rows: List[Dict[str, Any]] = []

    for reveal_row in reveal_rows:
        reveal_time = reveal_row.get("reveal_time")
        reveal_time_for_query = reveal_time or reveal_row.get("reveal_recorded_at")

        condition_row = db.execute_query(
            """
            SELECT
                event_time AS condition_met_time,
                created_at AS condition_met_recorded_at
            FROM stealth_order_lifecycle_history
            WHERE stealth_order_id = %s::uuid
              AND lifecycle_event = 'CONDITION_MET'
            ORDER BY ABS(EXTRACT(EPOCH FROM (event_time - %s::timestamp))) ASC
            LIMIT 1
            """,
            (reveal_row["stealth_order_id"], reveal_time_for_query),
        )
        condition_data = condition_row[0] if condition_row else {}

        fill_data: Dict[str, Any] = {}
        if fill_table_exists:
            fill_row = db.execute_query(
                """
                SELECT
                    timestamp AS fill_time,
                    price AS fill_price,
                    trade_id,
                    instrument AS fill_product_id
                FROM fill_ledger
                WHERE client_order_id = %s
                ORDER BY ABS(EXTRACT(EPOCH FROM (timestamp - %s::timestamp))) ASC
                LIMIT 1
                """,
                (reveal_row["client_order_id"], reveal_time_for_query),
            )
            fill_data = fill_row[0] if fill_row else {}

        threshold = _safe_float(reveal_row.get("price_threshold"))
        reveal_market_price = _safe_float(reveal_row.get("reveal_market_price"))
        fill_price = _safe_float(fill_data.get("fill_price"))

        threshold_delta = None
        fill_delta = None
        if reveal_market_price is not None and threshold is not None:
            threshold_delta = reveal_market_price - threshold
        if fill_price is not None and reveal_market_price is not None:
            fill_delta = fill_price - reveal_market_price

        enriched = {
            **reveal_row,
            **condition_data,
            **fill_data,
            "threshold_delta": threshold_delta,
            "fill_minus_reveal_market": fill_delta,
            "note": (
                "No persisted ticker-tick table found; correlation uses reveal trigger data, "
                "lifecycle timestamps, and nearest fill ledger entries."
            ),
        }
        enriched_rows.append(enriched)

    summary = {
        "rows": len(enriched_rows),
        "fill_ledger_available": fill_table_exists,
        "stealth_order_snapshots_available": snapshots_table_exists,
        "ticker_tick_table_available": ticker_tick_table_exists,
    }

    if args.json:
        print(
            json.dumps(
                {
                    "summary": {k: _to_jsonable(v) for k, v in summary.items()},
                    "filters": {
                        "client_order_id": args.client_order_id,
                        "exchange_order_id": args.exchange_order_id,
                        "stealth_order_id": args.stealth_order_id,
                        "limit": args.limit,
                    },
                    "rows": [{k: _to_jsonable(v) for k, v in row.items()} for row in enriched_rows],
                },
                sort_keys=True,
                indent=2,
                default=str,
            )
        )
        return 0

    _print_rows("timing_correlation_summary", [summary])
    _print_rows("reveal_timing_correlation", enriched_rows)

    print("\nUsage examples:")
    print("  python genai_tools/inspect_reveal_timing_correlation.py --limit 10")
    print("  python genai_tools/inspect_reveal_timing_correlation.py --client-order-id <uuid>")
    print("  python genai_tools/inspect_reveal_timing_correlation.py --exchange-order-id <uuid> --json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())