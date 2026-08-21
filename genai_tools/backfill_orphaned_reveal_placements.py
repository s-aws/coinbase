"""Backfill orphaned reveal-placement rows in `order_parent`.

Background
----------
Until 2026-04-29 the stealth manager inserted the `order_parent` row for a
reveal placement AFTER `REST_CLIENT.place_limit_order(...)` returned. The
WS confirmation for that REST call could (and did) arrive first, fall into
``OrderEngine.resolve_parent_client_order_id(create_parent=True)``, and
insert the placement uuid as a ROOT row with:

    parent_order_id          = NULL              (should be chain-root stealth)
    max_order_replacement    = orderbook default (should be inherited from stealth)
    target_movement          = order-derived     (should be inherited from stealth)
    target_movement_type     = "P"               (should be inherited from stealth)

This silently broke the flat hierarchy: the placement row appeared as a
standalone root rather than a child of the originating stealth order.

What this script does
---------------------
For every `order_parent` row P where:
    * P.parent_order_id IS NULL
    * P.client_order_id is NOT itself a stealth_order_id (i.e. it is not a
      legitimate root parent)
    * P.client_order_id appears in `stealth_order_reveal_history` as a
      placement (placement_client_order_id OR placed_order_id) of some
      stealth S

…the script:

    1. Resolves S's chain root R (follow stealth_orders.parent_order_id
       up until NULL — flat hierarchy means R == S in nearly all cases,
       but stealth follow-ups are walked to be safe).
    2. Reads R's canonical order_parent row to source:
           - target_movement
           - target_movement_type
           - max_order_replacement
    3. UPDATEs P with parent_order_id=R, plus the three inherited fields.
    4. After processing all orphans, re-syncs every affected root R's
       `current_order_replacement` to the actual count of children whose
       parent_order_id points at R.

Defaults to DRY-RUN. Pass ``--apply`` to write changes.

Usage
-----
    # Preview (default):
    python genai_tools/backfill_orphaned_reveal_placements.py

    # Apply:
    python genai_tools/backfill_orphaned_reveal_placements.py --apply
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional

from database.order import DB_CLIENT


SELECT_ORPHANS_SQL = """
SELECT DISTINCT
    op.id                AS placement_db_id,
    op.client_order_id   AS placement_client_order_id,
    op.product_id,
    op.side,
    op.size,
    op.price,
    op.status,
    op.target_movement   AS placement_target_movement,
    op.target_movement_type AS placement_tm_type,
    op.max_order_replacement AS placement_max_repl,
    op.created_at        AS placement_created_at,
    srh.stealth_order_id AS reveal_stealth_id
FROM order_parent op
JOIN stealth_order_reveal_history srh
  ON (
        srh.placement_client_order_id::text = op.client_order_id
     OR srh.placed_order_id::text          = op.client_order_id
  )
WHERE op.parent_order_id IS NULL
  AND NOT EXISTS (
        SELECT 1 FROM stealth_orders so
        WHERE so.stealth_order_id::text = op.client_order_id
  )
ORDER BY op.id
"""


def resolve_chain_root(stealth_order_id: str) -> Optional[str]:
    """Walk stealth_orders.parent_order_id up to NULL. Returns root id."""
    current = stealth_order_id
    seen = set()
    while True:
        if current in seen:
            print(f"  [WARN] cycle detected at {current}, aborting walk")
            return None
        seen.add(current)
        rows = DB_CLIENT.execute_query(
            "SELECT parent_order_id FROM stealth_orders WHERE stealth_order_id = %s",
            (current,),
        )
        if not rows:
            return current  # not in stealth_orders; treat as terminal
        parent = rows[0]["parent_order_id"]
        if parent is None:
            return current
        current = str(parent)


def fetch_root_parent_row(client_order_id: str) -> Optional[dict]:
    rows = DB_CLIENT.execute_query(
        """
        SELECT id, client_order_id, target_movement, target_movement_type,
               max_order_replacement, current_order_replacement
        FROM order_parent
        WHERE client_order_id = %s
        """,
        (client_order_id,),
    )
    return rows[0] if rows else None


def update_orphan(
    placement_client_order_id: str,
    chain_root: str,
    target_movement,
    target_movement_type: str,
    max_order_replacement: int,
    apply: bool,
) -> None:
    if not apply:
        return
    DB_CLIENT.execute_update(
        """
        UPDATE order_parent
           SET parent_order_id       = %s,
               target_movement       = %s,
               target_movement_type  = %s,
               max_order_replacement = %s
         WHERE client_order_id = %s
        """,
        (
            chain_root,
            target_movement,
            target_movement_type,
            int(max_order_replacement),
            placement_client_order_id,
        ),
    )


def resync_root_replacement_count(
    root_client_order_id: str,
    apply: bool,
    pending_link_count: int = 0,
) -> tuple[int, int]:
    """Returns (db_value_before, projected_real_count). Updates DB if apply=True.

    ``pending_link_count`` is the number of orphans this script is about to
    link under this root. In dry-run mode they are not yet linked in the DB,
    so we add them to the count to show the post-apply value.
    """
    rows = DB_CLIENT.execute_query(
        "SELECT current_order_replacement FROM order_parent WHERE client_order_id = %s",
        (root_client_order_id,),
    )
    db_before = int(rows[0]["current_order_replacement"]) if rows else 0

    rows = DB_CLIENT.execute_query(
        "SELECT COUNT(*) AS c FROM order_parent WHERE parent_order_id = %s",
        (root_client_order_id,),
    )
    actual_in_db = int(rows[0]["c"]) if rows else 0
    projected = actual_in_db if apply else (actual_in_db + pending_link_count)

    if apply and db_before != projected:
        DB_CLIENT.execute_update(
            "UPDATE order_parent SET current_order_replacement = %s WHERE client_order_id = %s",
            (projected, root_client_order_id),
        )
    return db_before, projected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes. Without this flag the script only previews.",
    )
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== Backfill orphaned reveal placements [{mode}] ===\n")

    orphans = DB_CLIENT.execute_query(SELECT_ORPHANS_SQL)
    print(f"Found {len(orphans)} orphan reveal-placement rows.\n")

    if not orphans:
        print("Nothing to do.")
        return 0

    affected_roots: dict[str, int] = {}
    skipped: list[str] = []

    print(
        f"{'placement_id':<40} {'-> chain_root':<40} "
        f"{'old_max':>7} {'new_max':>7} {'old_tm':>10} {'new_tm':>10} {'tm_type':>8}"
    )
    print("-" * 130)

    for row in orphans:
        placement_coid = row["placement_client_order_id"]
        reveal_stealth_id = str(row["reveal_stealth_id"])

        chain_root = resolve_chain_root(reveal_stealth_id)
        if not chain_root:
            skipped.append(f"{placement_coid} (no chain root)")
            continue

        if chain_root == placement_coid:
            # Defensive: should not happen given the NOT EXISTS guard above
            skipped.append(f"{placement_coid} (resolves to self)")
            continue

        root_row = fetch_root_parent_row(chain_root)
        if not root_row:
            skipped.append(f"{placement_coid} (chain root {chain_root} has no order_parent row)")
            continue

        new_tm = root_row["target_movement"]
        new_tm_type = root_row["target_movement_type"] or "P"
        new_max = int(root_row["max_order_replacement"])

        print(
            f"{placement_coid:<40} {chain_root:<40} "
            f"{int(row['placement_max_repl']):>7} {new_max:>7} "
            f"{str(row['placement_target_movement']):>10} {str(new_tm):>10} "
            f"{new_tm_type:>8}"
        )

        update_orphan(
            placement_client_order_id=placement_coid,
            chain_root=chain_root,
            target_movement=new_tm,
            target_movement_type=new_tm_type,
            max_order_replacement=new_max,
            apply=args.apply,
        )
        affected_roots[chain_root] = affected_roots.get(chain_root, 0) + 1

    print()
    if skipped:
        print(f"Skipped {len(skipped)} rows:")
        for s in skipped:
            print(f"  - {s}")
        print()

    print(f"=== Re-sync current_order_replacement on {len(affected_roots)} affected root(s) ===")
    for root in sorted(affected_roots):
        before, projected = resync_root_replacement_count(
            root, apply=args.apply, pending_link_count=affected_roots[root]
        )
        marker = "  (no change)" if before == projected else f"  -> {projected}"
        print(f"  {root}: db={before} projected_children={projected}{marker}")

    print()
    if args.apply:
        print("APPLY complete.")
    else:
        print("DRY-RUN complete. Re-run with --apply to write changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
