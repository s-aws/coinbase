"""Ad-hoc DB audit for the 2026-04-29 follow-up cap incident."""
from database.database import PostgresDB

db = PostgresDB(); db.connect(); cur = db._conn.cursor()

print("=== order_parent rows for chain root da7b8b66 ===")
cur.execute(
    "SELECT id, client_order_id, side, size, price, status, parent_order_id, "
    "max_order_replacement, current_order_replacement, allow_partial_fills "
    "FROM order_parent "
    "WHERE client_order_id=%s OR parent_order_id=%s ORDER BY id",
    ("da7b8b66-0626-41d6-93b2-621d72542ee2",
     "da7b8b66-0626-41d6-93b2-621d72542ee2"),
)
for r in cur.fetchall():
    print(r)

print("\n=== fills_ledger schema ===")
cur.execute(
    "SELECT column_name FROM information_schema.columns "
    "WHERE table_name='fill_ledger' ORDER BY ordinal_position"
)
cols = [r[0] for r in cur.fetchall()]
print(cols)

print("\n=== fills_ledger for filled child f0e4f53f ===")
cur.execute(
    "SELECT * FROM fill_ledger WHERE client_order_id=%s ORDER BY id",
    ("f0e4f53f-a45d-4cae-8b08-febc4d11cb3e",),
)
rows = cur.fetchall()
print(f"  fill count: {len(rows)}")
total = 0.0
for r in rows:
    d = dict(zip(cols, r))
    sz = d.get("size") or d.get("filled_size") or d.get("quantity")
    total += float(sz) if sz else 0
    keep = {k: d[k] for k in d if k in (
        "id", "derived_trade_key", "side", "size", "filled_size",
        "price", "fee", "fees", "client_order_id"
    )}
    print(" ", keep)
print(f"  fills sum = {total}")

print("\n=== stealth_orders for chain ===")
ids = [
    "da7b8b66-0626-41d6-93b2-621d72542ee2",
    "f0e4f53f-a45d-4cae-8b08-febc4d11cb3e",
    "0205ab38-a517-4940-8c8c-c0c0027c2f8d",
    "8f70f446-7c20-4289-b10c-0f686a4333a1",
    "c3d6235d-0fe7-436d-9980-e0c9fd3c4d62",
    "70cc636e-ce23-4912-8b38-8c566add9a5d",
]
cur.execute(
    "SELECT stealth_order_id, parent_order_id, side, total_size, revealed_size, "
    "executed_size, remaining_size, status, limit_price, reason "
    "FROM stealth_orders WHERE stealth_order_id::text = ANY(%s) ORDER BY id",
    (ids,),
)
for r in cur.fetchall():
    print(r)

print("\n=== order_event_stream for filled child (top 30) ===")
try:
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='order_event_stream' ORDER BY ordinal_position"
    )
    ecols = [r[0] for r in cur.fetchall()]
    cur.execute(
        "SELECT * FROM order_event_stream WHERE client_order_id=%s "
        "ORDER BY id LIMIT 30",
        ("f0e4f53f-a45d-4cae-8b08-febc4d11cb3e",),
    )
    for r in cur.fetchall():
        d = dict(zip(ecols, r))
        keep = {k: d[k] for k in d if k in (
            "id", "event_type", "size", "price", "status", "ts", "created_at"
        )}
        print(" ", keep)
except Exception as e:
    print("  (no order_event_stream or schema differs):", e)
