"""Calculation utilities - Resolver functions for orders and products."""

from typing import Optional, Dict, Any

from core.enums import ProductType
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
            if side in ("BUY", "SELL"):
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
