from _bootstrap import ensure_repo_root

ensure_repo_root()

from database.database import PostgresDB

db = PostgresDB()

# Get sample fills
fills = db.execute_query('SELECT client_order_id, instrument FROM fill_ledger LIMIT 3')
print("Sample fills:")
for f in fills:
    print(f"  {f['client_order_id'][:8]}... | {f['instrument']}")

# Check relationships
if fills:
    cid = fills[0]['client_order_id']
    
    # Check stealth_orders
    stealth = db.execute_query('SELECT stealth_order_id, parent_order_id FROM stealth_orders WHERE stealth_order_id = %s', (cid,))
    if stealth:
        print(f"\nFound stealth match for {cid[:8]}...")
        print(f"  Parent: {stealth[0]['parent_order_id']}")
    else:
        # Check order_parent
        parent = db.execute_query('SELECT client_order_id, parent_order_id FROM order_parent WHERE client_order_id = %s', (cid,))
        if parent:
            print(f"\nFound parent order match for {cid[:8]}...")
            print(f"  Parent ID: {parent[0]['parent_order_id']}")
        else:
            print(f"\n{cid[:8]}... doesn't match parent or stealth directly")
            # Check if it's a stealth order by looking at stealth_order_snapshots
            snap = db.execute_query('SELECT parent_order_id, stealth_order_id FROM stealth_order_snapshots WHERE stealth_order_id = %s LIMIT 1', (cid,))
            if snap:
                print(f"  Found in stealth_order_snapshots!")
                print(f"  Parent: {snap[0]['parent_order_id']}")

db.disconnect()
