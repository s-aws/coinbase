#!/usr/bin/env python3
"""
Test the StealthOrderManager schema migration fix.

This script verifies that:
1. StealthOrderManager initializes without errors
2. The required columns exist after initialization
3. Basic database operations work with the new columns
"""

import json
import uuid
from database.database import PostgresDB
from core.stealth_order_manager import StealthOrderManager

def check_columns_exist():
    """Check if the required columns exist."""
    db = PostgresDB()
    try:
        db.connect()

        query = """
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'stealth_orders'
        AND column_name IN ('anchor_repricing_policy_json', 'anchor_repricing_state_json')
        ORDER BY column_name;
        """

        results = db.execute_query(query)
        columns_found = [row[0] for row in results] if results else []

        print(f"Found columns: {columns_found}")

        required_columns = {'anchor_repricing_policy_json', 'anchor_repricing_state_json'}
        found_columns = set(columns_found)

        return required_columns == found_columns

    except Exception as e:
        print(f"✗ Error checking columns: {e}")
        return False
    finally:
        db.disconnect()

def test_stealth_order_manager_init():
    """Test that StealthOrderManager initializes and runs migration."""
    print("\n→ Testing StealthOrderManager initialization...")

    try:
        db = PostgresDB()
        manager = StealthOrderManager(db_client=db)
        print("✓ StealthOrderManager initialized successfully")

        # Check columns again after init
        if check_columns_exist():
            print("✓ Required columns exist after StealthOrderManager init")
            return True
        else:
            print("✗ Required columns missing after StealthOrderManager init")
            return False

    except Exception as e:
        print(f"✗ Error initializing StealthOrderManager: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_order_update():
    """Test that order updates work with new columns."""
    print("\n→ Testing stealth order update with anchor repricing columns...")

    db = PostgresDB()
    try:
        db.connect()

        # Create a test order
        test_order = {
            'stealth_order_id': str(uuid.uuid4()),
            'product_id': 'BTC-USDC',
            'side': 'BUY',
            'total_size': 1.0,
            'revealed_size': 0.0,
            'remaining_size': 1.0,
            'executed_size': 0.0,
            'limit_price': 50000.0,
            'status': 'HIDDEN',
            'reveal_condition_type': 'time_delay',
            'reveal_condition_json': json.dumps({"delay_seconds": 0}),
            'anchor_repricing_policy_json': json.dumps({"enabled": False}),
            'anchor_repricing_state_json': json.dumps({}),
            'revealed_orders': json.dumps([])
        }

        # Insert test order
        insert_query = """
        INSERT INTO stealth_orders (
            stealth_order_id, product_id, side, total_size, revealed_size,
            remaining_size, executed_size, limit_price, status,
            reveal_condition_type, reveal_condition_json,
            anchor_repricing_policy_json, anchor_repricing_state_json,
            revealed_orders
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """

        db.execute_update(insert_query, (
            test_order['stealth_order_id'],
            test_order['product_id'],
            test_order['side'],
            test_order['total_size'],
            test_order['revealed_size'],
            test_order['remaining_size'],
            test_order['executed_size'],
            test_order['limit_price'],
            test_order['status'],
            test_order['reveal_condition_type'],
            test_order['reveal_condition_json'],
            test_order['anchor_repricing_policy_json'],
            test_order['anchor_repricing_state_json'],
            test_order['revealed_orders']
        ))

        print(f"✓ Test order inserted: {test_order['stealth_order_id']}")

        # Update the order with new repricing policy
        update_query = """
        UPDATE stealth_orders
        SET status = %s, anchor_repricing_policy_json = %s, anchor_repricing_state_json = %s
        WHERE stealth_order_id = %s
        """

        new_policy = json.dumps({"enabled": True, "policy": "top_of_book"})
        new_state = json.dumps({"last_repriced": "2026-04-25T17:30:00"})

        db.execute_update(update_query, (
            'REVEALED',
            new_policy,
            new_state,
            test_order['stealth_order_id']
        ))

        print(f"✓ Test order updated with anchor repricing columns")

        # Verify the update
        verify_query = """
        SELECT anchor_repricing_policy_json, anchor_repricing_state_json
        FROM stealth_orders
        WHERE stealth_order_id = %s
        """

        result = db.execute_query(verify_query, (test_order['stealth_order_id'],))

        if result and len(result) > 0:
            row = result[0]
            print(f"✓ Updated policy: {row[0]}")
            print(f"✓ Updated state: {row[1]}")

            # Cleanup
            db.execute_update("DELETE FROM stealth_orders WHERE stealth_order_id = %s",
                            (test_order['stealth_order_id'],))
            print(f"✓ Test order cleaned up")
            return True
        else:
            print("✗ Failed to retrieve updated order")
            return False

    except Exception as e:
        print(f"✗ Error testing order update: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.disconnect()

def main():
    """Run all tests."""
    print("=" * 60)
    print("Testing StealthOrderManager Schema Migration Fix")
    print("=" * 60)

    # Test 1: Check columns before init
    print("\n→ Checking columns before StealthOrderManager init...")
    cols_before = check_columns_exist()

    # Test 2: Init manager (this should run migrations if needed)
    init_ok = test_stealth_order_manager_init()

    # Test 3: Test order operations
    update_ok = test_order_update()

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary:")
    print("=" * 60)
    print(f"Columns before init: {'✓ Found' if cols_before else '✗ Missing'}")
    print(f"Manager initialization: {'✓ Pass' if init_ok else '✗ Fail'}")
    print(f"Order update test: {'✓ Pass' if update_ok else '✗ Fail'}")

    success = init_ok and update_ok
    print(f"\n{'✓ All tests passed!' if success else '✗ Some tests failed'}")

    return 0 if success else 1

if __name__ == '__main__':
    import sys
    sys.exit(main())
