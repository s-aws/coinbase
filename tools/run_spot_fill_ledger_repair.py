"""Plan or apply local repairs for suspicious spot fill-ledger rows.

The command never submits Coinbase orders. It may call Coinbase read APIs to
fetch fills for already-recorded exchange order ids, then it can apply narrow
local corrections only when ``--apply`` is supplied.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from business.spot_fill_backfill import fetch_rest_fills_for_order
from business.spot_fill_ledger_health import (
    DEFAULT_QUOTE_CURRENCY,
    analyze_spot_fill_ledger_rows,
    apply_spot_fill_ledger_repair_actions,
    build_spot_fill_ledger_repair_actions,
    fetch_spot_fill_ledger_rows,
)
from core.enums import (
    SpotAuditRecordType,
    SpotFillLedgerHealthStatus,
    SpotFillLedgerRepairStatus,
)
from tools.run_spot_fill_backfill_recovery import (
    DEFAULT_SMOKE_AUDIT_FILE,
    DEFAULT_SWEEP_STATE_FILE,
    _load_jsonl_records,
    collect_backfill_order_reports,
)


SUMMARY_PREFIX = "SPOT_FILL_LEDGER_REPAIR "
DEFAULT_REPAIR_FILE = Path("runtime_state") / "spot_fill_ledger_repairs.jsonl"


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


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


def _dedupe_repairable_orders(
    *,
    health_report: Mapping[str, Any],
    order_reports: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_client = {
        _text(order.get("client_order_id")): order
        for order in order_reports
        if _text(order.get("client_order_id"))
        and (_text(order.get("exchange_order_id")) or _text(order.get("order_id")))
    }
    seen: set[tuple[str, str]] = set()
    repairable_orders: list[dict[str, Any]] = []
    for finding in health_report.get("findings") or []:
        if not isinstance(finding, Mapping) or not finding.get("repairable"):
            continue
        row = finding.get("row") or {}
        client_order_id = _text(row.get("client_order_id"))
        order = by_client.get(client_order_id)
        if not order:
            continue
        exchange_order_id = _text(order.get("exchange_order_id")) or _text(
            order.get("order_id")
        )
        key = (client_order_id, exchange_order_id)
        if key in seen:
            continue
        seen.add(key)
        repairable_orders.append(order)
    return repairable_orders


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Plan or apply local fill-ledger repairs from Coinbase REST fill "
            "evidence. This command never places orders."
        )
    )
    parser.add_argument(
        "--quote-currency",
        default=DEFAULT_QUOTE_CURRENCY,
        help="Quote currency suffix to inspect.",
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
        help="Live smoke JSONL audit file.",
    )
    parser.add_argument(
        "--sweep-state-file",
        type=Path,
        default=DEFAULT_SWEEP_STATE_FILE,
        help="Spot sweep JSONL state file.",
    )
    parser.add_argument(
        "--repair-file",
        type=Path,
        default=DEFAULT_REPAIR_FILE,
        help="JSONL correction record file.",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Report local repair candidates without Coinbase read calls.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply exact local corrections after Coinbase read-only fill fetch.",
    )
    parser.add_argument(
        "--record-dry-run",
        action="store_true",
        help="Append dry-run repair evidence to the repair JSONL file.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Omit per-row health findings and repair actions from printed output.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.apply and args.plan_only:
        parser.error("--apply cannot be combined with --plan-only")

    db_client = _build_db_client()
    rows = fetch_spot_fill_ledger_rows(
        db_client=db_client,
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
    health_report = analyze_spot_fill_ledger_rows(
        rows=rows,
        quote_currency=args.quote_currency,
        order_reports=order_reports,
        include_findings=True,
    )
    repairable_orders = _dedupe_repairable_orders(
        health_report=health_report,
        order_reports=order_reports,
    )
    summary: dict[str, Any] = {
        "record_type": SpotAuditRecordType.FILL_LEDGER_REPAIR.value,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": not args.apply,
        "plan_only": args.plan_only,
        "quote_currency": args.quote_currency,
        "health_status": health_report["status"],
        "health_finding_count": health_report["finding_count"],
        "repairable_order_count": len(repairable_orders),
        "repair_file": str(args.repair_file),
        "live_coinbase_orders_ran": False,
        "live_order_notional_usdc": "0",
        "total_submitted_notional_usdc": "0",
        "total_executed_notional_usdc": "0",
        "read_only_coinbase_requests": [],
        "live_coinbase_requests": [],
    }
    if not args.summary_only:
        summary["health"] = health_report

    if args.plan_only or not repairable_orders:
        summary["repair"] = {
            "status": (
                SpotFillLedgerRepairStatus.SKIPPED.value
                if not repairable_orders
                else SpotFillLedgerRepairStatus.DRY_RUN.value
            ),
            "reason": (
                "no repairable suspicious rows were found"
                if not repairable_orders
                else "plan-only mode skips Coinbase read calls"
            ),
            "action_count": 0,
        }
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
        if args.plan_only:
            return 0
        return 0 if health_report["status"] != SpotFillLedgerHealthStatus.FAILED.value else 1

    if not os.environ.get("COINBASE_API_KEY") or not os.environ.get("COINBASE_API_SECRET"):
        parser.error("COINBASE_API_KEY and COINBASE_API_SECRET are required")

    import configuration

    rest_client = configuration.get_rest_client()
    rest_fills_by_order_id: dict[str, list[dict[str, Any]]] = {}
    for order in repairable_orders:
        exchange_order_id = _text(order.get("exchange_order_id")) or _text(
            order.get("order_id")
        )
        rest_fills_by_order_id[exchange_order_id] = fetch_rest_fills_for_order(
            rest_client,
            exchange_order_id=exchange_order_id,
            product_id=_text(order.get("product_id")) or None,
        )
    summary["read_only_coinbase_requests"] = ["list_fills"]

    actions = build_spot_fill_ledger_repair_actions(
        rows=rows,
        order_reports=order_reports,
        rest_fills_by_order_id=rest_fills_by_order_id,
        quote_currency=args.quote_currency,
    )
    repair = apply_spot_fill_ledger_repair_actions(
        db_client=db_client,
        actions=actions,
        apply=args.apply,
    )
    if args.summary_only:
        repair.pop("actions", None)
    summary["repair"] = repair

    if args.apply or args.record_dry_run:
        _append_jsonl(args.repair_file, summary)
    print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
    return 1 if repair["status"] == SpotFillLedgerRepairStatus.FAILED.value else 0


if __name__ == "__main__":
    raise SystemExit(main())
