"""
Test the fill_ledger recording fix.

This simulates a fill event and verifies it's recorded in the database.
"""

import sys
sys.path.insert(0, 'e:\\coinbase')

from datetime import datetime
import uuid
from business.post_fill_hook import initialize_fill_ledger, on_order_filled
from database.database import PostgresDB
from database.order import insert_order_parent

def test_fill_recording():
    """Test that fills are recorded in fill_ledger."""

    print("\n" + "="*80)
    print("FILL LEDGER RECORDING TEST")
    print("="*80)

    db = PostgresDB()
    db.connect()

    # Step 1: Create a test parent order
    test_client_order_id = "test-fill-order-" + str(datetime.now().timestamp()).replace('.', '')
    test_trade_id = str(uuid.uuid4())  # Proper UUID for trade_id

    print(f"\n1️⃣  Creating test parent order: {test_client_order_id}")
    inserted = insert_order_parent(
        client_order_id=test_client_order_id,
        product_id="BTC-USDC",
        side="BUY",
        size=1.0,
        price=43000.0,
        target_movement=0.5,  # 0.5% profit target
        target_movement_type="P",
        status="OPEN"
    )
    print(f"   {'✓' if inserted else '✗'} Parent order created")

    # Step 2: Record a fill for that order
    print(f"\n2️⃣  Recording fill for the order...")
    fill_repo = initialize_fill_ledger(db)

    fill_success = on_order_filled(
        fill_repo=fill_repo,
        product_id="BTC-USDC",
        side="BUY",
        quantity=1.0,
        price=43000.0,
        fees=25.0,
        client_order_id=test_client_order_id,
        trade_id=test_trade_id,
        timestamp=datetime.utcnow(),
        commission_pct=0.0
    )
    print(f"   {'✓' if fill_success else '✗'} Fill recorded: {fill_success}")

    # Step 3: Verify the fill was recorded
    print(f"\n3️⃣  Verifying fill was recorded...")

    results = db.execute_query(
        "SELECT COUNT(*) as count FROM fill_ledger WHERE client_order_id = %s",
        (test_client_order_id,)
    )
    fill_count = results[0]['count'] if results and len(results) > 0 else 0
    print(f"   Found {fill_count} fill record(s)")

    if fill_count > 0:
        # Get details
        details = db.execute_query(
            "SELECT trade_id, instrument, side, quantity, price, fees FROM fill_ledger WHERE client_order_id = %s",
            (test_client_order_id,)
        )
        for row in details:
            print(f"   ✓ Fill details:")
            print(f"     - Trade ID: {row.get('trade_id')}")
            print(f"     - Instrument: {row.get('instrument')}")
            print(f"     - Side: {row.get('side')}")
            print(f"     - Quantity: {row.get('quantity')}")
            print(f"     - Price: {row.get('price')}")
            print(f"     - Fees: {row.get('fees')}")

    # Step 4: Summary
    print("\n" + "="*80)
    if fill_count > 0:
        print("✅ TEST PASSED: Fill was successfully recorded in fill_ledger!")
        result = True
    else:
        print("❌ TEST FAILED: Fill was NOT recorded in fill_ledger")
        result = False
    print("="*80 + "\n")

    db.disconnect()
    return result

if __name__ == "__main__":
    try:
        success = test_fill_recording()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ TEST EXCEPTION: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
