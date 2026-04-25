#!/usr/bin/env python
"""Check which tables exist in the database."""
import sys
sys.path.insert(0, '.')
from database.database import PostgresDB

db = PostgresDB()
db.connect()

result = db.execute_query(
    '''SELECT table_name FROM information_schema.tables 
       WHERE table_schema = 'public' 
       ORDER BY table_name;'''
)

print("=" * 80)
print("TABLES CURRENTLY IN DATABASE")
print("=" * 80)
if result:
    print(f"Found {len(result)} tables:")
    for row in result:
        table_name = row.get('table_name') if isinstance(row, dict) else row[0]
        print(f"  - {table_name}")
else:
    print("  (no tables found)")

db.disconnect()
