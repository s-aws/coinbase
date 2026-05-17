"""
Test script to demonstrate LOT-TRACK integration logging.

This script simulates a trading scenario with fill events and condition evaluation
to show the INFO logging in action.
"""

import uuid
from datetime import datetime

from _bootstrap import ensure_repo_root

ensure_repo_root()

from database.database import PostgresDB
from database.order import insert_order_parent
from business.fill_ledger import FillLedgerRepository
from business.conditional_execution import ConditionalExecutionWrapper
from business.order_interception_layer import OrderInterceptionLayer
from business.post_fill_hook import on_order_filled, trigger_lot_update
from core.enums import OrderSide
from logging_service import get_logger

logger = get_logger("TestLotTracking")


def test_lot_tracking_integration():
    """Demonstrate lot tracking integration with INFO logging."""
    
    logger.info("\n" + "="*80)
    logger.info("[TEST] Starting Lot Tracking Integration Test")
    logger.info("="*80 + "\n")
    
    db = PostgresDB()
    
    try:
        # Initialize fill ledger
        logger.info("[TEST] Initializing components...")
        fill_repo = FillLedgerRepository(db)
        
        # Initialize order interception layer
        interception_layer = OrderInterceptionLayer(fill_repo, profit_margin_pct=0.5)
        
        # Initialize conditional execution wrapper with database persistence
        conditional_wrapper = ConditionalExecutionWrapper(
            order_interception_layer=interception_layer,
            db_client=db
        )
        
        logger.info("[TEST] All components initialized\n")
        
        # Create parent orders first (required for conditional orders FK constraint)
        logger.info("[TEST] Creating parent orders...")
        insert_order_parent(
            client_order_id="order-001",
            product_id="BTC-USDC",
            side="BUY",
            size=1.0,
            price=40000.0,
            target_movement=0.005,
            target_movement_type="P"
        )
        
        insert_order_parent(
            client_order_id="order-002",
            product_id="BTC-USDC",
            side="BUY",
            size=0.5,
            price=40500.0,
            target_movement=0.005,
            target_movement_type="P"
        )
        
        logger.info("[TEST] Parent orders created\n")
        logger.info("[TEST] --- SCENARIO 1: BUY ORDER ---")
        logger.info("[TEST] Simulating BUY 1.0 BTC-USDC @ $40,000")
        
        trade_id_1 = str(uuid.uuid4())
        on_order_filled(
            fill_repo=fill_repo,
            product_id="BTC-USDC",
            side="BUY",
            quantity=1.0,
            price=40000.0,
            fees=10.0,
            client_order_id="order-001",
            trade_id=trade_id_1,
            timestamp=datetime.utcnow(),
            commission_pct=0.0025
        )
        
        # Trigger lot reconstruction
        logger.info("[TEST] Reconstructing position lots after fill...")
        result = trigger_lot_update(fill_repo, "BTC-USDC")
        logger.info(f"[TEST] Position: {len(result['lots'])} lot(s), total_qty={result['total_quantity']}")
        
        if result['lots']:
            lot = result['lots'][0]
            logger.info(f"[TEST] Lot details: entry_price={lot['entry_price']}, min_profitable_exit={lot['min_profitable_exit_price']}")
        
        logger.info("[TEST] ---")
        
        # Simulate another BUY to create second lot
        logger.info("[TEST] --- SCENARIO 2: SECOND BUY ORDER ---")
        logger.info("[TEST] Simulating BUY 0.5 BTC-USDC @ $40,500")
        
        trade_id_2 = str(uuid.uuid4())
        on_order_filled(
            fill_repo=fill_repo,
            product_id="BTC-USDC",
            side="BUY",
            quantity=0.5,
            price=40500.0,
            fees=5.0,
            client_order_id="order-002",
            trade_id=trade_id_2,
            timestamp=datetime.utcnow(),
            commission_pct=0.0025
        )
        
        # Trigger lot reconstruction again
        logger.info("[TEST] Reconstructing position lots after second fill...")
        result = trigger_lot_update(fill_repo, "BTC-USDC")
        logger.info(f"[TEST] Position: {len(result['lots'])} lot(s), total_qty={result['total_quantity']}")
        
        logger.info("[TEST] ---")
        
        # Create conditional order with profit threshold
        logger.info("[TEST] --- SCENARIO 3: CONDITIONAL SELL ORDER ---")
        logger.info("[TEST] Creating conditional SELL order with min_profitable_price=$40,500")
        
        conditional_id = str(uuid.uuid4())
        conditional = conditional_wrapper.wrap_with_profit_condition(
            product_id="BTC-USDC",
            side=OrderSide.SELL,
            size=1.0,
            price=40500.0,
            min_profitable_price=40500.0,
            base_order_id="order-001",
            notes="Exit position if market reaches $40,500"
        )
        
        if conditional:
            logger.info(f"[TEST] Conditional order created: {conditional.conditional_order_id}")
        
        logger.info("[TEST] ---")
        
        # Evaluate condition at different prices
        logger.info("[TEST] --- SCENARIO 4: CONDITION EVALUATION ---")
        logger.info("[TEST] Market price = $40,200 (below threshold)")
        ready = conditional_wrapper.evaluate_condition(40200.0, "BTC-USDC")
        logger.info(f"[TEST] Orders ready to submit: {len(ready)}")
        
        logger.info("[TEST] ---")
        logger.info("[TEST] Market price = $40,600 (above threshold)")
        ready = conditional_wrapper.evaluate_condition(40600.0, "BTC-USDC")
        logger.info(f"[TEST] Orders ready to submit: {len(ready)}")
        
        if ready:
            logger.info(f"[TEST] Marking conditional order as SUBMITTED")
            conditional_wrapper.mark_submitted(ready[0].conditional_order_id)
            
            logger.info(f"[TEST] Simulating fill at $40,650")
            conditional_wrapper.mark_filled(ready[0].conditional_order_id, 40650.0)
        
        logger.info("[TEST] ---")
        
        # Show recovery on restart
        logger.info("[TEST] --- SCENARIO 5: RECOVERY ON RESTART ---")
        logger.info("[TEST] Simulating engine restart (creating new conditional wrapper)")
        
        conditional_wrapper_2 = ConditionalExecutionWrapper(
            order_interception_layer=interception_layer,
            db_client=db
        )
        
        logger.info("[TEST] Recovery complete\n")
        
        logger.info("="*80)
        logger.info("[TEST] Integration test completed successfully!")
        logger.info("="*80 + "\n")
        
        # Summary
        logger.info("[TEST] Summary:")
        logger.info(f"[TEST]   • Recorded 2 fills for BTC-USDC")
        logger.info(f"[TEST]   • Created 1 conditional SELL order")
        logger.info(f"[TEST]   • Evaluated condition at 2 price points")
        logger.info(f"[TEST]   • Filled 1 conditional order")
        logger.info(f"[TEST]   • Simulated engine restart and recovery")
        logger.info(f"[TEST] Check logs above for [LOT-TRACK] entries\n")
        
    finally:
        db.disconnect()


if __name__ == "__main__":
    test_lot_tracking_integration()
