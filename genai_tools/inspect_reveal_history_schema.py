from database.database import PostgresDB
db = PostgresDB(); db.connect()
rows = db.execute_query(
    "SELECT column_name FROM information_schema.columns "
    "WHERE table_name = 'stealth_order_reveal_history' ORDER BY ordinal_position"
)
print("stealth_order_reveal_history columns:")
for r in rows:
    print(" ", r['column_name'])
db.disconnect()
