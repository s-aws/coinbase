"""Read-only audit helpers for manual direct spot orders.

Direct dashboard ``place_order`` is intentionally a manual one-off path. These
helpers reconstruct what local evidence exists for one ``client_order_id`` so
operators can inspect a direct order without adding a second automation path.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Iterable, Mapping

from core.enums import (
    EventSourceChannel,
    EventStreamType,
    SpotAuditRecordType,
    SpotDirectOrderAuditStatus,
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


def _event_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = row.get("raw_payload_json")
    if isinstance(payload, Mapping):
        return dict(payload)
    return {}


def fetch_direct_order_event_rows(
    *,
    db_client: Any,
    client_order_id: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Fetch local event-stream rows for one direct-order client id."""
    client_order_id = _text(client_order_id)
    if not client_order_id:
        return []
    if limit <= 0:
        raise ValueError("limit must be greater than 0")
    query = """
    SELECT id, created_at, event_id::text AS event_id,
           event_time_exchange, event_time_ingested, product_id,
           client_order_id, order_id, parent_client_order_id,
           stealth_order_id, event_type, event_status_from,
           event_status_to, side, price, size, cumulative_filled_size,
           leaves_size, fee, fee_currency, trigger_type,
           trigger_payload_json, source_channel, raw_payload_json,
           idempotency_key
      FROM order_event_stream
     WHERE client_order_id = %s
     ORDER BY created_at ASC, id ASC
     LIMIT %s
    """
    return [
        dict(row)
        for row in db_client.execute_query(query, (client_order_id, limit))
    ]


def fetch_direct_order_fill_rows(
    *,
    db_client: Any,
    client_order_id: str,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Fetch local fill-ledger rows for one direct-order client id."""
    client_order_id = _text(client_order_id)
    if not client_order_id:
        return []
    if limit <= 0:
        raise ValueError("limit must be greater than 0")
    query = """
    SELECT id, created_at, derived_trade_key::text AS derived_trade_key,
           exchange_trade_id::text AS exchange_trade_id, exchange_entry_id,
           instrument, side, quantity, price, timestamp, fees,
           commission_percentage, client_order_id, reconciliation_status,
           reconciled_at
      FROM fill_ledger
     WHERE client_order_id = %s
     ORDER BY timestamp ASC, created_at ASC, id ASC
     LIMIT %s
    """
    return [
        dict(row)
        for row in db_client.execute_query(query, (client_order_id, limit))
    ]


def _submission_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in rows
        if _text(row.get("event_type")) == EventStreamType.ORDER_SUBMITTED.value
        and _text(row.get("source_channel")) == EventSourceChannel.REST_SUBMIT.value
    ]


def _submission_summary(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    payload = _event_payload(row)
    return {
        "product_id": _text(row.get("product_id")) or _text(payload.get("product_id")),
        "side": _text(row.get("side")) or _text(payload.get("side")),
        "client_order_id": _text(row.get("client_order_id")),
        "exchange_order_id": _text(row.get("order_id")) or None,
        "event_id": _text(row.get("event_id")),
        "event_type": _text(row.get("event_type")),
        "source_channel": _text(row.get("source_channel")),
        "event_status_to": _text(row.get("event_status_to")) or None,
        "order_configuration_type": _text(
            payload.get("order_configuration_type")
        ) or None,
        "base_size": _text(payload.get("base_size")) or None,
        "quote_size": _text(payload.get("quote_size")) or None,
        "limit_price": _text(payload.get("limit_price")) or None,
        "post_only": payload.get("post_only"),
    }


def _event_summary(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "event_id": _text(row.get("event_id")),
        "event_type": _text(row.get("event_type")),
        "source_channel": _text(row.get("source_channel")),
        "product_id": _text(row.get("product_id")) or None,
        "side": _text(row.get("side")) or None,
        "order_id": _text(row.get("order_id")) or None,
        "event_status_to": _text(row.get("event_status_to")) or None,
        "created_at": row.get("created_at"),
        "event_time_exchange": row.get("event_time_exchange"),
    }


def _fill_summary(row: Mapping[str, Any]) -> dict[str, Any]:
    quantity = _decimal(row.get("quantity"))
    price = _decimal(row.get("price"))
    fees = _decimal(row.get("fees"))
    return {
        "id": row.get("id"),
        "derived_trade_key": _text(row.get("derived_trade_key")),
        "instrument": _text(row.get("instrument")),
        "side": _text(row.get("side")).upper(),
        "quantity": _format_decimal(quantity),
        "price": _format_decimal(price),
        "fees": _format_decimal(fees),
        "notional": _format_decimal(quantity * price),
        "timestamp": row.get("timestamp"),
        "exchange_trade_id": _text(row.get("exchange_trade_id")) or None,
        "exchange_entry_id": _text(row.get("exchange_entry_id")) or None,
        "reconciliation_status": _text(row.get("reconciliation_status")) or None,
    }


def build_spot_direct_order_audit(
    *,
    client_order_id: str,
    event_rows: Iterable[Mapping[str, Any]],
    fill_rows: Iterable[Mapping[str, Any]],
    generated_at: datetime | None = None,
    include_events: bool = True,
    include_fills: bool = True,
) -> dict[str, Any]:
    """Build a read-only local audit for one manual direct order."""
    generated_at = generated_at or datetime.now(timezone.utc)
    client_order_id = _text(client_order_id)
    rows = [dict(row) for row in event_rows]
    fills = [dict(row) for row in fill_rows]
    submissions = _submission_rows(rows)
    submission = submissions[-1] if submissions else None
    event_type_counts = Counter(_text(row.get("event_type")) for row in rows)
    source_counts = Counter(_text(row.get("source_channel")) for row in rows)
    fill_notional = sum(
        (
            _decimal(row.get("quantity")) * _decimal(row.get("price"))
            for row in fills
        ),
        Decimal("0"),
    )
    fill_fees = sum(
        (_decimal(row.get("fees")) for row in fills),
        Decimal("0"),
    )

    if not client_order_id:
        status = SpotDirectOrderAuditStatus.MISSING_CLIENT_ORDER_ID.value
    elif submission is None:
        status = SpotDirectOrderAuditStatus.MISSING_SUBMISSION.value
    else:
        status = SpotDirectOrderAuditStatus.FOUND.value

    report = {
        "record_type": SpotAuditRecordType.DIRECT_ORDER_AUDIT.value,
        "generated_at": generated_at.isoformat(),
        "status": status,
        "client_order_id": client_order_id or None,
        "submission": _submission_summary(submission),
        "event_count": len(rows),
        "submission_event_count": len(submissions),
        "event_type_counts": dict(sorted(event_type_counts.items())),
        "source_channel_counts": dict(sorted(source_counts.items())),
        "fill_count": len(fills),
        "fill_notional": _format_decimal(fill_notional),
        "fill_fees": _format_decimal(fill_fees),
        "live_coinbase_orders_ran": False,
        "live_order_notional_usdc": "0",
        "total_submitted_notional_usdc": "0",
        "total_executed_notional_usdc": "0",
        "read_only_coinbase_requests": [],
        "live_coinbase_requests": [],
    }
    if include_events:
        report["events"] = [_event_summary(row) for row in rows]
    if include_fills:
        report["fills"] = [_fill_summary(row) for row in fills]
    return _json_safe(report)
