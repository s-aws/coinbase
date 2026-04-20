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
        # Group orders: separate parents from children
        parents = {}  # parent_order_id -> parent row
        children = {}  # parent_order_id -> [child rows]
        orphaned_children = []  # children with non-existent parents
        
        # First pass: identify all parents
        for row in results:
            if not row['parent_order_id']:
                parents[row['stealth_order_id']] = row
        
        # Second pass: group children under parents
        for row in results:
            if row['parent_order_id']:
                if row['parent_order_id'] in parents:
                    if row['parent_order_id'] not in children:
                        children[row['parent_order_id']] = []
                    children[row['parent_order_id']].append(row)
                else:
                    orphaned_children.append(row)
        
        # Print parents with their children
        for parent_id, parent_row in parents.items():
            print(f"{'PARENT':6} | {parent_row['product_id']:15} | {parent_row['status']:10} | {parent_row['created_at']}")
            print(f"        ID: {parent_row['stealth_order_id']}")
            print()
            
            # Print all children under this parent
            if parent_id in children:
                for child_row in children[parent_id]:
                    print(f"{'CHILD':6} | {child_row['product_id']:15} | {child_row['status']:10} | {child_row['created_at']}")
                    print(f"        ID: {child_row['stealth_order_id']}")
                    print(f"        Parent ID: {child_row['parent_order_id']}")
                    print()
        
        # Print orphaned children (if any)
        if orphaned_children:
            print("\n" + "=" * 100)
            print("ORPHANED CHILDREN (parent not found):")
            print("=" * 100)
            for child_row in orphaned_children:
                print(f"{'CHILD':6} | {child_row['product_id']:15} | {child_row['status']:10} | {child_row['created_at']}")
                print(f"        ID: {child_row['stealth_order_id']}")
                print(f"        Parent ID: {child_row['parent_order_id']}")
                print()
    else:
        print("No stealth orders found in database")
        
except Exception as e:
    print(f"Error querying database: {e}")
    import traceback
    traceback.print_exc()
finally:
    db.disconnect()
