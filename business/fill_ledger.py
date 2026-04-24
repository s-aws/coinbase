"""
Fill Ledger - Immutable record of all fills for lot tracking and position reconstruction.

This module maintains an append-only ledger of all fills, serving as the source of truth
for position lot derivation and profit target calculations.

The fill ledger enables:
- Reconstruction of position lots at any historical point
- Accurate fee tracking per lot
- P&L computation and reporting
- Audit trail for all fills

Architecture:
- FillLedger (dataclass): Immutable fill record
- FillLedgerRepository: Data access layer
- Database: fill_ledger table (append-only)

Example:
    >>> from business.fill_ledger import FillLedger, FillLedgerRepository
    >>> from core.constants import get_local_now
    >>>
    >>> repo = FillLedgerRepository(db_client)
    >>> fill = FillLedger(
    ...     trade_id='trade-001',
    ...     instrument='BTC-USDC',
    ...     side='BUY',
    ...     quantity=0.25,
    ...     price=42000.0,
    ...     timestamp=get_local_now(),
    ...     fees=1.25,
    ...     client_order_id='client-order-123',
    ... )
    >>> repo.append_fill(fill)
    True
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from datetime import datetime
from core.enums import OrderSide
from logging_service import get_logger

logger = get_logger("FillLedger")

# Import database functions
from database.order import create_fill_ledger_table


@dataclass
class FillLedger:
    """Immutable record of a single fill event.
    
    Attributes:
        trade_id: Unique identifier for this fill (UUID)
        instrument: Trading pair (e.g., 'BTC-USDC')
        side: BUY or SELL
        quantity: Amount filled
        price: Price per unit at fill
        timestamp: When the fill occurred (ISO format)
        fees: Total fees paid on this fill (optional)
        commission_percentage: Commission rate applied
        order_side: OrderSide enum for standardization
        client_order_id: Client order ID that generated this fill
        product_id: Product ID (may differ from instrument format)
        average_price: Average fill price (same as price for single fills)
    """
    
    trade_id: str  # Unique fill identifier
    instrument: str  # Trading pair
    side: str  # 'BUY' or 'SELL'
    quantity: float  # Amount filled
    price: float  # Fill price
    timestamp: datetime  # When fill occurred
    fees: float = 0.0  # Total fees on this fill
    commission_percentage: float = 0.0  # Commission rate
    order_side: Optional[OrderSide] = None
    client_order_id: Optional[str] = None  # Originating order
    product_id: Optional[str] = None
    average_price: Optional[float] = None
    
    # Metadata
    created_at: datetime = field(default_factory=lambda: datetime.utcnow())
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FillLedger':
        """Create FillLedger from dictionary (e.g., database row or API response)."""
        from calculation.formatter import safe_float
        from core.constants import get_local_now
        
        timestamp = data.get('timestamp')
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        elif timestamp is None:
            timestamp = get_local_now()
        
        side = data.get('side', '').upper()
        order_side = OrderSide.BUY if side == 'BUY' else OrderSide.SELL if side == 'SELL' else None
        
        return cls(
            trade_id=data.get('trade_id'),
            instrument=data.get('instrument', data.get('product_id')),
            side=side,
            quantity=safe_float(data.get('quantity'), 0.0),
            price=safe_float(data.get('price'), 0.0),
            timestamp=timestamp,
            fees=safe_float(data.get('fees'), 0.0),
            commission_percentage=safe_float(data.get('commission_percentage'), 0.0),
            order_side=order_side,
            client_order_id=data.get('client_order_id'),
            product_id=data.get('product_id'),
            average_price=safe_float(data.get('average_price'), None) or safe_float(data.get('price'), 0.0),
            created_at=timestamp if timestamp else get_local_now()
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database storage."""
        return {
            'trade_id': self.trade_id,
            'instrument': self.instrument,
            'side': self.side,
            'quantity': self.quantity,
            'price': self.price,
            'timestamp': self.timestamp.isoformat() if isinstance(self.timestamp, datetime) else self.timestamp,
            'fees': self.fees,
            'commission_percentage': self.commission_percentage,
            'order_side': self.order_side.name if self.order_side else self.side,
            'client_order_id': self.client_order_id,
            'product_id': self.product_id,
            'average_price': self.average_price,
            'created_at': self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at
        }


class FillLedgerRepository:
    """Repository for fill ledger operations - data access abstraction."""
    
    def __init__(self, db_client):
        """Initialize with database client.
        
        Args:
            db_client: PostgresDB instance for database operations
        """
        self.db_client = db_client
        self._ensure_table_exists()
    
    def _ensure_table_exists(self) -> None:
        """Ensure fill_ledger table exists by calling database function."""
        try:
            # Call database function to create table with proper schema
            create_fill_ledger_table()
            logger.info("Fill ledger table ready")
        except Exception as e:
            logger.error(f"Failed to create fill_ledger table: {type(e).__name__}: {e}")
    
    def append_fill(self, fill: FillLedger) -> bool:
        """Append a fill to the immutable ledger.
        
        Args:
            fill: FillLedger record to append
        
        Returns:
            True if successful, False otherwise
        """
        try:
            query = """
            INSERT INTO fill_ledger 
            (trade_id, instrument, side, quantity, price, timestamp, fees, 
             commission_percentage, client_order_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            params = (
                fill.trade_id,
                fill.instrument,
                fill.side,
                fill.quantity,
                fill.price,
                fill.timestamp,
                fill.fees,
                fill.commission_percentage,
                fill.client_order_id
            )
            
            rows_affected = self.db_client.execute_update(query, params)
            
            if rows_affected > 0:
                logger.info(f"[LOT-TRACK] Fill appended to ledger: trade_id={fill.trade_id}, instrument={fill.instrument}, {fill.side} {fill.quantity} @ {fill.price}, fees={fill.fees}")
                return True
            else:
                logger.warning(f"[LOT-TRACK] No rows inserted for fill {fill.trade_id}")
                return False
                
        except Exception as e:
            logger.error(f"✗ Error appending fill {fill.trade_id}: {type(e).__name__}: {e}")
            return False
    
    def get_fills_by_instrument(self, instrument: str) -> List[FillLedger]:
        """Get all fills for an instrument in chronological order.
        
        Args:
            instrument: Trading pair (e.g., 'BTC-USDC')
        
        Returns:
            List of FillLedger records ordered by timestamp
        """
        try:
            query = """
            SELECT * FROM fill_ledger
            WHERE instrument = %s
            ORDER BY timestamp ASC
            """
            
            results = self.db_client.execute_query(query, (instrument,))
            
            fills = []
            for row in results:
                fill = FillLedger.from_dict(row)
                fills.append(fill)
            
            if fills:
                logger.info(f"[LOT-TRACK] Retrieved {len(fills)} fills for {instrument}")
            return fills
            
        except Exception as e:
            logger.error(f"✗ Error fetching fills for {instrument}: {type(e).__name__}: {e}")
            return []
    
    def get_fills_by_product(self, product_id: str, side: Optional[str] = None) -> List[FillLedger]:
        """Get fills by product ID, optionally filtered by side.
        
        Args:
            product_id: Product ID (e.g., 'BTC-USDC')
            side: Optional side filter ('BUY' or 'SELL')
        
        Returns:
            List of FillLedger records ordered by timestamp
        """
        try:
            if side:
                query = """
                SELECT * FROM fill_ledger
                WHERE instrument = %s AND side = %s
                ORDER BY timestamp ASC
                """
                results = self.db_client.execute_query(query, (product_id, side.upper()))
            else:
                query = """
                SELECT * FROM fill_ledger
                WHERE instrument = %s
                ORDER BY timestamp ASC
                """
                results = self.db_client.execute_query(query, (product_id,))
            
            fills = [FillLedger.from_dict(row) for row in results]
            if fills:
                logger.info(f"[LOT-TRACK] Retrieved {len(fills)} fills for {product_id}")
            return fills
            
        except Exception as e:
            logger.error(f"[LOT-TRACK] Error fetching fills for {product_id}: {type(e).__name__}: {e}")
            return []
    
    def get_fill_by_trade_id(self, trade_id: str) -> Optional[FillLedger]:
        """Get a specific fill by trade ID.
        
        Args:
            trade_id: Unique fill identifier
        
        Returns:
            FillLedger record or None if not found
        """
        try:
            query = "SELECT * FROM fill_ledger WHERE trade_id = %s"
            results = self.db_client.execute_query(query, (trade_id,))
            
            if results:
                return FillLedger.from_dict(results[0])
            return None
            
        except Exception as e:
            logger.error(f"✗ Error fetching fill {trade_id}: {type(e).__name__}: {e}")
            return None
    
    def get_fills_by_order(self, client_order_id: str) -> List[FillLedger]:
        """Get all fills generated by a specific order.
        
        Args:
            client_order_id: Client order ID
        
        Returns:
            List of FillLedger records ordered by timestamp
        """
        try:
            query = """
            SELECT * FROM fill_ledger
            WHERE client_order_id = %s
            ORDER BY timestamp ASC
            """
            
            results = self.db_client.execute_query(query, (client_order_id,))
            fills = [FillLedger.from_dict(row) for row in results]
            
            return fills
            
        except Exception as e:
            logger.error(f"✗ Error fetching fills for order {client_order_id}: {type(e).__name__}: {e}")
            return []
    
    def get_fills_since(self, instrument: str, since: datetime) -> List[FillLedger]:
        """Get fills for an instrument since a specific time.
        
        Args:
            instrument: Trading pair
            since: Datetime to query from
        
        Returns:
            List of FillLedger records ordered by timestamp
        """
        try:
            query = """
            SELECT * FROM fill_ledger
            WHERE instrument = %s AND timestamp >= %s
            ORDER BY timestamp ASC
            """
            
            results = self.db_client.execute_query(query, (instrument, since))
            fills = [FillLedger.from_dict(row) for row in results]
            
            return fills
            
        except Exception as e:
            logger.error(f"✗ Error fetching fills since {since}: {type(e).__name__}: {e}")
            return []
