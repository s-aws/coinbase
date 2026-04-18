#!/usr/bin/env python3
"""Clean up all stealth orders for fresh start."""

import database.order as DB_CLIENT

print("Deleting all stealth orders for fresh start...")

# Delete by product - go through each known product
products_to_clean = ["BTC-USD", "BTC-USDC", "ETH-USD", "ETH-USDC", "BIP-20DEC30-CDE"]

total_deleted = 0
for product in products_to_clean:
    try:
        deleted = DB_CLIENT.DB_CLIENT.delete("stealth_orders", {"product_id": product})
        if deleted > 0:
            print(f"  Deleted {deleted} from {product}")
            total_deleted += deleted
    except:
        pass

print(f"\nTotal deleted: {total_deleted} stealth orders")
print("Ready to create new stealth orders with correct product mapping")
