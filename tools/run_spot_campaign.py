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
    apply_spot_campaign_sell_authority_profile,
    append_spot_campaign_snapshot_record,
    build_spot_campaign_all_usdc_readiness_gate,
    build_spot_campaign_config_template,
    build_spot_campaign_config_validation_report,
    build_spot_campaign_dry_run_matrix,
    build_spot_campaign_dry_run_diff,
    build_spot_campaign_intake_request,
    build_spot_campaign_ledger_cleanup_apply,
    build_spot_campaign_ledger_cleanup_plan,
    build_spot_campaign_no_order_recovery_drill,
    build_spot_campaign_operation_lock_status,
    build_spot_campaign_operator_status,
    build_spot_campaign_pnl_checkpoints,
    build_spot_campaign_pnl_delta_report,
    build_spot_campaign_release_gate,
    build_spot_campaign_retry_plan,
    build_spot_campaign_run_index,
    build_spot_campaign_scheduler_status,
    build_spot_campaign_sell_authority_drift_report,
    build_spot_campaign_sell_authority_allowlist,
    build_spot_campaign_sell_authority_operator_report,
    build_spot_campaign_snapshot_record,
    build_spot_campaign_strict_sell_canary_candidates,
    load_spot_campaign_snapshot_records,
    normalize_spot_campaign_config,
    spot_campaign_config_to_sweep_config,
)
from business.spot_portfolio_sweep import (
    load_sweep_run_records,
    summarize_sweep_order_statuses,
)
from business.spot_sweep_recovery_gate import build_sweep_recovery_gate_plan
from core.enums import (
    SpotCampaignGateStatus,
    SpotCampaignRunMode,
    SpotCampaignSellAuthorityProfile,
    SpotCampaignStatus,
    SpotCampaignTemplateProfile,
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


SUMMARY_PREFIX = "SPOT_CAMPAIGN "


def _load_config(path: Path | None) -> dict[str, Any]:
    if path is None:
        raise ValueError("--config-file is required for this mode")
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise ValueError("campaign config file must contain a JSON object")
    return dict(payload)


def _load_mapping_file(path: Path | None, *, field_name: str) -> dict[str, Any]:
    if path is None:
        raise ValueError(f"{field_name} is required for this mode")
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise ValueError(f"{field_name} must contain a JSON object")
    return dict(payload)


def _requires_coinbase_read(args: argparse.Namespace) -> bool:
    return bool(
        args.dry_run_matrix
        or args.release_gate
        or args.dry_run_diff
        or args.no_order_recovery_drill
        or args.all_usdc_readiness_gate
        or args.sell_authority_allowlist
    )


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


def _allowlist_summary_for_print(
    allowlist: Mapping[str, Any],
    *,
    summary_only: bool,
) -> dict[str, Any]:
    output = dict(allowlist)
    if summary_only:
        output.pop("allowlist_rows", None)
        output.pop("blocked_rows", None)
        output.pop("skipped_rows", None)
    return output


def _report_summary_for_print(
    report: Mapping[str, Any],
    *,
    summary_only: bool,
) -> dict[str, Any]:
    output = dict(report)
    if not summary_only:
        return output
    output.pop("run_index", None)
    for key in (
        "common_products",
        "strict_only_products",
        "average_cost_only_products",
    ):
        if isinstance(output.get(key), list):
            output[f"{key}_count"] = len(output[key])
            output.pop(key, None)
    for summary_key in ("strict_fill_ledger", "coinbase_average_cost"):
        summary = output.get(summary_key)
        if isinstance(summary, Mapping):
            summary = dict(summary)
            summary.pop("allow_products", None)
            output[summary_key] = summary
    return output


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
        "--baseline-config-file",
        type=Path,
        default=None,
        help="Baseline campaign config used by --dry-run-diff.",
    )
    parser.add_argument(
        "--template-profile",
        choices=[profile.value for profile in SpotCampaignTemplateProfile],
        default=None,
        help="Print a canonical campaign config template.",
    )
    parser.add_argument(
        "--write-template-file",
        type=Path,
        default=None,
        help="Optional output path for --template-profile.",
    )
    parser.add_argument(
        "--validate-config-report",
        action="store_true",
        help="Validate config shape and operator safety caps without Coinbase calls.",
    )
    parser.add_argument(
        "--dry-run-diff",
        action="store_true",
        help="Compare current and baseline dry-run matrices.",
    )
    parser.add_argument(
        "--run-index",
        action="store_true",
        help="Build a local campaign/sweep run index from durable ledgers.",
    )
    parser.add_argument(
        "--pnl-checkpoints",
        action="store_true",
        help="Build campaign P/L checkpoints from the durable campaign ledger.",
    )
    parser.add_argument(
        "--pnl-delta-report",
        action="store_true",
        help="Compare the latest durable campaign P/L checkpoints by scope.",
    )
    parser.add_argument(
        "--ledger-cleanup-plan",
        action="store_true",
        help="Plan local recording or intentional ignore handling for unrecorded sweep runs.",
    )
    parser.add_argument(
        "--apply-ledger-cleanup-plan",
        action="store_true",
        help="Build local-only campaign ledger cleanup records for approved sweep run ids.",
    )
    parser.add_argument(
        "--approved-cleanup-run-id",
        action="append",
        default=[],
        help="Approved sweep run_id for --apply-ledger-cleanup-plan. Repeat for multiple runs.",
    )
    parser.add_argument(
        "--execute-local-cleanup-apply",
        action="store_true",
        help="Append approved cleanup records locally. Without this flag the apply mode is dry-run only.",
    )
    parser.add_argument(
        "--sell-authority-drift-report",
        action="store_true",
        help="Compare two SELL authority allowlists for product-removal drift.",
    )
    parser.add_argument(
        "--baseline-allowlist-file",
        type=Path,
        default=None,
        help="Older SELL allowlist JSON used by --sell-authority-drift-report.",
    )
    parser.add_argument(
        "--current-allowlist-file",
        type=Path,
        default=None,
        help="Current SELL allowlist JSON used by --sell-authority-drift-report.",
    )
    parser.add_argument(
        "--authority-operator-report",
        action="store_true",
        help="Compare strict fill-ledger and Coinbase average-cost SELL authority reports.",
    )
    parser.add_argument(
        "--strict-allowlist-file",
        type=Path,
        default=None,
        help="Strict fill-ledger SELL allowlist JSON used by authority reports.",
    )
    parser.add_argument(
        "--average-cost-allowlist-file",
        type=Path,
        default=None,
        help="Coinbase average-cost SELL allowlist JSON used by authority reports.",
    )
    parser.add_argument(
        "--strict-sell-canary-candidates",
        action="store_true",
        help="Select strict SELL canary candidates while avoiding recent live SELL products.",
    )
    parser.add_argument(
        "--input-allowlist-file",
        type=Path,
        default=None,
        help="SELL allowlist JSON input for --strict-sell-canary-candidates.",
    )
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=3,
        help="Maximum candidate products for --strict-sell-canary-candidates.",
    )
    parser.add_argument(
        "--recent-run-limit",
        type=int,
        default=5,
        help="Recent live SELL sweep runs to exclude from candidate rotation.",
    )
    parser.add_argument(
        "--no-order-recovery-drill",
        action="store_true",
        help="Exercise retry classification with synthetic no-submission orders.",
    )
    parser.add_argument(
        "--all-usdc-readiness-gate",
        action="store_true",
        help="Validate that a broad all-USDC campaign is intentionally broad.",
    )
    parser.add_argument(
        "--scheduler-status",
        action="store_true",
        help="Report recurring campaign due state from the sweep ledger.",
    )
    parser.add_argument(
        "--sell-authority-allowlist",
        action="store_true",
        help="Build a read-only SELL authority allowlist from dry-run rows.",
    )
    parser.add_argument(
        "--sell-authority-profile",
        choices=[profile.value for profile in SpotCampaignSellAuthorityProfile],
        default=None,
        help="Apply a named SELL authority profile when writing a profiled config or allowlist.",
    )
    parser.add_argument(
        "--write-profiled-config-file",
        type=Path,
        default=None,
        help="Write config with --sell-authority-profile applied.",
    )
    parser.add_argument(
        "--write-allowlist-file",
        type=Path,
        default=None,
        help="Optional JSON output path for --sell-authority-allowlist.",
    )
    parser.add_argument(
        "--write-allowlist-config-file",
        type=Path,
        default=None,
        help="Optional campaign config output path from --sell-authority-allowlist.",
    )
    parser.add_argument(
        "--write-allowlist-sweep-config-file",
        type=Path,
        default=None,
        help="Optional sweep config output path from --sell-authority-allowlist.",
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
    parser.add_argument(
        "--include-pnl-products",
        action="store_true",
        help="Persist product-level P/L rows in campaign dry-run snapshots.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    mode_count = sum(
        1
        for enabled in (
            args.template_profile is not None,
            args.validate_config_report,
            args.dry_run_diff,
            args.run_index,
            args.pnl_checkpoints,
            args.pnl_delta_report,
            args.ledger_cleanup_plan,
            args.apply_ledger_cleanup_plan,
            args.sell_authority_drift_report,
            args.authority_operator_report,
            args.strict_sell_canary_candidates,
            args.no_order_recovery_drill,
            args.all_usdc_readiness_gate,
            args.scheduler_status,
            args.sell_authority_allowlist,
            args.write_profiled_config_file is not None,
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
            "choose exactly one campaign mode"
        )
    if args.write_template_file and args.template_profile is None:
        parser.error("--write-template-file is valid only with --template-profile")
    if args.baseline_config_file and not args.dry_run_diff:
        parser.error("--baseline-config-file is valid only with --dry-run-diff")
    if args.dry_run_diff and args.baseline_config_file is None:
        parser.error("--dry-run-diff requires --baseline-config-file")
    if (
        args.sell_authority_profile
        and args.write_profiled_config_file is None
        and not args.sell_authority_allowlist
    ):
        parser.error(
            "--sell-authority-profile requires --write-profiled-config-file or --sell-authority-allowlist"
        )
    if args.write_profiled_config_file and args.sell_authority_profile is None:
        parser.error("--write-profiled-config-file requires --sell-authority-profile")
    if args.record_snapshot and not (
        args.dry_run_matrix or args.release_gate or args.sell_authority_allowlist
    ):
        parser.error(
            "--record-snapshot is valid only with dry-run, release gate, or sell authority allowlist"
        )
    if args.write_retry_config_file and not args.retry_plan:
        parser.error("--write-retry-config-file is valid only with --retry-plan")
    if args.approved_cleanup_run_id and not args.apply_ledger_cleanup_plan:
        parser.error("--approved-cleanup-run-id is valid only with --apply-ledger-cleanup-plan")
    if args.execute_local_cleanup_apply and not args.apply_ledger_cleanup_plan:
        parser.error("--execute-local-cleanup-apply is valid only with --apply-ledger-cleanup-plan")
    if args.apply_ledger_cleanup_plan and not args.approved_cleanup_run_id:
        parser.error("--apply-ledger-cleanup-plan requires --approved-cleanup-run-id")
    if args.baseline_allowlist_file and not args.sell_authority_drift_report:
        parser.error("--baseline-allowlist-file is valid only with --sell-authority-drift-report")
    if args.current_allowlist_file and not args.sell_authority_drift_report:
        parser.error("--current-allowlist-file is valid only with --sell-authority-drift-report")
    if args.strict_allowlist_file and not args.authority_operator_report:
        parser.error("--strict-allowlist-file is valid only with --authority-operator-report")
    if args.average_cost_allowlist_file and not args.authority_operator_report:
        parser.error("--average-cost-allowlist-file is valid only with --authority-operator-report")
    if args.input_allowlist_file and not args.strict_sell_canary_candidates:
        parser.error("--input-allowlist-file is valid only with --strict-sell-canary-candidates")
    for writer_name in (
        "write_allowlist_file",
        "write_allowlist_config_file",
        "write_allowlist_sweep_config_file",
    ):
        if getattr(args, writer_name) is not None and not args.sell_authority_allowlist:
            parser.error(
                f"--{writer_name.replace('_', '-')} is valid only with --sell-authority-allowlist"
            )
    if _requires_coinbase_read(args) and (
        not os.environ.get("COINBASE_API_KEY")
        or not os.environ.get("COINBASE_API_SECRET")
    ):
        parser.error("COINBASE_API_KEY and COINBASE_API_SECRET are required")

    if args.template_profile is not None:
        template = build_spot_campaign_config_template(profile=args.template_profile)
        if args.write_template_file:
            args.write_template_file.parent.mkdir(parents=True, exist_ok=True)
            with args.write_template_file.open(
                "w",
                encoding="utf-8",
                newline="\n",
            ) as handle:
                json.dump(template, handle, indent=2, sort_keys=True)
                handle.write("\n")
        summary = _build_summary_base(config=template, state_file=args.state_file)
        summary["status"] = SpotCampaignStatus.RECORDED.value
        summary["mode"] = SpotCampaignRunMode.TEMPLATE.value
        summary["template_profile"] = args.template_profile
        summary["template_config"] = template
        if args.write_template_file:
            summary["template_file"] = str(args.write_template_file)
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
        return 0

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

    if args.run_index:
        run_index = build_spot_campaign_run_index(
            campaign_records=load_spot_campaign_snapshot_records(args.state_file),
            sweep_records=load_sweep_run_records(args.sweep_state_file),
        )
        summary = _build_summary_base(config=None, state_file=args.state_file)
        summary["status"] = SpotCampaignStatus.RECORDED.value
        summary["mode"] = SpotCampaignRunMode.RUN_INDEX.value
        summary["run_index"] = run_index
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
        return 0

    if args.ledger_cleanup_plan:
        cleanup_plan = build_spot_campaign_ledger_cleanup_plan(
            campaign_records=load_spot_campaign_snapshot_records(args.state_file),
            sweep_records=load_sweep_run_records(args.sweep_state_file),
        )
        summary = _build_summary_base(config=None, state_file=args.state_file)
        summary["status"] = cleanup_plan["status"]
        summary["mode"] = SpotCampaignRunMode.LEDGER_CLEANUP_PLAN.value
        summary["ledger_cleanup_plan"] = _report_summary_for_print(
            cleanup_plan,
            summary_only=args.summary_only,
        )
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
        return 0

    if args.apply_ledger_cleanup_plan:
        cleanup_apply = build_spot_campaign_ledger_cleanup_apply(
            campaign_records=load_spot_campaign_snapshot_records(args.state_file),
            sweep_records=load_sweep_run_records(args.sweep_state_file),
            approved_run_ids=args.approved_cleanup_run_id,
            dry_run=not args.execute_local_cleanup_apply,
            actor_id="cli",
        )
        appended_count = 0
        if (
            args.execute_local_cleanup_apply
            and cleanup_apply["status"] != SpotCampaignStatus.BLOCKED.value
        ):
            for record in cleanup_apply["records_to_append"]:
                append_spot_campaign_snapshot_record(args.state_file, record)
                appended_count += 1
        summary = _build_summary_base(config=None, state_file=args.state_file)
        summary["status"] = cleanup_apply["status"]
        summary["mode"] = SpotCampaignRunMode.LEDGER_CLEANUP_APPLY.value
        summary["ledger_cleanup_apply"] = _report_summary_for_print(
            {
                **cleanup_apply,
                "appended_record_count": appended_count,
            },
            summary_only=args.summary_only,
        )
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
        return 0 if cleanup_apply["status"] != SpotCampaignStatus.BLOCKED.value else 1

    if args.pnl_checkpoints:
        checkpoints = build_spot_campaign_pnl_checkpoints(
            records=load_spot_campaign_snapshot_records(args.state_file),
        )
        summary = _build_summary_base(config=None, state_file=args.state_file)
        summary["status"] = SpotCampaignStatus.RECORDED.value
        summary["mode"] = SpotCampaignRunMode.PNL_CHECKPOINT.value
        summary["pnl_checkpoints"] = checkpoints
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
        return 0

    if args.pnl_delta_report:
        pnl_delta = build_spot_campaign_pnl_delta_report(
            records=load_spot_campaign_snapshot_records(args.state_file),
        )
        summary = _build_summary_base(config=None, state_file=args.state_file)
        summary["status"] = pnl_delta["status"]
        summary["mode"] = SpotCampaignRunMode.PNL_DELTA_REPORT.value
        summary["pnl_delta_report"] = _report_summary_for_print(
            pnl_delta,
            summary_only=args.summary_only,
        )
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
        return 0

    if args.sell_authority_drift_report:
        try:
            previous_allowlist = _load_mapping_file(
                args.baseline_allowlist_file,
                field_name="--baseline-allowlist-file",
            )
            current_allowlist = _load_mapping_file(
                args.current_allowlist_file,
                field_name="--current-allowlist-file",
            )
        except ValueError as exc:
            parser.error(str(exc))
        drift_report = build_spot_campaign_sell_authority_drift_report(
            previous_allowlist=previous_allowlist,
            current_allowlist=current_allowlist,
        )
        summary = _build_summary_base(config=None, state_file=args.state_file)
        summary["status"] = drift_report["status"]
        summary["mode"] = SpotCampaignRunMode.SELL_AUTHORITY_DRIFT.value
        summary["sell_authority_drift_report"] = _report_summary_for_print(
            drift_report,
            summary_only=args.summary_only,
        )
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
        return 0 if drift_report["gate_status"] == SpotCampaignGateStatus.PASSED.value else 1

    if args.authority_operator_report:
        try:
            strict_allowlist = _load_mapping_file(
                args.strict_allowlist_file,
                field_name="--strict-allowlist-file",
            )
            average_cost_allowlist = _load_mapping_file(
                args.average_cost_allowlist_file,
                field_name="--average-cost-allowlist-file",
            )
        except ValueError as exc:
            parser.error(str(exc))
        authority_report = build_spot_campaign_sell_authority_operator_report(
            strict_allowlist=strict_allowlist,
            average_cost_allowlist=average_cost_allowlist,
        )
        summary = _build_summary_base(config=None, state_file=args.state_file)
        summary["status"] = authority_report["status"]
        summary["mode"] = SpotCampaignRunMode.SELL_AUTHORITY_OPERATOR_REPORT.value
        summary["authority_operator_report"] = _report_summary_for_print(
            authority_report,
            summary_only=args.summary_only,
        )
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
        return 0

    if args.strict_sell_canary_candidates:
        try:
            allowlist = _load_mapping_file(
                args.input_allowlist_file,
                field_name="--input-allowlist-file",
            )
        except ValueError as exc:
            parser.error(str(exc))
        candidates = build_spot_campaign_strict_sell_canary_candidates(
            allowlist=allowlist,
            sweep_records=load_sweep_run_records(args.sweep_state_file),
            max_candidates=args.max_candidates,
            recent_run_limit=args.recent_run_limit,
        )
        summary = _build_summary_base(config=None, state_file=args.state_file)
        summary["status"] = candidates["status"]
        summary["mode"] = SpotCampaignRunMode.STRICT_SELL_CANARY_CANDIDATES.value
        summary["strict_sell_canary_candidates"] = _report_summary_for_print(
            candidates,
            summary_only=args.summary_only,
        )
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
        return 0 if candidates["status"] == SpotCampaignStatus.READY.value else 1

    if args.validate_config_report:
        try:
            raw_config = _load_config(args.config_file)
        except ValueError as exc:
            parser.error(str(exc))
        report = build_spot_campaign_config_validation_report(config=raw_config)
        summary = _build_summary_base(
            config=report.get("config") or None,
            state_file=args.state_file,
        )
        summary["status"] = report["status"]
        summary["mode"] = SpotCampaignRunMode.VALIDATION.value
        summary["validation_report"] = report
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
        return 0 if report["phase_90_ready"] else 1

    try:
        raw_config = _load_config(args.config_file)
        if args.sell_authority_profile and args.sell_authority_allowlist:
            config = apply_spot_campaign_sell_authority_profile(
                config=raw_config,
                profile=args.sell_authority_profile,
            )
        else:
            config = normalize_spot_campaign_config(raw_config)
    except ValueError as exc:
        parser.error(str(exc))

    if args.write_profiled_config_file:
        profiled = apply_spot_campaign_sell_authority_profile(
            config=config,
            profile=args.sell_authority_profile,
        )
        args.write_profiled_config_file.parent.mkdir(parents=True, exist_ok=True)
        with args.write_profiled_config_file.open(
            "w",
            encoding="utf-8",
            newline="\n",
        ) as handle:
            json.dump(profiled, handle, indent=2, sort_keys=True)
            handle.write("\n")
        summary = _build_summary_base(config=profiled, state_file=args.state_file)
        summary["status"] = SpotCampaignStatus.RECORDED.value
        summary["mode"] = SpotCampaignRunMode.VALIDATION.value
        summary["profiled_config_file"] = str(args.write_profiled_config_file)
        summary["profiled_config"] = profiled
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
        return 0

    if args.scheduler_status:
        scheduler_status = build_spot_campaign_scheduler_status(
            config=config,
            sweep_records=load_sweep_run_records(args.sweep_state_file),
        )
        summary = _build_summary_base(config=config, state_file=args.state_file)
        summary["status"] = scheduler_status["status"]
        summary["mode"] = SpotCampaignRunMode.SCHEDULER_STATUS.value
        summary["scheduler_status"] = scheduler_status
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
        return 0 if scheduler_status["status"] == SpotCampaignStatus.READY.value else 1

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
        include_items=(
            not args.summary_only
            or args.dry_run_diff
            or args.no_order_recovery_drill
            or args.sell_authority_allowlist
        ),
        include_pnl_products=args.include_pnl_products,
    )
    read_requests = [
        "get_public_products",
        "get_accounts",
        *cost_basis.get("read_only_coinbase_requests", []),
    ]

    if args.sell_authority_allowlist:
        allowlist = build_spot_campaign_sell_authority_allowlist(
            config=config,
            dry_run_matrix=dry_run_matrix,
        )
        if args.write_allowlist_file:
            args.write_allowlist_file.parent.mkdir(parents=True, exist_ok=True)
            with args.write_allowlist_file.open(
                "w",
                encoding="utf-8",
                newline="\n",
            ) as handle:
                json.dump(allowlist, handle, indent=2, sort_keys=True)
                handle.write("\n")
        if args.write_allowlist_config_file and allowlist.get("allowlist_config"):
            args.write_allowlist_config_file.parent.mkdir(parents=True, exist_ok=True)
            with args.write_allowlist_config_file.open(
                "w",
                encoding="utf-8",
                newline="\n",
            ) as handle:
                json.dump(
                    allowlist["allowlist_config"],
                    handle,
                    indent=2,
                    sort_keys=True,
                )
                handle.write("\n")
        if (
            args.write_allowlist_sweep_config_file
            and allowlist.get("allowlist_sweep_config")
        ):
            args.write_allowlist_sweep_config_file.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            with args.write_allowlist_sweep_config_file.open(
                "w",
                encoding="utf-8",
                newline="\n",
            ) as handle:
                json.dump(
                    allowlist["allowlist_sweep_config"],
                    handle,
                    indent=2,
                    sort_keys=True,
                )
                handle.write("\n")
        snapshot_record = None
        if args.record_snapshot:
            record = build_spot_campaign_snapshot_record(
                config=config,
                mode=SpotCampaignRunMode.SELL_AUTHORITY_ALLOWLIST,
                status=allowlist["status"],
                dry_run_matrix=dry_run_matrix,
                sell_authority_allowlist=allowlist,
            )
            append_spot_campaign_snapshot_record(args.state_file, record)
            snapshot_record = {
                "record_type": record["record_type"],
                "generated_at": record["generated_at"],
                "campaign_id": record["campaign_id"],
                "status": record["status"],
                "mode": record["mode"],
                "state_file": str(args.state_file),
            }
        summary = _build_summary_base(config=config, state_file=args.state_file)
        summary["status"] = allowlist["status"]
        summary["mode"] = SpotCampaignRunMode.SELL_AUTHORITY_ALLOWLIST.value
        summary["read_only_coinbase_requests"] = sorted(set(read_requests))
        summary["sell_authority_allowlist"] = _allowlist_summary_for_print(
            allowlist,
            summary_only=args.summary_only,
        )
        if args.write_allowlist_file:
            summary["allowlist_file"] = str(args.write_allowlist_file)
        if args.write_allowlist_config_file:
            summary["allowlist_config_file"] = str(args.write_allowlist_config_file)
        if args.write_allowlist_sweep_config_file:
            summary["allowlist_sweep_config_file"] = str(
                args.write_allowlist_sweep_config_file
            )
        if snapshot_record:
            summary["campaign_snapshot_record"] = snapshot_record
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
        return 0 if allowlist["status"] == SpotCampaignStatus.READY.value else 1

    if args.dry_run_diff:
        try:
            baseline_config = normalize_spot_campaign_config(
                _load_config(args.baseline_config_file)
            )
        except ValueError as exc:
            parser.error(str(exc))
        baseline_matrix = build_spot_campaign_dry_run_matrix(
            config=baseline_config,
            products=products,
            wallets=wallets,
            fill_ledger_repo=fill_ledger_repo,
            inventory_baselines=inventory_baselines,
            coinbase_average_costs=cost_basis,
            sweep_records=sweep_records,
            include_items=True,
            include_pnl_products=args.include_pnl_products,
        )
        diff = build_spot_campaign_dry_run_diff(
            baseline_matrix=baseline_matrix,
            current_matrix=dry_run_matrix,
        )
        summary = _build_summary_base(config=config, state_file=args.state_file)
        summary["status"] = SpotCampaignStatus.RECORDED.value
        summary["mode"] = SpotCampaignRunMode.DRY_RUN_DIFF.value
        summary["read_only_coinbase_requests"] = sorted(set(read_requests))
        summary["dry_run_diff"] = diff
        if not args.summary_only:
            summary["baseline_dry_run_matrix"] = baseline_matrix
            summary["current_dry_run_matrix"] = dry_run_matrix
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
        return 0

    if args.no_order_recovery_drill:
        drill = build_spot_campaign_no_order_recovery_drill(
            config=config,
            dry_run_matrix=dry_run_matrix,
        )
        summary = _build_summary_base(config=config, state_file=args.state_file)
        summary["status"] = drill["status"]
        summary["mode"] = SpotCampaignRunMode.RECOVERY_DRILL.value
        summary["read_only_coinbase_requests"] = sorted(set(read_requests))
        summary["no_order_recovery_drill"] = drill
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
        return 0 if drill["passed"] else 1

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
    if args.all_usdc_readiness_gate:
        all_usdc_gate = build_spot_campaign_all_usdc_readiness_gate(
            config=config,
            dry_run_matrix=dry_run_matrix,
            release_gate=release_gate,
        )
        summary = _build_summary_base(config=config, state_file=args.state_file)
        summary["status"] = all_usdc_gate["status"]
        summary["mode"] = SpotCampaignRunMode.ALL_USDC_READINESS.value
        summary["read_only_coinbase_requests"] = sorted(set(read_requests))
        summary["dry_run_matrix"] = dry_run_matrix
        summary["release_gate"] = release_gate
        summary["all_usdc_readiness_gate"] = all_usdc_gate
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
        return 0 if all_usdc_gate["gate_status"] == SpotCampaignGateStatus.PASSED.value else 1

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
