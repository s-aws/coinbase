#!/usr/bin/env python3
"""Debug script to check max_order_replacement in database."""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from database.database import PostgresDB

def check_max_order_replacement():
    """Check max_order_replacement column status in order_parent table."""
    db = PostgresDB()
    db.connect()

    print("=" * 80)
    print("CHECKING MAX_ORDER_REPLACEMENT IN DATABASE")
    print("=" * 80)

    # 1. Check table structure
    print("\n1. TABLE STRUCTURE:")
    query = """
    SELECT column_name, data_type, is_nullable, column_default
    FROM information_schema.columns
    WHERE table_name = 'order_parent'
    ORDER BY ordinal_position
    """
    try:
        result = db.execute_query(query)
        if result:
            print(f"\nFound {len(result)} columns in order_parent table:")
            for col in result:
                print(f"  - {col['column_name']}: {col['data_type']} (nullable: {col['is_nullable']}, default: {col['column_default']})")
        else:
            print("ERROR: No columns found - table may not exist")
            return
    except Exception as e:
        print(f"ERROR checking table structure: {e}")
        return

    # 2. Check for max_order_replacement column
    max_order_repl_found = any(col['column_name'] == 'max_order_replacement' for col in result)
    print(f"\n2. MAX_ORDER_REPLACEMENT COLUMN: {'✓ FOUND' if max_order_repl_found else '✗ MISSING'}")

    if not max_order_repl_found:
        print("\n⚠️  ISSUE: max_order_replacement column is missing from table!")
        print("   This needs to be added via migration.")
        db.disconnect()
        return

    # 3. Check data in table
    print("\n3. DATA IN ORDER_PARENT TABLE:")
    query = """
    SELECT id, client_order_id, max_order_replacement, current_order_replacement, status, created_at
    FROM order_parent
    ORDER BY created_at DESC
    LIMIT 10
    """
    try:
        result = db.execute_query(query)
        if result:
            print(f"\nFound {len(result)} recent orders:")
            for order in result:
                print(f"  ID {order['id']}: client_order_id={order['client_order_id']}")
                print(f"    max_order_replacement={order['max_order_replacement']} (type: {type(order['max_order_replacement'])})")
                print(f"    current_order_replacement={order['current_order_replacement']}")
                print(f"    status={order['status']}, created_at={order['created_at']}")
        else:
            print("No orders found in order_parent table")
    except Exception as e:
        print(f"ERROR querying data: {e}")

    # 4. Check NULL values
    print("\n4. NULL VALUE CHECK:")
    query = """
    SELECT COUNT(*) as total,
           COUNT(*) FILTER (WHERE max_order_replacement IS NULL) as null_count,
           COUNT(*) FILTER (WHERE max_order_replacement = 0) as zero_count,
           COUNT(*) FILTER (WHERE max_order_replacement > 0) as nonzero_count
    FROM order_parent
    """
    try:
        result = db.execute_query(query)
        if result:
            stats = result[0]
            print(f"  Total orders: {stats['total']}")
            print(f"  With NULL max_order_replacement: {stats['null_count']}")
            print(f"  With zero max_order_replacement: {stats['zero_count']}")
            print(f"  With non-zero max_order_replacement: {stats['nonzero_count']}")
    except Exception as e:
        print(f"ERROR checking NULL values: {e}")

    # 5. Summary and recommendations
    print("\n" + "=" * 80)
    print("ANALYSIS & RECOMMENDATIONS:")
    print("=" * 80)

    if not max_order_repl_found:
        print("❌ CRITICAL: max_order_replacement column is MISSING")
        print("\nFIX:")
        print("  1. Add column migration:")
        print("     ALTER TABLE order_parent ADD COLUMN max_order_replacement INTEGER DEFAULT 0;")
        print("  2. Or drop and recreate table with correct schema")
    else:
        if result and result[0]['null_count'] > 0:
            print("⚠️  WARNING: Some orders have NULL max_order_replacement values")
            print("\nFIX: Update NULL values to DEFAULT_MAX_ORDER_REPLACEMENT (11):")
            print("     UPDATE order_parent SET max_order_replacement = 11 WHERE max_order_replacement IS NULL;")

        if result and result[0]['zero_count'] > 0:
            print(f"⚠️  WARNING: {result[0]['zero_count']} orders have max_order_replacement = 0")
            print("     This may be expected for child orders, or incorrect for root orders.")

        if result and result[0]['nonzero_count'] > 0:
            print(f"✓ Good: {result[0]['nonzero_count']} orders have non-zero max_order_replacement")

    db.disconnect()
    print("\n")

if __name__ == "__main__":
    check_max_order_replacement()
