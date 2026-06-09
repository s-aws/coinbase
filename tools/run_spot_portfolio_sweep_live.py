"""Run an explicitly approved live USDC spot portfolio sweep.

This tool can place real Coinbase Advanced Trade sweep orders. It builds the
same USDC-only sweep plan as the dry-run tool, rechecks the shared
action-condition guard for each order, records a durable JSONL run record, and
exits. Recurring automation is "run if due" per invocation; use Windows Task
Scheduler or another supervisor to invoke it periodically.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from coinbase.rest import RESTClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from business.spot_portfolio_sweep import (
    append_sweep_run_record,
    build_sweep_config_id,
    build_sweep_disabled_record,
    build_sweep_operator_status,
    build_sweep_plan_explain,
    build_sweep_product_metadata,
    build_sweep_run_record,
    build_spot_portfolio_pnl_report,
    build_spot_inventory_coverage_report,
    build_sweep_config_registry,
    build_usdc_portfolio_sweep_plan,
    evaluate_sweep_automation_due,
    evaluate_sweep_safety_policy,
    execute_usdc_portfolio_sweep_plan,
    load_sweep_run_records,
    reconcile_sweep_run_record,
    summarize_sweep_execution,
)
from core.enums import (
    OrderSide,
    SpotPortfolioSweepAutomationDecision,
    SpotPortfolioSweepOrderType,
    SpotPortfolioSweepRunStatus,
    SpotPortfolioSweepSafetyDecision,
)
from external.coinbase_client import (
    coinbase_sdk_response_to_dict,
    list_all_account_dicts,
)


SUMMARY_PREFIX = "SPOT_PORTFOLIO_SWEEP_LIVE "
DEFAULT_STATE_FILE = Path("runtime_state") / "spot_portfolio_sweeps.jsonl"


def _load_public_products() -> list[dict[str, Any]]:
    client = RESTClient(rate_limit_headers=True)
    response = coinbase_sdk_response_to_dict(
        client.get_public_products(
            product_type="SPOT",
            get_all_products=True,
            get_tradability_status=True,
        )
    )
    return list(response.get("products") or [])


def _wallets_from_sdk_client(sdk_client: Any) -> dict[str, dict[str, Any]]:
    wallets: dict[str, dict[str, Any]] = {}
    for account in list_all_account_dicts(sdk_client):
        if account.get("deleted_at") is not None:
            continue
        currency = str(account.get("currency") or "").upper()
        if not currency:
            continue
        wallets[currency] = account
    return wallets


def _load_wallets(rest_client: Any) -> dict[str, dict[str, Any]]:
    sdk_getter = getattr(rest_client, "get_sdk_client", None)
    if callable(sdk_getter):
        return _wallets_from_sdk_client(sdk_getter())
    return _wallets_from_sdk_client(rest_client)


def _config_payload(args: argparse.Namespace) -> dict[str, Any]:
    safety_policy = _safety_policy_payload(args)
    return {
        "side": args.side,
        "quote_notional": (
            str(args.quote_notional) if args.quote_notional is not None else None
        ),
        "max_products": args.max_products,
        "quote_currency": "USDC",
        "order_type": args.order_type,
        "limit_price_offset_bps": str(args.limit_price_offset_bps),
        "repeat_every_hours": (
            str(args.repeat_every_hours)
            if args.repeat_every_hours is not None
            else None
        ),
        "max_runs": args.max_runs,
        "safety_policy": safety_policy,
    }


def _safety_policy_payload(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "enabled": not args.disable_safety_policy,
        "require_wallet_check": True,
        "require_known_profitable_inventory": (
            args.require_known_profitable_inventory
        ),
        "max_total_notional_per_run": (
            str(args.max_total_notional_per_run)
            if args.max_total_notional_per_run is not None
            else None
        ),
        "max_notional_per_order": (
            str(args.max_notional_per_order)
            if args.max_notional_per_order is not None
            else None
        ),
        "max_planned_orders": args.max_planned_orders,
        "max_skipped_orders": args.max_skipped_orders,
        "allow_products": args.allow_product or [],
        "deny_products": args.deny_product or [],
    }


def _optional_decimal(value: Any, *, field_name: str) -> Decimal | None:
    if value is None:
        return None
    try:
        converted = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{field_name} must be a decimal value") from exc
    return converted


def _optional_int(value: Any, *, field_name: str) -> int | None:
    if value is None:
        return None
    try:
        converted = int(value)
    except Exception as exc:
        raise ValueError(f"{field_name} must be an integer value") from exc
    return converted


def _load_sweep_config_file(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise ValueError("sweep config file must contain a JSON object")
    version = payload.get("version", 1)
    if version != 1:
        raise ValueError("sweep config version must be 1")
    return dict(payload)


def _apply_config_file(args: argparse.Namespace, config: Mapping[str, Any]) -> None:
    if not config:
        return
    if args.side is None:
        args.side = config.get("side")
    if args.quote_notional is None:
        args.quote_notional = _optional_decimal(
            config.get("quote_notional"),
            field_name="quote_notional",
        )
    if args.max_products is None:
        args.max_products = _optional_int(
            config.get("max_products"),
            field_name="max_products",
        )
    if args.order_type is None:
        args.order_type = config.get("order_type")
    if args.limit_price_offset_bps is None:
        args.limit_price_offset_bps = _optional_decimal(
            config.get("limit_price_offset_bps"),
            field_name="limit_price_offset_bps",
        )
    if args.repeat_every_hours is None:
        args.repeat_every_hours = _optional_decimal(
            config.get("repeat_every_hours"),
            field_name="repeat_every_hours",
        )
    if args.max_runs is None:
        args.max_runs = _optional_int(config.get("max_runs"), field_name="max_runs")
    if args.config_id is None:
        config_id = config.get("config_id")
        args.config_id = str(config_id) if config_id else None

    safety = config.get("safety_policy") or {}
    if not isinstance(safety, Mapping):
        raise ValueError("safety_policy must be an object when supplied")
    if safety.get("enabled") is False:
        args.disable_safety_policy = True
    for name in ("max_total_notional_per_run", "max_notional_per_order"):
        if getattr(args, name) is None:
            setattr(
                args,
                name,
                _optional_decimal(safety.get(name), field_name=f"safety_policy.{name}"),
            )
    for name in ("max_planned_orders", "max_skipped_orders"):
        if getattr(args, name) is None:
            setattr(
                args,
                name,
                _optional_int(safety.get(name), field_name=f"safety_policy.{name}"),
            )
    if args.allow_product is None and safety.get("allow_products") is not None:
        allow_products = safety.get("allow_products")
        if isinstance(allow_products, str):
            allow_products = [allow_products]
        args.allow_product = [str(product_id) for product_id in allow_products]
    if args.deny_product is None and safety.get("deny_products") is not None:
        deny_products = safety.get("deny_products")
        if isinstance(deny_products, str):
            deny_products = [deny_products]
        args.deny_product = [str(product_id) for product_id in deny_products]
    if (
        not args.require_known_profitable_inventory
        and safety.get("require_known_profitable_inventory") is True
    ):
        args.require_known_profitable_inventory = True
    if args.profit_target_pct is None:
        args.profit_target_pct = _optional_decimal(
            safety.get("profit_target_pct"),
            field_name="safety_policy.profit_target_pct",
        )


def _build_fill_ledger_repo() -> Any:
    from business.fill_ledger import FillLedgerRepository
    from database.database import PostgresDB

    return FillLedgerRepository(PostgresDB())


def _backfill_sweep_fills(
    *,
    rest_client: Any,
    reports: list[Any],
) -> dict[str, Any]:
    try:
        from business.spot_fill_backfill import (
            backfill_fill_ledger_from_order_reports,
        )

        return backfill_fill_ledger_from_order_reports(
            fill_ledger_repo=_build_fill_ledger_repo(),
            rest_client=rest_client,
            order_reports=[report.to_dict() for report in reports],
        )
    except Exception as exc:  # pragma: no cover - depends on local DB wiring
        return {
            "total_order_count": len(reports),
            "total_fetched_fill_count": 0,
            "total_appended_fill_count": 0,
            "total_skipped_fill_count": 0,
            "orders": [],
            "error": f"{type(exc).__name__}: {exc}",
        }


def _build_summary(
    *,
    config_id: str,
    run_id: str | None,
    state_file: Path,
    status: str,
    config: dict[str, Any],
    plan: dict[str, Any] | None = None,
    execution: dict[str, Any] | None = None,
    automation_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    execution = execution or {}
    summary = {
        "config_id": config_id,
        "run_id": run_id,
        "state_file": str(state_file),
        "status": status,
        "config": config,
        "automation_decision": automation_decision,
        "live_coinbase_orders_ran": bool(
            execution.get("live_coinbase_orders_ran", False)
        ),
        "total_submitted_notional_usdc": (
            execution.get("total_submitted_notional_usdc") or "0"
        ),
        "total_executed_notional_usdc": (
            execution.get("total_executed_notional_usdc") or "0"
        ),
        "read_only_coinbase_requests": [],
        "live_coinbase_requests": [],
    }
    if plan is not None:
        summary["plan"] = plan
        summary["read_only_coinbase_requests"] = [
            "get_public_products",
            "get_accounts",
        ]
    if execution:
        summary["execution"] = execution
        if execution.get("live_coinbase_orders_ran"):
            summary["live_coinbase_requests"] = [
                "create_order",
                "get_order",
                "list_fills",
            ]
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Place explicitly approved live orders for a USDC-only spot "
            "portfolio sweep, or run one due automation attempt."
        )
    )
    parser.add_argument(
        "--side",
        default=None,
        choices=[OrderSide.BUY.value, OrderSide.SELL.value],
        help="Sweep side to execute.",
    )
    parser.add_argument(
        "--quote-notional",
        default=None,
        type=Decimal,
        help="Requested USDC notional per eligible crypto-USDC pair.",
    )
    parser.add_argument(
        "--max-products",
        type=int,
        default=None,
        help="Optional cap on eligible products included in the sweep.",
    )
    parser.add_argument(
        "--order-type",
        default=None,
        choices=[order_type.value for order_type in SpotPortfolioSweepOrderType],
        help="Live order policy. Limit modes use rounded planned base size.",
    )
    parser.add_argument(
        "--limit-price-offset-bps",
        type=Decimal,
        default=None,
        help=(
            "Limit price offset in basis points. BUY limits price above mark; "
            "SELL limits price below mark. Ignored by market_ioc."
        ),
    )
    parser.add_argument(
        "--approved-live-orders",
        action="store_true",
        help="Required for any live Coinbase order submission.",
    )
    parser.add_argument(
        "--repeat-every-hours",
        type=Decimal,
        default=None,
        help="Run only when this recurring interval has elapsed.",
    )
    parser.add_argument(
        "--max-runs",
        type=int,
        default=None,
        help="Maximum live run attempts for this recurring config.",
    )
    parser.add_argument(
        "--disable-automation",
        action="store_true",
        help="Write a stop record for this config and exit without live orders.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print durable sweep operator status and exit without Coinbase calls.",
    )
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="Reconcile durable sweep run records against Coinbase and append reconciliation records.",
    )
    parser.add_argument(
        "--pnl-report",
        action="store_true",
        help="Build a read-only fill-ledger P/L report using public Coinbase mark prices.",
    )
    parser.add_argument(
        "--inventory-coverage",
        action="store_true",
        help="Build a read-only wallet-vs-fill-ledger inventory coverage report.",
    )
    parser.add_argument(
        "--config-registry",
        action="store_true",
        help="Print the durable sweep config registry and exit without Coinbase calls.",
    )
    parser.add_argument(
        "--config-file",
        type=Path,
        default=None,
        help="Versioned JSON sweep config file. CLI values override supplied config fields.",
    )
    parser.add_argument(
        "--validate-config",
        action="store_true",
        help="Load config/CLI values, build a wallet-aware plan, and print an explain report without live orders.",
    )
    parser.add_argument(
        "--product-id",
        action="append",
        default=None,
        help="Optional USDC spot product filter for --pnl-report. Can be repeated.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional run_id filter for --reconcile.",
    )
    parser.add_argument(
        "--config-id",
        default=None,
        help="Optional explicit automation config id. Defaults to a hash of side/notional/max-products.",
    )
    parser.add_argument(
        "--max-total-notional-per-run",
        type=Decimal,
        default=None,
        help="Safety cap: maximum planned USDC notional for one run.",
    )
    parser.add_argument(
        "--max-notional-per-order",
        type=Decimal,
        default=None,
        help="Safety cap: maximum planned USDC notional per product order.",
    )
    parser.add_argument(
        "--max-planned-orders",
        type=int,
        default=None,
        help="Safety cap: maximum planned product orders.",
    )
    parser.add_argument(
        "--max-skipped-orders",
        type=int,
        default=None,
        help="Safety cap: maximum skipped products tolerated in the plan.",
    )
    parser.add_argument(
        "--allow-product",
        action="append",
        default=None,
        help="Safety allow-list product id. Can be repeated.",
    )
    parser.add_argument(
        "--deny-product",
        action="append",
        default=None,
        help="Safety deny-list product id. Can be repeated.",
    )
    parser.add_argument(
        "--disable-safety-policy",
        action="store_true",
        help="Disable artificial safety policy checks for this invocation.",
    )
    parser.add_argument(
        "--require-known-profitable-inventory",
        action="store_true",
        help="Safety policy: require known profitable lots for planned SELL sweeps.",
    )
    parser.add_argument(
        "--profit-target-pct",
        type=Decimal,
        default=None,
        help="Optional profit target percentage override for known-inventory SELL safety.",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=DEFAULT_STATE_FILE,
        help="Durable JSONL run ledger path.",
    )
    parser.add_argument(
        "--poll-timeout-seconds",
        type=float,
        default=20.0,
        help="Seconds to poll each submitted order for terminal status.",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=0.5,
        help="Polling interval for submitted order status.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Omit per-product plan items. Live order reports are still included.",
    )
    parser.add_argument(
        "--skip-fill-backfill",
        action="store_true",
        help="Skip REST-fill backfill into fill_ledger after submitted live sweep orders.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        file_config = _load_sweep_config_file(args.config_file)
        _apply_config_file(args, file_config)
    except ValueError as exc:
        parser.error(str(exc))
    if args.order_type is None:
        args.order_type = SpotPortfolioSweepOrderType.MARKET_IOC.value
    if args.limit_price_offset_bps is None:
        args.limit_price_offset_bps = Decimal("0")

    read_only_mode_count = sum(
        1
        for enabled in (
            args.status,
            args.reconcile,
            args.pnl_report,
            args.inventory_coverage,
            args.config_registry,
            args.validate_config,
        )
        if enabled
    )
    if read_only_mode_count > 1:
        parser.error(
            "--status, --reconcile, --pnl-report, --inventory-coverage, "
            "--config-registry, and --validate-config are mutually exclusive"
        )
    if args.quote_notional is not None and args.quote_notional <= 0:
        parser.error("--quote-notional must be greater than 0")
    if args.max_products is not None and args.max_products <= 0:
        parser.error("--max-products must be greater than 0")
    if args.limit_price_offset_bps < 0:
        parser.error("--limit-price-offset-bps must be greater than or equal to 0")
    if (
        args.order_type == SpotPortfolioSweepOrderType.MARKET_IOC.value
        and args.limit_price_offset_bps != 0
    ):
        parser.error("--limit-price-offset-bps can only be used with limit order types")
    if args.side == OrderSide.SELL.value and args.limit_price_offset_bps >= 10000:
        parser.error("SELL --limit-price-offset-bps must be less than 10000")
    if args.repeat_every_hours is not None and args.repeat_every_hours <= 0:
        parser.error("--repeat-every-hours must be greater than 0")
    if args.max_runs is not None and args.max_runs <= 0:
        parser.error("--max-runs must be greater than 0")
    for option_name in (
        "max_total_notional_per_run",
        "max_notional_per_order",
    ):
        value = getattr(args, option_name)
        if value is not None and value <= 0:
            parser.error(f"--{option_name.replace('_', '-')} must be greater than 0")
    for option_name in ("max_planned_orders", "max_skipped_orders"):
        value = getattr(args, option_name)
        if value is not None and value <= 0:
            parser.error(f"--{option_name.replace('_', '-')} must be greater than 0")
    if args.profit_target_pct is not None and args.profit_target_pct < 0:
        parser.error("--profit-target-pct must be greater than or equal to 0")
    recurring = args.repeat_every_hours is not None or args.max_runs is not None
    if recurring and (
        args.repeat_every_hours is None or args.max_runs is None
    ):
        parser.error("--repeat-every-hours and --max-runs must be supplied together")

    config = _config_payload(args)
    if file_config:
        config["source_config_file"] = str(args.config_file)
    config_id = args.config_id
    if config_id is None and args.side and args.quote_notional is not None:
        config_id = build_sweep_config_id(
            side=args.side,
            quote_notional=args.quote_notional,
            max_products=args.max_products,
            order_type=args.order_type,
            limit_price_offset_bps=args.limit_price_offset_bps,
        )

    if args.status:
        operator_status = build_sweep_operator_status(
            records=load_sweep_run_records(args.state_file),
        )
        summary = _build_summary(
            config_id=config_id or "",
            run_id=None,
            state_file=args.state_file,
            status=SpotPortfolioSweepRunStatus.COMPLETED.value,
            config=config,
        )
        summary["operator_status"] = operator_status
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
        return 0

    if args.config_registry:
        registry = build_sweep_config_registry(
            records=load_sweep_run_records(args.state_file),
        )
        summary = _build_summary(
            config_id=config_id or "",
            run_id=None,
            state_file=args.state_file,
            status=SpotPortfolioSweepRunStatus.COMPLETED.value,
            config=config,
        )
        summary["config_registry"] = registry
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
        return 0

    if args.inventory_coverage:
        if not os.environ.get("COINBASE_API_KEY") or not os.environ.get("COINBASE_API_SECRET"):
            parser.error("COINBASE_API_KEY and COINBASE_API_SECRET are required")
        import configuration

        rest_client = configuration.get_rest_client()
        products = _load_public_products()
        wallets = _load_wallets(rest_client)
        report = build_spot_inventory_coverage_report(
            fill_ledger_repo=_build_fill_ledger_repo(),
            products=products,
            wallets=wallets,
            inventory_baselines=getattr(configuration, "SPOT_INVENTORY_BASELINES", []),
        )
        if args.summary_only:
            report.pop("products", None)
        summary = _build_summary(
            config_id=config_id or "",
            run_id=None,
            state_file=args.state_file,
            status=SpotPortfolioSweepRunStatus.COMPLETED.value,
            config=config,
        )
        summary["read_only_coinbase_requests"] = [
            "get_public_products",
            "get_accounts",
        ]
        summary["inventory_coverage"] = report
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
        return 0

    if args.pnl_report:
        products = _load_public_products()
        report = build_spot_portfolio_pnl_report(
            fill_ledger_repo=_build_fill_ledger_repo(),
            products=products,
            product_ids=args.product_id,
        )
        summary = _build_summary(
            config_id=config_id or "",
            run_id=None,
            state_file=args.state_file,
            status=SpotPortfolioSweepRunStatus.COMPLETED.value,
            config=config,
        )
        summary["read_only_coinbase_requests"] = ["get_public_products"]
        summary["pnl_report"] = report
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
        return 0

    if args.validate_config:
        if args.side is None or args.quote_notional is None:
            parser.error("--side and --quote-notional are required for --validate-config")
        if not os.environ.get("COINBASE_API_KEY") or not os.environ.get("COINBASE_API_SECRET"):
            parser.error("COINBASE_API_KEY and COINBASE_API_SECRET are required")
        import configuration

        rest_client = configuration.get_rest_client()
        products = _load_public_products()
        wallets = _load_wallets(rest_client)
        plan_obj = build_usdc_portfolio_sweep_plan(
            side=args.side,
            quote_notional=args.quote_notional,
            products=products,
            wallets=wallets,
            max_products=args.max_products,
        )
        fill_ledger_repo = None
        if args.side == OrderSide.SELL.value:
            try:
                fill_ledger_repo = _build_fill_ledger_repo()
            except Exception:
                fill_ledger_repo = None
        safety_evaluation = evaluate_sweep_safety_policy(
            plan=plan_obj,
            policy=config["safety_policy"],
            order_type=args.order_type,
            limit_price_offset_bps=args.limit_price_offset_bps,
            fill_ledger_repo=fill_ledger_repo,
            inventory_baselines=getattr(configuration, "SPOT_INVENTORY_BASELINES", []),
            profit_target_pct=args.profit_target_pct,
        )
        plan = plan_obj.to_dict()
        explain = build_sweep_plan_explain(
            plan=plan_obj,
            safety_evaluation=safety_evaluation,
            order_type=args.order_type,
            limit_price_offset_bps=args.limit_price_offset_bps,
            fill_ledger_repo=fill_ledger_repo,
            inventory_baselines=getattr(configuration, "SPOT_INVENTORY_BASELINES", []),
            profit_target_pct=args.profit_target_pct,
        )
        if args.summary_only:
            plan.pop("items", None)
            explain.pop("items", None)
        summary = _build_summary(
            config_id=config_id or "",
            run_id=None,
            state_file=args.state_file,
            status=SpotPortfolioSweepRunStatus.COMPLETED.value,
            config=config,
            plan=plan,
        )
        summary["live_coinbase_orders_ran"] = False
        summary["total_submitted_notional_usdc"] = "0"
        summary["total_executed_notional_usdc"] = "0"
        summary["safety_evaluation"] = safety_evaluation.to_dict()
        summary["plan_explain"] = explain
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
        return 0

    if args.reconcile:
        if not os.environ.get("COINBASE_API_KEY") or not os.environ.get("COINBASE_API_SECRET"):
            parser.error("COINBASE_API_KEY and COINBASE_API_SECRET are required")
        import configuration

        rest_client = configuration.get_rest_client()
        try:
            fill_ledger_repo = _build_fill_ledger_repo()
        except Exception:
            fill_ledger_repo = None
        records = load_sweep_run_records(args.state_file)
        run_records = [
            record
            for record in records
            if record.get("record_type") == "sweep_run"
            and (config_id is None or record.get("config_id") == config_id)
            and (args.run_id is None or record.get("run_id") == args.run_id)
        ]
        reconciliations = [
            reconcile_sweep_run_record(
                record=record,
                rest_client=rest_client,
                fill_ledger_repo=fill_ledger_repo,
            )
            for record in run_records
        ]
        for reconciliation in reconciliations:
            append_sweep_run_record(args.state_file, reconciliation)
        summary = _build_summary(
            config_id=config_id or "",
            run_id=args.run_id,
            state_file=args.state_file,
            status=SpotPortfolioSweepRunStatus.COMPLETED.value,
            config=config,
        )
        summary["read_only_coinbase_requests"] = ["get_order", "list_fills"]
        summary["reconciled_run_count"] = len(reconciliations)
        summary["reconciliations"] = reconciliations
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
        return 0

    if config_id is None:
        parser.error("--side and --quote-notional are required unless --config-id is supplied")
    if not args.disable_automation and (
        args.side is None or args.quote_notional is None
    ):
        parser.error("--side and --quote-notional are required for live mode")

    if args.disable_automation:
        record = build_sweep_disabled_record(config_id=config_id, config=config)
        append_sweep_run_record(args.state_file, record)
        summary = _build_summary(
            config_id=config_id,
            run_id=None,
            state_file=args.state_file,
            status=SpotPortfolioSweepRunStatus.DISABLED.value,
            config=config,
        )
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
        return 0

    if not args.approved_live_orders:
        parser.error("--approved-live-orders is required because this can place live orders")
    if not os.environ.get("COINBASE_API_KEY") or not os.environ.get("COINBASE_API_SECRET"):
        parser.error("COINBASE_API_KEY and COINBASE_API_SECRET are required")

    records = load_sweep_run_records(args.state_file)
    automation_decision = None
    if recurring:
        automation_decision = evaluate_sweep_automation_due(
            config_id=config_id,
            repeat_every_hours=args.repeat_every_hours,
            max_runs=args.max_runs,
            records=records,
        )
        if automation_decision["decision"] != (
            SpotPortfolioSweepAutomationDecision.DUE.value
        ):
            run_id = f"spot-sweep-skip-{uuid.uuid4()}"
            now = datetime.now(timezone.utc)
            record = build_sweep_run_record(
                config_id=config_id,
                run_id=run_id,
                status=SpotPortfolioSweepRunStatus.SKIPPED.value,
                started_at=now,
                completed_at=now,
                config=config,
                automation_decision=automation_decision,
            )
            append_sweep_run_record(args.state_file, record)
            summary = _build_summary(
                config_id=config_id,
                run_id=run_id,
                state_file=args.state_file,
                status=SpotPortfolioSweepRunStatus.SKIPPED.value,
                config=config,
                automation_decision=automation_decision,
            )
            print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
            return 0

    import configuration

    rest_client = configuration.get_rest_client()
    products = _load_public_products()
    wallets = _load_wallets(rest_client)
    plan_obj = build_usdc_portfolio_sweep_plan(
        side=args.side,
        quote_notional=args.quote_notional,
        products=products,
        wallets=wallets,
        max_products=args.max_products,
    )
    plan = plan_obj.to_dict()
    if args.summary_only:
        plan.pop("items", None)

    product_metadata = build_sweep_product_metadata(products)
    run_id = f"spot-sweep-{uuid.uuid4()}"
    started_at = datetime.now(timezone.utc)
    fill_ledger_repo = None
    if config["safety_policy"].get("require_known_profitable_inventory"):
        fill_ledger_repo = _build_fill_ledger_repo()
    safety_evaluation = evaluate_sweep_safety_policy(
        plan=plan_obj,
        policy=config["safety_policy"],
        order_type=args.order_type,
        limit_price_offset_bps=args.limit_price_offset_bps,
        fill_ledger_repo=fill_ledger_repo,
        inventory_baselines=getattr(configuration, "SPOT_INVENTORY_BASELINES", []),
        profit_target_pct=args.profit_target_pct,
    ).to_dict()
    if safety_evaluation["decision"] != (
        SpotPortfolioSweepSafetyDecision.ALLOWED.value
    ):
        completed_at = datetime.now(timezone.utc)
        execution = {
            "run_status": SpotPortfolioSweepRunStatus.FAILED.value,
            "live_coinbase_orders_ran": False,
            "submitted_order_count": 0,
            "blocked_or_error_count": len(safety_evaluation["violations"]),
            "total_submitted_notional_usdc": "0",
            "total_executed_notional_usdc": "0",
            "orders": [],
            "safety_evaluation": safety_evaluation,
        }
        record = build_sweep_run_record(
            config_id=config_id,
            run_id=run_id,
            status=SpotPortfolioSweepRunStatus.FAILED.value,
            started_at=started_at,
            completed_at=completed_at,
            config=config,
            plan=plan,
            execution=execution,
            automation_decision=automation_decision,
        )
        append_sweep_run_record(args.state_file, record)
        summary = _build_summary(
            config_id=config_id,
            run_id=run_id,
            state_file=args.state_file,
            status=SpotPortfolioSweepRunStatus.FAILED.value,
            config=config,
            plan=plan,
            execution=execution,
            automation_decision=automation_decision,
        )
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
        return 0

    reports = execute_usdc_portfolio_sweep_plan(
        plan=plan_obj,
        rest_client=rest_client,
        wallet_fetcher=lambda: _load_wallets(rest_client),
        product_metadata=product_metadata,
        order_type=args.order_type,
        limit_price_offset_bps=args.limit_price_offset_bps,
        poll_timeout_seconds=args.poll_timeout_seconds,
        poll_interval_seconds=args.poll_interval_seconds,
    )
    completed_at = datetime.now(timezone.utc)
    execution = summarize_sweep_execution(reports=reports)
    execution["fill_backfill"] = (
        {
            "skipped": True,
            "reason": "--skip-fill-backfill supplied",
        }
        if args.skip_fill_backfill
        else _backfill_sweep_fills(rest_client=rest_client, reports=reports)
    )
    execution["safety_evaluation"] = safety_evaluation
    status = execution["run_status"]
    record = build_sweep_run_record(
        config_id=config_id,
        run_id=run_id,
        status=status,
        started_at=started_at,
        completed_at=completed_at,
        config=config,
        plan=plan,
        execution=execution,
        automation_decision=automation_decision,
    )
    append_sweep_run_record(args.state_file, record)
    summary = _build_summary(
        config_id=config_id,
        run_id=run_id,
        state_file=args.state_file,
        status=status,
        config=config,
        plan=plan,
        execution=execution,
        automation_decision=automation_decision,
    )
    print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
