"""Processor bridge providing order processing utilities.

Wraps OrderProcessor to provide a clean interface for order context building,
validation, status checking, and enrichment.

Example:
    >>> bridge = ProcessorBridge()
    >>> order = {'order_id': '123', 'product_id': 'BTC-USDC', 'status': 'FILLED'}
    >>> context = bridge.build_order_context(order)
    >>> context['order_id']
    '123'
"""

from business.order_processor import OrderProcessor


class ProcessorBridge:
    """Adapter bridge wrapping OrderProcessor for OrderEngine.
    
    Provides order processing utilities that OrderEngine uses internally.
    
    Attributes:
        processor: OrderProcessor instance for validation and enrichment.
    """

    def __init__(self):
        """Initialize processor bridge."""
        self.processor = OrderProcessor()

    def build_order_context(self, order: dict, include_debug: bool = False) -> dict:
        """Build concise log context from order.
        
        Args:
            order: Order dict to extract context from.
            include_debug: Whether to include debug fields.
        
        Returns:
            Dict with order_id, product_id, side, status, price, filled_size.
        
        Example:
            >>> bridge = ProcessorBridge()
            >>> ctx = bridge.build_order_context(
            ...     {'order_id': '123', 'product_id': 'BTC-USDC', 'status': 'FILLED'}
            ... )
            >>> ctx['product_id']
            'BTC-USDC'
        """
        context = self.processor.build_order_context(order)
        if include_debug:
            # Include all fields for debug logging
            context.update({
                'type': order.get('type'),
                'time_in_force': order.get('time_in_force'),
                'created_at': order.get('created_at'),
                'updated_at': order.get('updated_at'),
            })
        return context

    def is_filled_order(self, order: dict) -> bool:
        """Check if order is fully filled.
        
        Args:
            order: Order dict to check.
        
        Returns:
            True if status=FILLED and filled_size > 0.
        
        Example:
            >>> bridge = ProcessorBridge()
            >>> is_filled = bridge.is_filled_order(
            ...     {'status': 'FILLED', 'filled_size': '1.0'}
            ... )
            >>> is_filled
            True
        """
        return self.processor.is_filled_order(order)

    def is_cancelled_order(self, order: dict) -> bool:
        """Check if order is cancelled.
        
        Args:
            order: Order dict to check.
        
        Returns:
            True if status is CANCELLED or EXPIRED_CANCELLED.
        
        Example:
            >>> bridge = ProcessorBridge()
            >>> is_cancelled = bridge.is_cancelled_order(
            ...     {'status': 'CANCELLED'}
            ... )
            >>> is_cancelled
            True
        """
        return self.processor.is_cancelled_order(order)

    def is_open_order(self, order: dict) -> bool:
        """Check if order is open or pending.
        
        Args:
            order: Order dict to check.
        
        Returns:
            True if status is OPEN or PENDING.
        
        Example:
            >>> bridge = ProcessorBridge()
            >>> is_open = bridge.is_open_order(
            ...     {'status': 'OPEN'}
            ... )
            >>> is_open
            True
        """
        return self.processor.is_open_order(order)

    def order_matches_product(self, order: dict, product_id: str) -> bool:
        """Check if order belongs to product.
        
        Args:
            order: Order dict to check.
            product_id: Product ID to match.
        
        Returns:
            True if order's product_id matches.
        
        Example:
            >>> bridge = ProcessorBridge()
            >>> matches = bridge.order_matches_product(
            ...     {'product_id': 'BTC-USDC'},
            ...     'BTC-USDC'
            ... )
            >>> matches
            True
        """
        return self.processor.order_matches_product(order, product_id)

    def validate_order_fields(
        self,
        order: dict,
        required_fields: list = None,
    ) -> tuple:
        """Validate order has required fields.
        
        Args:
            order: Order dict to validate.
            required_fields: List of required field names.
                Default: ['order_id', 'product_id', 'side', 'status'].
        
        Returns:
            Tuple (is_valid: bool, missing_fields: list).
        
        Example:
            >>> bridge = ProcessorBridge()
            >>> is_valid, missing = bridge.validate_order_fields(
            ...     {'order_id': '123', 'product_id': 'BTC-USDC'}
            ... )
            >>> is_valid
            False
            >>> 'side' in missing
            True
        """
        return self.processor.validate_order_fields(order, required_fields)

    def enrich_order_with_calculated_fields(
        self,
        order: dict,
        calculated_fields: dict,
    ) -> dict:
        """Merge calculated fields into order dict.
        
        Args:
            order: Original order dict.
            calculated_fields: Dict of calculated values to merge.
        
        Returns:
            Order dict with calculated fields merged in.
        
        Example:
            >>> bridge = ProcessorBridge()
            >>> enriched = bridge.enrich_order_with_calculated_fields(
            ...     {'order_id': '123'},
            ...     {'calculated_fees': '0.5'}
            ... )
            >>> enriched['calculated_fees']
            '0.5'
        """
        return self.processor.enrich_order_with_calculated_fields(order, calculated_fields)
