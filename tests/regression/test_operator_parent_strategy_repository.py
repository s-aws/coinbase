from __future__ import annotations

import os
import re
import uuid

import pytest
from psycopg2 import errors, sql

from application.admin_api.operator_parent_strategy import (
    OperatorParentStrategyError,
    normalize_parent_strategy_terms,
)
from application.admin_api.operator_product_catalog import (
    ProductCatalogReadResult,
    normalize_product_catalog_item,
)
from database.database import PostgresDB
from database.operator_parent_strategy import OperatorParentStrategyRepository
from database.operator_product_catalog import OperatorProductCatalogRepository


pytestmark = [pytest.mark.regression, pytest.mark.serial]

TEST_DB_HOST = os.environ.get("COINBASE_DB_HOST", "coinbase-test-postgres")
TEST_DB_PORT = int(os.environ.get("COINBASE_DB_PORT", "9876"))
TEST_DB_NAME = os.environ.get("COINBASE_DB_NAME", "postgres")
TEST_DB_USER = os.environ.get("COINBASE_DB_USER", "postgres")
TEST_DB_PASSWORD = os.environ.get("COINBASE_DB_PASSWORD", "postgres")
_SCHEMA_PATTERN = re.compile(r"^test_operator_parent_strategy_[0-9a-f]{32}$")


def _terms(*, target: str = "0.005"):
    return normalize_parent_strategy_terms(
        product_id="BTC-USDC",
        side="BUY",
        reference_size="0.0001",
        reference_price="60000",
        target_movement=target,
        target_movement_type="P",
        max_order_replacement=2,
        allow_partial_fills=False,
        child_order_type="LIMIT",
        child_time_in_force="GOOD_UNTIL_CANCELLED",
        child_post_only=True,
    )


def _enable_btc_catalog(
    catalog: OperatorProductCatalogRepository,
) -> None:
    cycle = catalog.begin_refresh(
        expected_active_revision_id=None,
        actor_id="operator",
        operator_reason="seed test product",
        correlation_id="parent-strategy-product-refresh",
        idempotency_key="parent-strategy-product-refresh",
        acknowledgement=True,
    )
    catalog.record_page_call(
        cycle_id=cycle["cycle_id"],
        page_ordinal=1,
        cursor_sha256=None,
    )
    catalog.record_page_returned(
        cycle_id=cycle["cycle_id"],
        page_ordinal=1,
    )
    proposed = catalog.complete_refresh(
        cycle_id=cycle["cycle_id"],
        read_result=ProductCatalogReadResult(
            products=[
                normalize_product_catalog_item(
                    {
                        "product_id": "BTC-USDC",
                        "product_type": "SPOT",
                        "base_currency_id": "BTC",
                        "quote_currency_id": "USDC",
                        "base_increment": "0.00000001",
                        "quote_increment": "0.01",
                        "price_increment": "0.01",
                        "base_min_size": "0.00001",
                        "base_max_size": "10",
                        "quote_min_size": "1",
                        "quote_max_size": "1000000",
                        "display_name": "BTC-USDC",
                        "status": "ONLINE",
                        "is_disabled": False,
                        "trading_disabled": False,
                        "cancel_only": False,
                        "limit_only": False,
                        "post_only": False,
                        "view_only": False,
                    }
                )
            ],
            page_count=1,
            pagination_complete=True,
        ),
        actor_id="operator",
        correlation_id=cycle["correlation_id"],
    )
    approved = catalog.approve_revision(
        revision_id=proposed["revision_id"],
        expected_revision=proposed["revision"],
        snapshot_sha256=proposed["snapshot_sha256"],
        actor_id="operator",
        operator_reason="approve test product",
        correlation_id="parent-strategy-product-approve",
        idempotency_key="parent-strategy-product-approve",
        acknowledgement=True,
    )
    catalog.change_product_lifecycle(
        product_id="BTC-USDC",
        action="ENABLE",
        expected_active_revision_id=approved["revision_id"],
        expected_active_revision=approved["revision"],
        actor_id="operator",
        operator_reason="enable test product",
        correlation_id="parent-strategy-product-enable",
        idempotency_key="parent-strategy-product-enable",
        acknowledgement=True,
    )


@pytest.fixture
def repository() -> OperatorParentStrategyRepository:
    schema = f"test_operator_parent_strategy_{uuid.uuid4().hex}"
    assert _SCHEMA_PATTERN.fullmatch(schema)
    database = PostgresDB(
        host=TEST_DB_HOST,
        port=TEST_DB_PORT,
        database=TEST_DB_NAME,
        user=TEST_DB_USER,
        password=TEST_DB_PASSWORD,
    )
    database.connect()
    with database.get_cursor() as cursor:
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        cursor.execute(
            sql.SQL(
                """
                CREATE TABLE {}.order_parent (
                    id BIGSERIAL PRIMARY KEY,
                    client_order_id VARCHAR(40) UNIQUE NOT NULL,
                    parent_order_id VARCHAR(40),
                    product_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    exchange_order_id TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            ).format(sql.Identifier(schema))
        )
        cursor.execute(
            sql.SQL(
                """
                CREATE TABLE {}.order_follow_up_semantic_claim (
                    claim_id UUID PRIMARY KEY,
                    source_client_order_id VARCHAR(128) NOT NULL,
                    state VARCHAR(20) NOT NULL
                )
                """
            ).format(sql.Identifier(schema))
        )
        cursor.execute(
            sql.SQL(
                """
                CREATE TABLE {}.operator_follow_up_materialization_attempt (
                    materialization_id UUID PRIMARY KEY,
                    root_client_order_id VARCHAR(128) NOT NULL
                )
                """
            ).format(sql.Identifier(schema))
        )
        cursor.execute(
            sql.SQL(
                """
                CREATE TABLE {}.partial_fill_progress (
                    client_order_id VARCHAR(128) PRIMARY KEY,
                    status VARCHAR(20) NOT NULL
                )
                """
            ).format(sql.Identifier(schema))
        )
    catalog = OperatorProductCatalogRepository(database, schema=schema)
    catalog.ensure_schema()
    _enable_btc_catalog(catalog)
    store = OperatorParentStrategyRepository(database, schema=schema)
    store.ensure_schema()
    try:
        yield store
    finally:
        with database.get_cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )
        database.disconnect()


def _create(
    repository: OperatorParentStrategyRepository,
    *,
    idempotency_key: str = "parent-strategy-create",
) -> dict:
    return repository.create_strategy(
        name="BTC follow-up parent",
        terms=_terms(),
        portfolio_scope_sha256="a" * 64,
        actor_id="operator",
        operator_reason="create reviewed parent strategy",
        correlation_id="parent-strategy-create",
        idempotency_key=idempotency_key,
        acknowledgement=True,
    )


def test_repository_create_list_edit_deactivate_delete_and_replay(
    repository: OperatorParentStrategyRepository,
) -> None:
    assert repository.product_is_active_spot("BTC-USDC") is True
    assert repository.product_is_active_spot("ETH-USDC") is False

    created = _create(repository)
    assert created["admitted_product_catalog_revision_id"]
    assert len(created["admitted_product_catalog_snapshot_sha256"]) == 64
    replay = _create(repository)
    assert replay["strategy_id"] == created["strategy_id"]
    assert replay["command_replayed"] is True
    items, total = repository.list_strategies(
        lifecycle_state=None,
        product_id=None,
        limit=25,
        offset=0,
    )
    assert total == 1
    assert items[0]["allowed_actions"] == ["EDIT", "DEACTIVATE"]
    assert items[0]["delete_allowed"] is False

    edited = repository.edit_strategy(
        strategy_id=created["strategy_id"],
        expected_revision=1,
        name="BTC follow-up parent v2",
        terms=_terms(target="0.006"),
        actor_id="operator",
        operator_reason="adjust target",
        correlation_id="parent-strategy-edit",
        idempotency_key="parent-strategy-edit",
        acknowledgement=True,
    )
    assert edited["revision"] == 2
    assert str(edited["target_movement"]) == "0.006"
    with pytest.raises(
        OperatorParentStrategyError,
        match="parent_strategy_revision_conflict",
    ):
        repository.edit_strategy(
            strategy_id=created["strategy_id"],
            expected_revision=1,
            name="stale",
            terms=_terms(target="0.007"),
            actor_id="operator",
            operator_reason="stale edit",
            correlation_id="parent-strategy-edit-stale",
            idempotency_key="parent-strategy-edit-stale",
            acknowledgement=True,
        )
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT state, diagnostic_code
            FROM {repository.prefix}operator_parent_strategy_command
            WHERE idempotency_key = 'parent-strategy-edit-stale'
            """
        )
        rejected = cursor.fetchone()
    assert tuple(rejected) == (
        "REJECTED",
        "parent_strategy_revision_conflict",
    )
    with pytest.raises(
        OperatorParentStrategyError,
        match="parent_strategy_revision_conflict",
    ):
        repository.edit_strategy(
            strategy_id=created["strategy_id"],
            expected_revision=1,
            name="stale",
            terms=_terms(target="0.007"),
            actor_id="operator",
            operator_reason="stale edit",
            correlation_id="parent-strategy-edit-stale",
            idempotency_key="parent-strategy-edit-stale",
            acknowledgement=True,
        )

    deactivated = repository.deactivate_strategy(
        strategy_id=created["strategy_id"],
        expected_revision=2,
        actor_id="operator",
        operator_reason="stop future use",
        correlation_id="parent-strategy-deactivate",
        idempotency_key="parent-strategy-deactivate",
        acknowledgement=True,
    )
    assert deactivated["revision"] == 3
    assert deactivated["delete_allowed"] is True
    edited_deactivated = repository.edit_strategy(
        strategy_id=created["strategy_id"],
        expected_revision=3,
        name="Deactivated parent revised",
        terms=_terms(target="0.008"),
        actor_id="operator",
        operator_reason="revise inactive definition",
        correlation_id="parent-strategy-edit-deactivated",
        idempotency_key="parent-strategy-edit-deactivated",
        acknowledgement=True,
    )
    assert edited_deactivated["revision"] == 4
    assert edited_deactivated["lifecycle_state"] == "DEACTIVATED"
    deactivated_events, _ = repository.list_events(
        strategy_id=created["strategy_id"],
        limit=25,
        offset=0,
    )
    deactivated_edit_event = next(
        event
        for event in deactivated_events
        if event["correlation_id"] == "parent-strategy-edit-deactivated"
    )
    assert deactivated_edit_event["evidence"] == {
        "lifecycle_state": "DEACTIVATED",
        "revision": 4,
    }
    deleted = repository.delete_strategy(
        strategy_id=created["strategy_id"],
        expected_revision=4,
        actor_id="operator",
        operator_reason="delete unused definition",
        correlation_id="parent-strategy-delete",
        idempotency_key="parent-strategy-delete",
        acknowledgement=True,
    )
    assert deleted["lifecycle_state"] == "DELETED"
    assert deleted["allowed_actions"] == []
    assert repository.get_strategy(created["strategy_id"])[
        "lifecycle_state"
    ] == "DELETED"
    late_create_replay = _create(repository)
    assert late_create_replay["revision"] == 1
    assert late_create_replay["lifecycle_state"] == "ACTIVE"
    late_edit_replay = repository.edit_strategy(
        strategy_id=created["strategy_id"],
        expected_revision=1,
        name="BTC follow-up parent v2",
        terms=_terms(target="0.006"),
        actor_id="operator",
        operator_reason="adjust target",
        correlation_id="parent-strategy-edit",
        idempotency_key="parent-strategy-edit",
        acknowledgement=True,
    )
    assert late_edit_replay["revision"] == 2
    assert late_edit_replay["lifecycle_state"] == "ACTIVE"
    events, event_total = repository.list_events(
        strategy_id=created["strategy_id"],
        limit=2,
        offset=0,
    )
    assert event_total == 5
    assert len(events) == 2
    assert len({event["event_id"] for event in events}) == 2


def test_repository_idempotency_binds_actor_reason_and_payload(
    repository: OperatorParentStrategyRepository,
) -> None:
    _create(repository)

    with pytest.raises(
        OperatorParentStrategyError,
        match="parent_strategy_idempotency_conflict",
    ):
        repository.create_strategy(
            name="BTC follow-up parent",
            terms=_terms(),
            portfolio_scope_sha256="a" * 64,
            actor_id="different-operator",
            operator_reason="different reason",
            correlation_id="different-correlation",
            idempotency_key="parent-strategy-create",
            acknowledgement=True,
        )


def test_create_rejection_is_durable_and_same_payload_replays_rejection(
    repository: OperatorParentStrategyRepository,
) -> None:
    disabled_terms = normalize_parent_strategy_terms(
        product_id="ETH-USDC",
        side="BUY",
        reference_size="0.001",
        reference_price="3000",
        target_movement="0.005",
        target_movement_type="P",
        max_order_replacement=0,
        allow_partial_fills=False,
        child_order_type="LIMIT",
        child_time_in_force="GOOD_UNTIL_CANCELLED",
        child_post_only=True,
    )

    for _ in range(2):
        with pytest.raises(
            OperatorParentStrategyError,
            match="parent_strategy_product_not_enabled",
        ):
            repository.create_strategy(
                name="Disabled ETH parent",
                terms=disabled_terms,
                portfolio_scope_sha256="a" * 64,
                actor_id="operator",
                operator_reason="prove rejected creation is durable",
                correlation_id="parent-strategy-create-rejected",
                idempotency_key="parent-strategy-create-rejected",
                acknowledgement=True,
            )

    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT state, diagnostic_code, strategy_id
            FROM {repository.prefix}operator_parent_strategy_command
            WHERE idempotency_key = 'parent-strategy-create-rejected'
            """
        )
        rejected = cursor.fetchone()
    assert tuple(rejected) == (
        "REJECTED",
        "parent_strategy_product_not_enabled",
        None,
    )


def test_delete_fails_closed_on_parent_dependencies(
    repository: OperatorParentStrategyRepository,
) -> None:
    created = _create(repository)
    root_id = "33333333-3333-4333-8333-333333333333"
    child_id = "44444444-4444-4444-8444-444444444444"
    repository.bind_materialized_root(
        strategy_id=created["strategy_id"],
        expected_revision=1,
        root_client_order_id=root_id,
    )
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {repository.prefix}order_parent (
                client_order_id, product_id, status, exchange_order_id
            )
            VALUES (%s, 'BTC-USDC', 'OPEN', 'exchange-evidence')
            """,
            (root_id,),
        )
    deactivated = repository.deactivate_strategy(
        strategy_id=created["strategy_id"],
        expected_revision=2,
        actor_id="operator",
        operator_reason="stop strategy",
        correlation_id="parent-strategy-dependency-deactivate",
        idempotency_key="parent-strategy-dependency-deactivate",
        acknowledgement=True,
    )
    assert deactivated["delete_allowed"] is False
    assert "parent_strategy_parent_not_unused_or_terminal" in deactivated[
        "delete_blockers"
    ]
    with pytest.raises(
        OperatorParentStrategyError,
        match="parent_strategy_delete_blocked",
    ):
        repository.delete_strategy(
            strategy_id=created["strategy_id"],
            expected_revision=3,
            actor_id="operator",
            operator_reason="blocked delete",
            correlation_id="parent-strategy-blocked-delete",
            idempotency_key="parent-strategy-blocked-delete",
            acknowledgement=True,
        )

    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE {repository.prefix}order_parent
            SET status = 'FILLED', exchange_order_id = NULL
            WHERE client_order_id = %s
            """,
            (root_id,),
        )
        cursor.execute(
            f"""
            INSERT INTO {repository.prefix}order_parent (
                client_order_id, parent_order_id, product_id, status
            )
            VALUES (%s, %s, 'BTC-USDC', 'FILLED')
            """,
            (child_id, root_id),
        )
    detail = repository.get_strategy(created["strategy_id"])
    assert detail["child_count"] == 1
    assert detail["delete_allowed"] is False

    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"DELETE FROM {repository.prefix}order_parent "
            "WHERE client_order_id = %s",
            (child_id,),
        )
        cursor.execute(
            f"""
            INSERT INTO {repository.prefix}order_follow_up_semantic_claim (
                claim_id, source_client_order_id, state
            )
            VALUES (%s::uuid, %s, 'CLAIMED')
            """,
            (str(uuid.uuid4()), root_id),
        )
    detail = repository.get_strategy(created["strategy_id"])
    assert detail["unresolved_claim_count"] == 1
    assert detail["delete_allowed"] is False

    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE {repository.prefix}order_follow_up_semantic_claim
            SET state = 'RELEASED'
            WHERE source_client_order_id = %s
            """,
            (root_id,),
        )
        cursor.execute(
            f"""
            INSERT INTO
                {repository.prefix}operator_follow_up_materialization_attempt (
                    materialization_id, root_client_order_id
                )
            VALUES (%s::uuid, %s)
            """,
            (str(uuid.uuid4()), root_id),
        )
    detail = repository.get_strategy(created["strategy_id"])
    assert detail["reconciliation_required"] is True
    assert detail["delete_allowed"] is False


def test_schema_is_upgrade_safe_and_commands_are_postgresql_durable(
    repository: OperatorParentStrategyRepository,
) -> None:
    repository.ensure_schema()
    _create(repository)
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = %s
              AND table_name LIKE 'operator_parent_strategy%%'
            """,
            (repository.schema,),
        )
        table_count = int(cursor.fetchone()[0])
        cursor.execute(
            f"""
            SELECT state, operation, diagnostic_code
            FROM {repository.prefix}operator_parent_strategy_command
            WHERE idempotency_key = 'parent-strategy-create'
            """
        )
        command = cursor.fetchone()
    assert table_count == 3
    assert tuple(command) == ("COMPLETED", "CREATE", "parent_strategy_created")


def test_schema_upgrade_backfills_admitted_catalog_binding(
    repository: OperatorParentStrategyRepository,
) -> None:
    created = _create(
        repository,
        idempotency_key="parent-strategy-upgrade-create",
    )
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            ALTER TABLE {repository.prefix}operator_parent_strategy
            DROP COLUMN admitted_product_catalog_revision_id,
            DROP COLUMN admitted_product_catalog_snapshot_sha256
            """
        )

    repository.ensure_schema()

    upgraded = repository.get_strategy(created["strategy_id"])
    assert upgraded["admitted_product_catalog_revision_id"]
    assert len(
        upgraded["admitted_product_catalog_snapshot_sha256"]
    ) == 64


def test_replay_without_exact_result_snapshot_fails_closed(
    repository: OperatorParentStrategyRepository,
) -> None:
    _create(
        repository,
        idempotency_key="parent-strategy-missing-replay-snapshot",
    )
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE {repository.prefix}operator_parent_strategy_command
            SET result_json = NULL
            WHERE idempotency_key =
                'parent-strategy-missing-replay-snapshot'
            """
        )

    with pytest.raises(
        OperatorParentStrategyError,
        match="parent_strategy_replay_evidence_unavailable",
    ):
        _create(
            repository,
            idempotency_key="parent-strategy-missing-replay-snapshot",
        )


def test_product_admission_is_bound_to_exact_goal_row(
    repository: OperatorParentStrategyRepository,
) -> None:
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT revision_id
            FROM {repository.prefix}operator_product_catalog_active
            WHERE goal_id = 'operator_product_catalog_administration_v1'
            """
        )
        canonical_revision_id = str(cursor.fetchone()[0])
        cursor.execute(
            f"""
            INSERT INTO {repository.prefix}operator_product_catalog_goal (
                goal_id
            )
            VALUES ('unrelated_product_catalog_goal')
            """
        )
        cursor.execute(
            f"""
            INSERT INTO {repository.prefix}operator_product_catalog_active (
                goal_id, revision_id
            )
            VALUES (
                'unrelated_product_catalog_goal',
                %s::uuid
            )
            """,
            (canonical_revision_id,),
        )
        cursor.execute(
            f"""
            DELETE FROM {repository.prefix}operator_product_catalog_active
            WHERE goal_id = 'operator_product_catalog_administration_v1'
            """
        )
    assert repository.product_is_active_spot("BTC-USDC") is False
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {repository.prefix}operator_product_catalog_active (
                goal_id, revision_id
            )
            VALUES (
                'operator_product_catalog_administration_v1',
                %s::uuid
            )
            """,
            (canonical_revision_id,),
        )


def test_missing_used_definition_dependency_table_fails_closed(
    repository: OperatorParentStrategyRepository,
) -> None:
    created = _create(
        repository,
        idempotency_key="parent-strategy-missing-dependency-create",
    )
    root_id = "55555555-5555-4555-8555-555555555555"
    repository.bind_materialized_root(
        strategy_id=created["strategy_id"],
        expected_revision=1,
        root_client_order_id=root_id,
    )
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {repository.prefix}order_parent (
                client_order_id, product_id, status
            )
            VALUES (%s, 'BTC-USDC', 'FILLED')
            """,
            (root_id,),
        )
        cursor.execute(
            f"""
            DROP TABLE
                {repository.prefix}operator_follow_up_materialization_attempt
            """
        )
    deactivated = repository.deactivate_strategy(
        strategy_id=created["strategy_id"],
        expected_revision=2,
        actor_id="operator",
        operator_reason="deactivate missing dependency proof",
        correlation_id="parent-strategy-missing-dependency-deactivate",
        idempotency_key="parent-strategy-missing-dependency-deactivate",
        acknowledgement=True,
    )
    assert deactivated["reconciliation_required"] is True
    assert deactivated["delete_allowed"] is False


def test_command_audit_lists_rejected_and_completed_commands(
    repository: OperatorParentStrategyRepository,
) -> None:
    created = _create(
        repository,
        idempotency_key="parent-strategy-command-audit-create",
    )
    with pytest.raises(
        OperatorParentStrategyError,
        match="parent_strategy_revision_conflict",
    ):
        repository.deactivate_strategy(
            strategy_id=created["strategy_id"],
            expected_revision=9,
            actor_id="operator",
            operator_reason="record rejected command evidence",
            correlation_id="parent-strategy-command-audit-rejected",
            idempotency_key="parent-strategy-command-audit-rejected",
            acknowledgement=True,
        )

    commands, total = repository.list_commands(limit=25, offset=0)

    assert total == 2
    assert {command["state"] for command in commands} == {
        "COMPLETED",
        "REJECTED",
    }
    rejected = next(
        command for command in commands
        if command["state"] == "REJECTED"
    )
    assert rejected["diagnostic_code"] == (
        "parent_strategy_revision_conflict"
    )
    assert "operator_reason_sha256" not in rejected
    assert "payload_sha256" not in rejected


def test_malformed_actor_never_enters_rejected_command_audit(
    repository: OperatorParentStrategyRepository,
) -> None:
    with pytest.raises(
        OperatorParentStrategyError,
        match="parent_strategy_command_context_invalid",
    ):
        repository.create_strategy(
            name="Invalid actor parent",
            terms=_terms(),
            portfolio_scope_sha256="a" * 64,
            actor_id="unsafe actor",
            operator_reason="invalid identity must remain outside audit",
            correlation_id="parent-strategy-invalid-actor",
            idempotency_key="parent-strategy-invalid-actor",
            acknowledgement=True,
        )

    with pytest.raises(
        OperatorParentStrategyError,
        match="parent_strategy_command_context_invalid",
    ):
        repository.record_rejected_request(
            operation="EDIT",
            strategy_id=None,
            request_payload={"name": "invalid"},
            actor_id="unsafe actor",
            operator_reason="invalid identity must remain outside audit",
            correlation_id="parent-strategy-invalid-rejected-actor",
            idempotency_key="parent-strategy-invalid-rejected-actor",
            diagnostic_code="parent_strategy_name_invalid",
        )

    commands, total = repository.list_commands(limit=25, offset=0)
    assert total == 0
    assert commands == []


def test_delete_takes_shared_follow_up_root_advisory_lock(
    repository: OperatorParentStrategyRepository,
) -> None:
    created = _create(
        repository,
        idempotency_key="parent-strategy-root-lock-create",
    )
    root_id = "66666666-6666-4666-8666-666666666666"
    repository.bind_materialized_root(
        strategy_id=created["strategy_id"],
        expected_revision=1,
        root_client_order_id=root_id,
    )
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {repository.prefix}order_parent (
                client_order_id, product_id, status
            )
            VALUES (%s, 'BTC-USDC', 'FILLED')
            """,
            (root_id,),
        )
    deactivated = repository.deactivate_strategy(
        strategy_id=created["strategy_id"],
        expected_revision=2,
        actor_id="operator",
        operator_reason="deactivate before root lock proof",
        correlation_id="parent-strategy-root-lock-deactivate",
        idempotency_key="parent-strategy-root-lock-deactivate",
        acknowledgement=True,
    )
    assert deactivated["delete_allowed"] is True

    blocker = PostgresDB(
        host=TEST_DB_HOST,
        port=TEST_DB_PORT,
        database=TEST_DB_NAME,
        user=TEST_DB_USER,
        password=TEST_DB_PASSWORD,
    )
    blocker.connect()
    blocker_cursor = blocker._conn.cursor()
    blocker_cursor.execute(
        "SELECT pg_advisory_xact_lock(%s, hashtext(%s))",
        (17291, root_id),
    )
    try:
        with repository.database.get_cursor() as cursor:
            cursor.execute("SET lock_timeout = '100ms'")
        with pytest.raises(errors.LockNotAvailable):
            repository.delete_strategy(
                strategy_id=created["strategy_id"],
                expected_revision=3,
                actor_id="operator",
                operator_reason="prove root interlock blocks deletion",
                correlation_id="parent-strategy-root-lock-delete",
                idempotency_key="parent-strategy-root-lock-delete",
                acknowledgement=True,
            )
    finally:
        blocker._conn.rollback()
        blocker_cursor.close()
        blocker.disconnect()
        with repository.database.get_cursor() as cursor:
            cursor.execute("SET lock_timeout = 0")
