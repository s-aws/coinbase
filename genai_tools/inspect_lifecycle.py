from database.database import PostgresDB
db = PostgresDB(); db.connect()

print("=== lifecycle_history columns ===")
rows = db.execute_query(
    "SELECT column_name FROM information_schema.columns "
    "WHERE table_name = 'stealth_order_lifecycle_history' ORDER BY ordinal_position"
)
print(" ", [r['column_name'] for r in rows])

print("\n=== lifecycle_history for stealth ===")
rows = db.execute_query(
    "SELECT * FROM stealth_order_lifecycle_history "
    "WHERE stealth_order_id::text LIKE %s "
    "ORDER BY created_at",
    ("4b6d2185%",),
)
for r in rows:
    print(f"  {dict(r)}")
if not rows:
    print("  (no rows)")

print("\n=== order_event_stream for stealth ===")
try:
    rows = db.execute_query(
        "SELECT * FROM order_event_stream "
        "WHERE client_order_id::text LIKE %s "
        "ORDER BY created_at LIMIT 20",
        ("4b6d2185%",),
    )
    for r in rows:
        print(f"  {dict(r)}")
    if not rows:
        print("  (no rows)")
except Exception as e:
    print(f"  failed: {e}")

db.disconnect()
