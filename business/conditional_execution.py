"""
Conditional Execution Wrapper - Wraps orders with trigger conditions.

This module implements the actual conditional order execution logic that gates
orders based on computed profit thresholds. Orders remain dormant until market
conditions allow profitable execution.

Design:
- Database-backed: Stores conditional orders in PostgreSQL for recovery on restart
- Async evaluation: 100ms loop checks conditions (matches existing stealth order pattern)
- Non-invasive: Orders are wrapped, not replaced
- Recoverable: Conditional orders survive engine restarts

This follows the same pattern as stealth orders but for profit constraints.

Example:
    >>> from business.conditional_execution import ConditionalExecutionWrapper
    >>> from business.order_interception_layer import OrderInterceptionLayer
    >>> from business.fill_ledger import FillLedgerRepository
    >>> from core.enums import OrderSide
    >>>
    >>> fill_repo = FillLedgerRepository(db_client)
    >>> layer = OrderInterceptionLayer(fill_repo, profit_margin_pct=0.5)
    >>> wrapper = ConditionalExecutionWrapper(layer, db_client=db_client)
    >>>
    >>> conditional = wrapper.wrap_with_profit_condition(
    ...     product_id='BTC-USDC',
    ...     side=OrderSide.SELL,
    ...     size=0.1,
    ...     price=43000.0,
    ...     min_profitable_price=42950.0,
    ...     base_order_id='client-order-123',
    ...     notes='Wait for profitable exit'
    ... )
    >>> conditional is not None
    True
"""

from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import uuid
from business.order_interception_layer import OrderInterceptionLayer
from business.position_lot import PositionLot
from core.enums import OrderSide
from logging_service import get_logger

logger = get_logger("ConditionalExecutionWrapper")

# Import database functions
from database.order import (
    create_conditional_orders_table,
    insert_conditional_order,
    get_conditional_order,
    get_awaiting_conditional_orders,
    update_conditional_order_status,
    mark_conditional_submitted,
    mark_conditional_filled,
    cancel_conditional_order
)


class ConditionalOrderStatus(Enum):
    """Status of a conditional order."""
    AWAITING_CONDITION = "AWAITING_CONDITION"  # Waiting for condition
    CONDITION_MET = "CONDITION_MET"             # Ready to submit
    SUBMITTED = "SUBMITTED"                      # Submitted to exchange
    FILLED = "FILLED"                            # Execution completed
    CANCELLED = "CANCELLED"                      # User cancelled
    EXPIRED = "EXPIRED"                          # Time-based expiration
    FAILED = "FAILED"                            # Submission failed


@dataclass
class ConditionalOrder:
    """Conditional order - wraps an order with execution trigger.
    
    Attributes:
        conditional_order_id: Unique ID for this conditional wrapper
        base_order_id: Original order client_order_id (if known)
        product_id: Trading pair
        side: BUY or SELL
        size: Order quantity
        price: Limit price
        min_profitable_price: Threshold that must be met
        status: Current status
        created_at: When created
        submitted_at: When condition was met and submitted
        filled_at: When execution completed
        execution_price: Actual fill price (if filled)
        notes: Human-readable trigger description
    """
    conditional_order_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    base_order_id: Optional[str] = None
    product_id: str = ""
    side: OrderSide = OrderSide.BUY
    size: float = 0.0
    price: Optional[float] = None
    min_profitable_price: float = 0.0
    status: ConditionalOrderStatus = ConditionalOrderStatus.AWAITING_CONDITION
    created_at: datetime = field(default_factory=datetime.utcnow)
    submitted_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None
    execution_price: Optional[float] = None
    notes: str = "Awaiting profitable execution price"
    
    # Tracking
    is_active: bool = True
    expiration_time: Optional[datetime] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            'conditional_order_id': self.conditional_order_id,
            'base_order_id': self.base_order_id,
            'product_id': self.product_id,
            'side': self.side.name,
            'size': self.size,
            'price': self.price,
            'min_profitable_price': self.min_profitable_price,
            'status': self.status.value,
            'created_at': self.created_at.isoformat(),
            'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None,
            'filled_at': self.filled_at.isoformat() if self.filled_at else None,
            'execution_price': self.execution_price,
            'notes': self.notes,
            'is_active': self.is_active,
            'expiration_time': self.expiration_time.isoformat() if self.expiration_time else None
        }


class ConditionalExecutionWrapper:
    """Manages conditional order execution lifecycle with database persistence.
    
    Wraps orders with profit thresholds and evaluates them against
    market conditions. Orders only submit when profitable.
    
    Conditional orders are persisted in PostgreSQL for recovery on restart.
    """
    
    def __init__(self,
                 order_interception_layer: OrderInterceptionLayer,
                 db_client=None,
                 max_queue_size: int = 1000):
        """Initialize wrapper.
        
        Args:
            order_interception_layer: Layer for profit constraint validation
            db_client: Database client for persistence (optional)
            max_queue_size: Maximum conditional orders to track
        """
        self.interception_layer = order_interception_layer
        self.db_client = db_client
        self.max_queue_size = max_queue_size
        
        # In-memory cache of conditional orders (for fast lookup)
        self.conditional_orders: Dict[str, ConditionalOrder] = {}
        
        # Initialize database table if db_client provided
        if self.db_client:
            try:
                create_conditional_orders_table()
                logger.info("Conditional orders table ready")
                # Load existing conditional orders from database
                self._load_from_database()
            except Exception as e:
                logger.error(f"Failed to initialize conditional orders table: {type(e).__name__}: {e}")
        
        logger.info(f"Conditional execution wrapper initialized (persistence: {'enabled' if self.db_client else 'disabled'})")
    
    def _load_from_database(self) -> None:
        """Load existing conditional orders from database on startup.
        
        Recovers all awaiting conditional orders after engine restart.
        """
        try:
            if not self.db_client:
                return
            
            # Get all awaiting conditional orders from database
            awaiting_db = get_awaiting_conditional_orders()
            
            if awaiting_db:
                logger.info(f"[LOT-TRACK] Recovering {len(awaiting_db)} awaiting conditional orders from database")
                
                for row in awaiting_db:
                    # Reconstruct ConditionalOrder from database row
                    cond_order = ConditionalOrder(
                        conditional_order_id=row.get('conditional_order_id'),
                        base_order_id=row.get('base_order_id'),
                        product_id=row.get('product_id'),
                        side=OrderSide.BUY if row.get('side') == 'BUY' else OrderSide.SELL,
                        size=float(row.get('size', 0.0)),
                        price=float(row.get('price')) if row.get('price') else None,
                        min_profitable_price=float(row.get('min_profitable_price', 0.0)),
                        status=ConditionalOrderStatus(row.get('status', 'AWAITING_CONDITION')),
                        created_at=row.get('created_at') if isinstance(row.get('created_at'), datetime) else datetime.fromisoformat(str(row.get('created_at', ''))),
                        submitted_at=row.get('submitted_at') if isinstance(row.get('submitted_at'), datetime) else (datetime.fromisoformat(str(row.get('submitted_at'))) if row.get('submitted_at') else None),
                        filled_at=row.get('filled_at') if isinstance(row.get('filled_at'), datetime) else (datetime.fromisoformat(str(row.get('filled_at'))) if row.get('filled_at') else None),
                        execution_price=float(row.get('execution_price')) if row.get('execution_price') else None,
                        notes=row.get('notes', ''),
                        is_active=True
                    )
                    
                    # Store in memory cache
                    self.conditional_orders[cond_order.conditional_order_id] = cond_order
                    logger.info(f"[LOT-TRACK] Recovered conditional order {cond_order.conditional_order_id}: "
                               f"{cond_order.side.name} {cond_order.size} {cond_order.product_id} @ min_profit={cond_order.min_profitable_price}")
            else:
                logger.info("[LOT-TRACK] No conditional orders to recover from database")
                
        except Exception as e:
            logger.error(f"Error loading conditional orders from database: {type(e).__name__}: {e}")
    
    def wrap_with_profit_condition(self,
                                   product_id: str,
                                   side: OrderSide,
                                   size: float,
                                   price: Optional[float] = None,
                                   min_profitable_price: Optional[float] = None,
                                   base_order_id: Optional[str] = None,
                                   notes: str = "") -> Optional[ConditionalOrder]:
        """Wrap an order with profit condition.
        
        Args:
            product_id: Trading pair
            side: BUY or SELL
            size: Order quantity
            price: Limit price (if limit order)
            min_profitable_price: Threshold price
            base_order_id: Reference to order_parent.client_order_id (optional)
            notes: Description of why this condition exists
        
        Returns:
            ConditionalOrder ready for evaluation, or None if queue full
        """
        # Validate queue size
        if len(self.conditional_orders) >= self.max_queue_size:
            logger.error(f"Conditional order queue is full ({self.max_queue_size})")
            return None
        
        # Create conditional order
        conditional = ConditionalOrder(
            conditional_order_id=str(uuid.uuid4()),
            base_order_id=base_order_id,
            product_id=product_id,
            side=side,
            size=size,
            price=price,
            min_profitable_price=min_profitable_price or 0.0,
            notes=notes or f"Awaiting {side.name} @ {min_profitable_price}",
            status=ConditionalOrderStatus.AWAITING_CONDITION
        )
        
        # Store in memory cache
        self.conditional_orders[conditional.conditional_order_id] = conditional
        
        # Persist to database if available
        if self.db_client:
            try:
                db_id = insert_conditional_order(
                    conditional_order_id=conditional.conditional_order_id,
                    base_order_id=base_order_id,
                    product_id=product_id,
                    side=side.name,
                    size=size,
                    price=price or 0.0,
                    min_profitable_price=min_profitable_price or 0.0,
                    notes=notes
                )
                if db_id:
                    logger.info(f"[LOT-TRACK] Wrapped & persisted conditional order {conditional.conditional_order_id}: "
                               f"{side.name} {size} {product_id} @ min_profit={min_profitable_price} (base_order={base_order_id})")
                else:
                    logger.warning(f"[LOT-TRACK] Failed to persist conditional order {conditional.conditional_order_id}")
            except Exception as e:
                logger.error(f"[LOT-TRACK] Error persisting conditional order: {type(e).__name__}: {e}")
        else:
            logger.info(f"[LOT-TRACK] Wrapped order (in-memory only) {conditional.conditional_order_id}: "
                       f"{side.name} {size} {product_id} @ min_profit={min_profitable_price}")
        
        return conditional
    
    def evaluate_condition(self, market_price: float, product_id: str) -> List[ConditionalOrder]:
        """Evaluate all conditional orders for a product.
        
        Checks if market conditions allow order execution.
        
        Args:
            market_price: Current market price
            product_id: Product to evaluate
        
        Returns:
            List of orders ready for submission
        """
        ready_to_submit = []
        
        # Query awaiting orders from database if available, otherwise use memory cache
        if self.db_client:
            try:
                awaiting_db = get_awaiting_conditional_orders(product_id)
                for row in awaiting_db:
                    cond_id = row.get('conditional_order_id')
                    # Get or reconstruct conditional order
                    if cond_id not in self.conditional_orders:
                        cond_order = ConditionalOrder(
                            conditional_order_id=cond_id,
                            base_order_id=row.get('base_order_id'),
                            product_id=row.get('product_id'),
                            side=OrderSide.BUY if row.get('side') == 'BUY' else OrderSide.SELL,
                            size=float(row.get('size', 0.0)),
                            price=float(row.get('price')) if row.get('price') else None,
                            min_profitable_price=float(row.get('min_profitable_price', 0.0)),
                            status=ConditionalOrderStatus(row.get('status', 'AWAITING_CONDITION')),
                            notes=row.get('notes', ''),
                            is_active=True
                        )
                        self.conditional_orders[cond_id] = cond_order
                    else:
                        cond_order = self.conditional_orders[cond_id]
                    
                    # Check expiration
                    if cond_order.expiration_time and datetime.utcnow() > cond_order.expiration_time:
                        cond_order.status = ConditionalOrderStatus.EXPIRED
                        cond_order.is_active = False
                        if self.db_client:
                            try:
                                update_conditional_order_status(cond_id, 'EXPIRED')
                            except Exception as e:
                                logger.error(f"Error updating expired order in database: {type(e).__name__}: {e}")
                        logger.info(f"Conditional order {cond_id} expired")
                        continue
                    
                    # Evaluate profit condition
                    is_profitable = self._check_profit_condition(cond_order, market_price)
                    
                    if is_profitable:
                        cond_order.status = ConditionalOrderStatus.CONDITION_MET
                        cond_order.submitted_at = datetime.utcnow()
                        ready_to_submit.append(cond_order)
                        
                        logger.info(f"[LOT-TRACK] Condition met for {cond_id}: "
                                   f"market_price={market_price} allows {cond_order.side.name} {cond_order.size} {cond_order.product_id} "
                                   f"@ min_profit={cond_order.min_profitable_price}")
            except Exception as e:
                logger.error(f"Error querying awaiting conditional orders: {type(e).__name__}: {e}")
        else:
            # Fallback to memory cache if no database
            for cond_id, cond_order in list(self.conditional_orders.items()):
                # Skip inactive orders
                if not cond_order.is_active:
                    continue
                
                # Skip if not matching product
                if cond_order.product_id != product_id:
                    continue
                
                # Skip if already submitted
                if cond_order.status != ConditionalOrderStatus.AWAITING_CONDITION:
                    continue
                
                # Check expiration
                if cond_order.expiration_time and datetime.utcnow() > cond_order.expiration_time:
                    cond_order.status = ConditionalOrderStatus.EXPIRED
                    cond_order.is_active = False
                    logger.info(f"Conditional order {cond_id} expired")
                    continue
                
                # Evaluate profit condition
                is_profitable = self._check_profit_condition(cond_order, market_price)
                
                if is_profitable:
                    cond_order.status = ConditionalOrderStatus.CONDITION_MET
                    cond_order.submitted_at = datetime.utcnow()
                    ready_to_submit.append(cond_order)
                    
                    logger.info(f"[LOT-TRACK] Condition met for {cond_id}: "
                               f"market_price={market_price} allows {cond_order.side.name} {cond_order.size} {cond_order.product_id} "
                               f"@ min_profit={cond_order.min_profitable_price}")
        
        return ready_to_submit
    
    def _check_profit_condition(self, cond_order: ConditionalOrder, market_price: float) -> bool:
        """Check if profit condition is met for an order.
        
        Args:
            cond_order: ConditionalOrder to check
            market_price: Current market price
        
        Returns:
            True if order can execute profitably
        """
        if cond_order.side == OrderSide.BUY:
            # For buys, market must be below min profitable price
            return market_price <= cond_order.min_profitable_price
        else:
            # For sells, market must be above min profitable price
            return market_price >= cond_order.min_profitable_price
    
    def mark_submitted(self, conditional_order_id: str) -> bool:
        """Mark a conditional order as submitted to exchange.
        
        Args:
            conditional_order_id: ID of conditional order
        
        Returns:
            True if successful
        """
        cond_order = self.conditional_orders.get(conditional_order_id)
        if not cond_order:
            logger.warning(f"Conditional order {conditional_order_id} not found")
            return False
        
        if cond_order.status != ConditionalOrderStatus.CONDITION_MET:
            logger.warning(f"Cannot mark {conditional_order_id} as submitted "
                          f"(status: {cond_order.status.value})")
            return False
        
        cond_order.status = ConditionalOrderStatus.SUBMITTED
        cond_order.submitted_at = datetime.utcnow()
        
        # Update database if available
        if self.db_client:
            try:
                mark_conditional_submitted(conditional_order_id)
            except Exception as e:
                logger.error(f"Error updating submitted status in database: {type(e).__name__}: {e}")
        
        logger.info(f"[LOT-TRACK] Marked conditional {conditional_order_id} as SUBMITTED to exchange")
        return True
    
    def mark_filled(self,
                   conditional_order_id: str,
                   execution_price: float,
                   filled_at: Optional[datetime] = None) -> bool:
        """Mark a conditional order as filled.
        
        Args:
            conditional_order_id: ID of conditional order
            execution_price: Price at which filled
            filled_at: When it was filled
        
        Returns:
            True if successful
        """
        cond_order = self.conditional_orders.get(conditional_order_id)
        if not cond_order:
            logger.warning(f"Conditional order {conditional_order_id} not found")
            return False
        
        cond_order.status = ConditionalOrderStatus.FILLED
        cond_order.execution_price = execution_price
        cond_order.filled_at = filled_at or datetime.utcnow()
        cond_order.is_active = False
        
        # Update database if available
        if self.db_client:
            try:
                mark_conditional_filled(conditional_order_id, execution_price)
            except Exception as e:
                logger.error(f"Error updating filled status in database: {type(e).__name__}: {e}")
        
        logger.info(f"[LOT-TRACK] Conditional order {conditional_order_id} FILLED @ {execution_price}")
        return True
    
    def cancel_order(self, conditional_order_id: str) -> bool:
        """Cancel a conditional order.
        
        Args:
            conditional_order_id: ID of conditional order to cancel
        
        Returns:
            True if successful
        """
        cond_order = self.conditional_orders.get(conditional_order_id)
        if not cond_order:
            logger.warning(f"Conditional order {conditional_order_id} not found")
            return False
        
        cond_order.status = ConditionalOrderStatus.CANCELLED
        cond_order.is_active = False
        
        # Update database if available
        if self.db_client:
            try:
                cancel_conditional_order(conditional_order_id)
            except Exception as e:
                logger.error(f"Error updating cancelled status in database: {type(e).__name__}: {e}")
        
        logger.info(f"[LOT-TRACK] Conditional order {conditional_order_id} CANCELLED")
        return True
    
    def get_active_orders(self, product_id: Optional[str] = None) -> List[ConditionalOrder]:
        """Get all active conditional orders.
        
        Args:
            product_id: Optional product filter
        
        Returns:
            List of active conditional orders
        """
        active = [o for o in self.conditional_orders.values() if o.is_active]
        
        if product_id:
            active = [o for o in active if o.product_id == product_id]
        
        return active
    
    def get_awaiting_conditions(self, product_id: Optional[str] = None) -> List[ConditionalOrder]:
        """Get all orders still awaiting condition.
        
        Args:
            product_id: Optional product filter
        
        Returns:
            List of orders in AWAITING_CONDITION status
        """
        awaiting = [o for o in self.conditional_orders.values()
                   if o.status == ConditionalOrderStatus.AWAITING_CONDITION]
        
        if product_id:
            awaiting = [o for o in awaiting if o.product_id == product_id]
        
        return awaiting
