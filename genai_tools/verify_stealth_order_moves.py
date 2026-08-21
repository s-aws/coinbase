"""Verify stealth_order_moves table exists with expected columns."""
from database.database import PostgresDB

db = PostgresDB()
cols = db.execute_query(
    "SELECT column_name, data_type FROM information_schema.columns "
    "WHERE table_name=%s ORDER BY ordinal_position",
    ("stealth_order_moves",),
)
print("--columns--")
for row in cols:
    print(f"  {row['column_name']}: {row['data_type']}")

idx = db.execute_query(
    "SELECT indexname FROM pg_indexes WHERE tablename=%s",
    ("stealth_order_moves",),
)
print("--indexes--")
for row in idx:
    print(f"  {row['indexname']}")
