"""Coinbase average cost-basis helpers for USDC spot inventory.

Coinbase portfolio breakdown exposes asset-level spot position cost basis and
average entry price. This module treats that as an explicit operational
authority source, separate from exact local fill-ledger lots.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping

from core.enums import (
    InventoryCostBasisStatus,
    InventoryLotSource,
    SpotAuditRecordType,
    SpotCostBasisGapStatus,
    SpotCostBasisSource,
    SpotCostBasisStatus,
    SpotInventoryCoverageStatus,
    SpotPortfolioPnlScope,
)


QUOTE_CURRENCY = "USDC"


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


def _dict_response(response: Any) -> Any:
    converter = getattr(response, "to_dict", None)
    if callable(converter):
        return converter()
    return response


def _product_id(product: Any) -> str:
    return _text(
        product.get("product_id") if isinstance(product, Mapping) else getattr(product, "product_id", "")
    )


def _base_currency(product: Any) -> str:
    if isinstance(product, Mapping):
        return _text(
            product.get("base_currency_id")
            or product.get("base_currency")
            or _product_id(product).split("-", 1)[0]
        ).upper()
    return _text(
        getattr(product, "base_currency_id", "")
        or getattr(product, "base_currency", "")
        or _product_id(product).split("-", 1)[0]
    ).upper()


def _quote_currency(product: Any) -> str:
    if isinstance(product, Mapping):
        return _text(
            product.get("quote_currency_id")
            or product.get("quote_currency")
            or (_product_id(product).split("-", 1)[1] if "-" in _product_id(product) else "")
        ).upper()
    return _text(
        getattr(product, "quote_currency_id", "")
        or getattr(product, "quote_currency", "")
        or (_product_id(product).split("-", 1)[1] if "-" in _product_id(product) else "")
    ).upper()


def _usdc_product_by_base(products: Iterable[Any]) -> dict[str, str]:
    from business.spot_portfolio_sweep import filter_usdc_spot_products

    mapping: dict[str, str] = {}
    for product in filter_usdc_spot_products(products or []):
        product_id = _product_id(product)
        base = _base_currency(product)
        quote = _quote_currency(product)
        if not product_id or not base or quote != QUOTE_CURRENCY:
            continue
        mapping.setdefault(base, product_id)
    return mapping


def _money_value(source: Mapping[str, Any], name: str) -> tuple[Decimal, str]:
    raw = source.get(name)
    if isinstance(raw, Mapping):
        return _decimal(raw.get("value")), _text(raw.get("currency")).upper()
    return _decimal(raw), ""


def _first_available_portfolio(portfolios: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    active = [
        portfolio for portfolio in portfolios
        if isinstance(portfolio, Mapping) and not portfolio.get("deleted")
    ]
    if not active:
        return None
    for portfolio in active:
        if _text(portfolio.get("type")).upper() in {"DEFAULT", "CONSUMER"}:
            return portfolio
    return active[0]


def select_coinbase_cost_basis_portfolio(
    portfolios: Iterable[Mapping[str, Any]],
    *,
    portfolio_uuid: str | None = None,
) -> Mapping[str, Any] | None:
    """Select the requested portfolio or the first usable active portfolio."""
    portfolios = [dict(portfolio) for portfolio in portfolios or [] if isinstance(portfolio, Mapping)]
    if portfolio_uuid:
        for portfolio in portfolios:
            if _text(portfolio.get("uuid")) == _text(portfolio_uuid):
                return portfolio
        return None
    return _first_available_portfolio(portfolios)


def build_coinbase_average_cost_records(
    *,
    portfolio_breakdown: Mapping[str, Any],
    products: Iterable[Any],
    generated_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """Parse Coinbase portfolio spot positions into USDC product records."""
    generated_at = generated_at or datetime.now(timezone.utc)
    breakdown = portfolio_breakdown.get("breakdown") or portfolio_breakdown
    portfolio = breakdown.get("portfolio") if isinstance(breakdown, Mapping) else {}
    positions = breakdown.get("spot_positions") if isinstance(breakdown, Mapping) else []
    product_by_base = _usdc_product_by_base(products)

    records: list[dict[str, Any]] = []
    for position in positions or []:
        if not isinstance(position, Mapping):
            continue
        asset = _text(position.get("asset")).upper()
        product_id = product_by_base.get(asset)
        if not asset or not product_id:
            continue
        average_entry_price, average_currency = _money_value(
            position,
            "average_entry_price",
        )
        cost_basis, cost_basis_currency = _money_value(position, "cost_basis")
        total_balance = _decimal(position.get("total_balance_crypto"))
        available_balance = _decimal(position.get("available_to_trade_crypto"))
        quantity = available_balance if available_balance > 0 else total_balance
        if quantity <= 0:
            status = SpotCostBasisStatus.MISSING_BALANCE.value
        elif average_entry_price <= 0:
            status = SpotCostBasisStatus.MISSING_AVERAGE_ENTRY_PRICE.value
        else:
            status = SpotCostBasisStatus.AVAILABLE.value
        records.append({
            "source": SpotCostBasisSource.COINBASE_AVERAGE_COST.value,
            "status": status,
            "generated_at": generated_at.isoformat(),
            "portfolio_uuid": _text((portfolio or {}).get("uuid")) or None,
            "portfolio_name": _text((portfolio or {}).get("name")) or None,
            "asset": asset,
            "product_id": product_id,
            "account_uuid": _text(position.get("account_uuid")) or None,
            "quantity": _format_decimal(quantity),
            "total_balance_crypto": _format_decimal(total_balance),
            "available_to_trade_crypto": _format_decimal(available_balance),
            "average_entry_price": _format_decimal(average_entry_price),
            "average_entry_price_currency": average_currency or None,
            "cost_basis": _format_decimal(cost_basis),
            "cost_basis_currency": cost_basis_currency or None,
            "unrealized_pnl": _format_decimal(_decimal(position.get("unrealized_pnl"))),
        })
    return records


def coinbase_average_cost_records_to_baselines(
    records: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Convert available Coinbase average-cost records into baseline lots."""
    baselines: list[dict[str, Any]] = []
    for index, record in enumerate(records or []):
        if record.get("status") != SpotCostBasisStatus.AVAILABLE.value:
            continue
        quantity = _decimal(record.get("quantity"))
        entry_price = _decimal(record.get("average_entry_price"))
        product_id = _text(record.get("product_id"))
        if quantity <= 0 or entry_price <= 0 or not product_id:
            continue
        source_id = (
            record.get("account_uuid")
            or record.get("portfolio_uuid")
            or f"coinbase-average-{index}"
        )
        baselines.append({
            "product_id": product_id,
            "quantity": _format_decimal(quantity),
            "remaining_quantity": _format_decimal(quantity),
            "entry_price": _format_decimal(entry_price),
            "entry_timestamp": record.get("generated_at"),
            "fees": "0",
            "cost_basis_status": InventoryCostBasisStatus.KNOWN.value,
            "source_id": source_id,
            "lot_source": InventoryLotSource.COINBASE_AVERAGE_COST.value,
        })
    return baselines


def fetch_coinbase_average_cost_records(
    *,
    rest_client: Any,
    products: Iterable[Any],
    portfolio_uuid: str | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Fetch and parse Coinbase average-cost records from portfolio breakdown."""
    generated_at = generated_at or datetime.now(timezone.utc)
    lister = getattr(rest_client, "list_portfolios", None)
    if callable(lister):
        portfolios = lister()
    else:
        sdk_lister = getattr(rest_client, "get_portfolios", None)
        portfolios = (_dict_response(sdk_lister()) or {}).get("portfolios", []) if callable(sdk_lister) else []
    portfolio = select_coinbase_cost_basis_portfolio(
        portfolios,
        portfolio_uuid=portfolio_uuid,
    )
    if not portfolio:
        return {
            "generated_at": generated_at.isoformat(),
            "status": SpotCostBasisStatus.UNAVAILABLE.value,
            "portfolio_uuid": portfolio_uuid,
            "record_count": 0,
            "baseline_count": 0,
            "records": [],
            "baselines": [],
            "read_only_coinbase_requests": ["get_portfolios"],
            "error": "portfolio was not found",
        }
    selected_uuid = _text(portfolio.get("uuid"))
    getter = getattr(rest_client, "get_portfolio", None)
    if callable(getter):
        breakdown = getter(selected_uuid)
    else:
        sdk_getter = getattr(rest_client, "get_portfolio_breakdown", None)
        breakdown = _dict_response(sdk_getter(selected_uuid)) if callable(sdk_getter) else {}
    records = build_coinbase_average_cost_records(
        portfolio_breakdown=breakdown or {},
        products=products,
        generated_at=generated_at,
    )
    baselines = coinbase_average_cost_records_to_baselines(records)
    return {
        "generated_at": generated_at.isoformat(),
        "status": SpotCostBasisStatus.AVAILABLE.value,
        "portfolio_uuid": selected_uuid,
        "portfolio_name": _text(portfolio.get("name")) or None,
        "record_count": len(records),
        "baseline_count": len(baselines),
        "records": records,
        "baselines": baselines,
        "read_only_coinbase_requests": ["get_portfolios", "get_portfolio_breakdown"],
    }


def average_cost_records_by_product(
    records: Iterable[Mapping[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    return {
        _text(record.get("product_id")): dict(record)
        for record in records or []
        if _text(record.get("product_id"))
    }


def build_average_cost_pnl_report(
    *,
    average_cost_records: Iterable[Mapping[str, Any]],
    mark_prices: Mapping[str, Any],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build operational average-cost P/L from Coinbase average basis."""
    generated_at = generated_at or datetime.now(timezone.utc)
    products: list[dict[str, Any]] = []
    totals = {
        "quantity": Decimal("0"),
        "cost_basis": Decimal("0"),
        "mark_value": Decimal("0"),
        "unrealized_pnl": Decimal("0"),
    }
    for record in sorted(average_cost_records or [], key=lambda item: _text(item.get("product_id"))):
        if record.get("status") != SpotCostBasisStatus.AVAILABLE.value:
            continue
        product_id = _text(record.get("product_id"))
        quantity = _decimal(record.get("quantity"))
        average_entry = _decimal(record.get("average_entry_price"))
        mark_price = _decimal(mark_prices.get(product_id))
        cost_basis = quantity * average_entry
        mark_value = quantity * mark_price
        unrealized = mark_value - cost_basis
        totals["quantity"] += quantity
        totals["cost_basis"] += cost_basis
        totals["mark_value"] += mark_value
        totals["unrealized_pnl"] += unrealized
        products.append({
            "product_id": product_id,
            "scope": SpotPortfolioPnlScope.AVERAGE_COST.value,
            "source": SpotCostBasisSource.COINBASE_AVERAGE_COST.value,
            "quantity": _format_decimal(quantity),
            "average_entry_price": _format_decimal(average_entry),
            "mark_price": _format_decimal(mark_price),
            "cost_basis": _format_decimal(cost_basis),
            "mark_value": _format_decimal(mark_value),
            "unrealized_pnl": _format_decimal(unrealized),
            "status": record.get("status"),
        })
    return {
        "generated_at": generated_at.isoformat(),
        "scope": SpotPortfolioPnlScope.AVERAGE_COST.value,
        "source": SpotCostBasisSource.COINBASE_AVERAGE_COST.value,
        "product_count": len(products),
        "portfolio": {
            "scope": SpotPortfolioPnlScope.AVERAGE_COST.value,
            "quantity": _format_decimal(totals["quantity"]),
            "cost_basis": _format_decimal(totals["cost_basis"]),
            "mark_value": _format_decimal(totals["mark_value"]),
            "unrealized_pnl": _format_decimal(totals["unrealized_pnl"]),
        },
        "products": products,
    }


def build_cost_basis_drift_audit(
    *,
    fill_ledger_repo: Any,
    products: Iterable[Any],
    average_cost_records: Iterable[Mapping[str, Any]],
    generated_at: datetime | None = None,
    warning_threshold_pct: Any = "5",
) -> dict[str, Any]:
    """Compare local fill-ledger average basis against Coinbase average basis."""
    generated_at = generated_at or datetime.now(timezone.utc)
    records_by_product = average_cost_records_by_product(average_cost_records)
    product_ids = sorted(_usdc_product_by_base(products).values())
    rows: list[dict[str, Any]] = []
    status_counts = {
        SpotCostBasisStatus.AVAILABLE.value: 0,
        SpotCostBasisStatus.MISSING_POSITION.value: 0,
        SpotCostBasisStatus.UNAVAILABLE.value: 0,
    }
    threshold = _decimal(warning_threshold_pct)
    try:
        from business.lot_builder import PositionLotBuilder
        from core.enums import OrderSide

        builder = PositionLotBuilder(fill_ledger_repo)
    except Exception:
        builder = None
    for product_id in product_ids:
        record = records_by_product.get(product_id)
        if not record or record.get("status") != SpotCostBasisStatus.AVAILABLE.value:
            status_counts[SpotCostBasisStatus.MISSING_POSITION.value] += 1
            rows.append({
                "product_id": product_id,
                "status": SpotCostBasisStatus.MISSING_POSITION.value,
                "source": SpotCostBasisSource.COINBASE_AVERAGE_COST.value,
            })
            continue
        if builder is None:
            status_counts[SpotCostBasisStatus.UNAVAILABLE.value] += 1
            rows.append({
                "product_id": product_id,
                "status": SpotCostBasisStatus.UNAVAILABLE.value,
                "source": SpotCostBasisSource.FILL_LEDGER.value,
            })
            continue
        position = builder.build_position_by_product(product_id, side=OrderSide.BUY)
        local_lots = [
            lot for lot in position.get_unexited_lots()
            if lot.cost_basis_status == InventoryCostBasisStatus.KNOWN
            and lot.lot_source == InventoryLotSource.FILL_LEDGER
        ]
        local_quantity = sum((_decimal(lot.remaining_quantity) for lot in local_lots), Decimal("0"))
        local_value = sum(
            (_decimal(lot.remaining_quantity) * _decimal(lot.entry_price) for lot in local_lots),
            Decimal("0"),
        )
        local_average = local_value / local_quantity if local_quantity > 0 else Decimal("0")
        coinbase_average = _decimal(record.get("average_entry_price"))
        drift = coinbase_average - local_average
        drift_pct = (drift / local_average * Decimal("100")) if local_average > 0 else Decimal("0")
        status = (
            SpotCostBasisStatus.UNAVAILABLE.value
            if local_quantity <= 0
            else SpotCostBasisStatus.STALE.value
            if abs(drift_pct) > threshold
            else SpotCostBasisStatus.AVAILABLE.value
        )
        status_counts[status] = status_counts.get(status, 0) + 1
        rows.append({
            "product_id": product_id,
            "status": status,
            "local_quantity": _format_decimal(local_quantity),
            "local_average_entry_price": _format_decimal(local_average),
            "coinbase_quantity": record.get("quantity") or "0",
            "coinbase_average_entry_price": record.get("average_entry_price") or "0",
            "drift": _format_decimal(drift),
            "drift_pct": _format_decimal(drift_pct),
            "warning_threshold_pct": _format_decimal(threshold),
        })
    return {
        "generated_at": generated_at.isoformat(),
        "quote_currency": QUOTE_CURRENCY,
        "status_counts": status_counts,
        "product_count": len(rows),
        "products": rows,
    }


def _dedupe_strings(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values or []:
        text = _text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def build_cost_basis_gap_triage(
    *,
    inventory_coverage: Mapping[str, Any],
    drift_audit: Mapping[str, Any] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Summarize cost-basis gaps that still need operator review."""
    generated_at = generated_at or datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    status_counts = {status.value: 0 for status in SpotCostBasisGapStatus}
    coverage_products = {
        _text(row.get("product_id")): row
        for row in inventory_coverage.get("products") or []
        if isinstance(row, Mapping) and _text(row.get("product_id"))
    }
    drift_products = {
        _text(row.get("product_id")): row
        for row in (drift_audit or {}).get("products") or []
        if isinstance(row, Mapping) and _text(row.get("product_id"))
    }

    for product_id, row in sorted(coverage_products.items()):
        coverage_status = _text(row.get("coverage_status"))
        if coverage_status != SpotInventoryCoverageStatus.WALLET_ONLY.value:
            continue
        average_qty = _decimal(row.get("coinbase_average_cost_quantity"))
        gap_status = (
            SpotCostBasisGapStatus.MISSING_AVERAGE_COST_POSITION.value
            if average_qty <= 0
            else SpotCostBasisGapStatus.WALLET_ONLY.value
        )
        status_counts[gap_status] += 1
        rows.append({
            "product_id": product_id,
            "status": gap_status,
            "coverage_status": coverage_status,
            "wallet_available": row.get("wallet_available") or "0",
            "local_evidence_quantity": row.get("local_evidence_quantity") or "0",
            "coinbase_average_cost_quantity": (
                row.get("coinbase_average_cost_quantity") or "0"
            ),
            "reason": row.get("reason") or "",
        })

    for product_id, row in sorted(drift_products.items()):
        drift_status = _text(row.get("status"))
        if drift_status == SpotCostBasisStatus.STALE.value:
            gap_status = SpotCostBasisGapStatus.STALE_AVERAGE_COST.value
        elif drift_status == SpotCostBasisStatus.UNAVAILABLE.value:
            gap_status = SpotCostBasisGapStatus.LOCAL_LOT_UNAVAILABLE.value
        elif drift_status == SpotCostBasisStatus.MISSING_POSITION.value:
            if product_id in coverage_products:
                continue
            gap_status = SpotCostBasisGapStatus.MISSING_AVERAGE_COST_POSITION.value
        else:
            continue
        status_counts[gap_status] += 1
        rows.append({
            "product_id": product_id,
            "status": gap_status,
            "drift_status": drift_status,
            "local_quantity": row.get("local_quantity") or "0",
            "local_average_entry_price": (
                row.get("local_average_entry_price") or "0"
            ),
            "coinbase_quantity": row.get("coinbase_quantity") or "0",
            "coinbase_average_entry_price": (
                row.get("coinbase_average_entry_price") or "0"
            ),
            "drift_pct": row.get("drift_pct") or "0",
            "reason": "local average cost basis differs or is unavailable",
        })

    return {
        "generated_at": generated_at.isoformat(),
        "quote_currency": QUOTE_CURRENCY,
        "product_count": len(rows),
        "status_counts": status_counts,
        "products": rows,
    }


def build_cost_basis_snapshot_record(
    *,
    cost_basis: Mapping[str, Any],
    inventory_coverage: Mapping[str, Any] | None = None,
    drift_audit: Mapping[str, Any] | None = None,
    gap_triage: Mapping[str, Any] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a durable local snapshot of read-only Coinbase cost-basis state."""
    generated_at = generated_at or datetime.now(timezone.utc)
    read_requests = list(cost_basis.get("read_only_coinbase_requests") or [])
    record = {
        "record_type": SpotAuditRecordType.COST_BASIS_SNAPSHOT.value,
        "generated_at": generated_at.isoformat(),
        "source": SpotCostBasisSource.COINBASE_AVERAGE_COST.value,
        "status": cost_basis.get("status") or SpotCostBasisStatus.UNAVAILABLE.value,
        "portfolio_uuid": cost_basis.get("portfolio_uuid"),
        "portfolio_name": cost_basis.get("portfolio_name"),
        "baseline": {
            "record_count": int(cost_basis.get("record_count") or 0),
            "baseline_count": int(cost_basis.get("baseline_count") or 0),
        },
        "inventory_coverage": None,
        "drift_audit": None,
        "gap_triage": None,
        "read_only_coinbase_requests": [],
        "live_coinbase_orders_ran": False,
        "live_order_notional_usdc": "0",
        "total_submitted_notional_usdc": "0",
        "total_executed_notional_usdc": "0",
    }
    if inventory_coverage:
        read_requests.extend(["get_public_products", "get_accounts"])
        record["inventory_coverage"] = {
            "eligible_product_count": int(
                inventory_coverage.get("eligible_product_count") or 0
            ),
            "wallet_balance_product_count": int(
                inventory_coverage.get("wallet_balance_product_count") or 0
            ),
            "coinbase_average_cost_product_count": int(
                inventory_coverage.get("coinbase_average_cost_product_count") or 0
            ),
            "wallet_only_product_count": int(
                inventory_coverage.get("wallet_only_product_count") or 0
            ),
            "status_counts": inventory_coverage.get("status_counts") or {},
        }
    if drift_audit:
        read_requests.append("get_public_products")
        record["drift_audit"] = {
            "product_count": int(drift_audit.get("product_count") or 0),
            "status_counts": drift_audit.get("status_counts") or {},
        }
    if gap_triage:
        record["gap_triage"] = {
            "product_count": int(gap_triage.get("product_count") or 0),
            "status_counts": gap_triage.get("status_counts") or {},
        }
    record["read_only_coinbase_requests"] = _dedupe_strings(read_requests)
    return record


def append_cost_basis_snapshot_record(
    state_file: str | Path,
    record: Mapping[str, Any],
) -> None:
    """Append a cost-basis snapshot record to a local JSONL ledger."""
    path = Path(state_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(dict(record), sort_keys=True))
        handle.write("\n")


def load_cost_basis_snapshot_records(state_file: str | Path) -> list[dict[str, Any]]:
    """Load durable cost-basis snapshot records from a local JSONL ledger."""
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


def build_cost_basis_operator_status(
    *,
    records: Iterable[Mapping[str, Any]],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Summarize durable cost-basis snapshots for dashboard/operator views."""
    generated_at = generated_at or datetime.now(timezone.utc)
    snapshots = [
        dict(record)
        for record in records or []
        if record.get("record_type") == SpotAuditRecordType.COST_BASIS_SNAPSHOT.value
    ]
    snapshots.sort(key=lambda record: _text(record.get("generated_at")))
    latest = snapshots[-1] if snapshots else None
    return {
        "generated_at": generated_at.isoformat(),
        "snapshot_count": len(snapshots),
        "latest_snapshot": latest,
    }
