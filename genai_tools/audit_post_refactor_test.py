"""Quick audit dump for the post-refactor live test on 2026-04-26.

Pulls the relevant rows from fill_ledger, order_match_audit,
partial_fill_progress, and order_parent for the two filled orders so we
can verify the new tracker pipeline did the right thing.
"""

from __future__ import annotations

import json
import sys

sys.path.insert(0, "e:\\coinbase")

from database.database import PostgresDB


COIDS = [
    "1459febd-6d7d-4c9a-a30b-f834e6e34a0a",  # SELL 5 BIP-20DEC30-CDE (clean fill)
    "0753a2ae-01ba-4d10-8005-f2acbcf3910d",  # SELL 5 BIT-29MAY26-CDE (3 partials)
    "5d66dd34-66d7-47bb-8d8e-a61882510f0d",  # follow-up child of #1
    "dea4b49d-f736-4bd0-a4ac-cfa123efb28e",  # follow-up child of #2
]


def _print_section(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def _dump_rows(rows, columns):
    if not rows:
        print("  (no rows)")
        return
    for row in rows:
        for col in columns:
            print(f"  {col}={row.get(col)!r}")
        print("  --")


def main() -> int:
    db = PostgresDB()

    _print_section("order_parent")
    rows = db.execute_query(
        "SELECT id, client_order_id, product_id, side, size, price, status, "
        "max_order_replacement, current_order_replacement, allow_partial_fills, "
        "parent_order_id "
        "FROM order_parent ORDER BY id"
    )
    _dump_rows(rows, [
        "id", "client_order_id", "product_id", "side", "size", "price",
        "status", "max_order_replacement", "current_order_replacement",
        "allow_partial_fills", "parent_order_id",
    ])

    _print_section("fill_ledger")
    rows = db.execute_query(
        "SELECT id, client_order_id, derived_trade_key, exchange_trade_id, "
        "exchange_entry_id, reconciliation_status, side, quantity, price, fees, "
        "timestamp "
        "FROM fill_ledger ORDER BY id"
    )
    _dump_rows(rows, [
        "id", "client_order_id", "derived_trade_key", "exchange_trade_id",
        "reconciliation_status", "side", "quantity", "price", "fees", "timestamp",
    ])

    _print_section("order_match_audit")
    try:
        rows = db.execute_query(
            "SELECT id, client_order_id, snapshot_seq, cumulative_quantity, "
            "filled_value, total_fees, number_of_fills, status, "
            "derived_size_delta, derived_value_delta, derived_price, "
            "derived_trade_key, emitted_fill_ledger_row, created_at "
            "FROM order_match_audit ORDER BY id"
        )
        _dump_rows(rows, [
            "id", "client_order_id", "snapshot_seq", "cumulative_quantity",
            "filled_value", "total_fees", "number_of_fills", "status",
            "derived_size_delta", "derived_value_delta", "derived_price",
            "derived_trade_key", "emitted_fill_ledger_row", "created_at",
        ])
    except Exception as e:
        print(f"  query failed: {type(e).__name__}: {e}")

    _print_section("partial_fill_progress")
    try:
        rows = db.execute_query(
            "SELECT client_order_id, parent_client_order_id, product_id, side, "
            "original_order_size, min_order_size, last_cumulative_qty_processed, "
            "carry_remainder_qty, last_number_of_fills_seen, "
            "last_completion_pct_seen, partial_follow_ups_created, status, "
            "updated_at "
            "FROM partial_fill_progress ORDER BY client_order_id"
        )
        _dump_rows(rows, [
            "client_order_id", "parent_client_order_id", "product_id", "side",
            "original_order_size", "min_order_size", "last_cumulative_qty_processed",
            "carry_remainder_qty", "last_number_of_fills_seen",
            "last_completion_pct_seen", "partial_follow_ups_created", "status",
            "updated_at",
        ])
    except Exception as e:
        print(f"  query failed: {type(e).__name__}: {e}")

    _print_section("Per-order summary")
    for coid in COIDS:
        ledger = db.execute_query(
            "SELECT COUNT(*) AS n, COALESCE(SUM(quantity), 0) AS qty, "
            "COALESCE(SUM(fees), 0) AS fees "
            "FROM fill_ledger WHERE client_order_id = %s",
            (coid,),
        )
        audit = db.execute_query(
            "SELECT COUNT(*) AS n, MAX(cumulative_quantity) AS cum, "
            "MAX(number_of_fills) AS fills "
            "FROM order_match_audit WHERE client_order_id = %s",
            (coid,),
        )
        print(f"  {coid}")
        if ledger:
            print(f"    fill_ledger: rows={ledger[0]['n']} qty={ledger[0]['qty']} fees={ledger[0]['fees']}")
        if audit:
            print(f"    order_match_audit: snapshots={audit[0]['n']} cum={audit[0]['cum']} fills={audit[0]['fills']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
