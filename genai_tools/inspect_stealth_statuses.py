#!/usr/bin/env python3
"""
Inspect stealth orders status distribution in database.
Helps debug the reveal bug where many orders show as REVEALED unexpectedly.
"""

from database.database import PostgresDB
from collections import defaultdict

db = PostgresDB()
db.connect()

try:
    # Get status counts
    print("\n" + "="*60)
    print("STEALTH ORDERS STATUS DISTRIBUTION")
    print("="*60)

    with db.get_cursor() as cursor:
        cursor.execute("""
            SELECT status, COUNT(*) as count
            FROM stealth_orders
            GROUP BY status
            ORDER BY count DESC
        """)
        rows = cursor.fetchall()

        total = 0
        for status, count in rows:
            print(f"  {status:12} : {count:4} orders")
            total += count

        print("-" * 60)
        print(f"  {'TOTAL':12} : {total:4} orders")
        print()

    # Get first 10 orders by creation time to see if they have proper status
    print("\nRECENT ORDERS (first 10 by creation):")
    print("-" * 60)
    with db.get_cursor() as cursor:
        cursor.execute("""
            SELECT
                stealth_order_id,
                product_id,
                side,
                status,
                total_size,
                revealed_size,
                remaining_size,
                ARRAY_LENGTH(revealed_orders::text[], 1) as reveal_count,
                created_at
            FROM stealth_orders
            ORDER BY created_at DESC
            LIMIT 10
        """)
        rows = cursor.fetchall()

        for row in rows:
            sid, prod, side, status, total, revealed, remaining, reveal_count, created = row
            reveal_count = reveal_count or 0
            print(f"\n  ID: {str(sid)[:8]}...")
            print(f"    Product: {prod} | Side: {side} | Status: {status}")
            print(f"    Sizes: total={total}, revealed={revealed}, remaining={remaining}")
            print(f"    Reveals: {reveal_count} events")
            print(f"    Created: {created}")

    # Check for potential issue: are revealed_orders populated but status is HIDDEN?
    print("\n" + "="*60)
    print("POTENTIAL BUG CHECK: Mismatched status/reveals")
    print("="*60)
    with db.get_cursor() as cursor:
        cursor.execute("""
            SELECT
                stealth_order_id,
                product_id,
                status,
                ARRAY_LENGTH(revealed_orders::text[], 1) as reveal_count,
                remaining_size
            FROM stealth_orders
            WHERE
                (
                    (status = 'HIDDEN' AND ARRAY_LENGTH(revealed_orders::text[], 1) > 0)
                    OR
                    (status = 'REVEALED' AND remaining_size > 0)
                )
            LIMIT 20
        """)
        rows = cursor.fetchall()

        if rows:
            print(f"\nFound {len(rows)} orders with potential mismatches:")
            for sid, prod, status, reveal_count, remaining in rows:
                print(f"  {str(sid)[:8]}... | {prod:12} | Status={status:8} | Reveals={reveal_count} | Remaining={remaining}")
        else:
            print("✓ No mismatches found - status and reveals are consistent")

finally:
    db.disconnect()
