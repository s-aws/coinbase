#!/usr/bin/env python3
"""
Inspect reveal conditions of the REVEALED orders to understand why they're revealed.
"""

from database.database import PostgresDB
import json

db = PostgresDB()
db.connect()

try:
    print("\n" + "="*80)
    print("REVEAL CONDITIONS OF REVEALED ORDERS")
    print("="*80)

    # Get a sample of REVEALED orders with their condition info
    with db.get_cursor() as cursor:
        cursor.execute("""
            SELECT
                stealth_order_id,
                reveal_condition_type,
                reveal_condition_json,
                created_at
            FROM stealth_orders
            WHERE status = 'REVEALED'
            ORDER BY created_at DESC
            LIMIT 30
        """)
        rows = cursor.fetchall()

        condition_counts = {}

        for row in rows:
            sid, cond_type, cond_json, created = row

            if cond_type not in condition_counts:
                condition_counts[cond_type] = {
                    'count': 0,
                    'examples': []
                }

            condition_counts[cond_type]['count'] += 1
            if len(condition_counts[cond_type]['examples']) < 2:
                # Parse the JSON to show the config
                try:
                    if isinstance(cond_json, str):
                        config = json.loads(cond_json)
                    else:
                        config = cond_json
                    condition_counts[cond_type]['examples'].append({
                        'id': str(sid)[:8],
                        'config': config
                    })
                except:
                    pass

    # Print summary
    for cond_type, data in condition_counts.items():
        print(f"\n{cond_type}: {data['count']} orders")
        for example in data['examples']:
            print(f"  Example {example['id']}...")
            for key, value in example['config'].items():
                print(f"    {key}: {value}")

    # Overall count
    print("\n" + "="*80)
    print(f"Total condition types seen: {len(condition_counts)}")

finally:
    db.disconnect()
