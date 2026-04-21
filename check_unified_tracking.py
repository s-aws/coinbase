#!/usr/bin/env python3
"""Check if order_child insertions are failing or if there just haven't been any follow-ups."""

import psycopg2
from psycopg2.extras import RealDictCursor

try:
    conn = psycopg2.connect(
        host="127.0.0.1",
        port=5432,
        database="postgres",
        user="postgres",
        password="postgres"
    )
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    print("=" * 100)
    print("ANALYZING ORDER_CHILD TRACKING")
    print("=" * 100)
    print()
    
    # Check order_child count
    cursor.execute("SELECT COUNT(*) as cnt FROM order_child")
    child_count = cursor.fetchone()['cnt']
    print(f"order_child table: {child_count} rows")
    
    # Check for any orders in order_parent that are also in stealth_orders and have parent_order_id
    cursor.execute("""
        SELECT op.client_order_id, op.product_id, op.side, op.status
        FROM order_parent op
        WHERE EXISTS (
            SELECT 1 FROM stealth_orders so 
            WHERE so.stealth_order_id::text = op.client_order_id 
            AND so.parent_order_id IS NOT NULL
        )
        LIMIT 10
    """)
    
    stealth_children = cursor.fetchall()
    
    if stealth_children:
        print(f"\nFound {len(stealth_children)} orders in order_parent that are CHILDREN of stealth orders:")
        for row in stealth_children:
            print(f"  - {row['client_order_id'][:8]}... ({row['product_id']} {row['side']}) [status: {row['status']}]")
        print("\n⚠️ These should be in order_child table instead of order_parent!")
    else:
        print("\n✓ No stealth children found in order_parent (good)")
    
    # Check stealth orders that have been created since the fix (should be in order_parent now)
    cursor.execute("""
        SELECT COUNT(*) as cnt FROM stealth_orders so
        WHERE EXISTS (
            SELECT 1 FROM order_parent op
            WHERE op.client_order_id = so.stealth_order_id::text
        )
    """)
    
    overlap = cursor.fetchone()['cnt']
    print(f"\nStealth orders also in order_parent: {overlap}")
    
    # Check the total count
    cursor.execute("SELECT COUNT(*) as cnt FROM order_parent")
    parent_total = cursor.fetchone()['cnt']
    
    cursor.execute("SELECT COUNT(*) as cnt FROM stealth_orders")
    stealth_total = cursor.fetchone()['cnt']
    
    print(f"Total order_parent: {parent_total}")
    print(f"Total stealth_orders: {stealth_total}")
    
    if overlap > 0:
        print(f"\n✓ {overlap}/{stealth_total} stealth orders are now in BOTH tables (unified tracking)")
    
    conn.close()
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
