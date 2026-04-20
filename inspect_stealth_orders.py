#!/usr/bin/env python3
"""Inspect stealth_orders table to check parent_order_id values."""

from database.database import PostgresDB

db = PostgresDB()
db.connect()

try:
    # Get all stealth orders
    results = db.execute_query(
        """SELECT stealth_order_id, product_id, status, parent_order_id, created_at 
           FROM stealth_orders 
           ORDER BY product_id, created_at DESC"""
    )
    
    print(f"Total stealth orders: {len(results) if results else 0}")
    print("=" * 100)
    
    if results:
        for row in results:
            parent_indicator = "CHILD" if row['parent_order_id'] else "PARENT"
            print(f"{parent_indicator:6} | {row['product_id']:15} | {row['status']:10} | {row['created_at']}")
            print(f"        ID: {row['stealth_order_id']}")
            if row['parent_order_id']:
                print(f"        Parent ID: {row['parent_order_id']}")
            print()
    else:
        print("No stealth orders found in database")
        
except Exception as e:
    print(f"Error querying database: {e}")
    import traceback
    traceback.print_exc()
finally:
    db.disconnect()
