"""Temporary audit script — do not commit."""
from database.order import DB_CLIENT

print("=== stealth_orders for 2f274206 ===")
rows = DB_CLIENT.execute_query(
    "SELECT stealth_order_id, parent_order_id, status, total_size, revealed_size FROM stealth_orders WHERE stealth_order_id = %s",
    ("2f274206-ec40-49db-8302-e53a951bdccb",),
)
for r in rows:
    print(r)

print("\n=== order_parent rows id>=60 ===")
rows = DB_CLIENT.execute_query(
    "SELECT id, client_order_id, parent_order_id, status, max_order_replacement, current_order_replacement, created_at FROM order_parent WHERE id >= 60 ORDER BY id"
)
for r in rows:
    print(r)

print("\n=== All order_parent where parent_order_id IS NULL but client_order_id appears in stealth_orders.parent_order_id (i.e. orphan reveal placements) ===")
rows = DB_CLIENT.execute_query("""
    SELECT op.id, op.client_order_id, op.parent_order_id, op.status, op.created_at
    FROM order_parent op
    WHERE op.parent_order_id IS NULL
      AND EXISTS (
        SELECT 1 FROM order_parent op2
        WHERE op2.client_order_id != op.client_order_id
          AND op2.created_at < op.created_at
          AND op2.product_id = op.product_id
      )
    ORDER BY op.id
""")
print(f"(broad list, count={len(rows)})")

print("\n=== partial_fill_progress for f6281a12 ===")
try:
    rows = DB_CLIENT.execute_query(
        "SELECT client_order_id, status, filled_size, remaining_size FROM partial_fill_progress WHERE client_order_id = %s",
        ("f6281a12-8b4d-43e1-9059-553bd832ed96",),
    )
    for r in rows:
        print(r)
except Exception as e:
    print("partial_fill_progress query err:", e)
