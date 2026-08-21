#!/usr/bin/env python3
"""Integration test for stealth order child creation with target movement.

Simulates the scenario where:
1. A Parent stealth order is created with target_movement
2. The Parent is revealed and fills
3. A Child stealth order is automatically created (via order_engine logic)
4. The Child inherits the Parent's target_movement
"""

import sys
from pathlib import Path
import json

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.database import PostgresDB
from core.stealth_order_manager import StealthOrderManager
from database.order import (
    get_stealth_order_by_id,
    insert_order_parent,
    insert_order_child,
    get_parent_order,
    get_child_orders
)
import uuid

def test_stealth_child_creation_with_inheritance():
    """Test that stealth child orders are created with inherited target_movement."""
    print("\n" + "="*70)
    print("TEST: Stealth Child Creation with Target Movement Inheritance")
    print("="*70)

    db = PostgresDB()
    db.connect()

    try:
        manager = StealthOrderManager(db)

        # 1. Create Parent stealth order
        print("\n1. Creating Parent stealth order...")
        parent_stealth_id = manager.create_stealth_order(
            product_id="BTC-USDC",
            side="BUY",
            total_size=1.0,
            limit_price=40000.0,
            reveal_condition={"type": "price", "price_threshold": 40000, "direction": "below"},
            follow_up_reveal_direction="opposite",
            reason="test_integration"
        )
        print(f"   ✓ Parent stealth created: {parent_stealth_id[:8]}...")

        # Set target_movement on parent
        parent_order = manager._get_stealth_order(parent_stealth_id)
        parent_order["target_movement"] = 0.01
        parent_order["target_movement_type"] = "P"
        manager._update_stealth_order(parent_order)
        print(f"   ✓ Set target_movement=0.01% (P) on parent")

        # Verify parent in DB
        parent_db = get_stealth_order_by_id(parent_stealth_id)
        assert parent_db and float(parent_db.get('target_movement', 0)) == 0.01, "Parent target_movement not in DB"
        print(f"   ✓ Parent target_movement verified in DB")

        # 2. Create Parent order reference (simulating what trading engine does)
        print("\n2. Creating Parent order record...")
        parent_order_id = str(uuid.uuid4())
        insert_order_parent(parent_order_id, "BTC-USDC", "BUY", 1.0, 40000.0, 0.01, "P")
        print(f"   ✓ Parent order created: {parent_order_id[:8]}...")

        # 3. Simulate what order_engine does when a stealth order fills
        print("\n3. Creating Child stealth order (simulating order_engine.handle_filled_order)...")

        # Simulate filled order from exchange
        follow_up_side = "SELL"  # Opposite of parent
        follow_up_size = 1.0
        parent_reveal_condition = parent_order["reveal_condition_json"]
        parent_target_movement = parent_order["target_movement"]
        parent_target_movement_type = parent_order.get("target_movement_type", "P")

        # This is what order_engine.handle_filled_order() would call
        child_stealth_id = manager.create_follow_up_stealth_order(
            original_stealth_order_id=parent_stealth_id,
            side=follow_up_side,
            total_size=follow_up_size,
            limit_price=40001.0,
            reveal_condition=parent_reveal_condition,
            follow_up_reveal_direction="opposite",
            notes="Follow-up from filled reveal",
            target_movement=parent_target_movement,
            target_movement_type=parent_target_movement_type
        )

        assert child_stealth_id, "Failed to create child stealth order"
        print(f"   ✓ Child stealth order created: {child_stealth_id[:8]}...")

        # 4. Verify child linkage
        print("\n4. Verifying child-parent relationships...")
        child_stealth = manager._get_stealth_order(child_stealth_id)

        assert child_stealth.get("parent_order_id") == parent_stealth_id, "Child parent linkage incorrect"
        print(f"   ✓ Child linked to correct parent")

        # 5. Verify target_movement inheritance
        print("\n5. Verifying target_movement inheritance...")
        assert float(child_stealth.get("target_movement", 0)) == 0.01, "Child target_movement not inherited"
        print(f"   ✓ Child inherited target_movement=0.01%")

        # Verify in database
        child_db = get_stealth_order_by_id(child_stealth_id)
        assert child_db and float(child_db.get('target_movement', 0)) == 0.01, "Child target_movement not in DB"
        print(f"   ✓ Child target_movement verified in DB")

        # 6. Create corresponding Child order record
        print("\n6. Creating Child order record...")
        child_order_id = str(uuid.uuid4())
        insert_order_child(parent_order_id, child_order_id, "BTC-USDC", follow_up_side, follow_up_size, 40001.0)
        print(f"   ✓ Child order record created: {child_order_id[:8]}...")

        # 7. Verify parent-child relationship in orders table
        print("\n7. Verifying parent-child relationship...")
        child_orders = get_child_orders(parent_order_id)
        assert any(o['client_order_id'] == child_order_id for o in child_orders), "Child not found in orders table"
        print(f"   ✓ Parent-child relationship established in orders table")

        # 8. Create another child to test transitive inheritance
        print("\n8. Testing transitive inheritance (Child → Grandchild)...")
        grandchild_stealth_id = manager.create_follow_up_stealth_order(
            original_stealth_order_id=child_stealth_id,
            side="BUY",
            total_size=1.0,
            limit_price=40050.0
            # Not explicitly passing target_movement - should inherit from child
        )

        assert grandchild_stealth_id, "Failed to create grandchild"
        print(f"   ✓ Grandchild stealth order created: {grandchild_stealth_id[:8]}...")

        grandchild_stealth = manager._get_stealth_order(grandchild_stealth_id)
        assert grandchild_stealth.get("parent_order_id") == child_stealth_id, "Grandchild parent linkage incorrect"
        print(f"   ✓ Grandchild linked to child (not directly to original parent)")

        assert float(grandchild_stealth.get("target_movement", 0)) == 0.01, "Grandchild didn't inherit target_movement"
        print(f"   ✓ Grandchild inherited target_movement=0.01% (transitive)")

        # 9. Clean up
        print("\n9. Cleaning up test data...")
        with db.get_cursor() as cursor:
            cursor.execute("DELETE FROM stealth_orders WHERE stealth_order_id IN (%s, %s, %s)",
                          (parent_stealth_id, child_stealth_id, grandchild_stealth_id))
            cursor.execute("DELETE FROM order_child WHERE client_order_id = %s", (child_order_id,))
            cursor.execute("DELETE FROM order_parent WHERE client_order_id = %s", (parent_order_id,))
        print("   ✓ Test data deleted")

        return True

    finally:
        db.disconnect()


def main():
    """Run integration test."""
    print("\n" + "="*70)
    print("STEALTH ORDER CHILD CREATION INTEGRATION TEST")
    print("="*70)

    try:
        success = test_stealth_child_creation_with_inheritance()
    except AssertionError as e:
        print(f"\n   ✗ Assertion failed: {e}")
        return 1
    except Exception as e:
        print(f"\n   ✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    print("\n" + "="*70)
    if success:
        print("✅ INTEGRATION TEST PASSED")
        print("="*70)
        print("\nStealth order child creation with target_movement verified!")
        print("- Parent stealth orders can have target_movement")
        print("- Child stealth orders inherit parent's target_movement")
        print("- Grandchildren inherit transitively through the chain")
        print("- Parent-child relationships properly established")
        return 0
    else:
        print("❌ INTEGRATION TEST FAILED")
        print("="*70)
        return 1


if __name__ == "__main__":
    sys.exit(main())
