#!/usr/bin/env python3
"""Diagnose the parent-child order chain for stealth orders."""

import psycopg2
from psycopg2.extras import RealDictCursor

# Database connection
try:
    conn = psycopg2.connect(
        host="127.0.0.1",
        port=5432,
        database="postgres",
        user="postgres",
        password="postgres"
    )
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    # The chain from the logs
    chain_ids = [
        "c37ae73a-5e20-4b27-99a9-e1c88430cc03",  # root parent
        "e874487c-1016-4d95-a230-32670db37edf",  # child of root
        "be1606c5-981f-4ec7-8eb1-c6a249b27c74",  # child of e874487c
        "c8da8ba8-9e7a-4752-ad31-36cabf2c3ad2",  # child of be1606c5
    ]
    
    print("=" * 100)
    print("PARENT-CHILD CHAIN DIAGNOSTIC")
    print("=" * 100)
    print()
    
    for idx, order_id in enumerate(chain_ids, 1):
        print(f"\n{idx}. Order: {order_id}")
        print("-" * 100)
        
        # Check if it's a parent
        cursor.execute("SELECT id, client_order_id, product_id, side, size FROM order_parent WHERE client_order_id = %s", (order_id,))
        parent_row = cursor.fetchone()
        
        # Check if it's a child
        cursor.execute("SELECT id, client_order_id, parent_client_order_id, product_id, side FROM order_child WHERE client_order_id = %s", (order_id,))
        child_row = cursor.fetchone()
        
        if parent_row:
            print(f"  ✓ EXISTS AS PARENT in order_parent table")
            print(f"    - DB ID: {parent_row['id']}")
            print(f"    - Product: {parent_row['product_id']}")
            print(f"    - Side: {parent_row['side']}")
            print(f"    - Size: {parent_row['size']}")
        elif child_row:
            print(f"  ✓ EXISTS AS CHILD in order_child table")
            print(f"    - DB ID: {child_row['id']}")
            print(f"    - Parent FK: {child_row['parent_client_order_id']}")
            print(f"    - Product: {child_row['product_id']}")
            print(f"    - Side: {child_row['side']}")
        else:
            print(f"  ✗ NOT FOUND in either order_parent or order_child table")
    
    print("\n" + "=" * 100)
    print("CHAIN STRUCTURE ANALYSIS")
    print("=" * 100)
    print()
    print("Expected chain from logs:")
    print(f"  {chain_ids[0]} (parent)")
    print(f"    └─ {chain_ids[1]} (child)")
    print(f"        └─ {chain_ids[2]} (grandchild)")
    print(f"            └─ {chain_ids[3]} (great-grandchild)")
    
    print("\nActual structure in database:")
    
    # Check parent 1
    cursor.execute(
        "SELECT client_order_id FROM order_child WHERE parent_client_order_id = %s",
        (chain_ids[0],)
    )
    children_of_root = cursor.fetchall()
    
    if children_of_root:
        print(f"  {chain_ids[0]} (parent)")
        for child in children_of_root:
            print(f"    └─ {child['client_order_id']} (child)")
            
            # Check grandchildren
            cursor.execute(
                "SELECT client_order_id FROM order_child WHERE parent_client_order_id = %s",
                (child['client_order_id'],)
            )
            grandchildren = cursor.fetchall()
            if grandchildren:
                for grandchild in grandchildren:
                    print(f"        └─ {grandchild['client_order_id']} (grandchild)")
    else:
        print(f"  {chain_ids[0]} (parent)")
        print(f"    ✗ NO CHILDREN FOUND IN DATABASE")
    
    print("\n" + "=" * 100)
    print("DIAGNOSIS")
    print("=" * 100)
    
    # Check if parent exists
    cursor.execute("SELECT id FROM order_parent WHERE client_order_id = %s", (chain_ids[0],))
    if not cursor.fetchone():
        print("✗ CRITICAL: Root parent doesn't exist as parent entry!")
    
    # Check the key missing pieces
    cursor.execute("SELECT id FROM order_parent WHERE client_order_id = %s", (chain_ids[2],))
    if not cursor.fetchone():
        print(f"✗ CRITICAL: {chain_ids[2]} is not in order_parent table")
        print(f"   This is why {chain_ids[3]} cannot be inserted as its child (FK violation)")
    
    conn.close()
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
