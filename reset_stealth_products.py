#!/usr/bin/env python3
"""Reset stealth orders to use correct product IDs."""

import database.order as DB_CLIENT

# Delete old stealth orders with incorrect product IDs
print("Deleting old stealth orders with incorrect product IDs...")
deleted = DB_CLIENT.DB_CLIENT.delete("stealth_orders", {"product_id": "BTC-USD"})
print(f"Deleted {deleted} BTC-USD stealth orders")

print("\nNow create stealth orders for BTC-USDC (receives market data from BTC-USD ticker)")
print("Available ticker products: BTC-USD, ETH-USD, DOGE-USD, etc.")
print("These map to trading products: BTC-USDC, ETH-USDC, DOGE-USDC, etc.")
