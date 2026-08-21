"""Audit for the 2026-04-30 04:46 size bug report."""
from database.database import PostgresDB

db = PostgresDB(); db.connect(); cur = db._conn.cursor()

print("=== order_parent rows for chain root f2d151c9 ===")
cur.execute(
    "SELECT id, client_order_id, side, size, price, status, parent_order_id, "
    "max_order_replacement, current_order_replacement, allow_partial_fills "
    "FROM order_parent "
    "WHERE client_order_id=%s OR parent_order_id=%s ORDER BY id",
    ("f2d151c9-f394-413d-9147-99c896d7c55a",
     "f2d151c9-f394-413d-9147-99c896d7c55a"),
)
for r in cur.fetchall():
    print(r)

print("\n=== fills for child 0ced55c0 ===")
cur.execute(
    "SELECT column_name FROM information_schema.columns "
    "WHERE table_name='fill_ledger' ORDER BY ordinal_position"
)
cols = [r[0] for r in cur.fetchall()]
cur.execute(
    "SELECT * FROM fill_ledger WHERE client_order_id=%s ORDER BY id",
    ("0ced55c0-5e7c-42df-b2fc-60080a08df3c",),
)
rows = cur.fetchall()
total_qty = 0.0
for r in rows:
    d = dict(zip(cols, r))
    qty = d.get("quantity") or d.get("size")
    total_qty += float(qty or 0)
    print(" ", {k: d[k] for k in ("id", "side", "quantity", "price", "fees")})
print(f"  fills sum = {total_qty}")

print("\n=== stealth_orders rows for chain ===")
cur.execute(
    "SELECT stealth_order_id, parent_order_id, side, total_size, revealed_size, "
    "executed_size, remaining_size, status, limit_price, reason "
    "FROM stealth_orders WHERE stealth_order_id::text IN (%s,%s,%s) "
    "OR parent_order_id::text=%s ORDER BY id",
    ("f2d151c9-f394-413d-9147-99c896d7c55a",
     "0ced55c0-5e7c-42df-b2fc-60080a08df3c",
     "30599a8b-5113-4eb4-9536-72516677af5b",
     "f2d151c9-f394-413d-9147-99c896d7c55a"),
)
for r in cur.fetchall():
    print(r)

print("\n=== partial_fill_progress rows ===")
try:
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='partial_fill_progress' ORDER BY ordinal_position"
    )
    pcols = [r[0] for r in cur.fetchall()]
    cur.execute(
        "SELECT * FROM partial_fill_progress WHERE client_order_id=%s",
        ("0ced55c0-5e7c-42df-b2fc-60080a08df3c",),
    )
    for r in cur.fetchall():
        d = dict(zip(pcols, r))
        print(" ", d)
except Exception as e:
    print("  (skip):", e)

print("\n=== follow-up stealth_order details ===")
cur.execute(
    "SELECT stealth_order_id, parent_order_id, side, total_size, "
    "limit_price, status, reason, notes "
    "FROM stealth_orders WHERE stealth_order_id::text=%s",
    ("30599a8b-5113-4eb4-9536-72516677af5b",),
)
for r in cur.fetchall():
    print(r)
