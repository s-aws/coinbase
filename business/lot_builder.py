"""
Position Lot Builder - Derives position lots from immutable fill ledger.

This service maintains the mapping between fills and position lots, enabling:
1. FIFO lot construction (standard accounting)
2. Lot history reconstruction at any point
3. Profit threshold computation per lot

Design Pattern:
- Immutable source: fill_ledger table (append-only)
- Derived state: position_lots (cached, can be regenerated)
- Service: PositionLotBuilder (stateless, query-based)

The lot builder is stateless - it derives lots from the fill ledger
on demand, ensuring consistency without maintaining separate state.

Example:
    >>> from business.fill_ledger import FillLedgerRepository
    >>> from business.lot_builder import PositionLotBuilder
    >>>
    >>> repo = FillLedgerRepository(db_client)
    >>> builder = PositionLotBuilder(repo)
    >>> position = builder.build_position_by_product('BTC-USDC', profit_target_pct=0.5)
    >>> position.instrument
    'BTC-USDC'
"""

from typing import List, Dict, Optional
from datetime import datetime
import uuid
from business.fill_ledger import FillLedger, FillLedgerRepository
from business.position_lot import PositionLot, Position
from core.enums import OrderSide
from logging_service import get_logger

logger = get_logger("PositionLotBuilder")


class PositionLotBuilder:
    """Builds position lots from immutable fill ledger.
    
    Processes fill events chronologically to construct position lots using
    the FIFO (First-In-First-Out) accounting method. The builder is stateless
    and derives lots on-demand from the database.
    """
    
    def __init__(self, fill_ledger_repo: FillLedgerRepository):
        """Initialize lot builder.
        
        Args:
            fill_ledger_repo: FillLedgerRepository for accessing fills
        """
        self.fill_ledger_repo = fill_ledger_repo
    
    def build_position_lots(self, 
                           instrument: str, 
                           side: Optional[OrderSide] = None,
                           profit_target_pct: float = 0.5) -> Position:
        """Build position lots for an instrument from its fill history.
        
        Uses FIFO accounting: fills are grouped chronologically by entry price.
        Each group with the same entry price becomes one lot.
        
        Args:
            instrument: Trading pair (e.g., 'BTC-USDC')
            side: Optional side filter (BUY/SELL) - if None, gets all fills
            profit_target_pct: Target profit margin in percentage
        
        Returns:
            Position object with derived lots
        """
        # Get fills for the instrument
        fills = self.fill_ledger_repo.get_fills_by_instrument(instrument)
        
        if side:
            fills = [f for f in fills if OrderSide[f.side.upper()] == side]
        
        if not fills:
            logger.info(f"No fills found for {instrument}")
            return Position(instrument=instrument)
        
        # Group fills by side and entry price to create lots (FIFO)
        position = Position(instrument=instrument)
        lots_dict: Dict[str, PositionLot] = {}  # key: (side, price) -> lot
        
        for fill in fills:
            lot_key = self._get_lot_key(fill)
            
            if lot_key not in lots_dict:
                # Create new lot
                lot = self._create_lot_from_fill(
                    fill, 
                    lots_dict, 
                    profit_target_pct
                )
                lots_dict[lot_key] = lot
                position.add_lot(lot)
                
                logger.debug(f"Created lot {lot.lot_id}: {fill.side} {fill.quantity} @ {fill.price}")
            else:
                # Add fill to existing lot (same side, same price)
                lot = lots_dict[lot_key]
                lot.quantity += fill.quantity
                lot.entry_value = lot.quantity * lot.entry_price
                lot.fees += fill.fees
                lot.source_fills.append(fill.trade_id)
                
                logger.debug(f"Extended lot {lot.lot_id}: now {lot.quantity} total")
        
        logger.info(f"Built position for {instrument}: {len(position.lots)} lots, "
                   f"total {position.total_quantity}")
        
        return position
    
    def _get_lot_key(self, fill: FillLedger) -> str:
        """Get the lot grouping key for a fill (side + price).
        
        Fills with the same side and price are grouped into the same lot.
        
        Args:
            fill: FillLedger record
        
        Returns:
            Lot key for grouping
        """
        return f"{fill.side}:{fill.price}"
    
    def _create_lot_from_fill(self, 
                             fill: FillLedger, 
                             existing_lots: Dict,
                             profit_target_pct: float) -> PositionLot:
        """Create a new PositionLot from initial fill.
        
        Args:
            fill: FillLedger record
            existing_lots: Already-created lots (for validation)
            profit_target_pct: Target profit percentage
        
        Returns:
            New PositionLot object
        """
        lot_id = str(uuid.uuid4())
        
        lot = PositionLot(
            lot_id=lot_id,
            instrument=fill.instrument,
            side=OrderSide[fill.side.upper()],
            quantity=fill.quantity,
            entry_price=fill.price,
            entry_timestamp=fill.timestamp,
            fees=fill.fees,
            target_profit_percentage=profit_target_pct,
            source_fills=[fill.trade_id]
        )
        
        # Compute entry value and profit threshold
        lot.entry_value = lot.quantity * lot.entry_price
        lot._compute_exit_threshold()
        lot.remaining_quantity = lot.quantity
        
        return lot
    
    def build_position_by_product(self,
                                  product_id: str,
                                  side: Optional[OrderSide] = None,
                                  profit_target_pct: float = 0.5) -> Position:
        """Build position lots filtered by product ID and optional side.
        
        Args:
            product_id: Product ID (e.g., 'BTC-USDC')
            side: Optional side filter (BUY/SELL)
            profit_target_pct: Target profit percentage
        
        Returns:
            Position object with derived lots
        """
        fills = self.fill_ledger_repo.get_fills_by_product(product_id, 
                                                           side.name if side else None)
        
        if not fills:
            # Infer instrument from product_id
            instrument = product_id
            logger.info(f"No fills found for {product_id}")
            return Position(instrument=instrument)
        
        # Build position using the fill list
        position = Position(instrument=fills[0].instrument if fills else product_id)
        lots_dict: Dict[str, PositionLot] = {}
        
        for fill in fills:
            lot_key = self._get_lot_key(fill)
            
            if lot_key not in lots_dict:
                lot = self._create_lot_from_fill(fill, lots_dict, profit_target_pct)
                lots_dict[lot_key] = lot
                position.add_lot(lot)
            else:
                lot = lots_dict[lot_key]
                lot.quantity += fill.quantity
                lot.entry_value = lot.quantity * lot.entry_price
                lot.fees += fill.fees
                lot.source_fills.append(fill.trade_id)
        
        return position
    
    def get_profitable_exit_strategy(self,
                                    position: Position,
                                    market_price: float) -> Dict:
        """Analyze position and return profitable exit strategy.
        
        Given current market price and position lots, determine:
        1. Which lots can exit profitably
        2. What quantity can exit
        3. What prices are needed
        
        Args:
            position: Position with lots
            market_price: Current market price
        
        Returns:
            Dictionary with exit strategy details
        """
        profitable_lots = position.get_profitable_lots_at_price(market_price)
        
        if not profitable_lots:
            return {
                'can_exit_profitably': False,
                'profitable_lots': [],
                'message': f'No lots can exit profitably at {market_price}'
            }
        
        total_profitable_qty = sum(lot.remaining_quantity for lot in profitable_lots)
        
        return {
            'can_exit_profitably': True,
            'profitable_lots': [lot.to_dict() for lot in profitable_lots],
            'total_profitable_quantity': total_profitable_qty,
            'market_price': market_price,
            'threshold_prices': [lot.min_profitable_exit_price for lot in profitable_lots]
        }
