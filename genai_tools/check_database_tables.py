"""
Diagnostic script to check database table status and counts.
"""

import sys
sys.path.insert(0, 'e:\\coinbase')

from database.database import PostgresDB
from database.order import (
    create_order_parent_table,
    create_stealth_orders_table,
    create_fill_ledger_table,
    create_conditional_orders_table
)

def check_tables():
    """Check which tables exist and their row counts."""
    db = PostgresDB()
    db.connect()

    print("\n" + "="*60)
    print("DATABASE TABLE STATUS")
    print("="*60)

    tables = {
        'order_parent': 'Parent Orders',
        'order_child': 'Child Orders',
        'stealth_orders': 'Stealth Orders',
        'fill_ledger': 'Fill Ledger',
        'conditional_orders': 'Conditional Orders'
    }

    for table_name, display_name in tables.items():
        try:
            results = db.execute_query(
                f"SELECT COUNT(*) as count FROM {table_name}"
            )
            count = results[0][0] if results else 0
            print(f"✓ {display_name:30} ({table_name:25}) - {count:6} rows")
        except Exception as e:
            print(f"✗ {display_name:30} ({table_name:25}) - TABLE NOT FOUND or ERROR")
            print(f"  Error: {str(e)[:80]}")

    print("\n" + "="*60)
    print("DETAILED STATISTICS")
    print("="*60)

    # Show sample data from each table
    for table_name, display_name in tables.items():
        try:
            results = db.execute_query(
                f"SELECT COUNT(*) as count FROM {table_name}"
            )
            count = results[0][0] if results else 0

            if count > 0:
                print(f"\n{display_name} ({count} rows):")
                # Get column info
                col_results = db.execute_query(
                    f"""
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_name = '{table_name}'
                    ORDER BY ordinal_position
                    """
                )
                print(f"  Columns: {', '.join([col[0] for col in col_results])}")

                # Get sample rows (limit 3)
                sample_results = db.execute_query(
                    f"SELECT * FROM {table_name} LIMIT 3"
                )
                for i, row in enumerate(sample_results, 1):
                    print(f"  Row {i}: {str(row)[:100]}...")
        except Exception as e:
            pass

    # Check LOT_TRACKING_AVAILABLE
    print("\n" + "="*60)
    print("LOT TRACKING INITIALIZATION STATUS")
    print("="*60)

    try:
        from business.post_fill_hook import on_order_filled
        print("✓ post_fill_hook.on_order_filled imports OK")
    except Exception as e:
        print(f"✗ post_fill_hook.on_order_filled: {e}")

    try:
        from integration.fill_event_hooks import get_global_fill_event_hook_registry
        print("✓ fill_event_hooks.get_global_fill_event_hook_registry imports OK")
    except Exception as e:
        print(f"✗ fill_event_hooks: {e}")

    try:
        from core.order_engine import LOT_TRACKING_AVAILABLE
        status = "ENABLED" if LOT_TRACKING_AVAILABLE else "DISABLED"
        print(f"✓ OrderEngine LOT_TRACKING_AVAILABLE: {status}")
    except Exception as e:
        print(f"✗ Could not check LOT_TRACKING_AVAILABLE: {e}")

    db.disconnect()
    print("\n" + "="*60)

if __name__ == "__main__":
    check_tables()
