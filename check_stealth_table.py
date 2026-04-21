#!/usr/bin/env python3
"""Check if stealth orders are in the stealth_orders table."""

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
    
    chain_ids = [
        "c37ae73a-5e20-4b27-99a9-e1c88430cc03",
        "e874487c-1016-4d95-a230-32670db37edf",
        "be1606c5-981f-4ec7-8eb1-c6a249b27c74",
        "c8da8ba8-9e7a-4752-ad31-36cabf2c3ad2",
    ]
    
    print("=" * 100)
    print("CHECKING STEALTH_ORDERS TABLE")
    print("=" * 100)
    print()
    
    for order_id in chain_ids:
        cursor.execute(
            "SELECT stealth_order_id, parent_order_id, product_id, side, status FROM stealth_orders WHERE stealth_order_id = %s",
            (order_id,)
        )
        row = cursor.fetchone()
        
        if row:
            print(f"✓ {order_id}")
            print(f"  - Parent Stealth ID: {row['parent_order_id']}")
            print(f"  - Product: {row['product_id']}")
            print(f"  - Side: {row['side']}")
            print(f"  - Status: {row['status']}")
        else:
            print(f"✗ {order_id} NOT FOUND in stealth_orders")
    
    print("\n" + "=" * 100)
    print("CHECKING IF ANY ORDER IN STEALTH_ORDERS HAS THESE AS CHILDREN")
    print("=" * 100)
    print()
    
    for order_id in chain_ids:
        cursor.execute(
            "SELECT stealth_order_id, parent_order_id FROM stealth_orders WHERE parent_order_id = %s",
            (order_id,)
        )
        children = cursor.fetchall()
        
        if children:
            print(f"{order_id} has {len(children)} child(ren) in stealth_orders:")
            for child in children:
                print(f"  - {child['stealth_order_id']}")
        else:
            print(f"{order_id} has no children in stealth_orders")
    
    conn.close()
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
