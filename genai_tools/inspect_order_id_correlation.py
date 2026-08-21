from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from database.database import PostgresDB


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _render_rows(title: str, rows: List[Dict[str, Any]]) -> None:
    print(f"\n=== {title} ===")
    if not rows:
        print("<no rows>")
        return
    for row in rows:
        print(json.dumps({k: _to_jsonable(v) for k, v in row.items()}, sort_keys=True, default=str))


def _build_filters(args: argparse.Namespace) -> tuple[str, tuple[Any, ...]]:
    predicates: List[str] = []
    params: List[Any] = []

    if args.client_order_id:
        predicates.append("m.client_order_id = %s")
        params.append(args.client_order_id)

    if args.exchange_order_id:
        predicates.append("m.exchange_order_id = %s")
        params.append(args.exchange_order_id)

    if args.stealth_order_id:
        predicates.append("m.stealth_order_id = %s::uuid")
        params.append(args.stealth_order_id)

    where_clause = ""
    if predicates:
        where_clause = "WHERE " + " AND ".join(predicates)

    return where_clause, tuple(params)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect correlation between internal client_order_id and exchange order_id "
            "for stealth orders using reveal/lifecycle audit tables."
        )
    )
    parser.add_argument("--client-order-id", help="Filter by internal client order ID (UUID string).")
    parser.add_argument("--exchange-order-id", help="Filter by exchange order ID (UUID string).")
    parser.add_argument("--stealth-order-id", help="Filter by stealth order ID (UUID string).")
    parser.add_argument("--limit", type=int, default=50, help="Max correlated rows to return (default: 50).")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON payload.")
    args = parser.parse_args()

    db = PostgresDB()
    where_clause, filter_params = _build_filters(args)

    summary = db.execute_query(
        """
        SELECT
            (SELECT COUNT(*) FROM stealth_order_reveal_history) AS reveal_total,
            (SELECT COUNT(*) FROM stealth_order_reveal_history WHERE exchange_order_id IS NOT NULL) AS reveal_with_exchange,
            (SELECT COUNT(*) FROM stealth_order_lifecycle_history) AS lifecycle_total,
            (SELECT COUNT(*) FROM stealth_order_lifecycle_history WHERE exchange_order_id IS NOT NULL) AS lifecycle_with_exchange,
            (SELECT COUNT(*) FROM order_event_stream) AS stream_total,
            (SELECT COUNT(*) FROM order_event_stream WHERE client_order_id IS NOT NULL) AS stream_with_client,
            (SELECT COUNT(*) FROM order_event_stream WHERE order_id IS NOT NULL) AS stream_with_exchange
        """
    )[0]

    query = f"""
    WITH reveal_map AS (
        SELECT
            r.stealth_order_id,
            r.placed_order_id AS client_order_id,
            r.exchange_order_id,
            'reveal_history'::text AS source_table,
            NULL::text AS source_event,
            r.created_at AS mapped_at
        FROM stealth_order_reveal_history r
        WHERE r.exchange_order_id IS NOT NULL
          AND r.placed_order_id IS NOT NULL
    ),
    lifecycle_map AS (
        SELECT
            l.stealth_order_id,
            l.placed_order_id AS client_order_id,
            l.exchange_order_id,
            'lifecycle_history'::text AS source_table,
            l.lifecycle_event::text AS source_event,
            l.created_at AS mapped_at
        FROM stealth_order_lifecycle_history l
        WHERE l.exchange_order_id IS NOT NULL
          AND l.placed_order_id IS NOT NULL
    ),
    unioned AS (
        SELECT * FROM reveal_map
        UNION ALL
        SELECT * FROM lifecycle_map
    ),
    dedup AS (
        SELECT
            u.*,
            ROW_NUMBER() OVER (
                PARTITION BY u.stealth_order_id, u.client_order_id, u.exchange_order_id
                ORDER BY u.mapped_at DESC
            ) AS rn
        FROM unioned u
    ),
    mapped AS (
        SELECT
            d.stealth_order_id,
            d.client_order_id,
            d.exchange_order_id,
            d.source_table,
            d.source_event,
            d.mapped_at,
            s.status AS stealth_status,
            s.last_lifecycle_event,
            s.product_id,
            s.side,
            s.limit_price
        FROM dedup d
        LEFT JOIN stealth_orders s
               ON s.stealth_order_id = d.stealth_order_id
        WHERE d.rn = 1
    )
    SELECT *
    FROM mapped m
    {where_clause}
    ORDER BY m.mapped_at DESC
    LIMIT %s
    """

    rows = db.execute_query(query, filter_params + (args.limit,))

    if args.json:
        payload = {
            "summary": {k: _to_jsonable(v) for k, v in summary.items()},
            "filters": {
                "client_order_id": args.client_order_id,
                "exchange_order_id": args.exchange_order_id,
                "stealth_order_id": args.stealth_order_id,
                "limit": args.limit,
            },
            "rows": [{k: _to_jsonable(v) for k, v in row.items()} for row in rows],
        }
        print(json.dumps(payload, sort_keys=True, indent=2, default=str))
        return 0

    _render_rows("correlation_summary", [summary])
    _render_rows("client_to_exchange_mappings", rows)

    print("\nUsage examples:")
    print("  python genai_tools/inspect_order_id_correlation.py --limit 20")
    print("  python genai_tools/inspect_order_id_correlation.py --client-order-id <uuid>")
    print("  python genai_tools/inspect_order_id_correlation.py --exchange-order-id <uuid>")
    print("  python genai_tools/inspect_order_id_correlation.py --json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())