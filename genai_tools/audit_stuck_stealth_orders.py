"""Audit the two stealth orders that were placed but aren't triggering.

Schema verified via information_schema before queries (per repo memory rule #10).
"""
from __future__ import annotations
from database.database import PostgresDB

SIDS = (
    "a70465d0-1ac3-4cc5-afcf-96895fb77387",
    "a8d5c4e7-5f82-4850-8f50-15dfb3b0dce3",
)
PRODUCT_ID = "BIP-20DEC30-CDE"

SO_COLS = (
    "stealth_order_id, parent_order_id, product_id, side, status, "
    "total_size, revealed_size, remaining_size, executed_size, "
    "limit_price, reveal_condition_type, reveal_condition_json, "
    "condition_first_met_at, condition_confirmed_at, "
    "anchor_repricing_policy_json, anchor_repricing_state_json, "
    "target_movement, target_movement_type, last_lifecycle_event, "
    "failure_reason, last_placement_at, created_at, updated_at"
)

OP_COLS = (
    "client_order_id, product_id, side, status, size, price, "
    "parent_order_id, target_movement, target_movement_type, "
    "max_order_replacement, current_order_replacement, "
    "allow_partial_fills, created_at"
)


def _print_row(row: dict, indent: str = "  ") -> None:
    for k, v in row.items():
        print(f"{indent}{k}: {v}")


def main() -> None:
    db = PostgresDB()

    print("=" * 78)
    print("STEALTH ORDERS")
    print("=" * 78)
    rows = db.execute_query(
        f"SELECT {SO_COLS} FROM stealth_orders WHERE stealth_order_id = ANY(%s::uuid[]) "
        "ORDER BY created_at",
        (list(SIDS),),
    )
    for r in rows:
        print(f"\n--- {r['stealth_order_id']} ---")
        _print_row(r)
    missing = set(SIDS) - {r["stealth_order_id"] for r in rows}
    if missing:
        print(f"\n!! NOT FOUND in stealth_orders: {missing}")

    print("\n" + "=" * 78)
    print("ORDER_PARENT rows")
    print("=" * 78)
    parents = db.execute_query(
        f"SELECT {OP_COLS} FROM order_parent WHERE client_order_id = ANY(%s::uuid[]) "
        "ORDER BY created_at",
        (list(SIDS),),
    )
    if parents:
        for p in parents:
            print(f"\n--- {p['client_order_id']} ---")
            _print_row(p)
    else:
        print("  (none)")

    print("\n" + "=" * 78)
    print(f"LATEST market_tick rows for {PRODUCT_ID}")
    print("=" * 78)
    ticks = db.execute_query(
        "SELECT product_id, best_bid, best_ask, price, ts "
        "FROM market_tick WHERE product_id=%s ORDER BY ts DESC LIMIT 5",
        (PRODUCT_ID,),
    )
    if ticks:
        for t in ticks:
            print(f"  {t['ts']}  bid={t['best_bid']}  ask={t['best_ask']}  last={t['price']}")
    else:
        print("  (no market_tick rows for this product)")

    print("\n" + "=" * 78)
    print("Recent order_event_stream events for these sids")
    print("=" * 78)
    events = db.execute_query(
        "SELECT created_at, event_type, event_status_from, event_status_to, "
        "       client_order_id, order_id, source_channel "
        "FROM order_event_stream "
        "WHERE client_order_id = ANY(%s::uuid[]) OR stealth_order_id = ANY(%s::uuid[]) "
        "ORDER BY created_at DESC LIMIT 30",
        (list(SIDS), list(SIDS)),
    )
    if events:
        for e in events:
            print(f"  {e['created_at']}  {e['event_type']}  "
                  f"{e['event_status_from']}->{e['event_status_to']}  "
                  f"coid={e['client_order_id']}  src={e['source_channel']}")
    else:
        print("  (no events)")

    print("\n" + "=" * 78)
    print("stealth_order_lifecycle_history (last 30 rows)")
    print("=" * 78)
    cols = db.execute_query(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name=%s ORDER BY ordinal_position",
        ("stealth_order_lifecycle_history",),
    )
    if cols:
        col_list = ", ".join(c["column_name"] for c in cols)
        hist = db.execute_query(
            f"SELECT {col_list} FROM stealth_order_lifecycle_history "
            "WHERE stealth_order_id = ANY(%s::uuid[]) "
            "ORDER BY id DESC LIMIT 30",
            (list(SIDS),),
        )
        if hist:
            for h in hist:
                print(f"\n  --- entry ---")
                _print_row(h, indent="    ")
        else:
            print("  (no lifecycle rows)")


if __name__ == "__main__":
    main()
