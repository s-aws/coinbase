"""
Simple test showing [LOT-TRACK] logging with proper timestamps.
"""

import logging
import sys

from _bootstrap import ensure_repo_root

ensure_repo_root()

from database.database import PostgresDB
from core.stealth_order_manager import StealthOrderManager
from logging_service import get_logger

# Configure all loggers to show INFO level
logging.getLogger().setLevel(logging.INFO)
logging.getLogger("StealthOrderManager").setLevel(logging.INFO)

# Add console handler to root logger
console = logging.StreamHandler(sys.stdout)
console.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console.setFormatter(formatter)
logging.getLogger().addHandler(console)
logging.getLogger("StealthOrderManager").addHandler(console)

print("\n" + "="*80)
print("LOT-TRACK LOGGING WITH TIMESTAMPS")
print("="*80 + "\n")

db = PostgresDB()

try:
    manager = StealthOrderManager(db_client=db)
    
    print("[TEST] Creating stealth order...\n")
    order_id = manager.create_stealth_order(
        product_id="BIT-29MAY26-CDE",
        side="BUY",
        total_size=1.0,
        limit_price=77000.0,
        reveal_condition={"type": "time_delay", "delay_seconds": 0}
    )
    
    print("\n[TEST] Evaluating condition...\n")
    condition_met, reason = manager.evaluate_conditions(order_id)
    
    print("\n[TEST] Updating execution...\n")
    manager.update_execution(order_id, executed_size=1.0, order_status="EXECUTED")
    
    print("\n" + "="*80)
    print("Check the output above for timestamped [LOT-TRACK] entries")
    print("="*80 + "\n")
    
finally:
    db.disconnect()
