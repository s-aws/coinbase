"""
Verify tables exist in PostgreSQL database.
"""

import sys
sys.path.insert(0, 'e:\\coinbase')

import psycopg2

try:
    # Connect directly with psycopg2
    conn = psycopg2.connect(
        host="127.0.0.1",
        port=5432,
        database="postgres",
        user="postgres",
        password="postgres"
    )
    cursor = conn.cursor()

    # Query to list all tables
    cursor.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema='public'
        ORDER BY table_name
    """)

    tables = cursor.fetchall()

    print("\n" + "="*60)
    print("TABLES IN POSTGRES DATABASE")
    print("="*60)

    expected_tables = {
        'order_parent',
        'stealth_orders',
        'stealth_order_snapshots',
        'stealth_order_reveal_history',
        'order_moves',
        'fill_ledger',
        'conditional_orders'
    }

    found_tables = set()
    if tables:
        for (table_name,) in tables:
            status = "✓" if table_name in expected_tables else " "
            print(f"{status} {table_name}")
            if table_name in expected_tables:
                found_tables.add(table_name)

    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"Total tables found: {len(tables)}")
    print(f"Expected tables found: {len(found_tables)}/{len(expected_tables)}")

    missing = expected_tables - found_tables
    if missing:
        print(f"\n⚠️  Missing tables: {', '.join(sorted(missing))}")
    else:
        print("\n✅ All expected tables exist!")

    # Show row counts for expected tables
    print("\n" + "="*60)
    print("ROW COUNTS")
    print("="*60)

    for table in sorted(expected_tables):
        if table in found_tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            print(f"{table:35} - {count:6} rows")

    cursor.close()
    conn.close()

except psycopg2.Error as e:
    print(f"Database error: {e}")
    sys.exit(1)
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
