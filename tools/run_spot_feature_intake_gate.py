"""Validate an approved spot-specific feature request before implementation.

This gate is intentionally read-only and local-only. It prevents Phase 50 style
feature work from starting with ambiguous product scope, live-order approval,
automation cadence, notional caps, or audit evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.enums import (
    OrderSide,
    SpotCostBasisSource,
    SpotAuditRecordType,
    SpotFeatureIntakeGateStatus,
    SpotFeatureInventoryRetentionPolicy,
    SpotPortfolioSweepOrderType,
)


SUMMARY_PREFIX = "SPOT_FEATURE_INTAKE_GATE "
QUOTE_CURRENCY = "USDC"
MINIMUM_AUDIT_EVIDENCE = {
    "client_order_id",
    "exchange_order_id",
    "submitted_notional_usdc",
    "executed_notional_usdc",
    "fill_ledger_reconciliation",
}


def _enum_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value


def _text(value: Any) -> str:
    value = _enum_value(value)
    if value is None:
        return ""
    return str(value).strip()


def _get_path(payload: Mapping[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _has_value(payload: Mapping[str, Any], path: str) -> bool:
    value = _get_path(payload, path)
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return value is not None


def _positive_decimal(value: Any) -> bool:
    try:
        return Decimal(str(value)) > 0
    except (InvalidOperation, TypeError, ValueError):
        return False


def _positive_int(value: Any) -> bool:
    try:
        return int(value) > 0
    except (TypeError, ValueError):
        return False


def _string_set(values: Iterable[Any]) -> set[str]:
    return {_text(value) for value in values if _text(value)}


def _invalid_field(field: str, reason: str) -> dict[str, str]:
    return {"field": field, "reason": reason}


def build_spot_feature_intake_summary(
    *,
    request: Mapping[str, Any] | None,
    request_file: Path | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Return the intake-gate result for one proposed spot feature."""
    generated_at = generated_at or datetime.now(timezone.utc)
    request = dict(request or {})
    missing_fields = []
    invalid_fields: list[dict[str, str]] = []
    warnings: list[str] = []

    required_paths = [
        "feature_name",
        "goal",
        "product_scope.quote_currency",
        "product_scope.us_customer_available",
        "order_sides",
        "order_types",
        "automation.repeat_every_hours",
        "automation.max_runs",
        "live_approval.required",
        "safety.max_notional_per_order",
        "safety.max_total_notional_per_run",
        "inventory_policy.retention",
        "cost_basis_authority.allowed_sources",
        "audit.required_evidence",
    ]
    for path in required_paths:
        if not _has_value(request, path):
            missing_fields.append(path)

    if not (
        _has_value(request, "product_scope.allowed_products")
        or _has_value(request, "product_scope.selection_rule")
    ):
        missing_fields.append(
            "product_scope.allowed_products_or_selection_rule"
        )

    quote_currency = _text(_get_path(request, "product_scope.quote_currency")).upper()
    if quote_currency and quote_currency != QUOTE_CURRENCY:
        invalid_fields.append(
            _invalid_field(
                "product_scope.quote_currency",
                "approved spot scope is USDC-only",
            )
        )

    us_customer_available = _get_path(request, "product_scope.us_customer_available")
    if us_customer_available is not None and us_customer_available is not True:
        invalid_fields.append(
            _invalid_field(
                "product_scope.us_customer_available",
                "features must explicitly require US-customer-available products",
            )
        )

    order_sides = _get_path(request, "order_sides") or []
    if order_sides and not isinstance(order_sides, list):
        invalid_fields.append(_invalid_field("order_sides", "must be a list"))
    else:
        allowed_sides = {side.value for side in OrderSide}
        invalid_sides = sorted(_string_set(order_sides) - allowed_sides)
        if invalid_sides:
            invalid_fields.append(
                _invalid_field(
                    "order_sides",
                    f"unsupported side(s): {', '.join(invalid_sides)}",
                )
            )

    order_types = _get_path(request, "order_types") or []
    if order_types and not isinstance(order_types, list):
        invalid_fields.append(_invalid_field("order_types", "must be a list"))
    else:
        allowed_order_types = {order_type.value for order_type in SpotPortfolioSweepOrderType}
        invalid_order_types = sorted(_string_set(order_types) - allowed_order_types)
        if invalid_order_types:
            invalid_fields.append(
                _invalid_field(
                    "order_types",
                    "unsupported order policy/policies: "
                    + ", ".join(invalid_order_types),
                )
            )

    repeat_every_hours = _get_path(request, "automation.repeat_every_hours")
    if repeat_every_hours is not None and not _positive_decimal(repeat_every_hours):
        invalid_fields.append(
            _invalid_field(
                "automation.repeat_every_hours",
                "must be greater than zero",
            )
        )
    max_runs = _get_path(request, "automation.max_runs")
    if max_runs is not None and not _positive_int(max_runs):
        invalid_fields.append(
            _invalid_field("automation.max_runs", "must be a positive integer")
        )

    live_required = _get_path(request, "live_approval.required")
    if live_required is not None and live_required is not True:
        invalid_fields.append(
            _invalid_field(
                "live_approval.required",
                "live Coinbase order submission must remain explicitly approved",
            )
        )

    for field in ("safety.max_notional_per_order", "safety.max_total_notional_per_run"):
        value = _get_path(request, field)
        if value is not None and not _positive_decimal(value):
            invalid_fields.append(_invalid_field(field, "must be greater than zero"))

    retention = _text(_get_path(request, "inventory_policy.retention"))
    if retention:
        allowed_retention = {policy.value for policy in SpotFeatureInventoryRetentionPolicy}
        if retention not in allowed_retention:
            invalid_fields.append(
                _invalid_field(
                    "inventory_policy.retention",
                    "must be one of: " + ", ".join(sorted(allowed_retention)),
                )
            )

    allowed_sources = _get_path(request, "cost_basis_authority.allowed_sources") or []
    if _has_value(request, "cost_basis_authority.allowed_sources"):
        if not isinstance(allowed_sources, list):
            invalid_fields.append(
                _invalid_field("cost_basis_authority.allowed_sources", "must be a list")
            )
        else:
            allowed_authorities = {source.value for source in SpotCostBasisSource}
            invalid_sources = sorted(_string_set(allowed_sources) - allowed_authorities)
            if invalid_sources:
                invalid_fields.append(
                    _invalid_field(
                        "cost_basis_authority.allowed_sources",
                        "unsupported source(s): " + ", ".join(invalid_sources),
                    )
                )
            if (
                SpotCostBasisSource.COINBASE_AVERAGE_COST.value
                in _string_set(allowed_sources)
                and not _has_value(
                    request,
                    "cost_basis_authority.coinbase_average_cost_profit_buffer_pct",
                )
            ):
                invalid_fields.append(
                    _invalid_field(
                        "cost_basis_authority.coinbase_average_cost_profit_buffer_pct",
                        "required when Coinbase average cost basis is allowed",
                    )
                )

    evidence = _get_path(request, "audit.required_evidence") or []
    if _has_value(request, "audit.required_evidence"):
        if not isinstance(evidence, list):
            invalid_fields.append(
                _invalid_field("audit.required_evidence", "must be a list")
            )
        else:
            missing_evidence = sorted(MINIMUM_AUDIT_EVIDENCE - _string_set(evidence))
            if missing_evidence:
                invalid_fields.append(
                    _invalid_field(
                        "audit.required_evidence",
                        "missing required evidence: " + ", ".join(missing_evidence),
                    )
                )

    allowed_products = _get_path(request, "product_scope.allowed_products") or []
    selection_rule = _text(_get_path(request, "product_scope.selection_rule"))
    if allowed_products and not isinstance(allowed_products, list):
        invalid_fields.append(
            _invalid_field("product_scope.allowed_products", "must be a list")
        )
    elif allowed_products:
        non_usdc_products = [
            _text(product) for product in allowed_products
            if not _text(product).upper().endswith(f"-{QUOTE_CURRENCY}")
        ]
        if non_usdc_products:
            invalid_fields.append(
                _invalid_field(
                    "product_scope.allowed_products",
                    "non-USDC product(s): " + ", ".join(non_usdc_products),
                )
            )
    elif selection_rule:
        warnings.append(
            "selection_rule must be resolved to concrete eligible products at run time"
        )

    status = (
        SpotFeatureIntakeGateStatus.FAILED.value
        if invalid_fields
        else SpotFeatureIntakeGateStatus.INCOMPLETE.value
        if missing_fields
        else SpotFeatureIntakeGateStatus.PASSED.value
    )
    return {
        "record_type": SpotAuditRecordType.FEATURE_INTAKE_GATE.value,
        "generated_at": generated_at.isoformat(),
        "request_file": str(request_file) if request_file else None,
        "status": status,
        "phase_50_ready": status == SpotFeatureIntakeGateStatus.PASSED.value,
        "missing_fields": missing_fields,
        "invalid_fields": invalid_fields,
        "warnings": warnings,
        "live_coinbase_orders_ran": False,
        "live_order_notional_usdc": "0",
        "total_submitted_notional_usdc": "0",
        "total_executed_notional_usdc": "0",
        "read_only_coinbase_requests": [],
        "live_coinbase_requests": [],
    }


def _load_request(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise ValueError("spot feature request file must contain a JSON object")
    return dict(payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate spot feature intake before implementation."
    )
    parser.add_argument(
        "--request-file",
        type=Path,
        default=None,
        help="JSON feature request to validate.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Omit the loaded request payload from output.",
    )
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="Return success for incomplete intake. Failed intake still returns nonzero.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    request = _load_request(args.request_file)
    summary = build_spot_feature_intake_summary(
        request=request,
        request_file=args.request_file,
    )
    if not args.summary_only:
        summary["request"] = request
    print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
    status = summary["status"]
    if status == SpotFeatureIntakeGateStatus.PASSED.value:
        return 0
    if status == SpotFeatureIntakeGateStatus.INCOMPLETE.value and args.allow_incomplete:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
