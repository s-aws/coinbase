#!/usr/bin/env python
"""Check the specific parent order from the logs."""
from _bootstrap import ensure_repo_root

ensure_repo_root()

from database.database import PostgresDB

db = PostgresDB()
db.connect()

target_parent_id = "cd341f8d-01f0-4c33-9f37-076de03106d8"

print("=" * 80)
print(f"CHECKING PARENT ORDER: {target_parent_id}")
print("=" * 80)

result = db.execute_query(
    '''SELECT id, client_order_id, product_id, side, size, status, current_order_replacement, max_order_replacement
       FROM order_parent 
       WHERE client_order_id = %s;''',
    (target_parent_id,)
)

if result:
    row = result[0]
    id_ = row.get('id')
    coid = row.get('client_order_id')
    prod = row.get('product_id')
    side = row.get('side')
    size = row.get('size')
    status = row.get('status')
    current_repl = row.get('current_order_replacement')
    max_repl = row.get('max_order_replacement')
    
    print(f"  ID: {id_}")
    print(f"  Client Order ID: {coid}")
    print(f"  Product: {prod}")
    print(f"  Order: {side} {float(size):8.2f}")
    print(f"  Status: {status}")
    print(f"  Replacement Count: {current_repl}/{max_repl}")
    
    print(f"\n  Child orders for this parent:")
    result2 = db.execute_query(
        '''SELECT id, client_order_id, side, size, status, created_at
           FROM order_parent 
           WHERE parent_order_id = %s
           ORDER BY id DESC;''',
        (coid,)
    )
    
    if result2:
        print(f"  Found {len(result2)} child orders:")
        for i, row2 in enumerate(result2):
            id2 = row2.get('id')
            coid2 = row2.get('client_order_id')
            side2 = row2.get('side')
            size2 = row2.get('size')
            status2 = row2.get('status')
            created = row2.get('created_at')
            size_str = f"{float(size2):8.2f}" if size2 else "N/A"
            print(f"    {i+1}. ID {id2:3d} | {str(coid2)[:16]:16s} {side2:4s} {size_str} status={status2:10s} created={created}")
    else:
        print("  (no child orders found)")
else:
    print(f"  Parent order not found!")

db.disconnect()
