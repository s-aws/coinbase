"""Non-destructive database schema bootstrap.

The table definitions remain owned by :mod:`database.order`.  This module
provides the single ordered entry point used by Linux setup and test
provisioning to create or forward-migrate every required table.
"""

from collections.abc import Callable

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


def initialize_database_schema() -> None:
    """Create and forward-migrate every required table in dependency order."""

    for _table_name, initializer in SCHEMA_INITIALIZERS:
        initializer()


if __name__ == "__main__":
    initialize_database_schema()
    print("Database schema is ready.")
