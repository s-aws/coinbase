from __future__ import annotations

import json
import os
import sys
from decimal import Decimal
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from database.database import PostgresDB


def _json_default(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _print_section(title: str, rows):
    print(f"\n=== {title} ===")
    if not rows:
        print("<no rows>")
        return
    for row in rows:
        print(json.dumps(row, default=_json_default, sort_keys=True, indent=2))


def _table_exists(db: PostgresDB, table_name: str) -> bool:
    rows = db.execute_query(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = %s
        ) AS exists
        """,
        (table_name,),
    )
    return bool(rows and rows[0]["exists"])


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: inspect_stealth_reveal_order.py <client_order_id>")
        return 1

    client_order_id = sys.argv[1]
    db = PostgresDB()

    tables = [
        "stealth_orders",
        "order_parent",
        "order_child",
        "fill_ledger",
        "order_event_stream",
        "stealth_order_snapshots",
        "stealth_order_reveal_history",
    ]
    existing_tables = {name: _table_exists(db, name) for name in tables}

    _print_section("table_existence", [existing_tables])

    stealth_rows = db.execute_query(
        """
        SELECT
            stealth_order_id,
            parent_order_id,
            product_id,
            side,
            total_size,
            revealed_size,
            remaining_size,
            executed_size,
            limit_price,
            status,
            reveal_condition_type,
            reveal_condition_json,
            condition_first_met_at,
            condition_confirmed_at,
            revealed_orders,
            last_placement_at,
            target_movement,
            target_movement_type,
            reason,
            last_lifecycle_event,
            failure_reason,
            created_at,
            updated_at
        FROM stealth_orders
        WHERE stealth_order_id = %s
           OR parent_order_id = %s
        ORDER BY created_at ASC
        """,
        (client_order_id, client_order_id),
    )

    parent_rows = db.execute_query(
        """
        SELECT *
        FROM order_parent
        WHERE client_order_id = %s
        """,
        (client_order_id,),
    )

    child_rows = []
    if existing_tables["order_child"]:
        child_rows = db.execute_query(
            """
            SELECT *
            FROM order_child
            WHERE client_order_id = %s OR parent_client_order_id = %s
            ORDER BY created_at ASC
            """,
            (client_order_id, client_order_id),
        )

    fill_rows = []
    if existing_tables["fill_ledger"]:
        fill_rows = db.execute_query(
            """
            SELECT *
            FROM fill_ledger
            WHERE client_order_id = %s
            ORDER BY timestamp DESC
            LIMIT 20
            """,
            (client_order_id,),
        )

    event_rows = []
    if existing_tables["order_event_stream"]:
        event_rows = db.execute_query(
            """
            SELECT *
            FROM order_event_stream
            WHERE client_order_id = %s
               OR parent_client_order_id = %s
            ORDER BY event_time_exchange DESC NULLS LAST, event_time_ingested DESC
            LIMIT 50
            """,
            (client_order_id, client_order_id),
        )

    snapshot_rows = []
    if existing_tables["stealth_order_snapshots"]:
        snapshot_rows = db.execute_query(
            """
            SELECT *
            FROM stealth_order_snapshots
            WHERE stealth_order_id = %s
            ORDER BY created_at DESC
            LIMIT 20
            """,
            (client_order_id,),
        )

    reveal_history_rows = []
    if existing_tables["stealth_order_reveal_history"]:
        reveal_history_rows = db.execute_query(
            """
            SELECT *
            FROM stealth_order_reveal_history
            WHERE stealth_order_id = %s OR placed_order_id = %s
            ORDER BY created_at DESC
            LIMIT 20
            """,
            (client_order_id, client_order_id),
        )

    _print_section("stealth_orders", stealth_rows)
    _print_section("order_parent", parent_rows)
    _print_section("order_child", child_rows)
    _print_section("fill_ledger", fill_rows)
    _print_section("order_event_stream", event_rows)
    _print_section("stealth_order_snapshots", snapshot_rows)
    _print_section("stealth_order_reveal_history", reveal_history_rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())