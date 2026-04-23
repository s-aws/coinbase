"""Profit Validator - Ensures trades are profitable after fees.

Validates that follow-up orders will be profitable after accounting for exchange fees.
Uses dynamic fee rates from FeeManager to ensure we charge enough to cover costs and profit.

Fee Charging Model (CRITICAL):
- Fees are charged ONLY when orders CLOSE on the exchange
- Open orders (establishing position) have NO fee yet
- Close orders (exiting position) incur TWO fee types:
  1. Percentage fee (taker fee × 4x multiplier)
  2. Mandatory fixed fee (FUTURE/PERPETUAL only: $0.15 per contract)

Fee Components by Product Type:
- SPOT: Only percentage fee (0.6% × 4 = 2.4%)
- FUTURE: Percentage fee (2.4%) + Mandatory $0.15 per contract
- PERPETUAL: Percentage fee (2.4%) + Mandatory $0.15 per contract

What constitutes "open" vs "close" depends on product type:
- SPOT: BUY=open, SELL=close (always)
- FUTURE/PERPETUAL: Depends on position
  - If position is LONG: BUY=open, SELL=close
  - If position is SHORT: SELL=open, BUY=close

This validator ensures follow-up orders capture enough profit to exceed the fee
charged when the close order fills.

Example (SPOT: BUY @$50K, SELL @$52.5K):
    Parent BUY fills @$50,000 (OPEN, no fee yet)
    Fee rate: 2.4% (0.6% base × 4x)
    Fee when SELL closes: $52,500 × 0.024 = $1,260
    Gross profit: $52,500 - $50,000 = $2,500
    Net profit: $2,500 - $1,260 = $1,240 ✓ PROFITABLE

Example (FUTURE SHORT position: SELL @$50K, BUY @$48.5K with 5 contracts):
    Account is SHORT, so SELL=open, BUY=close
    Parent SELL fills @$50,000 (OPEN for SHORT, no fee yet)
    Fee when BUY closes:
      - Percentage: $48,500 × 0.024 = $1,164
      - Mandatory: $0.15 × 5 contracts = $0.75
      - Total: $1,164.75
    Gross profit: ($50,000 - $48,500) × 5 = $7,500
    Net profit: $7,500 - $1,164.75 = $6,335.25 ✓ PROFITABLE
"""

from typing import Dict, Any, Optional
import logging
from calculation.formatter import safe_float
from configuration import determine_open_close_sides
from core.enums import OrderSide, ProductType

logger = logging.getLogger(__name__)

# Mandatory fixed fee for FUTURE and PERPETUAL products
DERIVATIVES_MANDATORY_FEE_PER_CONTRACT = 0.15  # $0.15 per contract on close


class ProfitValidator:
    """Validates order profitability after fees.
    
    ⚠️ CRITICAL: Profitability is PRODUCT-SPECIFIC
    
    Different product types have fundamentally different profitability considerations:
    
    **SPOT Products:**
    - No leverage, no liquidation risk
    - Profit = (sell_price - buy_price) × size - fee_on_close
    - ✅ FULLY IMPLEMENTED: Basic profitability check
    
    **FUTURE Products:**
    - Uses leverage (up to 20x), has liquidation risk
    - Profit = (close_price - open_price) × size × leverage - fee_on_close
    - ✅ IMPLEMENTED: Basic profitability + open/close logic
    - ⚠️ TODO: Margin validation (ensure position won't liquidate)
    - ⚠️ TODO: Liquidation distance check
    - ⚠️ TODO: Expiry date validation
    
    **PERPETUAL Products:**
    - Uses leverage (up to 20x), has liquidation risk
    - Has continuous funding rates (not expiry-based)
    - Profit = (close_price - open_price) × size × leverage - fee_on_close - funding_costs
    - ✅ IMPLEMENTED: Basic profitability + open/close logic
    - ⚠️ TODO: Margin validation (ensure position won't liquidate)
    - ⚠️ TODO: Liquidation distance check
    - ⚠️ TODO: Funding rate accounting (continuous cost model)
    
    Ensures follow-up orders will be profitable after accounting for:
    - Fee charged when close order fills (not open order)
    - Correct identification of open vs close orders for the product type
    - Base taker fee multiplied by 4x
    - (Future work: Margin/liquidation checks for leveraged products)
    
    Thread-safe: Can be called from multiple threads with same fee_manager instance.
    Accounts for product type and position-specific open/close determination.
    """
    
    def __init__(self, fee_manager=None):
        """Initialize ProfitValidator.
        
        Args:
            fee_manager: Optional FeeManager instance for dynamic fee rates.
                        If None, uses conservative defaults.
        """
        self.fee_manager = fee_manager
    
    def _get_fee_rate(self) -> float:
        """Get current effective fee rate (4x multiplied).
        
        Returns:
            Fee rate as decimal (e.g., 0.024 for 2.4%)
        """
        if self.fee_manager:
            return self.fee_manager.get_profit_validation_fee_rate()
        else:
            # Fallback to conservative default (0.6% * 4)
            return 0.024
    
    def is_profitable(self,
        filled_price: float,
        follow_up_price: float,
        side: str,  # 'BUY' or 'SELL' - the parent order side
        order_size: float,
        min_profit_margin: float = 0.0,
        product_type: str = 'SPOT',
        position_side: str = None,
        contract_size: float = None
    ) -> Dict[str, Any]:
        """
        Check if follow-up order is profitable after fees.
        
        ⚠️ CRITICAL: Profitability Validation is PRODUCT-SPECIFIC
        
        This method validates BASIC profitability (price difference - fees).
        Additional product-specific validations should be performed separately:
        
        **SPOT (✅ FULLY VALIDATED HERE):**
        - Basic profit check only (no leverage/margin risk)
        - Method: is_profitable() is sufficient
        
        **FUTURE (⚠️ PARTIAL VALIDATION):**
        - ✅ Basic profit check (implemented)
        - ⚠️ Margin sufficiency NOT checked (TODO)
        - ⚠️ Liquidation distance NOT checked (TODO)
        - ⚠️ Expiry date NOT checked (TODO)
        - Must add: margin, liquidation_price, contract_expiry to validation
        
        **PERPETUAL (⚠️ PARTIAL VALIDATION):**
        - ✅ Basic profit check (implemented)
        - ⚠️ Margin sufficiency NOT checked (TODO)
        - ⚠️ Liquidation distance NOT checked (TODO)
        - ⚠️ Funding rates NOT accounted for (TODO)
        - Must add: margin, liquidation_price, current_funding_rate
        
        ⚠️ CRITICAL FEE CHARGING MODEL:
        
        Fees are charged ONLY when orders CLOSE (fill on exchange):
        - Open order (parent): NO FEE YET (order is pending)
        - Close order (follow-up): FEE CHARGED when it fills
        
        For BUY parent → SELL follow-up:
            - Parent BUY @ $50,000: OPEN, no fee yet
            - Parent BUY fills: fee charged = $50,000 × size × base_fee
            - Follow-up SELL @ $52,500: OPEN, no fee yet
            - Follow-up SELL fills: fee charged = $52,500 × size × base_fee
        
        But we only validate against the FOLLOW-UP/CLOSE fee, not both:
        - Profit = (follow_up_price - filled_price) × size
        - Fee charged = follow_up_price × size × (base_fee × 4)
        - Net profit = Profit - Fee_on_close_only
        
        We require: Net profit > 0 (profit must exceed 4x Coinbase fee on close)
        
        Example with real numbers:
            Parent BUY fills @$50,000 × 1 BTC (open position)
            Follow-up SELL @$52,500 × 1 BTC (close position)
            Base Coinbase fee: 0.6%
            Effective fee (4x): 2.4%
            
            NO fee on parent buy (it's the open order)
            Fee on follow-up sell (close): $52,500 × 1 × 0.024 = $1,260
            
            Gross profit: $52,500 - $50,000 = $2,500
            Total fees: $1,260 (only on close)
            Net profit: $2,500 - $1,260 = $1,240 ✓ PROFITABLE
        
        Args:
            filled_price: Price at which parent order filled (the OPEN position)
            follow_up_price: Proposed price for follow-up order (the CLOSE position)
            side: 'BUY' or 'SELL' (the parent order side, the OPEN order)
            order_size: Size of both parent and follow-up orders
            min_profit_margin: Minimum profit threshold (default: 0 = breakeven)
            product_type: 'SPOT', 'FUTURE', or 'PERPETUAL' (default: 'SPOT')
            position_side: For futures only, 'LONG' or 'SHORT' (position context)
            contract_size: For FUTURE/PERPETUAL, the contract size (e.g., 0.01 BTC).
                          Used to adjust fee rate calculation per contract. (optional)
        
        Notes:
            Mandatory fees use raw constant ($0.15 per contract).
            For contract-size-adjusted fees, use OrderBook.mandatory_fee_per_contract.
        
        Returns:
            Dict with keys:
            - is_profitable: True if net profit > min_profit_margin
            - net_profit: Profit in USD after fees (percentage + mandatory)
            - net_profit_pct: Profit as percentage of filled_price
            - gross_profit: Profit before fees
            - total_fees: Total fees charged on close order (percentage + mandatory)
            - percentage_fees: Percentage-based fee component
            - mandatory_fees: Fixed fee component (FUTURE/PERPETUAL only)
            - fee_rate_applied: Effective fee rate used (base × 4)
            - breakeven_price: Price needed to break even
            - minimum_viable_price: Price needed to meet min_profit_margin
            - open_side: Which side is the OPEN order
            - close_side: Which side is the CLOSE order (where fee is charged)
            
        Example (SPOT):
            >>> validator = ProfitValidator(fee_manager)
            >>> result = validator.is_profitable(
            ...     filled_price=50000.0,      # Parent filled (open)
            ...     follow_up_price=52500.0,   # Follow-up price (close)
            ...     side='BUY',
            ...     order_size=1.0,
            ...     product_type='SPOT'        # Default
            ... )
            
        Example (FUTURE with SHORT position):
            >>> result = validator.is_profitable(
            ...     filled_price=50000.0,      # Parent SELL (open for SHORT)
            ...     follow_up_price=48500.0,   # Follow-up BUY (close)
            ...     side='SELL',
            ...     order_size=1.0,
            ...     product_type='FUTURE',
            ...     position_side='SHORT'      # SELL is open, BUY is close
            ... )
        """
        # Determine which side is open/close based on product type and current position
        # Pass parent_order_side (the 'side' parameter) for context when position is closed
        open_side, close_side = determine_open_close_sides(
            product_type, 
            position_side,
            parent_order_side=side
        )
        
        # TODO: Change to DEBUG level logging
        logger.info(
            f"Open/Close side determination | Product: {product_type} | "
            f"Parent side: {side} | Position side: {position_side} | "
            f"Determined: OPEN={open_side}, CLOSE={close_side}"
        )
        
        # Get the effective fee rate (base_fee_rate × 4)
        fee_rate = self._get_fee_rate()
        
        # For FUTURE/PERPETUAL products, order_size is in "number of contracts"
        # We need to convert to actual position size (in BTC/units) for fee calculation
        # Gross profit and fees should be based on actual position size, not contract count
        effective_size = order_size
        if product_type in ('FUTURE', 'PERPETUAL') and contract_size and contract_size > 0:
            effective_size = order_size * float(contract_size)
            # TODO: Change to DEBUG level logging
            logger.info(
                f"Contract size adjustment | Product: {product_type} | "
                f"Order size (contracts): {order_size} | Contract size: {contract_size} | "
                f"Effective size (units): {effective_size}"
            )
        
        # Calculate gross profit (before fees)
        # Profit is the price difference between open and close
        if side == OrderSide.BUY.value:
            # Parent was BUY (open), follow-up will be SELL (close)
            gross_profit = (follow_up_price - filled_price) * effective_size
        else:  # SELL
            # Parent was SELL (open), follow-up will be BUY (close)
            gross_profit = (filled_price - follow_up_price) * effective_size
        
        # Calculate fees - ONLY the close order incurs fees
        # The fee is charged on the close_side order's price
        # Important: Fee is charged at close_side price, not open_side price
        percentage_fees = follow_up_price * effective_size * fee_rate
        
        # TODO: Change to DEBUG level logging
        logger.info(
            f"Fee rate applied | Base fee rate: {fee_rate:.6f} ({fee_rate*100:.4f}%) | "
            f"Follow-up price: ${follow_up_price:.2f} | Size: {order_size} | "
            f"Calculated percentage fee: ${percentage_fees:.2f}"
        )
        
        # Add mandatory fixed fee for FUTURE/PERPETUAL contracts
        # FUTURE and PERPETUAL products charge $0.15 per contract on close
        # SPOT products have no mandatory fee
        # Note: Uses raw constant; OrderBook pre-computes contract-size-adjusted fees
        mandatory_fees = 0.0
        if product_type in ('FUTURE', 'PERPETUAL'):
            mandatory_fees = DERIVATIVES_MANDATORY_FEE_PER_CONTRACT * order_size
            # TODO: Change to DEBUG level logging
            logger.info(
                f"Mandatory fee applied | Product: {product_type} | "
                f"Contracts: {order_size} | Fee: ${mandatory_fees:.2f} "
                f"(${DERIVATIVES_MANDATORY_FEE_PER_CONTRACT} per contract)"
            )
        
        total_fees = percentage_fees + mandatory_fees
        
        # Calculate net profit
        net_profit = gross_profit - total_fees
        
        # Calculate net profit as percentage
        net_profit_pct = net_profit / filled_price if filled_price > 0 else 0.0
        
        # Calculate breakeven price (zero profit)
        breakeven_price = self._calculate_breakeven_price(
            filled_price, side, order_size, fee_rate, open_side, close_side
        )
        
        # Calculate minimum viable price (for desired profit)
        minimum_viable_price = self._calculate_minimum_viable_price(
            filled_price, side, order_size, fee_rate, min_profit_margin, open_side, close_side
        )
        
        is_profitable = net_profit > min_profit_margin
        
        # TODO: Change to DEBUG level logging
        # Log profitability result
        if mandatory_fees > 0:  # Only log when mandatory fees present (FUTURE/PERPETUAL)
            logger.info(
                f"Profitability result | Product: {product_type} | "
                f"GrossProfit: ${gross_profit:.2f} | "
                f"Fees: ${total_fees:.2f} (Percentage: ${percentage_fees:.2f} + Mandatory: ${mandatory_fees:.2f}) | "
                f"NetProfit: ${net_profit:.2f} | Status: {'PROFITABLE' if is_profitable else 'UNPROFITABLE'}"
            )
        
        return {
            "is_profitable": is_profitable,
            "net_profit": net_profit,
            "net_profit_pct": net_profit_pct,
            "gross_profit": gross_profit,
            "total_fees": total_fees,
            "percentage_fees": percentage_fees,
            "mandatory_fees": mandatory_fees,
            "fee_rate_applied": fee_rate,
            "breakeven_price": breakeven_price,
            "minimum_viable_price": minimum_viable_price,
            "open_side": open_side,
            "close_side": close_side,
        }
    
    def _calculate_breakeven_price(self, 
                                  filled_price: float, 
                                  side: str,
                                  order_size: float, 
                                  fee_rate: float,
                                  open_side: str = 'BUY',
                                  close_side: str = 'SELL') -> float:
        """Calculate price needed to break even (zero profit).
        
        Accounts for fee on the CLOSE order only (follow-up).
        The OPEN order (parent) has no fee.
        
        For BUY parent → SELL follow-up:
            Net profit = (sell_price - buy_price) × size - (sell_price × size × fee_rate)
            At breakeven: 0 = (sell_price - filled) × size - sell_price × size × fee_rate
            Solving: sell_price = filled_price / (1 - fee_rate)
        
        For SELL parent → BUY follow-up:
            Net profit = (sell_price - buy_price) × size - (buy_price × size × fee_rate)
            At breakeven: 0 = (filled - buy_price) × size - buy_price × size × fee_rate
            Solving: buy_price = filled_price / (1 + fee_rate)
        
        Args:
            filled_price: Original fill price (the OPEN order)
            side: Parent order side ('BUY' or 'SELL') - should match open_side
            order_size: Size of both orders
            fee_rate: Effective fee rate (already multiplied by 4x)
            open_side: The side that opens positions (default 'BUY')
            close_side: The side that closes positions (default 'SELL')
        
        Returns:
            Price at which net profit = 0
        """
        if side == OrderSide.BUY.value:
            # Parent BUY (open, no fee), Follow-up SELL (close, has fee)
            # 0 = (follow_up - filled) × size - follow_up × size × fee_rate
            # 0 = follow_up × size - filled × size - follow_up × size × fee_rate
            # filled × size = follow_up × size × (1 - fee_rate)
            # follow_up = filled / (1 - fee_rate)
            return filled_price / (1 - fee_rate) if fee_rate < 1 else filled_price
        else:
            # Parent SELL (open, no fee), Follow-up BUY (close, has fee)
            # 0 = (filled - follow_up) × size - follow_up × size × fee_rate
            # 0 = filled × size - follow_up × size - follow_up × size × fee_rate
            # filled × size = follow_up × size × (1 + fee_rate)
            # follow_up = filled / (1 + fee_rate)
            return filled_price / (1 + fee_rate)
    
    def _calculate_minimum_viable_price(self,
                                       filled_price: float,
                                       side: str,
                                       order_size: float,
                                       fee_rate: float,
                                       min_profit: float,
                                       open_side: str = 'BUY',
                                       close_side: str = 'SELL') -> float:
        """Calculate price needed to achieve desired minimum profit.
        
        Accounts for fee on the CLOSE order only (follow-up).
        
        Args:
            filled_price: Original fill price (open order)
            side: Parent order side ('BUY' or 'SELL') - should match open_side
            order_size: Size of both orders
            fee_rate: Effective fee rate (already multiplied by 4x)
            min_profit: Minimum desired profit in USD
            open_side: The side that opens positions (default 'BUY')
            close_side: The side that closes positions (default 'SELL')
        
        Returns:
            Price at which net profit >= min_profit
        """
        # Get breakeven price first
        breakeven = self._calculate_breakeven_price(filled_price, side, order_size, fee_rate, open_side, close_side)
        
        # How much additional price movement do we need per unit?
        profit_per_unit = min_profit / order_size if order_size > 0 else 0
        
        if side == OrderSide.BUY.value:
            # SELL at: breakeven + profit_per_unit
            return breakeven + profit_per_unit
        else:
            # BUY at: breakeven - profit_per_unit
            return breakeven - profit_per_unit
    
    def validate_order_profitability(self,
                                    parent_filled_price: float,
                                    parent_side: str,
                                    follow_up_price: float,
                                    order_size: float,
                                    min_margin_pct: float = 0.0) -> Dict[str, Any]:
        """Comprehensive profitability validation with detailed reporting.
        
        Args:
            parent_filled_price: Price at which parent order filled
            parent_side: Side of parent order ('BUY' or 'SELL')
            follow_up_price: Proposed price for follow-up
            order_size: Size of orders
            min_margin_pct: Minimum profit margin as percentage (e.g., 0.005 for 0.5%)
        
        Returns:
            Dict with profitability assessment and remediation suggestions
        """
        fee_rate = self._get_fee_rate()
        
        # Validate inputs
        if order_size <= 0:
            return {
                "is_valid": False,
                "is_profitable": False,
                "error": "Order size must be positive",
                "remediation": "Check order size calculation"
            }
        
        if parent_side not in ("BUY", "SELL"):
            return {
                "is_valid": False,
                "is_profitable": False,
                "error": f"Invalid side: {parent_side}",
                "remediation": "Use 'BUY' or 'SELL'"
            }
        
        if follow_up_price <= 0 or parent_filled_price <= 0:
            return {
                "is_valid": False,
                "is_profitable": False,
                "error": "Prices must be positive",
                "remediation": "Check price values"
            }
        
        # Calculate profitability
        min_profit = parent_filled_price * min_margin_pct * order_size
        
        result = self.is_profitable(
            filled_price=parent_filled_price,
            follow_up_price=follow_up_price,
            side=parent_side,
            order_size=order_size,
            min_profit_margin=min_profit
        )
        
        # Add validation status and remediation
        result["is_valid"] = True
        result["fee_rate_base"] = self._get_fee_rate() / 4.0  # Show base rate too
        result["multiplier"] = 4.0
        result["parent_filled_price"] = parent_filled_price
        result["follow_up_proposed_price"] = follow_up_price
        result["order_size"] = order_size
        
        if not result["is_profitable"]:
            # Suggest adjusted price
            result["suggested_action"] = "REJECT_ORDER"
            result["reason"] = f"Would result in loss of ${abs(result['net_profit']):.2f} after fees"
            result["suggested_follow_up_price"] = result["minimum_viable_price"]
            result["price_adjustment_needed"] = result["minimum_viable_price"] - follow_up_price
        else:
            result["suggested_action"] = "ACCEPT_ORDER"
            result["reason"] = f"Profitable: ${result['net_profit']:.2f} net profit after fees"
            result["suggested_follow_up_price"] = follow_up_price
            result["price_adjustment_needed"] = 0.0
        
        return result
    
    def explain_fee_calculation(self, 
                               filled_price: float,
                               follow_up_price: float,
                               order_size: float) -> Dict[str, Any]:
        """Detailed explanation of fee calculation (for debugging and verification).
        
        Shows the complete fee breakdown for OPEN and CLOSE orders.
        
        Returns a dict showing:
        - base_fee_rate: From Coinbase API (e.g., 0.006 for 0.6%)
        - multiplier: Applied multiplier (4.0)
        - effective_fee_rate: base × multiplier (e.g., 0.024 for 2.4%)
        - fee_on_open: Cost when parent order (open) fills - ZERO
        - fee_on_close: Cost when follow-up order (close) fills
        - total_fees: Sum of both (just the close fee)
        - breakdown: Clear text explanation
        
        Example:
            >>> explanation = validator.explain_fee_calculation(
            ...     filled_price=50000.0,      # Open order
            ...     follow_up_price=52500.0,   # Close order
            ...     order_size=1.0
            ... )
            >>> print(explanation['breakdown'])
        """
        fee_rate_effective = self._get_fee_rate()
        
        # Back-calculate the base rate (we store it as multiplied)
        # This is for clarity - to show base vs effective
        base_fee = fee_rate_effective / 4.0
        
        # OPEN order (parent): NO FEE CHARGED
        fee_on_open = 0.0
        
        # CLOSE order (follow-up): FEE CHARGED when it fills
        fee_on_close = follow_up_price * order_size * fee_rate_effective
        
        total_fees = fee_on_open + fee_on_close
        
        # Build clear explanation
        breakdown = f"""
FEE CALCULATION BREAKDOWN (OPEN vs CLOSE)
==========================================

Base Coinbase taker fee: {base_fee:.4%}
Our multiplier: 4x
Effective fee for validation: {fee_rate_effective:.4%}

Order sizes: {order_size} units

When OPEN order (parent BUY) fills at ${filled_price:,.2f}:
  Fee = $0.00
  (Fee is NOT charged when the OPEN position is established)

When CLOSE order (follow-up SELL) fills at ${follow_up_price:,.2f}:
  Fee = ${follow_up_price:,.2f} × {order_size} × {fee_rate_effective:.4%} = ${fee_on_close:,.2f}
  (Fee IS charged when the position is CLOSED/closed out)

TOTAL FEES for round-trip: ${total_fees:,.2f}
(This is 1× effective fee on the close order only, not both orders)

Profit calculation:
  Gross profit: ${follow_up_price:,.2f} - ${filled_price:,.2f} = ${(follow_up_price - filled_price) * order_size:,.2f}
  Fees charged: ${fee_on_close:,.2f}
  Net profit: ${(follow_up_price - filled_price) * order_size - fee_on_close:,.2f}
"""
        
        return {
            "base_fee_rate": base_fee,
            "multiplier": 4.0,
            "effective_fee_rate": fee_rate_effective,
            "fee_on_open": fee_on_open,
            "fee_on_close": fee_on_close,
            "total_fees": total_fees,
            "breakdown": breakdown,
            "note": "Fee is charged ONLY when orders close. Open order has NO fee."
        }
