"""Calculation module - Order and position calculation functions."""

from calculation.formatter import (
    safe_float,
    format_based_on_reference,
    quantize_to_increment,
)
from calculation.resolver import (
    normalize_product_type,
    resolve_order_size,
    resolve_profit_move_pct,
    extract_order_price,
)

__all__ = [
    # Formatter
    'safe_float',
    'format_based_on_reference',
    'quantize_to_increment',
    # Resolver
    'normalize_product_type',
    'resolve_order_size',
    'resolve_profit_move_pct',
    'extract_order_price',
]
