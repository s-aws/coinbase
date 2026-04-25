#!/usr/bin/env python
"""Check order_parent table schema."""
import sys
sys.path.insert(0, '.')
from database.database import PostgresDB

db = PostgresDB()
db.connect()

print("=" * 80)
print("ORDER_PARENT TABLE SCHEMA")
print("=" * 80)
result = db.execute_query(
    'SELECT column_name, data_type FROM information_schema.columns WHERE table_name = %s ORDER BY column_name;',
    ('order_parent',)
)

if result:
    print(f"Found {len(result)} columns:")
    for row in result:
        col_name = row.get('column_name')
        col_type = row.get('data_type')
        print(f"  - {col_name:40s} {col_type}")
else:
    print("  (no results)")

print("\n" + "=" * 80)
print("RECENT ORDERS IN ORDER_PARENT")
print("=" * 80)
result = db.execute_query(
    '''SELECT id, client_order_id, product_id, side, size, status, current_order_replacement 
       FROM order_parent 
       ORDER BY created_at DESC 
       LIMIT 10;'''
)
if result:
    print(f"Found {len(result)} orders:")
    for row in result:
        id_ = row.get('id')
        coid = row.get('client_order_id')
        prod = row.get('product_id')
        side = row.get('side')
        size = row.get('size')
        status = row.get('status')
        repl = row.get('current_order_replacement')
        size_str = f"{float(size):8.2f}" if size else "N/A"
        print(f"  ID {id_:3d} | {str(coid)[:16]:16s} | {prod:20s} {side:4s} {size_str} | repl={repl}")
else:
    print("  (no results)")

print("\n" + "=" * 80)
print("PARENT ORDER WITH MOST REPLACEMENTS")
print("=" * 80)
result = db.execute_query(
    '''SELECT id, client_order_id, product_id, side, size, status, current_order_replacement 
       FROM order_parent 
       ORDER BY current_order_replacement DESC 
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
    repl = row.get('current_order_replacement')
    size_str = f"{float(size):8.2f}" if size else "N/A"
    print(f"  ID {id_:3d} | {coid}")
    print(f"  Product: {prod}")
    print(f"  Order: {side} {size_str} @ status={status}")
    print(f"  Replacement count: {repl}")
    
    print(f"\n  Child orders for this parent (parent_order_id={coid}):")
    result2 = db.execute_query(
        '''SELECT id, client_order_id, side, size, status, created_at
           FROM order_parent 
           WHERE parent_order_id = %s
           ORDER BY created_at DESC;''',
        (coid,)
    )
    if result2:
        print(f"  Found {len(result2)} child orders:")
        for row2 in result2:
            id2 = row2.get('id')
            coid2 = row2.get('client_order_id')
            side2 = row2.get('side')
            size2 = row2.get('size')
            status2 = row2.get('status')
            created = row2.get('created_at')
            size_str = f"{float(size2):8.2f}" if size2 else "N/A"
            print(f"    ID {id2:3d} | {str(coid2)[:16]:16s} {side2:4s} {size_str} status={status2} created={created}")
    else:
        print("  (no child orders found)")

db.disconnect()
