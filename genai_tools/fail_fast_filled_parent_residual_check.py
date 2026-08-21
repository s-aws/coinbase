#!/usr/bin/env python
"""Fail-fast checker for FILLED parent follow-up sizing integrity.

Exits with code 1 when any newly FILLED parent violates sizing constraints:
1) Total child size cannot exceed original parent size.
2) Sum of children created after fill time cannot exceed allowed residual size.

Residual size is derived from partial_fill_progress when available:
    residual = max(0, original_order_size - partial_follow_ups_created * min_order_size)
If partial progress is unavailable, residual defaults to parent size.
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from typing import Any

sys.path.insert(0, ".")
from database.database import PostgresDB


def safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_recent_filled_parents(db: PostgresDB, lookback_minutes: int) -> list[dict[str, Any]]:
    query = """
    WITH filled_events AS (
        SELECT
            es.client_order_id,
            MIN(es.created_at) AS filled_at
        FROM order_event_stream es
        WHERE es.event_type = 'order_filled'
          AND es.created_at >= (NOW() - (%s || ' minutes')::interval)
          AND es.client_order_id IS NOT NULL
        GROUP BY es.client_order_id
    )
    SELECT
        p.client_order_id,
        p.size AS parent_size,
        p.status,
        p.created_at,
        fe.filled_at
    FROM order_parent p
    INNER JOIN filled_events fe
        ON fe.client_order_id = p.client_order_id
    WHERE p.status = 'FILLED'
    ORDER BY fe.filled_at DESC
    """
    return db.execute_query(query, (str(lookback_minutes),)) or []


def load_partial_progress(db: PostgresDB, client_order_id: str) -> dict[str, Any] | None:
    query = """
    SELECT
        client_order_id,
        original_order_size,
        min_order_size,
        partial_follow_ups_created,
        status,
        updated_at
    FROM partial_fill_progress
    WHERE client_order_id = %s
    LIMIT 1
    """
    rows = db.execute_query(query, (client_order_id,)) or []
    return rows[0] if rows else None


def load_children_for_parent(db: PostgresDB, parent_client_order_id: str) -> list[dict[str, Any]]:
    query = """
    SELECT
        id,
        client_order_id,
        side,
        size,
        status,
        created_at
    FROM order_parent
    WHERE parent_order_id = %s
    ORDER BY created_at ASC
    """
    return db.execute_query(query, (parent_client_order_id,)) or []


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail-fast check for FILLED parent follow-up residual sizing",
    )
    parser.add_argument(
        "--lookback-minutes",
        type=int,
        default=180,
        help="Only evaluate FILLED parents created in the last N minutes (default: 180)",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=1e-9,
        help="Numeric tolerance for float comparisons (default: 1e-9)",
    )
    args = parser.parse_args()

    db = PostgresDB()
    db.connect()

    violations: list[dict[str, Any]] = []
    inspected = 0

    parents = load_recent_filled_parents(db, args.lookback_minutes)

    for parent in parents:
        inspected += 1
        parent_id = parent.get("client_order_id")
        parent_size = safe_float(parent.get("parent_size"), default=0.0)
        filled_at = parent.get("filled_at")

        progress = load_partial_progress(db, parent_id)
        if progress:
            original_order_size = safe_float(progress.get("original_order_size"), default=parent_size)
            min_order_size = safe_float(progress.get("min_order_size"), default=0.0)
            partial_follow_ups_created = int(progress.get("partial_follow_ups_created") or 0)
            allocated_by_partials = partial_follow_ups_created * min_order_size
            allowed_residual = max(0.0, original_order_size - allocated_by_partials)
        else:
            original_order_size = parent_size
            min_order_size = 0.0
            partial_follow_ups_created = 0
            allocated_by_partials = 0.0
            allowed_residual = parent_size

        children = load_children_for_parent(db, parent_id)
        total_child_size = sum(safe_float(c.get("size"), default=0.0) for c in children)

        if filled_at is not None:
            post_fill_children = [c for c in children if c.get("created_at") is not None and c.get("created_at") >= filled_at]
        else:
            post_fill_children = children
        post_fill_child_size = sum(safe_float(c.get("size"), default=0.0) for c in post_fill_children)

        total_violation = total_child_size > (original_order_size + args.tolerance)
        residual_violation = post_fill_child_size > (allowed_residual + args.tolerance)

        if total_violation or residual_violation:
            violations.append(
                {
                    "parent_client_order_id": parent_id,
                    "parent_size": parent_size,
                    "original_order_size": original_order_size,
                    "partial_follow_ups_created": partial_follow_ups_created,
                    "min_order_size": min_order_size,
                    "allocated_by_partials": allocated_by_partials,
                    "allowed_residual": allowed_residual,
                    "filled_at": str(filled_at) if filled_at else None,
                    "child_count": len(children),
                    "post_fill_child_count": len(post_fill_children),
                    "total_child_size": total_child_size,
                    "post_fill_child_size": post_fill_child_size,
                    "total_violation": total_violation,
                    "residual_violation": residual_violation,
                    "children": [
                        {
                            "id": c.get("id"),
                            "client_order_id": c.get("client_order_id"),
                            "size": safe_float(c.get("size"), default=0.0),
                            "side": c.get("side"),
                            "status": c.get("status"),
                            "created_at": str(c.get("created_at")) if c.get("created_at") else None,
                        }
                        for c in children
                    ],
                }
            )

    db.disconnect()

    print("=" * 100)
    print("FILLED PARENT RESIDUAL FAIL-FAST CHECK")
    print("=" * 100)
    print(f"Inspected FILLED parents: {inspected}")
    print(f"Lookback window (minutes): {args.lookback_minutes}")
    print(f"Violations: {len(violations)}")

    if not violations:
        print("\nPASS: No residual-size violations detected.")
        return 0

    print("\nFAIL: Residual-size violations detected.\n")
    for i, v in enumerate(violations, 1):
        print(f"[{i}] parent_client_order_id={v['parent_client_order_id']}")
        print(
            "    sizes:"
            f" parent={v['parent_size']}"
            f" original={v['original_order_size']}"
            f" allocated_by_partials={v['allocated_by_partials']}"
            f" allowed_residual={v['allowed_residual']}"
            f" total_child={v['total_child_size']}"
            f" post_fill_child={v['post_fill_child_size']}"
        )
        print(
            "    flags:"
            f" total_violation={v['total_violation']}"
            f" residual_violation={v['residual_violation']}"
            f" filled_at={v['filled_at']}"
        )
        print("    children:")
        for c in v["children"]:
            print(
                "      -"
                f" id={c['id']}"
                f" client_order_id={c['client_order_id']}"
                f" side={c['side']}"
                f" size={c['size']}"
                f" status={c['status']}"
                f" created_at={c['created_at']}"
            )

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
