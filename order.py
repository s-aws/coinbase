"""Order placement module for Coinbase Advanced trading.

This module provides utilities for creating and managing limit orders across
multiple price points (order spanning). Handles:
- Random order size generation within configured ranges
- Automatic price stepping across a range
- Delay coordination between order placements
- Insufficient fund error handling and retry logic
- Optional stealth (hidden) order creation with reveal conditions

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
    
    >>> # Place as stealth order (hidden until condition met)
    >>> stealth_orders = create_limit_order_span(
    ...     product_id='BTC-USDC',
    ...     side='SELL',
    ...     start_price=42000.00,
    ...     order_base_size=0.5,
    ...     max_order_count=1,
    ...     use_stealth=True,
    ...     reveal_condition={
    ...         'type': 'price',
    ...         'price_threshold': 41500.00,
    ...         'direction': 'below'
    ...     }
    ... )
"""
import uuid
from random import uniform as random
from json import dumps
from time import sleep
from configuration import REST_CLIENT, \
    ORDER_DIRECTION, ORDERBOOK, format_based_on_reference, quantize_to_increment

# Global stealth bridge reference (set by dashboard_server)
_stealth_order_bridge = None

def set_stealth_order_bridge(bridge):
    """Set the global stealth order bridge reference.
    
    Called by dashboard_server during initialization to enable stealth order
    support in create_limit_order_span().
    
    Args:
        bridge: StealthOrderBridge instance
    """
    global _stealth_order_bridge
    _stealth_order_bridge = bridge

def get_stealth_order_bridge():
    """Get the global stealth order bridge reference.
    
    Returns:
        StealthOrderBridge instance if available, None otherwise
    """
    return _stealth_order_bridge

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
        post_only: bool = False,
        use_stealth: bool = False,
        reveal_condition: dict = None,
        sizing_strategy: dict = None) -> list:
    """Create a series of limit orders spanning a price range.
    
    Places multiple GTC (Good-Till-Cancel) limit orders at specified price intervals,
    with optional delays between placements. Can create orders as hidden (stealth)
    that will be revealed when specified conditions are met.
    
    Key Features:
    - Automatic price stepping: each order placed at start_price + (order_index * price_difference)
    - Size variation: use order_base_size_range to randomize sizes
    - Exchange compliance: formats prices/sizes to exchange increments
    - Error handling: retries on insufficient funds, aborts on other errors
    - Stealth orders: optionally create hidden orders that reveal conditionally
    
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
        use_stealth: If True, creates hidden orders instead of placing directly (default False).
                     Requires reveal_condition to be specified.
        reveal_condition: Dictionary specifying when to reveal hidden order (required if use_stealth=True).
                         Example: {
                             'type': 'price',
                             'price_threshold': 41000.00,
                             'direction': 'below',  # 'below' or 'above'
                             'hold_duration_seconds': 2,
                             'follow_up_reveal_direction': 'opposite'  # Optional: 'same', 'opposite', 'above', or 'below'
                         }
                         The 'follow_up_reveal_direction' field controls how reveal conditions are set for
                         follow-ups when this order fills:
                         - 'same': Keep the original direction (default)
                         - 'opposite': Flip the direction (below→above, above→below)
                         - 'above'/'below': Explicitly set the direction
        sizing_strategy: Dictionary specifying how to reveal hidden orders (optional, used with use_stealth).
                        Example: {
                            'type': 'fixed',  # or 'volume_proportional'
                            'slice_size': 0.1
                        }
    
    Returns:
        A list of order response dictionaries. Each dict contains:
        - 'success': bool indicating if order was placed/created
        - 'success_response': order data with standard fields:
            - For normal orders:
                - 'client_order_id': our local UUID for tracking
                - 'order_id': exchange-assigned UUID (from API response)
                - 'status': order status (e.g., 'PENDING', 'OPEN', 'FILLED')
                - 'created_at': timestamp
            - For stealth orders (use_stealth=True):
                - 'client_order_id': our local UUID (same as stealth_order_id)
                - 'order_id': None (will be assigned when order reveals on API)
                - 'status': 'HIDDEN' (indicates not yet sent to exchange)
                - 'type': 'STEALTH_ORDER' (indicates special type)
                - 'created_at': timestamp of stealth order creation
                - 'reveal_condition': the condition that triggers reveal
                - 'sizing_strategy': strategy for adaptive reveals
        - 'error_response': error details if failed
    
    Raises:
        Exception: Re-raises unhandled API errors (other than INSUFFICIENT_FUND).
    
    Examples:
        >>> # Place 5 SELL orders with fixed size (normal flow)
        >>> orders = create_limit_order_span(
        ...     product_id='BTC-USDC',
        ...     side='SELL',
        ...     start_price=42000.0,
        ...     order_price_difference=50.0,
        ...     max_order_count=5,
        ...     order_base_size=0.01
        ... )
        >>> for order in orders:
        ...     if order["success"]:
        ...         print(f"Placed order: {order['success_response']['client_order_id']}")
        
        >>> # Place as hidden stealth order (revealed when condition met)
        >>> stealth_orders = create_limit_order_span(
        ...     product_id='BTC-USDC',
        ...     side='SELL',
        ...     order_base_size=0.5,
        ...     start_price=42000.0,
        ...     max_order_count=1,
        ...     use_stealth=True,
        ...     reveal_condition={
        ...         'type': 'price',
        ...         'price_threshold': 41500.0,
        ...         'direction': 'below'
        ...     }
        ... )
        >>> for order in stealth_orders:
        ...     if order["success"]:
        ...         resp = order['success_response']
        ...         print(f"Stealth order {resp['client_order_id']}")
        ...         print(f"  Status: {resp['status']}")  # 'HIDDEN'
        ...         print(f"  Will reveal when: {resp['reveal_condition']}")
        ...         print(f"  order_id (on API): {resp['order_id']}")  # None until revealed
        
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
    """
    results = []
    
    # Handle stealth order creation
    if use_stealth:
        if not reveal_condition:
            raise ValueError("reveal_condition is required when use_stealth=True")
        
        stealth_bridge = get_stealth_order_bridge()
        if not stealth_bridge:
            raise RuntimeError(
                "Stealth order system not initialized. "
                "Ensure dashboard_server has been started and stealth bridge is set."
            )
        
        # Calculate total size for hidden order
        if order_base_size_range:
            # Use midpoint of range for stealth order sizing
            start_size = order_base_size_range.get("start", order_base_size)
            stop_size = order_base_size_range.get("stop", start_size)
            total_size = (start_size + stop_size) / 2 * max_order_count
        else:
            total_size = order_base_size * max_order_count
        
        # Create stealth order wrapper instead of placing directly
        try:
            from datetime import datetime as dt
            
            sizing_strategy_dict = sizing_strategy or {"type": "fixed"}
            stealth_id = stealth_bridge.create_stealth_order(
                product_id=product_id,
                side=side,
                total_size=total_size,
                limit_price=start_price,
                reveal_condition=reveal_condition,
                sizing_strategy=sizing_strategy_dict,
                reason="programmatic_stealth_placement",
                notes=f"Stealth span: {max_order_count} orders with price diff {order_price_difference}"
            )
            
            # Return stealth order with same structure as normal orders
            # client_order_id = stealth_order_id (our local tracking UUID)
            # order_id = None (will be assigned when revealed on exchange)
            return [
                {
                    "success": True,
                    "success_response": {
                        "client_order_id": stealth_id,           # Local UUID for tracking
                        "order_id": None,                       # Assigned when revealed on API
                        "product_id": product_id,
                        "side": side,
                        "size": str(total_size),
                        "price": str(start_price),
                        "status": "HIDDEN",                     # Not yet placed on exchange
                        "type": "STEALTH_ORDER",                # Indicates hidden order
                        "created_at": dt.utcnow().isoformat(),
                        "reveal_condition": reveal_condition,   # Condition for triggering reveal
                        "sizing_strategy": sizing_strategy_dict,# Strategy for reveal slicing
                    }
                }
            ]
        except Exception as e:
            print(f"ERROR: Failed to create stealth order: {e}")
            return [
                {
                    "success": False,
                    "error_response": {
                        "error": "STEALTH_ORDER_CREATION_FAILED",
                        "message": str(e)
                    }
                }
            ]

    # Normal (non-stealth) order placement flow
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
