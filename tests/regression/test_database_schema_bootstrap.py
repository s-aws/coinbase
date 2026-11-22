"""Regression coverage for fresh test-database schema provisioning."""

from database.database import PostgresDB
from database.schema import REQUIRED_TABLES, initialize_database_schema


def test_database_schema_bootstrap_is_complete_and_idempotent():
    initialize_database_schema()
    initialize_database_schema()

    db = PostgresDB()
    rows = db.execute_query(
        """
        SELECT tablename
          FROM pg_catalog.pg_tables
         WHERE schemaname = current_schema()
           AND tablename = ANY(%s)
        """,
        (list(REQUIRED_TABLES),),
    )

    assert {row["tablename"] for row in rows} == set(REQUIRED_TABLES)

    external_marker = db.execute_query(
        """
        SELECT is_nullable, column_default
          FROM information_schema.columns
         WHERE table_schema = current_schema()
           AND table_name = 'order_parent'
           AND column_name = 'externally_created'
        """
    )
    assert external_marker == [{
        "is_nullable": "NO",
        "column_default": "false",
    }]
