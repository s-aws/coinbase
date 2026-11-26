"""Regression coverage for fresh test-database schema provisioning."""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from psycopg2 import sql

from core.enums import OrderSide, OrderStatus, TargetMovementType
from database.database import PostgresDB
from database.order import update_order_parent_execution_statuses
from database.schema import (
    ALLOWED_DEPLOYMENT_TABLES,
    REQUIRED_TABLES,
    initialize_database_schema,
    verify_database_schema,
    verify_fresh_runtime_database,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_BOOTSTRAP_SCRIPT = (
    PROJECT_ROOT / "scripts" / "bootstrap_runtime_database.sh"
)
RUNTIME_DATABASE_VARIABLES = (
    "COINBASE_DB_HOST",
    "COINBASE_DB_PORT",
    "COINBASE_DB_NAME",
    "COINBASE_DB_USER",
    "COINBASE_DB_PASSWORD",
)


@pytest.fixture
def fresh_runtime_schema(monkeypatch):
    """Route new connections into an empty schema without clearing shared state."""

    schema_name = f"deployment_fresh_{uuid.uuid4().hex}"
    admin_db = PostgresDB()
    try:
        with admin_db.get_cursor() as cursor:
            cursor.execute(
                sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name))
            )
        monkeypatch.setenv("PGOPTIONS", f"-c search_path={schema_name}")
        yield schema_name
    finally:
        with admin_db.get_cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )
        admin_db.disconnect()


def test_database_schema_bootstrap_is_complete_and_idempotent():
    initialize_database_schema()
    initialize_database_schema()
    verify_database_schema()

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

    execution_owner = db.execute_query(
        """
        SELECT is_nullable, column_default
          FROM information_schema.columns
         WHERE table_schema = current_schema()
           AND table_name = 'order_parent'
           AND column_name = 'execution_owner_client_order_id'
        """
    )
    assert execution_owner == [{
        "is_nullable": "YES",
        "column_default": None,
    }]


def test_schema_bootstrap_does_not_import_live_runtime_configuration():
    source = (PROJECT_ROOT / "database" / "order.py").read_text(encoding="utf-8")

    assert "from configuration import DEFAULT_MAX_ORDER_REPLACEMENT" not in source
    assert "from core.constants import DEFAULT_MAX_ORDER_REPLACEMENT" in source

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import database.schema; "
                "assert 'configuration' not in sys.modules"
            ),
        ],
        cwd=PROJECT_ROOT,
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_runtime_database_bootstrap_requires_explicit_environment():
    environment = os.environ.copy()
    for variable_name in RUNTIME_DATABASE_VARIABLES:
        environment.pop(variable_name, None)

    result = subprocess.run(
        [str(RUNTIME_BOOTSTRAP_SCRIPT)],
        cwd=PROJECT_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert result.returncode != 0
    assert (
        "COINBASE_DB_HOST must be set explicitly and cannot be empty"
        in result.stderr
    )


def test_runtime_database_bootstrap_rejects_arguments_before_connect():
    environment = os.environ.copy()
    environment["COINBASE_DB_HOST"] = "invalid.example.test"
    environment["COINBASE_DB_PORT"] = "6543"
    environment["COINBASE_DB_NAME"] = "wrong_confirmation_guard"
    environment["COINBASE_DB_USER"] = "nobody"
    environment["COINBASE_DB_PASSWORD"] = "not-used"

    result = subprocess.run(
        [
            str(RUNTIME_BOOTSTRAP_SCRIPT),
            "--confirm-target",
            "definitely-not-the-configured-target",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert result.returncode != 0
    assert "does not accept arguments" in result.stderr
    assert "Connected database identity" not in result.stdout


def test_runtime_database_bootstrap_verifies_target_and_required_schema(
    fresh_runtime_schema,
):
    environment = os.environ.copy()
    configured_target = (
        f"{environment['COINBASE_DB_HOST']}:"
        f"{environment['COINBASE_DB_PORT']}/"
        f"{environment['COINBASE_DB_NAME']}"
    )

    result = subprocess.run(
        [str(RUNTIME_BOOTSTRAP_SCRIPT)],
        cwd=PROJECT_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert f"Configured runtime database: {configured_target}" in result.stdout
    assert "Connected database identity:" in result.stdout
    assert "Fresh trading-state check:" in result.stdout
    assert "12 required tables verified" in result.stdout
    assert (
        f"Runtime database schema bootstrap complete for {configured_target}."
        in result.stdout
    )


def test_fresh_runtime_verifier_allows_empty_runtime_and_telemetry_tables(
    fresh_runtime_schema,
):
    runtime_db = PostgresDB()
    try:
        with runtime_db.get_cursor() as cursor:
            for table_name in (*REQUIRED_TABLES, *ALLOWED_DEPLOYMENT_TABLES):
                cursor.execute(
                    sql.SQL("CREATE TABLE {} (id INTEGER)").format(
                        sql.Identifier(table_name)
                    )
                )
            for table_name in ALLOWED_DEPLOYMENT_TABLES:
                cursor.execute(
                    sql.SQL("INSERT INTO {} (id) VALUES (1)").format(
                        sql.Identifier(table_name)
                    )
                )

        counts = verify_fresh_runtime_database(runtime_db)
    finally:
        runtime_db.disconnect()

    assert set(counts) == set(REQUIRED_TABLES)
    assert set(ALLOWED_DEPLOYMENT_TABLES) == {
        "market_candle_1m",
        "market_tick",
    }
    assert all(row_count == 0 for row_count in counts.values())


def test_fresh_runtime_verifier_rejects_existing_trading_state(
    fresh_runtime_schema,
):
    runtime_db = PostgresDB()
    try:
        with runtime_db.get_cursor() as cursor:
            cursor.execute("CREATE TABLE order_parent (id INTEGER)")
            cursor.execute("INSERT INTO order_parent (id) VALUES (1)")

        with pytest.raises(RuntimeError, match="order_parent=1"):
            verify_fresh_runtime_database(runtime_db)
    finally:
        runtime_db.disconnect()


def test_fresh_runtime_verifier_rejects_unknown_public_table(
    fresh_runtime_schema,
):
    runtime_db = PostgresDB()
    table_name = f"deployment_unknown_{uuid.uuid4().hex}"

    try:
        with runtime_db.get_cursor() as cursor:
            cursor.execute(
                sql.SQL("CREATE TABLE {} (id INTEGER)").format(
                    sql.Identifier(table_name)
                )
            )

        with pytest.raises(RuntimeError, match="unsupported public tables"):
            verify_fresh_runtime_database(runtime_db)
    finally:
        runtime_db.disconnect()


def test_guarded_execution_status_update_keeps_exact_and_logical_truth():
    initialize_database_schema()
    db = PostgresDB()
    root = str(uuid.uuid4())
    logical_child = str(uuid.uuid4())
    placement = str(uuid.uuid4())
    rows = (
        (root, None, root),
        (logical_child, root, logical_child),
        (placement, root, logical_child),
    )

    try:
        for client_order_id, parent_order_id, owner_id in rows:
            db.execute_query(
                """
                INSERT INTO order_parent (
                    client_order_id,
                    product_id,
                    side,
                    size,
                    price,
                    status,
                    target_movement,
                    target_movement_type,
                    parent_order_id,
                    execution_owner_client_order_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    client_order_id,
                    "BTC-USDC",
                    OrderSide.BUY.value,
                    1,
                    100,
                    OrderStatus.PENDING.value,
                    1,
                    TargetMovementType.PERCENTAGE.value,
                    parent_order_id,
                    owner_id,
                ),
            )

        projected = update_order_parent_execution_statuses(
            placement,
            OrderStatus.OPEN.value,
            expected_execution_owner_client_order_id=logical_child,
        )
        assert projected["placement_updated"] is True
        assert projected["execution_owner_valid"] is True
        assert projected["execution_owner_updated"] is True

        statuses = {
            row["client_order_id"]: row["status"]
            for row in db.execute_query(
                """
                SELECT client_order_id, status
                  FROM order_parent
                 WHERE client_order_id = ANY(%s)
                """,
                ([root, logical_child, placement],),
            )
        }
        assert statuses == {
            root: OrderStatus.PENDING.value,
            logical_child: OrderStatus.OPEN.value,
            placement: OrderStatus.OPEN.value,
        }

        conflicted = update_order_parent_execution_statuses(
            placement,
            OrderStatus.CANCELLED.value,
            expected_execution_owner_client_order_id=root,
        )
        assert conflicted["placement_updated"] is True
        assert conflicted["execution_owner_conflict"] is True
        assert conflicted["execution_owner_valid"] is False
        assert conflicted["execution_owner_updated"] is False

        statuses = {
            row["client_order_id"]: row["status"]
            for row in db.execute_query(
                """
                SELECT client_order_id, status
                  FROM order_parent
                 WHERE client_order_id = ANY(%s)
                """,
                ([root, logical_child, placement],),
            )
        }
        assert statuses == {
            root: OrderStatus.PENDING.value,
            logical_child: OrderStatus.OPEN.value,
            placement: OrderStatus.CANCELLED.value,
        }

        rearmed = update_order_parent_execution_statuses(
            placement,
            OrderStatus.CANCELLED.value,
            logical_status=OrderStatus.PENDING.value,
            expected_execution_owner_client_order_id=logical_child,
        )
        assert rearmed["placement_updated"] is True
        assert rearmed["execution_owner_updated"] is True
        statuses = {
            row["client_order_id"]: row["status"]
            for row in db.execute_query(
                """
                SELECT client_order_id, status
                  FROM order_parent
                 WHERE client_order_id = ANY(%s)
                """,
                ([root, logical_child, placement],),
            )
        }
        assert statuses == {
            root: OrderStatus.PENDING.value,
            logical_child: OrderStatus.PENDING.value,
            placement: OrderStatus.CANCELLED.value,
        }
    finally:
        db.execute_update(
            "DELETE FROM order_parent WHERE client_order_id = ANY(%s)",
            ([placement, logical_child, root],),
        )
