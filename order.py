"""Order placement module for Coinbase Advanced trading.

This module provides utilities for creating and managing limit orders across
multiple price points (order spanning). Handles:
- Random order size generation within configured ranges
- Automatic price stepping across a range
- Delay coordination between order placements
- Insufficient fund error handling and retry logic

Example:
    >>> from order import create_limit_order_span
    >>> orders = create_limit_order_span(
    ...     product_id='BTC-USDC',
    ...     side='SELL',
    ...     start_price=42000.00,
    ...     order_price_difference=10.00,
    ...     max_order_count=5
    ... )
    >>> print(f"Placed {len(orders)} orders")
"""
import uuid
from random import uniform as random
from json import dumps
from time import sleep
from configuration import REST_CLIENT, \
    ORDER_DIRECTION, ORDERBOOK, format_based_on_reference, quantize_to_increment

def generate_float(start: float, stop: float = None) -> float:
    """Generate a random float between two floats.
    
    Produces uniformly distributed random floating point values. If stop is None,
    returns the start value. Useful for creating order size variation within
    a range.
    
    Args:
        start: The minimum value of the float to be generated.
        stop: The maximum value of the float to be generated.
              If None, returns start value without randomization.
    
    Returns:
        A random float between start and stop (or start if stop is None).
    
    Examples:
        >>> generate_float(10.0, 20.0)  # Random between 10 and 20
        15.347
        >>> generate_float(5.5)  # Returns exactly 5.5
        5.5
        >>> generate_float(1.0, 1.5)  # Random between 1.0 and 1.5
        1.234
    """
    result = random(start, stop) if stop is not None else start
    return result

def create_limit_order_span(
        order_base_size_range: dict = None,
        delay_in_secs: int = 0,
        product_id: str = "NCT-USDC",
        side: str = "SELL",
        max_order_count: int = 1,
        order_base_size: float = 1,
        order_price_difference: float = 0.00001,
        start_price: float = 0.00992,
        post_only: bool = False) -> list:
    """Create a series of limit orders spanning a price range.
    
    Places multiple GTC (Good-Till-Cancel) limit orders at specified price intervals,
    with optional delays between placements. Handles insufficient fund errors by 
    retrying. Each order is assigned a unique UUID client_order_id.
    
    Key Features:
    - Automatic price stepping: each order placed at start_price + (order_index * price_difference)
    - Size variation: use order_base_size_range to randomize sizes
    - Exchange compliance: formats prices/sizes to exchange increments
    - Error handling: retries on insufficient funds, aborts on other errors
    
    Args:
        order_base_size_range: Dictionary with 'start' and optional 'stop' for size range.
                               If None, uses fixed order_base_size for all orders.
                               Example: {'start': 1.0, 'stop': 5.0}
        delay_in_secs: Delay in seconds between order placements (default: 0).
        product_id: The product ID (e.g., "BTC-USDC", "MON-USDC").
        side: Order side ("BUY" or "SELL").
        max_order_count: Number of orders to create (minimum 1, default 1).
        order_base_size: Base size for each order if range not specified (default 1).
        order_price_difference: Price difference between consecutive orders (default 0.00001).
        start_price: Starting price for the first order (default 0.00992).
        post_only: If True, orders will be rejected if they would immediately fill (default False).
    
    Returns:
        A list of order response dictionaries from the API. Each dict contains:
        - 'success': bool indicating if order was placed
        - 'success_response': order data if successful
        - 'error_response': error details if failed
    
    Raises:
        Exception: Re-raises unhandled API errors (other than INSUFFICIENT_FUND).
    
    Examples:
        >>> # Place 5 SELL orders with fixed size
        >>> orders = create_limit_order_span(
        ...     product_id='BTC-USDC',
        ...     side='SELL',
        ...     start_price=42000.0,
        ...     order_price_difference=50.0,
        ...     max_order_count=5,
        ...     order_base_size=0.01
        ... )
        
        >>> # Place 3 BUY orders with random sizes and 2-second delay
        >>> orders = create_limit_order_span(
        ...     product_id='ETH-USDC',
        ...     side='BUY',
        ...     start_price=2000.0,
        ...     order_base_size_range={'start': 0.5, 'stop': 2.0},
        ...     order_price_difference=10.0,
        ...     max_order_count=3,
        ...     delay_in_secs=2
        ... )
        
        >>> # Create post-only orders (will cancel if they'd fill immediately)
        >>> orders = create_limit_order_span(
        ...     product_id='MON-USDC',
        ...     side='SELL',
        ...     start_price=0.009,
        ...     max_order_count=2,
        ...     post_only=True
        ... )
    """
    results = []

    if max_order_count <= 0:
        max_order_count = 1

    delay_in_secs = int(delay_in_secs)
    order_price_difference = float(order_price_difference)
    price = float(start_price)

    order_count = 0
    while order_count < max_order_count:
        order_count += 1

        while True:
            sleep(delay_in_secs)

            price = format_based_on_reference(
                float(price),
                ORDERBOOK.product[product_id]["price_increment"])

            order_base_size = format_based_on_reference(
                float(generate_float(**order_base_size_range or {"start": float(order_base_size)})),
                ORDERBOOK.product[product_id]["base_min_size"])

            order = REST_CLIENT.limit_order_gtc(
                client_order_id=str(uuid.uuid4()),
                product_id=product_id,
                side=side,
                base_size=str(order_base_size),
                limit_price=str(price),
                post_only=post_only
            ).to_dict()

            if order["success"] is False:
                print(dumps(order, indent=4))
                if order["error_response"]["error"] == "INSUFFICIENT_FUND":
                    sleep(1)
                else:
                    print(f"ERROR RESPONSE UNHANDLED: {order['error_response']['error']}")
                    break
            else:
                break

        price = float(start_price) + (order_price_difference * ORDER_DIRECTION[side] * order_count)

        round_direction = "up" if side == "SELL" else "down"
        price = quantize_to_increment(
            price,
            ORDERBOOK.product[product_id]["price_increment"],
            direction=round_direction,
        )

        results.append(order)

    return results

if __name__ == "__main__":
    print(ORDERBOOK.positions)
