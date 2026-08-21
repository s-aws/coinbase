"""Backfill REST-confirmed fills the WS pipeline missed.

Operator-driven recovery tool. Pulls the current
:class:`MissedFillsReport` (REST historical/fills minus local
``fill_ledger``), maps each REST fill back to its internal
``client_order_id`` via ``order_event_stream``, and inserts the missing
rows into ``fill_ledger`` with ``reconciliation_status = 'RECONCILED'``.

Design constraints (honored intentionally):

* Read-only by default. Inserts only after the operator types
  ``BACKFILL`` at the prompt — destructive recovery must never run
  unattended.
* Uses the existing :func:`database.order.insert_fill_record` insert
  path so the ``derived_trade_key`` UNIQUE constraint provides
  idempotency. Re-running the script is safe.
* ``derived_trade_key`` is ``uuid5(NAMESPACE_OID, entry_id)`` —
  ``entry_id`` is the exchange's per-match identifier and is globally
  unique, so the key is deterministic and stable across runs.
* Skips fills whose exchange ``order_id`` cannot be resolved to a
  ``client_order_id`` via ``order_event_stream``. Those are logged so
  the operator can investigate (likely orders placed by a different
  client).
* Promotes the inserted row to ``RECONCILED`` via a follow-up UPDATE
  keyed on ``derived_trade_key`` (handles both fresh inserts and the
  ON CONFLICT case where a row already existed but was not yet
  promoted).

Run:
    & C:/Users/heisg/AppData/Local/Programs/Python/Python313/python.exe \
        genai_tools/backfill_missed_fills.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set
from uuid import NAMESPACE_OID, uuid5

# Project root on path when launched from elsewhere.
import os
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.startup_reconciler import (
    audit_missed_fills,
    _fetch_client_order_ids_for_exchange_order_ids,
)
from database.database import PostgresDB
from database.order import insert_fill_record
from logging_service import get_logger


logger = get_logger("BackfillMissedFills")


_CONFIRM_TOKEN = "BACKFILL"


def _derived_key_for_entry(entry_id: str) -> str:
    """Deterministic UUID5 keyed on the exchange entry_id.

    Matches the idempotency strategy used by the live derived-fill
    path (which keys on ``client_order_id`` + cumulative quantity);
    using ``entry_id`` here gives the same uniqueness guarantee for
    REST-sourced rows without needing the WS counter context.
    """
    return str(uuid5(NAMESPACE_OID, entry_id))


def _safe_decimal_str(value, default: float = 0.0) -> float:
    """REST returns numeric fields as strings; coerce safely."""
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_trade_time(raw: str) -> datetime:
    """Parse ISO-8601 trade_time. REST uses Zulu suffix."""
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    return datetime.fromisoformat(raw)


def _promote_to_reconciled(db: PostgresDB, derived_trade_key: str) -> bool:
    """Stamp the row as RECONCILED with current UTC timestamp.

    Idempotent: skips rows already RECONCILED so re-runs are quiet.
    Returns True iff a row was actually updated.
    """
    rows = db.execute_query(
        """
        UPDATE fill_ledger
           SET reconciliation_status = 'RECONCILED',
               reconciled_at = NOW()
         WHERE derived_trade_key = %s
           AND reconciliation_status <> 'RECONCILED'
         RETURNING id
        """,
        (derived_trade_key,),
    )
    return bool(rows)


def _summarize(missed: List[dict], oid_to_coid: Dict[str, str]) -> None:
    """Print operator-facing summary before the confirmation prompt."""
    if not missed:
        print("No missed fills to backfill.")
        return

    by_product: Dict[str, int] = {}
    by_side: Dict[str, int] = {}
    notional_by_product: Dict[str, float] = {}
    unresolved_orders: Set[str] = set()
    resolved_count = 0

    for fill in missed:
        product = fill.get("product_id") or "<unknown>"
        side = fill.get("side") or "<unknown>"
        size = _safe_decimal_str(fill.get("size"))
        price = _safe_decimal_str(fill.get("price"))
        order_id = str(fill.get("order_id") or "")

        by_product[product] = by_product.get(product, 0) + 1
        by_side[side] = by_side.get(side, 0) + 1
        notional_by_product[product] = (
            notional_by_product.get(product, 0.0) + size * price
        )
        if order_id and order_id in oid_to_coid:
            resolved_count += 1
        elif order_id:
            unresolved_orders.add(order_id)

    print("=" * 72)
    print(f"Missed fills detected: {len(missed)}")
    print(f"  resolvable to client_order_id: {resolved_count}")
    print(f"  unresolvable (will be skipped): {len(missed) - resolved_count}")
    if unresolved_orders:
        print(f"  unresolvable distinct order_ids: {len(unresolved_orders)}")
    print()
    print("By product:")
    for product, count in sorted(by_product.items()):
        notional = notional_by_product.get(product, 0.0)
        print(f"  {product:<24} count={count:<5} notional≈{notional:,.2f}")
    print()
    print("By side:")
    for side, count in sorted(by_side.items()):
        print(f"  {side:<8} {count}")
    print("=" * 72)


def _confirm() -> bool:
    """Operator gate. Anything other than the exact token aborts."""
    print()
    print(f'Type "{_CONFIRM_TOKEN}" to insert missed fills into fill_ledger,')
    print("or anything else to abort: ", end="", flush=True)
    try:
        answer = input().strip()
    except EOFError:
        return False
    return answer == _CONFIRM_TOKEN


def main() -> int:
    print("Running missed-fills audit (this hits REST historical/fills)...")
    report = audit_missed_fills()
    if report is None:
        print("REST client unavailable; cannot run backfill.", file=sys.stderr)
        return 2

    print(report.to_missed_fills_summary_dict())

    if not report.has_missed_fills:
        print("No missed fills. Nothing to do.")
        return 0

    # Resolve exchange order_id -> internal client_order_id once up-front.
    order_ids = {
        str(f.get("order_id"))
        for f in report.missed
        if f.get("order_id")
    }
    oid_to_coid = _fetch_client_order_ids_for_exchange_order_ids(order_ids)

    _summarize(report.missed, oid_to_coid)

    if not _confirm():
        print("Aborted by operator. No rows inserted.")
        return 1

    db = PostgresDB()
    inserted = 0
    promoted_existing = 0
    skipped_unresolved = 0
    failed = 0

    try:
        for fill in report.missed:
            entry_id: Optional[str] = fill.get("entry_id")
            order_id = str(fill.get("order_id") or "")
            if not entry_id:
                logger.warning(
                    "Backfill: REST fill missing entry_id; skipping",
                    extra={"fill": fill},
                )
                failed += 1
                continue

            client_order_id = oid_to_coid.get(order_id)
            if not client_order_id:
                logger.warning(
                    "Backfill: cannot resolve order_id to client_order_id; skipping",
                    extra={"order_id": order_id, "entry_id": entry_id},
                )
                skipped_unresolved += 1
                continue

            derived_key = _derived_key_for_entry(entry_id)

            try:
                inserted_id = insert_fill_record(
                    derived_trade_key=derived_key,
                    instrument=fill.get("product_id"),
                    side=fill.get("side"),
                    quantity=_safe_decimal_str(fill.get("size")),
                    price=_safe_decimal_str(fill.get("price")),
                    timestamp=_parse_trade_time(fill["trade_time"]),
                    fees=_safe_decimal_str(fill.get("fee")),
                    commission_percentage=_safe_decimal_str(
                        fill.get("user_fee_rate")
                    ),
                    client_order_id=client_order_id,
                    exchange_trade_id=fill.get("trade_id"),
                    exchange_entry_id=entry_id,
                )
            except Exception:
                logger.exception(
                    "Backfill: insert failed",
                    extra={"entry_id": entry_id, "order_id": order_id},
                )
                failed += 1
                continue

            try:
                promoted = _promote_to_reconciled(db, derived_key)
            except Exception:
                logger.exception(
                    "Backfill: promotion to RECONCILED failed",
                    extra={"derived_trade_key": derived_key},
                )
                failed += 1
                continue

            if inserted_id is not None:
                inserted += 1
            elif promoted:
                # Row already existed (ON CONFLICT) but had not been
                # promoted yet — count it as a recovered row, not a new one.
                promoted_existing += 1
            # else: row existed AND was already RECONCILED -> no-op, no count
    finally:
        try:
            db.disconnect()
        except Exception:
            pass

    print()
    print("=" * 72)
    print("Backfill complete.")
    print(f"  inserted (new rows):              {inserted}")
    print(f"  promoted (existing -> RECONCILED): {promoted_existing}")
    print(f"  skipped (unresolved order_id):    {skipped_unresolved}")
    print(f"  failed:                           {failed}")
    print("=" * 72)

    return 0 if failed == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
