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
- create_stealth_order_span(): Creates a declarative, resumable order span
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
import warnings

from configuration import DEFAULT_MAX_ORDER_REPLACEMENT
from core.enums import (
    FollowUpRevealDirection,
    OrderResponseType,
    RevealConditionType,
    StealthOrderStatus,
    StealthSpanCreationMode,
    StealthSpanOrderResultStatus,
    StealthSpanSizeDistribution,
    TargetMovementType,
)

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


def create_stealth_order_span(span_request: dict) -> dict:
    """Create one declarative span through the canonical bridge coordinator.

    ``span_request`` must include a UUID ``span_id``. Retrying the same request
    is resumable: deterministic per-rung ``client_order_id`` values allow the
    bridge to return matching rungs as existing and create only missing rungs.
    The returned aggregate status is ``success``, ``partial``, or ``error``;
    span creation is deliberately not represented as an atomic transaction.
    """

    order_bridge = get_stealth_order_bridge()
    if not order_bridge:
        raise RuntimeError(
            "Order system not initialized. "
            "Ensure dashboard_server has been started."
        )
    return order_bridge.create_stealth_order_span(span_request)

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
        sizing_strategy: dict = None,
        reveal_pricing_policy: str = None,
        camouflage_round_numbers: bool = False,
        camouflage_mode: str = "passive") -> list:
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
    - Automatic price stepping: SELL prices step up; BUY prices step down
    - Deterministic size allocation: legacy size ranges use their midpoint
    - Adaptive sizing: supports volume-proportional or fixed-size reveals
    
    Args:
        order_base_size_range: Dictionary with 'start' and optional 'stop'. The
                               compatibility adapter uses the range midpoint for
                               every order. If None, uses order_base_size.
                               Example: {'start': 1.0, 'stop': 5.0}
        delay_in_secs: Deprecated and ignored. Span creation is coordinated as
                       one resumable operation.
        product_id: The product ID (e.g., "BTC-USDC", "MON-USDC").
        side: Order side ("BUY" or "SELL").
        max_order_count: Number of orders to create (minimum 1, default 1).
        order_base_size: Base size for each order if range not specified (default 1).
        order_price_difference: Price difference between consecutive orders (default 0.00001).
        start_price: Starting price for the first order (default 0.00992).
        post_only: Deprecated. Maker/taker behavior is derived from
                   reveal_pricing_policy.
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
        reveal_pricing_policy: Optional reveal pricing policy override.
                               Supported values: configured_limit,
                               top_of_book, midpoint.
    
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
        
        >>> # Place 3 BUY orders using the midpoint of a legacy size range
        >>> orders = create_limit_order_span(
        ...     product_id='ETH-USDC',
        ...     side='BUY',
        ...     start_price=2000.0,
        ...     order_base_size_range={'start': 0.5, 'stop': 2.0},
        ...     order_price_difference=10.0,
        ...     max_order_count=3
        ... )
    """
    # Default to a delayed reveal to prevent accidental immediate placement.
    if not reveal_condition:
        reveal_condition = {
            "type": RevealConditionType.TIME_DELAY.value,
            "delay_seconds": 60,
            "jitter_seconds": 0
        }

    # Optional round-number camouflage. OFF by default to preserve the
    # "generator follows instruction" property — when on, the supplied
    # ``start_price`` is nudged off-magnet by a deterministic small
    # number of ticks. See calculation/price_camouflage.py for the full
    # contract; honest scope notes there too.
    effective_start_price = start_price
    if camouflage_round_numbers:
        try:
            from calculation.price_camouflage import camouflage_round_price
            from configuration import get_product_metadata
            product_meta = get_product_metadata(product_id)
            price_increment = product_meta.get("price_increment")
            if price_increment:
                effective_start_price = camouflage_round_price(
                    start_price,
                    side=side,
                    price_increment=str(price_increment),
                    mode=camouflage_mode,
                    # No seed: deterministic from inputs. Pass an explicit
                    # seed kwarg via the stealth-order path if you want
                    # per-order stability across reveals.
                )
        except Exception:
            # Camouflage is decoration; never fail order creation on it.
            effective_start_price = start_price
    
    # Preserve the legacy midpoint rule for a requested size range. The new
    # canonical API itself is deterministic and does not define random sizing.
    if order_base_size_range:
        start_size = order_base_size_range.get("start", order_base_size)
        stop_size = order_base_size_range.get("stop", start_size)
        per_order_size = (start_size + stop_size) / 2
    else:
        per_order_size = order_base_size

    if delay_in_secs:
        warnings.warn(
            "delay_in_secs is deprecated and ignored; span creation is a single "
            "server-coordinated operation",
            DeprecationWarning,
            stacklevel=2,
        )
    if post_only:
        warnings.warn(
            "post_only is deprecated; use reveal_pricing_policy to select maker "
            "or configured-limit reveal behavior",
            DeprecationWarning,
            stacklevel=2,
        )

    span_request = {
        "span_id": str(uuid.uuid4()),
        "product_id": product_id,
        "side": side,
        "order_count": max_order_count,
        "start_price": effective_start_price,
        "price_step": order_price_difference,
        "total_size": per_order_size * max_order_count,
        "size_distribution": StealthSpanSizeDistribution.EQUAL.value,
        "creation_mode": StealthSpanCreationMode.INDEPENDENT_PARENTS.value,
        "reveal_condition": reveal_condition,
        "reveal_pricing_policy": reveal_pricing_policy,
        "sizing_strategy": sizing_strategy or {"type": "fixed"},
        "follow_up_reveal_direction": FollowUpRevealDirection.OPPOSITE.value,
        "max_order_replacements": DEFAULT_MAX_ORDER_REPLACEMENT,
        "target_movement": 0.0,
        "target_movement_type": TargetMovementType.PERCENTAGE.value,
        "allow_partial_fills": False,
        "anchor_repricing_policy": {"enabled": False},
        "enable_hotpoint_replication": False,
        "notes": (
            "Legacy create_limit_order_span compatibility request; "
            f"price diff {order_price_difference}"
        ),
    }

    # Preserve the public RuntimeError contract before entering the legacy
    # response-shaping exception boundary used for actual creation failures.
    if get_stealth_order_bridge() is None:
        raise RuntimeError(
            "Order system not initialized. "
            "Ensure dashboard_server has been started."
        )

    try:
        from datetime import datetime as dt
        result = create_stealth_order_span(span_request)
        responses = []
        for order_result in result.get("orders", []):
            status = order_result.get("status")
            if status in {
                StealthSpanOrderResultStatus.CREATED.value,
                StealthSpanOrderResultStatus.EXISTING.value,
            }:
                responses.append({
                    "success": True,
                    "success_response": {
                        "client_order_id": order_result["client_order_id"],
                        "order_id": None,
                        "product_id": order_result["product_id"],
                        "side": order_result["side"],
                        "size": str(order_result["size"]),
                        "price": str(order_result["price"]),
                        "status": StealthOrderStatus.HIDDEN.value,
                        "type": OrderResponseType.ORDER.value,
                        "created_at": dt.utcnow().isoformat(),
                        "reveal_condition": order_result["reveal_condition"],
                        "sizing_strategy": sizing_strategy or {"type": "fixed"},
                    },
                })
            else:
                responses.append({
                    "success": False,
                    "error_response": {
                        "error": "ORDER_CREATION_FAILED",
                        "message": order_result.get("error") or status or "not attempted",
                    },
                })
        if responses:
            return responses
        raise RuntimeError(result.get("error") or "span creation returned no order results")
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
