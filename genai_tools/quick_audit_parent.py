#!/usr/bin/env python
import argparse
import sys
from decimal import Decimal

sys.path.insert(0, '.')
from database.database import PostgresDB

DEFAULT_PARENT = "5cb69570-4e02-4164-aa19-e5fa78f775f0"


def f(v):
    if isinstance(v, Decimal):
        return float(v)
    return v


def show_rows(title, rows, keys):
    print("\n" + title)
    print("-" * len(title))
    if not rows:
        print("(none)")
        return
    for i, r in enumerate(rows, 1):
        parts = []
        for k in keys:
            parts.append(f"{k}={f(r.get(k))}")
        print(f"{i}. " + " | ".join(parts))


parser = argparse.ArgumentParser(description="Quick audit for one parent order chain")
parser.add_argument("--parent", default=DEFAULT_PARENT, help="Parent client_order_id to audit")
args = parser.parse_args()
PARENT = args.parent

db = PostgresDB()
db.connect()

parent = db.execute_query(
    """SELECT id, client_order_id, side, size, status, current_order_replacement, max_order_replacement, created_at
       FROM order_parent WHERE client_order_id=%s""",
    (PARENT,),
)
show_rows("Parent", parent, ["id", "client_order_id", "side", "size", "status", "current_order_replacement", "max_order_replacement", "created_at"])

children = db.execute_query(
    """SELECT id, client_order_id, parent_order_id, side, size, price, status, created_at
       FROM order_parent WHERE parent_order_id=%s ORDER BY created_at""",
    (PARENT,),
)
show_rows("Children", children, ["id", "client_order_id", "parent_order_id", "side", "size", "price", "status", "created_at"])

sum_size = sum(float(r["size"]) for r in children)
print(f"\nChild count={len(children)}; Sum(child sizes)={sum_size}")

stealth = db.execute_query(
    """SELECT stealth_order_id, parent_order_id, side, total_size, remaining_size, revealed_size, executed_size, status, last_lifecycle_event, created_at
       FROM stealth_orders
       WHERE stealth_order_id=%s OR parent_order_id::text=%s
       ORDER BY created_at""",
    (PARENT, PARENT),
)
show_rows("Stealth chain", stealth, ["stealth_order_id", "parent_order_id", "side", "total_size", "remaining_size", "revealed_size", "executed_size", "status", "last_lifecycle_event", "created_at"])

pfp_cols = db.execute_query(
    "SELECT column_name FROM information_schema.columns WHERE table_name='partial_fill_progress' ORDER BY ordinal_position"
)
pfp_col_names = [r["column_name"] for r in pfp_cols]
print("\npartial_fill_progress columns:", pfp_col_names)

if "parent_client_order_id" in pfp_col_names:
    pfp = db.execute_query(
        "SELECT * FROM partial_fill_progress WHERE parent_client_order_id=%s ORDER BY updated_at",
        (PARENT,),
    )
    show_rows("partial_fill_progress rows", pfp, pfp_col_names)

stream_cols = db.execute_query(
    "SELECT column_name FROM information_schema.columns WHERE table_name='order_event_stream' ORDER BY ordinal_position"
)
stream_col_names = [r["column_name"] for r in stream_cols]
print("\norder_event_stream columns:", stream_col_names)

queries = []
if "parent_client_order_id" in stream_col_names:
    queries.append(("By parent_client_order_id", "SELECT event_type, client_order_id, parent_client_order_id, stealth_order_id, side, size, price, event_status_to, created_at FROM order_event_stream WHERE parent_client_order_id=%s ORDER BY created_at", (PARENT,)))
if "client_order_id" in stream_col_names:
    queries.append(("By client_order_id", "SELECT event_type, client_order_id, parent_client_order_id, stealth_order_id, side, size, price, event_status_to, created_at FROM order_event_stream WHERE client_order_id=%s ORDER BY created_at", (PARENT,)))

for label, q, params in queries:
    rows = db.execute_query(q, params)
    show_rows(f"order_event_stream {label}", rows, ["event_type", "client_order_id", "parent_client_order_id", "stealth_order_id", "side", "size", "price", "event_status_to", "created_at"])

calc_rows = db.execute_query(
    """SELECT event_type, created_at, trigger_payload_json, raw_payload_json
       FROM order_event_stream
       WHERE client_order_id=%s
         AND event_type IN ('partial_fill_detected','partial_fill_follow_up_queued','partial_fill_progress_updated')
       ORDER BY created_at""",
    (PARENT,),
)

print("\nPartial-fill calculation payloads")
print("---------------------------------")
if not calc_rows:
    print("(none)")
else:
    for i, r in enumerate(calc_rows, 1):
        print(f"{i}. event_type={r.get('event_type')} | created_at={r.get('created_at')}")
        print(f"   trigger_payload_json={r.get('trigger_payload_json')}")
        print(f"   raw_payload_json={r.get('raw_payload_json')}")

fills = db.execute_query(
    "SELECT trade_id, client_order_id, side, quantity, price, fees, created_at FROM fill_ledger WHERE client_order_id=%s ORDER BY created_at",
    (PARENT,),
)
show_rows("fill_ledger rows", fills, ["trade_id", "client_order_id", "side", "quantity", "price", "fees", "created_at"])

db.disconnect()
