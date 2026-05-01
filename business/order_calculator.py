"""Order calculator for computing follow-up orders and position metrics.

This module provides business logic for:
- Calculating follow-up order prices based on fills
- Computing position-based profit targets
- Calculating order metrics and fees
- Applying position updates from trades

Example:
    >>> from business.order_calculator import OrderCalculator
    >>> calc = OrderCalculator()
    >>> 
    >>> # Calculate follow-up order for a filled buy order
    >>> parent_order = {
    ...     'product_id': 'BTC-USDC',
    ...     'order_side': 'BUY',
    ...     'avg_price': '42000.00',
    ...     'filled_size': '0.1'
    ... }
    >>> products = {'BTC-USDC': {'base_increment': '0.00000001', 'quote_increment': '0.01'}}
    >>> 
    >>> follow_up = calc.calculate_follow_up_price(
    ...     parent_order=parent_order,
    ...     side='SELL',
    ...     profit_target_pct=0.004,
    ...     products=products
    ... )
    >>> follow_up['price']
    42168.0
"""

from decimal import Decimal, ROUND_HALF_UP
from core.models import Order, Position
from core.enums import OrderSide, ProductType, OrderStatus
from calculation.formatter import safe_float, format_based_on_reference, quantize_to_increment
from calculation.resolver import normalize_product_type


class OrderCalculator:
    """Calculates follow-up orders and position metrics."""

    @staticmethod
    def calculate_follow_up_price(
        parent_order: dict,
        side: str,
        profit_target_pct: float,
        products: dict = None,
    ) -> dict:
        """Calculate the price for a follow-up order based on parent order fill price.
        
        Computes the price that satisfies the profit target percentage. For a BUY order,
        this calculates the SELL price that achieves the target profit. For a SELL order,
        this calculates the BUY price.
        
        Args:
            parent_order: Order dict with 'avg_price', 'order_side' fields.
            side: The follow-up order side ('BUY' or 'SELL').
            profit_target_pct: Target profit as decimal (e.g., 0.004 for 0.4%).
            products: Product metadata dict keyed by product_id.
        
        Returns:
            Dict with:
            - 'price': computed price as float
            - 'product_id': product being traded
            - 'side': follow-up side
        
        Examples:
            >>> calc = OrderCalculator()
            >>> parent = {'order_side': 'BUY', 'avg_price': '100.00', 'product_id': 'BTC-USD'}
            >>> result = calc.calculate_follow_up_price(parent, 'SELL', 0.01)
            >>> result['price']  # 100 * 1.01 = 101.0
            101.0
            >>> parent = {'order_side': 'SELL', 'avg_price': '100.00', 'product_id': 'BTC-USD'}
            >>> result = calc.calculate_follow_up_price(parent, 'BUY', 0.01)
            >>> result['price']  # 100 / 1.01 ≈ 99.01
            99.01
        """
        parent_side = parent_order.get("order_side")
        fill_price = safe_float(parent_order.get("avg_price"), default=0.0)
        product_id = parent_order.get("product_id")

        if fill_price <= 0:
            return {"price": 0.0, "product_id": product_id, "side": side}

        # For BUY orders, follow-up is SELL at higher price
        # For SELL orders, follow-up is BUY at lower price
        if parent_side == OrderSide.BUY.value:
            # Sell at fill_price * (1 + profit_target_pct)
            target_price = fill_price * (1 + profit_target_pct)
        else:
            # Buy at fill_price / (1 + profit_target_pct)
            target_price = fill_price / (1 + profit_target_pct)

        return {
            "price": target_price,
            "product_id": product_id,
            "side": side,
        }

    @staticmethod
    def calculate_follow_up_size(
        parent_order: dict,
        size_field: str = "filled_size",
    ) -> dict:
        """Extract or calculate the size for a follow-up order.
        
        Determines the size for a follow-up order from the filled quantity of the
        parent order. Attempts multiple field names to handle different order states.
        
        Args:
            parent_order: Order dict with quantity fields.
            size_field: Primary field to use for size (default: 'filled_size').
        
        Returns:
            Dict with:
            - 'size': order size as float
            - 'source_field': which field was used
        
        Examples:
            >>> calc = OrderCalculator()
            >>> parent = {'filled_size': '0.5'}
            >>> result = calc.calculate_follow_up_size(parent)
            >>> result['size']
            0.5
            >>> parent = {'cumulative_quantity': '1.0'}
            >>> result = calc.calculate_follow_up_size(parent)
            >>> result['size']
            1.0
        """
        fields_to_check = [size_field, "filled_size", "cumulative_quantity", "base_size"]
        
        for field in fields_to_check:
            value = safe_float(parent_order.get(field), default=0.0)
            if value > 0:
                return {"size": value, "source_field": field}
        
        return {"size": 0.0, "source_field": None}

    @staticmethod
    def calculate_position_change(
        order: dict,
        position: dict = None,
    ) -> dict:
        """Calculate how an order affects a futures position.
        
        Determines the impact of a fill on position size and value. For a position,
        long buys increase net_size, shorts sell reduce net_size.
        
        Args:
            order: Order dict with 'order_side', 'filled_size', 'avg_price'.
            position: Current position dict with 'net_size', 'entry_vwap'.
        
        Returns:
            Dict with:
            - 'new_size': new position size after order
            - 'size_change': amount added/removed
            - 'entry_vwap': new entry VWAP (weighted average price)
            - 'unrealized_pnl': unrealized profit/loss
        
        Examples:
            >>> calc = OrderCalculator()
            >>> order = {'order_side': 'BUY', 'filled_size': '0.5', 'avg_price': '100.0'}
            >>> position = {'net_size': '0.0', 'entry_vwap': '0'}
            >>> result = calc.calculate_position_change(order, position)
            >>> result['new_size']
            0.5
            >>> result['entry_vwap']
            100.0
        """
        if not position:
            position = {"net_size": "0.0", "entry_vwap": "0.0"}

        side = order.get("order_side")
        fill_size = safe_float(order.get("filled_size"), default=0.0)
        fill_price = safe_float(order.get("avg_price"), default=0.0)
        
        current_size = safe_float(position.get("net_size"), default=0.0)
        current_vwap = safe_float(position.get("entry_vwap"), default=0.0)

        # Calculate new VWAP (volume-weighted average price)
        if side == OrderSide.BUY.value:
            size_change = fill_size
            if current_size == 0:
                new_vwap = fill_price
            else:
                total_value = (current_size * current_vwap) + (fill_size * fill_price)
                new_size = current_size + fill_size
                new_vwap = total_value / new_size
        else:  # SELL
            size_change = -fill_size
            if current_size == fill_size:
                new_vwap = 0.0
            else:
                new_vwap = current_vwap

        new_size = current_size + size_change

        return {
            "new_size": new_size,
            "size_change": size_change,
            "entry_vwap": new_vwap,
            "unrealized_pnl": None,  # Requires current mark price
        }

    @staticmethod
    def calculate_fees(
        order: dict,
        fee_rate: float = 0.001,
        derivatives_mandatory_fee_per_contract: float = 0.0,
    ) -> dict:
        """Calculate fees for an order.
        
        Computes total fees based on filled size, fill value, and fee rate.
        For derivatives, adds mandatory per-contract fees.
        
        Args:
            order: Order dict with 'filled_size', 'avg_price'.
            fee_rate: Commission rate as decimal (e.g., 0.001 for 0.1%).
            derivatives_mandatory_fee_per_contract: Fixed fee per contract per fill.\n                Caller must supply the per-side rate (e.g. $0.10 nano /\n                $0.20 full-size under Coinbase's March 2026 schedule).\n                For round-trip recovery, double it before passing in.
        
        Returns:
            Dict with:
            - 'total_fees': total fee amount
            - 'commission': percentage-based fees
            - 'mandatory_fees': fixed fees
        
        Examples:
            >>> calc = OrderCalculator()
            >>> order = {'filled_size': '1.0', 'avg_price': '100.0'}
            >>> result = calc.calculate_fees(order, fee_rate=0.001)
            >>> result['total_fees']
            0.1
            >>> result['commission']
            0.1
        """
        fill_size = safe_float(order.get("filled_size"), default=0.0)
        fill_price = safe_float(order.get("avg_price"), default=0.0)
        
        fill_value = fill_size * fill_price
        commission = fill_value * fee_rate
        mandatory_fees = fill_size * derivatives_mandatory_fee_per_contract
        total_fees = commission + mandatory_fees

        return {
            "total_fees": total_fees,
            "commission": commission,
            "mandatory_fees": mandatory_fees,
        }

    @staticmethod
    def should_create_follow_up(order: dict) -> bool:
        """Determine if an order should trigger a follow-up order.
        
        An order qualifies for follow-up if:
        - Status is FILLED
        - Has non-zero filled_size
        
        Args:
            order: Order dict with 'status' and size fields.
        
        Returns:
            True if follow-up should be created, False otherwise.
        
        Examples:
            >>> calc = OrderCalculator()
            >>> order = {'status': 'FILLED', 'filled_size': '0.5'}
            >>> calc.should_create_follow_up(order)
            True
            >>> order = {'status': 'OPEN', 'filled_size': '0.5'}
            >>> calc.should_create_follow_up(order)
            False
        """
        status = order.get("status")
        filled_size = safe_float(order.get("filled_size"), default=0.0)

        return status == OrderStatus.FILLED.value and filled_size > 0
