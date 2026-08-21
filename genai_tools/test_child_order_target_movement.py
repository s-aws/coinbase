#!/usr/bin/env python3
"""
Test script to verify child orders inherit parent's target_movement.

This script tests the fix for the issue where child orders weren't
inheriting the parent's target_movement and target_movement_type values.
"""

from database.database import PostgresDB
from database.order import (
    create_order_parent_table,
    create_order_child_table,
    add_missing_order_child_target_movement_columns,
    insert_order_parent,
    insert_order_child,
    get_parent_order,
    get_child_orders,
)

def test_child_order_inherits_target_movement():
    """Test that child orders inherit parent's target_movement."""
    db = PostgresDB()

    try:
        print("=" * 70)
        print("TEST: Child Orders Inherit Parent Target Movement")
        print("=" * 70)

        # Ensure tables exist with all columns
        print("\n1. Creating/updating tables...")
        create_order_parent_table()
        create_order_child_table()
        add_missing_order_child_target_movement_columns()
        print("   ✓ Tables ready with target_movement columns")

        # Create a parent order with target_movement
        print("\n2. Creating parent order with target_movement=0.005 (0.5%)...")
        parent_id = insert_order_parent(
            client_order_id="test_parent_001",
            product_id="BTC-USDC",
            side="BUY",
            size=1.0,
            price=50000.0,
            target_movement=0.005,
            target_movement_type="P",
            max_order_replacement=3,
            current_order_replacement=0,
            status="OPEN"
        )
        print(f"   ✓ Parent order created with ID: {parent_id}")

        # Retrieve the parent to verify
        parent = get_parent_order("test_parent_001")
        if parent:
            print(f"   ✓ Parent order retrieved:")
            print(f"     - client_order_id: {parent['client_order_id']}")
            print(f"     - target_movement: {parent['target_movement']}")
            print(f"     - target_movement_type: {parent['target_movement_type']}")

        # Create a child order that inherits parent's target_movement
        print("\n3. Creating child order inheriting parent's target_movement...")
        child_id = insert_order_child(
            parent_client_order_id="test_parent_001",
            client_order_id="test_child_001",
            product_id="BTC-USDC",
            side="SELL",
            size=1.0,
            price=50250.0,
            status="OPEN",
            target_movement=parent['target_movement'],  # Inherit from parent
            target_movement_type=parent['target_movement_type']
        )
        print(f"   ✓ Child order created with ID: {child_id}")

        # Retrieve the child order and verify it has target_movement
        children = get_child_orders("test_parent_001")
        if children:
            child = children[0]
            print(f"   ✓ Child order retrieved:")
            print(f"     - client_order_id: {child['client_order_id']}")
            print(f"     - parent_client_order_id: {child['parent_client_order_id']}")
            print(f"     - target_movement: {child.get('target_movement')}")
            print(f"     - target_movement_type: {child.get('target_movement_type')}")

            # Verify inheritance
            if child.get('target_movement') == parent['target_movement']:
                print("\n   ✓ SUCCESS: Child order correctly inherited parent's target_movement!")
            else:
                print("\n   ✗ FAILED: Child order did not inherit target_movement")
                return False

            if child.get('target_movement_type') == parent['target_movement_type']:
                print("   ✓ SUCCESS: Child order correctly inherited parent's target_movement_type!")
            else:
                print("   ✗ FAILED: Child order did not inherit target_movement_type")
                return False
        else:
            print("\n   ✗ FAILED: Could not retrieve child orders")
            return False

        # Test with multiple children
        print("\n4. Creating additional child orders to test multiple inheritance...")
        for i in range(2, 4):
            child_id = insert_order_child(
                parent_client_order_id="test_parent_001",
                client_order_id=f"test_child_00{i}",
                product_id="BTC-USDC",
                side="SELL",
                size=0.5,
                price=50250.0 + (i * 100),
                status="PENDING",
                target_movement=parent['target_movement'],
                target_movement_type=parent['target_movement_type']
            )
            print(f"   ✓ Created child order {i} with ID: {child_id}")

        # Verify all children have the target_movement
        all_children = get_child_orders("test_parent_001")
        print(f"\n5. Verifying all {len(all_children)} child orders inherited target_movement...")
        all_valid = True
        for i, child in enumerate(all_children, 1):
            if child.get('target_movement') == parent['target_movement']:
                print(f"   ✓ Child {i} ({child['client_order_id']}): target_movement={child.get('target_movement')}")
            else:
                print(f"   ✗ Child {i} ({child['client_order_id']}): MISSING or INCORRECT target_movement")
                all_valid = False

        if all_valid:
            print("\n" + "=" * 70)
            print("✓ ALL TESTS PASSED!")
            print("=" * 70)
            print("\nFix verified: Child orders now correctly inherit parent's target_movement values.")
            return True
        else:
            print("\n" + "=" * 70)
            print("✗ SOME TESTS FAILED")
            print("=" * 70)
            return False

    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.disconnect()


if __name__ == "__main__":
    success = test_child_order_inherits_target_movement()
    exit(0 if success else 1)
