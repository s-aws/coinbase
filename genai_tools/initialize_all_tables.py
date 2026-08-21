"""
Initialize all database tables for the trading engine.

This script creates all required tables from scratch:
- order_parent
- stealth_orders
- fill_ledger
- conditional_orders
- Plus supporting tables for snapshots, history, and moves
"""

import sys
sys.path.insert(0, 'e:\\coinbase')

from database.database import PostgresDB
from database.order import (
    create_order_parent_table,
    create_stealth_orders_table,
    create_fill_ledger_table,
    create_conditional_orders_table,
    create_stealth_order_snapshots_table,
    create_stealth_order_reveal_history_table,
    create_order_moves_table
)
from logging_service import get_logger

logger = get_logger("DatabaseInitializer")

def initialize_all_tables():
    """Create all database tables."""
    print("\n" + "="*60)
    print("INITIALIZING ALL DATABASE TABLES")
    print("="*60)

    tables_to_create = [
        ("order_parent", create_order_parent_table),
        ("stealth_orders", create_stealth_orders_table),
        ("stealth_order_snapshots", create_stealth_order_snapshots_table),
        ("stealth_order_reveal_history", create_stealth_order_reveal_history_table),
        ("order_moves", create_order_moves_table),
        ("fill_ledger", create_fill_ledger_table),
        ("conditional_orders", create_conditional_orders_table),
    ]

    db = PostgresDB()
    db.connect()

    for table_name, create_func in tables_to_create:
        try:
            print(f"\nCreating {table_name}...", end=" ")
            create_func()
            print("✓ SUCCESS")
            logger.info(f"✓ Table '{table_name}' created successfully")
        except Exception as e:
            print(f"✗ FAILED: {e}")
            logger.error(f"✗ Failed to create '{table_name}': {e}")

    db.disconnect()

    print("\n" + "="*60)
    print("VERIFICATION - Checking table counts")
    print("="*60)

    db = PostgresDB()
    db.connect()

    verification_tables = {
        'order_parent': 'Parent Orders',
        'stealth_orders': 'Stealth Orders',
        'stealth_order_snapshots': 'Stealth Snapshots',
        'stealth_order_reveal_history': 'Reveal History',
        'order_moves': 'Order Moves',
        'fill_ledger': 'Fill Ledger',
        'conditional_orders': 'Conditional Orders'
    }

    all_exist = True
    for table_name, display_name in verification_tables.items():
        try:
            results = db.execute_query(
                f"SELECT COUNT(*) as count FROM {table_name}"
            )
            count = results[0][0] if results else 0
            print(f"✓ {display_name:30} ({table_name:30}) - {count:6} rows")
        except Exception as e:
            print(f"✗ {display_name:30} ({table_name:30}) - ERROR")
            all_exist = False

    db.disconnect()

    print("\n" + "="*60)
    if all_exist:
        print("✅ ALL TABLES INITIALIZED SUCCESSFULLY")
    else:
        print("⚠️  SOME TABLES FAILED - SEE ERRORS ABOVE")
    print("="*60 + "\n")

    return all_exist

if __name__ == "__main__":
    success = initialize_all_tables()
    sys.exit(0 if success else 1)
