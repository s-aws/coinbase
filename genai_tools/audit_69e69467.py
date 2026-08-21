"""Ad-hoc DB audit for parent order 69e69467-9778-4d6c-b995-504cc1cbfb71."""
from database.database import PostgresDB

CID = "69e69467-9778-4d6c-b995-504cc1cbfb71"

FIELDS = [
    "client_order_id", "parent_order_id", "product_id", "side", "size", "price",
    "status", "max_order_replacement", "current_order_replacement",
    "allow_partial_fills", "target_movement", "target_movement_type",
    "created_at",
]

db = PostgresDB()
with db.get_cursor() as c:
    c.execute(
        f"""
        SELECT {', '.join(FIELDS)}
        FROM order_parent
        WHERE client_order_id = %s OR parent_order_id = %s
        ORDER BY created_at
        """,
        (CID, CID),
    )
    rows = c.fetchall()

print(f"Found {len(rows)} order_parent row(s) related to {CID}\n")
for r in rows:
    print("-" * 70)
    for k, v in zip(FIELDS, r):
        print(f"  {k}: {v}")

# discover related tables
with db.get_cursor() as c:
    c.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name"
    )
    tables = [t[0] for t in c.fetchall()]
print("\nTables:", tables)

# Look for fills table
for t in tables:
    if "fill" in t.lower() or "ledger" in t.lower() or "lot" in t.lower():
        with db.get_cursor() as c:
            c.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name=%s",
                (t,),
            )
            cols = [r[0] for r in c.fetchall()]
        if "client_order_id" in cols:
            with db.get_cursor() as c:
                c.execute(
                    f"SELECT {', '.join(cols)} FROM {t} WHERE client_order_id=%s",
                    (CID,),
                )
                rs = c.fetchall()
            print(f"\n{t} ({len(rs)} rows):")
            for r in rs:
                print(" ", dict(zip(cols, r)))
