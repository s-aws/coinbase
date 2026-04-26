#!/usr/bin/env python
"""Comprehensive audit of logs against database state."""
import sys
sys.path.insert(0, '.')
from database.database import PostgresDB
from decimal import Decimal

db = PostgresDB()
db.connect()

print("=" * 100)
print("AUDIT: Logs vs Database State")
print("=" * 100)

# Get all parent orders
print("\n[1] PARENT ORDERS")
print("-" * 100)
result = db.execute_query(
    '''SELECT id, client_order_id, product_id, side, size, status, 
              current_order_replacement, max_order_replacement, created_at
       FROM order_parent 
       ORDER BY created_at DESC;'''
)

if result:
    print(f"Found {len(result)} parent orders:\n")
    for row in result:
        id_ = row.get('id')
        coid = row.get('client_order_id')
        prod = row.get('product_id')
        side = row.get('side')
        size = row.get('size')
        status = row.get('status')
        curr_repl = row.get('current_order_replacement')
        max_repl = row.get('max_order_replacement')
        created = row.get('created_at')
        size_str = f"{float(size):.2f}" if size else "N/A"
        print(f"  ID {id_:2d} | {str(coid)[:16]:16s}... | {prod} {side:4s} {size_str:6s} | status={status:8s} | repl={curr_repl}/{max_repl} | created={created}")
else:
    print("  (no parent orders found)")

# Check parent-child relationships
print("\n[2] PARENT-CHILD RELATIONSHIPS")
print("-" * 100)
result = db.execute_query(
    '''SELECT id, client_order_id, parent_order_id, side, size, status
       FROM order_parent 
       WHERE parent_order_id IS NOT NULL
       ORDER BY id;'''
)

if result:
    print(f"Found {len(result)} child orders:\n")
    for row in result:
        id_ = row.get('id')
        coid = row.get('client_order_id')
        parent_id = row.get('parent_order_id')
        side = row.get('side')
        size = row.get('size')
        status = row.get('status')
        size_str = f"{float(size):.2f}" if size else "N/A"
        print(f"  Child ID {id_:2d} | {str(coid)[:16]:16s}... | parent={str(parent_id)[:16]:16s}... | {side} {size_str:6s} | status={status}")
else:
    print("  (no child orders found)")

# Verify replacement counts match actual child counts
print("\n[3] VERIFICATION: Replacement Count vs Actual Children")
print("-" * 100)
result = db.execute_query(
    '''SELECT id, client_order_id, current_order_replacement
       FROM order_parent 
       WHERE parent_order_id IS NULL
       ORDER BY id;'''
)

if result:
    all_match = True
    for row in result:
        parent_id = row.get('id')
        parent_coid = row.get('client_order_id')
        recorded_count = row.get('current_order_replacement')
        
        # Count actual children
        children_result = db.execute_query(
            '''SELECT COUNT(*) as cnt FROM order_parent 
               WHERE parent_order_id = %s;''',
            (parent_coid,)
        )
        actual_count = children_result[0].get('cnt', 0) if children_result else 0
        
        match = "✓ MATCH" if recorded_count == actual_count else f"✗ MISMATCH"
        print(f"  Parent ID {parent_id:2d} ({str(parent_coid)[:12]:12s}...): recorded={recorded_count}, actual={actual_count} {match}")
        if recorded_count != actual_count:
            all_match = False
    
    if all_match:
        print("\n  ✓ All replacement counts match actual children!")
    else:
        print("\n  ✗ ISSUE: Some replacement counts don't match actual children")
else:
    print("  (no parent orders found)")

# Check stealth_orders table for the new columns
print("\n[4] STEALTH_ORDERS TABLE: New Columns Check")
print("-" * 100)
result = db.execute_query(
    '''SELECT stealth_order_id, parent_order_id, side, total_size, limit_price, 
              status, anchor_repricing_policy_json, anchor_repricing_state_json
       FROM stealth_orders 
       ORDER BY created_at DESC 
       LIMIT 5;'''
)

if result:
    print(f"Found {len(result)} recent stealth orders:\n")
    for row in result:
        soid = row.get('stealth_order_id')
        parent_id = row.get('parent_order_id')
        side = row.get('side')
        size = row.get('total_size')
        price = row.get('limit_price')
        status = row.get('status')
        anchor_policy = row.get('anchor_repricing_policy_json')
        anchor_state = row.get('anchor_repricing_state_json')
        
        size_str = f"{float(size):.1f}" if size else "N/A"
        price_str = f"{float(price):.2f}" if price else "N/A"
        parent_str = str(parent_id)[:16] if parent_id else "None"
        
        print(f"  {str(soid)[:16]:16s}... | {side} {size_str:5s} @ {price_str:8s} | status={status:10s} | parent={parent_str}...")
        print(f"    anchor_repricing_policy_json: {anchor_policy}")
        print(f"    anchor_repricing_state_json: {anchor_state}")
else:
    print("  (no stealth orders found)")

# Check fill ledger
print("\n[5] FILL LEDGER: Recent Fills")
print("-" * 100)
result = db.execute_query(
    '''SELECT trade_id, instrument, side, quantity, price, fees, created_at
       FROM fill_ledger 
       ORDER BY created_at DESC 
       LIMIT 5;'''
)

if result:
    print(f"Found {len(result)} recent fills:\n")
    for row in result:
        trade_id = row.get('trade_id')
        instrument = row.get('instrument')
        side = row.get('side')
        qty = row.get('quantity')
        price = row.get('price')
        fees = row.get('fees')
        created = row.get('created_at')
        
        qty_str = f"{float(qty):.2f}" if qty else "N/A"
        price_str = f"{float(price):.2f}" if price else "N/A"
        fees_str = f"{float(fees):.5f}" if fees else "N/A"
        
        print(f"  {instrument:16s} | {side} {qty_str:6s} @ {price_str:10s} | fees={fees_str:10s} | {created}")
else:
    print("  (no fills found)")

print("\n" + "=" * 100)
print("AUDIT COMPLETE")
print("=" * 100)

db.disconnect()
