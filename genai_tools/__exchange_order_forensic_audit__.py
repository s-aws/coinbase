"""Forensic audit utility for a Coinbase exchange order ID.

Usage:
    python genai_tools/__exchange_order_forensic_audit__.py --exchange-order-id <uuid>

What it does:
- Resolves the associated client_order_id from order_event_stream.
- Pulls timeline rows from order_event_stream.
- Pulls reveal/lifecycle context from stealth audit tables.
- Pulls parent and stealth order linkage context.
- Prints a compact report and Mermaid sequence diagram markup.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.order import DB_CLIENT


def _to_plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _to_plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_plain(v) for v in value]
    return value


def _query(sql: str, params: tuple) -> List[Dict[str, Any]]:
    rows = DB_CLIENT.execute_query(sql, params)
    return [_to_plain(r) for r in rows]


def resolve_client_order_ids(exchange_order_id: str) -> List[str]:
    sql = (
        "SELECT DISTINCT client_order_id "
        "FROM order_event_stream "
        "WHERE order_id = %s "
        "  AND client_order_id IS NOT NULL "
        "ORDER BY client_order_id"
    )
    rows = _query(sql, (exchange_order_id,))
    return [r["client_order_id"] for r in rows]


def fetch_order_event_stream(exchange_order_id: str, client_order_id: str) -> List[Dict[str, Any]]:
    sql = (
        "SELECT id, created_at, event_type, source_channel, event_status_to, "
        "       client_order_id, order_id, product_id, side, price, size, fee, "
        "       raw_payload_json "
        "FROM order_event_stream "
        "WHERE order_id = %s OR client_order_id = %s "
        "ORDER BY created_at, id"
    )
    return _query(sql, (exchange_order_id, client_order_id))


def fetch_reveal_history(exchange_order_id: str, client_order_id: str) -> List[Dict[str, Any]]:
    sql = (
        "SELECT id, created_at, stealth_order_id, reveal_number, revealed_size, placement_price, "
        "       placed_order_id, exchange_order_id, market_price, market_bid, market_ask, "
        "       reveal_trigger_reason, reveal_trigger_data "
        "FROM stealth_order_reveal_history "
        "WHERE exchange_order_id = %s OR placed_order_id::text = %s "
        "ORDER BY created_at, id"
    )
    return _query(sql, (exchange_order_id, client_order_id))


def fetch_lifecycle_history(exchange_order_id: str, client_order_id: str) -> List[Dict[str, Any]]:
    sql = (
        "SELECT id, created_at, stealth_order_id, lifecycle_event, status_from, status_to, "
        "       event_time, product_id, side, size, total_size, limit_price, reason, "
        "       parent_order_id, placed_order_id, exchange_order_id, failure_reason "
        "FROM stealth_order_lifecycle_history "
        "WHERE exchange_order_id = %s OR placed_order_id::text = %s "
        "ORDER BY created_at, id"
    )
    return _query(sql, (exchange_order_id, client_order_id))


def fetch_parent_row(client_order_id: str) -> List[Dict[str, Any]]:
    sql = (
        "SELECT id, client_order_id, product_id, side, size, price, status, "
        "       target_movement, target_movement_type, max_order_replacement, current_order_replacement "
        "FROM order_parent WHERE client_order_id = %s"
    )
    return _query(sql, (client_order_id,))


def fetch_stealth_rows(exchange_order_id: str, client_order_id: str) -> List[Dict[str, Any]]:
    sql = (
        "SELECT stealth_order_id, parent_order_id, product_id, side, total_size, revealed_size, remaining_size, "
        "       executed_size, limit_price, status, reveal_condition_type, reveal_condition_json, "
        "       reason, last_lifecycle_event, failure_reason, revealed_orders "
        "FROM stealth_orders "
        "WHERE stealth_order_id::text = %s "
        "   OR parent_order_id::text = %s "
        "   OR revealed_orders::text LIKE %s "
        "ORDER BY created_at"
    )
    return _query(sql, (client_order_id, client_order_id, f"%{exchange_order_id}%"))


def _mermaid(events: List[Dict[str, Any]], lifecycle: List[Dict[str, Any]], reveal: List[Dict[str, Any]]) -> str:
    lines: List[str] = [
        "sequenceDiagram",
        "    autonumber",
        "    participant SM as Stealth Manager",
        "    participant REST as Coinbase REST",
        "    participant WS as Coinbase WS",
        "    participant OES as order_event_stream",
        "    participant SLH as stealth_order_lifecycle_history",
        "    participant SRH as stealth_order_reveal_history",
    ]

    if any(e.get("event_type") == "stealth_condition_met" for e in events):
        lines.append("    SM->>OES: stealth_condition_met")

    if any(e.get("event_type") == "order_submitted" for e in events):
        lines.append("    SM->>REST: submit order")
        lines.append("    REST-->>SM: order accepted")
        lines.append("    SM->>OES: order_submitted")

    if any(e.get("event_type") == "stealth_revealed" for e in events):
        lines.append("    SM->>OES: stealth_revealed")

    for row in reveal:
        rn = row.get("reveal_number")
        lines.append(f"    SM->>SRH: reveal_history row (reveal #{rn})")

    for row in events:
        et = row.get("event_type")
        if et in {"order_open", "order_filled", "order_cancelled", "order_failed"}:
            lines.append(f"    WS-->>OES: {et}")

    for row in lifecycle:
        evt = row.get("lifecycle_event")
        if evt:
            lines.append(f"    SM->>SLH: {evt}")

    return "\n".join(lines)


def run(exchange_order_id: str) -> None:
    client_order_ids = resolve_client_order_ids(exchange_order_id)
    if not client_order_ids:
        print(f"No order_event_stream rows found for exchange order id: {exchange_order_id}")
        return

    if len(client_order_ids) > 1:
        print("Warning: multiple client_order_id values found. Showing each in sequence.")

    for client_order_id in client_order_ids:
        print("=" * 80)
        print(f"Exchange order id: {exchange_order_id}")
        print(f"Client order id:   {client_order_id}")

        events = fetch_order_event_stream(exchange_order_id, client_order_id)
        reveal = fetch_reveal_history(exchange_order_id, client_order_id)
        lifecycle = fetch_lifecycle_history(exchange_order_id, client_order_id)
        parent_rows = fetch_parent_row(client_order_id)
        stealth_rows = fetch_stealth_rows(exchange_order_id, client_order_id)

        print("\n-- Event timeline --")
        for e in events:
            print(
                f"[{e.get('created_at')}] id={e.get('id')} {e.get('event_type')} "
                f"status={e.get('event_status_to')} side={e.get('side')} "
                f"price={e.get('price')} fee={e.get('fee')}"
            )

        print("\n-- Reveal history rows --")
        print(json.dumps(reveal, indent=2, default=str))

        print("\n-- Lifecycle history rows --")
        print(json.dumps(lifecycle, indent=2, default=str))

        print("\n-- Parent row --")
        print(json.dumps(parent_rows, indent=2, default=str))

        print("\n-- Stealth rows (original + follow-ups) --")
        print(json.dumps(stealth_rows, indent=2, default=str))

        print("\n-- Mermaid diagram --")
        print(_mermaid(events, lifecycle, reveal))


def run_with_options(exchange_order_id: str, mermaid_out: Optional[str] = None) -> None:
    client_order_ids = resolve_client_order_ids(exchange_order_id)
    if not client_order_ids:
        print(f"No order_event_stream rows found for exchange order id: {exchange_order_id}")
        return

    all_mermaid_blocks: List[str] = []

    for client_order_id in client_order_ids:
        print("=" * 80)
        print(f"Exchange order id: {exchange_order_id}")
        print(f"Client order id:   {client_order_id}")

        events = fetch_order_event_stream(exchange_order_id, client_order_id)
        reveal = fetch_reveal_history(exchange_order_id, client_order_id)
        lifecycle = fetch_lifecycle_history(exchange_order_id, client_order_id)
        parent_rows = fetch_parent_row(client_order_id)
        stealth_rows = fetch_stealth_rows(exchange_order_id, client_order_id)

        print("\n-- Event timeline --")
        for e in events:
            print(
                f"[{e.get('created_at')}] id={e.get('id')} {e.get('event_type')} "
                f"status={e.get('event_status_to')} side={e.get('side')} "
                f"price={e.get('price')} fee={e.get('fee')}"
            )

        print("\n-- Reveal history rows --")
        print(json.dumps(reveal, indent=2, default=str))

        print("\n-- Lifecycle history rows --")
        print(json.dumps(lifecycle, indent=2, default=str))

        print("\n-- Parent row --")
        print(json.dumps(parent_rows, indent=2, default=str))

        print("\n-- Stealth rows (original + follow-ups) --")
        print(json.dumps(stealth_rows, indent=2, default=str))

        mermaid = _mermaid(events, lifecycle, reveal)
        print("\n-- Mermaid diagram --")
        print(mermaid)
        all_mermaid_blocks.append(mermaid)

    if mermaid_out:
        out_path = Path(mermaid_out)
        if not out_path.is_absolute():
            out_path = PROJECT_ROOT / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)

        merged_mermaid = "\n\n".join(all_mermaid_blocks) + "\n"
        out_path.write_text(merged_mermaid, encoding="utf-8")
        print(f"\nMermaid written to: {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Forensic audit for Coinbase exchange order IDs")
    parser.add_argument("--exchange-order-id", required=True, help="Coinbase exchange order UUID")
    parser.add_argument(
        "--mermaid-out",
        required=False,
        help="Optional path to write Mermaid markup (.mmd recommended)",
    )
    args = parser.parse_args()
    run_with_options(args.exchange_order_id, mermaid_out=args.mermaid_out)


if __name__ == "__main__":
    main()
