"""Run read-only gates for USDC spot campaign configs.

This tool does not submit Coinbase orders. Live campaign canaries are executed
by rendering a sweep config and passing it to run_spot_portfolio_sweep_live.py
with that tool's explicit --approved-live-orders gate.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from business.spot_campaign import (
    DEFAULT_CAMPAIGN_STATE_FILE,
    append_spot_campaign_snapshot_record,
    build_spot_campaign_dry_run_matrix,
    build_spot_campaign_intake_request,
    build_spot_campaign_operation_lock_status,
    build_spot_campaign_operator_status,
    build_spot_campaign_release_gate,
    build_spot_campaign_retry_plan,
    build_spot_campaign_snapshot_record,
    load_spot_campaign_snapshot_records,
    normalize_spot_campaign_config,
    spot_campaign_config_to_sweep_config,
)
from business.spot_portfolio_sweep import (
    load_sweep_run_records,
    summarize_sweep_order_statuses,
)
from core.enums import (
    SpotCampaignGateStatus,
    SpotCampaignRunMode,
    SpotCampaignStatus,
    SpotCostBasisSource,
    SpotPortfolioSweepRunStatus,
    SpotPortfolioSweepSafetyDecision,
)
from tools.run_spot_feature_intake_gate import build_spot_feature_intake_summary
from tools.run_spot_portfolio_sweep_live import (
    DEFAULT_COST_BASIS_STATE_FILE,
    DEFAULT_OPERATION_LOCK_FILE,
    DEFAULT_STATE_FILE as DEFAULT_SWEEP_STATE_FILE,
    _build_fill_ledger_repo,
    _load_coinbase_average_costs,
    _load_public_products,
    _load_wallets,
)
from tools.run_spot_sweep_recovery_gate import build_sweep_recovery_gate_plan


SUMMARY_PREFIX = "SPOT_CAMPAIGN "


def _load_config(path: Path | None) -> dict[str, Any]:
    if path is None:
        raise ValueError("--config-file is required for this mode")
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise ValueError("campaign config file must contain a JSON object")
    return dict(payload)


def _requires_coinbase_read(args: argparse.Namespace) -> bool:
    return bool(args.dry_run_matrix or args.release_gate)


def _build_summary_base(
    *,
    config: Mapping[str, Any] | None,
    state_file: Path,
) -> dict[str, Any]:
    normalized = normalize_spot_campaign_config(config) if config else {}
    return {
        "campaign_id": normalized.get("campaign_id"),
        "sweep_config_id": normalized.get("sweep_config_id"),
        "state_file": str(state_file),
        "config": normalized,
        "live_coinbase_orders_ran": False,
        "live_order_notional_usdc": "0",
        "total_submitted_notional_usdc": "0",
        "total_executed_notional_usdc": "0",
        "read_only_coinbase_requests": [],
        "live_coinbase_requests": [],
    }


def _include_coinbase_average_cost(
    *,
    config: Mapping[str, Any],
    args: argparse.Namespace,
) -> bool:
    normalized = normalize_spot_campaign_config(config)
    safety = normalized["safety_policy"]
    sources = set(normalized["cost_basis_authority"].get("allowed_sources") or [])
    return bool(
        args.include_coinbase_average_cost
        or safety.get("allow_coinbase_average_cost_basis")
        or SpotCostBasisSource.COINBASE_AVERAGE_COST.value in sources
    )


def _build_fill_repo_or_none() -> Any:
    try:
        return _build_fill_ledger_repo()
    except Exception:
        return None


def _record_snapshot_if_requested(
    *,
    args: argparse.Namespace,
    config: Mapping[str, Any],
    dry_run_matrix: Mapping[str, Any] | None,
    release_gate: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not args.record_snapshot:
        return None
    status = SpotCampaignStatus.READY.value
    if release_gate:
        status = (
            SpotCampaignStatus.READY.value
            if release_gate.get("gate_status") == SpotCampaignGateStatus.PASSED.value
            else SpotCampaignStatus.BLOCKED.value
        )
    elif dry_run_matrix:
        safety = dry_run_matrix.get("safety_evaluation") or {}
        status = (
            SpotCampaignStatus.READY.value
            if safety.get("decision") == SpotPortfolioSweepSafetyDecision.ALLOWED.value
            else SpotCampaignStatus.BLOCKED.value
        )
    record = build_spot_campaign_snapshot_record(
        config=config,
        mode=(
            SpotCampaignRunMode.RELEASE_GATE
            if release_gate
            else SpotCampaignRunMode.DRY_RUN
        ),
        status=status,
        dry_run_matrix=dry_run_matrix,
        release_gate=release_gate,
    )
    append_spot_campaign_snapshot_record(args.state_file, record)
    return {
        "record_type": record["record_type"],
        "generated_at": record["generated_at"],
        "campaign_id": record["campaign_id"],
        "status": record["status"],
        "mode": record["mode"],
        "state_file": str(args.state_file),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate and inspect USDC spot campaign configs. This command "
            "is read-only with respect to Coinbase orders."
        )
    )
    parser.add_argument(
        "--config-file",
        type=Path,
        default=None,
        help="Versioned JSON spot campaign config file.",
    )
    parser.add_argument(
        "--intake",
        action="store_true",
        help="Build and validate the formal spot feature-intake artifact.",
    )
    parser.add_argument(
        "--dry-run-matrix",
        action="store_true",
        help="Build a read-only campaign plan/safety/P&L matrix.",
    )
    parser.add_argument(
        "--release-gate",
        action="store_true",
        help="Run the read-only campaign release gate.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Read the durable local campaign ledger and exit.",
    )
    parser.add_argument(
        "--write-sweep-config-file",
        type=Path,
        default=None,
        help="Write the equivalent sweep config file and exit.",
    )
    parser.add_argument(
        "--record-latest-sweep-run",
        action="store_true",
        help="Append a campaign snapshot from the latest matching sweep run.",
    )
    parser.add_argument(
        "--retry-plan",
        action="store_true",
        help="Build a targeted retry config for not-submitted products from a partial run.",
    )
    parser.add_argument(
        "--retry-run-id",
        default=None,
        help="Optional source sweep run_id for --retry-plan. Defaults to latest matching run.",
    )
    parser.add_argument(
        "--write-retry-config-file",
        type=Path,
        default=None,
        help="Optional path for the campaign retry config generated by --retry-plan.",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=DEFAULT_CAMPAIGN_STATE_FILE,
        help="Durable local campaign JSONL ledger.",
    )
    parser.add_argument(
        "--sweep-state-file",
        type=Path,
        default=DEFAULT_SWEEP_STATE_FILE,
        help="Durable spot sweep JSONL ledger used for due/recovery checks.",
    )
    parser.add_argument(
        "--cost-basis-state-file",
        type=Path,
        default=DEFAULT_COST_BASIS_STATE_FILE,
        help="Durable cost-basis snapshot ledger path.",
    )
    parser.add_argument(
        "--operation-lock-file",
        type=Path,
        default=DEFAULT_OPERATION_LOCK_FILE,
        help="Shared sweep operation lock path.",
    )
    parser.add_argument(
        "--lock-stale-after-seconds",
        default="3600",
        help="Age threshold used when reporting whether the lock is stale.",
    )
    parser.add_argument(
        "--include-coinbase-average-cost",
        action="store_true",
        help="Read Coinbase portfolio average cost for P/L and coverage.",
    )
    parser.add_argument(
        "--coinbase-average-cost-portfolio-uuid",
        default=None,
        help="Optional Coinbase portfolio UUID for average cost-basis reads.",
    )
    parser.add_argument(
        "--record-snapshot",
        action="store_true",
        help="Append a durable campaign snapshot after dry-run or release gate.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Omit per-product rows from printed read-only reports.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    mode_count = sum(
        1
        for enabled in (
            args.intake,
            args.dry_run_matrix,
            args.release_gate,
            args.status,
            args.write_sweep_config_file is not None,
            args.record_latest_sweep_run,
            args.retry_plan,
        )
        if enabled
    )
    if mode_count != 1:
        parser.error(
            "choose exactly one of --intake, --dry-run-matrix, --release-gate, "
            "--status, --write-sweep-config-file, --record-latest-sweep-run, "
            "or --retry-plan"
        )
    if args.record_snapshot and not (args.dry_run_matrix or args.release_gate):
        parser.error("--record-snapshot is valid only with dry-run or release gate")
    if args.write_retry_config_file and not args.retry_plan:
        parser.error("--write-retry-config-file is valid only with --retry-plan")
    if _requires_coinbase_read(args) and (
        not os.environ.get("COINBASE_API_KEY")
        or not os.environ.get("COINBASE_API_SECRET")
    ):
        parser.error("COINBASE_API_KEY and COINBASE_API_SECRET are required")

    if args.status:
        operator_status = build_spot_campaign_operator_status(
            records=load_spot_campaign_snapshot_records(args.state_file),
        )
        summary = _build_summary_base(config=None, state_file=args.state_file)
        summary["status"] = SpotCampaignStatus.RECORDED.value
        summary["mode"] = SpotCampaignRunMode.STATUS.value
        summary["operator_status"] = operator_status
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
        return 0

    try:
        raw_config = _load_config(args.config_file)
        config = normalize_spot_campaign_config(raw_config)
    except ValueError as exc:
        parser.error(str(exc))

    if args.write_sweep_config_file:
        sweep_config = spot_campaign_config_to_sweep_config(config)
        args.write_sweep_config_file.parent.mkdir(parents=True, exist_ok=True)
        with args.write_sweep_config_file.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(sweep_config, handle, indent=2, sort_keys=True)
            handle.write("\n")
        summary = _build_summary_base(config=config, state_file=args.state_file)
        summary["status"] = SpotCampaignStatus.RECORDED.value
        summary["mode"] = SpotCampaignRunMode.DRY_RUN.value
        summary["sweep_config_file"] = str(args.write_sweep_config_file)
        summary["sweep_config"] = sweep_config
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
        return 0

    if args.record_latest_sweep_run:
        records = [
            record
            for record in load_sweep_run_records(args.sweep_state_file)
            if record.get("record_type") == "sweep_run"
            and record.get("config_id") == config["sweep_config_id"]
        ]
        records.sort(key=lambda record: record.get("started_at") or "")
        if not records:
            parser.error("no matching sweep_run records found for this campaign")
        latest = records[-1]
        execution = latest.get("execution") or {}
        execution_orders = list(execution.get("orders") or [])
        effective_outcome = (
            summarize_sweep_order_statuses(execution_orders)
            if execution_orders
            else {}
        )
        effective_status = (
            effective_outcome.get("run_status") or latest.get("status")
        )
        effective_submitted_count = (
            effective_outcome.get("submitted_order_count")
            if effective_outcome
            else execution.get("submitted_order_count", 0)
        )
        effective_blocked_or_error_count = (
            effective_outcome.get("blocked_or_error_count")
            if effective_outcome
            else execution.get("blocked_or_error_count", 0)
        )
        sweep_summary = {
            "run_id": latest.get("run_id"),
            "status": effective_status,
            "recorded_status": latest.get("status"),
            "started_at": latest.get("started_at"),
            "completed_at": latest.get("completed_at"),
            "live_coinbase_orders_ran": bool(
                execution.get("live_coinbase_orders_ran", False)
            ),
            "submitted_order_count": effective_submitted_count,
            "blocked_or_error_count": effective_blocked_or_error_count,
            "skipped_order_count": (
                effective_outcome.get("skipped_order_count", 0)
                if effective_outcome
                else execution.get("skipped_order_count", 0)
            ),
            "total_submitted_notional_usdc": (
                execution.get("total_submitted_notional_usdc") or "0"
            ),
            "total_executed_notional_usdc": (
                execution.get("total_executed_notional_usdc") or "0"
            ),
            "orders": execution.get("orders") or [],
            "fill_backfill": execution.get("fill_backfill") or {},
        }
        status = (
            SpotCampaignStatus.READY.value
            if (
                sweep_summary["live_coinbase_orders_ran"]
                and effective_status == SpotPortfolioSweepRunStatus.COMPLETED.value
            )
            else SpotCampaignStatus.BLOCKED.value
        )
        record = build_spot_campaign_snapshot_record(
            config=config,
            mode=SpotCampaignRunMode.LIVE_CANARY,
            status=status,
            sweep_summary=sweep_summary,
        )
        append_spot_campaign_snapshot_record(args.state_file, record)
        summary = _build_summary_base(config=config, state_file=args.state_file)
        summary["status"] = status
        summary["mode"] = SpotCampaignRunMode.LIVE_CANARY.value
        summary["campaign_snapshot_record"] = {
            "record_type": record["record_type"],
            "generated_at": record["generated_at"],
            "campaign_id": record["campaign_id"],
            "status": record["status"],
            "mode": record["mode"],
            "state_file": str(args.state_file),
        }
        summary["sweep_summary"] = sweep_summary
        summary["live_coinbase_orders_ran"] = sweep_summary[
            "live_coinbase_orders_ran"
        ]
        summary["live_order_notional_usdc"] = sweep_summary[
            "total_submitted_notional_usdc"
        ]
        summary["total_submitted_notional_usdc"] = sweep_summary[
            "total_submitted_notional_usdc"
        ]
        summary["total_executed_notional_usdc"] = sweep_summary[
            "total_executed_notional_usdc"
        ]
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
        return 0

    if args.retry_plan:
        retry_plan = build_spot_campaign_retry_plan(
            config=config,
            sweep_records=load_sweep_run_records(args.sweep_state_file),
            run_id=args.retry_run_id,
        )
        if args.write_retry_config_file and retry_plan.get("retry_config"):
            args.write_retry_config_file.parent.mkdir(parents=True, exist_ok=True)
            with args.write_retry_config_file.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(retry_plan["retry_config"], handle, indent=2, sort_keys=True)
                handle.write("\n")
        summary = _build_summary_base(config=config, state_file=args.state_file)
        summary["status"] = retry_plan["retry_status"]
        summary["mode"] = SpotCampaignRunMode.RETRY_PLAN.value
        summary["retry_plan"] = retry_plan
        if args.write_retry_config_file and retry_plan.get("retry_config"):
            summary["retry_config_file"] = str(args.write_retry_config_file)
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
        return 0 if retry_plan["retry_status"] == SpotCampaignStatus.READY.value else 1

    intake_request = build_spot_campaign_intake_request(config)
    intake_summary = build_spot_feature_intake_summary(request=intake_request)
    if args.intake:
        summary = _build_summary_base(config=config, state_file=args.state_file)
        summary["status"] = (
            SpotCampaignStatus.READY.value
            if intake_summary.get("phase_50_ready")
            else SpotCampaignStatus.INCOMPLETE.value
        )
        summary["mode"] = SpotCampaignRunMode.DRY_RUN.value
        summary["intake_request"] = intake_request
        summary["intake_summary"] = intake_summary
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
        return 0 if intake_summary.get("phase_50_ready") else 1

    import configuration

    rest_client = configuration.get_rest_client()
    products = _load_public_products()
    wallets = _load_wallets(rest_client)
    fill_ledger_repo = _build_fill_repo_or_none()
    inventory_baselines = getattr(configuration, "SPOT_INVENTORY_BASELINES", [])
    include_average_cost = _include_coinbase_average_cost(config=config, args=args)
    cost_basis = (
        _load_coinbase_average_costs(
            rest_client=rest_client,
            products=products,
            portfolio_uuid=args.coinbase_average_cost_portfolio_uuid,
        )
        if include_average_cost
        else {}
    )
    sweep_records = load_sweep_run_records(args.sweep_state_file)
    dry_run_matrix = build_spot_campaign_dry_run_matrix(
        config=config,
        products=products,
        wallets=wallets,
        fill_ledger_repo=fill_ledger_repo,
        inventory_baselines=inventory_baselines,
        coinbase_average_costs=cost_basis,
        sweep_records=sweep_records,
        include_items=not args.summary_only,
    )
    read_requests = [
        "get_public_products",
        "get_accounts",
        *cost_basis.get("read_only_coinbase_requests", []),
    ]

    if args.dry_run_matrix:
        record = _record_snapshot_if_requested(
            args=args,
            config=config,
            dry_run_matrix=dry_run_matrix,
            release_gate=None,
        )
        summary = _build_summary_base(config=config, state_file=args.state_file)
        summary["status"] = (
            SpotCampaignStatus.READY.value
            if dry_run_matrix["safety_evaluation"]["decision"]
            == SpotPortfolioSweepSafetyDecision.ALLOWED.value
            else SpotCampaignStatus.BLOCKED.value
        )
        summary["mode"] = SpotCampaignRunMode.DRY_RUN.value
        summary["read_only_coinbase_requests"] = sorted(set(read_requests))
        summary["dry_run_matrix"] = dry_run_matrix
        if record:
            summary["campaign_snapshot_record"] = record
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
        return 0

    operation_lock_status = build_spot_campaign_operation_lock_status(
        lock_file=args.operation_lock_file,
        stale_after_seconds=args.lock_stale_after_seconds,
    )
    recovery_plan = build_sweep_recovery_gate_plan(
        records=sweep_records,
        state_file=args.sweep_state_file,
        config_id=config["sweep_config_id"],
    )
    if args.summary_only:
        recovery_plan.pop("backfill_orders", None)
    release_gate = build_spot_campaign_release_gate(
        config=config,
        dry_run_matrix=dry_run_matrix,
        intake_summary=intake_summary,
        operation_lock_status=operation_lock_status,
        recovery_plan=recovery_plan,
    )
    record = _record_snapshot_if_requested(
        args=args,
        config=config,
        dry_run_matrix=dry_run_matrix,
        release_gate=release_gate,
    )
    summary = _build_summary_base(config=config, state_file=args.state_file)
    summary["status"] = release_gate["status"]
    summary["mode"] = SpotCampaignRunMode.RELEASE_GATE.value
    summary["read_only_coinbase_requests"] = sorted(set(read_requests))
    summary["intake_summary"] = intake_summary
    summary["dry_run_matrix"] = dry_run_matrix
    summary["release_gate"] = release_gate
    if record:
        summary["campaign_snapshot_record"] = record
    print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
    return 0 if release_gate["gate_status"] == SpotCampaignGateStatus.PASSED.value else 1


if __name__ == "__main__":
    raise SystemExit(main())
