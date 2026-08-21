"""Dump parent 514563cc and any siblings."""
from database.database import PostgresDB

ROOT = "514563cc-607b-446f-b92f-c3714594fc44"
CHILD = "69e69467-9778-4d6c-b995-504cc1cbfb71"

FIELDS = [
    "client_order_id", "parent_order_id", "product_id", "side", "size", "price",
    "status", "max_order_replacement", "current_order_replacement",
    "allow_partial_fills", "target_movement", "target_movement_type",
    "created_at",
]

db = PostgresDB()
with db.get_cursor() as c:
    c.execute(
        f"SELECT {', '.join(FIELDS)} FROM order_parent "
        f"WHERE client_order_id = %s OR parent_order_id = %s OR client_order_id = %s "
        f"ORDER BY created_at",
        (ROOT, ROOT, CHILD),
    )
    rows = c.fetchall()

print(f"{len(rows)} related row(s)\n")
for r in rows:
    print("-" * 70)
    for k, v in zip(FIELDS, r):
        print(f"  {k}: {v}")

# stealth_orders linkage too
with db.get_cursor() as c:
    c.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='stealth_orders'"
    )
    cols = [r[0] for r in c.fetchall()]
print("\nstealth_orders columns sampled:",
      [c for c in cols if "order" in c or "parent" in c])

# event stream around this order
with db.get_cursor() as c:
    c.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='order_event_stream'"
    )
    es_cols = [r[0] for r in c.fetchall()]
print("\norder_event_stream columns:", es_cols)

if "client_order_id" in es_cols:
    with db.get_cursor() as c:
        c.execute(
            f"SELECT {', '.join(es_cols)} FROM order_event_stream "
            f"WHERE client_order_id IN (%s, %s) ORDER BY id",
            (ROOT, CHILD),
        )
        evs = c.fetchall()
    print(f"\norder_event_stream ({len(evs)} rows):")
    for e in evs:
        print(" ", dict(zip(es_cols, e)))
