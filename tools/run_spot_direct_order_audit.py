"""Audit one manual direct spot order by client_order_id.

This command is read-only. It reads local ``order_event_stream`` and
``fill_ledger`` evidence only; it never submits Coinbase orders and does not
call Coinbase REST.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT_PATH = str(PROJECT_ROOT)
sys.path = [path for path in sys.path if path != PROJECT_ROOT_PATH]
sys.path.insert(0, PROJECT_ROOT_PATH)

from business.spot_direct_order_audit import (
    build_spot_direct_order_audit,
    fetch_direct_order_event_rows,
    fetch_direct_order_fill_rows,
)
from core.enums import SpotDirectOrderAuditStatus


SUMMARY_PREFIX = "SPOT_DIRECT_ORDER_AUDIT "


def _append_jsonl(path: Path, record: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(dict(record), sort_keys=True))
        handle.write("\n")


def _build_db_client() -> Any:
    from database.database import PostgresDB

    return PostgresDB()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read local audit evidence for a manual direct dashboard spot "
            "order by client_order_id."
        )
    )
    parser.add_argument(
        "--client-order-id",
        required=True,
        help="Internal client_order_id returned by dashboard place_order.",
    )
    parser.add_argument(
        "--event-limit",
        type=int,
        default=100,
        help="Maximum order_event_stream rows to inspect.",
    )
    parser.add_argument(
        "--fill-limit",
        type=int,
        default=1000,
        help="Maximum fill_ledger rows to inspect.",
    )
    parser.add_argument(
        "--audit-file",
        type=Path,
        default=None,
        help="Optional JSONL file to append the audit record to.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Omit per-event and per-fill rows from printed output.",
    )
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="Return success even when submission evidence is not found.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    db_client = _build_db_client()
    event_rows = fetch_direct_order_event_rows(
        db_client=db_client,
        client_order_id=args.client_order_id,
        limit=args.event_limit,
    )
    fill_rows = fetch_direct_order_fill_rows(
        db_client=db_client,
        client_order_id=args.client_order_id,
        limit=args.fill_limit,
    )
    report = build_spot_direct_order_audit(
        client_order_id=args.client_order_id,
        event_rows=event_rows,
        fill_rows=fill_rows,
        include_events=not args.summary_only,
        include_fills=not args.summary_only,
    )
    if args.audit_file:
        _append_jsonl(args.audit_file, report)
    print(SUMMARY_PREFIX + json.dumps(report, sort_keys=True))
    if args.allow_missing:
        return 0
    return (
        0
        if report["status"] == SpotDirectOrderAuditStatus.FOUND.value
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
