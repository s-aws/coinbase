"""
Simple test to demonstrate LOT-TRACK logging.
This version writes logs to a file for easier inspection.
"""

import uuid
from datetime import datetime

from _bootstrap import ensure_repo_root

ensure_repo_root()

from database.database import PostgresDB
from database.order import insert_order_parent
from business.fill_ledger import FillLedgerRepository, FillLedger
from business.conditional_execution import ConditionalExecutionWrapper
from business.order_interception_layer import OrderInterceptionLayer
from core.enums import OrderSide
from logging_service import get_logger
import sys

logger = get_logger("TestLotTracking")

# Also log to console
import logging
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)

# Add handler to the logger
python_logger = logging.getLogger("PostFillHook")
python_logger.addHandler(console_handler)
python_logger.setLevel(logging.INFO)

python_logger2 = logging.getLogger("FillLedger")
python_logger2.addHandler(console_handler)
python_logger2.setLevel(logging.INFO)

python_logger3 = logging.getLogger("ConditionalExecutionWrapper")
python_logger3.addHandler(console_handler)
python_logger3.setLevel(logging.INFO)

python_logger4 = logging.getLogger("OrderDB")
python_logger4.addHandler(console_handler)
python_logger4.setLevel(logging.INFO)


def test_logging():
    print("\n" + "="*80)
    print("LOT TRACKING INTEGRATION - LOGGING DEMONSTRATION")
    print("="*80 + "\n")
    
    db = PostgresDB()
    
    try:
        # Initialize fill ledger
        print("[SETUP] Creating parent orders...")
        insert_order_parent(
            client_order_id="order-001",
            product_id="BTC-USDC",
            side="BUY",
            size=1.0,
            price=40000.0,
            target_movement=0.005,
            target_movement_type="P"
        )
        print("[SETUP] Parent order created: order-001\n")
        
        print("[SETUP] Initializing FillLedgerRepository...")
        fill_repo = FillLedgerRepository(db)
        print("[SETUP] FillLedgerRepository ready\n")
        
        # Simulate a fill
        print("[SCENARIO 1] Recording a fill...")
        print("-" * 60)
        fill = FillLedger(
            derived_trade_key=str(uuid.uuid4()),
            instrument="BTC-USDC",
            side="BUY",
            quantity=1.0,
            price=40000.0,
            timestamp=datetime.utcnow(),
            fees=10.0,
            commission_percentage=0.0025,
            order_side=OrderSide.BUY,
            client_order_id="order-001",
            product_id="BTC-USDC",
            average_price=40000.0
        )
        
        success = fill_repo.append_fill(fill)
        print(f"Fill recording result: {'SUCCESS' if success else 'FAILED'}\n")
        
        # Retrieve fills
        print("[SCENARIO 2] Retrieving recorded fills...")
        print("-" * 60)
        fills = fill_repo.get_fills_by_instrument("BTC-USDC")
        print(f"Retrieved {len(fills)} fill(s) for BTC-USDC\n")
        
        # Initialize conditional wrapper
        print("[SCENARIO 3] Initializing ConditionalExecutionWrapper...")
        print("-" * 60)
        interception_layer = OrderInterceptionLayer(fill_repo, profit_margin_pct=0.5)
        conditional_wrapper = ConditionalExecutionWrapper(
            order_interception_layer=interception_layer,
            db_client=db
        )
        print("ConditionalExecutionWrapper initialized with database persistence\n")
        
        # Create conditional order
        print("[SCENARIO 4] Creating conditional order...")
        print("-" * 60)
        conditional = conditional_wrapper.wrap_with_profit_condition(
            product_id="BTC-USDC",
            side=OrderSide.SELL,
            size=1.0,
            price=40500.0,
            min_profitable_price=40500.0,
            base_order_id="order-001",
            notes="Exit when market reaches $40,500"
        )
        print(f"Conditional order created: {conditional.conditional_order_id if conditional else 'FAILED'}\n")
        
        # Evaluate conditions
        print("[SCENARIO 5] Evaluating market conditions...")
        print("-" * 60)
        print("Testing: Market price = $40,200 (below threshold)")
        ready_1 = conditional_wrapper.evaluate_condition(40200.0, "BTC-USDC")
        print(f"Orders ready to submit: {len(ready_1)}\n")
        
        print("Testing: Market price = $40,600 (above threshold)")
        ready_2 = conditional_wrapper.evaluate_condition(40600.0, "BTC-USDC")
        print(f"Orders ready to submit: {len(ready_2)}\n")
        
        if ready_2:
            print("[SCENARIO 6] Processing conditional order transition...")
            print("-" * 60)
            print("Marking order as SUBMITTED...")
            conditional_wrapper.mark_submitted(ready_2[0].conditional_order_id)
            
            print("Marking order as FILLED...")
            conditional_wrapper.mark_filled(ready_2[0].conditional_order_id, 40650.0)
            print()
        
        # Test recovery
        print("[SCENARIO 7] Testing recovery on restart...")
        print("-" * 60)
        print("Creating new ConditionalExecutionWrapper (simulating restart)...")
        conditional_wrapper_2 = ConditionalExecutionWrapper(
            order_interception_layer=interception_layer,
            db_client=db
        )
        print("Recovery complete\n")
        
        print("="*80)
        print("TEST COMPLETE - Check logs above for [LOT-TRACK] entries")
        print("="*80 + "\n")
        
    finally:
        db.disconnect()


if __name__ == "__main__":
    test_logging()
