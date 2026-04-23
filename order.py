"""Order placement and management module.

Entry point for order creation with automated reveal conditions.

UNIFIED ARCHITECTURE:
All orders are created through the unified system via StealthOrderManager:
- Orders have a reveal_condition that controls when they appear on the exchange
- Immediate reveals (delay_seconds=0) behave like traditional orders
- Time-delayed reveals hide orders for N seconds
- Price-triggered reveals hide orders until price conditions are met
- The term "stealth" is internal; externally these are just orders with reveal conditions

Key Functions:
- create_limit_order_span(): Creates one or more limit orders with reveal conditions
- get_immediate_reveal_condition(): Returns a reveal condition for immediate placement

All orders use the unified mechanism:
- Orders start HIDDEN with a reveal_condition
- Condition is evaluated continuously
- When triggered, order transitions to PENDING
- On fill, OrderEngine creates automatic follow-up orders

Examples:
    >>> # Immediate reveal (traditional order behavior)
    >>> orders = create_limit_order_span(
    ...     product_id='BTC-USDC',
    ...     side='SELL',
    ...     order_base_size=0.5,
    ...     start_price=42000.0
    ... )
    
    >>> # Price-triggered reveal (hidden until price drops)
    >>> hidden_orders = create_limit_order_span(
    ...     product_id='BTC-USDC',
    ...     side='SELL',
    ...     order_base_size=0.5,
    ...     start_price=42000.0,
    ...     reveal_condition={
    ...         'type': 'price',
    ...         'price_threshold': 41500.0,
    ...         'direction': 'below'
    ...     }
    ... )
    
    >>> # Time-delayed reveal (hidden for 5 minutes)
    >>> delayed_orders = create_limit_order_span(
    ...     product_id='BTC-USDC',
    ...     side='SELL',
    ...     order_base_size=0.5,
    ...     start_price=42000.0,
    ...     reveal_condition={
    ...         'type': 'time_delay',
    ...         'delay_seconds': 300
    ...     }
    ... )
"""
import uuid
from random import uniform as random
from json import dumps
from time import sleep
from configuration import REST_CLIENT, \
    ORDER_DIRECTION, ORDERBOOK, format_based_on_reference, quantize_to_increment
from core.enums import RevealConditionType

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

def get_immediate_reveal_condition() -> dict:
    """Create a reveal condition for immediate order placement (Time Delay 0).
    
    Use this when you want to create a stealth order that is immediately revealed.
    The order will be created as hidden but triggered instantly, resulting in
    behavior nearly equivalent to non-stealth orders but with stealth system tracking.
    
    Returns:
        dict: Reveal condition with type='time_delay', delay_seconds=0, jitter_seconds=0
        
    Example:
        >>> from order import create_limit_order_span, get_immediate_reveal_condition
        >>> orders = create_limit_order_span(
        ...     product_id='BTC-USDC',
        ...     side='SELL',
        ...     order_base_size=0.5,
        ...     start_price=42000.0,
        ...     max_order_count=1,
        ...     reveal_condition=get_immediate_reveal_condition()
        ... )
    """
    return {
        "type": RevealConditionType.TIME_DELAY.value,
        "delay_seconds": 0,
        "jitter_seconds": 0
    }

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
        reveal_condition: dict = None,
        sizing_strategy: dict = None) -> list:
    """Create a series of limit orders spanning a price range.
    
    ARCHITECTURE: ALL orders are created through the order system with automated
    reveal conditions. This provides a unified mechanism for order lifecycle management,
    from creation through reveal and execution.
    
    The reveal_condition controls when/how the order transitions to the exchange:
    - Time-based: Reveal after delay_seconds
    - Price-based: Reveal when price crosses threshold
    - Immediate: Use get_immediate_reveal_condition() for instant reveal (0 second delay)
    
    Key Features:
    - UNIFIED ORDER SYSTEM: All orders use the same reveal mechanism
    - Automatic reveal condition: If reveal_condition not provided, defaults to 60-second delay (to prevent accidental instant reveals)
    - Automatic price stepping: each order placed at start_price + (order_index * price_difference)
    - Size variation: use order_base_size_range to randomize sizes
    - Adaptive sizing: supports volume-proportional or fixed-size reveals
    
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
        reveal_condition: Dictionary specifying when/how order transitions to exchange.
                         If not provided, defaults to immediate reveal.
                         Example for price-based reveal: {
                             'type': 'price',
                             'price_threshold': 41000.00,
                             'direction': 'below',  # 'below' or 'above'
                             'hold_duration_seconds': 2,
                         }
                         Example for time-based reveal: {
                             'type': 'time_delay',
                             'delay_seconds': 300,  # 5 minutes
                             'jitter_seconds': 60    # ±60 seconds random variation
                         }
        sizing_strategy: Strategy for adaptive reveals (default: fixed-size).
                        Example: {'type': 'volume_proportional', 'min_reveal': 0.1}
                         - 'same': Keep the original direction (default)
                         - 'opposite': Flip the direction (below→above, above→below)
                         - 'above'/'below': Explicitly set the direction
        sizing_strategy: Strategy for adaptive reveals (default: fixed-size).
                        Example: {'type': 'volume_proportional', 'min_reveal': 0.1}
    
    Returns:
        A list of order response dictionaries. Each dict contains:
        - 'success': bool indicating if order was created
        - 'success_response': order data with standard fields:
            - 'client_order_id': our local UUID for tracking
            - 'order_id': None (will be assigned when order reveals on exchange)
            - 'status': 'HIDDEN' (indicates not yet sent to exchange, pending reveal)
            - 'type': 'ORDER' (unified order type)
            - 'created_at': timestamp of order creation
            - 'reveal_condition': the condition that controls when/how order appears on exchange
            - 'sizing_strategy': strategy for adaptive reveals
        - 'error_response': error details if failed
    
    Raises:
        RuntimeError: If order system not initialized
        Exception: Re-raises unhandled API errors
    
    Examples:
        >>> # Place 5 SELL orders (will be immediately revealed by default)
        >>> orders = create_limit_order_span(
        ...     product_id='BTC-USDC',
        ...     side='SELL',
        ...     start_price=42000.0,
        ...     order_price_difference=50.0,
        ...     max_order_count=5,
        ...     order_base_size=0.01
        ... )
        
        >>> # Place with custom price-based reveal condition
        >>> orders = create_limit_order_span(
        ...     product_id='BTC-USDC',
        ...     side='SELL',
        ...     order_base_size=0.5,
        ...     start_price=42000.0,
        ...     max_order_count=1,
        ...     reveal_condition={
        ...         'type': 'price',
        ...         'price_threshold': 41500.0,
        ...         'direction': 'below'
        ...     }
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
    """
    # Auto-generate reveal condition if not provided
    # Default to 60-second delay instead of immediate (0s) to prevent accidental instant reveals
    if not reveal_condition:
        reveal_condition = {
            "type": RevealConditionType.TIME_DELAY.value,
            "delay_seconds": 60,
            "jitter_seconds": 0
        }
    
    order_bridge = get_stealth_order_bridge()
    if not order_bridge:
        raise RuntimeError(
            "Order system not initialized. "
            "Ensure dashboard_server has been started."
        )
    
    # Calculate total size for order
    if order_base_size_range:
        # Use midpoint of range for order sizing
        start_size = order_base_size_range.get("start", order_base_size)
        stop_size = order_base_size_range.get("stop", start_size)
        total_size = (start_size + stop_size) / 2 * max_order_count
    else:
        total_size = order_base_size * max_order_count
    
    try:
        from datetime import datetime as dt
        
        sizing_strategy_dict = sizing_strategy or {"type": "fixed"}
        order_id = order_bridge.create_stealth_order(
            product_id=product_id,
            side=side,
            total_size=total_size,
            limit_price=start_price,
            reveal_condition=reveal_condition,
            sizing_strategy=sizing_strategy_dict,
            reason="programmatic_order_placement",
            notes=f"Order span: {max_order_count} orders with price diff {order_price_difference}"
        )
        
        # Return order with standard structure
        # client_order_id = order_id (our local tracking UUID)
        # order_id = None (will be assigned when revealed on exchange)
        return [
            {
                "success": True,
                "success_response": {
                    "client_order_id": order_id,              # Local UUID for tracking
                    "order_id": None,                         # Assigned when revealed on exchange
                    "product_id": product_id,
                    "side": side,
                    "size": str(total_size),
                    "price": str(start_price),
                    "status": "HIDDEN",                       # Pending reveal
                    "type": "ORDER",                          # Standard order type
                    "created_at": dt.utcnow().isoformat(),
                    "reveal_condition": reveal_condition,     # Condition controlling reveal
                    "sizing_strategy": sizing_strategy_dict,  # Strategy for adaptive reveals
                }
            }
        ]
    except Exception as e:
        print(f"ERROR: Failed to create order: {e}")
        return [
            {
                "success": False,
                "error_response": {
                    "error": "ORDER_CREATION_FAILED",
                    "message": str(e)
                }
            }
        ]
