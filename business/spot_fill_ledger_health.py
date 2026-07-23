"""Spot fill-ledger health and repair planning helpers.

These helpers audit local fill evidence used by spot inventory, P/L, and sweep
reconciliation. They do not place orders. Repair planning uses durable local
order evidence to map ``client_order_id`` to an exchange order id, then matches
Coinbase REST fills back to suspicious local rows.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Iterable, Mapping

from business.spot_fill_backfill import fill_ledger_from_rest_fill
from core.enums import (
    FillLedgerReconciliationStatus,
    SpotAuditRecordType,
    SpotFillLedgerFindingType,
    SpotFillLedgerHealthStatus,
    SpotFillLedgerRepairStatus,
)
from database.fill_ledger_lock import FILL_LEDGER_PRODUCT_LOCK_NAMESPACE


DEFAULT_QUOTE_CURRENCY = "USDC"
REPAIRABLE_FINDINGS = {
    SpotFillLedgerFindingType.NON_POSITIVE_QUANTITY.value,
    SpotFillLedgerFindingType.NON_POSITIVE_PRICE.value,
    SpotFillLedgerFindingType.ZERO_NOTIONAL.value,
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
    normalized = value.normalize()
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _json_safe(value: Any) -> Any:
    value = _enum_value(value)
    if isinstance(value, Decimal):
        return _format_decimal(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _row_identity(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "derived_trade_key": _text(row.get("derived_trade_key")),
        "client_order_id": _text(row.get("client_order_id")) or None,
        "instrument": _text(row.get("instrument")),
        "side": _text(row.get("side")).upper(),
        "exchange_trade_id": _text(row.get("exchange_trade_id")) or None,
        "exchange_entry_id": _text(row.get("exchange_entry_id")) or None,
        "reconciliation_status": _text(row.get("reconciliation_status")),
    }


def _is_quote_row(row: Mapping[str, Any], quote_currency: str) -> bool:
    instrument = _text(row.get("instrument")).upper()
    suffix = f"-{_text(quote_currency).upper()}"
    return bool(instrument and instrument.endswith(suffix))


def _finding_types_for_row(row: Mapping[str, Any]) -> list[str]:
    findings: list[str] = []
    quantity = _decimal(row.get("quantity"))
    price = _decimal(row.get("price"))
    notional = quantity * price
    if not _text(row.get("client_order_id")):
        findings.append(SpotFillLedgerFindingType.MISSING_CLIENT_ORDER_ID.value)
    if quantity <= 0:
        findings.append(SpotFillLedgerFindingType.NON_POSITIVE_QUANTITY.value)
    if price <= 0:
        findings.append(SpotFillLedgerFindingType.NON_POSITIVE_PRICE.value)
    if quantity > 0 and notional <= 0:
        findings.append(SpotFillLedgerFindingType.ZERO_NOTIONAL.value)
    if (
        _text(row.get("reconciliation_status"))
        == FillLedgerReconciliationStatus.RECONCILED.value
        and not _text(row.get("exchange_trade_id"))
        and not _text(row.get("exchange_entry_id"))
        and not _text(row.get("exchange_fill_identity_sha256"))
    ):
        findings.append(
            SpotFillLedgerFindingType.MISSING_RECONCILED_EXCHANGE_EVIDENCE.value
        )
    return findings


def _order_report_index(
    order_reports: Iterable[Mapping[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for order in order_reports or []:
        client_order_id = _text(order.get("client_order_id"))
        exchange_order_id = _text(order.get("exchange_order_id")) or _text(
            order.get("order_id")
        )
        if client_order_id and exchange_order_id:
            index.setdefault(client_order_id, dict(order))
    return index


def analyze_spot_fill_ledger_rows(
    *,
    rows: Iterable[Mapping[str, Any]],
    quote_currency: str = DEFAULT_QUOTE_CURRENCY,
    order_reports: Iterable[Mapping[str, Any]] | None = None,
    generated_at: datetime | None = None,
    include_findings: bool = True,
) -> dict[str, Any]:
    """Build a data-health report for local spot fill-ledger rows."""
    generated_at = generated_at or datetime.now(timezone.utc)
    order_index = _order_report_index(order_reports)
    scoped_rows = [
        dict(row) for row in rows if _is_quote_row(row, quote_currency)
    ]
    findings: list[dict[str, Any]] = []
    repairable_count = 0
    unrepairable_count = 0

    for row in scoped_rows:
        finding_types = _finding_types_for_row(row)
        if not finding_types:
            continue
        client_order_id = _text(row.get("client_order_id"))
        has_repairable_finding = bool(REPAIRABLE_FINDINGS.intersection(finding_types))
        order_report = order_index.get(client_order_id)
        repairable = bool(has_repairable_finding and order_report)
        if has_repairable_finding:
            if repairable:
                repairable_count += 1
            else:
                unrepairable_count += 1
        for finding_type in finding_types:
            finding = {
                "type": finding_type,
                "severity": SpotFillLedgerHealthStatus.FAILED.value,
                "row": _row_identity(row),
                "quantity": _format_decimal(_decimal(row.get("quantity"))),
                "price": _format_decimal(_decimal(row.get("price"))),
                "notional": _format_decimal(
                    _decimal(row.get("quantity")) * _decimal(row.get("price"))
                ),
                "repairable": repairable
                and finding_type in REPAIRABLE_FINDINGS,
            }
            if finding["repairable"]:
                finding["exchange_order_id"] = _text(
                    order_report.get("exchange_order_id")
                ) or _text(order_report.get("order_id"))
            elif finding_type in REPAIRABLE_FINDINGS:
                finding["repair_blocker"] = (
                    "durable exchange_order_id evidence is unavailable"
                )
            findings.append(finding)

    counts = Counter(finding["type"] for finding in findings)
    warnings = []
    if not scoped_rows:
        warnings.append(f"no {quote_currency} fill-ledger rows were found")
    status = (
        SpotFillLedgerHealthStatus.PASSED.value
        if not findings and scoped_rows
        else SpotFillLedgerHealthStatus.WARNING.value
        if not findings
        else SpotFillLedgerHealthStatus.FAILED.value
    )
    report = {
        "record_type": SpotAuditRecordType.FILL_LEDGER_HEALTH.value,
        "generated_at": generated_at.isoformat(),
        "quote_currency": _text(quote_currency).upper(),
        "status": status,
        "row_count": len(scoped_rows),
        "finding_count": len(findings),
        "finding_type_counts": dict(sorted(counts.items())),
        "repairable_finding_count": repairable_count,
        "unrepairable_finding_count": unrepairable_count,
        "warnings": warnings,
        "live_coinbase_orders_ran": False,
        "live_order_notional_usdc": "0",
        "total_submitted_notional_usdc": "0",
        "total_executed_notional_usdc": "0",
        "read_only_coinbase_requests": [],
        "live_coinbase_requests": [],
    }
    if include_findings:
        report["findings"] = findings
    return _json_safe(report)


def fetch_spot_fill_ledger_rows(
    *,
    db_client: Any,
    quote_currency: str = DEFAULT_QUOTE_CURRENCY,
    limit: int = 10000,
) -> list[dict[str, Any]]:
    """Fetch local fill-ledger rows for quote-scoped spot health checks."""
    if limit <= 0:
        raise ValueError("limit must be greater than 0")
    suffix = f"%-{_text(quote_currency).upper()}"
    query = """
    SELECT id, created_at, derived_trade_key::text AS derived_trade_key,
           exchange_trade_id::text AS exchange_trade_id, exchange_entry_id,
           exchange_fill_identity_sha256,
           instrument, side, quantity, price, timestamp, fees,
           commission_percentage, client_order_id, reconciliation_status,
           reconciled_at
      FROM fill_ledger
     WHERE UPPER(instrument) LIKE %s
     ORDER BY created_at ASC, id ASC
     LIMIT %s
    """
    return [dict(row) for row in db_client.execute_query(query, (suffix, limit))]


def _fill_value(fill: Mapping[str, Any], *names: str) -> str:
    for name in names:
        if name in fill:
            return _text(fill.get(name))
    return ""


def _match_rest_fill(
    row: Mapping[str, Any],
    fills: Iterable[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    fills = [dict(fill) for fill in fills]
    row_entry_id = _text(row.get("exchange_entry_id"))
    row_trade_id = _text(row.get("exchange_trade_id"))
    for fill in fills:
        fill_entry_id = _fill_value(fill, "entry_id", "fill_id")
        fill_trade_id = _fill_value(fill, "trade_id")
        if row_entry_id and row_entry_id in {fill_entry_id, fill_trade_id}:
            return fill
        if row_trade_id and row_trade_id == fill_trade_id:
            return fill
    if len(fills) == 1 and not row_entry_id and not row_trade_id:
        return fills[0]
    return None


def build_spot_fill_ledger_repair_actions(
    *,
    rows: Iterable[Mapping[str, Any]],
    order_reports: Iterable[Mapping[str, Any]],
    rest_fills_by_order_id: Mapping[str, Iterable[Mapping[str, Any]]],
    quote_currency: str = DEFAULT_QUOTE_CURRENCY,
) -> list[dict[str, Any]]:
    """Plan exact row updates from Coinbase REST fill evidence."""
    order_index = _order_report_index(order_reports)
    actions: list[dict[str, Any]] = []
    for row in rows:
        row = dict(row)
        if not _is_quote_row(row, quote_currency):
            continue
        finding_types = _finding_types_for_row(row)
        repair_reasons = sorted(REPAIRABLE_FINDINGS.intersection(finding_types))
        if not repair_reasons:
            continue
        row_base = {
            "row": _row_identity(row),
            "finding_types": repair_reasons,
            "old_quantity": _format_decimal(_decimal(row.get("quantity"))),
            "old_price": _format_decimal(_decimal(row.get("price"))),
            "old_fees": _format_decimal(_decimal(row.get("fees"))),
        }
        client_order_id = _text(row.get("client_order_id"))
        order_report = order_index.get(client_order_id)
        if not order_report:
            actions.append({
                **row_base,
                "status": SpotFillLedgerRepairStatus.SKIPPED.value,
                "reason": "durable exchange_order_id evidence is unavailable",
            })
            continue
        exchange_order_id = _text(order_report.get("exchange_order_id")) or _text(
            order_report.get("order_id")
        )
        fills = list(rest_fills_by_order_id.get(exchange_order_id) or [])
        matched_fill = _match_rest_fill(row, fills)
        if matched_fill is None:
            actions.append({
                **row_base,
                "status": SpotFillLedgerRepairStatus.FAILED.value,
                "exchange_order_id": exchange_order_id,
                "reason": "matching REST fill was not found",
            })
            continue
        product_id = _text(order_report.get("product_id")) or _text(row.get("instrument"))
        side = _text(order_report.get("side")).upper() or _text(row.get("side")).upper()
        repaired = fill_ledger_from_rest_fill(
            fill=matched_fill,
            client_order_id=client_order_id,
            exchange_order_id=exchange_order_id,
            product_id=product_id,
            side=side,
            fallback_index=0,
        )
        if repaired is None:
            actions.append({
                **row_base,
                "status": SpotFillLedgerRepairStatus.FAILED.value,
                "exchange_order_id": exchange_order_id,
                "reason": "REST fill could not be converted to a fill-ledger row",
            })
            continue
        new_quantity = _decimal(repaired.quantity)
        new_price = _decimal(repaired.price)
        actions.append({
            **row_base,
            "status": SpotFillLedgerRepairStatus.PLANNED.value,
            "exchange_order_id": exchange_order_id,
            "new_quantity": _format_decimal(new_quantity),
            "new_price": _format_decimal(new_price),
            "new_fees": _format_decimal(_decimal(repaired.fees)),
            "new_notional_usdc": _format_decimal(new_quantity * new_price),
            "new_exchange_trade_id": repaired.exchange_trade_id,
            "new_exchange_entry_id": repaired.exchange_entry_id,
            "new_reconciliation_status": (
                FillLedgerReconciliationStatus.RECONCILED.value
            ),
        })
    return _json_safe(actions)


def apply_spot_fill_ledger_repair_actions(
    *,
    db_client: Any,
    actions: Iterable[Mapping[str, Any]],
    apply: bool,
) -> dict[str, Any]:
    """Dry-run or apply exact fill-ledger row repairs."""
    results: list[dict[str, Any]] = []
    for action in actions:
        action = dict(action)
        if action.get("status") != SpotFillLedgerRepairStatus.PLANNED.value:
            results.append(action)
            continue
        if not apply:
            results.append({
                **action,
                "status": SpotFillLedgerRepairStatus.DRY_RUN.value,
            })
            continue
        row = action.get("row") or {}
        row_id = row.get("id")
        derived_trade_key = row.get("derived_trade_key")
        if not row_id or not derived_trade_key:
            results.append({
                **action,
                "status": SpotFillLedgerRepairStatus.FAILED.value,
                "reason": "row id and derived_trade_key are required for repair",
            })
            continue
        query = """
        WITH target_product AS MATERIALIZED (
            SELECT instrument
            FROM fill_ledger
            WHERE id = %s
              AND derived_trade_key = %s
        ),
        product_lock AS MATERIALIZED (
            SELECT pg_advisory_xact_lock(
                hashtext(%s || target_product.instrument)
            )
            FROM target_product
        )
        UPDATE fill_ledger AS target
           SET quantity = %s,
               price = %s,
               fees = %s,
               commission_percentage = %s,
               exchange_trade_id = %s,
               exchange_entry_id = %s,
               reconciliation_status = %s,
               reconciled_at = CURRENT_TIMESTAMP
          FROM product_lock
         WHERE target.id = %s
           AND target.derived_trade_key = %s
        """
        params = (
            row_id,
            derived_trade_key,
            FILL_LEDGER_PRODUCT_LOCK_NAMESPACE,
            action["new_quantity"],
            action["new_price"],
            action["new_fees"],
            "0",
            action.get("new_exchange_trade_id"),
            action.get("new_exchange_entry_id"),
            action["new_reconciliation_status"],
            row_id,
            derived_trade_key,
        )
        try:
            rows_updated = db_client.execute_update(query, params)
        except Exception as exc:
            results.append({
                **action,
                "status": SpotFillLedgerRepairStatus.FAILED.value,
                "reason": f"{type(exc).__name__}: {exc}",
            })
            continue
        results.append({
            **action,
            "status": (
                SpotFillLedgerRepairStatus.APPLIED.value
                if rows_updated == 1
                else SpotFillLedgerRepairStatus.FAILED.value
            ),
            "rows_updated": rows_updated,
            **({} if rows_updated == 1 else {"reason": "repair update matched no rows"}),
        })
    counts = Counter(_text(result.get("status")) for result in results)
    failures = [
        result for result in results
        if result.get("status") == SpotFillLedgerRepairStatus.FAILED.value
    ]
    return _json_safe({
        "record_type": SpotAuditRecordType.FILL_LEDGER_REPAIR.value,
        "dry_run": not apply,
        "status": (
            SpotFillLedgerRepairStatus.FAILED.value
            if failures
            else SpotFillLedgerRepairStatus.APPLIED.value
            if apply
            else SpotFillLedgerRepairStatus.DRY_RUN.value
        ),
        "action_count": len(results),
        "status_counts": dict(sorted(counts.items())),
        "actions": results,
        "live_coinbase_orders_ran": False,
        "live_order_notional_usdc": "0",
        "total_submitted_notional_usdc": "0",
        "total_executed_notional_usdc": "0",
    })
