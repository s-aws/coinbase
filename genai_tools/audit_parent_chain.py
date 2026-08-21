#!/usr/bin/env python
"""Targeted audit for one parent order chain."""
import sys
import json
from decimal import Decimal

sys.path.insert(0, '.')
from database.database import PostgresDB

PARENT_ID = "5cb69570-4e02-4164-aa19-e5fa78f775f0"


def to_jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_jsonable(v) for v in value]
    return value


def print_section(title):
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)


def show_columns(db, table_name):
    result = db.execute_query(
        """SELECT column_name, data_type
           FROM information_schema.columns
           WHERE table_name = %s
           ORDER BY ordinal_position""",
        (table_name,),
    )
    print(f"\n[{table_name}] columns:")
    for row in result:
        print(f"  - {row['column_name']}: {row['data_type']}")


def main():
    db = PostgresDB()
    db.connect()

    print_section(f"TARGET PARENT: {PARENT_ID}")

    parent_rows = db.execute_query(
        """SELECT id, client_order_id, parent_order_id, product_id, side, size, price, status,
                  current_order_replacement, max_order_replacement, created_at
           FROM order_parent
           WHERE client_order_id = %s""",
        (PARENT_ID,),
    )
    print("Parent row:")
    for row in parent_rows:
        print(json.dumps(to_jsonable(row), indent=2, default=str))

    child_rows = db.execute_query(
        """SELECT id, client_order_id, parent_order_id, product_id, side, size, price, status, created_at
           FROM order_parent
           WHERE parent_order_id = %s
           ORDER BY created_at ASC""",
        (PARENT_ID,),
    )
    print("\nChildren rows:")
    total_child_size = 0.0
    for row in child_rows:
        total_child_size += float(row.get("size") or 0.0)
        print(json.dumps(to_jsonable(row), indent=2, default=str))
    print(f"\nChild count={len(child_rows)} | Sum(child.size)={total_child_size}")

    stealth_rows = db.execute_query(
        """SELECT stealth_order_id, parent_order_id, side, total_size, remaining_size, revealed_size,
                  executed_size, limit_price, status, last_lifecycle_event, revealed_orders, created_at, updated_at
           FROM stealth_orders
           WHERE stealth_order_id = %s OR parent_order_id::text = %s
           ORDER BY created_at ASC""",
        (PARENT_ID, PARENT_ID),
    )
    print("\nStealth chain rows:")
    for row in stealth_rows:
        print(json.dumps(to_jsonable(row), indent=2, default=str))

    fill_rows = db.execute_query(
        """SELECT trade_id, client_order_id, instrument, side, quantity, price, fees, created_at
           FROM fill_ledger
           WHERE client_order_id = %s
           ORDER BY created_at ASC""",
        (PARENT_ID,),
    )
    print("\nFill ledger rows for parent client_order_id:")
    for row in fill_rows:
        print(json.dumps(to_jsonable(row), indent=2, default=str))

    # Introspection for extra audit tables
    print_section("TABLE INTROSPECTION")
    show_columns(db, "partial_fill_progress")
    show_columns(db, "order_event_stream")
    show_columns(db, "stealth_order_reveal_history")
    show_columns(db, "stealth_order_lifecycle_history")

    # Generic dumps using expected common column names
    print_section("partial_fill_progress rows")
    try:
        pfp_rows = db.execute_query(
            """SELECT *
               FROM partial_fill_progress
               WHERE parent_client_order_id = %s
               ORDER BY updated_at ASC""",
            (PARENT_ID,),
        )
        for row in pfp_rows:
            print(json.dumps(to_jsonable(row), indent=2, default=str))
        if not pfp_rows:
            print("(no rows)")
    except Exception as exc:
        print(f"Query failed for partial_fill_progress: {exc}")

    print_section("order_event_stream rows")
    for query in [
        """SELECT * FROM order_event_stream WHERE client_order_id = %s ORDER BY created_at ASC""",
        """SELECT * FROM order_event_stream WHERE parent_client_order_id = %s ORDER BY created_at ASC""",
    ]:
        try:
            rows = db.execute_query(query, (PARENT_ID,))
            print(f"\nQuery: {query}")
            for row in rows:
                print(json.dumps(to_jsonable(row), indent=2, default=str))
            if not rows:
                print("(no rows)")
        except Exception as exc:
            print(f"Query failed: {query} -> {exc}")

    print_section("stealth_order_reveal_history rows")
    try:
        rows = db.execute_query(
            """SELECT *
               FROM stealth_order_reveal_history
               WHERE stealth_order_id::text = %s
               ORDER BY created_at ASC""",
            (PARENT_ID,),
        )
        for row in rows:
            print(json.dumps(to_jsonable(row), indent=2, default=str))
        if not rows:
            print("(no rows)")
    except Exception as exc:
        print(f"Query failed for stealth_order_reveal_history: {exc}")

    print_section("stealth_order_lifecycle_history rows")
    try:
        rows = db.execute_query(
            """SELECT *
               FROM stealth_order_lifecycle_history
               WHERE stealth_order_id::text = %s OR parent_order_id::text = %s
               ORDER BY created_at ASC""",
            (PARENT_ID, PARENT_ID),
        )
        for row in rows:
            print(json.dumps(to_jsonable(row), indent=2, default=str))
        if not rows:
            print("(no rows)")
    except Exception as exc:
        print(f"Query failed for stealth_order_lifecycle_history: {exc}")

    db.disconnect()


if __name__ == "__main__":
    main()
