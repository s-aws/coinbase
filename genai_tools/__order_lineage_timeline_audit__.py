from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from database.database import PostgresDB


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _safe_iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _in_clause(values: Sequence[Any]) -> Tuple[str, Tuple[Any, ...]]:
    if not values:
        return "(NULL)", tuple()
    placeholders = ", ".join(["%s"] * len(values))
    return f"({placeholders})", tuple(values)


def _resolve_seed_id(db: PostgresDB, args: argparse.Namespace) -> Optional[str]:
    if args.client_order_id:
        return args.client_order_id

    if args.stealth_order_id:
        return args.stealth_order_id

    rows = db.execute_query(
        """
        SELECT client_order_id
        FROM order_parent
        ORDER BY created_at DESC
        LIMIT 1
        """
    )
    return rows[0]["client_order_id"] if rows else None


def _resolve_root_parent_id(db: PostgresDB, seed_id: str) -> str:
    rows = db.execute_query(
        """
        WITH RECURSIVE ancestors AS (
            SELECT
                op.client_order_id,
                op.parent_order_id,
                0 AS depth
            FROM order_parent op
            WHERE op.client_order_id = %s

            UNION ALL

            SELECT
                p.client_order_id,
                p.parent_order_id,
                a.depth + 1 AS depth
            FROM order_parent p
            INNER JOIN ancestors a
                    ON a.parent_order_id = p.client_order_id
        )
        SELECT client_order_id
        FROM ancestors
        WHERE parent_order_id IS NULL
        ORDER BY depth DESC
        LIMIT 1
        """,
        (seed_id,),
    )
    if rows:
        return rows[0]["client_order_id"]
    return seed_id


def _load_lineage_nodes(db: PostgresDB, root_parent_id: str) -> List[Dict[str, Any]]:
    rows = db.execute_query(
        """
        WITH RECURSIVE descendants AS (
            SELECT
                op.client_order_id,
                op.parent_order_id,
                0 AS depth
            FROM order_parent op
            WHERE op.client_order_id = %s

            UNION ALL

            SELECT
                c.client_order_id,
                c.parent_order_id,
                d.depth + 1 AS depth
            FROM order_parent c
            INNER JOIN descendants d
                    ON c.parent_order_id = d.client_order_id
        )
        SELECT
            d.client_order_id,
            d.parent_order_id,
            d.depth,
            op.created_at AS parent_created_at,
            op.product_id,
            op.side,
            op.size,
            op.price,
            op.status AS parent_status,
            op.current_order_replacement,
            op.max_order_replacement,
            so.reason AS stealth_reason,
            so.status AS stealth_status,
            so.last_lifecycle_event
        FROM descendants d
        LEFT JOIN order_parent op
               ON op.client_order_id = d.client_order_id
        LEFT JOIN stealth_orders so
               ON so.stealth_order_id::text = d.client_order_id
        ORDER BY d.depth, op.created_at
        """,
        (root_parent_id,),
    )
    return rows


def _relation_kind(parent_order_id: Optional[str], stealth_reason: Optional[str]) -> str:
    if not parent_order_id:
        return "root"
    reason = (stealth_reason or "").lower()
    if "replacement" in reason:
        return "move_replacement"
    if "move" in reason:
        return "move"
    return "child_follow_up"


def _load_timeline_events(
    db: PostgresDB,
    lineage_ids: List[str],
    limit_events: int,
) -> List[Dict[str, Any]]:
    if not lineage_ids:
        return []

    in_sql, in_params = _in_clause(lineage_ids)
    half_limit = max(50, limit_events)

    parent_events = db.execute_query(
        f"""
        SELECT
            op.created_at AS event_time,
            'order_parent'::text AS source_table,
            'parent_order_created'::text AS event_type,
            op.client_order_id,
            NULL::text AS exchange_order_id,
            op.parent_order_id,
            op.product_id,
            op.side,
            op.price,
            op.size,
            op.status,
            NULL::jsonb AS payload
        FROM order_parent op
        WHERE op.client_order_id IN {in_sql}
        ORDER BY op.created_at ASC
        LIMIT %s
        """,
        in_params + (half_limit,),
    )

    stream_events = db.execute_query(
        f"""
        SELECT
            COALESCE(oes.event_time_ingested, oes.created_at) AS event_time,
            'order_event_stream'::text AS source_table,
            oes.event_type::text AS event_type,
            COALESCE(oes.client_order_id, oes.stealth_order_id::text) AS client_order_id,
            oes.order_id AS exchange_order_id,
            oes.parent_client_order_id AS parent_order_id,
            oes.product_id,
            oes.side,
            oes.price,
            oes.size,
            COALESCE(oes.event_status_to, oes.event_status_from) AS status,
            oes.trigger_payload_json AS payload
        FROM order_event_stream oes
        WHERE (
            (oes.client_order_id IS NOT NULL AND oes.client_order_id IN {in_sql})
            OR (oes.stealth_order_id IS NOT NULL AND oes.stealth_order_id::text IN {in_sql})
            OR (oes.parent_client_order_id IS NOT NULL AND oes.parent_client_order_id IN {in_sql})
        )
        ORDER BY COALESCE(oes.event_time_ingested, oes.created_at) ASC
        LIMIT %s
        """,
        in_params + in_params + in_params + (half_limit,),
    )

    lifecycle_events = db.execute_query(
        f"""
        SELECT
            COALESCE(lh.event_time, lh.created_at) AS event_time,
            'stealth_order_lifecycle_history'::text AS source_table,
            lh.lifecycle_event::text AS event_type,
            lh.stealth_order_id::text AS client_order_id,
            lh.exchange_order_id,
            lh.parent_order_id::text AS parent_order_id,
            lh.product_id,
            lh.side,
            lh.limit_price AS price,
            lh.size,
            lh.status_to AS status,
            lh.context_json AS payload
        FROM stealth_order_lifecycle_history lh
        WHERE lh.stealth_order_id::text IN {in_sql}
        ORDER BY COALESCE(lh.event_time, lh.created_at) ASC
        LIMIT %s
        """,
        in_params + (half_limit,),
    )

    reveal_events = db.execute_query(
        f"""
        SELECT
            COALESCE((rh.reveal_trigger_data ->> 'reveal_time')::timestamp, rh.created_at) AS event_time,
            'stealth_order_reveal_history'::text AS source_table,
            'reveal_recorded'::text AS event_type,
            rh.placed_order_id AS client_order_id,
            rh.exchange_order_id,
            rh.stealth_order_id::text AS parent_order_id,
            so.product_id,
            so.side,
            COALESCE(rh.placement_price, so.limit_price) AS price,
            rh.revealed_size AS size,
            so.status,
            jsonb_build_object(
                'reveal_number', rh.reveal_number,
                'reveal_trigger_reason', rh.reveal_trigger_reason,
                'reveal_trigger_data', rh.reveal_trigger_data,
                'market_price', rh.market_price,
                'market_bid', rh.market_bid,
                'market_ask', rh.market_ask,
                'market_spread', rh.market_spread,
                'market_volume_1m', rh.market_volume_1m
            ) AS payload
        FROM stealth_order_reveal_history rh
        LEFT JOIN stealth_orders so
               ON so.stealth_order_id = rh.stealth_order_id
        WHERE rh.stealth_order_id::text IN {in_sql}
           OR rh.placed_order_id IN {in_sql}
        ORDER BY COALESCE((rh.reveal_trigger_data ->> 'reveal_time')::timestamp, rh.created_at) ASC
        LIMIT %s
        """,
        in_params + in_params + (half_limit,),
    )

    fill_events = db.execute_query(
        f"""
        SELECT
            fl.timestamp AS event_time,
            'fill_ledger'::text AS source_table,
            'fill_ledger_recorded'::text AS event_type,
            fl.client_order_id,
            NULL::text AS exchange_order_id,
            NULL::text AS parent_order_id,
            fl.instrument AS product_id,
            fl.side,
            fl.price,
            fl.quantity AS size,
            NULL::text AS status,
            jsonb_build_object('trade_id', fl.trade_id, 'fees', fl.fees, 'commission_percentage', fl.commission_percentage) AS payload
        FROM fill_ledger fl
        WHERE fl.client_order_id IN {in_sql}
        ORDER BY fl.timestamp ASC
        LIMIT %s
        """,
        in_params + (half_limit,),
    )

    merged = parent_events + stream_events + lifecycle_events + reveal_events + fill_events

    def _event_sort_key(item: Dict[str, Any]) -> Tuple[str, str, str]:
        event_time = _safe_iso(item.get("event_time")) or ""
        source = str(item.get("source_table") or "")
        event_type = str(item.get("event_type") or "")
        return (event_time, source, event_type)

    merged.sort(key=_event_sort_key)
    if len(merged) > limit_events:
        merged = merged[-limit_events:]
    return merged


def _build_output(
    seed_id: str,
    root_parent_id: str,
    nodes: List[Dict[str, Any]],
    events: List[Dict[str, Any]],
) -> Dict[str, Any]:
    node_map: Dict[str, Dict[str, Any]] = {}
    for node in nodes:
        client_order_id = node.get("client_order_id")
        if not client_order_id:
            continue
        relation_kind = _relation_kind(node.get("parent_order_id"), node.get("stealth_reason"))
        node_map[client_order_id] = {
            "client_order_id": client_order_id,
            "parent_client_order_id": node.get("parent_order_id"),
            "depth": int(node.get("depth") or 0),
            "relation_kind": relation_kind,
            "stealth_reason": node.get("stealth_reason"),
            "product_id": node.get("product_id"),
            "side": node.get("side"),
            "price": _to_jsonable(node.get("price")),
            "size": _to_jsonable(node.get("size")),
            "parent_status": node.get("parent_status"),
            "stealth_status": node.get("stealth_status"),
            "last_lifecycle_event": node.get("last_lifecycle_event"),
            "current_order_replacement": _to_jsonable(node.get("current_order_replacement")),
            "max_order_replacement": _to_jsonable(node.get("max_order_replacement")),
            "created_at": _safe_iso(node.get("parent_created_at")),
        }

    edges: List[Dict[str, Any]] = []
    for node in node_map.values():
        if node.get("parent_client_order_id"):
            edges.append(
                {
                    "from_parent_client_order_id": node["parent_client_order_id"],
                    "to_child_client_order_id": node["client_order_id"],
                    "relation_kind": node["relation_kind"],
                    "reason": node.get("stealth_reason"),
                }
            )

    normalized_events: List[Dict[str, Any]] = []
    last_dt: Optional[datetime] = None
    for idx, raw in enumerate(events, start=1):
        event_client_order_id = raw.get("client_order_id")
        if event_client_order_id is None and raw.get("parent_order_id") in node_map:
            event_client_order_id = raw.get("parent_order_id")

        node = node_map.get(event_client_order_id, {})
        event_dt = raw.get("event_time")
        delta_ms: Optional[int] = None
        if isinstance(event_dt, datetime) and isinstance(last_dt, datetime):
            delta_ms = int((event_dt - last_dt).total_seconds() * 1000)
        if isinstance(event_dt, datetime):
            last_dt = event_dt

        normalized_events.append(
            {
                "sequence": idx,
                "event_time": _safe_iso(event_dt),
                "delta_ms_from_previous": delta_ms,
                "source_table": raw.get("source_table"),
                "event_type": raw.get("event_type"),
                "client_order_id": event_client_order_id,
                "exchange_order_id": raw.get("exchange_order_id"),
                "parent_client_order_id": node.get("parent_client_order_id") or raw.get("parent_order_id"),
                "root_parent_client_order_id": root_parent_id,
                "relation_kind": node.get("relation_kind") or "unmapped",
                "product_id": raw.get("product_id") or node.get("product_id"),
                "side": raw.get("side") or node.get("side"),
                "price": _to_jsonable(raw.get("price")),
                "size": _to_jsonable(raw.get("size")),
                "status": raw.get("status"),
                "payload": _to_jsonable(raw.get("payload")),
            }
        )

    return {
        "audit_scope": {
            "seed_id": seed_id,
            "root_parent_client_order_id": root_parent_id,
            "lineage_node_count": len(node_map),
            "event_count": len(normalized_events),
        },
        "lineage_nodes": sorted(node_map.values(), key=lambda n: (n["depth"], n.get("created_at") or "")),
        "lineage_edges": edges,
        "timeline_events": normalized_events,
    }


def _print_human(payload: Dict[str, Any]) -> None:
    scope = payload.get("audit_scope", {})
    print("\n=== focused_audit_scope ===")
    print(json.dumps(scope, sort_keys=True, default=str))

    print("\n=== lineage_nodes ===")
    nodes = payload.get("lineage_nodes", [])
    if not nodes:
        print("<no lineage nodes>")
    for node in nodes:
        print(json.dumps(node, sort_keys=True, default=str))

    print("\n=== lineage_edges ===")
    edges = payload.get("lineage_edges", [])
    if not edges:
        print("<no lineage edges>")
    for edge in edges:
        print(json.dumps(edge, sort_keys=True, default=str))

    print("\n=== timeline_events ===")
    events = payload.get("timeline_events", [])
    if not events:
        print("<no timeline events>")
    for event in events:
        print(json.dumps(event, sort_keys=True, default=str))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Focused DB-only audit pass for order lineage and event timeline. "
            "Shows root/child relationships and classifies moves vs new follow-ups "
            "for charting or timestamp-based animation."
        )
    )
    parser.add_argument("--client-order-id", help="Start audit from this client_order_id.")
    parser.add_argument("--stealth-order-id", help="Start audit from this stealth_order_id.")
    parser.add_argument("--limit-events", type=int, default=500, help="Maximum timeline events to emit (default: 500).")
    parser.add_argument(
        "--human",
        action="store_true",
        help="Emit human-readable sectioned text instead of default JSON.",
    )
    args = parser.parse_args()

    db = PostgresDB()
    seed_id = _resolve_seed_id(db, args)
    if not seed_id:
        print("No order found in database. Provide --client-order-id or create orders first.")
        return 1

    root_parent_id = _resolve_root_parent_id(db, seed_id)
    nodes = _load_lineage_nodes(db, root_parent_id)
    lineage_ids = [n["client_order_id"] for n in nodes if n.get("client_order_id")]
    events = _load_timeline_events(db, lineage_ids, max(1, args.limit_events))

    payload = _build_output(seed_id, root_parent_id, nodes, events)
    if args.human:
        _print_human(payload)
        print("\nUsage examples:")
        print("  python genai_tools/__order_lineage_timeline_audit__.py --client-order-id <uuid>")
        print("  python genai_tools/__order_lineage_timeline_audit__.py --stealth-order-id <uuid>")
        print("  python genai_tools/__order_lineage_timeline_audit__.py --human")
        return 0

    # Default behavior is JSON for chart/animation pipelines.
    print(json.dumps(payload, sort_keys=True, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())