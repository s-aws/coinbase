"""Read-only campaign orchestration for USDC spot portfolio sweeps.

Campaigns are an operator layer over the existing USDC sweep planner and live
runner. This module validates campaign config, builds dry-run matrices, records
durable P/L snapshots, and summarizes status without submitting Coinbase orders.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping

from business.spot_portfolio_sweep import (
    build_spot_inventory_coverage_report,
    build_spot_portfolio_pnl_report,
    build_sweep_config_id,
    build_sweep_plan_explain,
    build_usdc_portfolio_sweep_plan,
    evaluate_sweep_automation_due,
    evaluate_sweep_safety_policy,
    summarize_sweep_order_statuses,
)
from core.enums import (
    InventoryLotSource,
    OrderSide,
    SpotAuditRecordType,
    SpotCampaignGateStatus,
    SpotCampaignProductSelection,
    SpotCampaignRetryOrderClass,
    SpotCampaignRunMode,
    SpotCampaignStatus,
    SpotCostBasisGapStatus,
    SpotCostBasisSource,
    SpotFeatureInventoryRetentionPolicy,
    SpotOperationLockStatus,
    SpotPortfolioSweepExecutionStatus,
    SpotPortfolioSweepOrderType,
    SpotPortfolioSweepRunStatus,
    SpotPortfolioSweepSafetyDecision,
    SpotSweepRecoveryGateStatus,
)


QUOTE_CURRENCY = "USDC"
DEFAULT_CAMPAIGN_STATE_FILE = Path("runtime_state") / "spot_campaigns.jsonl"
DEFAULT_REQUIRED_AUDIT_EVIDENCE = (
    "client_order_id",
    "exchange_order_id",
    "submitted_notional_usdc",
    "executed_notional_usdc",
    "fill_ledger_reconciliation",
)


def _enum_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value


def _text(value: Any) -> str:
    value = _enum_value(value)
    if value is None:
        return ""
    return str(value).strip()


def _decimal(value: Any, default: str = "0") -> Decimal:
    value = _enum_value(value)
    if isinstance(value, Mapping) and "value" in value:
        value = value.get("value")
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _format_decimal(value: Decimal | None) -> str:
    if value is None:
        return "0"
    if not value.is_finite():
        return str(value)
    if value == 0:
        return "0"
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal("1")))
    return format(normalized, "f")


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a JSON object")
    return value


def _string_list(value: Any, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, Iterable) or isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a list of strings")
    return [str(item) for item in value if str(item).strip()]


def _product_list(value: Any, *, field_name: str) -> list[str]:
    return sorted({product.upper() for product in _string_list(value, field_name=field_name)})


def _optional_positive_decimal_text(
    value: Any,
    *,
    field_name: str,
    required: bool = False,
) -> str | None:
    if value is None:
        if required:
            raise ValueError(f"{field_name} is required")
        return None
    converted = _decimal(value)
    if converted <= 0:
        raise ValueError(f"{field_name} must be greater than 0")
    return _format_decimal(converted)


def _optional_non_negative_decimal_text(
    value: Any,
    *,
    field_name: str,
    default: str | None = None,
) -> str | None:
    if value is None:
        return default
    converted = _decimal(value)
    if converted < 0:
        raise ValueError(f"{field_name} must be greater than or equal to 0")
    return _format_decimal(converted)


def _optional_positive_int(
    value: Any,
    *,
    field_name: str,
    required: bool = False,
) -> int | None:
    if value is None:
        if required:
            raise ValueError(f"{field_name} is required")
        return None
    try:
        converted = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    if converted <= 0:
        raise ValueError(f"{field_name} must be greater than 0")
    return converted


def _dedupe_strings(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        text = _text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output


def _generated_campaign_id(config: Mapping[str, Any]) -> str:
    payload = {
        "side": config.get("side"),
        "quote_currency": QUOTE_CURRENCY,
        "quote_notional": config.get("quote_notional"),
        "max_products": config.get("max_products"),
        "order_type": config.get("order_type"),
        "limit_price_offset_bps": config.get("limit_price_offset_bps"),
        "automation": config.get("automation"),
        "product_scope": config.get("product_scope"),
        "safety_policy": config.get("safety_policy"),
        "cost_basis_authority": config.get("cost_basis_authority"),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"spot-campaign-{digest[:16]}"


def build_spot_campaign_id(config: Mapping[str, Any]) -> str:
    """Return a stable campaign id for normalized or raw campaign config."""
    raw_id = _text(config.get("campaign_id"))
    if raw_id:
        return raw_id
    return _generated_campaign_id(config)


def normalize_spot_campaign_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize a versioned spot campaign config."""
    raw = dict(_require_mapping(config, "campaign config"))
    version = raw.get("version", 1)
    if version != 1:
        raise ValueError("spot campaign config version must be 1")

    product_scope = dict(raw.get("product_scope") or {})
    quote_currency = _text(
        product_scope.get("quote_currency") or raw.get("quote_currency") or QUOTE_CURRENCY
    ).upper()
    if quote_currency != QUOTE_CURRENCY:
        raise ValueError("spot campaign product_scope.quote_currency must be USDC")
    selection_rule = _text(
        product_scope.get("selection_rule")
        or SpotCampaignProductSelection.ALL_COINBASE_USDC_SPOT_US_CUSTOMER_AVAILABLE
    )
    try:
        selection_rule = SpotCampaignProductSelection(selection_rule).value
    except ValueError as exc:
        raise ValueError("unsupported spot campaign product selection rule") from exc

    try:
        side = OrderSide(_text(raw.get("side")).upper()).value
    except ValueError as exc:
        raise ValueError("side must be BUY or SELL") from exc

    try:
        order_type = SpotPortfolioSweepOrderType(
            _text(raw.get("order_type") or SpotPortfolioSweepOrderType.MARKET_IOC)
        ).value
    except ValueError as exc:
        raise ValueError("unsupported spot campaign order_type") from exc
    limit_price_offset_bps = _optional_non_negative_decimal_text(
        raw.get("limit_price_offset_bps"),
        field_name="limit_price_offset_bps",
        default="0",
    )
    if (
        order_type == SpotPortfolioSweepOrderType.MARKET_IOC.value
        and _decimal(limit_price_offset_bps) != 0
    ):
        raise ValueError("limit_price_offset_bps can only be used with limit order types")
    if side == OrderSide.SELL.value and _decimal(limit_price_offset_bps) >= 10000:
        raise ValueError("SELL limit_price_offset_bps must be less than 10000")

    quote_notional = _optional_positive_decimal_text(
        raw.get("quote_notional"),
        field_name="quote_notional",
        required=True,
    )
    max_products = _optional_positive_int(
        raw.get("max_products", product_scope.get("max_products")),
        field_name="max_products",
    )

    automation = dict(raw.get("automation") or {})
    repeat_every_hours = automation.get(
        "repeat_every_hours",
        raw.get("repeat_every_hours"),
    )
    max_runs = automation.get("max_runs", raw.get("max_runs"))
    automation_enabled = bool(
        automation.get("enabled", repeat_every_hours is not None or max_runs is not None)
    )
    normalized_repeat = _optional_positive_decimal_text(
        repeat_every_hours,
        field_name="automation.repeat_every_hours",
        required=automation_enabled,
    )
    normalized_max_runs = _optional_positive_int(
        max_runs,
        field_name="automation.max_runs",
        required=automation_enabled,
    )

    safety = dict(raw.get("safety_policy") or raw.get("safety") or {})
    scope_allow = _product_list(
        product_scope.get("allow_products"),
        field_name="product_scope.allow_products",
    )
    scope_deny = _product_list(
        product_scope.get("deny_products"),
        field_name="product_scope.deny_products",
    )
    safety_allow = _product_list(
        safety.get("allow_products"),
        field_name="safety_policy.allow_products",
    )
    safety_deny = _product_list(
        safety.get("deny_products"),
        field_name="safety_policy.deny_products",
    )
    allow_products = sorted(set(scope_allow + safety_allow))
    deny_products = sorted(set(scope_deny + safety_deny))

    cost_basis_authority = dict(raw.get("cost_basis_authority") or {})
    allowed_sources = _string_list(
        cost_basis_authority.get(
            "allowed_sources",
            [
                SpotCostBasisSource.FILL_LEDGER.value,
                SpotCostBasisSource.IMPORTED_BASELINE.value,
            ],
        ),
        field_name="cost_basis_authority.allowed_sources",
    )
    normalized_sources = []
    for source in allowed_sources:
        try:
            normalized_sources.append(SpotCostBasisSource(source).value)
        except ValueError as exc:
            raise ValueError("unsupported cost_basis_authority.allowed_sources value") from exc
    normalized_sources = _dedupe_strings(normalized_sources)
    coinbase_average_requested = (
        SpotCostBasisSource.COINBASE_AVERAGE_COST.value in normalized_sources
    )
    allow_coinbase_average = bool(
        safety.get("allow_coinbase_average_cost_basis", False)
        or (coinbase_average_requested and side == OrderSide.SELL.value)
    )
    if safety.get("allow_coinbase_average_cost_basis", False) and side != OrderSide.SELL.value:
        raise ValueError("allow_coinbase_average_cost_basis is only valid for SELL")

    require_known = bool(
        safety.get("require_known_profitable_inventory", False)
        or (allow_coinbase_average and side == OrderSide.SELL.value)
    )
    if allow_coinbase_average and not require_known:
        raise ValueError(
            "allow_coinbase_average_cost_basis requires known profitable inventory"
        )
    average_buffer = _optional_non_negative_decimal_text(
        safety.get(
            "coinbase_average_cost_profit_buffer_pct",
            cost_basis_authority.get("coinbase_average_cost_profit_buffer_pct", "0.5"),
        ),
        field_name="safety_policy.coinbase_average_cost_profit_buffer_pct",
        default="0.5",
    )
    profit_target_pct = _optional_non_negative_decimal_text(
        safety.get("profit_target_pct", cost_basis_authority.get("profit_target_pct")),
        field_name="safety_policy.profit_target_pct",
    )

    normalized_safety = {
        "enabled": bool(safety.get("enabled", True)),
        "require_wallet_check": bool(safety.get("require_wallet_check", True)),
        "require_known_profitable_inventory": require_known,
        "allow_coinbase_average_cost_basis": allow_coinbase_average,
        "coinbase_average_cost_profit_buffer_pct": average_buffer,
        "max_total_notional_per_run": _optional_positive_decimal_text(
            safety.get("max_total_notional_per_run"),
            field_name="safety_policy.max_total_notional_per_run",
        ),
        "max_notional_per_order": _optional_positive_decimal_text(
            safety.get("max_notional_per_order"),
            field_name="safety_policy.max_notional_per_order",
        ),
        "max_planned_orders": _optional_positive_int(
            safety.get("max_planned_orders"),
            field_name="safety_policy.max_planned_orders",
        ),
        "max_skipped_orders": _optional_positive_int(
            safety.get("max_skipped_orders"),
            field_name="safety_policy.max_skipped_orders",
        ),
        "allow_products": allow_products,
        "deny_products": deny_products,
    }
    if profit_target_pct is not None:
        normalized_safety["profit_target_pct"] = profit_target_pct

    inventory_policy = dict(raw.get("inventory_policy") or {})
    retention = _text(
        inventory_policy.get("retention")
        or SpotFeatureInventoryRetentionPolicy.RETAIN
    )
    try:
        retention = SpotFeatureInventoryRetentionPolicy(retention).value
    except ValueError as exc:
        raise ValueError("unsupported inventory_policy.retention") from exc

    normalized = {
        "version": 1,
        "campaign_id": _text(raw.get("campaign_id")) or None,
        "campaign_name": _text(raw.get("campaign_name") or raw.get("feature_name")) or None,
        "side": side,
        "quote_currency": QUOTE_CURRENCY,
        "quote_notional": quote_notional,
        "max_products": max_products,
        "order_type": order_type,
        "limit_price_offset_bps": limit_price_offset_bps,
        "automation": {
            "enabled": automation_enabled,
            "repeat_every_hours": normalized_repeat,
            "max_runs": normalized_max_runs,
        },
        "product_scope": {
            "quote_currency": QUOTE_CURRENCY,
            "us_customer_available": bool(product_scope.get("us_customer_available", True)),
            "selection_rule": selection_rule,
            "allow_products": allow_products,
            "deny_products": deny_products,
        },
        "safety_policy": normalized_safety,
        "inventory_policy": {
            "retention": retention,
        },
        "cost_basis_authority": {
            "allowed_sources": normalized_sources,
            "coinbase_average_cost_profit_buffer_pct": average_buffer,
        },
        "live_approval": {
            "required": bool((raw.get("live_approval") or {}).get("required", True)),
        },
        "audit": {
            "required_evidence": _dedupe_strings(
                _string_list(
                    (raw.get("audit") or {}).get(
                        "required_evidence",
                        DEFAULT_REQUIRED_AUDIT_EVIDENCE,
                    ),
                    field_name="audit.required_evidence",
                )
            ),
        },
    }
    normalized["campaign_id"] = build_spot_campaign_id(normalized)
    normalized["sweep_config_id"] = build_sweep_config_id(
        side=side,
        quote_notional=quote_notional,
        max_products=max_products,
        order_type=order_type,
        limit_price_offset_bps=limit_price_offset_bps,
        allow_products=allow_products,
        deny_products=deny_products,
    )
    return normalized


def spot_campaign_config_to_sweep_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a campaign config into the existing sweep config schema."""
    normalized = normalize_spot_campaign_config(config)
    automation = normalized["automation"]
    sweep_config = {
        "version": 1,
        "config_id": normalized["sweep_config_id"],
        "side": normalized["side"],
        "quote_notional": normalized["quote_notional"],
        "max_products": normalized["max_products"],
        "order_type": normalized["order_type"],
        "limit_price_offset_bps": normalized["limit_price_offset_bps"],
        "safety_policy": dict(normalized["safety_policy"]),
        "campaign_id": normalized["campaign_id"],
    }
    if automation["enabled"]:
        sweep_config["repeat_every_hours"] = automation["repeat_every_hours"]
        sweep_config["max_runs"] = automation["max_runs"]
    return sweep_config


def build_spot_campaign_intake_request(config: Mapping[str, Any]) -> dict[str, Any]:
    """Build the existing feature-intake request shape from campaign config."""
    normalized = normalize_spot_campaign_config(config)
    safety = normalized["safety_policy"]
    return {
        "feature_name": normalized.get("campaign_name") or normalized["campaign_id"],
        "goal": (
            "Automate capped USDC spot campaign sweeps with durable P/L, "
            "reconciliation, and cost-basis evidence."
        ),
        "product_scope": dict(normalized["product_scope"]),
        "order_sides": [normalized["side"]],
        "order_types": [normalized["order_type"]],
        "automation": dict(normalized["automation"]),
        "live_approval": dict(normalized["live_approval"]),
        "safety": {
            "max_notional_per_order": safety.get("max_notional_per_order"),
            "max_total_notional_per_run": safety.get("max_total_notional_per_run"),
            "max_planned_orders": safety.get("max_planned_orders"),
            "max_skipped_orders": safety.get("max_skipped_orders"),
        },
        "inventory_policy": dict(normalized["inventory_policy"]),
        "cost_basis_authority": dict(normalized["cost_basis_authority"]),
        "audit": dict(normalized["audit"]),
    }


def _average_cost_records(cost_basis: Any) -> list[Mapping[str, Any]]:
    if isinstance(cost_basis, Mapping):
        return list(cost_basis.get("records") or [])
    return list(cost_basis or [])


def _average_cost_baselines(cost_basis: Any) -> list[Mapping[str, Any]]:
    if isinstance(cost_basis, Mapping):
        return list(cost_basis.get("baselines") or [])
    return []


def _summarize_pnl_report(report: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not report:
        return None
    snapshot = report.get("snapshot") if isinstance(report, Mapping) else {}
    portfolio = snapshot.get("portfolio") if isinstance(snapshot, Mapping) else {}
    average_cost = report.get("average_cost_pnl") if isinstance(report, Mapping) else {}
    average_portfolio = (
        average_cost.get("portfolio")
        if isinstance(average_cost, Mapping)
        else None
    )
    return {
        "generated_at": report.get("generated_at") or snapshot.get("generated_at"),
        "selected_product_count": report.get("selected_product_count"),
        "mark_price_count": report.get("mark_price_count"),
        "portfolio": dict(portfolio or {}),
        "average_cost_portfolio": dict(average_portfolio or {}),
    }


def _summarize_cost_basis(cost_basis: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not cost_basis:
        return None
    return {
        "generated_at": cost_basis.get("generated_at"),
        "status": cost_basis.get("status"),
        "portfolio_uuid": cost_basis.get("portfolio_uuid"),
        "portfolio_name": cost_basis.get("portfolio_name"),
        "record_count": int(cost_basis.get("record_count") or 0),
        "baseline_count": int(cost_basis.get("baseline_count") or 0),
    }


def _strip_product_rows(payload: Any) -> Any:
    if isinstance(payload, Mapping):
        stripped = dict(payload)
        stripped.pop("items", None)
        stripped.pop("products", None)
        stripped.pop("selected_product_ids", None)
        if isinstance(stripped.get("snapshot"), Mapping):
            snapshot = dict(stripped["snapshot"])
            snapshot.pop("products", None)
            stripped["snapshot"] = snapshot
        if isinstance(stripped.get("average_cost_pnl"), Mapping):
            average = dict(stripped["average_cost_pnl"])
            average.pop("products", None)
            stripped["average_cost_pnl"] = average
        return stripped
    return payload


def build_spot_campaign_dry_run_matrix(
    *,
    config: Mapping[str, Any],
    products: Iterable[Any],
    wallets: Mapping[str, Any] | None,
    fill_ledger_repo: Any = None,
    inventory_baselines: Any = None,
    coinbase_average_costs: Any = None,
    sweep_records: Iterable[Mapping[str, Any]] | None = None,
    include_items: bool = True,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a read-only plan/safety/P&L matrix for one campaign config."""
    timestamp = generated_at or datetime.now(timezone.utc)
    normalized = normalize_spot_campaign_config(config)
    safety = normalized["safety_policy"]
    plan_obj = build_usdc_portfolio_sweep_plan(
        side=normalized["side"],
        quote_notional=normalized["quote_notional"],
        products=products,
        wallets=wallets,
        max_products=normalized["max_products"],
        allow_products=safety.get("allow_products"),
        deny_products=safety.get("deny_products"),
        generated_at=timestamp,
    )
    cost_baselines = (
        _average_cost_baselines(coinbase_average_costs)
        if safety.get("allow_coinbase_average_cost_basis")
        else []
    )
    cost_records = _average_cost_records(coinbase_average_costs)
    safety_evaluation = evaluate_sweep_safety_policy(
        plan=plan_obj,
        policy=safety,
        order_type=normalized["order_type"],
        limit_price_offset_bps=normalized["limit_price_offset_bps"],
        fill_ledger_repo=fill_ledger_repo,
        inventory_baselines=inventory_baselines,
        coinbase_average_cost_baselines=cost_baselines,
        profit_target_pct=safety.get("profit_target_pct"),
    )
    explain = build_sweep_plan_explain(
        plan=plan_obj,
        safety_evaluation=safety_evaluation,
        order_type=normalized["order_type"],
        limit_price_offset_bps=normalized["limit_price_offset_bps"],
        fill_ledger_repo=fill_ledger_repo,
        inventory_baselines=inventory_baselines,
        coinbase_average_cost_baselines=cost_baselines,
        profit_target_pct=safety.get("profit_target_pct"),
    )
    inventory_coverage = None
    if wallets is not None:
        inventory_coverage = build_spot_inventory_coverage_report(
            fill_ledger_repo=fill_ledger_repo,
            products=products,
            wallets=wallets,
            inventory_baselines=inventory_baselines,
            coinbase_average_costs=cost_records,
            generated_at=timestamp,
        )
    pnl_report = None
    if fill_ledger_repo is not None:
        pnl_report = build_spot_portfolio_pnl_report(
            fill_ledger_repo=fill_ledger_repo,
            products=products,
            coinbase_average_costs=cost_records,
        )

    cost_basis_drift_audit = None
    cost_basis_gap_triage = None
    if cost_records and fill_ledger_repo is not None and inventory_coverage is not None:
        from business.spot_cost_basis import (
            build_cost_basis_drift_audit,
            build_cost_basis_gap_triage,
        )

        cost_basis_drift_audit = build_cost_basis_drift_audit(
            fill_ledger_repo=fill_ledger_repo,
            products=products,
            average_cost_records=cost_records,
            generated_at=timestamp,
        )
        cost_basis_gap_triage = build_cost_basis_gap_triage(
            inventory_coverage=inventory_coverage,
            drift_audit=cost_basis_drift_audit,
            generated_at=timestamp,
        )

    automation_due = None
    if normalized["automation"]["enabled"] and sweep_records is not None:
        automation_due = evaluate_sweep_automation_due(
            config_id=normalized["sweep_config_id"],
            repeat_every_hours=normalized["automation"]["repeat_every_hours"],
            max_runs=int(normalized["automation"]["max_runs"]),
            records=sweep_records,
            now=timestamp,
        )

    plan = plan_obj.to_dict()
    output = {
        "generated_at": timestamp.isoformat(),
        "campaign_id": normalized["campaign_id"],
        "sweep_config_id": normalized["sweep_config_id"],
        "mode": SpotCampaignRunMode.DRY_RUN.value,
        "config": normalized,
        "sweep_config": spot_campaign_config_to_sweep_config(normalized),
        "automation_due": automation_due,
        "plan": plan,
        "safety_evaluation": safety_evaluation.to_dict(),
        "plan_explain": explain,
        "inventory_coverage": inventory_coverage,
        "pnl_report": pnl_report,
        "pnl_snapshot": _summarize_pnl_report(pnl_report),
        "cost_basis": _summarize_cost_basis(
            coinbase_average_costs if isinstance(coinbase_average_costs, Mapping) else None
        ),
        "cost_basis_drift_audit": cost_basis_drift_audit,
        "cost_basis_gap_triage": cost_basis_gap_triage,
        "live_coinbase_orders_ran": False,
        "live_order_notional_usdc": "0",
        "total_submitted_notional_usdc": "0",
        "total_executed_notional_usdc": "0",
    }
    if not include_items:
        for key in (
            "plan",
            "plan_explain",
            "inventory_coverage",
            "pnl_report",
            "cost_basis_drift_audit",
            "cost_basis_gap_triage",
        ):
            output[key] = _strip_product_rows(output.get(key))
    return output


def build_spot_campaign_operation_lock_status(
    *,
    lock_file: str | Path,
    stale_after_seconds: Any = 3600,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return read-only status for the shared sweep operation lock file."""
    path = Path(lock_file)
    now = now or datetime.now(timezone.utc)
    if not path.exists():
        return {
            "lock_file": str(path),
            "status": SpotOperationLockStatus.RELEASED.value,
            "exists": False,
            "stale": False,
            "age_seconds": "0",
        }
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    age_seconds = max(Decimal("0"), Decimal(str((now - mtime).total_seconds())))
    stale_after = _decimal(stale_after_seconds, default="3600")
    return {
        "lock_file": str(path),
        "status": SpotOperationLockStatus.BUSY.value,
        "exists": True,
        "stale": bool(stale_after > 0 and age_seconds > stale_after),
        "age_seconds": _format_decimal(age_seconds),
        "stale_after_seconds": _format_decimal(stale_after),
    }


def build_spot_campaign_release_gate(
    *,
    config: Mapping[str, Any],
    dry_run_matrix: Mapping[str, Any],
    intake_summary: Mapping[str, Any] | None = None,
    operation_lock_status: Mapping[str, Any] | None = None,
    recovery_plan: Mapping[str, Any] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build the read-only release gate decision for a campaign."""
    timestamp = generated_at or datetime.now(timezone.utc)
    normalized = normalize_spot_campaign_config(config)
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if intake_summary and intake_summary.get("phase_50_ready") is not True:
        failures.append({
            "code": "feature_intake_not_ready",
            "status": intake_summary.get("status"),
            "reason": "campaign intake did not pass the spot feature gate",
        })

    plan = dry_run_matrix.get("plan") or {}
    safety = dry_run_matrix.get("safety_evaluation") or {}
    if int(plan.get("planned_count") or 0) <= 0:
        failures.append({
            "code": "no_planned_orders",
            "reason": "campaign dry-run produced no planned product orders",
        })
    if safety.get("decision") != SpotPortfolioSweepSafetyDecision.ALLOWED.value:
        failures.append({
            "code": "safety_policy_blocked",
            "reason": "campaign safety policy blocked the dry-run plan",
            "violation_count": len(safety.get("violations") or []),
        })

    if operation_lock_status and operation_lock_status.get("exists"):
        warnings.append({
            "code": "operation_lock_present",
            "reason": "shared sweep lock file exists during read-only gate",
            "stale": bool(operation_lock_status.get("stale")),
        })

    if recovery_plan:
        pending_reconciliation = int(
            recovery_plan.get("planned_reconciliation_run_count") or 0
        )
        pending_backfill = int(recovery_plan.get("planned_backfill_order_count") or 0)
        if pending_reconciliation or pending_backfill:
            failures.append({
                "code": "pending_recovery",
                "reason": "existing sweep records need reconciliation or fill backfill",
                "planned_reconciliation_run_count": pending_reconciliation,
                "planned_backfill_order_count": pending_backfill,
            })

    if normalized["side"] == OrderSide.SELL.value:
        triage = dry_run_matrix.get("cost_basis_gap_triage") or {}
        triage_counts = triage.get("status_counts") or {}
        stale_count = int(
            triage_counts.get(SpotCostBasisGapStatus.STALE_AVERAGE_COST.value) or 0
        )
        if stale_count and normalized["safety_policy"].get("allow_coinbase_average_cost_basis"):
            warnings.append({
                "code": "stale_average_cost_basis",
                "reason": "Coinbase average cost authority has stale local drift rows",
                "stale_count": stale_count,
            })

    gate_status = (
        SpotCampaignGateStatus.FAILED.value
        if failures
        else SpotCampaignGateStatus.PASSED.value
    )
    campaign_status = (
        SpotCampaignStatus.BLOCKED.value
        if failures
        else SpotCampaignStatus.READY.value
    )
    return {
        "generated_at": timestamp.isoformat(),
        "campaign_id": normalized["campaign_id"],
        "sweep_config_id": normalized["sweep_config_id"],
        "mode": SpotCampaignRunMode.RELEASE_GATE.value,
        "gate_status": gate_status,
        "status": campaign_status,
        "failures": failures,
        "warnings": warnings,
        "intake_summary": dict(intake_summary or {}),
        "operation_lock_status": dict(operation_lock_status or {}),
        "recovery_plan": dict(recovery_plan or {}),
        "live_coinbase_orders_ran": False,
        "live_order_notional_usdc": "0",
        "total_submitted_notional_usdc": "0",
        "total_executed_notional_usdc": "0",
    }


def _matching_sweep_runs_for_campaign(
    *,
    config: Mapping[str, Any],
    sweep_records: Iterable[Mapping[str, Any]],
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    normalized = normalize_spot_campaign_config(config)
    matches = [
        dict(record)
        for record in sweep_records
        if record.get("record_type") == "sweep_run"
        and record.get("config_id") == normalized["sweep_config_id"]
        and (run_id is None or record.get("run_id") == run_id)
    ]
    matches.sort(key=lambda record: record.get("started_at") or "")
    return matches


def _has_submission_evidence(order: Mapping[str, Any]) -> bool:
    return bool(
        _text(order.get("exchange_order_id"))
        or _decimal(order.get("submitted_notional_usdc")) > 0
        or _decimal(order.get("executed_notional_usdc")) > 0
        or order.get("response_success") is True
        or _text(order.get("status")) == SpotPortfolioSweepExecutionStatus.SUBMITTED.value
    )


def _classify_retry_order(order: Mapping[str, Any]) -> str:
    if _has_submission_evidence(order):
        return SpotCampaignRetryOrderClass.SUBMITTED_OR_LIVE.value
    status = _text(order.get("status"))
    if status in {
        SpotPortfolioSweepExecutionStatus.BLOCKED.value,
        SpotPortfolioSweepExecutionStatus.ERROR.value,
    }:
        return SpotCampaignRetryOrderClass.RETRYABLE_NOT_SUBMITTED.value
    return SpotCampaignRetryOrderClass.NOT_RETRYABLE.value


def _retry_campaign_config(
    *,
    normalized: Mapping[str, Any],
    source_run_id: str,
    retryable_product_ids: list[str],
) -> dict[str, Any]:
    retry_count = len(retryable_product_ids)
    retry_total_notional = _format_decimal(
        _decimal(normalized["quote_notional"]) * Decimal(retry_count)
    )
    safety = dict(normalized["safety_policy"])
    safety["allow_products"] = retryable_product_ids
    safety["max_planned_orders"] = retry_count
    safety["max_total_notional_per_run"] = retry_total_notional
    if safety.get("max_notional_per_order") is None:
        safety["max_notional_per_order"] = normalized["quote_notional"]

    short_run_id = _text(source_run_id)[-12:] or "unknown"
    source_automation = dict(normalized["automation"])
    retry_automation = {
        "enabled": bool(source_automation.get("enabled", True)),
        "repeat_every_hours": source_automation.get("repeat_every_hours"),
        "max_runs": 1 if source_automation.get("repeat_every_hours") else None,
    }
    config = {
        "version": 1,
        "campaign_id": f"{normalized['campaign_id']}-retry-{short_run_id}",
        "campaign_name": (
            f"{normalized.get('campaign_name') or normalized['campaign_id']} retry "
            f"{short_run_id}"
        ),
        "side": normalized["side"],
        "quote_notional": normalized["quote_notional"],
        "max_products": retry_count,
        "order_type": normalized["order_type"],
        "limit_price_offset_bps": normalized["limit_price_offset_bps"],
        "automation": retry_automation,
        "product_scope": {
            **dict(normalized["product_scope"]),
            "allow_products": retryable_product_ids,
        },
        "safety_policy": safety,
        "inventory_policy": dict(normalized["inventory_policy"]),
        "cost_basis_authority": dict(normalized["cost_basis_authority"]),
        "live_approval": dict(normalized["live_approval"]),
        "audit": dict(normalized["audit"]),
    }
    return normalize_spot_campaign_config(config)


def build_spot_campaign_retry_plan(
    *,
    config: Mapping[str, Any],
    sweep_records: Iterable[Mapping[str, Any]],
    run_id: str | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a targeted retry config for not-submitted products from a partial run."""
    timestamp = generated_at or datetime.now(timezone.utc)
    normalized = normalize_spot_campaign_config(config)
    runs = _matching_sweep_runs_for_campaign(
        config=normalized,
        sweep_records=sweep_records,
        run_id=run_id,
    )
    failures: list[dict[str, Any]] = []
    if not runs:
        return {
            "generated_at": timestamp.isoformat(),
            "campaign_id": normalized["campaign_id"],
            "sweep_config_id": normalized["sweep_config_id"],
            "source_run_id": run_id,
            "source_run_status": None,
            "retry_status": SpotCampaignStatus.BLOCKED.value,
            "failures": [{
                "code": "source_run_not_found",
                "reason": "no matching sweep_run record exists for this campaign",
            }],
            "retryable_product_count": 0,
            "retryable_product_ids": [],
            "submitted_or_live_product_ids": [],
            "not_retryable_product_ids": [],
            "order_classes": [],
            "retry_config": None,
            "retry_sweep_config": None,
            "live_coinbase_orders_ran": False,
            "live_order_notional_usdc": "0",
            "total_submitted_notional_usdc": "0",
            "total_executed_notional_usdc": "0",
        }

    source_run = runs[-1]
    execution = source_run.get("execution") or {}
    orders = [
        dict(order)
        for order in execution.get("orders") or []
        if isinstance(order, Mapping)
    ]
    order_classes: list[dict[str, Any]] = []
    retryable_product_ids: list[str] = []
    submitted_or_live_product_ids: list[str] = []
    not_retryable_product_ids: list[str] = []
    for order in orders:
        product_id = _text(order.get("product_id")).upper()
        if not product_id:
            continue
        order_class = _classify_retry_order(order)
        guard_failure = (
            order.get("guard_failure")
            if isinstance(order.get("guard_failure"), Mapping)
            else {}
        )
        order_classes.append({
            "product_id": product_id,
            "class": order_class,
            "status": order.get("status"),
            "exchange_order_id": order.get("exchange_order_id"),
            "submitted_notional_usdc": order.get("submitted_notional_usdc") or "0",
            "executed_notional_usdc": order.get("executed_notional_usdc") or "0",
            "reason": order.get("error") or guard_failure.get("reason"),
        })
        if order_class == SpotCampaignRetryOrderClass.RETRYABLE_NOT_SUBMITTED.value:
            retryable_product_ids.append(product_id)
        elif order_class == SpotCampaignRetryOrderClass.SUBMITTED_OR_LIVE.value:
            submitted_or_live_product_ids.append(product_id)
        else:
            not_retryable_product_ids.append(product_id)

    retryable_product_ids = sorted(set(retryable_product_ids))
    submitted_or_live_product_ids = sorted(set(submitted_or_live_product_ids))
    not_retryable_product_ids = sorted(set(not_retryable_product_ids))
    source_outcome = summarize_sweep_order_statuses(orders) if orders else {}
    source_status = _text(
        source_outcome.get("run_status") or source_run.get("status")
    )
    if source_status == SpotPortfolioSweepRunStatus.COMPLETED.value:
        failures.append({
            "code": "source_run_completed",
            "reason": "completed sweep runs do not need campaign retry configs",
        })
    if not retryable_product_ids:
        failures.append({
            "code": "no_retryable_products",
            "reason": "source run has no not-submitted product orders to retry",
        })

    retry_config = None
    retry_sweep_config = None
    if not failures:
        retry_config = _retry_campaign_config(
            normalized=normalized,
            source_run_id=_text(source_run.get("run_id")),
            retryable_product_ids=retryable_product_ids,
        )
        retry_sweep_config = spot_campaign_config_to_sweep_config(retry_config)

    retry_status = (
        SpotCampaignStatus.READY.value
        if retry_config
        else SpotCampaignStatus.BLOCKED.value
    )
    return {
        "generated_at": timestamp.isoformat(),
        "campaign_id": normalized["campaign_id"],
        "sweep_config_id": normalized["sweep_config_id"],
        "source_run_id": source_run.get("run_id"),
        "source_run_status": source_status,
        "source_started_at": source_run.get("started_at"),
        "source_completed_at": source_run.get("completed_at"),
        "retry_status": retry_status,
        "failures": failures,
        "retryable_product_count": len(retryable_product_ids),
        "retryable_product_ids": retryable_product_ids,
        "submitted_or_live_product_ids": submitted_or_live_product_ids,
        "not_retryable_product_ids": not_retryable_product_ids,
        "order_classes": order_classes,
        "retry_config": retry_config,
        "retry_sweep_config": retry_sweep_config,
        "live_coinbase_orders_ran": False,
        "live_order_notional_usdc": "0",
        "total_submitted_notional_usdc": "0",
        "total_executed_notional_usdc": "0",
    }


def build_spot_campaign_snapshot_record(
    *,
    config: Mapping[str, Any],
    mode: str | SpotCampaignRunMode,
    status: str | SpotCampaignStatus,
    dry_run_matrix: Mapping[str, Any] | None = None,
    release_gate: Mapping[str, Any] | None = None,
    sweep_summary: Mapping[str, Any] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a durable local campaign snapshot record."""
    timestamp = generated_at or datetime.now(timezone.utc)
    normalized = normalize_spot_campaign_config(config)
    mode_value = SpotCampaignRunMode(_text(mode)).value
    status_value = SpotCampaignStatus(_text(status)).value
    sweep_summary = dict(sweep_summary or {})
    submitted = sweep_summary.get("total_submitted_notional_usdc") or "0"
    executed = sweep_summary.get("total_executed_notional_usdc") or "0"
    return {
        "record_type": SpotAuditRecordType.CAMPAIGN_SNAPSHOT.value,
        "generated_at": timestamp.isoformat(),
        "campaign_id": normalized["campaign_id"],
        "sweep_config_id": normalized["sweep_config_id"],
        "mode": mode_value,
        "status": status_value,
        "config": normalized,
        "dry_run": {
            "plan": dict((dry_run_matrix or {}).get("plan") or {}),
            "safety_evaluation": dict(
                (dry_run_matrix or {}).get("safety_evaluation") or {}
            ),
            "automation_due": (dry_run_matrix or {}).get("automation_due"),
            "pnl_snapshot": (dry_run_matrix or {}).get("pnl_snapshot"),
            "cost_basis": (dry_run_matrix or {}).get("cost_basis"),
        },
        "release_gate": dict(release_gate or {}),
        "sweep_summary": sweep_summary,
        "live_coinbase_orders_ran": bool(
            sweep_summary.get("live_coinbase_orders_ran", False)
        ),
        "live_order_notional_usdc": submitted,
        "total_submitted_notional_usdc": submitted,
        "total_executed_notional_usdc": executed,
    }


def append_spot_campaign_snapshot_record(
    state_file: str | Path,
    record: Mapping[str, Any],
) -> None:
    """Append one campaign snapshot to the local JSONL campaign ledger."""
    path = Path(state_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(dict(record), sort_keys=True))
        handle.write("\n")


def load_spot_campaign_snapshot_records(state_file: str | Path) -> list[dict[str, Any]]:
    """Load durable spot campaign snapshot records from a JSONL ledger."""
    path = Path(state_file)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
    return records


def _timestamp_key(record: Mapping[str, Any]) -> float:
    raw = record.get("generated_at") or record.get("started_at") or ""
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _notional_dedupe_key(record: Mapping[str, Any]) -> tuple[str, ...]:
    sweep_summary = record.get("sweep_summary") or {}
    if isinstance(sweep_summary, Mapping):
        run_id = _text(sweep_summary.get("run_id"))
        if run_id:
            return ("sweep_run", run_id)
    return (
        "snapshot",
        _text(record.get("generated_at")),
        _text(record.get("mode")),
    )


def _deduped_notional_records(
    records: Iterable[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    seen: set[tuple[str, ...]] = set()
    deduped: list[Mapping[str, Any]] = []
    for record in records:
        key = _notional_dedupe_key(record)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def _is_campaign_readiness_snapshot(snapshot: Mapping[str, Any]) -> bool:
    mode = _text(snapshot.get("mode"))
    if mode in {
        SpotCampaignRunMode.DRY_RUN.value,
        SpotCampaignRunMode.RELEASE_GATE.value,
    }:
        return True
    dry_run = snapshot.get("dry_run") or {}
    release_gate = snapshot.get("release_gate") or {}
    return bool(
        release_gate
        or dry_run.get("plan")
        or dry_run.get("safety_evaluation")
        or dry_run.get("automation_due")
        or dry_run.get("pnl_snapshot")
        or dry_run.get("cost_basis")
    )


def _is_campaign_live_snapshot(snapshot: Mapping[str, Any]) -> bool:
    return (
        _text(snapshot.get("mode")) == SpotCampaignRunMode.LIVE_CANARY.value
        or bool(snapshot.get("live_coinbase_orders_ran"))
    )


def _latest_matching_snapshot(
    snapshots: Iterable[Mapping[str, Any]],
    predicate: Any,
) -> dict[str, Any] | None:
    for snapshot in reversed(list(snapshots)):
        if predicate(snapshot):
            return dict(snapshot)
    return None


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _build_campaign_recovery_summary(
    recovery_plan: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not recovery_plan:
        return {
            "status": None,
            "planned_reconciliation_run_count": 0,
            "planned_backfill_order_count": 0,
            "runs_needing_reconciliation": [],
            "runs_needing_backfill": [],
        }
    planned_reconciliation = _int_value(
        recovery_plan.get("planned_reconciliation_run_count")
    )
    planned_backfill = _int_value(recovery_plan.get("planned_backfill_order_count"))
    return {
        "status": (
            SpotSweepRecoveryGateStatus.FAILED.value
            if planned_reconciliation or planned_backfill
            else SpotSweepRecoveryGateStatus.PASSED.value
        ),
        "planned_reconciliation_run_count": planned_reconciliation,
        "planned_backfill_order_count": planned_backfill,
        "runs_needing_reconciliation": list(
            recovery_plan.get("runs_needing_reconciliation") or []
        ),
        "runs_needing_backfill": list(
            recovery_plan.get("runs_needing_backfill") or []
        ),
    }


def _build_campaign_operator_summary(
    *,
    latest_snapshot: Mapping[str, Any] | None,
    latest_readiness_snapshot: Mapping[str, Any] | None,
    latest_live_snapshot: Mapping[str, Any] | None,
    total_submitted: Decimal,
    total_executed: Decimal,
) -> dict[str, Any]:
    readiness_snapshot = dict(latest_readiness_snapshot or latest_snapshot or {})
    latest_snapshot = dict(latest_snapshot or {})
    live_snapshot = dict(latest_live_snapshot or {})
    dry_run = readiness_snapshot.get("dry_run") or {}
    plan = dry_run.get("plan") or {}
    safety = dry_run.get("safety_evaluation") or {}
    automation_due = dry_run.get("automation_due") or {}
    release_gate = readiness_snapshot.get("release_gate") or {}
    operation_lock = release_gate.get("operation_lock_status") or {}
    recovery = _build_campaign_recovery_summary(
        release_gate.get("recovery_plan") or None
    )
    pnl_snapshot = dry_run.get("pnl_snapshot") or {}
    portfolio = pnl_snapshot.get("portfolio") or {}
    sweep_summary = live_snapshot.get("sweep_summary") or latest_snapshot.get(
        "sweep_summary"
    ) or {}
    failures = release_gate.get("failures") or []
    warnings = release_gate.get("warnings") or []
    readiness_status = (
        release_gate.get("status")
        or readiness_snapshot.get("status")
        or latest_snapshot.get("status")
    )
    blocked = bool(
        readiness_status == SpotCampaignStatus.BLOCKED.value
        or release_gate.get("gate_status") == SpotCampaignGateStatus.FAILED.value
        or recovery["planned_reconciliation_run_count"]
        or recovery["planned_backfill_order_count"]
    )
    ready = bool(
        readiness_status == SpotCampaignStatus.READY.value
        and not blocked
    )
    return {
        "readiness_status": readiness_status,
        "ready": ready,
        "blocked": blocked,
        "gate_status": release_gate.get("gate_status"),
        "failure_count": len(failures) if isinstance(failures, list) else 0,
        "warning_count": len(warnings) if isinstance(warnings, list) else 0,
        "automation_decision": automation_due.get("decision"),
        "next_run_at": automation_due.get("next_run_at"),
        "automation_due_at": automation_due.get("due_at"),
        "run_count": automation_due.get("run_count"),
        "max_runs": automation_due.get("max_runs"),
        "operation_lock_status": operation_lock.get("status"),
        "operation_lock_exists": bool(operation_lock.get("exists", False)),
        "operation_lock_stale": bool(operation_lock.get("stale", False)),
        "recovery_status": recovery["status"],
        "planned_reconciliation_run_count": recovery[
            "planned_reconciliation_run_count"
        ],
        "planned_backfill_order_count": recovery[
            "planned_backfill_order_count"
        ],
        "planned_order_count": _int_value(plan.get("planned_count")),
        "planned_skip_count": _int_value(plan.get("skipped_count")),
        "planned_skip_counts": dict(plan.get("skip_counts") or {}),
        "safety_decision": safety.get("decision"),
        "estimated_planned_quote_notional": (
            plan.get("estimated_planned_quote_notional") or "0"
        ),
        "latest_live_run_id": sweep_summary.get("run_id"),
        "latest_live_status": sweep_summary.get("status"),
        "latest_live_recorded_status": sweep_summary.get("recorded_status"),
        "latest_live_skipped_order_count": _int_value(
            sweep_summary.get("skipped_order_count")
        ),
        "total_submitted_notional_usdc": _format_decimal(total_submitted),
        "total_executed_notional_usdc": _format_decimal(total_executed),
        "portfolio_total_pnl": portfolio.get("total_pnl"),
        "portfolio_mark_value": portfolio.get("mark_value"),
        "portfolio_fees": portfolio.get("fees"),
        "latest_snapshot_generated_at": latest_snapshot.get("generated_at"),
        "latest_readiness_generated_at": readiness_snapshot.get("generated_at"),
        "latest_live_generated_at": live_snapshot.get("generated_at"),
    }


def build_spot_campaign_operator_status(
    *,
    records: Iterable[Mapping[str, Any]],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Summarize durable campaign snapshots for dashboard/operator status."""
    timestamp = generated_at or datetime.now(timezone.utc)
    snapshots = [
        dict(record)
        for record in records
        if record.get("record_type") == SpotAuditRecordType.CAMPAIGN_SNAPSHOT.value
    ]
    snapshots.sort(key=_timestamp_key)
    by_campaign: dict[str, list[dict[str, Any]]] = {}
    for snapshot in snapshots:
        campaign_id = _text(snapshot.get("campaign_id")) or "unknown"
        by_campaign.setdefault(campaign_id, []).append(snapshot)

    campaigns: list[dict[str, Any]] = []
    total_submitted = Decimal("0")
    total_executed = Decimal("0")
    for campaign_id, campaign_records in sorted(by_campaign.items()):
        latest = campaign_records[-1]
        notional_records = _deduped_notional_records(campaign_records)
        submitted = sum(
            (
                _decimal(record.get("total_submitted_notional_usdc"))
                for record in notional_records
            ),
            Decimal("0"),
        )
        executed = sum(
            (
                _decimal(record.get("total_executed_notional_usdc"))
                for record in notional_records
            ),
            Decimal("0"),
        )
        total_submitted += submitted
        total_executed += executed
        latest_readiness = _latest_matching_snapshot(
            campaign_records,
            _is_campaign_readiness_snapshot,
        )
        latest_live = _latest_matching_snapshot(
            campaign_records,
            _is_campaign_live_snapshot,
        )
        campaigns.append({
            "campaign_id": campaign_id,
            "sweep_config_id": latest.get("sweep_config_id"),
            "snapshot_count": len(campaign_records),
            "notional_snapshot_count": len(notional_records),
            "latest_snapshot": latest,
            "latest_readiness_snapshot": latest_readiness,
            "latest_live_snapshot": latest_live,
            "operator_summary": _build_campaign_operator_summary(
                latest_snapshot=latest,
                latest_readiness_snapshot=latest_readiness,
                latest_live_snapshot=latest_live,
                total_submitted=submitted,
                total_executed=executed,
            ),
            "latest_status": latest.get("status"),
            "latest_mode": latest.get("mode"),
            "latest_generated_at": latest.get("generated_at"),
            "total_submitted_notional_usdc": _format_decimal(submitted),
            "total_executed_notional_usdc": _format_decimal(executed),
        })

    latest_snapshot = snapshots[-1] if snapshots else None
    latest_readiness_snapshot = _latest_matching_snapshot(
        snapshots,
        _is_campaign_readiness_snapshot,
    )
    latest_live_snapshot = _latest_matching_snapshot(
        snapshots,
        _is_campaign_live_snapshot,
    )
    return {
        "generated_at": timestamp.isoformat(),
        "campaign_count": len(campaigns),
        "snapshot_count": len(snapshots),
        "total_submitted_notional_usdc": _format_decimal(total_submitted),
        "total_executed_notional_usdc": _format_decimal(total_executed),
        "latest_snapshot": latest_snapshot,
        "latest_readiness_snapshot": latest_readiness_snapshot,
        "latest_live_snapshot": latest_live_snapshot,
        "operator_summary": _build_campaign_operator_summary(
            latest_snapshot=latest_snapshot,
            latest_readiness_snapshot=latest_readiness_snapshot,
            latest_live_snapshot=latest_live_snapshot,
            total_submitted=total_submitted,
            total_executed=total_executed,
        ),
        "campaigns": campaigns,
        "live_coinbase_orders_ran": bool(total_submitted > 0),
        "live_order_notional_usdc": _format_decimal(total_submitted),
    }
