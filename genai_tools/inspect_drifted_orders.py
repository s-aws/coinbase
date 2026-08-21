"""One-shot diagnostic: inspect non-terminal local order_parent rows.

Reports breakdown by status, side, product, and age — the data needed
to decide whether to flip auto_heal=True in main.py.

Usage (from any cwd, after `pip install -e .`):
    py -3.13 genai_tools/inspect_drifted_orders.py
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from database.database import PostgresDB


TERMINAL = {
    "FILLED",
    "CANCELLED",
    "REJECTED",
    "EXPIRED",
    "FAILED",
    "RECONCILED_CLOSED",
}


def main() -> None:
    db = PostgresDB()
    try:
        rows = db.execute_query(
            "SELECT client_order_id, status, side, product_id, "
            "       created_at, parent_order_id "
            "FROM order_parent "
            "ORDER BY created_at DESC"
        )
    finally:
        try:
            db.disconnect()
        except Exception:
            pass

    rows = rows or []
    drifted = [
        r for r in rows
        if (r.get("status") or "").upper() not in TERMINAL
    ]

    print(f"Total order_parent rows: {len(rows)}")
    print(f"Non-terminal (drifted):  {len(drifted)}")
    print()

    if not drifted:
        print("No drift to report.")
        return

    # Breakdown by status
    print("By status:")
    for status, count in Counter(r.get("status") for r in drifted).most_common():
        print(f"  {status!r:30s} {count}")
    print()

    # Breakdown by product
    print("By product:")
    for product, count in Counter(r.get("product_id") for r in drifted).most_common():
        print(f"  {product:20s} {count}")
    print()

    # Age distribution
    now = datetime.now(timezone.utc)
    age_buckets = Counter()
    for r in drifted:
        created = r.get("created_at")
        if created is None:
            age_buckets["unknown"] += 1
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age = now - created
        if age.days >= 7:
            age_buckets[">= 7 days"] += 1
        elif age.days >= 1:
            age_buckets["1-7 days"] += 1
        elif age.total_seconds() >= 3600:
            age_buckets["1h-1d"] += 1
        else:
            age_buckets["< 1h"] += 1

    print("By age:")
    for bucket, count in age_buckets.most_common():
        print(f"  {bucket:15s} {count}")
    print()

    # First 10 examples
    print("First 10 examples (most recent):")
    for r in drifted[:10]:
        print(
            f"  {r.get('client_order_id'):40s} "
            f"{(r.get('status') or 'NULL'):15s} "
            f"{r.get('side'):5s} "
            f"{r.get('product_id'):12s} "
            f"created={r.get('created_at')} "
            f"parent={r.get('parent_order_id')}"
        )


if __name__ == "__main__":
    main()
