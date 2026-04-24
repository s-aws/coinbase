"""
Post-Fill Hook Integration - Connects order engine fills to lot tracking.

This module provides hooks that can be called from the order engine
when orders are filled, ensuring the immutable fill ledger stays in sync
without modifying core execution logic.

The hook functions are designed to be called from:
- OrderEngine.process_user_order() when a fill is detected
- OrderEngine.handle_filled_order() when processing fill events
- Any other fill detection point in the engine

Design:
- Non-blocking: Logging failures don't block order processing
- Idempotent: Safe to call multiple times for same fill
- Recoverable: Database persistence enables replay/recovery

Example:
    >>> from business.post_fill_hook import initialize_fill_ledger, on_order_filled
    >>>
    >>> fill_repo = initialize_fill_ledger(db_client)
    >>> ok = on_order_filled(
    ...     fill_repo=fill_repo,
    ...     product_id='BTC-USDC',
    ...     side='BUY',
    ...     quantity=0.1,
    ...     price=42100.0,
    ...     fees=0.45,
    ...     client_order_id='client-order-123',
    ... )
    >>> ok
    True
"""

from typing import Optional, Dict, Any
from business.fill_ledger import FillLedger, FillLedgerRepository
from business.lot_config import get_profit_target_for_product
from core.enums import OrderSide
from core.constants import get_local_now
from logging_service import get_logger

logger = get_logger("PostFillHook")


def initialize_fill_ledger(db_client) -> FillLedgerRepository:
    """Initialize the fill ledger repository.
    
    This should be called once during application startup.
    
    Args:
        db_client: PostgresDB instance
    
    Returns:
        FillLedgerRepository ready for use
    """
    logger.info("[LOT-TRACK] Initializing fill ledger repository with database persistence")
    fill_repo = FillLedgerRepository(db_client)
    logger.info("[LOT-TRACK] Fill ledger repository initialized successfully")
    return fill_repo


def on_order_filled(fill_repo: FillLedgerRepository,
                   product_id: str,
                   side: str,
                   quantity: float,
                   price: float,
                   fees: float = 0.0,
                   client_order_id: Optional[str] = None,
                   trade_id: Optional[str] = None,
                   timestamp: Optional[Any] = None,
                   commission_pct: float = 0.0) -> bool:
    """Hook called when an order fill occurs.
    
    This function should be called from the order engine whenever a fill
    is detected. It records the fill in the immutable ledger and triggers
    any dependent processes.
    
    Args:
        fill_repo: FillLedgerRepository instance
        product_id: Trading pair (e.g., 'BTC-USDC')
        side: 'BUY' or 'SELL'
        quantity: Amount filled
        price: Fill price
        fees: Fees paid (optional)
        client_order_id: Client order ID (optional, for tracing)
        trade_id: Exchange trade ID (optional, for deduplication)
        timestamp: When fill occurred (optional, uses current time if not provided)
        commission_pct: Commission rate (optional)
    
    Returns:
        True if fill was recorded, False on error
    """
    # Validate inputs
    if not product_id or not side or quantity <= 0 or price < 0:
        logger.error(f"Invalid fill parameters: "
                    f"product_id={product_id}, side={side}, qty={quantity}, price={price}")
        return False
    
    # Normalize side
    side = side.upper()
    if side not in ('BUY', 'SELL'):
        logger.error(f"Invalid side: {side}")
        return False
    
    # Generate trade_id if not provided (idempotency key)
    if not trade_id:
        import uuid
        trade_id = str(uuid.uuid4())
    
    # Create fill ledger record
    try:
        fill = FillLedger(
            trade_id=trade_id,
            instrument=product_id,
            side=side,
            quantity=quantity,
            price=price,
            timestamp=timestamp or get_local_now(),
            fees=fees,
            commission_percentage=commission_pct,
            order_side=OrderSide[side],
            client_order_id=client_order_id,
            product_id=product_id,
            average_price=price
        )
        
        # Append to immutable ledger
        if fill_repo.append_fill(fill):
            logger.info(f"[LOT-TRACK] Fill hook processed: {trade_id} {side} {quantity} {product_id} @ {price}, fees={fees}, client_order={client_order_id}")
            return True
        else:
            logger.error(f"[LOT-TRACK] Failed to record fill {trade_id}")
            return False
    
    except Exception as e:
        logger.error(f"✗ Error creating fill record: {type(e).__name__}: {e}")
        return False


def on_partial_fill(fill_repo: FillLedgerRepository,
                   product_id: str,
                   side: str,
                   partial_quantity: float,
                   price: float,
                   partial_fees: float = 0.0,
                   client_order_id: Optional[str] = None,
                   trade_id: Optional[str] = None,
                   **kwargs) -> bool:
    """Hook called when an order partially fills.
    
    Partial fills are treated the same as regular fills - each partial
    is recorded separately in the ledger.
    
    Args:
        fill_repo: FillLedgerRepository instance
        product_id: Trading pair
        side: 'BUY' or 'SELL'
        partial_quantity: Amount of this partial fill
        price: Fill price for this partial
        partial_fees: Fees for this partial
        client_order_id: Client order ID
        trade_id: Unique fill identifier
        **kwargs: Additional parameters (passed to on_order_filled)
    
    Returns:
        True if recorded successfully
    """
    return on_order_filled(
        fill_repo=fill_repo,
        product_id=product_id,
        side=side,
        quantity=partial_quantity,
        price=price,
        fees=partial_fees,
        client_order_id=client_order_id,
        trade_id=trade_id,
        **kwargs
    )


def trigger_lot_update(fill_repo: FillLedgerRepository,
                      product_id: str) -> Dict[str, Any]:
    """Trigger lot reconstruction for a product after fill(s).
    
    This function can be called after recording fills to ensure
    position lots are updated. In the stateless design, this
    reconstructs lots from the ledger on-demand.
    
    Args:
        fill_repo: FillLedgerRepository instance
        product_id: Product to update lots for
    
    Returns:
        Dictionary with update status
    """
    try:
        from business.lot_builder import PositionLotBuilder
        
        builder = PositionLotBuilder(fill_repo)
        profit_target = get_profit_target_for_product(product_id)
        
        logger.info(f"[LOT-TRACK] Reconstructing position lots for {product_id}, profit_target={profit_target}%")
        
        position = builder.build_position_by_product(
            product_id,
            profit_target_pct=profit_target
        )
        
        logger.info(f"[LOT-TRACK] Lot reconstruction complete: {product_id} has {len(position.lots)} lots, total_qty={position.total_quantity}")
        
        return {
            'status': 'OK',
            'product_id': product_id,
            'num_lots': len(position.lots),
            'total_quantity': position.total_quantity,
            'lots': [lot.to_dict() for lot in position.lots]
        }
    
    except Exception as e:
        logger.error(f"Error updating lots for {product_id}: {type(e).__name__}: {e}")
        return {
            'status': 'ERROR',
            'product_id': product_id,
            'error': str(e)
        }


def get_profit_constraints_for_order(fill_repo: FillLedgerRepository,
                                    product_id: str,
                                    side: str,
                                    size: float,
                                    current_price: Optional[float] = None) -> Dict[str, Any]:
    """Get profit constraints for a proposed order.
    
    This function provides decision-support for the order engine,
    returning whether an order would be profitable and at what price.
    
    Args:
        fill_repo: FillLedgerRepository instance
        product_id: Trading pair
        side: 'BUY' or 'SELL'
        size: Order quantity
        current_price: Current market price (optional)
    
    Returns:
        Dictionary with profit constraint information
    """
    try:
        from business.lot_builder import PositionLotBuilder
        from business.profit_threshold_engine import ProfitThresholdEngine
        from core.enums import OrderSide
        
        builder = PositionLotBuilder(fill_repo)
        profit_target = get_profit_target_for_product(product_id)
        
        position = builder.build_position_by_product(
            product_id,
            profit_target_pct=profit_target
        )
        
        if not position.get_unexited_lots():
            return {
                'status': 'NO_POSITION',
                'product_id': product_id,
                'side': side,
                'size': size,
                'is_constrained': False
            }
        
        engine = ProfitThresholdEngine(profit_target)
        targets, meta = engine.compute_execution_targets(
            position=position,
            exit_quantity=size,
            market_price=current_price or 0.0,
            strategy='FIFO'
        )
        
        if not targets:
            return {
                'status': 'NO_TARGETS',
                'product_id': product_id,
                'side': side,
                'size': size,
                'is_constrained': False,
                'reason': meta.get('message', 'Unknown')
            }
        
        return {
            'status': 'OK',
            'product_id': product_id,
            'side': side,
            'size': size,
            'is_constrained': True,
            'num_targets': len(targets),
            'current_price': current_price,
            'min_profitable_price': min(t.min_profitable_price for t in targets),
            'max_profitable_price': max(t.min_profitable_price for t in targets),
            'is_profitable_at_current': all(
                t.min_profitable_price <= current_price if side == 'SELL' 
                else t.min_profitable_price >= current_price
                for t in targets
            ) if current_price else None
        }
    
    except Exception as e:
        logger.error(f"Error computing profit constraints: {type(e).__name__}: {e}")
        return {
            'status': 'ERROR',
            'error': str(e)
        }
