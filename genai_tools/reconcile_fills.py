"""Operator script: reconcile WS-derived fill_ledger rows against REST fills.

USAGE
-----
Reconcile a single order::

    python genai_tools/reconcile_fills.py \
        --client-order-id <coid> --exchange-order-id <eoid>

Reconcile every order with at least one ``WS_DERIVED`` row in fill_ledger
(uses order_parent.exchange_order_id for the REST lookup)::

    python genai_tools/reconcile_fills.py --all

Dry-run (no DB writes, prints the report only)::

    python genai_tools/reconcile_fills.py --all --dry-run

WHY THIS EXISTS
---------------
The live WebSocket pipeline only sees aggregated counters
(``cumulative_quantity`` / ``filled_value`` / ``total_fees``). We derive
per-match rows from those counters and write them to ``fill_ledger`` with
``reconciliation_status = 'WS_DERIVED'``. This script pulls the
authoritative per-match list from
``GET /api/v3/brokerage/orders/historical/fills`` and:

  * stamps ``exchange_trade_id`` / ``exchange_entry_id`` on matched rows and
    flips them to ``RECONCILED``;
  * flips unmatched WS rows to ``MISMATCH`` for operator review;
  * reports REST fills with no WS counterpart (indicates a WS pipeline gap).

Run this as a recurring job (e.g., hourly cron) and after any WS reconnect
storm.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Dict, List, Optional

# Allow running the script directly from the repo root or from genai_tools/.
sys.path.insert(0, "e:\\coinbase")

from business.fill_reconciler import FillReconciler, ReconcileReport
from configuration import REST_CLIENT
from database.database import PostgresDB
from logging_service import get_logger


logger = get_logger("reconcile_fills")


def _build_fills_fetcher():
    """Return a callable ``exchange_order_id -> list[REST fill dict]``.

    Wraps the SDK's ``get_fills(order_id=...)`` so the reconciler stays
    SDK-agnostic and unit-testable.
    """
    sdk = REST_CLIENT.get_sdk_client()

    def _fetch(exchange_order_id: str) -> List[Dict[str, Any]]:
        if not exchange_order_id:
            return []
        # The SDK returns either a typed object with a `fills` attribute or a
        # plain dict; handle both.
        response = sdk.get_fills(order_id=exchange_order_id)
        fills = getattr(response, "fills", None)
        if fills is None and isinstance(response, dict):
            fills = response.get("fills")
        return list(fills or [])

    return _fetch


def _orders_needing_reconciliation(db: PostgresDB) -> List[Dict[str, str]]:
    """Return ``[{client_order_id, exchange_order_id}, ...]`` for orders with
    at least one WS_DERIVED row.

    The exchange-side order id lives on the ``stealth_order_reveal_history``
    audit row that recorded the actual REST placement (``placed_order_id`` is
    the ``client_order_id`` of the placed order; ``exchange_order_id`` is the
    Coinbase-assigned UUID returned at placement time). We pick the most
    recent reveal row per ``placed_order_id`` to recover that mapping.
    """
    query = """
        WITH latest_reveal AS (
            SELECT placed_order_id::text AS client_order_id,
                   exchange_order_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY placed_order_id
                       ORDER BY id DESC
                   ) AS rn
              FROM stealth_order_reveal_history
             WHERE placed_order_id IS NOT NULL
               AND exchange_order_id IS NOT NULL
        )
        SELECT DISTINCT fl.client_order_id,
               lr.exchange_order_id
          FROM fill_ledger fl
          JOIN latest_reveal lr
            ON lr.client_order_id = fl.client_order_id
           AND lr.rn = 1
         WHERE fl.reconciliation_status = 'WS_DERIVED'
         ORDER BY fl.client_order_id ASC
    """
    try:
        return list(db.execute_query(query) or [])
    except Exception as e:
        logger.error(
            "Failed to enumerate orders needing reconciliation: %s: %s",
            type(e).__name__,
            e,
        )
        return []


def _print_report(report: ReconcileReport) -> None:
    print(
        f"  matched={len(report.matched)}  "
        f"ws_unmatched={len(report.ws_unmatched)}  "
        f"rest_unmatched={len(report.rest_unmatched)}  "
        f"rows_updated={report.rows_updated}"
    )
    for key in report.ws_unmatched:
        print(f"    [MISMATCH] derived_trade_key={key}")
    for rest in report.rest_unmatched:
        print(
            f"    [REST-ORPHAN] trade_id={rest.get('trade_id')} "
            f"size={rest.get('size')} price={rest.get('price')}"
        )


def _make_dry_run_db(real_db: PostgresDB) -> Any:
    """Return a thin shim that forwards SELECTs but no-ops UPDATEs."""

    class _DryRunDB:
        def execute_query(self, query, params=None):
            return real_db.execute_query(query, params) if params is not None else real_db.execute_query(query)

        def execute_update(self, query, params=None):
            print(f"  [DRY-RUN] would UPDATE: params={params}")
            return 0

    return _DryRunDB()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reconcile WS-derived fill_ledger rows with REST fills."
    )
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument(
        "--client-order-id",
        help="Reconcile a single order. Requires --exchange-order-id.",
    )
    selector.add_argument(
        "--all",
        action="store_true",
        help="Reconcile every order with at least one WS_DERIVED ledger row.",
    )
    parser.add_argument(
        "--exchange-order-id",
        help="Exchange order id (required with --client-order-id).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the report without applying any UPDATEs.",
    )
    args = parser.parse_args()
    if args.client_order_id and not args.exchange_order_id:
        parser.error("--client-order-id requires --exchange-order-id")
    return args


def main() -> int:
    args = _parse_args()

    real_db = PostgresDB()
    db_for_reconciler = _make_dry_run_db(real_db) if args.dry_run else real_db
    fetcher = _build_fills_fetcher()
    reconciler = FillReconciler(db_for_reconciler, fetcher)

    if args.client_order_id:
        targets: List[Dict[str, Optional[str]]] = [
            {
                "client_order_id": args.client_order_id,
                "exchange_order_id": args.exchange_order_id,
            }
        ]
    else:
        targets = _orders_needing_reconciliation(real_db)
        if not targets:
            print("Nothing to reconcile — no WS_DERIVED rows found.")
            return 0
        print(f"Reconciling {len(targets)} order(s)...")

    exit_code = 0
    for row in targets:
        coid = row.get("client_order_id")
        eoid = row.get("exchange_order_id")
        if not (coid and eoid):
            print(f"  [SKIP] missing ids: client_order_id={coid} exchange_order_id={eoid}")
            continue
        print(f"\nOrder client_order_id={coid} exchange_order_id={eoid}")
        report = reconciler.reconcile_order(coid, eoid)
        _print_report(report)
        if not report.is_clean:
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
