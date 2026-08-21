#!/usr/bin/env python3
"""Update stealth_orders table with parent-child relationships from logs.

This debugging tool updates existing stealth orders with parent-child relationships
based on stealth_follow_up_created events from application logs.

Used when: Stealth follow-up orders are created but parent_order_id is not persisted correctly.
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.database import PostgresDB

# Stealth follow-up relationships extracted from logs
# Format: (parent_stealth_id, child_stealth_id)
relationships = [
    ('64d1761a-d0f8-4805-becc-7ef88e04d476', '05e136cf-2458-4908-b07d-5445622e1e5e'),
    ('a89499ce-4f45-47d8-8972-ba194ab3afee', 'fafd0768-291c-4508-842c-f53bfbd22d74'),
    ('fafd0768-291c-4508-842c-f53bfbd22d74', '0dcd9081-1e9d-4804-a3f7-10c2de8f0c51'),
    ('05e136cf-2458-4908-b07d-5445622e1e5e', '8388707a-a81e-4254-8f66-0fa126882205'),
]

db = PostgresDB()
db.connect()

try:
    updated_count = 0
    for parent_id, child_id in relationships:
        db.execute_update(
            """UPDATE stealth_orders
               SET parent_order_id = %s
               WHERE stealth_order_id = %s""",
            (parent_id, child_id)
        )
        print(f"✓ Updated {child_id[:8]}... → parent {parent_id[:8]}...")
        updated_count += 1

    print(f"\n✓ Successfully updated {updated_count} stealth orders with parent-child relationships")

    # Verify the updates
    print("\n" + "=" * 100)
    print("VERIFICATION:")
    print("=" * 100)
    results = db.execute_query(
        """SELECT stealth_order_id, product_id, status, parent_order_id, created_at
           FROM stealth_orders
           WHERE parent_order_id IS NOT NULL
           ORDER BY created_at DESC"""
    )

    if results:
        print(f"Found {len(results)} child stealth orders:")
        for row in results:
            print(f"  {row['stealth_order_id'][:8]}... (parent: {row['parent_order_id'][:8]}...)")
    else:
        print("No child stealth orders found")

except Exception as e:
    print(f"Error updating database: {e}")
    import traceback
    traceback.print_exc()
finally:
    db.disconnect()
