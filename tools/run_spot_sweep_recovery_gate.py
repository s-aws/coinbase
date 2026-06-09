"""Recover and gate durable USDC spot portfolio sweep audit state.

The gate never places Coinbase orders. It can reconcile recorded sweep orders
against Coinbase read APIs and retry REST-fill backfill for submitted orders
whose durable run record does not have clean fill-backfill evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from business.spot_fill_backfill import backfill_fill_ledger_from_order_reports
from business.spot_portfolio_sweep import (
    append_sweep_run_record,
    build_sweep_recovery_record,
    load_sweep_run_records,
    reconcile_sweep_run_record,
)
from core.enums import (
    SpotFillBackfillStatus,
    SpotPortfolioSweepRunStatus,
    SpotSweepRecoveryGateStatus,
)
from tools.run_spot_fill_backfill_recovery import (
    DEFAULT_SWEEP_STATE_FILE,
    collect_backfill_order_reports,
    filter_backfillable_order_reports,
)


SUMMARY_PREFIX = "SPOT_SWEEP_RECOVERY_GATE "


def _fill_backfill_needs_retry(backfill: Mapping[str, Any] | None) -> bool:
    if not backfill:
        return True
    if backfill.get("skipped") or backfill.get("error"):
        return True
    for order in backfill.get("orders") or []:
        if (
            isinstance(order, Mapping)
            and order.get("status") == SpotFillBackfillStatus.ERROR.value
        ):
            return True
    return False


def _latest_reconciled_run_ids(records: Iterable[Mapping[str, Any]]) -> set[str]:
    run_ids: set[str] = set()
    for record in records:
        if record.get("record_type") != "sweep_reconciliation":
            continue
        run_id = str(record.get("run_id") or "").strip()
        if run_id:
            run_ids.add(run_id)
    return run_ids


def _filtered_sweep_runs(
    records: Iterable[Mapping[str, Any]],
    *,
    run_id: str | None = None,
    config_id: str | None = None,
) -> list[dict[str, Any]]:
    runs = []
    for record in records:
        if record.get("record_type") != "sweep_run":
            continue
        if run_id and record.get("run_id") != run_id:
            continue
        if config_id and record.get("config_id") != config_id:
            continue
        runs.append(dict(record))
    return runs


def build_sweep_recovery_gate_plan(
    *,
    records: Iterable[Mapping[str, Any]],
    state_file: Path = DEFAULT_SWEEP_STATE_FILE,
    run_id: str | None = None,
    config_id: str | None = None,
) -> dict[str, Any]:
    """Plan reconciliation/backfill recovery actions from durable sweep records."""
    records = [dict(record) for record in records]
    runs = _filtered_sweep_runs(records, run_id=run_id, config_id=config_id)
    reconciled_run_ids = _latest_reconciled_run_ids(records)
    runs_needing_reconciliation = [
        run
        for run in runs
        if str(run.get("run_id") or "").strip() not in reconciled_run_ids
    ]
    runs_needing_backfill = [
        run
        for run in runs
        if _fill_backfill_needs_retry((run.get("execution") or {}).get("fill_backfill"))
    ]
    candidate_orders = collect_backfill_order_reports(
        smoke_records=[],
        sweep_records=runs_needing_backfill,
        sweep_state_file=state_file,
        source="sweep",
        run_id=run_id,
        config_id=config_id,
    )
    backfillable_orders = filter_backfillable_order_reports(candidate_orders)
    return {
        "state_file": str(state_file),
        "run_id": run_id,
        "config_id": config_id,
        "sweep_run_count": len(runs),
        "runs_needing_reconciliation": [
            run.get("run_id") for run in runs_needing_reconciliation
        ],
        "runs_needing_backfill": [
            run.get("run_id") for run in runs_needing_backfill
        ],
        "planned_reconciliation_run_count": len(runs_needing_reconciliation),
        "candidate_backfill_order_count": len(candidate_orders),
        "planned_backfill_order_count": len(backfillable_orders),
        "backfill_orders": backfillable_orders,
    }


def _build_fill_ledger_repo() -> Any:
    from business.fill_ledger import FillLedgerRepository
    from database.database import PostgresDB

    return FillLedgerRepository(PostgresDB())


def _build_summary(
    *,
    plan: Mapping[str, Any],
    dry_run: bool,
    skip_reconcile: bool,
    skip_backfill: bool,
) -> dict[str, Any]:
    read_requests = []
    if not dry_run:
        if not skip_reconcile and plan["planned_reconciliation_run_count"]:
            read_requests.extend(["get_order", "list_fills"])
        if not skip_backfill and plan["planned_backfill_order_count"]:
            read_requests.append("list_fills")
    return {
        "dry_run": dry_run,
        "skip_reconcile": skip_reconcile,
        "skip_backfill": skip_backfill,
        "gate_status": SpotSweepRecoveryGateStatus.PASSED.value,
        "failures": [],
        "live_coinbase_orders_ran": False,
        "live_order_notional_usdc": "0",
        "total_submitted_notional_usdc": "0",
        "total_executed_notional_usdc": "0",
        "read_only_coinbase_requests": sorted(set(read_requests)),
        "live_coinbase_requests": [],
        "plan": dict(plan),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Reconcile and retry fill-ledger backfill for durable USDC spot "
            "sweep records. This command never submits Coinbase orders."
        )
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=DEFAULT_SWEEP_STATE_FILE,
        help="Durable spot portfolio sweep JSONL ledger.",
    )
    parser.add_argument("--run-id", default=None, help="Optional run_id filter.")
    parser.add_argument("--config-id", default=None, help="Optional config_id filter.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan recovery actions only; do not call Coinbase or write DB.",
    )
    parser.add_argument(
        "--skip-reconcile",
        action="store_true",
        help="Do not append sweep_reconciliation records.",
    )
    parser.add_argument(
        "--skip-backfill",
        action="store_true",
        help="Do not retry REST-fill backfill into fill_ledger.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Omit per-order backfill details from the printed plan.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    records = load_sweep_run_records(args.state_file)
    plan = build_sweep_recovery_gate_plan(
        records=records,
        state_file=args.state_file,
        run_id=args.run_id,
        config_id=args.config_id,
    )
    summary_plan = dict(plan)
    if args.summary_only:
        summary_plan.pop("backfill_orders", None)
    summary = _build_summary(
        plan=summary_plan,
        dry_run=args.dry_run,
        skip_reconcile=args.skip_reconcile,
        skip_backfill=args.skip_backfill,
    )

    needs_coinbase = (
        not args.dry_run
        and (
            (not args.skip_reconcile and plan["planned_reconciliation_run_count"])
            or (not args.skip_backfill and plan["planned_backfill_order_count"])
        )
    )
    if needs_coinbase and (
        not os.environ.get("COINBASE_API_KEY")
        or not os.environ.get("COINBASE_API_SECRET")
    ):
        parser.error("COINBASE_API_KEY and COINBASE_API_SECRET are required")

    if args.dry_run or not needs_coinbase:
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
        return 0

    import configuration

    rest_client = configuration.get_rest_client()
    fill_ledger_repo = None
    try:
        fill_ledger_repo = _build_fill_ledger_repo()
    except Exception as exc:
        summary["failures"].append(f"fill ledger repository unavailable: {exc}")

    if not args.skip_reconcile and plan["planned_reconciliation_run_count"]:
        reconciliations = []
        runs = _filtered_sweep_runs(
            records,
            run_id=args.run_id,
            config_id=args.config_id,
        )
        wanted_run_ids = set(plan["runs_needing_reconciliation"])
        for run in runs:
            if run.get("run_id") not in wanted_run_ids:
                continue
            reconciliation = reconcile_sweep_run_record(
                record=run,
                rest_client=rest_client,
                fill_ledger_repo=fill_ledger_repo,
            )
            append_sweep_run_record(args.state_file, reconciliation)
            reconciliations.append(reconciliation)
            if reconciliation.get("status") != (
                SpotPortfolioSweepRunStatus.COMPLETED.value
            ):
                summary["failures"].append(
                    f"reconciliation incomplete for {run.get('run_id')}"
                )
        summary["reconciliations"] = reconciliations

    if not args.skip_backfill and plan["planned_backfill_order_count"]:
        if fill_ledger_repo is None:
            summary["fill_backfill"] = {
                "error": "fill ledger repository is unavailable",
                "orders": [],
            }
        else:
            backfill = backfill_fill_ledger_from_order_reports(
                fill_ledger_repo=fill_ledger_repo,
                rest_client=rest_client,
                order_reports=plan["backfill_orders"],
            )
            summary["fill_backfill"] = backfill
            for order in backfill.get("orders") or []:
                if order.get("status") == SpotFillBackfillStatus.ERROR.value:
                    summary["failures"].append(
                        f"fill backfill errored for {order.get('exchange_order_id')}"
                    )

    if summary["failures"]:
        summary["gate_status"] = SpotSweepRecoveryGateStatus.FAILED.value
    if (
        not args.dry_run
        and (
            plan["planned_reconciliation_run_count"]
            or plan["planned_backfill_order_count"]
            or summary["failures"]
        )
    ):
        recovery_record = build_sweep_recovery_record(
            plan=plan,
            status=summary["gate_status"],
            failures=summary["failures"],
            summary={
                "reconciliation_count": len(summary.get("reconciliations") or []),
                "fill_backfill_order_count": len(
                    (summary.get("fill_backfill") or {}).get("orders") or []
                ),
            },
            config_id=args.config_id,
            run_id=args.run_id,
        )
        append_sweep_run_record(args.state_file, recovery_record)
        summary["recovery_record"] = {
            "record_type": recovery_record["record_type"],
            "config_id": recovery_record.get("config_id"),
            "run_id": recovery_record.get("run_id"),
            "status": recovery_record["status"],
            "created_at": recovery_record["created_at"],
            "summary": recovery_record["summary"],
        }
    print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
    return 1 if summary["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
