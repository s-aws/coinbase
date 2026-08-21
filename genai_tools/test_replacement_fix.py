#!/usr/bin/env python3
"""Test script to verify the register_child_order fix."""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from database.database import PostgresDB
from database.order import increment_order_parent_replacement_count

def test_increment_function():
    """Test that the increment_order_parent_replacement_count function works."""
    print("=" * 80)
    print("TESTING INCREMENT FUNCTION")
    print("=" * 80)

    db = PostgresDB()
    db.connect()

    # Get a sample parent order
    query = "SELECT client_order_id, current_order_replacement FROM order_parent WHERE parent_order_id IS NULL LIMIT 1"
    result = db.execute_query(query)

    if not result:
        print("No parent orders found to test with")
        db.disconnect()
        return

    parent_id = result[0]["client_order_id"]
    initial_count = result[0]["current_order_replacement"]

    print(f"\nTest parent order: {parent_id}")
    print(f"Initial count: {initial_count}")

    # Increment it
    new_count = increment_order_parent_replacement_count(parent_id)
    print(f"After increment_order_parent_replacement_count(): {new_count}")

    # Verify in database
    result2 = db.execute_query(f"SELECT current_order_replacement FROM order_parent WHERE client_order_id = %s", (parent_id,))
    if result2:
        db_count = result2[0]["current_order_replacement"]
        print(f"Verified in database: {db_count}")

        if new_count == db_count == initial_count + 1:
            print("✓ Increment function works correctly!")
        else:
            print(f"✗ Mismatch: function returned {new_count}, database has {db_count}")

    # Decrement it back for cleanup
    set_query = f"UPDATE order_parent SET current_order_replacement = {initial_count} WHERE client_order_id = '{parent_id}'"
    db.execute_update(set_query, ())
    print(f"Reverted to original count {initial_count} for cleanup")

    db.disconnect()

def test_replace_count_tracking():
    """Test that counting logic works correctly."""
    print("\n" + "=" * 80)
    print("TESTING COUNT TRACKING LOGIC")
    print("=" * 80)

    db = PostgresDB()
    db.connect()

    query = """
    SELECT
        op.client_order_id,
        op.max_order_replacement,
        op.current_order_replacement,
        COUNT(so.stealth_order_id) as actual_children_count
    FROM order_parent op
    LEFT JOIN stealth_orders so ON so.parent_order_id::text = op.client_order_id
    WHERE op.parent_order_id IS NULL
    GROUP BY op.id, op.client_order_id, op.max_order_replacement, op.current_order_replacement
    HAVING COUNT(so.stealth_order_id) > 0
    ORDER BY op.current_order_replacement DESC
    """

    result = db.execute_query(query)

    if result:
        print(f"\nFound {len(result)} parent orders with children:\n")

        mismatches = []
        for order in result:
            curr = order['current_order_replacement']
            actual = order['actual_children_count']
            match = "✓" if curr == actual else "✗"
            print(f"{match} {order['client_order_id'][:8]}... | current={curr}, actual={actual}")

            if curr != actual:
                mismatches.append({
                    'id': order['client_order_id'],
                    'current': curr,
                    'actual': actual
                })

        if mismatches:
            print(f"\n⚠️  Found {len(mismatches)} count mismatches")
            print("These orders need their counts reset:")
            for m in mismatches:
                print(f"  - {m['id'][:8]}... should have current_order_replacement = {m['actual']}")
        else:
            print("\n✓ All counts match!")
    else:
        print("No parent orders with children found")

    db.disconnect()

if __name__ == "__main__":
    test_increment_function()
    test_replace_count_tracking()
    print()
