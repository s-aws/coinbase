#!/usr/bin/env python3
"""Check all target_movement values to find any with 2% instead of 0.2%."""

import sys
import os
os.chdir('e:\\coinbase')
sys.path.insert(0, 'e:\\coinbase')

from database.order import DB_CLIENT

query = """
SELECT stealth_order_id, product_id, target_movement, target_movement_type, created_at
FROM stealth_orders
WHERE target_movement IS NOT NULL
ORDER BY target_movement DESC
"""

print("=" * 110)
print("STEALTH ORDERS - All Target Movement Values (Sorted by Value)")
print("=" * 110)

try:
    results = DB_CLIENT.execute_query(query)

    if not results:
        print("No stealth orders found.")
    else:
        print(f"\n{'Stealth ID':<40} {'Product':<15} {'DB Value':<15} {'Type':<6} {'Display':<15}")
        print("-" * 110)

        for row in results:
            # Handle both dict and tuple formats
            if isinstance(row, dict):
                stealth_id = row.get('stealth_order_id', 'N/A')
                product_id = row.get('product_id', 'N/A')
                target_movement = row.get('target_movement')
                target_movement_type = row.get('target_movement_type', 'P')
            else:
                stealth_id, product_id, target_movement, target_movement_type, _ = row

            # Calculate display value
            if target_movement is not None:
                try:
                    if target_movement_type == 'P':
                        display_value = float(target_movement) * 100
                        display_unit = '%'
                    else:
                        display_value = float(target_movement)
                        display_unit = '(Abs)'
                    display_str = f"{display_value:.6f}{display_unit}"
                except (ValueError, TypeError):
                    display_str = str(target_movement)
            else:
                display_str = "None"

            print(f"{str(stealth_id)[:40]:<40} {str(product_id):<15} {str(target_movement):<15} {str(target_movement_type):<6} {display_str:<15}")

        print("\n" + "=" * 110)
        print(f"Total orders shown: {len(results)}")

        # Group by target_movement value
        value_groups = {}
        for row in results:
            if isinstance(row, dict):
                target_movement = row.get('target_movement')
            else:
                target_movement = row[2]

            if target_movement not in value_groups:
                value_groups[target_movement] = 0
            value_groups[target_movement] += 1

        print("\nValue Distribution:")
        print("-" * 50)
        for value in sorted(value_groups.keys(), reverse=True):
            if value:
                pct = float(value) * 100
                print(f"  {value:>15} → {pct:>10.6f}%   (Count: {value_groups[value]})")

except Exception as e:
    print(f"Error querying database: {e}")
    import traceback
    traceback.print_exc()
