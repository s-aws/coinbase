"""Bridge between OrderEngine and OrderCalculator.

Provides calculation utilities that OrderEngine uses internally.
Wraps OrderCalculator to provide the expected interface.

Example:
    >>> bridge = CalculatorBridge()
    >>> parent_order = {'order_side': 'BUY', 'avg_price': '100.00'}
    >>> follow_up_price = bridge.calculate_follow_up_price(
    ...     parent_order, 'SELL', 0.01
    ... )
    >>> follow_up_price
    101.0
"""

from business.order_calculator import OrderCalculator
from calculation.formatter import safe_float, format_based_on_reference


class CalculatorBridge:
    """Wraps OrderCalculator to provide OrderEngine calculation interface.
    
    Attributes:
        calculator: OrderCalculator instance for computations.
    """

    def __init__(self):
        """Initialize calculator bridge."""
        self.calculator = OrderCalculator()

    def calculate_follow_up_price(
        self,
        parent_order: dict,
        follow_up_side: str,
        profit_pct: float,
    ) -> float:
        """Calculate follow-up order price with profit target.
        
        Args:
            parent_order: Parent order dict with 'order_side' and 'avg_price'.
            follow_up_side: Side for follow-up order ('BUY' or 'SELL').
            profit_pct: Profit percentage (e.g., 0.01 for 1%).
        
        Returns:
            Float price for follow-up order.
        
        Example:
            >>> bridge = CalculatorBridge()
            >>> price = bridge.calculate_follow_up_price(
            ...     {'order_side': 'BUY', 'avg_price': '100.00'},
            ...     'SELL',
            ...     0.01
            ... )
            >>> price
            101.0
        """
        result = self.calculator.calculate_follow_up_price(
            parent_order,
            follow_up_side,
            profit_pct,
        )
        return safe_float(result.get('price', 0.0))

    def calculate_follow_up_size(self, order: dict) -> float:
        """Extract filled size from order.
        
        Args:
            order: Order dict to extract size from.
        
        Returns:
            Float size of order fill.
        
        Example:
            >>> bridge = CalculatorBridge()
            >>> size = bridge.calculate_follow_up_size(
            ...     {'filled_size': '0.5'}
            ... )
            >>> size
            0.5
        """
        result = self.calculator.calculate_follow_up_size(order)
        return safe_float(result.get('size', 0.0))

    def calculate_position_change(
        self,
        order: dict,
        current_position: dict = None,
    ) -> dict:
        """Calculate position change from order fill.
        
        Args:
            order: Filled order dict.
            current_position: Current position state (optional).
        
        Returns:
            Dict with 'net_size' and 'entry_vwap' keys.
        
        Example:
            >>> bridge = CalculatorBridge()
            >>> change = bridge.calculate_position_change(
            ...     {'order_side': 'BUY', 'filled_size': '1.0', 'avg_price': '100.00'},
            ...     {'net_size': '0.0', 'entry_vwap': '0.0'}
            ... )
            >>> change['net_size']
            1.0
        """
        return self.calculator.calculate_position_change(order, current_position)

    def calculate_fees(self, order: dict, fee_rate: float = 0.0) -> dict:
        """Calculate total fees from order.
        
        Args:
            order: Order dict with fill details.
            fee_rate: Commission rate (e.g., 0.001 for 0.1%).
        
        Returns:
            Dict with 'commission' and 'mandatory_fees' keys.
        
        Example:
            >>> bridge = CalculatorBridge()
            >>> fees = bridge.calculate_fees(
            ...     {'filled_size': '1.0', 'avg_price': '100.00'}
            ... )
        """
        return self.calculator.calculate_fees(order, fee_rate)

    def should_create_follow_up(self, order: dict) -> bool:
        """Check if order should trigger follow-up creation.
        
        Args:
            order: Order dict to check.
        
        Returns:
            True if order is FILLED with filled_size > 0.
        
        Example:
            >>> bridge = CalculatorBridge()
            >>> should_follow = bridge.should_create_follow_up(
            ...     {'status': 'FILLED', 'filled_size': '1.0'}
            ... )
            >>> should_follow
            True
        """
        return self.calculator.should_create_follow_up(order)
