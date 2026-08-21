#!/usr/bin/env python3
"""
Check if the REVEALED orders actually have placed orders on the exchange.
"""

from database.database import PostgresDB
import json

db = PostgresDB()
db.connect()

try:
    print("\n" + "="*80)
    print("CHECKING IF REVEALED ORDERS WERE ACTUALLY PLACED")
    print("="*80)

    # Get a REVEALED order and check its revealed_orders array
    with db.get_cursor() as cursor:
        cursor.execute("""
            SELECT
                stealth_order_id,
                status,
                revealed_size,
                remaining_size,
                revealed_orders
            FROM stealth_orders
            WHERE status = 'REVEALED'
            LIMIT 5
        """)
        rows = cursor.fetchall()

        print(f"\nFound {len(rows)} REVEALED orders. Checking placement data...\n")

        for row in rows:
            sid, status, revealed_size, remaining_size, revealed_orders_json = row

            print(f"Order ID: {str(sid)[:8]}...")
            print(f"  Status: {status}, revealed_size: {revealed_size}, remaining: {remaining_size}")

            # Parse the revealed_orders JSON
            try:
                if isinstance(revealed_orders_json, str):
                    revealed_list = json.loads(revealed_orders_json)
                else:
                    revealed_list = revealed_orders_json or []

                print(f"  Revealed orders array: {len(revealed_list) if revealed_list else 0} entries")

                if revealed_list:
                    for i, reveal_event in enumerate(revealed_list[:2]):  # Show first 2
                        print(f"    Event {i}: placed_order_id = {reveal_event.get('placed_order_id', 'MISSING')}")
                else:
                    print(f"    ⚠️  Revealed orders array is EMPTY!")

            except Exception as e:
                print(f"  ERROR parsing revealed_orders: {e}")

            print()

finally:
    db.disconnect()
