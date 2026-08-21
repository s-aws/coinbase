"""Quick audit: stealth_orders vs order_parent target_movement persistence."""
import sys
sys.path.insert(0, '.')
from database.database import PostgresDB

db = PostgresDB()
db.connect()

print("=== stealth_orders (latest 5) ===")
rows = db.execute_query(
    "SELECT stealth_order_id, side, limit_price, target_movement, "
    "target_movement_type, reveal_condition_json "
    "FROM stealth_orders ORDER BY created_at DESC LIMIT 5"
)
for r in rows or []:
    print(r)

print("\n=== order_parent (latest 5) ===")
rows = db.execute_query(
    "SELECT client_order_id, side, price, target_movement, "
    "target_movement_type, parent_order_id, status "
    "FROM order_parent ORDER BY created_at DESC LIMIT 5"
)
for r in rows or []:
    print(r)

db.disconnect()
