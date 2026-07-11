"""Backfill Coinbase REST fills into the local fill ledger.

This module is for explicit REST backfill after live spot smoke or sweep runs.
It does not replace the WS-derived fill pipeline or the WS-vs-REST reconciler;
it creates deterministic REST-derived rows when a live test/sweep needs durable
lot/P&L evidence and the WS path has not written local fills.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Iterable, Mapping

from business.fill_ledger import FillLedger
from core.enums import (
    FillLedgerReconciliationStatus,
    OrderSide,
    SpotFillBackfillStatus,
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


def _get_value(source: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(source, Mapping) and name in source:
            return source[name]
        if hasattr(source, name):
            return getattr(source, name)
    return default


def _dict_response(response: Any) -> Any:
    converter = getattr(response, "to_dict", None)
    if callable(converter):
        return converter()
    return response


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        timestamp = value
    else:
        text = _text(value)
        if not text:
            return datetime.now(timezone.utc)
        try:
            timestamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp


def fetch_rest_fills_for_order(
    rest_client: Any,
    *,
    exchange_order_id: str,
    product_id: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch REST fills for one exchange order id from either wrapper shape."""
    if not exchange_order_id:
        return []
    lister = getattr(rest_client, "list_fills", None)
    if callable(lister):
        response = lister(
            order_id=exchange_order_id,
            limit=100,
        )
    else:
        getter = getattr(rest_client, "get_fills", None)
        if not callable(getter):
            return []
        response = getter(order_ids=[exchange_order_id], limit=100)
    data = _dict_response(response) or {}
    if isinstance(data, Mapping):
        return [dict(fill) for fill in (data.get("fills") or []) if isinstance(fill, Mapping)]
    return []


def fill_ledger_from_rest_fill(
    *,
    fill: Mapping[str, Any],
    client_order_id: str,
    exchange_order_id: str,
    product_id: str,
    side: str,
    fallback_index: int,
) -> FillLedger | None:
    """Convert one Coinbase REST fill dict into an idempotent FillLedger row."""
    product_id = (
        _text(_get_value(fill, "product_id", "instrument"))
        or _text(product_id)
    )
    side_value = (
        _text(_get_value(fill, "side")).upper()
        or _text(side).upper()
    )
    try:
        side_value = OrderSide(side_value).value
    except ValueError:
        return None

    price = _decimal(_get_value(fill, "price"))
    raw_size = _decimal(_get_value(fill, "size", "base_size"))
    if raw_size <= 0 or price <= 0:
        return None

    size_in_quote = bool(_get_value(fill, "size_in_quote"))
    quantity = raw_size / price if size_in_quote else raw_size
    if quantity <= 0:
        return None

    entry_id = _text(_get_value(fill, "entry_id", "trade_id", "fill_id"))
    trade_id = _text(_get_value(fill, "trade_id"))
    idempotency_key = "|".join([
        "coinbase-rest-fill",
        _text(client_order_id),
        _text(exchange_order_id),
        entry_id or trade_id or str(fallback_index),
    ])
    derived_trade_key = str(uuid.uuid5(uuid.NAMESPACE_OID, idempotency_key))
    fees = _decimal(
        _get_value(
            fill,
            "commission",
            "fee",
            "fees",
            default="0",
        )
    )
    return FillLedger(
        derived_trade_key=derived_trade_key,
        instrument=product_id,
        side=side_value,
        quantity=float(quantity),
        price=float(price),
        timestamp=_timestamp(_get_value(fill, "trade_time", "created_at", "time")),
        fees=float(fees),
        commission_percentage=0.0,
        order_side=OrderSide(side_value),
        client_order_id=_text(client_order_id) or None,
        product_id=product_id,
        average_price=float(price),
        exchange_trade_id=trade_id or None,
        exchange_entry_id=entry_id or None,
        reconciliation_status=FillLedgerReconciliationStatus.RECONCILED.value,
    )


@dataclass(frozen=True)
class SpotFillBackfillOrderReport:
    product_id: str
    side: str
    client_order_id: str | None
    exchange_order_id: str | None
    fetched_fill_count: int
    appended_fill_count: int
    skipped_fill_count: int
    status: str
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "side": self.side,
            "client_order_id": self.client_order_id,
            "exchange_order_id": self.exchange_order_id,
            "fetched_fill_count": self.fetched_fill_count,
            "appended_fill_count": self.appended_fill_count,
            "skipped_fill_count": self.skipped_fill_count,
            "status": self.status,
            "error": self.error,
        }


def backfill_fill_ledger_from_order_reports(
    *,
    fill_ledger_repo: Any,
    rest_client: Any,
    order_reports: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Fetch REST fills for submitted orders and append fill-ledger rows."""
    reports: list[SpotFillBackfillOrderReport] = []
    total_fetched = 0
    total_appended = 0
    total_skipped = 0
    for order in order_reports:
        exchange_order_id = _text(
            _get_value(order, "exchange_order_id", "order_id")
        )
        client_order_id = _text(_get_value(order, "client_order_id")) or None
        product_id = _text(_get_value(order, "product_id"))
        side = _text(_get_value(order, "side")).upper()
        if not exchange_order_id or not client_order_id:
            reports.append(
                SpotFillBackfillOrderReport(
                    product_id=product_id,
                    side=side,
                    client_order_id=client_order_id,
                    exchange_order_id=exchange_order_id or None,
                    fetched_fill_count=0,
                    appended_fill_count=0,
                    skipped_fill_count=0,
                    status=SpotFillBackfillStatus.SKIPPED.value,
                    error="exchange_order_id and client_order_id are required",
                )
            )
            continue
        try:
            fills = fetch_rest_fills_for_order(
                rest_client,
                exchange_order_id=exchange_order_id,
                product_id=product_id,
            )
            fetched = len(fills)
            appended = 0
            skipped = 0
            append_errors = 0
            for index, fill in enumerate(fills):
                ledger_row = fill_ledger_from_rest_fill(
                    fill=fill,
                    client_order_id=client_order_id,
                    exchange_order_id=exchange_order_id,
                    product_id=product_id,
                    side=side,
                    fallback_index=index,
                )
                if ledger_row is None:
                    skipped += 1
                    continue
                if fill_ledger_repo.append_fill(ledger_row):
                    appended += 1
                else:
                    append_errors += 1
            total_fetched += fetched
            total_appended += appended
            total_skipped += skipped + append_errors
            if append_errors:
                status = SpotFillBackfillStatus.ERROR.value
                error = f"{append_errors} fill-ledger append(s) failed"
            elif appended:
                status = SpotFillBackfillStatus.APPENDED.value
            elif fetched:
                status = SpotFillBackfillStatus.DUPLICATE_OR_ACCEPTED.value
            else:
                status = SpotFillBackfillStatus.SKIPPED.value
            if not append_errors:
                error = None
            reports.append(
                SpotFillBackfillOrderReport(
                    product_id=product_id,
                    side=side,
                    client_order_id=client_order_id,
                    exchange_order_id=exchange_order_id,
                    fetched_fill_count=fetched,
                    appended_fill_count=appended,
                    skipped_fill_count=skipped + append_errors,
                    status=status,
                    error=error,
                )
            )
        except Exception as exc:
            reports.append(
                SpotFillBackfillOrderReport(
                    product_id=product_id,
                    side=side,
                    client_order_id=client_order_id,
                    exchange_order_id=exchange_order_id,
                    fetched_fill_count=0,
                    appended_fill_count=0,
                    skipped_fill_count=0,
                    status=SpotFillBackfillStatus.ERROR.value,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
    return {
        "total_order_count": len(reports),
        "total_fetched_fill_count": total_fetched,
        "total_appended_fill_count": total_appended,
        "total_skipped_fill_count": total_skipped,
        "orders": [report.to_dict() for report in reports],
    }
