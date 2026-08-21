#!/usr/bin/env python3
"""Check target_movement values in the stealth_orders table."""

import sys
import os
os.chdir('e:\\coinbase')
sys.path.insert(0, 'e:\\coinbase')

from database.order import DB_CLIENT

query = """
SELECT stealth_order_id, product_id, target_movement, target_movement_type, created_at
FROM stealth_orders
ORDER BY created_at DESC
LIMIT 15
"""

print("=" * 110)
print("STEALTH ORDERS - Target Movement Values (Last 15)")
print("=" * 110)

try:
    results = DB_CLIENT.execute_query(query)

    if not results:
        print("No stealth orders found.")
    else:
        print(f"\n{'Stealth ID':<40} {'Product':<12} {'DB Value':<12} {'Type':<6} {'Display':<15} {'Created':<19}")
        print("-" * 110)

        for row in results:
            # Handle both dict and tuple formats
            if isinstance(row, dict):
                stealth_id = row.get('stealth_order_id', 'N/A')
                product_id = row.get('product_id', 'N/A')
                target_movement = row.get('target_movement')
                target_movement_type = row.get('target_movement_type', 'P')
                created_at = row.get('created_at', 'N/A')
            else:
                stealth_id, product_id, target_movement, target_movement_type, created_at = row

            # Calculate display value
            if target_movement is not None:
                try:
                    if target_movement_type == 'P':
                        display_value = float(target_movement) * 100
                        display_unit = '%'
                    else:
                        display_value = float(target_movement)
                        display_unit = '(Abs)'
                    display_str = f"{display_value:.4f}{display_unit}"
                except (ValueError, TypeError):
                    display_str = str(target_movement)
            else:
                display_str = "None"

            print(f"{str(stealth_id)[:40]:<40} {str(product_id):<12} {str(target_movement):<12} {str(target_movement_type):<6} {display_str:<15} {str(created_at):<19}")

        print("\n" + "=" * 110)
        print(f"Total orders shown: {len(results)}")

except Exception as e:
    print(f"Error querying database: {e}")
    import traceback
    traceback.print_exc()
