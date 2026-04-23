"""
Profit Threshold Engine - Computes minimum profitable execution levels per lot.

This engine takes position lots and market conditions and computes:
1. Minimum exit price per lot (based on entry + fees + target margin)
2. Eligible quantity for exit at current price
3. Execution constraints (price levels, qty distributions)

The engine is stateless and computes thresholds on-demand, enabling
easy strategy customization without changing core execution logic.

Profit Formula:
For BUY lots:
  min_exit_price = (entry_price + fees/qty) * (1 + profit_margin%)

For SELL lots:
  min_exit_price = (entry_price - fees/qty) * (1 - profit_margin%)
"""

from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from business.position_lot import PositionLot, Position
from core.enums import OrderSide
from logging_service import get_logger

logger = get_logger("ProfitThresholdEngine")


@dataclass
class ExecutionTarget:
    """Target for an execution order.
    
    Attributes:
        lot_id: Which lot to exit
        quantity: Amount to exit
        min_profitable_price: Minimum price for profitability
        recommended_price: Recommended execution price
        side: BUY or SELL (inverse of lot side)
        reason: Why this target was selected
    """
    lot_id: str
    quantity: float
    min_profitable_price: float
    recommended_price: Optional[float] = None
    side: Optional[OrderSide] = None
    reason: str = "Profit-aware execution"
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            'lot_id': self.lot_id,
            'quantity': self.quantity,
            'min_profitable_price': self.min_profitable_price,
            'recommended_price': self.recommended_price,
            'side': self.side.name if self.side else None,
            'reason': self.reason
        }


class ProfitThresholdEngine:
    """Computes profit-aware execution constraints per lot.
    
    Given a position with lots and a user's exit order, this engine:
    1. Selects which lots to exit (FIFO by default)
    2. Computes minimum profitable prices
    3. Returns execution constraints for the order engine
    """
    
    def __init__(self, profit_margin_pct: float = 0.5):
        """Initialize engine with default profit margin.
        
        Args:
            profit_margin_pct: Default profit margin (e.g., 0.5 for 0.5%)
        """
        self.profit_margin_pct = profit_margin_pct
    
    def compute_execution_targets(self,
                                  position: Position,
                                  exit_quantity: float,
                                  market_price: float,
                                  strategy: str = 'FIFO') -> Tuple[List[ExecutionTarget], Dict]:
        """Compute execution targets for an exit order.
        
        Given a position and desired exit quantity, selects lots to exit
        and computes minimum profitable prices for each.
        
        Args:
            position: Position with lots to exit from
            exit_quantity: Total quantity to exit
            market_price: Current market price (for price checks)
            strategy: Lot selection strategy ('FIFO', 'LIFO', 'BEST_PROFIT')
        
        Returns:
            Tuple of (execution_targets, metadata)
        """
        if not position.get_unexited_lots():
            return ([], {
                'status': 'NO_LOTS',
                'message': 'No unexited lots in position'
            })
        
        # Select lots based on strategy
        selected_lots = self._select_lots(position, exit_quantity, strategy)
        
        if not selected_lots:
            return ([], {
                'status': 'INSUFFICIENT_QUANTITY',
                'message': f'Position has {position.remaining_quantity}, need {exit_quantity}'
            })
        
        # Create execution targets
        targets = []
        total_qty = 0
        
        for lot, qty_for_lot in selected_lots:
            # Determine opposite side for exit
            exit_side = OrderSide.SELL if lot.side == OrderSide.BUY else OrderSide.BUY
            
            # Check if profitable at current price
            is_profitable = lot.can_exit_profitably_at(market_price)
            
            target = ExecutionTarget(
                lot_id=lot.lot_id,
                quantity=qty_for_lot,
                min_profitable_price=lot.min_profitable_exit_price,
                recommended_price=market_price if is_profitable else None,
                side=exit_side,
                reason=f"Exit {qty_for_lot} from lot {lot.lot_id} "
                       f"(entry: {lot.entry_price}, min_profit: {lot.min_profitable_exit_price})"
            )
            
            targets.append(target)
            total_qty += qty_for_lot
        
        metadata = {
            'status': 'OK',
            'total_quantity': total_qty,
            'num_targets': len(targets),
            'market_price': market_price,
            'all_profitable': all(
                lot.can_exit_profitably_at(market_price) 
                for lot, _ in selected_lots
            )
        }
        
        logger.info(f"Execution targets computed: {len(targets)} targets, "
                   f"{total_qty} qty, profitable: {metadata['all_profitable']}")
        
        return (targets, metadata)
    
    def _select_lots(self, 
                    position: Position, 
                    exit_quantity: float,
                    strategy: str = 'FIFO') -> List[Tuple[PositionLot, float]]:
        """Select lots to exit based on strategy.
        
        Args:
            position: Position with lots
            exit_quantity: Total quantity to exit
            strategy: Selection strategy
        
        Returns:
            List of (lot, quantity_for_lot) tuples
        """
        unexited_lots = position.get_unexited_lots()
        
        if not unexited_lots:
            return []
        
        if strategy == 'FIFO':
            # Select oldest lots first
            sorted_lots = sorted(unexited_lots, key=lambda l: l.entry_timestamp)
        elif strategy == 'LIFO':
            # Select newest lots first
            sorted_lots = sorted(unexited_lots, key=lambda l: l.entry_timestamp, reverse=True)
        elif strategy == 'BEST_PROFIT':
            # Select lots with highest profit margin first
            sorted_lots = sorted(unexited_lots, 
                               key=lambda l: abs(l.min_profitable_exit_price - l.entry_price),
                               reverse=True)
        else:
            sorted_lots = unexited_lots
        
        # Allocate quantity across selected lots
        selected = []
        remaining_qty = exit_quantity
        
        for lot in sorted_lots:
            if remaining_qty <= 0:
                break
            
            qty_for_lot = min(remaining_qty, lot.remaining_quantity)
            selected.append((lot, qty_for_lot))
            remaining_qty -= qty_for_lot
        
        return selected
    
    def validate_execution_price(self,
                                lot: PositionLot,
                                execution_price: float) -> Tuple[bool, Optional[str]]:
        """Validate if execution price is profitable for lot.
        
        Args:
            lot: PositionLot to validate
            execution_price: Proposed execution price
        
        Returns:
            Tuple of (is_profitable, message)
        """
        if lot.side == OrderSide.BUY:
            # For buy lots, must sell above min threshold
            is_profitable = execution_price >= lot.min_profitable_exit_price
            if not is_profitable:
                msg = (f"SELL price {execution_price} < min profitable "
                      f"{lot.min_profitable_exit_price}")
        else:
            # For sell lots, must buy below min threshold
            is_profitable = execution_price <= lot.min_profitable_exit_price
            if not is_profitable:
                msg = (f"BUY price {execution_price} > min profitable "
                      f"{lot.min_profitable_exit_price}")
        
        message = None if is_profitable else msg
        return (is_profitable, message)
    
    def get_price_range(self, position: Position) -> Dict:
        """Get the price range for fully profitable execution.
        
        Args:
            position: Position to analyze
        
        Returns:
            Dictionary with price range information
        """
        unexited_lots = position.get_unexited_lots()
        
        if not unexited_lots:
            return {
                'status': 'NO_LOTS',
                'min_price': None,
                'max_price': None
            }
        
        # For BUY lots (exit via SELL)
        buy_lots = [l for l in unexited_lots if l.side == OrderSide.BUY]
        sell_min_price = max(l.min_profitable_exit_price for l in buy_lots) if buy_lots else None
        
        # For SELL lots (exit via BUY)
        sell_lots = [l for l in unexited_lots if l.side == OrderSide.SELL]
        buy_max_price = min(l.min_profitable_exit_price for l in sell_lots) if sell_lots else None
        
        return {
            'status': 'OK',
            'for_sells': sell_min_price,  # Min price to exit BUY lots profitably
            'for_buys': buy_max_price,     # Max price to exit SELL lots profitably
            'buy_lots_count': len(buy_lots),
            'sell_lots_count': len(sell_lots)
        }
