#!/usr/bin/env python3
"""Correction script to fix replacement count mismatches in the database."""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from database.database import PostgresDB

def fix_replacement_counts():
    """Fix all replacement count mismatches."""
    db = PostgresDB()
    db.connect()

    print("=" * 80)
    print("FIXING REPLACEMENT COUNT MISMATCHES")
    print("=" * 80)

    # Find mismatches
    query = """
    SELECT
        op.id,
        op.client_order_id,
        op.current_order_replacement,
        COUNT(so.stealth_order_id) as actual_children_count
    FROM order_parent op
    LEFT JOIN stealth_orders so ON so.parent_order_id::text = op.client_order_id
    WHERE op.parent_order_id IS NULL
    GROUP BY op.id, op.client_order_id, op.current_order_replacement
    HAVING COUNT(so.stealth_order_id) != op.current_order_replacement
    """

    result = db.execute_query(query)

    if not result:
        print("\n✓ No mismatches found!")
        db.disconnect()
        return

    print(f"\nFound {len(result)} mismatches to fix:\n")

    for order in result:
        order_id = order['client_order_id']
        current = order['current_order_replacement']
        actual = order['actual_children_count']

        print(f"  Fixing {order_id[:8]}...")
        print(f"    Current: {current} → Actual: {actual}")

        # Update the database
        update_query = """
        UPDATE order_parent
        SET current_order_replacement = %s
        WHERE client_order_id = %s
        """

        rows_affected = db.execute_update(update_query, (actual, order_id))

        if rows_affected > 0:
            print(f"    ✓ Updated")
        else:
            print(f"    ✗ Failed to update")

    print("\n" + "=" * 80)
    print("VERIFICATION")
    print("=" * 80)

    # Verify the fix
    verify_result = db.execute_query(query)

    if verify_result:
        print(f"\n✗ Still {len(verify_result)} mismatches found!")
        for order in verify_result:
            print(f"  {order['client_order_id'][:8]}... current={order['current_order_replacement']} actual={order['actual_children_count']}")
    else:
        print("\n✓ All replacement counts are now correct!")

    db.disconnect()

if __name__ == "__main__":
    fix_replacement_counts()
