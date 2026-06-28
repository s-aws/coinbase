"""Pure planning helpers for spot sweep recovery-gate evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from core.enums import SpotFillBackfillStatus
from tools.run_spot_fill_backfill_recovery import (
    collect_backfill_order_reports,
    filter_backfillable_order_reports,
)


DEFAULT_SWEEP_STATE_FILE = Path("runtime_state") / "spot_portfolio_sweeps.jsonl"


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


def filtered_sweep_runs(
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
    runs = filtered_sweep_runs(records, run_id=run_id, config_id=config_id)
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
