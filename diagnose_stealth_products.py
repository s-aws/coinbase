#!/usr/bin/env python3
"""Diagnose which products stealth orders are using."""

import database.order as DB_CLIENT

# Check stealth orders
print("=== Stealth Orders by Product ===")
results = DB_CLIENT.DB_CLIENT.execute_query(
    """SELECT DISTINCT product_id, COUNT(*) as count, status 
       FROM stealth_orders 
       GROUP BY product_id, status
       ORDER BY product_id"""
)

if results:
    for row in results:
        print(f"Product: {row['product_id']:<25} Status: {row['status']:<10} Count: {row['count']}")
else:
    print("No stealth orders found in database")

print("\n=== Subscribed Products ===")
from configuration import Subscription
products = Subscription.product_ids
print(f"Total subscribed: {len(products)}")
print("Derivatives:", Subscription.derivatives_product_ids[:5], "...")
print("Spot:", Subscription.product_ids[len(Subscription.derivatives_product_ids):])
