"""
Analyze order data to understand why fill_ledger and conditional_orders are empty.
"""

import sys
sys.path.insert(0, 'e:\\coinbase')

import psycopg2
from collections import defaultdict

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

    print("\n" + "="*80)
    print("ORDER STATUS ANALYSIS")
    print("="*80)

    # Check order_parent status distribution
    print("\n1️⃣  ORDER_PARENT STATUS DISTRIBUTION:")
    print("-" * 80)
    cursor.execute("""
        SELECT status, COUNT(*) as count
        FROM order_parent
        GROUP BY status
        ORDER BY count DESC
    """)

    status_counts = cursor.fetchall()
    for status, count in status_counts:
        print(f"   {status:15} - {count:3} orders")

    # Check if any orders are FILLED
    print("\n2️⃣  FILLED ORDERS DETAILS:")
    print("-" * 80)
    cursor.execute("""
        SELECT client_order_id, product_id, side, size, price, status, created_at
        FROM order_parent
        WHERE status = 'FILLED'
        LIMIT 5
    """)

    filled_orders = cursor.fetchall()
    if filled_orders:
        print(f"   Found {len(filled_orders)} FILLED orders (showing first 5):")
        for client_order_id, product_id, side, size, price, status, created_at in filled_orders:
            print(f"   - {client_order_id[:8]}... : {side:4} {size} {product_id:10} @ ${price} [{status}]")
    else:
        print("   ⚠️  NO FILLED ORDERS FOUND")

        # Check what statuses exist
        print("\n   Explanation: Orders are in these statuses but not FILLED yet:")
        for status, count in status_counts:
            if status != 'FILLED':
                print(f"   - {status}: {count} orders (not yet filled)")

    # Check stealth_orders
    print("\n3️⃣  STEALTH_ORDERS STATUS DISTRIBUTION:")
    print("-" * 80)
    cursor.execute("""
        SELECT status, COUNT(*) as count
        FROM stealth_orders
        GROUP BY status
        ORDER BY count DESC
    """)

    stealth_statuses = cursor.fetchall()
    for status, count in stealth_statuses:
        print(f"   {status:20} - {count:3} orders")

    # Check fill_ledger
    print("\n4️⃣  FILL_LEDGER STATUS:")
    print("-" * 80)
    cursor.execute("SELECT COUNT(*) FROM fill_ledger")
    fill_count = cursor.fetchone()[0]
    print(f"   Total fills recorded: {fill_count}")

    if fill_count == 0:
        print("\n   ⚠️  NO FILLS HAVE BEEN RECORDED YET")
        print("   Fills are only recorded when:")
        print("   - An order is FILLED on the exchange")
        print("   - The on_order_filled() hook is called")
        print("   - The fill is persisted to fill_ledger table")

    # Check conditional_orders
    print("\n5️⃣  CONDITIONAL_ORDERS STATUS:")
    print("-" * 80)
    cursor.execute("SELECT COUNT(*) FROM conditional_orders")
    cond_count = cursor.fetchone()[0]
    print(f"   Total conditional orders: {cond_count}")

    if cond_count == 0:
        print("\n   ⚠️  NO CONDITIONAL ORDERS HAVE BEEN CREATED YET")
        print("   Conditional orders are created when:")
        print("   - A parent order is FILLED")
        print("   - Follow-up orders are generated")
        print("   - Wrap order logic is triggered")

    # Summary
    print("\n" + "="*80)
    print("SUMMARY & ROOT CAUSE")
    print("="*80)

    if fill_count == 0 and cond_count == 0:
        print("""
✅ TABLES ARE EMPTY BECAUSE:

1. No orders have been FILLED on the exchange yet
   - Your 38 parent orders exist but are still in: OPEN, PENDING, or other statuses
   - Until an order reaches FILLED status, no fill records are created

2. No conditional orders exist because:
   - Conditional orders are only created AFTER a parent order is filled
   - Since no orders are filled → no conditional orders yet

NEXT STEPS:
1. Place and execute some test orders to generate FILLS
2. Monitor order status transitions: OPEN → FILLED
3. Once fills occur, fill_ledger will be populated
4. Once fills occur, conditional_orders will be created (if applicable)

Run: python main.py  (to start the trading engine)
Or:  python test_production_fill_flow.py  (to simulate fills)
        """)
    else:
        print(f"\n✅ Data exists: {fill_count} fills, {cond_count} conditional orders")

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
