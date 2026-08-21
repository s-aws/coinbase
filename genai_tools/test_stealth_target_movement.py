#!/usr/bin/env python3
"""Test stealth order target movement feature.

Tests the newly added target_movement columns and update functionality
for stealth orders.
"""

import sys
from pathlib import Path
import uuid

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.database import PostgresDB
from database.order import (
    update_stealth_order_target_movement,
    get_stealth_order_by_id,
)

def test_update_function():
    """Test the update_stealth_order_target_movement function."""
    print("\n" + "="*60)
    print("TEST 2: Update Function")
    print("="*60)

    db = PostgresDB()
    db.connect()

    try:
        # Create a test stealth order
        test_stealth_id = str(uuid.uuid4())
        print(f"Creating test stealth order: {test_stealth_id[:8]}...")

        with db.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO stealth_orders
                (stealth_order_id, product_id, side, total_size, limit_price, remaining_size,
                 reveal_condition_type, reveal_condition_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                test_stealth_id, 'BTC-USDC', 'BUY', 1.0, 40000.00, 1.0,
                'price', '{"type": "price", "price_threshold": 40000, "direction": "below", "hold_duration_seconds": 2}'
            ))
        print("✅ Test stealth order created")

        # Test update with percentage
        print("\nTest Case 1: Update with percentage (0.5%)")
        success = update_stealth_order_target_movement(
            stealth_order_id=test_stealth_id,
            target_movement=0.005,
            target_movement_type="P"
        )
        print(f"Update result: {success}")

        # Fetch and verify
        order = get_stealth_order_by_id(test_stealth_id)
        if order and float(order.get('target_movement')) == 0.005 and order.get('target_movement_type') == 'P':
            print(f"✅ Verified: target_movement={order['target_movement']}, type={order['target_movement_type']}")
        else:
            print(f"❌ Verification failed: {order}")
            return False

        # Test update with absolute amount
        print("\nTest Case 2: Update with absolute amount ($100)")
        success = update_stealth_order_target_movement(
            stealth_order_id=test_stealth_id,
            target_movement=100.0,
            target_movement_type="A"
        )
        print(f"Update result: {success}")

        # Fetch and verify
        order = get_stealth_order_by_id(test_stealth_id)
        if order and float(order.get('target_movement')) == 100.0 and order.get('target_movement_type') == 'A':
            print(f"✅ Verified: target_movement={order['target_movement']}, type={order['target_movement_type']}")
        else:
            print(f"❌ Verification failed: {order}")
            return False

        # Test clear target movement
        print("\nTest Case 3: Clear target movement (set to None)")
        success = update_stealth_order_target_movement(
            stealth_order_id=test_stealth_id,
            target_movement=None,
            target_movement_type="P"
        )
        print(f"Update result: {success}")

        # Fetch and verify
        order = get_stealth_order_by_id(test_stealth_id)
        if order and order.get('target_movement') is None:
            print(f"✅ Verified: target_movement cleared (None)")
        else:
            print(f"❌ Verification failed: {order}")
            return False

        # Clean up
        print("\nCleaning up test data...")
        with db.get_cursor() as cursor:
            cursor.execute("DELETE FROM stealth_orders WHERE stealth_order_id = %s", (test_stealth_id,))
        print("✅ Test data cleaned up")

        return True
    finally:
        db.disconnect()


def test_ui_scenario():
    """Test a realistic UI scenario."""
    print("\n" + "="*60)
    print("TEST 3: Realistic UI Scenario")
    print("="*60)

    db = PostgresDB()
    db.connect()

    try:
        # Create multiple stealth orders
        orders = []
        print("Creating test stealth orders...")

        for i in range(3):
            order_id = str(uuid.uuid4())
            with db.get_cursor() as cursor:
                cursor.execute("""
                    INSERT INTO stealth_orders
                    (stealth_order_id, product_id, side, total_size, limit_price, remaining_size,
                     reveal_condition_type, reveal_condition_json)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    order_id, f'PRODUCT-{i}', 'BUY', 1.0 + i, 40000.00 + (i*100), 1.0 + i,
                    'price', '{"type": "price", "price_threshold": 40000}'
                ))
            orders.append(order_id)
            print(f"  ✓ Order {i+1}: {order_id[:8]}...")

        # Update each with different target movements
        print("\nUpdating target movements via simulated UI actions...")

        # Order 0: Set to 0.5% (percentage)
        print(f"  1. Setting Order 0 to 0.5% profit target...")
        update_stealth_order_target_movement(orders[0], 0.005, "P")

        # Order 1: Set to $50 absolute
        print(f"  2. Setting Order 1 to $50 absolute target...")
        update_stealth_order_target_movement(orders[1], 50.0, "A")

        # Order 2: Clear target (None)
        print(f"  3. Clearing Order 2 target movement...")
        update_stealth_order_target_movement(orders[2], None, "P")

        # Verify all orders
        print("\nVerifying all updates...")
        results = []
        for i, order_id in enumerate(orders):
            order = get_stealth_order_by_id(order_id)
            target_str = "None"
            if order.get('target_movement'):
                target_str = f"{order['target_movement']}{order['target_movement_type']}"
            results.append((i, order_id[:8], target_str))
            print(f"  Order {i}: target_movement = {target_str}")

        # Expected: [0.005P, 50.0A, None]
        expected = [
            (0, orders[0][:8], "0.005P"),
            (1, orders[1][:8], "50.0A"),
            (2, orders[2][:8], "None")
        ]

        success = True
        for i, (idx, order_id, target) in enumerate(results):
            exp_target = expected[i][2]
            if target == exp_target:
                print(f"  ✓ Order {idx} matches expected target: {exp_target}")
            else:
                print(f"  ✗ Order {idx} mismatch! Expected {exp_target}, got {target}")
                success = False

        # Clean up
        print("\nCleaning up test data...")
        for order_id in orders:
            with db.get_cursor() as cursor:
                cursor.execute("DELETE FROM stealth_orders WHERE stealth_order_id = %s", (order_id,))
        print("✅ All test data cleaned up")

        return success
    finally:
        db.disconnect()


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("STEALTH ORDER TARGET MOVEMENT FEATURE TESTS")
    print("="*60)

    results = {}

    # Run tests
    results['Update Function'] = test_update_function()
    results['UI Scenario'] = test_ui_scenario()

    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)

    for test_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{test_name}: {status}")

    all_passed = all(results.values())
    print("\n" + ("="*60))
    if all_passed:
        print("✅ ALL TESTS PASSED")
        print("="*60)
        print("\nFeature is ready for use! You can now:")
        print("1. Create stealth orders with target movement")
        print("2. Update target movement via the UI edit button (⚙️)")
        print("3. View target movement values in the orders table")
        return 0
    else:
        print("❌ SOME TESTS FAILED")
        print("="*60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
