#!/usr/bin/env python3
"""Check if parent order is in database and trace parent-child relationships."""

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
    
    parent_id = "be1606c5-981f-4ec7-8eb1-c6a249b27c74"
    child_id = "c8da8ba8-9e7a-4752-ad31-36cabf2c3ad2"
    
    print("=" * 80)
    print(f"Checking parent: {parent_id}")
    print("=" * 80)
    
    # Check if parent exists in order_parent table
    cursor.execute(
        "SELECT * FROM order_parent WHERE client_order_id = %s",
        (parent_id,)
    )
    parent_row = cursor.fetchone()
    
    if parent_row:
        print(f"✓ Parent FOUND in order_parent table")
        print(f"  - DB ID: {parent_row['id']}")
        print(f"  - Product: {parent_row['product_id']}")
        print(f"  - Side: {parent_row['side']}")
        print(f"  - Size: {parent_row['size']}")
        print(f"  - Price: {parent_row['price']}")
        print(f"  - Target Movement: {parent_row['target_movement']}")
        print(f"  - Max Replacements: {parent_row['max_order_replacement']}")
        print(f"  - Current Replacements: {parent_row['current_order_replacement']}")
    else:
        print(f"✗ Parent NOT FOUND in order_parent table")
    
    print("\n" + "=" * 80)
    print(f"Checking child: {child_id}")
    print("=" * 80)
    
    # Check if child exists
    cursor.execute(
        "SELECT * FROM order_child WHERE client_order_id = %s",
        (child_id,)
    )
    child_row = cursor.fetchone()
    
    if child_row:
        print(f"✓ Child FOUND in order_child table")
        print(f"  - DB ID: {child_row['id']}")
        print(f"  - Parent ID (FK): {child_row['parent_order_id']}")
        print(f"  - Product: {child_row['product_id']}")
        print(f"  - Side: {child_row['side']}")
        print(f"  - Size: {child_row['size']}")
        print(f"  - Price: {child_row['price']}")
        print(f"  - Status: {child_row['status']}")
    else:
        print(f"✗ Child NOT FOUND in order_child table")
    
    print("\n" + "=" * 80)
    print("Tracing parent-child chain")
    print("=" * 80)
    
    # Trace all children of parent
    cursor.execute(
        "SELECT client_order_id, product_id, side, size, price, status FROM order_child WHERE parent_client_order_id = %s",
        (parent_id,)
    )
    children = cursor.fetchall()
    
    if children:
        print(f"Parent {parent_id} has {len(children)} direct child(ren):")
        for child in children:
            print(f"  - {child['client_order_id']} ({child['product_id']} {child['side']} {child['size']} @ {child['price']}) [{child['status']}]")
    else:
        print(f"✗ Parent {parent_id} has NO children in database")
    
    # Try to find the chain backwards
    print("\n" + "=" * 80)
    print("Tracing backwards from child to find root parent")
    print("=" * 80)
    
    current = child_id
    chain = [current]
    
    for i in range(10):  # Max 10 levels to prevent infinite loops
        cursor.execute(
            "SELECT parent_client_order_id FROM order_child WHERE client_order_id = %s",
            (current,)
        )
        result = cursor.fetchone()
        
        if result and result['parent_client_order_id']:
            current = result['parent_client_order_id']
            chain.insert(0, current)
        else:
            # Check if it's a parent
            cursor.execute(
                "SELECT client_order_id FROM order_parent WHERE client_order_id = %s",
                (current,)
            )
            if cursor.fetchone():
                break
            else:
                break
    
    print("Chain (root → ... → leaf):")
    for i, order_id in enumerate(chain):
        prefix = "├─ " if i < len(chain) - 1 else "└─ "
        print(f"{prefix}{order_id}")
    
    conn.close()
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
