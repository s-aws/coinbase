"""Canonical non-destructive runtime database schema bootstrap.

The table definitions remain owned by :mod:`database.order`.  This module
provides the single ordered entry point used by deployment, destructive reset,
Linux setup, and test provisioning to create or forward-migrate every required
runtime table.
"""

from collections.abc import Callable

from psycopg2 import sql

from database.database import PostgresDB
from database.order import (
    create_conditional_orders_table,
    create_fill_ledger_table,
    create_order_event_stream_table,
    create_order_match_audit_table,
    create_order_moves_table,
    create_order_parent_table,
    create_partial_fill_progress_table,
    create_stealth_order_lifecycle_history_table,
    create_stealth_order_moves_table,
    create_stealth_order_reveal_history_table,
    create_stealth_order_snapshots_table,
    create_stealth_orders_table,
)


SCHEMA_INITIALIZERS: tuple[tuple[str, Callable[[], None]], ...] = (
    ("order_parent", create_order_parent_table),
    ("stealth_orders", create_stealth_orders_table),
    ("stealth_order_lifecycle_history", create_stealth_order_lifecycle_history_table),
    ("stealth_order_snapshots", create_stealth_order_snapshots_table),
    ("stealth_order_reveal_history", create_stealth_order_reveal_history_table),
    ("order_moves", create_order_moves_table),
    ("stealth_order_moves", create_stealth_order_moves_table),
    ("fill_ledger", create_fill_ledger_table),
    ("conditional_orders", create_conditional_orders_table),
    ("order_event_stream", create_order_event_stream_table),
    ("partial_fill_progress", create_partial_fill_progress_table),
    ("order_match_audit", create_order_match_audit_table),
)

REQUIRED_TABLES: tuple[str, ...] = tuple(
    table_name for table_name, _initializer in SCHEMA_INITIALIZERS
)

# Runtime deployments are fresh trading instances. Existing market telemetry
# is allowed because operator reset/provisioning intentionally preserves or
# backfills it outside the canonical trading schema.
ALLOWED_DEPLOYMENT_TABLES: frozenset[str] = frozenset(
    {"market_candle_1m", "market_tick"}
)


def initialize_database_schema() -> None:
    """Create and forward-migrate required runtime tables in dependency order."""

    for _table_name, initializer in SCHEMA_INITIALIZERS:
        initializer()


def verify_database_schema(db: PostgresDB | None = None) -> None:
    """Raise when any required runtime table is absent from the current schema."""

    owns_connection = db is None
    schema_db = db if db is not None else PostgresDB()
    try:
        rows = schema_db.execute_query(
            """
            SELECT tablename
              FROM pg_catalog.pg_tables
             WHERE schemaname = current_schema()
               AND tablename = ANY(%s)
            """,
            (list(REQUIRED_TABLES),),
        )
        present_tables = {row["tablename"] for row in rows}
        missing_tables = sorted(set(REQUIRED_TABLES) - present_tables)
        if missing_tables:
            raise RuntimeError(
                "Canonical schema bootstrap did not create required "
                f"tables: {missing_tables}"
            )
    finally:
        if owns_connection:
            schema_db.disconnect()


def verify_fresh_runtime_database(
    db: PostgresDB | None = None,
) -> dict[str, int]:
    """Verify deployment has no pre-existing trading state.

    Required runtime tables may be absent or already provisioned, which keeps
    a failed fresh deployment retryable. Any existing required table must be
    empty. Only the two separately owned telemetry tables may coexist with the
    runtime schema; an unknown public table fails closed instead of silently
    deploying over an unintended database.

    Returns:
        Exact row counts for required runtime tables that already exist.
    """

    owns_connection = db is None
    schema_db = db if db is not None else PostgresDB()
    try:
        rows = schema_db.execute_query(
            """
            SELECT tablename
              FROM pg_catalog.pg_tables
             WHERE schemaname = current_schema()
             ORDER BY tablename
            """
        )
        present_tables = {row["tablename"] for row in rows}
        allowed_tables = set(REQUIRED_TABLES) | set(ALLOWED_DEPLOYMENT_TABLES)
        unexpected_tables = sorted(present_tables - allowed_tables)
        if unexpected_tables:
            raise RuntimeError(
                "Fresh runtime database contains unsupported public tables: "
                f"{unexpected_tables}"
            )

        existing_runtime_tables = sorted(
            present_tables.intersection(REQUIRED_TABLES)
        )
        row_counts: dict[str, int] = {}
        if existing_runtime_tables:
            with schema_db.get_cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                for table_name in existing_runtime_tables:
                    cursor.execute(
                        sql.SQL("SELECT COUNT(*) FROM {}").format(
                            sql.Identifier(table_name)
                        )
                    )
                    row_counts[table_name] = int(cursor.fetchone()[0])

        nonempty_tables = {
            table_name: row_count
            for table_name, row_count in row_counts.items()
            if row_count > 0
        }
        if nonempty_tables:
            detail = ", ".join(
                f"{table_name}={row_count}"
                for table_name, row_count in sorted(nonempty_tables.items())
            )
            raise RuntimeError(
                "Fresh runtime database contains existing trading state: "
                f"{detail}"
            )
        return row_counts
    finally:
        if owns_connection:
            schema_db.disconnect()


if __name__ == "__main__":
    initialize_database_schema()
    verify_database_schema()
    print(
        "Database schema is ready "
        f"({len(REQUIRED_TABLES)} required tables verified)."
    )
