"""Example script demonstrating limit order placement for various products.

Creates sample limit orders for derivatives and spot trading pairs.
Includes configurable parameters for order sizing, pricing, and delays.

Example:
    >>> python tools/diagnostics/main_place_order.py
    # Output: JSON array of order responses with success/error details

See order.py create_limit_order_span() docstring for more examples.
"""
import json

from _bootstrap import ensure_repo_root

ensure_repo_root()

from order import create_limit_order_span

if __name__ == "__main__":

    ##################### PERP - BTC #####################

    orders = create_limit_order_span(
        delay_in_secs=0,
        product_id="BIP-20DEC30-CDE",
        side="SELL",
        order_base_size_range={"start": 1, "stop": 1},
        order_price_difference=250,
        start_price=77000,
        max_order_count=1,
        post_only=True
    )
    print(json.dumps(orders))
    print(f"Count: {len(orders)}")

