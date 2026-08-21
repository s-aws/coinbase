"""One-shot DB inspection for stealth order 4b6d2185-* (2026-05-03 condition-met-no-reveal incident)."""
from database.database import PostgresDB

db = PostgresDB()
db.connect()

PREFIX = "4b6d2185%"

print("=== stealth_orders row ===")
rows = db.execute_query(
    """SELECT stealth_order_id::text AS sid, status, total_size, revealed_size,
              executed_size, remaining_size, condition_first_met_at,
              condition_confirmed_at, last_placement_at, limit_price, side,
              product_id, reveal_condition_type
       FROM stealth_orders WHERE stealth_order_id::text LIKE %s""",
    (PREFIX,),
)
for r in rows:
    for k, v in dict(r).items():
        print(f"  {k}: {v}")

print("\n=== revealed_orders JSONB ===")
rows = db.execute_query(
    "SELECT revealed_orders FROM stealth_orders WHERE stealth_order_id::text LIKE %s",
    (PREFIX,),
)
for r in rows:
    print(f"  {r['revealed_orders']}")

print("\n=== order_parent rows linked to this stealth ===")
rows = db.execute_query(
    """SELECT client_order_id::text AS coid, status, parent_order_id::text AS parent,
              current_order_replacement AS cur, max_order_replacement AS mx,
              size, price, side, product_id, created_at
       FROM order_parent
       WHERE client_order_id::text LIKE %s
          OR parent_order_id::text LIKE %s
       ORDER BY created_at""",
    (PREFIX, PREFIX),
)
for r in rows:
    print(f"  {dict(r)}")

print("\n=== reveal_history ===")
rows = db.execute_query(
    """SELECT reveal_number, revealed_size, placement_price, placement_status,
              placement_success, reveal_event_type,
              reveal_trigger_reason
       FROM stealth_order_reveal_history
       WHERE stealth_order_id::text LIKE %s
       ORDER BY reveal_number""",
    (PREFIX,),
)
for r in rows:
    print(f"  {dict(r)}")
if not rows:
    print("  (no reveal_history rows)")

print("\n=== lifecycle_history (last 20) ===")
try:
    rows = db.execute_query(
        """SELECT event, created_at, extra_json
           FROM stealth_order_lifecycle_history
           WHERE stealth_order_id::text LIKE %s
           ORDER BY created_at DESC LIMIT 20""",
        (PREFIX,),
    )
    for r in rows:
        print(f"  {r['created_at']} {r['event']}: {r['extra_json']}")
    if not rows:
        print("  (no lifecycle_history rows)")
except Exception as e:
    print(f"  (lifecycle_history query failed: {e})")

db.disconnect()
