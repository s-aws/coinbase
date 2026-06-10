"""Read-only campaign orchestration for USDC spot portfolio sweeps.

Campaigns are an operator layer over the existing USDC sweep planner and live
runner. This module validates campaign config, builds dry-run matrices, records
durable P/L snapshots, and summarizes status without submitting Coinbase orders.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping

from business.spot_portfolio_sweep import (
    apply_coinbase_average_cost_authority_gate,
    build_spot_inventory_coverage_report,
    build_spot_portfolio_pnl_report,
    build_sweep_run_record,
    build_sweep_config_id,
    build_sweep_plan_explain,
    build_usdc_portfolio_sweep_plan,
    evaluate_sweep_automation_due,
    evaluate_sweep_safety_policy,
    summarize_sweep_order_statuses,
)
from core.enums import (
    InventoryAuthorityStatus,
    InventoryLotSource,
    OrderSide,
    SpotAuditRecordType,
    SpotCampaignGateStatus,
    SpotCampaignProductSelection,
    SpotCampaignRetryOrderClass,
    SpotCampaignRunMode,
    SpotCampaignSellAuthorityProfile,
    SpotCampaignStatus,
    SpotCampaignTemplateProfile,
    SpotSellAuthorityAllowlistFreshness,
    SpotCostBasisGapStatus,
    SpotCostBasisSource,
    SpotFeatureInventoryRetentionPolicy,
    SpotOperationLockStatus,
    SpotPortfolioSweepAutomationDecision,
    SpotPortfolioSweepExecutionStatus,
    SpotPortfolioSweepItemStatus,
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
DEFAULT_SELL_AUTHORITY_ALLOWLIST_MAX_AGE_SECONDS = 300


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
        "sell_authority_profile": config.get("sell_authority_profile"),
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
    raw_sell_authority_profile = _text(
        raw.get("sell_authority_profile")
        or safety.get("sell_authority_profile")
        or cost_basis_authority.get("sell_authority_profile")
    )
    sell_authority_profile = None
    if raw_sell_authority_profile:
        try:
            sell_authority_profile = SpotCampaignSellAuthorityProfile(
                raw_sell_authority_profile
            ).value
        except ValueError as exc:
            raise ValueError("unsupported sell_authority_profile") from exc
        if side != OrderSide.SELL.value:
            raise ValueError("sell_authority_profile is only valid for SELL campaigns")
        safety["require_known_profitable_inventory"] = True
        if (
            sell_authority_profile
            == SpotCampaignSellAuthorityProfile.FILL_LEDGER_STRICT.value
        ):
            safety["allow_coinbase_average_cost_basis"] = False
            cost_basis_authority["allowed_sources"] = [
                SpotCostBasisSource.FILL_LEDGER.value,
                SpotCostBasisSource.IMPORTED_BASELINE.value,
            ]
        elif (
            sell_authority_profile
            == SpotCampaignSellAuthorityProfile.COINBASE_AVERAGE_COST_BUFFERED.value
        ):
            safety["allow_coinbase_average_cost_basis"] = True
            existing_sources = _string_list(
                cost_basis_authority.get(
                    "allowed_sources",
                    [
                        SpotCostBasisSource.FILL_LEDGER.value,
                        SpotCostBasisSource.IMPORTED_BASELINE.value,
                    ],
                ),
                field_name="cost_basis_authority.allowed_sources",
            )
            cost_basis_authority["allowed_sources"] = _dedupe_strings([
                *existing_sources,
                SpotCostBasisSource.COINBASE_AVERAGE_COST.value,
            ])
            cost_basis_authority.setdefault(
                "coinbase_average_cost_profit_buffer_pct",
                "0.5",
            )
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
        "sell_authority_profile": sell_authority_profile,
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


def build_spot_campaign_config_template(
    *,
    profile: str | SpotCampaignTemplateProfile,
    campaign_name: str | None = None,
) -> dict[str, Any]:
    """Build a canonical versioned campaign config template."""
    try:
        profile_value = SpotCampaignTemplateProfile(_text(profile)).value
    except ValueError as exc:
        raise ValueError("unsupported spot campaign template profile") from exc

    is_sell = profile_value in {
        SpotCampaignTemplateProfile.SELL_CANARY.value,
        SpotCampaignTemplateProfile.SELL_ALL_USDC.value,
    }
    is_canary = profile_value in {
        SpotCampaignTemplateProfile.BUY_CANARY.value,
        SpotCampaignTemplateProfile.SELL_CANARY.value,
    }
    max_products = 5 if is_canary else None
    max_planned_orders = 5 if is_canary else 500
    max_total_notional = "5" if is_canary else "500"
    side = OrderSide.SELL.value if is_sell else OrderSide.BUY.value
    template: dict[str, Any] = {
        "version": 1,
        "campaign_name": campaign_name or f"spot_{profile_value}_campaign",
        "side": side,
        "quote_notional": "1",
        "max_products": max_products,
        "order_type": SpotPortfolioSweepOrderType.MARKET_IOC.value,
        "automation": {
            "enabled": True,
            "repeat_every_hours": "6",
            "max_runs": 2 if is_canary else 4,
        },
        "product_scope": {
            "quote_currency": QUOTE_CURRENCY,
            "us_customer_available": True,
            "selection_rule": (
                SpotCampaignProductSelection
                .ALL_COINBASE_USDC_SPOT_US_CUSTOMER_AVAILABLE
                .value
            ),
        },
        "safety_policy": {
            "max_total_notional_per_run": max_total_notional,
            "max_notional_per_order": "1",
            "max_planned_orders": max_planned_orders,
        },
        "inventory_policy": {
            "retention": SpotFeatureInventoryRetentionPolicy.RETAIN.value,
        },
        "cost_basis_authority": {
            "allowed_sources": [
                SpotCostBasisSource.FILL_LEDGER.value,
                SpotCostBasisSource.IMPORTED_BASELINE.value,
            ],
        },
    }
    if is_sell:
        template["sell_authority_profile"] = (
            SpotCampaignSellAuthorityProfile.FILL_LEDGER_STRICT.value
            if is_canary
            else SpotCampaignSellAuthorityProfile.COINBASE_AVERAGE_COST_BUFFERED.value
        )
    return normalize_spot_campaign_config(template)


def apply_spot_campaign_sell_authority_profile(
    *,
    config: Mapping[str, Any],
    profile: str | SpotCampaignSellAuthorityProfile,
) -> dict[str, Any]:
    """Return a normalized SELL campaign config with an authority profile applied."""
    profile_value = SpotCampaignSellAuthorityProfile(_text(profile)).value
    updated = dict(config)
    updated["sell_authority_profile"] = profile_value
    return normalize_spot_campaign_config(updated)


def build_spot_campaign_config_validation_report(
    *,
    config: Mapping[str, Any],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Validate config shape and operator-critical safety settings without Coinbase calls."""
    timestamp = generated_at or datetime.now(timezone.utc)
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    normalized: dict[str, Any] | None = None
    try:
        normalized = normalize_spot_campaign_config(config)
    except ValueError as exc:
        errors.append({
            "code": "invalid_config",
            "reason": str(exc),
        })

    if normalized is not None:
        safety = normalized["safety_policy"]
        required_safety_fields = (
            "max_total_notional_per_run",
            "max_notional_per_order",
            "max_planned_orders",
        )
        for field_name in required_safety_fields:
            if safety.get(field_name) in (None, ""):
                errors.append({
                    "code": "missing_safety_cap",
                    "field": f"safety_policy.{field_name}",
                    "reason": "campaign configs must declare explicit run/order caps",
                })
        if (
            safety.get("max_notional_per_order") is not None
            and _decimal(safety.get("max_notional_per_order"))
            < _decimal(normalized["quote_notional"])
        ):
            errors.append({
                "code": "max_notional_per_order_below_quote_notional",
                "reason": "per-order cap is lower than requested quote_notional",
            })
        max_total = _decimal(safety.get("max_total_notional_per_run"))
        max_planned = safety.get("max_planned_orders")
        if max_total > 0 and max_planned:
            theoretical_notional = _decimal(normalized["quote_notional"]) * Decimal(
                int(max_planned)
            )
            if max_total < theoretical_notional:
                warnings.append({
                    "code": "max_total_below_theoretical_full_run",
                    "configured": _format_decimal(max_total),
                    "theoretical": _format_decimal(theoretical_notional),
                    "reason": (
                        "total cap may intentionally stop a full planned-order "
                        "run; dry-run matrix will show the actual result"
                    ),
                })
        if normalized["side"] == OrderSide.SELL.value:
            if not safety.get("require_known_profitable_inventory"):
                errors.append({
                    "code": "sell_authority_required",
                    "reason": "SELL campaigns must require profitable inventory authority",
                })
            if (
                safety.get("allow_coinbase_average_cost_basis")
                and normalized.get("sell_authority_profile")
                != SpotCampaignSellAuthorityProfile.COINBASE_AVERAGE_COST_BUFFERED.value
            ):
                warnings.append({
                    "code": "average_cost_without_named_profile",
                    "reason": (
                        "Coinbase average cost is enabled; using the named "
                        "buffered profile makes the authority policy explicit"
                    ),
                })
        if normalized["automation"]["enabled"]:
            warnings.append({
                "code": "automation_live_runner_required",
                "reason": (
                    "campaign automation is descriptive here; live scheduling "
                    "still uses the sweep runner approval gate"
                ),
            })

    status = (
        SpotCampaignStatus.READY.value
        if not errors
        else SpotCampaignStatus.INCOMPLETE.value
    )
    return {
        "generated_at": timestamp.isoformat(),
        "mode": SpotCampaignRunMode.VALIDATION.value,
        "status": status,
        "phase_90_ready": not errors,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "config": normalized,
        "live_coinbase_orders_ran": False,
        "live_order_notional_usdc": "0",
        "total_submitted_notional_usdc": "0",
        "total_executed_notional_usdc": "0",
    }


def _matrix_product_statuses(matrix: Mapping[str, Any]) -> dict[str, str]:
    plan = matrix.get("plan") or {}
    items = plan.get("items") or []
    statuses: dict[str, str] = {}
    for item in items:
        if not isinstance(item, Mapping):
            continue
        product_id = _text(item.get("product_id")).upper()
        if product_id:
            statuses[product_id] = _text(item.get("status"))
    return statuses


def build_spot_campaign_dry_run_diff(
    *,
    baseline_matrix: Mapping[str, Any],
    current_matrix: Mapping[str, Any],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Compare two campaign dry-run matrices without calling Coinbase."""
    timestamp = generated_at or datetime.now(timezone.utc)
    baseline_plan = baseline_matrix.get("plan") or {}
    current_plan = current_matrix.get("plan") or {}
    baseline_statuses = _matrix_product_statuses(baseline_matrix)
    current_statuses = _matrix_product_statuses(current_matrix)
    baseline_products = set(baseline_statuses)
    current_products = set(current_statuses)
    changed_products = []
    for product_id in sorted(baseline_products & current_products):
        if baseline_statuses[product_id] != current_statuses[product_id]:
            changed_products.append({
                "product_id": product_id,
                "baseline_status": baseline_statuses[product_id],
                "current_status": current_statuses[product_id],
            })
    baseline_pnl = (baseline_matrix.get("pnl_snapshot") or {}).get("portfolio") or {}
    current_pnl = (current_matrix.get("pnl_snapshot") or {}).get("portfolio") or {}
    return {
        "generated_at": timestamp.isoformat(),
        "mode": SpotCampaignRunMode.DRY_RUN_DIFF.value,
        "status": SpotCampaignStatus.RECORDED.value,
        "baseline_campaign_id": baseline_matrix.get("campaign_id"),
        "current_campaign_id": current_matrix.get("campaign_id"),
        "baseline_sweep_config_id": baseline_matrix.get("sweep_config_id"),
        "current_sweep_config_id": current_matrix.get("sweep_config_id"),
        "planned_count_delta": (
            _int_value(current_plan.get("planned_count"))
            - _int_value(baseline_plan.get("planned_count"))
        ),
        "skipped_count_delta": (
            _int_value(current_plan.get("skipped_count"))
            - _int_value(baseline_plan.get("skipped_count"))
        ),
        "estimated_notional_delta_usdc": _format_decimal(
            _decimal(current_plan.get("estimated_planned_quote_notional"))
            - _decimal(baseline_plan.get("estimated_planned_quote_notional"))
        ),
        "safety_decision_changed": (
            (baseline_matrix.get("safety_evaluation") or {}).get("decision")
            != (current_matrix.get("safety_evaluation") or {}).get("decision")
        ),
        "added_products": sorted(current_products - baseline_products),
        "removed_products": sorted(baseline_products - current_products),
        "changed_products": changed_products,
        "baseline_pnl_total": baseline_pnl.get("total_pnl"),
        "current_pnl_total": current_pnl.get("total_pnl"),
        "pnl_total_delta": _format_decimal(
            _decimal(current_pnl.get("total_pnl"))
            - _decimal(baseline_pnl.get("total_pnl"))
        ),
        "live_coinbase_orders_ran": False,
        "live_order_notional_usdc": "0",
        "total_submitted_notional_usdc": "0",
        "total_executed_notional_usdc": "0",
    }


def build_spot_campaign_scheduler_status(
    *,
    config: Mapping[str, Any],
    sweep_records: Iterable[Mapping[str, Any]],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Report recurring campaign due state without placing orders."""
    timestamp = generated_at or datetime.now(timezone.utc)
    normalized = normalize_spot_campaign_config(config)
    automation = normalized["automation"]
    if not automation["enabled"]:
        decision = {
            "decision": SpotPortfolioSweepAutomationDecision.DISABLED.value,
            "reason": "campaign automation is disabled",
            "attempt_count": 0,
            "max_runs": automation.get("max_runs"),
            "next_run_at": None,
        }
    else:
        decision = evaluate_sweep_automation_due(
            config_id=normalized["sweep_config_id"],
            repeat_every_hours=automation["repeat_every_hours"],
            max_runs=int(automation["max_runs"]),
            records=sweep_records,
            now=timestamp,
        )
    return {
        "generated_at": timestamp.isoformat(),
        "mode": SpotCampaignRunMode.SCHEDULER_STATUS.value,
        "status": (
            SpotCampaignStatus.READY.value
            if decision.get("decision") == SpotPortfolioSweepAutomationDecision.DUE.value
            else SpotCampaignStatus.BLOCKED.value
        ),
        "campaign_id": normalized["campaign_id"],
        "sweep_config_id": normalized["sweep_config_id"],
        "automation": dict(automation),
        "scheduler_decision": decision,
        "live_execution_due": (
            decision.get("decision") == SpotPortfolioSweepAutomationDecision.DUE.value
        ),
        "live_coinbase_orders_ran": False,
        "live_order_notional_usdc": "0",
        "total_submitted_notional_usdc": "0",
        "total_executed_notional_usdc": "0",
    }


def build_spot_campaign_run_index(
    *,
    campaign_records: Iterable[Mapping[str, Any]],
    sweep_records: Iterable[Mapping[str, Any]],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a durable local index of campaign snapshots and matching sweep runs."""
    timestamp = generated_at or datetime.now(timezone.utc)
    records = [
        dict(record)
        for record in campaign_records
        if record.get("record_type") == SpotAuditRecordType.CAMPAIGN_SNAPSHOT.value
    ]
    records.sort(key=_timestamp_key)
    operator_status = build_spot_campaign_operator_status(records=records)
    by_sweep_config: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        sweep_config_id = _text(record.get("sweep_config_id"))
        if sweep_config_id:
            by_sweep_config.setdefault(sweep_config_id, [])
    for record in sweep_records:
        if record.get("record_type") != "sweep_run":
            continue
        sweep_config_id = _text(record.get("config_id"))
        if sweep_config_id in by_sweep_config:
            by_sweep_config[sweep_config_id].append(dict(record))
    campaigns: list[dict[str, Any]] = []
    for campaign in operator_status.get("campaigns") or []:
        sweep_config_id = _text(campaign.get("sweep_config_id"))
        runs = sorted(by_sweep_config.get(sweep_config_id, []), key=_timestamp_key)
        recorded_run_ids = {
            _text((record.get("sweep_summary") or {}).get("run_id"))
            for record in records
            if _text(record.get("campaign_id")) == campaign.get("campaign_id")
        }
        run_rows = []
        for run in runs:
            execution = run.get("execution") or {}
            run_id = _text(run.get("run_id"))
            run_rows.append({
                "run_id": run_id,
                "status": run.get("status"),
                "started_at": run.get("started_at"),
                "completed_at": run.get("completed_at"),
                "recorded_in_campaign_ledger": run_id in recorded_run_ids,
                "live_coinbase_orders_ran": bool(
                    execution.get("live_coinbase_orders_ran", False)
                ),
                "total_submitted_notional_usdc": (
                    execution.get("total_submitted_notional_usdc") or "0"
                ),
                "total_executed_notional_usdc": (
                    execution.get("total_executed_notional_usdc") or "0"
                ),
            })
        campaigns.append({
            "campaign_id": campaign.get("campaign_id"),
            "sweep_config_id": sweep_config_id,
            "snapshot_count": campaign.get("snapshot_count"),
            "sweep_run_count": len(run_rows),
            "unrecorded_sweep_run_count": len([
                row for row in run_rows if not row["recorded_in_campaign_ledger"]
            ]),
            "latest_status": campaign.get("latest_status"),
            "latest_mode": campaign.get("latest_mode"),
            "total_submitted_notional_usdc": (
                campaign.get("total_submitted_notional_usdc") or "0"
            ),
            "total_executed_notional_usdc": (
                campaign.get("total_executed_notional_usdc") or "0"
            ),
            "runs": run_rows,
        })
    return {
        "generated_at": timestamp.isoformat(),
        "mode": SpotCampaignRunMode.RUN_INDEX.value,
        "status": SpotCampaignStatus.RECORDED.value,
        "campaign_count": len(campaigns),
        "snapshot_count": len(records),
        "total_submitted_notional_usdc": (
            operator_status.get("total_submitted_notional_usdc") or "0"
        ),
        "total_executed_notional_usdc": (
            operator_status.get("total_executed_notional_usdc") or "0"
        ),
        "campaigns": campaigns,
        "live_coinbase_orders_ran": False,
        "live_order_notional_usdc": "0",
    }


def build_spot_campaign_pnl_checkpoints(
    *,
    records: Iterable[Mapping[str, Any]],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build P/L checkpoint deltas from durable campaign snapshots."""
    timestamp = generated_at or datetime.now(timezone.utc)
    snapshots = [
        dict(record)
        for record in records
        if record.get("record_type") == SpotAuditRecordType.CAMPAIGN_SNAPSHOT.value
    ]
    snapshots.sort(key=_timestamp_key)
    checkpoints_by_campaign: dict[str, list[dict[str, Any]]] = {}
    previous_totals: dict[str, Decimal] = {}
    for snapshot in snapshots:
        campaign_id = _text(snapshot.get("campaign_id")) or "unknown"
        pnl_snapshot = (snapshot.get("dry_run") or {}).get("pnl_snapshot") or {}
        portfolio = pnl_snapshot.get("portfolio") or {}
        if not portfolio:
            continue
        total_pnl = _decimal(portfolio.get("total_pnl"))
        previous = previous_totals.get(campaign_id)
        previous_totals[campaign_id] = total_pnl
        checkpoints_by_campaign.setdefault(campaign_id, []).append({
            "generated_at": snapshot.get("generated_at"),
            "mode": snapshot.get("mode"),
            "status": snapshot.get("status"),
            "total_pnl": portfolio.get("total_pnl"),
            "mark_value": portfolio.get("mark_value"),
            "fees": portfolio.get("fees"),
            "delta_total_pnl": (
                None
                if previous is None
                else _format_decimal(total_pnl - previous)
            ),
            "since_last_purchase_pnl": portfolio.get("since_last_purchase_pnl"),
            "average_cost_total_pnl": (
                (pnl_snapshot.get("average_cost_portfolio") or {}).get("total_pnl")
            ),
        })
    campaigns = [
        {
            "campaign_id": campaign_id,
            "checkpoint_count": len(checkpoints),
            "latest_checkpoint": checkpoints[-1] if checkpoints else None,
            "checkpoints": checkpoints,
        }
        for campaign_id, checkpoints in sorted(checkpoints_by_campaign.items())
    ]
    return {
        "generated_at": timestamp.isoformat(),
        "mode": SpotCampaignRunMode.PNL_CHECKPOINT.value,
        "status": SpotCampaignStatus.RECORDED.value,
        "campaign_count": len(campaigns),
        "checkpoint_count": sum(
            int(campaign["checkpoint_count"]) for campaign in campaigns
        ),
        "campaigns": campaigns,
        "live_coinbase_orders_ran": False,
        "live_order_notional_usdc": "0",
        "total_submitted_notional_usdc": "0",
        "total_executed_notional_usdc": "0",
    }


def build_spot_campaign_ledger_cleanup_plan(
    *,
    campaign_records: Iterable[Mapping[str, Any]],
    sweep_records: Iterable[Mapping[str, Any]],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Plan local campaign-ledger recording for unrecorded sweep runs."""
    timestamp = generated_at or datetime.now(timezone.utc)
    run_index = build_spot_campaign_run_index(
        campaign_records=campaign_records,
        sweep_records=sweep_records,
        generated_at=timestamp,
    )
    recordable_runs: list[dict[str, Any]] = []
    ignore_candidates: list[dict[str, Any]] = []
    for campaign in run_index.get("campaigns") or []:
        campaign_id = _text(campaign.get("campaign_id"))
        sweep_config_id = _text(campaign.get("sweep_config_id"))
        for run in campaign.get("runs") or []:
            if run.get("recorded_in_campaign_ledger"):
                continue
            row = {
                "campaign_id": campaign_id,
                "sweep_config_id": sweep_config_id,
                "run_id": run.get("run_id"),
                "status": run.get("status"),
                "live_coinbase_orders_ran": bool(
                    run.get("live_coinbase_orders_ran", False)
                ),
                "total_submitted_notional_usdc": (
                    run.get("total_submitted_notional_usdc") or "0"
                ),
                "total_executed_notional_usdc": (
                    run.get("total_executed_notional_usdc") or "0"
                ),
            }
            has_notional = (
                _decimal(row["total_submitted_notional_usdc"]) > 0
                or _decimal(row["total_executed_notional_usdc"]) > 0
            )
            if row["live_coinbase_orders_ran"] or has_notional:
                recordable_runs.append({
                    **row,
                    "planned_action": "record_latest_matching_sweep_run",
                    "reason": (
                        "unrecorded sweep run has live/order notional evidence"
                    ),
                })
            else:
                ignore_candidates.append({
                    **row,
                    "planned_action": "ignore_or_document_legacy_no_order_run",
                    "reason": (
                        "unrecorded sweep run has no live order or notional evidence"
                    ),
                })

    status = (
        SpotCampaignStatus.READY.value
        if recordable_runs or ignore_candidates
        else SpotCampaignStatus.RECORDED.value
    )
    return {
        "generated_at": timestamp.isoformat(),
        "mode": SpotCampaignRunMode.LEDGER_CLEANUP_PLAN.value,
        "status": status,
        "campaign_count": run_index.get("campaign_count", 0),
        "unrecorded_sweep_run_count": (
            len(recordable_runs) + len(ignore_candidates)
        ),
        "planned_record_count": len(recordable_runs),
        "planned_ignore_count": len(ignore_candidates),
        "recordable_runs": recordable_runs,
        "ignore_candidates": ignore_candidates,
        "run_index": run_index,
        "live_coinbase_orders_ran": False,
        "live_order_notional_usdc": "0",
        "total_submitted_notional_usdc": "0",
        "total_executed_notional_usdc": "0",
    }


def _allowlist_products(allowlist: Mapping[str, Any]) -> list[str]:
    products = allowlist.get("allow_products") or []
    if not products and isinstance(allowlist.get("allowlist_rows"), list):
        products = [
            row.get("product_id")
            for row in allowlist.get("allowlist_rows") or []
            if isinstance(row, Mapping)
        ]
    return sorted({
        _text(product).upper()
        for product in products
        if _text(product)
    })


def build_spot_campaign_sell_authority_drift_report(
    *,
    previous_allowlist: Mapping[str, Any],
    current_allowlist: Mapping[str, Any],
    release_gate: Mapping[str, Any] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Compare two SELL authority allowlists for market/account drift."""
    timestamp = generated_at or datetime.now(timezone.utc)
    previous_products = set(_allowlist_products(previous_allowlist))
    current_products = set(_allowlist_products(current_allowlist))
    removed_products = sorted(previous_products - current_products)
    added_products = sorted(current_products - previous_products)
    common_products = sorted(previous_products & current_products)

    failures: list[dict[str, Any]] = []
    if removed_products:
        failures.append({
            "code": "allowlist_products_removed",
            "reason": (
                "one or more products left the SELL authority allowlist; "
                "regenerate the allowlist and rerun release validation"
            ),
            "product_count": len(removed_products),
            "products": removed_products,
        })
    if (
        release_gate
        and release_gate.get("gate_status") == SpotCampaignGateStatus.FAILED.value
    ):
        failures.append({
            "code": "release_gate_failed",
            "reason": "current release gate failed for the compared allowlist",
            "release_failures": list(release_gate.get("failures") or []),
        })

    gate_status = (
        SpotCampaignGateStatus.FAILED.value
        if failures
        else SpotCampaignGateStatus.PASSED.value
    )
    return {
        "generated_at": timestamp.isoformat(),
        "mode": SpotCampaignRunMode.SELL_AUTHORITY_DRIFT.value,
        "status": (
            SpotCampaignStatus.BLOCKED.value
            if failures
            else SpotCampaignStatus.READY.value
        ),
        "gate_status": gate_status,
        "previous_generated_at": (
            previous_allowlist.get("generated_at")
            or (previous_allowlist.get("allowlist_metadata") or {}).get("generated_at")
        ),
        "current_generated_at": (
            current_allowlist.get("generated_at")
            or (current_allowlist.get("allowlist_metadata") or {}).get("generated_at")
        ),
        "previous_allowlist_count": len(previous_products),
        "current_allowlist_count": len(current_products),
        "removed_count": len(removed_products),
        "added_count": len(added_products),
        "common_count": len(common_products),
        "removed_products": removed_products,
        "added_products": added_products,
        "common_products": common_products,
        "failures": failures,
        "operator_action": (
            "regenerate SELL authority allowlist immediately before live approval"
            if failures
            else "current allowlist comparison has no product-removal drift"
        ),
        "release_gate": dict(release_gate or {}),
        "live_coinbase_orders_ran": False,
        "live_order_notional_usdc": "0",
        "total_submitted_notional_usdc": "0",
        "total_executed_notional_usdc": "0",
    }


def _authority_reason_text(row: Mapping[str, Any]) -> str:
    fragments = [
        _text(row.get("authority_reason")),
        _text(row.get("reason")),
        _text(row.get("authority_status")),
    ]
    for violation in row.get("authority_gate_violations") or []:
        if isinstance(violation, Mapping):
            fragments.append(_text(violation.get("reason")))
            fragments.append(_text(violation.get("code")))
    return " ".join(fragment for fragment in fragments if fragment).lower()


def _authority_report_summary(
    *,
    allowlist: Mapping[str, Any],
    profile_name: str,
) -> dict[str, Any]:
    allow_products = _allowlist_products(allowlist)
    blocked_rows = [
        dict(row)
        for row in allowlist.get("blocked_rows") or []
        if isinstance(row, Mapping)
    ]
    skipped_rows = [
        dict(row)
        for row in allowlist.get("skipped_rows") or []
        if isinstance(row, Mapping)
    ]
    stale_or_drift = [
        _text(row.get("product_id")).upper()
        for row in blocked_rows
        if "stale" in _authority_reason_text(row)
        or "drift" in _authority_reason_text(row)
    ]
    reason_counts: dict[str, int] = {}
    for row in blocked_rows:
        reason = (
            _text(row.get("authority_reason"))
            or _text(row.get("reason"))
            or _text(row.get("authority_status"))
            or "missing"
        )
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    return {
        "profile": profile_name,
        "sell_authority_profile": allowlist.get("sell_authority_profile"),
        "generated_at": allowlist.get("generated_at"),
        "status": allowlist.get("status"),
        "allowlist_count": len(allow_products),
        "blocked_count": len(blocked_rows),
        "skipped_count": len(skipped_rows),
        "allow_products": allow_products,
        "authority_source_counts": dict(
            allowlist.get("authority_source_counts") or {}
        ),
        "authority_status_counts": dict(
            allowlist.get("authority_status_counts") or {}
        ),
        "blocked_reason_counts": reason_counts,
        "stale_or_drift_blocked_count": len(set(stale_or_drift)),
        "stale_or_drift_blocked_products": sorted(set(stale_or_drift)),
    }


def build_spot_campaign_sell_authority_operator_report(
    *,
    strict_allowlist: Mapping[str, Any],
    average_cost_allowlist: Mapping[str, Any],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Separate strict fill-ledger and Coinbase average-cost SELL authority."""
    timestamp = generated_at or datetime.now(timezone.utc)
    strict = _authority_report_summary(
        allowlist=strict_allowlist,
        profile_name=SpotCampaignSellAuthorityProfile.FILL_LEDGER_STRICT.value,
    )
    average_cost = _authority_report_summary(
        allowlist=average_cost_allowlist,
        profile_name=(
            SpotCampaignSellAuthorityProfile.COINBASE_AVERAGE_COST_BUFFERED.value
        ),
    )
    strict_products = set(strict["allow_products"])
    average_cost_products = set(average_cost["allow_products"])
    return {
        "generated_at": timestamp.isoformat(),
        "mode": SpotCampaignRunMode.SELL_AUTHORITY_OPERATOR_REPORT.value,
        "status": SpotCampaignStatus.RECORDED.value,
        "strict_fill_ledger": strict,
        "coinbase_average_cost": average_cost,
        "strict_only_products": sorted(strict_products - average_cost_products),
        "average_cost_only_products": sorted(average_cost_products - strict_products),
        "common_products": sorted(strict_products & average_cost_products),
        "strict_count": len(strict_products),
        "average_cost_count": len(average_cost_products),
        "stale_or_drift_blocked_count": (
            strict["stale_or_drift_blocked_count"]
            + average_cost["stale_or_drift_blocked_count"]
        ),
        "risk_notes": [
            "strict fill-ledger authority is preferred for capped SELL canaries",
            (
                "Coinbase average cost is portfolio-level operational authority "
                "and must pass freshness/drift gates before live approval"
            ),
        ],
        "live_coinbase_orders_ran": False,
        "live_order_notional_usdc": "0",
        "total_submitted_notional_usdc": "0",
        "total_executed_notional_usdc": "0",
    }


def _sweep_run_order_rows(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    execution = record.get("execution") or {}
    return [
        dict(order)
        for order in execution.get("orders") or []
        if isinstance(order, Mapping)
    ]


def _is_live_sell_sweep_run(record: Mapping[str, Any]) -> bool:
    if record.get("record_type") != "sweep_run":
        return False
    execution = record.get("execution") or {}
    config = record.get("config") or {}
    if not bool(execution.get("live_coinbase_orders_ran", False)):
        return False
    return _text(config.get("side")).upper() == OrderSide.SELL.value


def _submitted_products_from_sweep_run(record: Mapping[str, Any]) -> list[str]:
    submitted: list[str] = []
    for order in _sweep_run_order_rows(record):
        if _has_submission_evidence(order):
            product_id = _text(order.get("product_id")).upper()
            if product_id:
                submitted.append(product_id)
    return sorted(set(submitted))


def build_spot_campaign_strict_sell_canary_candidates(
    *,
    allowlist: Mapping[str, Any],
    sweep_records: Iterable[Mapping[str, Any]],
    max_candidates: int = 3,
    recent_run_limit: int = 5,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Pick strict SELL canary candidates excluding recently sold products."""
    timestamp = generated_at or datetime.now(timezone.utc)
    if max_candidates <= 0:
        raise ValueError("max_candidates must be greater than 0")
    if recent_run_limit <= 0:
        raise ValueError("recent_run_limit must be greater than 0")

    rows = [
        dict(row)
        for row in allowlist.get("allowlist_rows") or []
        if isinstance(row, Mapping) and _text(row.get("product_id"))
    ]
    if not rows:
        rows = [
            {"product_id": product_id}
            for product_id in _allowlist_products(allowlist)
        ]
    rows.sort(key=lambda row: _text(row.get("product_id")).upper())
    live_sell_runs = [
        dict(record)
        for record in sweep_records
        if _is_live_sell_sweep_run(record)
    ]
    live_sell_runs.sort(key=_timestamp_key, reverse=True)
    recent_runs = live_sell_runs[:recent_run_limit]
    recent_products = sorted({
        product_id
        for record in recent_runs
        for product_id in _submitted_products_from_sweep_run(record)
    })
    recent_product_set = set(recent_products)
    candidates: list[dict[str, Any]] = []
    excluded_recent: list[dict[str, Any]] = []
    for row in rows:
        product_id = _text(row.get("product_id")).upper()
        candidate = {
            "product_id": product_id,
            "authority_source": row.get("authority_source"),
            "authority_status": row.get("authority_status"),
            "estimated_quote_notional": (
                row.get("estimated_quote_notional") or "0"
            ),
            "requested_quote_notional": (
                row.get("requested_quote_notional") or "0"
            ),
        }
        if product_id in recent_product_set:
            excluded_recent.append({
                **candidate,
                "reason": "product appeared in a recent live SELL sweep",
            })
            continue
        if len(candidates) < max_candidates:
            candidates.append(candidate)

    failures: list[dict[str, Any]] = []
    if (
        allowlist.get("sell_authority_profile")
        != SpotCampaignSellAuthorityProfile.FILL_LEDGER_STRICT.value
    ):
        failures.append({
            "code": "not_strict_fill_ledger_allowlist",
            "reason": "candidate rotation expects a strict fill-ledger allowlist",
            "sell_authority_profile": allowlist.get("sell_authority_profile"),
        })
    if not candidates:
        failures.append({
            "code": "no_candidate_products",
            "reason": "no strict allowlist products remain after recent-sell exclusion",
        })
    return {
        "generated_at": timestamp.isoformat(),
        "mode": SpotCampaignRunMode.STRICT_SELL_CANARY_CANDIDATES.value,
        "status": (
            SpotCampaignStatus.BLOCKED.value
            if failures
            else SpotCampaignStatus.READY.value
        ),
        "sell_authority_profile": allowlist.get("sell_authority_profile"),
        "allowlist_generated_at": allowlist.get("generated_at"),
        "allowlist_count": len(rows),
        "max_candidates": max_candidates,
        "recent_run_limit": recent_run_limit,
        "recent_sell_run_ids": [
            _text(record.get("run_id"))
            for record in recent_runs
            if _text(record.get("run_id"))
        ],
        "recent_sell_products": recent_products,
        "excluded_recent_count": len(excluded_recent),
        "excluded_recent_products": excluded_recent,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "failures": failures,
        "proposal_note": (
            "candidate list is read-only; live SELL execution still requires "
            "fresh allowlist validation and explicit approval"
        ),
        "live_coinbase_orders_ran": False,
        "live_order_notional_usdc": "0",
        "total_submitted_notional_usdc": "0",
        "total_executed_notional_usdc": "0",
    }


def _scope_delta_row(
    *,
    scope: str,
    name: str,
    previous_value: Any,
    current_value: Any,
) -> dict[str, Any]:
    previous = _decimal(previous_value)
    current = _decimal(current_value)
    return {
        "scope": scope,
        "name": name,
        "previous": _format_decimal(previous),
        "current": _format_decimal(current),
        "delta": _format_decimal(current - previous),
    }


def _snapshot_pnl_scopes(snapshot: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    pnl_snapshot = (snapshot.get("dry_run") or {}).get("pnl_snapshot") or {}
    scopes: dict[str, dict[str, Any]] = {}
    portfolio = pnl_snapshot.get("portfolio") or {}
    if portfolio:
        scopes["portfolio"] = dict(portfolio)
    average_cost = pnl_snapshot.get("average_cost_portfolio") or {}
    if average_cost:
        scopes["average_cost"] = dict(average_cost)
    product_rows = {}
    for row in pnl_snapshot.get("products") or []:
        if isinstance(row, Mapping):
            product_id = _text(row.get("product_id")).upper()
            if product_id:
                product_rows[product_id] = dict(row)
    if product_rows:
        scopes["product"] = product_rows
    return scopes


def build_spot_campaign_pnl_delta_report(
    *,
    records: Iterable[Mapping[str, Any]],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Compare latest campaign P/L snapshots by durable reporting scope."""
    timestamp = generated_at or datetime.now(timezone.utc)
    snapshots = [
        dict(record)
        for record in records
        if record.get("record_type") == SpotAuditRecordType.CAMPAIGN_SNAPSHOT.value
    ]
    snapshots.sort(key=_timestamp_key)
    by_campaign: dict[str, list[dict[str, Any]]] = {}
    for snapshot in snapshots:
        pnl_snapshot = (snapshot.get("dry_run") or {}).get("pnl_snapshot") or {}
        if not pnl_snapshot:
            continue
        campaign_id = _text(snapshot.get("campaign_id")) or "unknown"
        by_campaign.setdefault(campaign_id, []).append(snapshot)

    campaigns: list[dict[str, Any]] = []
    for campaign_id, campaign_snapshots in sorted(by_campaign.items()):
        latest = campaign_snapshots[-1]
        previous = campaign_snapshots[-2] if len(campaign_snapshots) > 1 else None
        latest_scopes = _snapshot_pnl_scopes(latest)
        previous_scopes = _snapshot_pnl_scopes(previous or {})
        deltas: list[dict[str, Any]] = []
        if previous is not None:
            latest_portfolio = latest_scopes.get("portfolio") or {}
            previous_portfolio = previous_scopes.get("portfolio") or {}
            for field, scope_name in (
                ("total_pnl", "portfolio_total_pnl"),
                ("since_last_purchase_pnl", "since_last_purchase_pnl"),
            ):
                if field in latest_portfolio or field in previous_portfolio:
                    deltas.append(_scope_delta_row(
                        scope="portfolio",
                        name=scope_name,
                        previous_value=previous_portfolio.get(field),
                        current_value=latest_portfolio.get(field),
                    ))
            latest_realized = latest_portfolio.get("realized_lot") or {}
            previous_realized = previous_portfolio.get("realized_lot") or {}
            if latest_realized or previous_realized:
                deltas.append(_scope_delta_row(
                    scope="realized_lot",
                    name="portfolio_realized_pnl",
                    previous_value=previous_realized.get("realized_pnl"),
                    current_value=latest_realized.get("realized_pnl"),
                ))
            latest_average = latest_scopes.get("average_cost") or {}
            previous_average = previous_scopes.get("average_cost") or {}
            if latest_average or previous_average:
                deltas.append(_scope_delta_row(
                    scope="average_cost",
                    name="average_cost_total_pnl",
                    previous_value=previous_average.get("total_pnl"),
                    current_value=latest_average.get("total_pnl"),
                ))
            latest_products = latest_scopes.get("product") or {}
            previous_products = previous_scopes.get("product") or {}
            for product_id in sorted(set(latest_products) | set(previous_products)):
                latest_product = latest_products.get(product_id) or {}
                previous_product = previous_products.get(product_id) or {}
                if (
                    "total_pnl" in latest_product
                    or "total_pnl" in previous_product
                ):
                    deltas.append(_scope_delta_row(
                        scope="product",
                        name=product_id,
                        previous_value=previous_product.get("total_pnl"),
                        current_value=latest_product.get("total_pnl"),
                    ))
        campaigns.append({
            "campaign_id": campaign_id,
            "checkpoint_count": len(campaign_snapshots),
            "previous_generated_at": (
                previous.get("generated_at") if previous is not None else None
            ),
            "latest_generated_at": latest.get("generated_at"),
            "delta_count": len(deltas),
            "deltas": deltas,
        })

    return {
        "generated_at": timestamp.isoformat(),
        "mode": SpotCampaignRunMode.PNL_DELTA_REPORT.value,
        "status": SpotCampaignStatus.RECORDED.value,
        "campaign_count": len(campaigns),
        "delta_count": sum(campaign["delta_count"] for campaign in campaigns),
        "campaigns": campaigns,
        "live_coinbase_orders_ran": False,
        "live_order_notional_usdc": "0",
        "total_submitted_notional_usdc": "0",
        "total_executed_notional_usdc": "0",
    }


def build_spot_campaign_no_order_recovery_drill(
    *,
    config: Mapping[str, Any],
    dry_run_matrix: Mapping[str, Any],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Exercise retry classification with a synthetic no-submission sweep run."""
    timestamp = generated_at or datetime.now(timezone.utc)
    normalized = normalize_spot_campaign_config(config)
    plan = dry_run_matrix.get("plan") or {}
    synthetic_orders: list[dict[str, Any]] = []
    for item in plan.get("items") or []:
        if not isinstance(item, Mapping):
            continue
        product_id = _text(item.get("product_id")).upper()
        if not product_id:
            continue
        planned = item.get("status") == SpotPortfolioSweepItemStatus.PLANNED.value
        synthetic_orders.append({
            "product_id": product_id,
            "status": (
                SpotPortfolioSweepExecutionStatus.BLOCKED.value
                if planned
                else SpotPortfolioSweepExecutionStatus.SKIPPED.value
            ),
            "exchange_order_id": None,
            "submitted_notional_usdc": "0",
            "executed_notional_usdc": "0",
            "response_success": None,
            "error": (
                "synthetic no-order recovery drill"
                if planned
                else item.get("reason")
            ),
        })
    source_run_id = f"{normalized['sweep_config_id']}-no-order-drill"
    synthetic_run = build_sweep_run_record(
        config_id=normalized["sweep_config_id"],
        run_id=source_run_id,
        status=SpotPortfolioSweepRunStatus.FAILED.value,
        started_at=timestamp,
        completed_at=timestamp,
        config=spot_campaign_config_to_sweep_config(normalized),
        plan=plan,
        execution={
            "live_coinbase_orders_ran": False,
            "submitted_order_count": 0,
            "blocked_or_error_count": len([
                order
                for order in synthetic_orders
                if order["status"] == SpotPortfolioSweepExecutionStatus.BLOCKED.value
            ]),
            "skipped_order_count": len([
                order
                for order in synthetic_orders
                if order["status"] == SpotPortfolioSweepExecutionStatus.SKIPPED.value
            ]),
            "total_submitted_notional_usdc": "0",
            "total_executed_notional_usdc": "0",
            "orders": synthetic_orders,
        },
    )
    retry_plan = build_spot_campaign_retry_plan(
        config=normalized,
        sweep_records=[synthetic_run],
        run_id=source_run_id,
        generated_at=timestamp,
    )
    planned_count = _int_value(plan.get("planned_count"))
    passed = (
        planned_count > 0
        and retry_plan.get("retry_status") == SpotCampaignStatus.READY.value
        and int(retry_plan.get("retryable_product_count") or 0) == planned_count
    )
    return {
        "generated_at": timestamp.isoformat(),
        "mode": SpotCampaignRunMode.RECOVERY_DRILL.value,
        "status": (
            SpotCampaignStatus.READY.value
            if passed
            else SpotCampaignStatus.BLOCKED.value
        ),
        "campaign_id": normalized["campaign_id"],
        "sweep_config_id": normalized["sweep_config_id"],
        "synthetic_source_run_id": source_run_id,
        "planned_order_count": planned_count,
        "synthetic_order_count": len(synthetic_orders),
        "retry_plan": retry_plan,
        "passed": passed,
        "live_coinbase_orders_ran": False,
        "live_order_notional_usdc": "0",
        "total_submitted_notional_usdc": "0",
        "total_executed_notional_usdc": "0",
    }


def build_spot_campaign_all_usdc_readiness_gate(
    *,
    config: Mapping[str, Any],
    dry_run_matrix: Mapping[str, Any],
    release_gate: Mapping[str, Any],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Validate that a broad all-USDC campaign is intentionally and safely broad."""
    timestamp = generated_at or datetime.now(timezone.utc)
    normalized = normalize_spot_campaign_config(config)
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    scope = normalized["product_scope"]
    safety = normalized["safety_policy"]
    plan = dry_run_matrix.get("plan") or {}

    if scope.get("selection_rule") != (
        SpotCampaignProductSelection.ALL_COINBASE_USDC_SPOT_US_CUSTOMER_AVAILABLE.value
    ):
        failures.append({
            "code": "not_all_usdc_selection_rule",
            "reason": "campaign is not configured for the canonical all-USDC selector",
        })
    if scope.get("allow_products") or scope.get("deny_products"):
        failures.append({
            "code": "allow_or_deny_products_present",
            "reason": "broad all-USDC stage must not be scoped by allow/deny lists",
        })
    if normalized.get("max_products") is not None:
        failures.append({
            "code": "max_products_restricts_all_usdc",
            "reason": "broad all-USDC stage must not set max_products",
        })
    if _int_value(plan.get("selected_product_count")) != _int_value(
        plan.get("eligible_product_count")
    ):
        failures.append({
            "code": "selected_product_count_mismatch",
            "eligible_product_count": plan.get("eligible_product_count"),
            "selected_product_count": plan.get("selected_product_count"),
            "reason": "dry-run did not select the full eligible USDC product universe",
        })
    if _int_value(plan.get("planned_count")) <= 0:
        failures.append({
            "code": "no_planned_orders",
            "reason": "all-USDC readiness requires at least one planned order",
        })
    if _int_value(plan.get("skipped_count")) > 0:
        warnings.append({
            "code": "planned_skips_present",
            "skipped_count": plan.get("skipped_count"),
            "skip_counts": dict(plan.get("skip_counts") or {}),
            "reason": "some selected products will not receive orders at this notional",
        })
    for field_name in (
        "max_total_notional_per_run",
        "max_notional_per_order",
        "max_planned_orders",
    ):
        if safety.get(field_name) in (None, ""):
            failures.append({
                "code": "missing_safety_cap",
                "field": f"safety_policy.{field_name}",
                "reason": "broad all-USDC stage requires explicit safety caps",
            })
    if release_gate.get("gate_status") != SpotCampaignGateStatus.PASSED.value:
        failures.append({
            "code": "release_gate_not_passed",
            "reason": "campaign release gate must pass before a broad live stage",
            "release_gate_status": release_gate.get("gate_status"),
        })

    gate_status = (
        SpotCampaignGateStatus.FAILED.value
        if failures
        else SpotCampaignGateStatus.PASSED.value
    )
    return {
        "generated_at": timestamp.isoformat(),
        "mode": SpotCampaignRunMode.ALL_USDC_READINESS.value,
        "campaign_id": normalized["campaign_id"],
        "sweep_config_id": normalized["sweep_config_id"],
        "gate_status": gate_status,
        "status": (
            SpotCampaignStatus.BLOCKED.value
            if failures
            else SpotCampaignStatus.READY.value
        ),
        "failures": failures,
        "warnings": warnings,
        "plan_summary": {
            "eligible_product_count": plan.get("eligible_product_count"),
            "selected_product_count": plan.get("selected_product_count"),
            "planned_count": plan.get("planned_count"),
            "skipped_count": plan.get("skipped_count"),
            "estimated_planned_quote_notional": (
                plan.get("estimated_planned_quote_notional") or "0"
            ),
            "skip_counts": dict(plan.get("skip_counts") or {}),
        },
        "release_gate": dict(release_gate),
        "live_coinbase_orders_ran": False,
        "live_order_notional_usdc": "0",
        "total_submitted_notional_usdc": "0",
        "total_executed_notional_usdc": "0",
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
    safety_evaluation_dict = safety_evaluation.to_dict()
    explain = build_sweep_plan_explain(
        plan=plan_obj,
        safety_evaluation=safety_evaluation_dict,
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
    safety_evaluation_dict = apply_coinbase_average_cost_authority_gate(
        safety=safety_evaluation_dict,
        plan_explain=explain,
        coinbase_average_cost_records=cost_records,
        cost_basis_drift_audit=cost_basis_drift_audit,
        generated_at=timestamp,
    )
    explain = build_sweep_plan_explain(
        plan=plan_obj,
        safety_evaluation=safety_evaluation_dict,
        order_type=normalized["order_type"],
        limit_price_offset_bps=normalized["limit_price_offset_bps"],
        fill_ledger_repo=fill_ledger_repo,
        inventory_baselines=inventory_baselines,
        coinbase_average_cost_baselines=cost_baselines,
        profit_target_pct=safety.get("profit_target_pct"),
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
        "safety_evaluation": safety_evaluation_dict,
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


def _sell_authority_from_item(item: Mapping[str, Any]) -> Mapping[str, Any]:
    authority = item.get("sell_authority")
    return authority if isinstance(authority, Mapping) else {}


def _sell_authority_row(item: Mapping[str, Any]) -> dict[str, Any]:
    authority = _sell_authority_from_item(item)
    source = _text(authority.get("cost_basis_authority")) or (
        SpotCostBasisSource.WALLET_ONLY.value
    )
    return {
        "product_id": _text(item.get("product_id")).upper(),
        "side": _text(item.get("side")).upper(),
        "status": _text(item.get("status")),
        "requested_quote_notional": item.get("requested_quote_notional") or "0",
        "estimated_quote_notional": item.get("estimated_quote_notional") or "0",
        "estimated_price": item.get("estimated_price") or "0",
        "planned_base_size": item.get("planned_base_size") or "0",
        "authority_source": source,
        "authority_status": _text(authority.get("status")),
        "authority_allowed": bool(authority.get("allowed", False)),
        "authority_reason": authority.get("reason"),
        "limit_price": authority.get("limit_price") or "0",
        "known_quantity": authority.get("known_quantity") or "0",
        "known_profitable_quantity": (
            authority.get("known_profitable_quantity") or "0"
        ),
        "coinbase_average_cost_quantity": (
            authority.get("coinbase_average_cost_quantity") or "0"
        ),
        "coinbase_average_profitable_quantity": (
            authority.get("coinbase_average_profitable_quantity") or "0"
        ),
        "coinbase_average_cost_profit_target_pct": (
            authority.get("coinbase_average_cost_profit_target_pct")
        ),
    }


def _average_cost_gate_violations_by_product(
    dry_run_matrix: Mapping[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    safety = dry_run_matrix.get("safety_evaluation") or {}
    gate = safety.get("coinbase_average_cost_authority_gate") or {}
    violations_by_product: dict[str, list[dict[str, Any]]] = {}
    for violation in gate.get("violations") or []:
        if not isinstance(violation, Mapping):
            continue
        product_id = _text(violation.get("product_id")).upper()
        if not product_id:
            continue
        violations_by_product.setdefault(product_id, []).append(dict(violation))
    return violations_by_product


def _allowlist_config_from_rows(
    *,
    normalized: Mapping[str, Any],
    rows: list[Mapping[str, Any]],
) -> dict[str, Any] | None:
    product_ids = sorted({
        _text(row.get("product_id")).upper()
        for row in rows
        if _text(row.get("product_id"))
    })
    if not product_ids:
        return None

    updated = json.loads(json.dumps(normalized))
    updated["campaign_id"] = None
    base_name = _text(updated.get("campaign_name")) or "spot_sell_campaign"
    updated["campaign_name"] = f"{base_name}_authority_allowlist"
    updated["max_products"] = len(product_ids)
    updated.setdefault("product_scope", {})["allow_products"] = product_ids
    updated.setdefault("safety_policy", {})["allow_products"] = product_ids
    max_planned = updated["safety_policy"].get("max_planned_orders")
    if max_planned is None or int(max_planned) > len(product_ids):
        updated["safety_policy"]["max_planned_orders"] = len(product_ids)
    return normalize_spot_campaign_config(updated)


def build_spot_campaign_sell_authority_allowlist(
    *,
    config: Mapping[str, Any],
    dry_run_matrix: Mapping[str, Any],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a durable read-only allowlist from SELL authority rows."""
    timestamp = generated_at or datetime.now(timezone.utc)
    normalized = normalize_spot_campaign_config(config)
    if normalized["side"] != OrderSide.SELL.value:
        raise ValueError("sell authority allowlists are valid only for SELL campaigns")

    plan = dry_run_matrix.get("plan") or {}
    explain = dry_run_matrix.get("plan_explain") or {}
    items = [
        dict(item)
        for item in explain.get("items") or []
        if isinstance(item, Mapping)
    ]
    planned_items = [
        item
        for item in items
        if _text(item.get("status")) == SpotPortfolioSweepItemStatus.PLANNED.value
    ]
    skipped_items = [
        item
        for item in items
        if _text(item.get("status")) == SpotPortfolioSweepItemStatus.SKIPPED.value
    ]

    allowlist_rows: list[dict[str, Any]] = []
    blocked_rows: list[dict[str, Any]] = []
    authority_source_counts: dict[str, int] = {}
    authority_status_counts: dict[str, int] = {}
    average_cost_gate_violations = _average_cost_gate_violations_by_product(
        dry_run_matrix
    )
    for item in planned_items:
        row = _sell_authority_row(item)
        gate_violations = average_cost_gate_violations.get(row["product_id"], [])
        if (
            row["authority_allowed"]
            and row["authority_source"] == SpotCostBasisSource.COINBASE_AVERAGE_COST.value
            and gate_violations
        ):
            row["authority_allowed"] = False
            row["authority_pre_gate_status"] = row["authority_status"]
            row["authority_status"] = InventoryAuthorityStatus.UNAVAILABLE.value
            row["authority_gate_violations"] = gate_violations
            row["authority_reason"] = "; ".join(
                _text(violation.get("reason"))
                for violation in gate_violations
                if _text(violation.get("reason"))
            ) or "Coinbase average cost authority gate blocked this product"
        source = row["authority_source"]
        status = row["authority_status"] or "missing"
        authority_source_counts[source] = authority_source_counts.get(source, 0) + 1
        authority_status_counts[status] = authority_status_counts.get(status, 0) + 1
        if row["authority_allowed"]:
            allowlist_rows.append(row)
        else:
            blocked_rows.append(row)

    skipped_rows = [
        {
            "product_id": _text(item.get("product_id")).upper(),
            "side": _text(item.get("side")).upper(),
            "status": _text(item.get("status")),
            "skip_reason": _text(item.get("skip_reason")),
            "requested_quote_notional": item.get("requested_quote_notional") or "0",
            "estimated_quote_notional": item.get("estimated_quote_notional") or "0",
            "planned_base_size": item.get("planned_base_size") or "0",
            "reason": item.get("reason"),
        }
        for item in skipped_items
    ]
    allowlist_rows.sort(key=lambda row: row["product_id"])
    blocked_rows.sort(key=lambda row: row["product_id"])
    skipped_rows.sort(key=lambda row: row["product_id"])

    allowlisted_notional = sum(
        (_decimal(row.get("estimated_quote_notional")) for row in allowlist_rows),
        Decimal("0"),
    )
    max_age_seconds = DEFAULT_SELL_AUTHORITY_ALLOWLIST_MAX_AGE_SECONDS
    allowlist_metadata = {
        "mode": SpotCampaignRunMode.SELL_AUTHORITY_ALLOWLIST.value,
        "freshness_status": SpotSellAuthorityAllowlistFreshness.FRESH.value,
        "generated_at": timestamp.isoformat(),
        "max_age_seconds": max_age_seconds,
        "expires_at": (timestamp + timedelta(seconds=max_age_seconds)).isoformat(),
        "sell_authority_profile": normalized.get("sell_authority_profile"),
        "allowlist_count": len(allowlist_rows),
        "blocked_count": len(blocked_rows),
        "estimated_allowlisted_quote_notional": _format_decimal(
            allowlisted_notional
        ),
        "authority_source_counts": dict(authority_source_counts),
        "authority_status_counts": dict(authority_status_counts),
    }
    allowlist_config = _allowlist_config_from_rows(
        normalized=normalized,
        rows=allowlist_rows,
    )
    allowlist_sweep_config = (
        spot_campaign_config_to_sweep_config(allowlist_config)
        if allowlist_config
        else None
    )
    if allowlist_sweep_config is not None:
        allowlist_sweep_config["sell_authority_allowlist"] = dict(
            allowlist_metadata
        )
    risk_notes = [
        "rerun this allowlist gate immediately before any live SELL approval",
    ]
    if blocked_rows:
        risk_notes.append(
            "blocked planned rows are excluded and must not be sold by a broad run"
        )
    if any(
        row["authority_source"] == SpotCostBasisSource.COINBASE_AVERAGE_COST.value
        for row in allowlist_rows
    ):
        risk_notes.append(
            "Coinbase average cost is portfolio-level operational authority, not exact FIFO lot evidence"
        )

    return {
        "generated_at": timestamp.isoformat(),
        "mode": SpotCampaignRunMode.SELL_AUTHORITY_ALLOWLIST.value,
        "status": (
            SpotCampaignStatus.READY.value
            if allowlist_rows
            else SpotCampaignStatus.BLOCKED.value
        ),
        "campaign_id": normalized["campaign_id"],
        "sweep_config_id": normalized["sweep_config_id"],
        "sell_authority_profile": normalized.get("sell_authority_profile"),
        "quote_notional": normalized["quote_notional"],
        "order_type": normalized["order_type"],
        "planned_count": int(plan.get("planned_count") or len(planned_items)),
        "skipped_count": int(plan.get("skipped_count") or len(skipped_items)),
        "allowlist_count": len(allowlist_rows),
        "blocked_count": len(blocked_rows),
        "authority_source_counts": authority_source_counts,
        "authority_status_counts": authority_status_counts,
        "estimated_planned_quote_notional": (
            plan.get("estimated_planned_quote_notional") or "0"
        ),
        "estimated_allowlisted_quote_notional": _format_decimal(
            allowlisted_notional
        ),
        "allow_products": [row["product_id"] for row in allowlist_rows],
        "allowlist_rows": allowlist_rows,
        "blocked_rows": blocked_rows,
        "skipped_rows": skipped_rows,
        "allowlist_config": allowlist_config,
        "allowlist_sweep_config": allowlist_sweep_config,
        "allowlist_metadata": allowlist_metadata,
        "risk_notes": risk_notes,
        "live_coinbase_orders_ran": False,
        "live_order_notional_usdc": "0",
        "total_submitted_notional_usdc": "0",
        "total_executed_notional_usdc": "0",
    }


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
    sell_authority_allowlist: Mapping[str, Any] | None = None,
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
        "sell_authority_allowlist": dict(sell_authority_allowlist or {}),
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
        SpotCampaignRunMode.SELL_AUTHORITY_ALLOWLIST.value,
    }:
        return True
    dry_run = snapshot.get("dry_run") or {}
    release_gate = snapshot.get("release_gate") or {}
    allowlist = snapshot.get("sell_authority_allowlist") or {}
    return bool(
        release_gate
        or allowlist
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
    sell_allowlist = (
        readiness_snapshot.get("sell_authority_allowlist")
        or latest_snapshot.get("sell_authority_allowlist")
        or {}
    )
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
        "sell_authority_profile": sell_allowlist.get("sell_authority_profile"),
        "sell_authority_allowlist_count": _int_value(
            sell_allowlist.get("allowlist_count")
        ),
        "sell_authority_blocked_count": _int_value(
            sell_allowlist.get("blocked_count")
        ),
        "sell_authority_source_counts": dict(
            sell_allowlist.get("authority_source_counts") or {}
        ),
        "sell_authority_status_counts": dict(
            sell_allowlist.get("authority_status_counts") or {}
        ),
        "sell_authority_estimated_allowlisted_quote_notional": (
            sell_allowlist.get("estimated_allowlisted_quote_notional") or "0"
        ),
        "sell_authority_allow_products_preview": list(
            sell_allowlist.get("allow_products") or []
        )[:10],
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
