"""Regression coverage for fresh test-database schema provisioning."""

import os
import subprocess
import sys
import uuid
from pathlib import Path

from core.enums import OrderSide, OrderStatus, TargetMovementType
from database.database import PostgresDB
from database.order import update_order_parent_execution_statuses
from database.schema import (
    REQUIRED_TABLES,
    initialize_database_schema,
    verify_database_schema,
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
        [
            str(RUNTIME_BOOTSTRAP_SCRIPT),
            "--confirm-target",
            "unconfigured-target",
        ],
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


def test_runtime_database_bootstrap_rejects_wrong_confirmation_before_connect():
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
    assert "target confirmation mismatch" in result.stderr
    assert "invalid.example.test:6543/wrong_confirmation_guard" in result.stderr


def test_runtime_database_bootstrap_verifies_target_and_required_schema():
    environment = os.environ.copy()
    configured_target = (
        f"{environment['COINBASE_DB_HOST']}:"
        f"{environment['COINBASE_DB_PORT']}/"
        f"{environment['COINBASE_DB_NAME']}"
    )

    result = subprocess.run(
        [
            str(RUNTIME_BOOTSTRAP_SCRIPT),
            "--confirm-target",
            configured_target,
        ],
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
    assert "12 required tables verified" in result.stdout
    assert (
        f"Runtime database schema bootstrap complete for {configured_target}."
        in result.stdout
    )


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
