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
    >>> from business.position_lot import PositionLot, LotPosition
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
    >>> position = LotPosition(instrument='BTC-USDC', lots=[lot])
    >>> position.total_quantity
    0.5

Example usage:
    >>> from business.position_lot import PositionLot, LotPosition
    >>> from core.enums import OrderSide
    >>> from datetime import datetime
    >>>
    >>> # Create a position lot
    >>> lot = PositionLot(
    ...     lot_id='lot-001',
    ...     instrument='BTC-USDC',
    ...     side=OrderSide.BUY,
    ...     quantity=0.5,
    ...     entry_price=42000.0,
    ...     entry_timestamp=datetime.utcnow(),
    ...     fees=2.0,
    ...     target_profit_percentage=0.5
    ... )
    >>>
    >>> # Create a position with the lot
    >>> position = LotPosition(instrument='BTC-USDC', lots=[lot])
    >>>
    >>> # Check if lot can be exited profitably
    >>> can_exit = lot.can_exit_profitably_at(42500.0)
    >>> print(can_exit)
    True
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

    This class represents a single lot of a position, which is a discrete
    quantity acquired at a specific entry price. It's immutable once created
    and tracks all relevant information for profit calculation and exit decisions.

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
        target_profit_amount: Target profit amount in quote currency
        min_profitable_exit_price: Minimum price needed to be profitable

        # Tracking
        partially_exited_quantity: How much has been sold/closed
        partially_exited_value: Total value received from partial exits
        remaining_quantity: Still available for exit
        source_fills: List of trade IDs that comprise this lot
        created_at: When the lot was created (default: current time)

    Example:
        >>> from business.position_lot import PositionLot
        >>> from core.enums import OrderSide
        >>> from datetime import datetime
        >>>
        >>> lot = PositionLot(
        ...     lot_id='lot-001',
        ...     instrument='BTC-USDC',
        ...     side=OrderSide.BUY,
        ...     quantity=0.5,
        ...     entry_price=42000.0,
        ...     entry_timestamp=datetime.utcnow(),
        ...     fees=2.0,
        ...     target_profit_percentage=0.5
        ... )
        >>> print(lot.entry_value)
        21000.0
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
        """Compute minimum profitable exit price based on fees and target profit.

        This method calculates the minimum price at which the lot can be exited
        profitably, taking into account both the entry fees and the target profit
        percentage. The calculation differs based on whether the lot is a BUY or SELL.

        For BUY lots:
        - Cost per unit = entry_price + (fees / quantity)
        - Profit target = cost per unit * (target_profit_percentage / 100)
        - Minimum exit price = cost per unit + profit target

        For SELL lots:
        - Proceeds per unit = entry_price - (fees / quantity)
        - Profit target = proceeds per unit * (target_profit_percentage / 100)
        - Minimum exit price = proceeds per unit - profit target

        Example:
            >>> lot = PositionLot(
            ...     lot_id='lot-001',
            ...     instrument='BTC-USDC',
            ...     side=OrderSide.BUY,
            ...     quantity=0.5,
            ...     entry_price=42000.0,
            ...     fees=2.0,
            ...     target_profit_percentage=0.5
            ... )
            >>> print(lot.min_profitable_exit_price)
        """
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

        This method allows updating the profit target for the lot, either as
        a percentage or as an absolute amount. After updating, it recomputes
        the minimum profitable exit price.

        Args:
            target_pct: Profit target as percentage (e.g., 0.5 for 0.5%)
            target_amt: Profit target as absolute amount

        Example:
            >>> lot = PositionLot(
            ...     lot_id='lot-001',
            ...     instrument='BTC-USDC',
            ...     side=OrderSide.BUY,
            ...     quantity=0.5,
            ...     entry_price=42000.0,
            ...     fees=2.0,
            ...     target_profit_percentage=0.5
            ... )
            >>> lot.set_profit_target(target_pct=1.0)  # Update to 1%
            >>> print(lot.target_profit_percentage)
            1.0
        """
        if target_pct is not None:
            self.target_profit_percentage = target_pct
        if target_amt is not None:
            self.target_profit_amount = target_amt
        
        self._compute_exit_threshold()
    
    def mark_partially_exited(self, exit_quantity: float, exit_price: float) -> float:
        """Record a partial exit from this lot.

        This method records a partial exit of the lot, updating the tracking
        information and returning the realized value from the exit.

        Args:
            exit_quantity: Amount exited
            exit_price: Price per unit at exit

        Returns:
            float: Realized value from this exit (exit_quantity * exit_price)

        Example:
            >>> lot = PositionLot(
            ...     lot_id='lot-001',
            ...     instrument='BTC-USDC',
            ...     side=OrderSide.BUY,
            ...     quantity=0.5,
            ...     entry_price=42000.0,
            ...     fees=2.0
            ... )
            >>> realized_value = lot.mark_partially_exited(0.2, 42500.0)
            >>> print(realized_value)
            8500.0
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

        This method determines whether exiting the lot at the given market price
        would result in a profitable transaction, taking into account the entry
        price, fees, and target profit.

        Args:
            market_price: Current market price

        Returns:
            bool: True if profitable, False otherwise

        Example:
            >>> lot = PositionLot(
            ...     lot_id='lot-001',
            ...     instrument='BTC-USDC',
            ...     side=OrderSide.BUY,
            ...     quantity=0.5,
            ...     entry_price=42000.0,
            ...     fees=2.0,
            ...     target_profit_percentage=0.5
            ... )
            >>> can_exit = lot.can_exit_profitably_at(42500.0)
            >>> print(can_exit)
            True
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
class LotPosition:
    """Aggregate position across all lots for an instrument.

    Distinct from ``core.models.Position`` (the API-response dataclass for
    futures contracts). This class represents the internal lot-tracking
    aggregate — a collection of ``PositionLot`` entries with FIFO
    accounting helpers. Renamed from ``Position`` on 2026-05-04 to remove
    the same-name collision that made stack traces and imports ambiguous.

    Attributes:
        instrument: Trading pair
        total_quantity: Sum of all lots
        lots: List of PositionLot objects
        average_entry_price: FIFO-weighted entry price

    Example:
        >>> from business.position_lot import PositionLot, LotPosition
        >>> from core.enums import OrderSide
        >>> from datetime import datetime
        >>>
        >>> # Create a position lot
        >>> lot = PositionLot(
        ...     lot_id='lot-001',
        ...     instrument='BTC-USDC',
        ...     side=OrderSide.BUY,
        ...     quantity=0.5,
        ...     entry_price=42000.0,
        ...     entry_timestamp=datetime.utcnow(),
        ...     fees=2.0
        ... )
        >>>
        >>> # Create a position with the lot
        >>> position = LotPosition(instrument='BTC-USDC', lots=[lot])
        >>> print(position.total_quantity)
        0.5
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
