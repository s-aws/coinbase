#!/usr/bin/env python3
"""Check target_movement values in the stealth_orders table."""

import sys
import os
os.chdir('/e/coinbase')
sys.path.insert(0, '/e/coinbase')

from database.order import DB_CLIENT
import sqlite3

# Connect to database
db = DB_CLIENT.db_path
conn = sqlite3.connect(db)
cursor = conn.cursor()

# Query stealth_orders table
query = """
SELECT stealth_order_id, product_id, target_movement, target_movement_type, created_at
FROM stealth_orders
ORDER BY created_at DESC
LIMIT 10
"""

print("=" * 100)
print("STEALTH ORDERS - Target Movement Values")
print("=" * 100)

try:
    cursor.execute(query)
    rows = cursor.fetchall()

    if not rows:
        print("No stealth orders found.")
    else:
        for row in rows:
            stealth_id, product_id, target_movement, target_movement_type, created_at = row
            display_value = float(target_movement) * 100 if target_movement_type == 'P' else float(target_movement)
            display_unit = '%' if target_movement_type == 'P' else '(Abs)'

            print(f"\nStealth Order ID: {stealth_id[:8]}...")
            print(f"  Product: {product_id}")
            print(f"  DB Value: {target_movement} | DB Type: {target_movement_type}")
            print(f"  Display: {display_value:.4f}{display_unit}")
            print(f"  Created: {created_at}")

except Exception as e:
    print(f"Error querying database: {e}")
finally:
    conn.close()

print("\n" + "=" * 100)
