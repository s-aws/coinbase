"""Audit DB state for the 2026-04-28 partial_fill_progress FK violations.

Investigates the COIDs that appeared in the server log error window:
  - Direct FK violators (parent missing at upsert time)
  - Cascaded "InFailedSqlTransaction" victims
  - Did the parent_order rows eventually land?
  - Are there orphaned fill_ledger rows with no order_parent?
"""
import sys
sys.path.insert(0, '.')

from database.database import PostgresDB

# COIDs from the log window
DIRECT_FK_VIOLATORS = [
    "42ec9eeb-ff4f-44ac-9f3e-e43ae147e633",  # CANCELLED parent (later inserted)
    "8f81799f-48da-477d-9f1f-322f89211a90",  # FILLED parent (later inserted, DB ID 18)
    "a7e25117-08f1-4d42-8cb0-0ed38632a22b",  # FILLED parent (later inserted, DB ID 19)
    "fa295dc5-3c97-4f70-8cb8-516ace6a153d",  # CANCELLED parent (later inserted, DB ID 20)
]

# Victims of poisoned transaction (InFailedSqlTransaction, not real FK violators)
TXN_VICTIMS = [
    "23077e38-73e2-4b06-9304-eae252c04efd",
    "bd2123d8-eb6b-4c56-a3f0-aedee406ec12",
]

# Order events that failed to insert
ORPHAN_EVENT_IDS = [
    "ee08470e-8c09-4b98-9655-4267c0023a0b",
    "5c2e7e9f-eeb8-4b56-87de-46ff6f41becd",
]

ALL_COIDS = DIRECT_FK_VIOLATORS + TXN_VICTIMS

db = PostgresDB()
db.connect()


def section(title: str) -> None:
    print()
    print("=" * 100)
    print(title)
    print("=" * 100)


def fmt_row_keys(row: dict, keys) -> str:
    return " | ".join(f"{k}={row.get(k)}" for k in keys)


# ---------------------------------------------------------------------------
section("[A] order_parent presence for affected COIDs")
rows = db.execute_query(
    """SELECT client_order_id, id AS db_id, status, side, size, price, product_id,
              parent_order_id, created_at
       FROM order_parent
       WHERE client_order_id = ANY(%s)
       ORDER BY created_at;""",
    (ALL_COIDS,),
)
present = {r["client_order_id"] for r in (rows or [])}
for coid in ALL_COIDS:
    if coid in present:
        r = next(x for x in rows if x["client_order_id"] == coid)
        kind = "CHILD " if r.get("parent_order_id") else "ROOT  "
        print(f"  PRESENT  [{kind}] {coid}  db_id={r['db_id']}  status={r['status']}  "
              f"{r['side']} {r['size']} @ {r['price']}  {r['product_id']}  created={r['created_at']}")
    else:
        print(f"  MISSING  {coid}  <-- never landed in order_parent")

# ---------------------------------------------------------------------------
section("[B] partial_fill_progress rows for affected COIDs")
rows = db.execute_query(
    """SELECT client_order_id, parent_client_order_id, product_id, side,
              original_order_size, last_cumulative_qty_processed,
              carry_remainder_qty, last_number_of_fills_seen,
              partial_follow_ups_created, status, updated_at
       FROM partial_fill_progress
       WHERE client_order_id = ANY(%s)
       ORDER BY updated_at;""",
    (ALL_COIDS,),
)
have_progress = {r["client_order_id"] for r in (rows or [])}
for coid in ALL_COIDS:
    if coid in have_progress:
        r = next(x for x in rows if x["client_order_id"] == coid)
        print(f"  HAS ROW  {coid}  cum={r['last_cumulative_qty_processed']}  "
              f"carry={r['carry_remainder_qty']}  fills={r['last_number_of_fills_seen']}  "
              f"status={r['status']}  updated={r['updated_at']}")
    else:
        print(f"  MISSING  {coid}  <-- watermark never persisted")

# ---------------------------------------------------------------------------
section("[C] fill_ledger rows for affected COIDs (source-of-truth fills)")
# Verify column names first; fill_ledger may use derived_trade_key, client_order_id, etc.
schema = db.execute_query(
    """SELECT column_name FROM information_schema.columns
       WHERE table_name = 'fill_ledger' ORDER BY ordinal_position;"""
)
cols = [r["column_name"] for r in (schema or [])]
print(f"  fill_ledger columns: {cols}")
if "client_order_id" in cols:
    rows = db.execute_query(
        """SELECT client_order_id, derived_trade_key, instrument, side,
                  quantity, price, fees, timestamp
           FROM fill_ledger
           WHERE client_order_id = ANY(%s)
           ORDER BY timestamp;""",
        (ALL_COIDS,),
    ) or []
    if not rows:
        print("  (no fill_ledger rows for these COIDs)")
    for r in rows:
        print(f"  {r['client_order_id']}  trade_key={r['derived_trade_key']}  "
              f"{r['side']} {r['quantity']} @ {r['price']}  fees={r['fees']}  ts={r['timestamp']}")
else:
    print("  WARNING: fill_ledger has no client_order_id column; column names differ.")

# ---------------------------------------------------------------------------
section("[D] order_events / order_event_stream for the orphaned event IDs")
# Check both possible table names
for table in ("order_events", "order_event_stream"):
    exists = db.execute_query(
        "SELECT to_regclass(%s) AS t;", (table,)
    )
    if not exists or not exists[0]["t"]:
        print(f"  (table {table} does not exist)")
        continue
    schema = db.execute_query(
        """SELECT column_name FROM information_schema.columns
           WHERE table_name = %s ORDER BY ordinal_position;""", (table,),
    )
    cols = [r["column_name"] for r in (schema or [])]
    print(f"  {table} columns: {cols}")
    # Try common id columns
    id_col = next((c for c in ("event_id", "id", "client_order_id") if c in cols), None)
    if id_col:
        rows = db.execute_query(
            f"SELECT event_id, event_type, client_order_id, event_status_from, event_status_to, created_at "
            f"FROM {table} WHERE client_order_id = ANY(%s) ORDER BY created_at LIMIT 50;",
            (ALL_COIDS,),
        ) or []
        print(f"  {table}: {len(rows)} rows for the affected COIDs")
        for r in rows:
            print(f"    {r['created_at']}  {r['event_type']:30s}  coid={r['client_order_id']}  "
                  f"{r['event_status_from']}->{r['event_status_to']}  event_id={r['event_id']}")

# ---------------------------------------------------------------------------
section("[E] Systemic check: orphan fill_ledger rows (parent missing globally)")
if "client_order_id" in cols:
    rows = db.execute_query(
        """SELECT fl.client_order_id, COUNT(*) AS orphan_fills,
                  MIN(fl.timestamp) AS first_ts, MAX(fl.timestamp) AS last_ts
           FROM fill_ledger fl
           LEFT JOIN order_parent op ON op.client_order_id = fl.client_order_id
           WHERE op.client_order_id IS NULL
           GROUP BY fl.client_order_id
           ORDER BY last_ts DESC
           LIMIT 30;"""
    ) or []
    if not rows:
        print("  No orphaned fill_ledger rows (good).")
    else:
        print(f"  {len(rows)} COIDs have fills but NO order_parent row:")
        for r in rows:
            print(f"    {r['client_order_id']}  orphan_fills={r['orphan_fills']}  "
                  f"first={r['first_ts']}  last={r['last_ts']}")

# ---------------------------------------------------------------------------
section("[F] Systemic check: partial_fill_progress orphans (cannot exist due to FK)")
rows = db.execute_query(
    """SELECT pfp.client_order_id
       FROM partial_fill_progress pfp
       LEFT JOIN order_parent op ON op.client_order_id = pfp.client_order_id
       WHERE op.client_order_id IS NULL;"""
) or []
print(f"  {len(rows)} orphan rows in partial_fill_progress (expected: 0 due to FK constraint)")

print()
print("Audit complete.")
