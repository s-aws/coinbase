"""Audit local spot fill-ledger data quality.

This command is read-only. It never submits Coinbase orders and does not call
Coinbase unless a separate repair command is run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from business.spot_fill_ledger_health import (
    DEFAULT_QUOTE_CURRENCY,
    analyze_spot_fill_ledger_rows,
    fetch_spot_fill_ledger_rows,
)
from core.enums import SpotFillLedgerHealthStatus
from tools.run_spot_fill_backfill_recovery import (
    DEFAULT_SMOKE_AUDIT_FILE,
    DEFAULT_SWEEP_STATE_FILE,
    _load_jsonl_records,
    collect_backfill_order_reports,
)


SUMMARY_PREFIX = "SPOT_FILL_LEDGER_HEALTH "


def _append_jsonl(path: Path, record: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(dict(record), sort_keys=True))
        handle.write("\n")


def _build_db_client() -> Any:
    from business.fill_ledger import FillLedgerRepository
    from database.database import PostgresDB

    repo = FillLedgerRepository(PostgresDB())
    return repo.db_client


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit local USDC spot fill-ledger rows for data hazards."
    )
    parser.add_argument(
        "--quote-currency",
        default=DEFAULT_QUOTE_CURRENCY,
        help="Quote currency suffix to audit.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10000,
        help="Maximum fill-ledger rows to inspect.",
    )
    parser.add_argument(
        "--smoke-audit-file",
        type=Path,
        default=DEFAULT_SMOKE_AUDIT_FILE,
        help="Live smoke JSONL audit file used for repairability evidence.",
    )
    parser.add_argument(
        "--sweep-state-file",
        type=Path,
        default=DEFAULT_SWEEP_STATE_FILE,
        help="Spot sweep JSONL state file used for repairability evidence.",
    )
    parser.add_argument(
        "--audit-file",
        type=Path,
        default=None,
        help="Optional JSONL file to append the health record to.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Omit per-row findings from printed output.",
    )
    parser.add_argument(
        "--allow-findings",
        action="store_true",
        help="Return success even when findings are present.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    rows = fetch_spot_fill_ledger_rows(
        db_client=_build_db_client(),
        quote_currency=args.quote_currency,
        limit=args.limit,
    )
    order_reports = collect_backfill_order_reports(
        smoke_records=_load_jsonl_records(args.smoke_audit_file),
        sweep_records=_load_jsonl_records(args.sweep_state_file),
        smoke_audit_file=args.smoke_audit_file,
        sweep_state_file=args.sweep_state_file,
        source="all",
    )
    report = analyze_spot_fill_ledger_rows(
        rows=rows,
        quote_currency=args.quote_currency,
        order_reports=order_reports,
        include_findings=not args.summary_only,
    )
    if args.audit_file:
        _append_jsonl(args.audit_file, report)
    print(SUMMARY_PREFIX + json.dumps(report, sort_keys=True))
    if args.allow_findings:
        return 0
    return 0 if report["status"] == SpotFillLedgerHealthStatus.PASSED.value else 1


if __name__ == "__main__":
    raise SystemExit(main())
