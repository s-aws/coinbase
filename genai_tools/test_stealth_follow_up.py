#!/usr/bin/env python3
"""Test stealth order parent-child follow-up creation with target movement.

Verifies that when a Parent stealth order fills, a Child stealth order is created
with the inherited target_movement.
"""

import sys
from pathlib import Path
import uuid

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.database import PostgresDB
from core.stealth_order_manager import StealthOrderManager
from database.order import get_stealth_order_by_id

def test_stealth_follow_up_with_target_movement():
    """Test that Child stealth orders inherit parent's target_movement."""
    print("\n" + "="*70)
    print("TEST: Stealth Follow-Up with Target Movement Inheritance")
    print("="*70)

    db = PostgresDB()
    db.connect()

    try:
        # Create stealth manager
        manager = StealthOrderManager(db)

        # 1. Create Parent stealth order with target_movement
        print("\n1. Creating Parent stealth order with target_movement=0.005...")
        parent_stealth_id = manager.create_stealth_order(
            product_id="BTC-USDC",
            side="BUY",
            total_size=1.0,
            limit_price=40000.0,
            reveal_condition={"type": "price", "price_threshold": 40000, "direction": "below", "hold_duration_seconds": 2},
            follow_up_reveal_direction="opposite",
            reason="test_parent"
        )
        print(f"   ✓ Parent created: {parent_stealth_id[:8]}...")

        # Set target_movement on parent
        parent_order = manager._get_stealth_order(parent_stealth_id)
        parent_order["target_movement"] = 0.005
        parent_order["target_movement_type"] = "P"
        manager._update_stealth_order(parent_order)
        print(f"   ✓ Set target_movement=0.005% (P) on parent")

        # Verify parent saved correctly
        parent_db = get_stealth_order_by_id(parent_stealth_id)
        if parent_db and float(parent_db.get('target_movement', 0)) == 0.005:
            print(f"   ✓ Parent target_movement verified in DB")
        else:
            print(f"   ✗ Parent target_movement not saved correctly!")
            return False

        # 2. Create Child stealth order (follow-up)
        print("\n2. Creating Child stealth order via follow-up...")
        child_stealth_id = manager.create_follow_up_stealth_order(
            original_stealth_order_id=parent_stealth_id,
            side="SELL",
            total_size=1.0,
            limit_price=40050.0,
            target_movement=0.005,
            target_movement_type="P"
        )
        print(f"   ✓ Child created: {child_stealth_id[:8]}...")

        # Verify child has correct parent reference
        child_order = manager._get_stealth_order(child_stealth_id)
        if child_order and child_order.get("parent_order_id") == parent_stealth_id:
            print(f"   ✓ Child's parent_order_id correctly set to parent")
        else:
            print(f"   ✗ Child parent_order_id not set correctly!")
            return False

        # Verify child inherited target_movement
        if child_order and float(child_order.get('target_movement', 0)) == 0.005:
            print(f"   ✓ Child inherited target_movement=0.005%")
        else:
            print(f"   ✗ Child target_movement not inherited!")
            return False

        # Verify in database
        child_db = get_stealth_order_by_id(child_stealth_id)
        if child_db and float(child_db.get('target_movement', 0)) == 0.005:
            print(f"   ✓ Child target_movement verified in DB")
        else:
            print(f"   ✗ Child target_movement not in DB!")
            return False

        # 3. Create another Child (grandchild in the chain)
        print("\n3. Creating another Child from the first Child...")
        grandchild_stealth_id = manager.create_follow_up_stealth_order(
            original_stealth_order_id=child_stealth_id,
            side="BUY",
            total_size=1.0,
            limit_price=40100.0
            # Note: NOT explicitly passing target_movement - should inherit from child
        )
        print(f"   ✓ Grandchild created: {grandchild_stealth_id[:8]}...")

        # Verify grandchild has correct parent (the child)
        grandchild_order = manager._get_stealth_order(grandchild_stealth_id)
        if grandchild_order and grandchild_order.get("parent_order_id") == child_stealth_id:
            print(f"   ✓ Grandchild's parent_order_id correctly points to Child")
        else:
            print(f"   ✗ Grandchild parent_order_id incorrect!")
            return False

        # Verify grandchild inherited target_movement (transitively)
        if grandchild_order and float(grandchild_order.get('target_movement', 0)) == 0.005:
            print(f"   ✓ Grandchild inherited target_movement=0.005% from parent Chain")
        else:
            print(f"   ✗ Grandchild target_movement not inherited!")
            return False

        # 4. Clean up
        print("\n4. Cleaning up test data...")
        with db.get_cursor() as cursor:
            cursor.execute("DELETE FROM stealth_orders WHERE stealth_order_id IN (%s, %s, %s)",
                          (parent_stealth_id, child_stealth_id, grandchild_stealth_id))
        print("   ✓ Test data deleted")

        return True

    finally:
        db.disconnect()


def main():
    """Run test."""
    print("\n" + "="*70)
    print("STEALTH ORDER FOLLOW-UP WITH TARGET MOVEMENT TEST")
    print("="*70)

    success = test_stealth_follow_up_with_target_movement()

    print("\n" + "="*70)
    if success:
        print("✅ TEST PASSED")
        print("="*70)
        print("\nStealth order parent-child inheritance works correctly!")
        print("- Parent stealth orders can have target_movement")
        print("- Child stealth orders inherit parent's target_movement")
        print("- Inheritance works transitively through the chain")
        return 0
    else:
        print("❌ TEST FAILED")
        print("="*70)
        return 1


if __name__ == "__main__":
    sys.exit(main())
