#!/usr/bin/env python3
"""
Diagnostic tool to identify which stealth orders actually succeeded in placing on Coinbase
vs which ones failed and are using fallback UUIDs.

This helps understand the 262 REVEALED orders issue - were they placed or not?
"""

from database.database import PostgresDB
import json

db = PostgresDB()
db.connect()

try:
    print("\n" + "="*80)
    print("STEALTH ORDER PLACEMENT SUCCESS ANALYSIS")
    print("="*80)

    # Query all REVEALED orders and analyze their revealed_orders data
    with db.get_cursor() as cursor:
        cursor.execute("""
            SELECT
                stealth_order_id,
                product_id,
                side,
                status,
                revealed_orders
            FROM stealth_orders
            WHERE status = 'REVEALED'
            ORDER BY created_at DESC
        """)
        rows = cursor.fetchall()

        successful_placements = 0
        failed_placements = 0
        orders_with_success_tracking = 0
        old_format_orders = 0

        sample_failures = []

        print(f"\nAnalyzing {len(rows)} REVEALED orders...\n")

        for row in rows:
            sid, product_id, side, status, revealed_orders_json = row

            try:
                if isinstance(revealed_orders_json, str):
                    revealed_list = json.loads(revealed_orders_json)
                else:
                    revealed_list = revealed_orders_json or []

                for reveal_event in revealed_list:
                    # Check if this uses new tracking format
                    if "placement_success" in reveal_event:
                        orders_with_success_tracking += 1

                        if reveal_event.get("placement_success"):
                            successful_placements += 1
                        else:
                            failed_placements += 1
                            if len(sample_failures) < 5:
                                sample_failures.append({
                                    "order_id": str(sid)[:8],
                                    "product": product_id,
                                    "error": reveal_event.get("placement_error"),
                                })
                    else:
                        # Old format - no success tracking (these were created before fix)
                        old_format_orders += 1

            except Exception as e:
                print(f"  Error parsing order {str(sid)[:8]}: {e}")

        print("\nRESULTS:")
        print("-" * 80)
        print(f"Orders with success tracking:    {orders_with_success_tracking}")
        print(f"  ✓ Successfully placed:         {successful_placements}")
        print(f"  ✗ Failed placements:           {failed_placements}")
        print(f"Old format (pre-fix):            {old_format_orders}")
        print(f"\nTotal revealed orders analyzed:  {len(rows)}")

        if failed_placements > 0:
            print(f"\n⚠️  {failed_placements} orders FAILED to place on Coinbase!")
            print("Sample failures:")
            for failure in sample_failures:
                print(f"  - {failure['order_id']}... on {failure['product']}")
                print(f"    Error: {failure['error']}")

        if old_format_orders > 0:
            print(f"\n📊 {old_format_orders} orders use old format (no success tracking)")
            print("   These were created before the fix was applied")
            print("   Logs should show their placement status")

finally:
    db.disconnect()
