"""Validate follow-up profitability against a conservative round-trip model.

Percentage exchange fees are budgeted on both the entry and exit notional.
``FeeManager`` supplies an immutable quote selected from the product-specific
fee schedule: maker only when ``post_only=True`` and taker otherwise. Futures
also include the product's all-in fixed per-contract fee on both sides.

This is pre-trade validation, not fill-ledger accounting. It intentionally
assumes the same selected liquidity rate for both legs; actual fill liquidity
and statement rounding are outside this decision path.
"""

from typing import Dict, Any, Optional
import logging
from calculation.formatter import safe_float
from configuration import determine_open_close_sides
from core.constants import get_derivatives_per_side_fee
from core.enums import (
    LiquidityAssumption,
    OrderSide,
    ProductType,
    TargetMovementType,
)

logger = logging.getLogger(__name__)


class ProfitValidator:
    """Validates order profitability after fees.
    
    ⚠️ CRITICAL: Profitability is PRODUCT-SPECIFIC
    
    Different product types have fundamentally different profitability considerations:
    
    **SPOT Products:**
    - No leverage, no liquidation risk
    - Profit = (sell_price - buy_price) × size - round_trip_percentage_fees
    - ✅ FULLY IMPLEMENTED: Basic profitability check
    
    **FUTURE Products:**
    - Uses leverage (up to 20x), has liquidation risk
    - Profit = price movement × contract size - round_trip fees
    - ✅ IMPLEMENTED: Basic profitability + open/close logic
    - ⚠️ TODO: Margin validation (ensure position won't liquidate)
    - ⚠️ TODO: Liquidation distance check
    - ⚠️ TODO: Expiry date validation
    
    **PERPETUAL Products:**
    - Uses leverage (up to 20x), has liquidation risk
    - Has continuous funding rates (not expiry-based)
    - Profit = price movement × size - round_trip fees - funding costs
    - ✅ IMPLEMENTED: Basic profitability + open/close logic
    - ⚠️ TODO: Margin validation (ensure position won't liquidate)
    - ⚠️ TODO: Liquidation distance check
    - ⚠️ TODO: Funding rate accounting (continuous cost model)
    
    Ensures follow-up orders will be profitable after accounting for:
    - Percentage fees budgeted on both entry and exit fills
    - Correct identification of open vs close orders for the product type
    - Atomic maker/taker validation quote from FeeManager
    - (Future work: Margin/liquidation checks for leveraged products)
    
    Thread-safe: Can be called from multiple threads with same fee_manager instance.
    Accounts for product type and position-specific open/close determination.
    """
    
    def __init__(self, fee_manager=None, orderbook=None):
        """Initialize ProfitValidator.
        
        Args:
            fee_manager: Optional FeeManager instance for dynamic fee rates.
                        If None, uses conservative defaults.
            orderbook: Optional OrderBook instance used to auto-resolve product
                      context (product_type, contract_size, position_side) from
                      a product_id. When provided, callers may pass only
                      product_id and the validator will look up the rest.
                      When omitted, callers must supply context explicitly.
        """
        self.fee_manager = fee_manager
        self.orderbook = orderbook
    
    def _resolve_product_context(
        self,
        product_id: Optional[str],
        order: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Resolve product_type, contract_size, and position_side from product_id.

        Single source of truth for product context resolution. Used internally
        by is_profitable() and validate_order_profitability() so callers don't
        have to duplicate this logic across the codebase.

        Resolution order for product_type:
            1. order['product_type'] (if provided and valid)
            2. orderbook.product[product_id]['product_type']
            3. Suffix-based fallback: '-CDE' → FUTURE, else SPOT

        contract_size: Resolved from orderbook.product[product_id]
            ['future_product_details']['contract_size'] for FUTURE products.
            None for SPOT or when unavailable.

        position_side: Resolved via orderbook.get_position_side(product_id)
            for FUTURE products. None for SPOT or when no position exists.

        Args:
            product_id: Trading pair identifier (e.g., 'BIP-20DEC30-CDE').
            order: Optional order dict for product_type hint.

        Returns:
            Dict with keys: product_type, contract_size, position_side.
        """
        # Lazy import to avoid circular dependencies
        from configuration import normalize_product_type as _normalize_product_type

        # Resolve product_type from order hint or orderbook fallback
        order_for_normalize = dict(order) if order else {}
        if product_id and "product_id" not in order_for_normalize:
            order_for_normalize["product_id"] = product_id
        products = self.orderbook.product if self.orderbook else None
        product_type = _normalize_product_type(order_for_normalize, products=products)

        contract_size: Optional[float] = None
        position_side: Optional[str] = None

        if product_type == ProductType.FUTURE.value and self.orderbook and product_id:
            product_data = self.orderbook.product.get(product_id, {})
            raw_contract_size = (
                product_data.get("future_product_details", {}).get("contract_size")
                if isinstance(product_data, dict) else None
            )
            if raw_contract_size is not None:
                try:
                    candidate = float(raw_contract_size)
                    if candidate > 0:
                        contract_size = candidate
                except (TypeError, ValueError):
                    contract_size = None

            try:
                position_side = self.orderbook.get_position_side(product_id)
            except Exception:
                position_side = None

        return {
            "product_type": product_type,
            "contract_size": contract_size,
            "position_side": position_side,
        }
    
    def _get_fee_rate(
        self,
        product_id: str = None,
        post_only: bool = False,
        product_type: str = None,
    ) -> float:
        """Get current effective fee rate (adaptive base multiplier model).

        Args:
            product_id: Optional product hint for multiplier resolution.
            post_only: When ``True``, the order will rest as a maker if it
                doesn't cross. FeeManager returns the maker rate × multiplier
                instead of the taker rate. Default ``False`` matches the
                behavior for ``CONFIGURED_LIMIT`` reveals where the user-
                supplied price may cross the spread (taker semantics).
            product_type: Optional explicit schedule hint when ``product_id``
                is missing or is a local alias.
        """
        if self.fee_manager:
            return self.fee_manager.get_profit_validation_fee_rate(
                product_id=product_id,
                post_only=post_only,
                product_type=product_type,
            )
        else:
            # Fallback to conservative default. Use a maker-style estimate
            # when post_only=True (~0.4% × 1.1 cushion) to match the live
            # FeeManager behaviour for SPOT orders.
            return 0.0044 if post_only else 0.012

    def derive_follow_up_price_from_target(
        self,
        parent_filled_price: float,
        parent_side: str,
        target_movement: float,
        target_movement_type: str = TargetMovementType.PERCENTAGE.value,
    ) -> Optional[float]:
        """Derive follow-up close price from target movement configuration.

        This is the shared conversion used by reveal-time revalidation and any
        other flow that starts with entry price + target movement (P/A).

        Args:
            parent_filled_price: Entry/open price.
            parent_side: Parent/open side (BUY/SELL).
            target_movement: Target movement value (> 0).
            target_movement_type: TargetMovementType.PERCENTAGE ('P') or ABSOLUTE ('A').

        Returns:
            Derived follow-up price, or None if inputs are invalid.
        """
        side_raw = str(parent_side or "").upper()
        try:
            side = OrderSide(side_raw)
        except ValueError:
            return None

        filled_price = safe_float(parent_filled_price, default=0.0)
        movement = safe_float(target_movement, default=0.0)
        if filled_price <= 0 or movement <= 0:
            return None

        movement_type_raw = str(
            target_movement_type or TargetMovementType.PERCENTAGE.value
        ).upper()
        try:
            movement_type = TargetMovementType(movement_type_raw)
        except ValueError:
            movement_type = TargetMovementType.PERCENTAGE

        if movement_type == TargetMovementType.ABSOLUTE:
            return (
                filled_price + movement
                if side == OrderSide.BUY
                else filled_price - movement
            )

        return (
            filled_price * (1 + movement)
            if side == OrderSide.BUY
            else filled_price * (1 - movement)
        )
    
    def is_profitable(self,
        filled_price: float,
        follow_up_price: float,
        side: str,  # 'BUY' or 'SELL' - the parent order side
        order_size: float,
        min_profit_margin: float = 0.0,
        product_type: str = None,
        position_side: str = None,
        product_id: str = None,
        contract_size: float = None,
        triggered_by_fill: bool = False,
        post_only: bool = False,
        _fee_rate_override: Optional[float] = None,
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
        
        Fee model:
        - Percentage fees = (entry price + exit price) × effective size × rate.
        - Futures fixed fees = all-in per-contract/side × contracts × 2 sides.
        - Maker rate is permitted only when ``post_only=True``; otherwise the
          quote assumes taker regardless of the submitted limit price.
        
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
            Mandatory fees resolved per product via
            ``core.constants.get_derivatives_per_side_fee`` and doubled for
            the round-trip (Coinbase charges per side under the March 2026
            schedule). For contract-size-adjusted offsets used by the
            order-spacing path, see ``OrderBook.mandatory_fee_per_contract``.
        
        Returns:
            Dict with keys:
            - is_profitable: True if net profit > min_profit_margin
            - net_profit: Profit in USD after fees (percentage + mandatory)
            - net_profit_pct: Profit as percentage of filled_price
            - gross_profit: Profit before fees
            - total_fees: Budgeted round-trip percentage + mandatory fees
            - percentage_fees: Percentage-based fee component
            - mandatory_fees: Fixed fee component (FUTURE/PERPETUAL only)
            - fee_rate_applied: Effective fee rate used (base × multiplier × regime)
            - breakeven_price: Price needed to break even
            - minimum_viable_price: Price needed to meet min_profit_margin
            - open_side: Which side is the OPEN order
            - close_side: Which side closes the position
            
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
        # Auto-resolve product context from orderbook when caller didn't supply it.
        # This is the single point that fills in missing product_type / contract_size /
        # position_side, so callers only need to pass product_id (when an orderbook
        # is wired in). Explicit args always win over auto-resolution.
        if (product_type is None or contract_size is None or position_side is None) \
                and self.orderbook is not None and product_id:
            ctx = self._resolve_product_context(product_id)
            if product_type is None:
                product_type = ctx["product_type"]
            if contract_size is None:
                contract_size = ctx["contract_size"]
            if position_side is None:
                position_side = ctx["position_side"]
        
        # Final defaults if context still unresolved (no orderbook available)
        if product_type is None:
            product_type = ProductType.SPOT.value
        
        # Determine which side is open/close based on product type and current position
        # Pass parent_order_side (the 'side' parameter) for context when position is closed
        open_side, close_side = determine_open_close_sides(
            product_type, 
            position_side,
            parent_order_side=side
        )
        
        if triggered_by_fill:
            logger.info(
                f"Open/Close side determination | Product: {product_type} | "
                f"Parent side: {side} | Position side: {position_side} | "
                f"Determined: OPEN={open_side}, CLOSE={close_side}"
            )
        
        # Get the effective fee rate (base_fee_rate x multiplier x regime_factor).
        # post_only orders rest as makers (lower rate); regular orders that
        # may cross the spread pay the taker rate.
        fee_rate = (
            _fee_rate_override
            if _fee_rate_override is not None
            else self._get_fee_rate(
                product_id=product_id,
                post_only=post_only,
                product_type=product_type,
            )
        )
        
        # For FUTURE/PERPETUAL products, order_size is in "number of contracts"
        # We need to convert to actual position size (in BTC/units) for fee calculation
        # Gross profit and fees should be based on actual position size, not contract count
        effective_size = order_size
        if product_type == ProductType.FUTURE.value and contract_size and contract_size > 0:
            effective_size = order_size * float(contract_size)

            if triggered_by_fill:
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
        
        # Budget the selected maker/taker rate on BOTH sides (open + close).
        # The pre-trade model intentionally applies one liquidity assumption
        # to the complete round trip.
        # The pre-2026-05-01 formula computed only the close-side fee and
        # relied on a hidden 2.0 multiplier in FeeManager to compensate.
        # That coupling silently broke when the multiplier was tuned away
        # from 2.0; this version makes the round-trip fee explicit so the
        # multiplier can mean what it says (cushion only).
        percentage_fees = (filled_price + follow_up_price) * effective_size * fee_rate

        if triggered_by_fill:
            logger.info(
                f"Fee rate applied | Effective fee rate: {fee_rate:.6f} ({fee_rate*100:.4f}%) | "
                f"Open price: ${filled_price:.2f} | Close price: ${follow_up_price:.2f} | "
                f"Size: {order_size} | Round-trip percentage fee: ${percentage_fees:.2f}"
            )
        
        # Add mandatory fixed fee for FUTURE/PERPETUAL contracts.
        # Coinbase's March 2026 schedule charges the per-contract
        # commission per side (open + close), so round-trip = 2 × per-side.
        # Per-side all-in rate depends on product (settlement-reconciled
        # default = $0.12; explicit legacy full-size assumption = $0.27).
        # Resolved per product_id.
        # SPOT products have no mandatory fee.
        mandatory_fees = 0.0
        if product_type == ProductType.FUTURE.value:
            per_side_fee = get_derivatives_per_side_fee(product_id or "")
            mandatory_fees = per_side_fee * order_size * 2.0

            if triggered_by_fill:
                logger.info(
                    f"Mandatory fee applied | Product: {product_type} | "
                    f"Contracts: {order_size} | Round-trip fee: ${mandatory_fees:.2f} "
                    f"(${per_side_fee} per side × 2 sides)"
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

        # Log profitability result only when this evaluation is triggered by an
        # actual (partial) fill; reveal/reprice revalidation paths stay quiet.
        if triggered_by_fill and mandatory_fees > 0:  # FUTURE/PERPETUAL only
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
        
        Round-trip fee model: the selected validation rate is budgeted on
        BOTH the open fill (parent) and the close fill (follow-up). The
        break-even price therefore has to clear two fee instances, not one.
        
        For BUY parent → SELL follow-up:
            Net profit = (sell - buy) × size - (buy + sell) × size × fee_rate
            At breakeven:  sell × (1 - fee_rate) = buy × (1 + fee_rate)
            Solving:       sell = buy × (1 + fee_rate) / (1 - fee_rate)
        
        For SELL parent → BUY follow-up:
            Net profit = (sell - buy) × size - (buy + sell) × size × fee_rate
            At breakeven:  buy × (1 + fee_rate) = sell × (1 - fee_rate)
            Solving:       buy = sell × (1 - fee_rate) / (1 + fee_rate)
        
        Args:
            filled_price: Original fill price (the OPEN order)
            side: Parent order side ('BUY' or 'SELL') - should match open_side
            order_size: Size of both orders
            fee_rate: Effective fee rate (already includes multiplier/regime)
            open_side: The side that opens positions (default 'BUY')
            close_side: The side that closes positions (default 'SELL')
        
        Returns:
            Price at which net profit = 0
        """
        if side == OrderSide.BUY.value:
            # Parent BUY (open, has fee), Follow-up SELL (close, has fee)
            # 0 = (sell - buy)·size - (buy + sell)·size·fee_rate
            # sell·(1 - fee_rate) = buy·(1 + fee_rate)
            if fee_rate >= 1:
                return filled_price
            return filled_price * (1 + fee_rate) / (1 - fee_rate)
        else:
            # Parent SELL (open, has fee), Follow-up BUY (close, has fee)
            # 0 = (sell - buy)·size - (buy + sell)·size·fee_rate
            # buy·(1 + fee_rate) = sell·(1 - fee_rate)
            return filled_price * (1 - fee_rate) / (1 + fee_rate)
    
    def _calculate_minimum_viable_price(self,
                                       filled_price: float,
                                       side: str,
                                       order_size: float,
                                       fee_rate: float,
                                       min_profit: float,
                                       open_side: str = 'BUY',
                                       close_side: str = 'SELL') -> float:
        """Calculate price needed to achieve desired minimum profit.

        Builds on the round-trip break-even (selected validation rate on both
        open and close fills), then adds the per-unit profit headroom required
        to clear ``min_profit``.

        Args:
            filled_price: Original fill price (open order)
            side: Parent order side ('BUY' or 'SELL') - should match open_side
            order_size: Size of both orders
            fee_rate: Effective fee rate (already includes multiplier/regime)
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
                                    min_margin_pct: float = 0.0,
                                    product_type: str = None,
                                    product_id: str = None,
                                    position_side: str = None,
                                    contract_size: float = None,
                                    triggered_by_fill: bool = False,
                                    post_only: bool = False) -> Dict[str, Any]:
        """Comprehensive profitability validation with detailed reporting.
        
        When the validator was constructed with an orderbook, callers can pass
        only product_id and the validator will auto-resolve product_type,
        contract_size, and position_side. Explicit args always win.
        
        Args:
            parent_filled_price: Price at which parent order filled
            parent_side: Side of parent order ('BUY' or 'SELL')
            follow_up_price: Proposed price for follow-up
            order_size: Size of orders
            min_margin_pct: Minimum profit margin as percentage (e.g., 0.005 for 0.5%)
            product_type: Optional ProductType value; auto-resolved from product_id if omitted
            product_id: Trading pair ID (used for context auto-resolution and fee rate lookup)
            position_side: Optional 'LONG'/'SHORT'; auto-resolved from product_id if omitted
            contract_size: Optional contract size; auto-resolved from product_id if omitted
        
        Returns:
            Dict with profitability assessment and remediation suggestions
        """
        # Validate inputs
        if order_size <= 0:
            return {
                "is_valid": False,
                "is_profitable": False,
                "error": "Order size must be positive",
                "remediation": "Check order size calculation"
            }
        
        if parent_side not in (OrderSide.BUY.value, OrderSide.SELL.value):
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

        # Sample the complete FeeManager quote once. Every field used by this
        # decision is then immutable even if the hourly refresh or websocket
        # regime state changes concurrently while the math is running.
        fee_quote = None
        quote_getter = (
            getattr(type(self.fee_manager), "get_profit_validation_fee_quote", None)
            if self.fee_manager is not None else None
        )
        if callable(quote_getter):
            fee_quote = self.fee_manager.get_profit_validation_fee_quote(
                product_id=product_id,
                post_only=post_only,
                product_type=product_type,
            )
            fee_rate = fee_quote.validation_fee_rate
        else:
            fee_rate = self._get_fee_rate(
                product_id=product_id,
                post_only=post_only,
                product_type=product_type,
            )
        
        # Pass through to is_profitable() which handles auto-resolution of product context
        result = self.is_profitable(
            filled_price=parent_filled_price,
            follow_up_price=follow_up_price,
            side=parent_side,
            order_size=order_size,
            min_profit_margin=min_profit,
            product_type=product_type,
            product_id=product_id,
            position_side=position_side,
            contract_size=contract_size,
            triggered_by_fill=triggered_by_fill,
            post_only=post_only,
            _fee_rate_override=fee_rate,
        )
        
        # Add validation status and remediation
        result["is_valid"] = True
        # Effective rate already includes the (now product-type-aware)
        # multiplier and regime factor from FeeManager. Surface the live
        # effective rate as-is; callers that want the base rate can ask
        # FeeManager directly. The legacy ``/ 2.0`` divisor here was a
        # leftover from when DEFAULT_MULTIPLIER was hardcoded to 2.0 and
        # would lie about the base rate after the 2026-05-01 split.
        result["fee_rate_effective"] = fee_rate
        result["parent_filled_price"] = parent_filled_price
        result["follow_up_proposed_price"] = follow_up_price
        result["order_size"] = order_size
        liquidity_assumption = (
            LiquidityAssumption.MAKER
            if post_only else LiquidityAssumption.TAKER
        )
        result["liquidity_assumption"] = liquidity_assumption.value
        if fee_quote is not None:
            result.update({
                "exchange_fee_rate": fee_quote.exchange_fee_rate,
                "fee_product_type": fee_quote.product_type.value,
                "fee_product_multiplier": fee_quote.product_multiplier,
                "fee_regime_factor": fee_quote.raw_fee_regime_factor,
                "fee_validation_factor": fee_quote.applied_fee_regime_factor,
                "fee_pricing_tier": fee_quote.pricing_tier,
                "fee_schedule_source": fee_quote.source.value,
                "fee_has_cost_plus_commission": (
                    fee_quote.has_cost_plus_commission
                ),
            })
        
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
                               order_size: float,
                               product_id: Optional[str] = None) -> Dict[str, Any]:
        """Detailed explanation of fee calculation (for debugging and verification).

        Coinbase charges its taker fee on every fill, so the round-trip fee is
        the sum of the open-fill fee and the close-fill fee. Earlier versions
        of this method modeled only the close fee and relied on a hidden 2.0
        multiplier in FeeManager to compensate; that coupling is gone now.

        Returns a dict showing:
        - effective_fee_rate: Live rate from FeeManager (base × cushion × regime)
        - fee_on_open: Cost when parent (open) order fills
        - fee_on_close: Cost when follow-up (close) order fills
        - total_fees: fee_on_open + fee_on_close
        - breakdown: Clear text explanation
        """
        fee_rate_effective = self._get_fee_rate(product_id=product_id)

        # BOTH sides incur the taker fee (Coinbase charges per fill).
        fee_on_open = filled_price * order_size * fee_rate_effective
        fee_on_close = follow_up_price * order_size * fee_rate_effective
        total_fees = fee_on_open + fee_on_close

        breakdown = f"""
FEE CALCULATION BREAKDOWN (round-trip, both sides)
===================================================

Effective fee rate (per side): {fee_rate_effective:.4%}
Order size: {order_size} units

OPEN fill (parent) at ${filled_price:,.2f}:
  Fee = ${filled_price:,.2f} × {order_size} × {fee_rate_effective:.4%} = ${fee_on_open:,.2f}

CLOSE fill (follow-up) at ${follow_up_price:,.2f}:
  Fee = ${follow_up_price:,.2f} × {order_size} × {fee_rate_effective:.4%} = ${fee_on_close:,.2f}

TOTAL ROUND-TRIP FEES: ${total_fees:,.2f}

Profit calculation:
  Gross profit: (${follow_up_price:,.2f} - ${filled_price:,.2f}) × {order_size} = ${(follow_up_price - filled_price) * order_size:,.2f}
  Round-trip fees: ${total_fees:,.2f}
  Net profit: ${(follow_up_price - filled_price) * order_size - total_fees:,.2f}
"""

        return {
            "effective_fee_rate": fee_rate_effective,
            "fee_on_open": fee_on_open,
            "fee_on_close": fee_on_close,
            "total_fees": total_fees,
            "breakdown": breakdown,
            "note": "Coinbase charges the taker fee on BOTH the open and close fills.",
        }
