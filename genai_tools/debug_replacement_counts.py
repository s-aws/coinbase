#!/usr/bin/env python3
"""Debug script to trace the current_order_replacement flow."""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from database.database import PostgresDB

def analyze_order_counts():
    """Analyze current_order_replacement and max_order_replacement values."""
    db = PostgresDB()
    db.connect()

    print("=" * 80)
    print("ANALYZING ORDER REPLACEMENT COUNTS")
    print("=" * 80)

    # Query to show parent/child relationship and their counts
    query = """
    SELECT
        op.id,
        op.client_order_id,
        op.parent_order_id,
        op.product_id,
        op.side,
        op.max_order_replacement,
        op.current_order_replacement,
        op.status,
        COUNT(CASE WHEN so.parent_order_id::text = op.client_order_id THEN 1 END) as actual_children_count
    FROM order_parent op
    LEFT JOIN stealth_orders so ON so.parent_order_id::text = op.client_order_id
    GROUP BY op.id, op.client_order_id, op.parent_order_id, op.product_id,
             op.side, op.max_order_replacement, op.current_order_replacement, op.status
    ORDER BY op.created_at DESC
    """

    try:
        result = db.execute_query(query)
        if result:
            print(f"\nFound {len(result)} orders:\n")
            print("ID | Type | Max | Current | Actual Children | Status | Product | Side | Parent ID")
            print("-" * 100)

            for order in result:
                order_type = "ROOT" if order['parent_order_id'] is None else "CHILD"
                max_repl = order['max_order_replacement']
                curr_repl = order['current_order_replacement']
                actual = order['actual_children_count']

                status = f"{curr_repl}/{max_repl}"
                mismatch = "⚠️" if curr_repl != actual else "✓"

                print(f"{order['id']:2} | {order_type:4} | {max_repl:3} | {curr_repl:7} | {actual:3} {mismatch}        | {order['status']:7} | {order['product_id']:10} | {order['side']:4} | {order['parent_order_id']}")

            # Analysis
            print("\n" + "=" * 80)
            print("ANALYSIS:")
            print("=" * 80)

            issues = []

            for order in result:
                order_type = "ROOT" if order['parent_order_id'] is None else "CHILD"
                curr_repl = order['current_order_replacement']
                actual = order['actual_children_count']
                max_repl = order['max_order_replacement']

                # Check 1: current_order_replacement vs actual children count
                if curr_repl != actual:
                    issues.append(f"  ❌ Order {order['id']} ({order['client_order_id'][:8]}...)")
                    issues.append(f"     - current_order_replacement: {curr_repl}")
                    issues.append(f"     - actual children: {actual}")
                    issues.append(f"     ➜ Count mismatch detected!")

                # Check 2: Child orders should have max_order_replacement = 0
                if order_type == "CHILD" and max_repl != 0:
                    issues.append(f"  ❌ Child order {order['id']} ({order['client_order_id'][:8]}...)")
                    issues.append(f"     - max_order_replacement: {max_repl} (should be 0)")
                    issues.append(f"     ➜ Child has non-zero max replacements!")

                # Check 3: If current >= max, no more follow-ups allowed
                if order_type == "ROOT" and curr_repl >= max_repl and max_repl > 0:
                    issues.append(f"  ⚠️  Order {order['id']} ({order['client_order_id'][:8]}...)")
                    issues.append(f"     - current_order_replacement: {curr_repl}")
                    issues.append(f"     - max_order_replacement: {max_repl}")
                    issues.append(f"     ➜ No more follow-ups allowed (limit reached)")

            if issues:
                print("\nISSUES FOUND:\n")
                for issue in issues:
                    print(issue)
            else:
                print("\n✓ No issues found - all replacement counts are correct!")
        else:
            print("\nNo orders found in database")
    except Exception as e:
        print(f"ERROR: {e}")

    db.disconnect()

if __name__ == "__main__":
    analyze_order_counts()
