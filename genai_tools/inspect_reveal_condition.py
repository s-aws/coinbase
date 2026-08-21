from database.database import PostgresDB
import json
db = PostgresDB(); db.connect()
rows = db.execute_query(
    "SELECT reveal_condition_type, reveal_condition_json FROM stealth_orders "
    "WHERE stealth_order_id::text LIKE %s",
    ("4b6d2185%",),
)
for r in rows:
    print("type:", r['reveal_condition_type'])
    print("json:", json.dumps(r['reveal_condition_json'], indent=2))
db.disconnect()
