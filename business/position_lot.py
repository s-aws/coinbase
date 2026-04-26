"""
Position Lot Models - Derived position tracking from fill ledger.

A position lot represents a discrete quantity acquired at a specific entry price.
Lots are derived from the immutable fill ledger and are grouped by entry price,
instrument, and direction.

Design:
- PositionLot: Immutable record of a lot once created
- PositionLotBuilder: Service that constructs lots from fill ledger
- LotSelectionStrategy: Configurable strategy for selecting lots for exit

The lot builder maintains the single source of truth by deriving all lots
from the fill ledger, enabling reconstruction at any historical point.

Example:
    >>> from datetime import datetime
    >>> from business.position_lot import PositionLot, Position
    >>> from core.enums import OrderSide
    >>>
    >>> lot = PositionLot(
    ...     lot_id='lot-001',
    ...     instrument='BTC-USDC',
    ...     side=OrderSide.BUY,
    ...     quantity=0.5,
    ...     entry_price=42000.0,
    ...     entry_timestamp=datetime.utcnow(),
    ...     fees=2.0,
    ...     target_profit_percentage=0.5,
    ... )
    >>> position = Position(instrument='BTC-USDC', lots=[lot])
    >>> position.total_quantity
    0.5
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set
from datetime import datetime
from core.enums import OrderSide
from business.fill_ledger import FillLedger
from logging_service import get_logger

logger = get_logger("PositionLot")


@dataclass
class PositionLot:
    """Immutable position lot - a discrete quantity at a specific entry price.
    
    Attributes:
        lot_id: Unique identifier for this lot (UUID or derived)
        instrument: Trading pair (e.g., 'BTC-USDC')
        side: BUY or SELL (direction of the position)
        quantity: Amount in this lot
        entry_price: Price per unit when acquired
        entry_timestamp: When this lot was first created
        fees: Total fees paid to acquire this lot
        entry_value: Total value = quantity * entry_price
        
        # Profit tracking
        target_profit_percentage: Target profit margin for this lot (%)
        min_profitable_exit_price: Minimum price needed to be profitable
        min_profitable_exit_amount: Minimum price in absolute terms
        
        # Tracking
        partially_exited_quantity: How much has been sold/closed
        partially_exited_value: Total value received from partial exits
        remaining_quantity: Still available for exit
    """
    
    lot_id: str  # Unique identifier
    instrument: str  # Trading pair
    side: OrderSide  # BUY or SELL (acquisition direction)
    quantity: float  # Total size of lot
    entry_price: float  # Average entry price
    entry_timestamp: datetime  # When acquired
    fees: float = 0.0  # Total fees to acquire
    
    # Calculated values
    entry_value: float = 0.0  # quantity * entry_price
    
    # Profit configuration
    target_profit_percentage: float = 0.5  # 0.5% default
    target_profit_amount: float = 0.0  # Absolute profit target
    min_profitable_exit_price: float = 0.0  # Computed threshold
    
    # Exit tracking
    partially_exited_quantity: float = 0.0
    partially_exited_value: float = 0.0
    remaining_quantity: float = 0.0
    
    # Metadata
    source_fills: List[str] = field(default_factory=list)  # trade_ids that comprise this lot
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        """Compute derived fields after initialization."""
        if self.entry_value == 0.0:
            self.entry_value = self.quantity * self.entry_price
        
        if self.remaining_quantity == 0.0:
            self.remaining_quantity = self.quantity - self.partially_exited_quantity
        
        # Compute minimum profitable exit price
        self._compute_exit_threshold()
    
    def _compute_exit_threshold(self) -> None:
        """Compute minimum profitable exit price based on fees and target profit."""
        if self.side == OrderSide.BUY:
            # For buys: exit_price = (entry_price + fees/quantity) * (1 + profit_pct)
            cost_per_unit = self.entry_price + (self.fees / self.quantity if self.quantity > 0 else 0)
            profit_target = cost_per_unit * (self.target_profit_percentage / 100.0)
            self.min_profitable_exit_price = cost_per_unit + profit_target
            
        elif self.side == OrderSide.SELL:
            # For sells: exit_price = (entry_price - fees/quantity) * (1 - profit_pct)
            proceeds_per_unit = self.entry_price - (self.fees / self.quantity if self.quantity > 0 else 0)
            profit_target = proceeds_per_unit * (self.target_profit_percentage / 100.0)
            self.min_profitable_exit_price = proceeds_per_unit - profit_target
    
    def set_profit_target(self, target_pct: Optional[float] = None, target_amt: Optional[float] = None) -> None:
        """Update profit target and recompute exit threshold.
        
        Args:
            target_pct: Profit target as percentage (e.g., 0.5 for 0.5%)
            target_amt: Profit target as absolute amount
        """
        if target_pct is not None:
            self.target_profit_percentage = target_pct
        if target_amt is not None:
            self.target_profit_amount = target_amt
        
        self._compute_exit_threshold()
    
    def mark_partially_exited(self, exit_quantity: float, exit_price: float) -> float:
        """Record a partial exit from this lot.
        
        Args:
            exit_quantity: Amount exited
            exit_price: Price per unit at exit
        
        Returns:
            Realized value from this exit
        """
        exit_value = exit_quantity * exit_price
        self.partially_exited_quantity += exit_quantity
        self.partially_exited_value += exit_value
        self.remaining_quantity = self.quantity - self.partially_exited_quantity
        
        logger.info(f"Lot {self.lot_id}: Exited {exit_quantity} @ {exit_price}, "
                   f"remaining: {self.remaining_quantity}")
        
        return exit_value
    
    def is_fully_exited(self) -> bool:
        """Check if this lot has been completely closed."""
        return self.remaining_quantity <= 0.0
    
    def can_exit_profitably_at(self, market_price: float) -> bool:
        """Check if lot can exit profitably at given market price.
        
        Args:
            market_price: Current market price
        
        Returns:
            True if profitable, False otherwise
        """
        if self.side == OrderSide.BUY:
            return market_price >= self.min_profitable_exit_price
        else:  # SELL
            return market_price <= self.min_profitable_exit_price
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            'lot_id': self.lot_id,
            'instrument': self.instrument,
            'side': self.side.name,
            'quantity': self.quantity,
            'entry_price': self.entry_price,
            'entry_timestamp': self.entry_timestamp.isoformat(),
            'fees': self.fees,
            'entry_value': self.entry_value,
            'target_profit_percentage': self.target_profit_percentage,
            'min_profitable_exit_price': self.min_profitable_exit_price,
            'partially_exited_quantity': self.partially_exited_quantity,
            'remaining_quantity': self.remaining_quantity,
            'source_fills': self.source_fills,
        }


@dataclass
class Position:
    """Aggregate position across all lots for an instrument.
    
    Attributes:
        instrument: Trading pair
        total_quantity: Sum of all lots
        lots: List of PositionLot objects
        average_entry_price: FIFO-weighted entry price
    """
    
    instrument: str
    lots: List[PositionLot] = field(default_factory=list)
    
    @property
    def total_quantity(self) -> float:
        """Total quantity across all lots."""
        return sum(lot.quantity for lot in self.lots)
    
    @property
    def remaining_quantity(self) -> float:
        """Remaining unexited quantity."""
        return sum(lot.remaining_quantity for lot in self.lots)
    
    @property
    def average_entry_price(self) -> float:
        """FIFO-weighted average entry price."""
        total_value = sum(lot.entry_value for lot in self.lots)
        total_qty = self.total_quantity
        return total_value / total_qty if total_qty > 0 else 0.0
    
    @property
    def total_fees(self) -> float:
        """Total fees across all lots."""
        return sum(lot.fees for lot in self.lots)
    
    def add_lot(self, lot: PositionLot) -> None:
        """Add a new lot to the position."""
        self.lots.append(lot)
        logger.info(f"Position {self.instrument}: Added lot {lot.lot_id} "
                   f"({lot.quantity} @ {lot.entry_price})")
    
    def get_profitable_lots_at_price(self, market_price: float) -> List[PositionLot]:
        """Get all lots that can exit profitably at market price.
        
        Args:
            market_price: Current market price
        
        Returns:
            List of lots that satisfy profit threshold
        """
        return [lot for lot in self.lots 
                if lot.remaining_quantity > 0 and lot.can_exit_profitably_at(market_price)]
    
    def get_unexited_lots(self) -> List[PositionLot]:
        """Get all lots with remaining quantity."""
        return [lot for lot in self.lots if lot.remaining_quantity > 0]
