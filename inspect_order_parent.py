#!/usr/bin/env python3
"""Inspect order_parent entries to understand the tracking strategy."""

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
    print("ORDER_PARENT TABLE INSPECTION")
    print("=" * 100)
    print()
    
    # Get all order_parent entries
    cursor.execute("""
        SELECT client_order_id, product_id, side, size, price, 
               current_order_replacement, max_order_replacement, status
        FROM order_parent
        ORDER BY created_at DESC
        LIMIT 10
    """)
    
    rows = cursor.fetchall()
    
    for i, row in enumerate(rows, 1):
        print(f"{i}. {row['client_order_id'][:8]}...")
        print(f"   Product: {row['product_id']}, Side: {row['side']}")
        print(f"   Size: {row['size']}, Price: {row['price']}")
        print(f"   Replacements: {row['current_order_replacement']}/{row['max_order_replacement']}")
        print(f"   Status: {row['status']}")
        
        # Check if this order is also in stealth_orders (need to cast UUID)
        cursor.execute("""
            SELECT stealth_order_id, status FROM stealth_orders 
            WHERE stealth_order_id::text = %s
        """, (row['client_order_id'],))
        
        stealth = cursor.fetchone()
        if stealth:
            print(f"   ✓ Also in stealth_orders (status: {stealth['status']})")
        else:
            print(f"   ✗ NOT in stealth_orders")
        
        # Check for children
        cursor.execute("""
            SELECT COUNT(*) as cnt FROM order_child 
            WHERE parent_client_order_id = %s
        """, (row['client_order_id'],))
        
        child_count = cursor.fetchone()['cnt']
        print(f"   Children in order_child: {child_count}")
        print()
    
    print("=" * 100)
    print("FINDING: Are order_parent entries also stealth orders?")
    print("=" * 100)
    print()
    
    cursor.execute("""
        SELECT COUNT(*) as cnt FROM order_parent op
        WHERE EXISTS (
            SELECT 1 FROM stealth_orders so 
            WHERE so.stealth_order_id::text = op.client_order_id
        )
    """)
    
    overlap_count = cursor.fetchone()['cnt']
    
    print(f"Order_parent entries that are ALSO stealth orders: {overlap_count}/45")
    print()
    
    if overlap_count > 0:
        print("✓ There IS overlap - some orders are tracked in BOTH tables")
        print("  (Unified tracking strategy)")
    else:
        print("✗ NO overlap - order_parent and stealth_orders are SEPARATE systems")
        print("  (This means stealth orders are NOT also in order_parent)")
    
    conn.close()
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
