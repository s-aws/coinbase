"""Recover REST fill-ledger backfill for prior live spot smoke/sweep runs.

This command never places Coinbase orders. It reads durable JSONL audit records,
extracts submitted order reports, and optionally re-runs the existing REST-fill
backfill path for orders that have both a client_order_id and exchange order_id.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from business.spot_fill_backfill import backfill_fill_ledger_from_order_reports
from core.enums import SpotFillBackfillStatus


SUMMARY_PREFIX = "SPOT_FILL_BACKFILL_RECOVERY "
DEFAULT_SMOKE_AUDIT_FILE = Path("runtime_state") / "live_spot_usdc_smoke.jsonl"
DEFAULT_SWEEP_STATE_FILE = Path("runtime_state") / "spot_portfolio_sweeps.jsonl"


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _load_jsonl_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, Mapping):
                records.append(dict(payload))
    return records


def _normalize_order_report(
    order: Mapping[str, Any],
    *,
    source: str,
    source_file: Path,
    run_id: str | None = None,
    config_id: str | None = None,
) -> dict[str, Any]:
    return {
        "source": source,
        "source_file": str(source_file),
        "run_id": run_id,
        "config_id": config_id,
        "product_id": _text(order.get("product_id")),
        "side": _text(order.get("side")).upper(),
        "client_order_id": _text(order.get("client_order_id")) or None,
        "exchange_order_id": (
            _text(order.get("exchange_order_id"))
            or _text(order.get("order_id"))
            or None
        ),
        "source_status": _text(order.get("status")),
        "submitted_notional_usdc": _text(order.get("submitted_notional_usdc")),
        "executed_notional_usdc": _text(order.get("executed_notional_usdc")),
    }


def _is_backfillable(order: Mapping[str, Any]) -> bool:
    return bool(order.get("client_order_id") and order.get("exchange_order_id"))


def filter_backfillable_order_reports(
    orders: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return order reports that have both internal and exchange order ids."""
    return [dict(order) for order in orders if _is_backfillable(order)]


def _dedupe_orders(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for order in orders:
        key = (
            _text(order.get("client_order_id")),
            _text(order.get("exchange_order_id")),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(order)
    return deduped


def collect_backfill_order_reports(
    *,
    smoke_records: Iterable[Mapping[str, Any]],
    sweep_records: Iterable[Mapping[str, Any]],
    smoke_audit_file: Path = DEFAULT_SMOKE_AUDIT_FILE,
    sweep_state_file: Path = DEFAULT_SWEEP_STATE_FILE,
    source: str = "all",
    run_id: str | None = None,
    config_id: str | None = None,
) -> list[dict[str, Any]]:
    """Extract candidate order reports from durable smoke/sweep JSONL records."""
    collected: list[dict[str, Any]] = []
    if source in {"all", "smoke"}:
        for record in smoke_records:
            if record.get("record_type") != "live_spot_usdc_smoke":
                continue
            record_run_id = _text(record.get("run_id")) or None
            if run_id and record_run_id != run_id:
                continue
            for order in record.get("orders") or []:
                if isinstance(order, Mapping):
                    collected.append(
                        _normalize_order_report(
                            order,
                            source="smoke",
                            source_file=smoke_audit_file,
                            run_id=record_run_id,
                        )
                    )
    if source in {"all", "sweep"}:
        for record in sweep_records:
            if record.get("record_type") != "sweep_run":
                continue
            record_run_id = _text(record.get("run_id")) or None
            record_config_id = _text(record.get("config_id")) or None
            if run_id and record_run_id != run_id:
                continue
            if config_id and record_config_id != config_id:
                continue
            execution = record.get("execution") or {}
            for order in execution.get("orders") or []:
                if isinstance(order, Mapping):
                    collected.append(
                        _normalize_order_report(
                            order,
                            source="sweep",
                            source_file=sweep_state_file,
                            run_id=record_run_id,
                            config_id=record_config_id,
                        )
                    )
    return _dedupe_orders(collected)


def build_recovery_summary(
    *,
    orders: Iterable[Mapping[str, Any]],
    dry_run: bool,
    source: str,
    smoke_audit_file: Path,
    sweep_state_file: Path,
    run_id: str | None = None,
    config_id: str | None = None,
) -> dict[str, Any]:
    orders = [dict(order) for order in orders]
    eligible = filter_backfillable_order_reports(orders)
    status_counts = Counter(_text(order.get("source_status")) for order in orders)
    source_counts = Counter(_text(order.get("source")) for order in orders)
    return {
        "dry_run": dry_run,
        "source": source,
        "run_id": run_id,
        "config_id": config_id,
        "smoke_audit_file": str(smoke_audit_file),
        "sweep_state_file": str(sweep_state_file),
        "candidate_order_count": len(orders),
        "eligible_order_count": len(eligible),
        "skipped_candidate_count": len(orders) - len(eligible),
        "source_counts": dict(sorted(source_counts.items())),
        "source_status_counts": dict(sorted(status_counts.items())),
        "live_coinbase_orders_ran": False,
        "live_order_notional_usdc": "0",
        "total_submitted_notional_usdc": "0",
        "total_executed_notional_usdc": "0",
        "read_only_coinbase_requests": [] if dry_run else ["list_fills"],
        "live_coinbase_requests": [],
    }


def _build_fill_ledger_repo() -> Any:
    from business.fill_ledger import FillLedgerRepository
    from database.database import PostgresDB

    return FillLedgerRepository(PostgresDB())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Retry REST-fill backfill for prior live spot smoke/sweep order "
            "records. This command never submits Coinbase orders."
        )
    )
    parser.add_argument(
        "--source",
        choices=["all", "smoke", "sweep"],
        default="all",
        help="Durable audit source to scan.",
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
        help="Spot portfolio sweep JSONL state file.",
    )
    parser.add_argument("--run-id", default=None, help="Optional run_id filter.")
    parser.add_argument("--config-id", default=None, help="Optional sweep config filter.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report candidate orders; do not fetch Coinbase fills or write DB.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Omit candidate order details from the printed summary.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    orders = collect_backfill_order_reports(
        smoke_records=_load_jsonl_records(args.smoke_audit_file),
        sweep_records=_load_jsonl_records(args.sweep_state_file),
        smoke_audit_file=args.smoke_audit_file,
        sweep_state_file=args.sweep_state_file,
        source=args.source,
        run_id=args.run_id,
        config_id=args.config_id,
    )
    eligible_orders = filter_backfillable_order_reports(orders)
    summary = build_recovery_summary(
        orders=orders,
        dry_run=args.dry_run,
        source=args.source,
        smoke_audit_file=args.smoke_audit_file,
        sweep_state_file=args.sweep_state_file,
        run_id=args.run_id,
        config_id=args.config_id,
    )
    if not args.summary_only:
        summary["orders"] = orders

    if args.dry_run:
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
        return 0

    if not os.environ.get("COINBASE_API_KEY") or not os.environ.get("COINBASE_API_SECRET"):
        parser.error("COINBASE_API_KEY and COINBASE_API_SECRET are required")

    import configuration

    backfill = backfill_fill_ledger_from_order_reports(
        fill_ledger_repo=_build_fill_ledger_repo(),
        rest_client=configuration.get_rest_client(),
        order_reports=eligible_orders,
    )
    summary["fill_backfill"] = backfill
    print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
    errored = [
        order
        for order in backfill.get("orders") or []
        if order.get("status") == SpotFillBackfillStatus.ERROR.value
    ]
    return 1 if errored else 0


if __name__ == "__main__":
    raise SystemExit(main())
