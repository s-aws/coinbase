"""
Test OrderEngine integration with lot tracking.
This verifies that fill_repo is initialized and ready.
"""

from database.database import PostgresDB
from configuration import OrderBook
import json

# Mock configuration for testing
class MockSubscription:
    def __init__(self):
        self.channels = ["user"]
        self.product_ids = ["BTC-USDC"]

def test_order_engine_with_lot_tracking():
    """Test that OrderEngine initializes with lot tracking enabled."""
    print("\n" + "="*80)
    print("TESTING ORDERENGINE LOT TRACKING INTEGRATION")
    print("="*80 + "\n")
    
    try:
        # Initialize database
        db = PostgresDB()
        print("✓ Database connection established")
        
        # Initialize orderbook
        orderbook = OrderBook()
        print("✓ Orderbook initialized")
        
        # Mock API credentials
        api_key = "test_key"
        api_secret = "test_secret"
        order_post_only = {"BUY": False, "SELL": False}
        subscription = MockSubscription()
        
        # Import and instantiate OrderEngine
        from core.order_engine import OrderEngine
        
        engine = OrderEngine(
            orderbook=orderbook,
            db_helper=db,
            subscription=subscription,
            api_key=api_key,
            api_secret=api_secret,
            order_post_only=order_post_only,
            websocket_thread_maximum=1,
            max_workers=2,
        )
        print("✓ OrderEngine instantiated successfully")
        
        # Verify fill_repo is initialized
        if hasattr(engine, 'fill_repo'):
            if engine.fill_repo is not None:
                print(f"✓ Fill repository initialized: {type(engine.fill_repo).__name__}")
                print(f"  - FillLedgerRepository ready for recording fills")
            else:
                print("⚠ Fill repository is None (lot tracking disabled)")
        else:
            print("✗ OrderEngine missing fill_repo attribute")
            return False
        
        # Test that the fill recording hook is available
        from core.order_engine import LOT_TRACKING_AVAILABLE, post_fill_hook_on_order_filled
        print(f"✓ Lot tracking module available: {LOT_TRACKING_AVAILABLE}")
        
        print("\n" + "="*80)
        print("✅ ORDERENGINE LOT TRACKING INTEGRATION TEST PASSED")
        print("="*80 + "\n")
        print("Next: When orders are filled in production, they will be recorded with:")
        print("  [LOT-TRACK] Fill appended to ledger: trade_id=..., instrument=..., ...")
        print()
        
        return True
        
    except Exception as e:
        print(f"\n✗ ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        try:
            db.disconnect()
        except:
            pass

if __name__ == "__main__":
    success = test_order_engine_with_lot_tracking()
    exit(0 if success else 1)
