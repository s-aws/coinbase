"""One-shot fix: raise stuck-low target_movement values to 0.0015.

Scope: order_parent rows where
  - target_movement_type = 'P' (percentage)
  - 0 < target_movement < 0.0015
  - status NOT IN terminal set (FILLED, CANCELLED, RECONCILED_CLOSED, REJECTED, EXPIRED)
  - FAILED IS included per operator request 2026-05-04 (engine retries them)

Runs against the canonical writer ``update_parent_order_target_movement``
so any future audit logging / event emission stays consistent.
"""

from database.database import PostgresDB
from database.order import update_parent_order_target_movement

NEW_TARGET = 0.002
TERMINAL = ("FILLED", "CANCELLED", "RECONCILED_CLOSED", "REJECTED", "EXPIRED")


def main() -> None:
    db = PostgresDB()

    candidates = db.execute_query(
        f"""
        SELECT id, client_order_id, status, target_movement
        FROM order_parent
        WHERE target_movement IS NOT NULL
          AND target_movement < {NEW_TARGET}
          AND target_movement > 0
          AND target_movement_type = 'P'
          AND status NOT IN {TERMINAL}
        ORDER BY id
        """
    )

    print(f"=== {len(candidates)} rows to update ===")
    for r in candidates:
        print(
            f"  id={r['id']:>4}  status={r['status']:<10}  "
            f"current={r['target_movement']}  -> {NEW_TARGET}  "
            f"({r['client_order_id']})"
        )

    print()
    print("=== executing via update_parent_order_target_movement() ===")
    ok = 0
    fail = 0
    for r in candidates:
        coid = r["client_order_id"]
        try:
            result = update_parent_order_target_movement(
                coid, target_movement=NEW_TARGET, target_movement_type="P"
            )
            if result:
                ok += 1
            else:
                print(f"  WARN: {coid} returned False")
                fail += 1
        except Exception as e:
            print(f"  ERROR: {coid}: {e}")
            fail += 1

    print(f"\n=== complete: {ok} updated, {fail} failed ===\n")

    remaining = db.execute_query(
        f"""
        SELECT id, client_order_id, status, target_movement
        FROM order_parent
        WHERE target_movement IS NOT NULL
          AND target_movement < {NEW_TARGET}
          AND target_movement > 0
          AND target_movement_type = 'P'
          AND status NOT IN {TERMINAL}
        """
    )
    print(f"verification: {len(remaining)} rows still below threshold (expect 0)")
    for r in remaining:
        print(f"  STILL: {r}")


if __name__ == "__main__":
    main()
