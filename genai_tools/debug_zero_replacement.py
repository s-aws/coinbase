#!/usr/bin/env python3
"""Debug script to check which orders have max_order_replacement=0 and if they should."""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from database.database import PostgresDB

def check_zero_replacement_orders():
    """Check which orders have max_order_replacement=0 and their context."""
    db = PostgresDB()
    db.connect()

    print("=" * 80)
    print("CHECKING ORDERS WITH max_order_replacement = 0")
    print("=" * 80)

    query = """
    SELECT id, client_order_id, parent_order_id, product_id, side, size, status, created_at
    FROM order_parent
    WHERE max_order_replacement = 0
    ORDER BY created_at DESC
    """
    try:
        result = db.execute_query(query)
        if result:
            print(f"\nFound {len(result)} orders with max_order_replacement=0:\n")
            for order in result:
                is_child = order['parent_order_id'] is not None
                print(f"ID {order['id']}: {order['client_order_id']}")
                print(f"  Parent ID: {order['parent_order_id']} {'[CHILD ORDER]' if is_child else '[ROOT ORDER]'}")
                print(f"  Product: {order['product_id']}, Side: {order['side']}, Size: {order['size']}")
                print(f"  Status: {order['status']}")
                print(f"  Created: {order['created_at']}")

                if not is_child:
                    print(f"  ⚠️  WARNING: This is a ROOT order (no parent_order_id) with max_order_replacement=0")
                    print(f"      Should probably be 11 (DEFAULT_MAX_ORDER_REPLACEMENT)")
                else:
                    print(f"  ✓ OK: This is a CHILD order, so max_order_replacement=0 is expected")
                print()
        else:
            print("\nNo orders with max_order_replacement=0 found")
    except Exception as e:
        print(f"ERROR: {e}")

    db.disconnect()

if __name__ == "__main__":
    check_zero_replacement_orders()
