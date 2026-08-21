from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from database.database import PostgresDB


def _convert(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _print_rows(title, rows):
    print(f"\n=== {title} ===")
    if not rows:
        print("<no rows>")
        return
    for row in rows:
        print(json.dumps({key: _convert(val) for key, val in row.items()}, sort_keys=True, indent=2, default=str))


def _column_exists(db: PostgresDB, table_name: str, column_name: str) -> bool:
    rows = db.execute_query(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
              AND column_name = %s
        ) AS exists
        """,
        (table_name, column_name),
    )
    return bool(rows and rows[0]["exists"])


def main() -> int:
    db = PostgresDB()

    latest_orders = db.execute_query(
        """
        SELECT stealth_order_id, parent_order_id, product_id, side, status, reason,
               total_size, revealed_size, remaining_size, executed_size,
               limit_price, reveal_condition_type, reveal_condition_json,
               last_lifecycle_event, failure_reason, created_at, updated_at
        FROM stealth_orders
        ORDER BY created_at DESC
        LIMIT 10
        """
    )
    _print_rows("latest_stealth_orders", latest_orders)

    latest_uuid_ids = [row["stealth_order_id"] for row in latest_orders]
    latest_text_ids = [str(row["stealth_order_id"]) for row in latest_orders]
    if not latest_uuid_ids:
        return 0

    lifecycle_has_exchange = _column_exists(db, "stealth_order_lifecycle_history", "exchange_order_id")
    reveal_has_exchange = _column_exists(db, "stealth_order_reveal_history", "exchange_order_id")

    _print_rows(
        "audit_column_presence",
        [{
            "lifecycle_history.exchange_order_id": lifecycle_has_exchange,
            "reveal_history.exchange_order_id": reveal_has_exchange,
        }],
    )

    lifecycle_exchange_sql = ", exchange_order_id" if lifecycle_has_exchange else ""
    reveal_exchange_sql = ", exchange_order_id" if reveal_has_exchange else ""

    lifecycle_rows = db.execute_query(
        f"""
        SELECT stealth_order_id, lifecycle_event, previous_lifecycle_event, status_from, status_to,
               event_time, product_id, side, size, total_size, limit_price,
               reason, parent_order_id, placed_order_id{lifecycle_exchange_sql},
             failure_reason, created_at
        FROM stealth_order_lifecycle_history
        WHERE stealth_order_id = ANY(%s::uuid[])
        ORDER BY created_at DESC, id DESC
        LIMIT 50
        """,
        (latest_uuid_ids,),
    )
    _print_rows("lifecycle_history", lifecycle_rows)

    reveal_rows = db.execute_query(
         f"""
        SELECT stealth_order_id, reveal_number, revealed_size, placement_price,
             placed_order_id{reveal_exchange_sql},
             market_price, market_bid, market_ask,
               reveal_trigger_reason, reveal_trigger_data, created_at
        FROM stealth_order_reveal_history
        WHERE stealth_order_id = ANY(%s::uuid[])
        ORDER BY created_at DESC, id DESC
        LIMIT 20
         """,
        (latest_uuid_ids,),
    )
    _print_rows("reveal_history", reveal_rows)

    event_rows = db.execute_query(
        """
        SELECT stealth_order_id, client_order_id, order_id, event_type, event_status_to,
               source_channel, trigger_type, trigger_payload_json,
               event_time_ingested, created_at
        FROM order_event_stream
        WHERE stealth_order_id = ANY(%s)
        ORDER BY created_at DESC, id DESC
        LIMIT 80
        """,
        (latest_text_ids,),
    )
    _print_rows("order_event_stream", event_rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())