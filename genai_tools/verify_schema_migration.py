#!/usr/bin/env python3
"""
Verify that the stealth_orders table has all required columns for anchor repricing.

This script checks if the migration for anchor_repricing_policy_json and
anchor_repricing_state_json columns has been applied to the stealth_orders table.
"""

import sys
from database.database import PostgresDB

def check_column_exists(db_client, table_name: str, column_name: str) -> bool:
    """Check if a column exists in a PostgreSQL table."""
    query = """
    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
    );
    """
    try:
        result = db_client.execute_query(query, (table_name, column_name))
        return result[0][0] if result else False
    except Exception as e:
        print(f"✗ Error checking column: {e}")
        return False

def main():
    """Verify schema and run migrations if needed."""
    db = PostgresDB()

    try:
        db.connect()
        print("✓ Connected to database")

        # Check for required columns
        columns_to_check = [
            'anchor_repricing_policy_json',
            'anchor_repricing_state_json',
        ]

        all_exist = True
        for col in columns_to_check:
            exists = check_column_exists(db, 'stealth_orders', col)
            status = "✓" if exists else "✗"
            print(f"{status} Column '{col}' exists: {exists}")
            all_exist = all_exist and exists

        if not all_exist:
            print("\n→ Running schema migration...")
            from database.order import create_stealth_orders_table
            create_stealth_orders_table()
            print("✓ Migration completed")

            # Re-check columns
            print("\n→ Verifying after migration...")
            all_exist = True
            for col in columns_to_check:
                exists = check_column_exists(db, 'stealth_orders', col)
                status = "✓" if exists else "✗"
                print(f"{status} Column '{col}' exists: {exists}")
                all_exist = all_exist and exists

        if all_exist:
            print("\n✓ Schema migration successful!")
            return 0
        else:
            print("\n✗ Schema migration failed - columns still missing")
            return 1

    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        db.disconnect()

if __name__ == '__main__':
    sys.exit(main())
