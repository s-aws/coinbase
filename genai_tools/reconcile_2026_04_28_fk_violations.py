"""Reconcile DB state for the 2026-04-28 partial_fill_progress FK-violation incident.

What this script does (idempotent, safe to re-run):

  1. For ``42ec9eeb-ff4f-44ac-9f3e-e43ae147e633`` — the only COID that was
     completely lost because the error handler crashed on the broken
     ``OrderPersistenceError(error_type=...)`` call — recover the original
     parent_order_entry_created payload from ``order_event_stream`` and
     insert the missing row into ``order_parent``.

  2. For all six affected COIDs, backfill the missing watermark row in
     ``partial_fill_progress``. Source of truth:
       * cumulative quantity = SUM(fill_ledger.quantity) for that COID
       * number_of_fills      = COUNT(fill_ledger rows)
       * everything else      = derived from order_parent

  3. Re-verify nothing remains inconsistent.

Usage:
    python genai_tools/reconcile_2026_04_28_fk_violations.py            # dry-run
    python genai_tools/reconcile_2026_04_28_fk_violations.py --apply    # write
"""
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from typing import Dict, Iterable, Optional

sys.path.insert(0, ".")

from database.database import PostgresDB

# --- Affected COIDs from the 2026-04-28 10:22:23 server-log window. -------
MISSING_PARENT = "42ec9eeb-ff4f-44ac-9f3e-e43ae147e633"
ALL_AFFECTED = [
    MISSING_PARENT,
    "8f81799f-48da-477d-9f1f-322f89211a90",
    "a7e25117-08f1-4d42-8cb0-0ed38632a22b",
    "fa295dc5-3c97-4f70-8cb8-516ace6a153d",
    "23077e38-73e2-4b06-9304-eae252c04efd",
    "bd2123d8-eb6b-4c56-a3f0-aedee406ec12",
]


def _to_float(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


def _section(title: str) -> None:
    print()
    print("=" * 100)
    print(title)
    print("=" * 100)


# --- 1. Recover the missing 42ec9eeb parent_order row. -------------------
# Values from the original server log (`parent_order_entry_created` event,
# 2026-04-28 10:22:23.282) — that event never landed in order_event_stream
# because the FK violation aborted the transaction, so we use the log as
# the source of truth for fields not recoverable from the DB.
_MISSING_PARENT_LOG_VALUES = {
    "client_order_id": MISSING_PARENT,
    "product_id": "BIT-29MAY26-CDE",
    "side": "SELL",
    "price": 78065.0,
    "status": "CANCELLED",
}


def recover_missing_parent(db: PostgresDB, apply: bool) -> bool:
    coid = MISSING_PARENT
    existing = db.execute_query(
        "SELECT id FROM order_parent WHERE client_order_id = %s;", (coid,)
    )
    if existing:
        print(f"  [skip] {coid} already exists in order_parent (id={existing[0]['id']})")
        return True

    # Pull the original parent_order_entry_created payload from the event stream.
    rows = db.execute_query(
        """SELECT raw_payload_json, side, price, product_id, size, event_type, created_at
           FROM order_event_stream
           WHERE client_order_id = %s
           ORDER BY created_at;""",
        (coid,),
    ) or []
    if not rows:
        print(f"  [FAIL] no order_event_stream rows for {coid}; cannot recover")
        return False

    print(f"  Found {len(rows)} event_stream rows for {coid}:")
    for r in rows:
        print(f"    {r['created_at']}  {r['event_type']}  side={r['side']} "
              f"price={r['price']}  size={r['size']}  product={r['product_id']}")

    # Find the row that carries the original placement metadata.
    placement = next(
        (r for r in rows if r["event_type"] in ("partial_fill_progress_updated",
                                                "partial_fill_finalized")),
        rows[0],
    )

    # Pull authoritative size from raw_payload_json.original_order_size if available.
    raw = placement.get("raw_payload_json")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = {}
    raw = raw or {}

    size = _to_float(raw.get("original_order_size") or placement.get("size"))
    # Price isn't carried in partial_fill payloads; fall back to the log value.
    price = (
        _to_float(placement.get("price"))
        or _to_float(_MISSING_PARENT_LOG_VALUES["price"])
    )
    side = (placement.get("side") or _MISSING_PARENT_LOG_VALUES["side"]).upper()
    product_id = placement.get("product_id") or _MISSING_PARENT_LOG_VALUES["product_id"]

    if size <= 0:
        print(f"  [FAIL] could not derive original size for {coid}; aborting")
        return False

    print(f"  Will insert: {coid}  {side} {size} @ {price}  {product_id}  status=CANCELLED")

    if not apply:
        print("  (dry-run; pass --apply to insert)")
        return True

    insert_query = """
    INSERT INTO order_parent (
        client_order_id, product_id, side, size, price, status,
        target_movement, target_movement_type,
        max_order_replacement, current_order_replacement,
        parent_order_id, allow_partial_fills
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING id;
    """
    res = db.execute_query(
        insert_query,
        (coid, product_id, side, size, price, "CANCELLED",
         None, None, 0, 0, None, False),
    )
    if res:
        print(f"  [OK] inserted {coid} as order_parent.id={res[0]['id']}")
        return True
    print(f"  [FAIL] insert returned no id for {coid}")
    return False


# --- 2. Backfill partial_fill_progress watermarks. ----------------------
def backfill_watermark(db: PostgresDB, coid: str, apply: bool) -> bool:
    parent = db.execute_query(
        """SELECT client_order_id, product_id, side, size, parent_order_id, status
           FROM order_parent WHERE client_order_id = %s;""",
        (coid,),
    )
    if not parent:
        print(f"  [skip] {coid} has no order_parent row (handle parent first)")
        return False
    parent = parent[0]

    existing = db.execute_query(
        "SELECT client_order_id FROM partial_fill_progress WHERE client_order_id = %s;",
        (coid,),
    )
    if existing:
        print(f"  [skip] {coid} already has a partial_fill_progress row")
        return True

    fills = db.execute_query(
        """SELECT COALESCE(SUM(quantity), 0) AS cum_qty, COUNT(*) AS n_fills
           FROM fill_ledger WHERE client_order_id = %s;""",
        (coid,),
    )
    cum_qty = _to_float(fills[0]["cum_qty"]) if fills else 0.0
    n_fills = int(fills[0]["n_fills"]) if fills else 0
    original = _to_float(parent.get("size"))
    completion_pct = (cum_qty / original * 100.0) if original else 0.0

    status = "FINALIZED" if parent.get("status") in ("FILLED", "CANCELLED") else "ACTIVE"

    print(f"  {coid}  parent_size={original}  cum_qty={cum_qty}  fills={n_fills}  "
          f"pct={completion_pct:.2f}  -> status={status}")

    if not apply:
        return True

    query = """
    INSERT INTO partial_fill_progress (
        client_order_id, parent_client_order_id, product_id, side,
        original_order_size, min_order_size,
        last_cumulative_qty_processed, carry_remainder_qty,
        last_number_of_fills_seen, last_completion_pct_seen,
        partial_follow_ups_created, status, updated_at
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
    ON CONFLICT (client_order_id) DO NOTHING;
    """
    db.execute_update(
        query,
        (
            coid,
            parent.get("parent_order_id"),
            parent.get("product_id"),
            parent.get("side"),
            original,
            0.0,
            cum_qty,
            0.0,
            n_fills,
            completion_pct,
            0,
            status,
        ),
    )
    print(f"  [OK] inserted partial_fill_progress for {coid}")
    return True


# --- 3. Verification --------------------------------------------------------
def verify(db: PostgresDB) -> None:
    _section("[verify] order_parent + partial_fill_progress for affected COIDs")
    rows = db.execute_query(
        """SELECT op.client_order_id,
                  op.id            AS parent_id,
                  op.status        AS parent_status,
                  op.size          AS parent_size,
                  pfp.last_cumulative_qty_processed AS cum,
                  pfp.last_number_of_fills_seen     AS fills,
                  pfp.status                        AS pfp_status
           FROM order_parent op
           LEFT JOIN partial_fill_progress pfp
                  ON pfp.client_order_id = op.client_order_id
           WHERE op.client_order_id = ANY(%s)
           ORDER BY op.created_at;""",
        (ALL_AFFECTED,),
    ) or []
    have = {r["client_order_id"] for r in rows}
    for coid in ALL_AFFECTED:
        r = next((x for x in rows if x["client_order_id"] == coid), None)
        if not r:
            print(f"  STILL MISSING from order_parent: {coid}")
            continue
        pfp_state = (
            f"pfp_status={r['pfp_status']} cum={r['cum']} fills={r['fills']}"
            if r["pfp_status"] is not None else "pfp=MISSING"
        )
        print(f"  {coid}  parent.id={r['parent_id']} status={r['parent_status']} "
              f"size={r['parent_size']}   {pfp_state}")
    missing = set(ALL_AFFECTED) - have
    if missing:
        print(f"\n  Still missing from order_parent: {sorted(missing)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="Write changes; without this flag the script is read-only.")
    args = parser.parse_args()

    db = PostgresDB()
    db.connect()

    _section(f"[1] Recover missing parent {MISSING_PARENT}")
    recover_missing_parent(db, apply=args.apply)

    _section("[2] Backfill partial_fill_progress watermarks")
    for coid in ALL_AFFECTED:
        backfill_watermark(db, coid, apply=args.apply)

    verify(db)

    print()
    print("Done." if args.apply else "Dry-run complete. Re-run with --apply to write.")


if __name__ == "__main__":
    main()
