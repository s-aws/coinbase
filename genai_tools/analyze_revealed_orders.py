#!/usr/bin/env python3
"""
Detailed inspection of REVEALED orders to understand the bug.
"""

from database.database import PostgresDB
import json

db = PostgresDB()
db.connect()

try:
    print("\n" + "="*80)
    print("DETAILED ANALYSIS OF REVEALED ORDERS")
    print("="*80)

    # Get all REVEALED orders and check their sizes
    with db.get_cursor() as cursor:
        cursor.execute("""
            SELECT
                stealth_order_id,
                product_id,
                side,
                total_size,
                revealed_size,
                remaining_size,
                status,
                created_at,
                updated_at
            FROM stealth_orders
            WHERE status = 'REVEALED'
            ORDER BY created_at DESC
            LIMIT 20
        """)
        rows = cursor.fetchall()

        print(f"\nShowing first 20 of {len(rows)} REVEALED orders:\n")

        for row in rows:
            sid, prod, side, total, revealed, remaining, status, created, updated = row
            print(f"ID: {str(sid)[:8]}... | {prod:12} {side:4}")
            print(f"  Status: {status}")
            print(f"  Sizes: total={float(total):10.4f}, revealed={float(revealed):10.4f}, remaining={float(remaining):10.4f}")
            print(f"  Created: {created} | Updated: {updated}")
            print()

    # Check if all REVEALED orders have remaining_size = 0
    print("\n" + "="*80)
    print("REVEALED SIZE ANALYSIS")
    print("="*80)
    with db.get_cursor() as cursor:
        cursor.execute("""
            SELECT
                CASE
                    WHEN remaining_size = 0 THEN 'remaining=0'
                    WHEN remaining_size < 0 THEN 'remaining<0'
                    ELSE 'remaining>0'
                END as remaining_category,
                COUNT(*) as count
            FROM stealth_orders
            WHERE status = 'REVEALED'
            GROUP BY remaining_category
        """)
        rows = cursor.fetchall()

        for category, count in rows:
            print(f"  {category:20} : {count} orders")

    # Check if there's a pattern - when were these orders marked as REVEALED?
    print("\n" + "="*80)
    print("TIMELINE: When orders were marked as REVEALED")
    print("="*80)
    with db.get_cursor() as cursor:
        cursor.execute("""
            SELECT
                DATE_TRUNC('day', updated_at)::date as update_date,
                COUNT(*) as count
            FROM stealth_orders
            WHERE status = 'REVEALED'
            GROUP BY DATE_TRUNC('day', updated_at)
            ORDER BY update_date DESC
            LIMIT 10
        """)
        rows = cursor.fetchall()

        for date, count in rows:
            print(f"  {date} : {count} orders updated")

    # Check the single HIDDEN order
    print("\n" + "="*80)
    print("THE SINGLE HIDDEN ORDER")
    print("="*80)
    with db.get_cursor() as cursor:
        cursor.execute("""
            SELECT
                stealth_order_id,
                product_id,
                side,
                total_size,
                revealed_size,
                remaining_size,
                status,
                created_at,
                updated_at
            FROM stealth_orders
            WHERE status = 'HIDDEN'
        """)
        rows = cursor.fetchall()

        for row in rows:
            sid, prod, side, total, revealed, remaining, status, created, updated = row
            print(f"ID: {str(sid)[:8]}... | {prod:12} {side:4}")
            print(f"  Status: {status}")
            print(f"  Sizes: total={float(total):10.4f}, revealed={float(revealed):10.4f}, remaining={float(remaining):10.4f}")
            print(f"  Created: {created} | Updated: {updated}")

finally:
    db.disconnect()
