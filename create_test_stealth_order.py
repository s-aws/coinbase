#!/usr/bin/env python3
"""Create a stealth order for BTC-USDC with price threshold condition."""

from core.stealth_order_manager import StealthOrderManager
import database.order as DB_CLIENT

stealth_manager = StealthOrderManager(DB_CLIENT.DB_CLIENT)

# Create stealth order for BTC-USDC (ticker feeds BTC-USD data which maps to BTC-USDC for trading)
stealth_order_id = stealth_manager.create_stealth_order(
    product_id="BTC-USDC",  # Trading product (receives market data from BTC-USD ticker)
    side="BUY",
    total_size=0.1,  # Buy 0.1 BTC
    limit_price=76000.0,
    reveal_condition={
        "type": "price",
        "price_threshold": 76000.0,
        "direction": "below",
        "hold_duration_seconds": 5
    }
)

print(f"Created stealth order: {stealth_order_id}")
print(f"Trading product: BTC-USDC")
print(f"Receives market data from: BTC-USD ticker feed")
print(f"Condition: Reveal when price drops below $76,000 and holds for 5 seconds")
print(f"\nNow restart the engine and the stealth order will use BTC-USD ticker data")
