"""
Order Interception Layer - Pre-processing hook for profit-aware execution.

This layer intercepts new orders BEFORE they're submitted to the exchange,
applies lot-based profit constraints, and wraps them with conditional
execution requirements.

Design:
- Minimal intrusion: Orders still go through normal execution paths
- Layering: Adds constraints as order metadata
- Non-blocking: Can operate in advisory or enforcing mode

The interceptor acts as a decision-support layer, providing:
1. Profit-aware lot selection
2. Price constraints for execution
3. Metadata enrichment (why this order was shaped)

This enables the existing order engine to continue unchanged while
gaining profit-aware capabilities.

Example:
    >>> from business.fill_ledger import FillLedgerRepository
    >>> from business.order_interception_layer import OrderInterceptionLayer
    >>> from core.enums import OrderSide
    >>>
    >>> repo = FillLedgerRepository(db_client)
    >>> layer = OrderInterceptionLayer(repo, profit_margin_pct=0.5, strategy_mode='ADVISORY')
    >>> enriched_order, meta = layer.intercept_order(
    ...     product_id='BTC-USDC',
    ...     side=OrderSide.SELL,
    ...     size=0.1,
    ...     price=43000.0,
    ...     market_price=43010.0,
    ... )
    >>> 'product_id' in enriched_order
    True
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from business.lot_builder import PositionLotBuilder
from business.profit_threshold_engine import ProfitThresholdEngine, ExecutionTarget
from business.position_lot import LotPosition
from business.fill_ledger import FillLedgerRepository
from core.enums import OrderSide
from logging_service import get_logger

logger = get_logger("OrderInterceptionLayer")


@dataclass
class InterceptedOrderMetadata:
    """Metadata attached to intercepted order.
    
    Attributes:
        is_profit_constrained: Whether order has profit constraints
        execution_targets: List of ExecutionTarget for lot-based execution
        min_profitable_price: Minimum price for profitability
        strategy_mode: 'ADVISORY' or 'ENFORCING'
        position_analysis: Details about position and lots
    """
    is_profit_constrained: bool = False
    execution_targets: List[ExecutionTarget] = None
    min_profitable_price: Optional[float] = None
    strategy_mode: str = 'ADVISORY'
    position_analysis: Optional[Dict] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for storage."""
        return {
            'is_profit_constrained': self.is_profit_constrained,
            'execution_targets': [t.to_dict() for t in (self.execution_targets or [])],
            'min_profitable_price': self.min_profitable_price,
            'strategy_mode': self.strategy_mode,
            'position_analysis': self.position_analysis
        }


class OrderInterceptionLayer:
    """Intercepts orders to apply profit-aware constraints.
    
    This layer sits between order creation and market submission,
    enriching orders with position-based profit constraints.
    """
    
    def __init__(self,
                 fill_ledger_repo: FillLedgerRepository,
                 profit_margin_pct: float = 0.5,
                 strategy_mode: str = 'ADVISORY'):
        """Initialize interception layer.
        
        Args:
            fill_ledger_repo: Repository for fill data
            profit_margin_pct: Default profit margin percentage
            strategy_mode: 'ADVISORY' (log but allow) or 'ENFORCING' (block if unprofitable)
        """
        self.fill_ledger_repo = fill_ledger_repo
        self.lot_builder = PositionLotBuilder(fill_ledger_repo)
        self.threshold_engine = ProfitThresholdEngine(profit_margin_pct)
        self.strategy_mode = strategy_mode
        self.profit_margin_pct = profit_margin_pct
    
    def intercept_order(self,
                       product_id: str,
                       side: OrderSide,
                       size: float,
                       price: Optional[float] = None,
                       market_price: Optional[float] = None) -> Tuple[Dict, InterceptedOrderMetadata]:
        """Intercept an order and apply profit constraints.
        
        Args:
            product_id: Product to trade (e.g., 'BTC-USDC')
            side: BUY or SELL
            size: Order quantity
            price: Limit price (if specified)
            market_price: Current market price for validation
        
        Returns:
            Tuple of (enriched_order_dict, metadata)
        """
        metadata = InterceptedOrderMetadata()
        
        # Check if this is an exit order (opposite of position)
        position = self.lot_builder.build_position_by_product(
            product_id,
            side=None,  # Get all sides first
            profit_target_pct=self.profit_margin_pct
        )
        
        if not position.get_unexited_lots():
            # No position to exit - just pass through
            logger.debug(f"Order {side} {size} {product_id}: No position, passing through")
            return ({'product_id': product_id, 'side': side.name, 'size': size, 'price': price}, metadata)
        
        # Determine if this is an exit order
        position_side = position.get_unexited_lots()[0].side if position.get_unexited_lots() else None
        is_exit_order = (side != position_side)
        
        if not is_exit_order:
            # Adding to position, not profit-constrained
            logger.debug(f"Order {side} {size} {product_id}: Adding to position, passing through")
            return ({'product_id': product_id, 'side': side.name, 'size': size, 'price': price}, metadata)
        
        # This is an exit order - apply profit constraints
        logger.info(f"Order {side} {size} {product_id}: Exit order detected, applying constraints")
        
        # Use market price if available, otherwise use limit price
        check_price = market_price or price
        if check_price is None:
            logger.warning(f"No price provided for profit check, defaulting to advisory mode")
        
        # Compute execution targets
        targets, target_meta = self.threshold_engine.compute_execution_targets(
            position=position,
            exit_quantity=size,
            market_price=check_price or 0.0,
            strategy='FIFO'
        )
        
        if not targets:
            logger.warning(f"Order {side} {size} {product_id}: {target_meta.get('message', 'Unknown error')}")
            metadata.position_analysis = target_meta
            return ({'product_id': product_id, 'side': side.name, 'size': size, 'price': price}, metadata)
        
        # Build execution targets
        metadata.is_profit_constrained = True
        metadata.execution_targets = targets
        metadata.strategy_mode = self.strategy_mode
        metadata.position_analysis = {
            'position_lots': len(position.lots),
            'total_quantity': position.total_quantity,
            'remaining_quantity': position.remaining_quantity,
            'average_entry_price': position.average_entry_price,
            'exit_targets': len(targets)
        }
        
        # Set minimum profitable price from targets
        if targets:
            if side == OrderSide.SELL:
                # For sells, must be above highest min price
                metadata.min_profitable_price = max(t.min_profitable_price for t in targets)
            else:
                # For buys, must be below lowest min price
                metadata.min_profitable_price = min(t.min_profitable_price for t in targets)
        
        # Check if order is profitable at proposed price
        is_profitable = True
        if price is not None and metadata.min_profitable_price is not None:
            if side == OrderSide.SELL:
                is_profitable = price >= metadata.min_profitable_price
            else:
                is_profitable = price <= metadata.min_profitable_price
        
        if not is_profitable:
            msg = (f"Order {side} {size} @ {price} is not profitable. "
                  f"Min profitable: {metadata.min_profitable_price}. "
                  f"Strategy mode: {self.strategy_mode}")
            logger.warning(msg)
            
            if self.strategy_mode == 'ENFORCING':
                # Block unprofitable orders
                metadata.position_analysis['blocked'] = True
                metadata.position_analysis['block_reason'] = msg
                return ({'error': msg}, metadata)
        
        # Enrich order with metadata
        enriched_order = {
            'product_id': product_id,
            'side': side.name,
            'size': size,
            'price': price,
            'profit_aware_metadata': metadata.to_dict()
        }
        
        logger.info(f"Order enriched with profit constraints: "
                   f"{len(targets)} targets, min_price: {metadata.min_profitable_price}")
        
        return (enriched_order, metadata)
    
    def can_execute_at_price(self,
                            product_id: str,
                            side: OrderSide,
                            size: float,
                            execution_price: float) -> Tuple[bool, Optional[str]]:
        """Check if an order can execute profitably at given price.
        
        Args:
            product_id: Product to trade
            side: BUY or SELL
            size: Order quantity
            execution_price: Proposed execution price
        
        Returns:
            Tuple of (can_execute, reason)
        """
        # Build position
        position = self.lot_builder.build_position_by_product(
            product_id,
            side=None,
            profit_target_pct=self.profit_margin_pct
        )
        
        if not position.get_unexited_lots():
            return (True, "No position to constrain execution")
        
        # Get targets
        targets, _ = self.threshold_engine.compute_execution_targets(
            position=position,
            exit_quantity=size,
            market_price=execution_price,
            strategy='FIFO'
        )
        
        if not targets:
            return (False, "No execution targets available")
        
        # Validate all targets
        can_execute = True
        reason = None
        
        for target in targets:
            # Get the lot
            lot = next((l for l in position.lots if l.lot_id == target.lot_id), None)
            if not lot:
                continue
            
            is_profitable, msg = self.threshold_engine.validate_execution_price(lot, execution_price)
            if not is_profitable:
                can_execute = False
                reason = msg
                break
        
        return (can_execute, reason)
