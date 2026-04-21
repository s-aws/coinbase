#!/usr/bin/env python3
"""Check where orders are stored - stealth_orders vs order_parent/order_child tables."""

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
    
    # Check the root parent
    root_parent = "c37ae73a-5e20-4b27-99a9-e1c88430cc03"
    
    print("=" * 100)
    print(f"ROOT PARENT: {root_parent}")
    print("=" * 100)
    print()
    
    # Check order_parent table
    cursor.execute("SELECT id, client_order_id, product_id FROM order_parent WHERE client_order_id = %s", (root_parent,))
    parent_row = cursor.fetchone()
    if parent_row:
        print(f"✓ Found in order_parent table (DB ID: {parent_row['id']})")
    else:
        print(f"✗ NOT in order_parent table")
    
    # Check stealth_orders table
    cursor.execute("SELECT stealth_order_id, product_id, status FROM stealth_orders WHERE stealth_order_id = %s", (root_parent,))
    stealth_row = cursor.fetchone()
    if stealth_row:
        print(f"✓ Found in stealth_orders table (status: {stealth_row['status']})")
    else:
        print(f"✗ NOT in stealth_orders table")
    
    print("\n" + "=" * 100)
    print("TABLE INVENTORY")
    print("=" * 100)
    print()
    
    # Count rows in order_parent
    cursor.execute("SELECT COUNT(*) as cnt FROM order_parent")
    parent_count = cursor.fetchone()['cnt']
    
    # Count rows in order_child
    cursor.execute("SELECT COUNT(*) as cnt FROM order_child")
    child_count = cursor.fetchone()['cnt']
    
    # Count rows in stealth_orders
    cursor.execute("SELECT COUNT(*) as cnt FROM stealth_orders")
    stealth_count = cursor.fetchone()['cnt']
    
    print(f"order_parent table:  {parent_count} rows")
    print(f"order_child table:   {child_count} rows")
    print(f"stealth_orders table: {stealth_count} rows")
    
    print("\n" + "=" * 100)
    print("ORDER PLACEMENT ANALYSIS")
    print("=" * 100)
    print()
    
    # Get sample of what's in order_parent
    if parent_count > 0:
        cursor.execute("SELECT client_order_id, product_id, side FROM order_parent LIMIT 3")
        rows = cursor.fetchall()
        print("Sample order_parent entries:")
        for row in rows:
            print(f"  - {row['client_order_id'][:8]}... ({row['product_id']} {row['side']})")
    else:
        print("order_parent is EMPTY")
    
    print()
    
    # Get sample of what's in stealth_orders
    if stealth_count > 0:
        cursor.execute("SELECT stealth_order_id, product_id, side, status FROM stealth_orders LIMIT 3")
        rows = cursor.fetchall()
        print("Sample stealth_orders entries:")
        for row in rows:
            print(f"  - {row['stealth_order_id'][:8]}... ({row['product_id']} {row['side']}) [status: {row['status']}]")
    else:
        print("stealth_orders is EMPTY")
    
    print("\n" + "=" * 100)
    print("QUESTION: Are stealth orders ALSO inserted into order_parent/order_child?")
    print("=" * 100)
    print()
    
    # Check if any stealth order IDs appear in order_parent
    cursor.execute("""
        SELECT COUNT(*) as cnt FROM stealth_orders so
        WHERE EXISTS (SELECT 1 FROM order_parent op WHERE op.client_order_id = so.stealth_order_id)
    """)
    overlap = cursor.fetchone()['cnt']
    
    if overlap > 0:
        print(f"✓ {overlap} stealth orders are ALSO in order_parent table (dual tracking)")
    else:
        print(f"✗ Stealth orders are NOT in order_parent table (separate tracking)")
        print(f"  → This means two different tracking systems for two types of orders")
    
    conn.close()
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
