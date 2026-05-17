#!/usr/bin/env python
"""Audit database schema to find what's actually there."""
from _bootstrap import ensure_repo_root

ensure_repo_root()

from database.database import PostgresDB

db = PostgresDB()
db.connect()

print("=" * 80)
print("STEALTH_ORDERS TABLE SCHEMA")
print("=" * 80)
result = db.execute_query(
    'SELECT column_name, data_type FROM information_schema.columns WHERE table_name = %s ORDER BY column_name;',
    ('stealth_orders',)
)

if result:
    print(f"Found {len(result)} columns:")
    for row in result:
        col_name = row.get('column_name', row[0] if isinstance(row, (list, tuple)) else 'unknown')
        col_type = row.get('data_type', row[1] if isinstance(row, (list, tuple)) else 'unknown')
        print(f"  - {col_name:40s} {col_type}")
else:
    print("  (no results)")

print("\n" + "=" * 80)
print("CHECK: anchor_repricing_policy_json column")
print("=" * 80)
result = db.execute_query(
    'SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s);',
    ('stealth_orders', 'anchor_repricing_policy_json')
)
exists = False
if result:
    first_row = result[0]
    if isinstance(first_row, dict):
        exists = first_row.get('exists', False)
    else:
        exists = first_row[0]
print(f"Column exists: {exists}")

print("\n" + "=" * 80)
print("CHECK: anchor_repricing_state_json column")
print("=" * 80)
result = db.execute_query(
    'SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s);',
    ('stealth_orders', 'anchor_repricing_state_json')
)
exists = False
if result:
    first_row = result[0]
    if isinstance(first_row, dict):
        exists = first_row.get('exists', False)
    else:
        exists = first_row[0]
print(f"Column exists: {exists}")

print("\n" + "=" * 80)
print("RECENT PARENT ORDERS (last 5)")
print("=" * 80)
result = db.execute_query(
    '''SELECT id, client_order_id, product_id, side, size, status, replacement_count 
       FROM parent_orders 
       ORDER BY created_at DESC 
       LIMIT 5;'''
)
if result:
    for row in result:
        id_ = row.get('id')
        coid = row.get('client_order_id')
        prod = row.get('product_id')
        side = row.get('side')
        size = row.get('size')
        status = row.get('status')
        repl = row.get('replacement_count')
        print(f"  ID {id_:3d} | {coid} | {prod} {side} {size:5.1f} | status={status} | repl_count={repl}")
else:
    print("  (no results)")

print("\n" + "=" * 80)
print("PARENT ORDER WITH MOST REPLACEMENTS")
print("=" * 80)
result = db.execute_query(
    '''SELECT id, client_order_id, product_id, side, size, status, replacement_count 
       FROM parent_orders 
       ORDER BY replacement_count DESC 
       LIMIT 1;'''
)
if result:
    row = result[0]
    id_ = row.get('id')
    coid = row.get('client_order_id')
    prod = row.get('product_id')
    side = row.get('side')
    size = row.get('size')
    status = row.get('status')
    repl = row.get('replacement_count')
    print(f"  ID {id_:3d} | {coid}")
    print(f"  Product: {prod}")
    print(f"  Order: {side} {size} @ status={status}")
    print(f"  Replacement count: {repl}")
    
    print("\n  Child orders for this parent:")
    result2 = db.execute_query(
        '''SELECT client_order_id, side, size, status, created_at
           FROM parent_orders 
           WHERE parent_order_id = %s
           ORDER BY created_at DESC;''',
        (id_,)
    )
    if result2:
        for row2 in result2:
            coid2 = row2.get('client_order_id')
            side2 = row2.get('side')
            size2 = row2.get('size')
            status2 = row2.get('status')
            created = row2.get('created_at')
            print(f"    - {coid2} {side2} {size2:5.1f} status={status2} created={created}")

db.disconnect()
print("\n" + "=" * 80)
