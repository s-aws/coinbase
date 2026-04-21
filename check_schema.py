#!/usr/bin/env python3
from database.database import PostgresDB

db = PostgresDB()
db.connect()

try:
    with db.get_cursor() as cursor:
        cursor.execute("""
            SELECT column_name, data_type, is_nullable 
            FROM information_schema.columns 
            WHERE table_name = 'stealth_orders' 
            ORDER BY ordinal_position
        """)
        rows = cursor.fetchall()
        print("\nstealth_orders table schema:")
        print("-" * 50)
        for row in rows:
            col_name, data_type, nullable = row
            print(f"{col_name:30} {data_type:15} nullable={nullable}")
finally:
    db.disconnect()
