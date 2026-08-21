#!/usr/bin/env python3
"""
Test the UPSERT fix for duplicate reveal event recording.

This script verifies that:
1. Recording the same reveal event twice doesn't cause a duplicate key error
2. The second recording updates the record with new data
3. The reveal event is properly persisted in the database
"""

import json
import uuid
from datetime import datetime
from database.database import PostgresDB
from core.stealth_order_manager import StealthOrderManager

def test_duplicate_reveal_event_recording():
    """Test that UPSERT prevents duplicate key errors."""
    print("\n→ Testing duplicate reveal event recording (UPSERT fix)...")

    db = PostgresDB()
    try:
        db.connect()
        manager = StealthOrderManager(db_client=db)

        # Create a test stealth order
        stealth_order_id = str(uuid.uuid4())
        order = {
            'stealth_order_id': stealth_order_id,
            'product_id': 'BTC-USDC',
            'side': 'BUY',
            'total_size': 1.0,
            'revealed_size': 0.5,
            'remaining_size': 0.5,
            'executed_size': 0.0,
            'limit_price': 50000.0,
            'status': 'REVEALED',
            'reveal_condition_type': 'time_delay',
            'reveal_condition_json': json.dumps({"delay_seconds": 0}),
            'revealed_orders': [],
        }

        # Insert the stealth order
        insert_query = """
        INSERT INTO stealth_orders (
            stealth_order_id, product_id, side, total_size, revealed_size,
            remaining_size, executed_size, limit_price, status,
            reveal_condition_type, reveal_condition_json, revealed_orders
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """

        db.execute_update(insert_query, (
            order['stealth_order_id'],
            order['product_id'],
            order['side'],
            order['total_size'],
            order['revealed_size'],
            order['remaining_size'],
            order['executed_size'],
            order['limit_price'],
            order['status'],
            order['reveal_condition_type'],
            order['reveal_condition_json'],
            json.dumps(order['revealed_orders'])
        ))

        print(f"✓ Test order created: {stealth_order_id}")

        # Create a reveal event
        reveal_event_1 = {
            'reveal_number': 1,
            'revealed_size': 0.5,
            'placement_price': 50000.0,
            'placed_order_id': str(uuid.uuid4()),
            'exchange_order_id': 'exchange-123',
            'market_price': 49999.0,
            'market_bid': 49995.0,
            'market_ask': 50000.0,
            'market_spread': 5.0,
            'market_volume_1m': 100.0,
            'market_source': 'ticker',
            'reveal_time': datetime.utcnow(),
        }

        # Record the reveal event (first time)
        manager._record_reveal_event(order, reveal_event_1)
        print("✓ First reveal event recorded")

        # Verify it was inserted
        result = db.execute_query(
            "SELECT * FROM stealth_order_reveal_history WHERE stealth_order_id = %s AND reveal_number = 1",
            (stealth_order_id,)
        )

        if not result:
            print("✗ Reveal event not found in database after first insert")
            return False

        print(f"✓ Reveal event found in database")

        # Try to record the same reveal event again (should not fail due to UPSERT)
        # Update it with slightly different data
        reveal_event_2 = {
            'reveal_number': 1,
            'revealed_size': 0.5,
            'placement_price': 50000.0,
            'placed_order_id': str(uuid.uuid4()),
            'exchange_order_id': 'exchange-456',  # Changed
            'market_price': 50001.0,  # Changed
            'market_bid': 49996.0,  # Changed
            'market_ask': 50001.0,  # Changed
            'market_spread': 5.0,
            'market_volume_1m': 101.0,  # Changed
            'market_source': 'ticker',
            'reveal_time': datetime.utcnow(),
        }

        try:
            manager._record_reveal_event(order, reveal_event_2)
            print("✓ Second reveal event recorded (UPSERT) - no duplicate key error!")
        except Exception as e:
            print(f"✗ Second reveal event failed: {e}")
            return False

        # Verify the record was updated
        result = db.execute_query(
            "SELECT exchange_order_id, market_price FROM stealth_order_reveal_history WHERE stealth_order_id = %s AND reveal_number = 1",
            (stealth_order_id,)
        )

        if not result:
            print("✗ Reveal event not found after UPSERT")
            return False

        row = result[0]
        if row[1] == 50001.0:  # market_price was updated
            print(f"✓ Reveal event was updated with new data (market_price=50001.0)")
        else:
            print(f"✗ Reveal event was not updated (market_price={row[1]}, expected 50001.0)")
            return False

        # Cleanup
        db.execute_update("DELETE FROM stealth_order_reveal_history WHERE stealth_order_id = %s", (stealth_order_id,))
        db.execute_update("DELETE FROM stealth_orders WHERE stealth_order_id = %s", (stealth_order_id,))
        print("✓ Test data cleaned up")

        return True

    except Exception as e:
        print(f"✗ Error testing duplicate reveal event recording: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.disconnect()

def main():
    """Run the test."""
    print("=" * 60)
    print("Testing Reveal Event UPSERT Fix for Partial Fills")
    print("=" * 60)

    success = test_duplicate_reveal_event_recording()

    print("\n" + "=" * 60)
    if success:
        print("✓ UPSERT fix verified! Duplicate reveals are now handled safely.")
    else:
        print("✗ UPSERT fix test failed")
    print("=" * 60)

    return 0 if success else 1

if __name__ == '__main__':
    import sys
    sys.exit(main())
