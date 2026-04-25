"""Calculation utilities - Resolver functions for orders and products."""

from typing import Optional, Dict, Any

from core.enums import ProductType, OrderSide
from core.models import Order, Product
from calculation.formatter import safe_float


def normalize_product_type(order: Dict[str, Any], products: Optional[Dict[str, Product]] = None) -> str:
    """Normalize product type from an order payload and configured products.
    
    Determines if an order is for SPOT or FUTURE trading by checking multiple
    sources: order payload, product metadata, and product ID suffix patterns.
    Uses fallback logic to handle incomplete order data.
    
    Args:
        order: Order dictionary with optional 'product_type', 'product_id' fields
        products: Optional product metadata dict keyed by product_id
    
    Returns:
        'SPOT' or 'FUTURE' - the normalized product type
    
    Examples:
        >>> normalize_product_type({'product_type': 'SPOT'})
        'SPOT'
        >>> normalize_product_type({'product_id': 'BIP-20DEC30-CDE'})
        'FUTURE'
    """
    product_type = str(order.get("product_type") or "").upper()
    if product_type in {ProductType.SPOT.value, ProductType.FUTURE.value}:
        return product_type
    
    product_id = order.get("product_id")
    if products and product_id in products:
        product = products[product_id]
        if isinstance(product, Product):
            return product.product_type.value
        configured_product_type = str(product.get("product_type") or "").upper()
        if configured_product_type in {ProductType.SPOT.value, ProductType.FUTURE.value}:
            return configured_product_type
    
    if product_id and product_id.endswith("-CDE"):
        return "FUTURE"
    return "SPOT"


def resolve_order_size(order: Dict[str, Any]) -> float:
    """Resolve order size from the best available quantity field.
    
    Attempts to extract order size from multiple possible fields in priority order.
    Different API responses and order states use different field names.
    
    Args:
        order: Order dictionary that may contain size in various fields
    
    Returns:
        The order size as a float, or 0.0 if not found
    
    Examples:
        >>> resolve_order_size({'leaves_quantity': 10.5})
        10.5
        >>> resolve_order_size({'filled_size': '5.0'})
        5.0
    """
    # Priority order of field checking
    field_names = [
        "leaves_quantity",
        "cumulative_quantity",
        "filled_size",
        "base_size",
        "size"
    ]
    
    for field in field_names:
        value = safe_float(order.get(field), default=0.0)
        if value > 0:
            return value
    
    return 0.0


def resolve_order_side(order: Dict[str, Any]) -> Optional[str]:
    """Resolve order side (BUY/SELL) from the best available field.
    
    Attempts to extract order side from multiple possible fields.
    Different API responses and order states use different field names.
    
    Args:
        order: Order dictionary that may contain side in various fields
    
    Returns:
        The order side as a string ('BUY' or 'SELL'), or None if not found
    
    Examples:
        >>> resolve_order_side({'side': 'BUY'})
        'BUY'
        >>> resolve_order_side({'order_side': 'SELL'})
        'SELL'
        >>> resolve_order_side({})
        None
    """
    # Priority order of field checking
    field_names = ["order_side", "side"]
    
    for field in field_names:
        value = order.get(field)
        if value:
            side = str(value).upper().strip()
            if side in (OrderSide.BUY.value, OrderSide.SELL.value):
                return side
    
    return None


def resolve_profit_move_pct(
    order: Dict[str, Any],
    profits: Dict[str, Any],
    products: Optional[Dict[str, Any]] = None
) -> float:
    """Resolve configured profit target for an order.
    
    Determines the profit/fee movement percentage for an order by checking
    product-specific and product-type-level configurations. Checks product-specific
    config first, then falls back to product type (SPOT/FUTURE) config.
    
    Args:
        order: Order dict with 'product_id' and 'order_side' fields.
        profits: Profit config dict with structure:
                 {product_type: {side: percentage}, product_id: {side: percentage}}
        products: Optional product metadata dict keyed by product_id (default None).
    
    Returns:
        The profit movement percentage as float (e.g., 0.004 for 0.4%), or 0.0 if not found.
    
    Examples:
        >>> profits = {'SPOT': {'BUY': 0.004, 'SELL': 0.004}}
        >>> resolve_profit_move_pct({'product_id': 'BTC-USDC', 'order_side': 'BUY'}, profits, {})
        0.004
        >>> profits = {'FUTURE': {'SELL': 0.002}}
        >>> resolve_profit_move_pct({'product_id': 'BIP-20DEC30-CDE', 'order_side': 'SELL'}, profits, {})
        0.002
    """
    product_id = order.get("product_id")
    product_type = normalize_product_type(order, products=products)
    order_side = order.get("order_side")
    
    # Check product-specific config first
    product_profit = profits.get(product_id)
    if isinstance(product_profit, dict) and order_side in product_profit:
        return float(product_profit[order_side])
    
    # Fall back to product type config
    type_profit = profits.get(product_type, {})
    if order_side in type_profit:
        return float(type_profit[order_side])
    
    # Default if not found
    return 0.0


def resolve_cumulative_filled(order: Dict[str, Any]) -> float:
    """Resolve how much of an order has been cumulatively filled so far.

    Uses ``cumulative_quantity`` as the primary source (Coinbase WebSocket field
    meaning "amount filled in base currency").  Falls back to deriving the value
    from ``completion_percentage`` × ``base_size`` when the primary field is
    absent or zero, which covers edge-case payloads that omit the field.

    This function is intentionally separate from ``resolve_order_size`` because
    that function prioritises ``leaves_quantity`` (remaining), which is incorrect
    for computing partial-fill progress watermarks.

    Args:
        order: Order dictionary from a Coinbase WebSocket OPEN or UPDATE event.

    Returns:
        Cumulative filled quantity as a float, or 0.0 if not determinable.

    Examples:
        >>> resolve_cumulative_filled({'cumulative_quantity': '1.5'})
        1.5
        >>> resolve_cumulative_filled({'completion_percentage': '50', 'base_size': '3.0'})
        1.5
        >>> resolve_cumulative_filled({})
        0.0
    """
    cumulative = safe_float(order.get("cumulative_quantity"), default=0.0)
    if cumulative > 0.0:
        return cumulative

    # Fallback: derive from completion_percentage × base_size
    completion_pct = safe_float(order.get("completion_percentage"), default=0.0)
    base_size = safe_float(order.get("base_size") or order.get("size"), default=0.0)
    if completion_pct > 0.0 and base_size > 0.0:
        return (completion_pct / 100.0) * base_size

    return 0.0


def resolve_remaining_size(order: Dict[str, Any]) -> float:
    """Resolve how much of an order is still unfilled (remaining quantity).

    Uses ``leaves_quantity`` as the primary source, with ``base_size`` as a
    fallback for order snapshots that may not carry the field.

    Args:
        order: Order dictionary from a Coinbase WebSocket event.

    Returns:
        Remaining unfilled quantity as a float, or 0.0 if not determinable.

    Examples:
        >>> resolve_remaining_size({'leaves_quantity': '0.5'})
        0.5
        >>> resolve_remaining_size({'base_size': '2.0'})
        2.0
        >>> resolve_remaining_size({})
        0.0
    """
    leaves = safe_float(order.get("leaves_quantity"), default=0.0)
    if leaves > 0.0:
        return leaves

    return safe_float(order.get("base_size") or order.get("size"), default=0.0)


def resolve_partial_fill_delta(
    current_cumulative: float,
    last_watermark: float,
) -> float:
    """Compute the new fill quantity since the last recorded watermark.

    Enforces monotonicity: returns 0.0 if ``current_cumulative`` has not
    advanced beyond ``last_watermark``, guarding against out-of-order or
    duplicate WebSocket events.

    Args:
        current_cumulative: Latest ``cumulative_quantity`` from the exchange.
        last_watermark:     The last ``cumulative_quantity`` that was acted on,
                            stored in ``_partial_fill_state`` / DB.

    Returns:
        The non-negative delta (new fill since last watermark), or 0.0 if no
        advancement.

    Examples:
        >>> resolve_partial_fill_delta(1.5, 1.0)
        0.5
        >>> resolve_partial_fill_delta(1.0, 1.0)
        0.0
        >>> resolve_partial_fill_delta(0.9, 1.0)   # out-of-order / duplicate
        0.0
    """
    delta = current_cumulative - last_watermark
    return delta if delta > 0.0 else 0.0


def extract_order_price(order: Dict[str, Any]) -> Optional[float]:
    """Extract the price from an order, preferring limit_price over avg_price.
    
    Args:
        order: Order dict with optional 'limit_price' and 'avg_price' fields
    
    Returns:
        The price as a float, or None if not found
    
    Examples:
        >>> extract_order_price({'limit_price': '100.50'})
        100.5
        >>> extract_order_price({'avg_price': '100.00'})
        100.0
    """
    limit_price = safe_float(order.get("limit_price"), default=None)
    if limit_price and limit_price > 0:
        return limit_price
    
    avg_price = safe_float(order.get("avg_price"), default=None)
    if avg_price and avg_price > 0:
        return avg_price
    
    return None
