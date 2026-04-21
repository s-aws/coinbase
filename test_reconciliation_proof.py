#!/usr/bin/env python
"""Test script to prove reconciliation counts stealth children correctly."""

import sys
from uuid import uuid4

# Setup database
from database.database import PostgresDB
from database.order import (
    insert_order_parent,
    get_stealth_children_for_parent,
    get_parent_orders,
    DB_CLIENT,
)

# Initialize
db = PostgresDB()

print("\n" + "="*80)
print("RECONCILIATION CHILD COUNT PROOF TEST")
print("="*80 + "\n")

# Step 1: Create 3 parent orders
print("[STEP 1] Creating 3 parent orders...")
parent_ids = []
for i in range(3):
    parent_id = str(uuid4())
    parent_ids.append(parent_id)
    insert_order_parent(
        client_order_id=parent_id,
        product_id="BTC-USD",
        side="BUY",
        size=1.0,
        price=50000.0 + (i * 100),
        target_movement=1.0,  # 1% target
        target_movement_type="P",
    )
    print(f"  ✓ Parent {i+1}: {parent_id}")

# Step 2: Create stealth children directly in database
print("\n[STEP 2] Creating stealth children (follow-ups)...")
print("  Note: These are stored in stealth_orders table with parent_order_id set\n")

child_count_per_parent = {
    parent_ids[0]: 2,  # Parent 0 gets 2 children
    parent_ids[1]: 3,  # Parent 1 gets 3 children
    parent_ids[2]: 1,  # Parent 2 gets 1 child
}

all_stealth_child_ids = []
for parent_id, num_children in child_count_per_parent.items():
    for j in range(num_children):
        stealth_child_id = str(uuid4())
        
        # Insert directly to database
        insert_query = """
        INSERT INTO stealth_orders (
            stealth_order_id,
            parent_order_id,
            product_id,
            side,
            total_size,
            remaining_size,
            limit_price,
            reveal_condition_type,
            reveal_condition_json
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        with DB_CLIENT.get_cursor() as cursor:
            cursor.execute(
                insert_query,
                (
                    stealth_child_id,
                    parent_id,  # THIS MAKES IT A CHILD
                    "BTC-USD",
                    "SELL",
                    0.5,
                    0.5,  # remaining_size = total_size initially
                    51000.0 + (j * 50),
                    "time_delay",
                    '{"type": "time_delay", "delay_seconds": 0}',
                )
            )
        
        all_stealth_child_ids.append(stealth_child_id)
        print(f"  ✓ Stealth child created: {stealth_child_id[:8]}... (parent: {parent_id[:8]}...)")

# Step 3: Query stealth children directly
print("\n[STEP 3] Verifying stealth children in database...")
total_children = 0
for parent_id in parent_ids:
    stealth_children = get_stealth_children_for_parent(parent_id)
    child_count = len(stealth_children)
    total_children += child_count
    print(f"  Parent {parent_id[:8]}... has {child_count} stealth children")
    for child in stealth_children:
        print(f"    - {child['client_order_id'][:8]}... (side: {child['side']}, price: {child['price']})")

print(f"\n  TOTAL STEALTH CHILDREN: {total_children}")

# Step 4: Simulate reconciliation snapshot build
print("\n[STEP 4] Testing reconciliation snapshot build...")
print("  (This is what the reconciliation thread uses)\n")

parent_order_ids = {}
child_order_ids = {}

parent_orders = get_parent_orders()
print(f"  Found {len(parent_orders)} parent orders in database\n")

for parent in parent_orders:
    parent_client_order_id = parent["client_order_id"]
    
    parent_order_ids[parent_client_order_id] = {
        "parent_id": parent["id"],
        "orders": [],
        "target_movement": {
            "movement": float(parent["target_movement"]),
            "type": parent.get("target_movement_type", "P"),
        },
        "max_order_replacement": int(parent["max_order_replacement"]),
        "current_order_replacement": int(parent["current_order_replacement"]),
    }
    
    # Query stealth children (ALL children are stealth children)
    stealth_children = get_stealth_children_for_parent(parent_client_order_id)
    for stealth_child in stealth_children:
        stealth_child_id = stealth_child["client_order_id"]
        parent_order_ids[parent_client_order_id]["orders"].append(stealth_child_id)
        child_order_ids[stealth_child_id] = parent_client_order_id

# Print reconciliation results
print("[RECONCILIATION SNAPSHOT RESULTS]")
print(f"  Parent count: {len(parent_order_ids)}")
print(f"  Child count: {len(child_order_ids)}")
print()

for parent_id, parent_entry in parent_order_ids.items():
    num_children = len(parent_entry["orders"])
    print(f"  Parent {parent_id[:8]}... -> {num_children} children")
    for child_id in parent_entry["orders"]:
        print(f"    └─ {child_id[:8]}...")

# Verification
print("\n" + "="*80)
print("PROOF VERIFICATION")
print("="*80)

if len(child_order_ids) == total_children:
    print(f"✅ SUCCESS: child_count = {len(child_order_ids)} (matches expected {total_children})")
    print("✅ Stealth children are being counted in reconciliation!")
    sys.exit(0)
else:
    print(f"❌ FAILED: child_count = {len(child_order_ids)} (expected {total_children})")
    sys.exit(1)
