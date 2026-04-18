"""Order event processor for handling order state transitions.

This module provides business logic for:
- Processing order state changes (filled, cancelled, etc.)
- Enriching order data with computed fields
- Validating order data integrity
- Building order context for logging

Example:
    >>> from business.order_processor import OrderProcessor
    >>> processor = OrderProcessor()
    >>> 
    >>> order = {
    ...     'order_id': 'order-123',
    ...     'product_id': 'BTC-USDC',
    ...     'order_side': 'BUY',
    ...     'status': 'FILLED'
    ... }
    >>> 
    >>> context = processor.build_order_context(order)
    >>> context['product_id']
    'BTC-USDC'
"""

from typing import Optional, Dict, Any
from core.models import Order
from core.enums import OrderStatus, OrderSide
from calculation.formatter import safe_float


class OrderProcessor:
    """Processes order events and enriches order data."""

    @staticmethod
    def build_order_context(order: dict, include_debug: bool = False) -> dict:
        """Build a concise context dict from order data for logging.
        
        Extracts key fields from an order for structured logging without
        dumping the entire order. Useful for audit trails and debugging.
        
        Args:
            order: Order dict with optional fields.
            include_debug: If True, include additional debug fields.
        
        Returns:
            Dict with keys:
            - client_order_id
            - order_id
            - product_id
            - side
            - status
            - price (limit or avg)
            - filled_size
            - number_of_fills
        
        Examples:
            >>> processor = OrderProcessor()
            >>> order = {
            ...     'client_order_id': 'client-123',
            ...     'order_id': 'order-456',
            ...     'product_id': 'BTC-USDC',
            ...     'order_side': 'BUY',
            ...     'status': 'FILLED',
            ...     'limit_price': '42500.00',
            ...     'filled_size': '0.5'
            ... }
            >>> context = processor.build_order_context(order)
            >>> context['order_id']
            'order-456'
            >>> context['product_id']
            'BTC-USDC'
        """
        if not order:
            return {}

        # Try to get price (prefer limit_price, fallback to avg_price)
        price = None
        limit_price = safe_float(order.get("limit_price"), default=None)
        if limit_price and limit_price > 0:
            price = limit_price
        else:
            avg_price = safe_float(order.get("avg_price"), default=None)
            if avg_price and avg_price > 0:
                price = avg_price

        context = {
            "client_order_id": order.get("client_order_id"),
            "order_id": order.get("order_id"),
            "product_id": order.get("product_id"),
            "side": order.get("order_side") or order.get("side"),
            "status": order.get("status"),
            "price": price,
            "filled_size": safe_float(order.get("filled_size"), default=0.0),
            "number_of_fills": order.get("number_of_fills", 0),
        }

        if include_debug:
            context["debug"] = {
                "time_in_force": order.get("time_in_force"),
                "type": order.get("order_type") or order.get("type"),
                "created_at": order.get("created_at"),
                "total_fees": safe_float(order.get("total_fees"), default=0.0),
            }

        return {k: v for k, v in context.items() if v is not None}

    @staticmethod
    def is_filled_order(order: dict) -> bool:
        """Check if an order is fully filled.
        
        An order is considered filled if its status is 'FILLED' and has
        a non-zero filled_size.
        
        Args:
            order: Order dict with 'status' and size fields.
        
        Returns:
            True if order is filled, False otherwise.
        
        Examples:
            >>> processor = OrderProcessor()
            >>> order = {'status': 'FILLED', 'filled_size': '0.5'}
            >>> processor.is_filled_order(order)
            True
            >>> order = {'status': 'OPEN', 'filled_size': '0.5'}
            >>> processor.is_filled_order(order)
            False
        """
        status = order.get("status")
        filled_size = safe_float(order.get("filled_size"), default=0.0)
        return status == "FILLED" and filled_size > 0

    @staticmethod
    def is_cancelled_order(order: dict) -> bool:
        """Check if an order is cancelled.
        
        Args:
            order: Order dict with 'status' field.
        
        Returns:
            True if status is CANCELLED, False otherwise.
        
        Examples:
            >>> processor = OrderProcessor()
            >>> order = {'status': 'CANCELLED'}
            >>> processor.is_cancelled_order(order)
            True
        """
        return order.get("status") == "CANCELLED"

    @staticmethod
    def is_open_order(order: dict) -> bool:
        """Check if an order is open (waiting for execution).
        
        Args:
            order: Order dict with 'status' field.
        
        Returns:
            True if status is OPEN or PENDING, False otherwise.
        
        Examples:
            >>> processor = OrderProcessor()
            >>> order = {'status': 'OPEN'}
            >>> processor.is_open_order(order)
            True
        """
        status = order.get("status")
        return status in ("OPEN", "PENDING")

    @staticmethod
    def order_matches_product(order: dict, product_id: str) -> bool:
        """Check if an order matches a specific product.
        
        Args:
            order: Order dict with 'product_id' field.
            product_id: Product ID to match against.
        
        Returns:
            True if order's product_id matches, False otherwise.
        
        Examples:
            >>> processor = OrderProcessor()
            >>> order = {'product_id': 'BTC-USDC'}
            >>> processor.order_matches_product(order, 'BTC-USDC')
            True
            >>> processor.order_matches_product(order, 'ETH-USDC')
            False
        """
        return order.get("product_id") == product_id

    @staticmethod
    def validate_order_fields(order: dict, required_fields: list = None) -> tuple:
        """Validate that an order has required fields.
        
        Checks if all required fields are present and non-empty in the order.
        
        Args:
            order: Order dict to validate.
            required_fields: List of field names to check (default: common fields).
        
        Returns:
            Tuple of (is_valid: bool, missing_fields: list).
        
        Examples:
            >>> processor = OrderProcessor()
            >>> order = {'order_id': '123', 'product_id': 'BTC-USDC'}
            >>> is_valid, missing = processor.validate_order_fields(
            ...     order, 
            ...     required_fields=['order_id', 'product_id', 'side']
            ... )
            >>> is_valid
            False
            >>> missing
            ['side']
        """
        if required_fields is None:
            required_fields = ["order_id", "product_id", "side", "status"]

        missing_fields = [f for f in required_fields if not order.get(f)]
        is_valid = len(missing_fields) == 0

        return is_valid, missing_fields

    @staticmethod
    def enrich_order_with_calculated_fields(
        order: dict,
        calculator_results: dict,
    ) -> dict:
        """Add computed fields to an order dict.
        
        Merges order with calculated fields (prices, sizes, fees) from
        an OrderCalculator result. Returns a new dict without modifying original.
        
        Args:
            order: Original order dict.
            calculator_results: Dict with keys like 'price', 'size', 'total_fees'.
        
        Returns:
            New dict with order fields plus calculated fields.
        
        Examples:
            >>> processor = OrderProcessor()
            >>> order = {'order_id': '123', 'product_id': 'BTC-USDC'}
            >>> calcs = {'price': 42500.0, 'size': 0.1}
            >>> enriched = processor.enrich_order_with_calculated_fields(order, calcs)
            >>> enriched['price']
            42500.0
            >>> enriched['order_id']
            '123'
        """
        enriched = {**order}
        enriched.update(calculator_results)
        return enriched
