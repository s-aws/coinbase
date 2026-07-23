from __future__ import annotations

import os
import re
import uuid

import pytest
from psycopg2 import sql

from application.admin_api.operator_product_catalog import (
    OperatorProductCatalogError,
    ProductCatalogLifecycle,
    ProductCatalogReadResult,
    normalize_product_catalog_item,
)
from application.admin_api.operator_product_catalog_service import (
    OperatorProductCatalogService,
    ProductCatalogApproveRequest,
    ProductCatalogRefreshRequest,
)
from database.database import PostgresDB
from database.operator_product_catalog import OperatorProductCatalogRepository


pytestmark = [pytest.mark.regression, pytest.mark.serial]

TEST_DB_HOST = os.environ.get("COINBASE_DB_HOST", "coinbase-test-postgres")
TEST_DB_PORT = int(os.environ.get("COINBASE_DB_PORT", "9876"))
TEST_DB_NAME = os.environ.get("COINBASE_DB_NAME", "postgres")
TEST_DB_USER = os.environ.get("COINBASE_DB_USER", "postgres")
TEST_DB_PASSWORD = os.environ.get("COINBASE_DB_PASSWORD", "postgres")
_SCHEMA_PATTERN = re.compile(r"^test_operator_product_catalog_[0-9a-f]{32}$")


def _raw_product(
    product_id: str,
    *,
    base: str,
    disabled: bool = False,
) -> dict:
    return {
        "product_id": product_id,
        "product_type": "SPOT",
        "base_currency_id": base,
        "quote_currency_id": "USDC",
        "base_increment": "0.00000001",
        "quote_increment": "0.01",
        "price_increment": "0.01",
        "base_min_size": "0.00001",
        "base_max_size": "10",
        "quote_min_size": "1",
        "quote_max_size": "1000000",
        "display_name": product_id,
        "status": "ONLINE",
        "is_disabled": disabled,
        "trading_disabled": disabled,
        "cancel_only": False,
        "limit_only": False,
        "post_only": False,
        "view_only": False,
    }


@pytest.fixture
def repository() -> OperatorProductCatalogRepository:
    schema = f"test_operator_product_catalog_{uuid.uuid4().hex}"
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
    store = OperatorProductCatalogRepository(database, schema=schema)
    store.ensure_schema()
    try:
        yield store
    finally:
        with database.get_cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )
        database.disconnect()


def _complete_refresh(
    repository: OperatorProductCatalogRepository,
    *,
    products: list[dict],
) -> dict:
    claimed = repository.begin_refresh(
        expected_active_revision_id=repository.get_active_revision_id(),
        actor_id="operator",
        operator_reason="refresh product catalog",
        correlation_id=f"catalog-refresh-{uuid.uuid4()}",
        idempotency_key=f"catalog-refresh-{uuid.uuid4()}",
        acknowledgement=True,
    )
    repository.record_page_call(
        cycle_id=claimed["cycle_id"],
        page_ordinal=1,
        cursor_sha256=None,
    )
    repository.record_page_returned(
        cycle_id=claimed["cycle_id"],
        page_ordinal=1,
    )
    return repository.complete_refresh(
        cycle_id=claimed["cycle_id"],
        read_result=ProductCatalogReadResult(
            products=[
                normalize_product_catalog_item(product)
                for product in products
            ],
            page_count=1,
            pagination_complete=True,
        ),
        actor_id="operator",
        correlation_id=claimed["correlation_id"],
    )


def test_schema_upgrade_adds_rejected_command_state_and_diagnostic_column(
    repository: OperatorProductCatalogRepository,
) -> None:
    table = sql.SQL("{}.operator_product_catalog_command").format(
        sql.Identifier(repository.schema)
    )
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            sql.SQL("ALTER TABLE {} DROP CONSTRAINT {}").format(
                table,
                sql.Identifier(
                    "operator_product_catalog_command_state_check"
                ),
            )
        )
        cursor.execute(
            sql.SQL(
                "ALTER TABLE {} ADD CONSTRAINT {} "
                "CHECK (state IN "
                "('IN_PROGRESS', 'COMPLETED', 'UNKNOWN'))"
            ).format(
                table,
                sql.Identifier(
                    "operator_product_catalog_command_state_check"
                ),
            )
        )
        cursor.execute(
            sql.SQL("ALTER TABLE {} DROP COLUMN diagnostic_code").format(
                table
            )
        )

    repository.ensure_schema()

    with repository.database.get_cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = 'operator_product_catalog_command'
            """,
            (repository.schema,),
        )
        columns = {str(row[0]) for row in cursor.fetchall()}
        cursor.execute(
            """
            SELECT pg_get_constraintdef(constraint_record.oid) AS definition
            FROM pg_constraint AS constraint_record
            JOIN pg_class AS table_record
              ON table_record.oid = constraint_record.conrelid
            JOIN pg_namespace AS namespace_record
              ON namespace_record.oid = table_record.relnamespace
            WHERE namespace_record.nspname = %s
              AND table_record.relname =
                  'operator_product_catalog_command'
              AND constraint_record.conname =
                  'operator_product_catalog_command_state_check'
            """,
            (repository.schema,),
        )
        definitions = [
            str(row[0]) for row in cursor.fetchall()
        ]
    assert "diagnostic_code" in columns
    assert len(definitions) == 1
    assert "REJECTED" in definitions[0]

    repository.record_local_command_rejection(
        operation="APPROVE",
        command_fields={
            "revision_id": str(uuid.uuid4()),
            "expected_revision": 1,
            "snapshot_sha256": "a" * 64,
        },
        actor_id="operator",
        operator_reason="prove migrated rejection durability",
        correlation_id="catalog-migrated-rejection",
        idempotency_key="catalog-migrated-rejection",
        acknowledgement=True,
        diagnostic_code="product_catalog_approval_conflict",
    )
    assert any(
        event["event_type"] == "CATALOG_COMMAND_REJECTED"
        for event in repository.list_events(limit=10)
    )


def test_repository_refresh_review_approve_lifecycle_and_rollback(
    repository: OperatorProductCatalogRepository,
) -> None:
    proposed = _complete_refresh(
        repository,
        products=[
            _raw_product("BTC-USDC", base="BTC"),
            _raw_product("ETH-USDC", base="ETH"),
        ],
    )
    assert proposed["state"] == "PROPOSED"
    assert proposed["added_count"] == 2
    assert proposed["trading_authority_granted"] is False
    assert proposed["portfolio_scope_expanded"] is False
    proposed_rows = {
        row["product_id"]: row
        for row in repository.list_revision_products(
            proposed["revision_id"]
        )
    }
    assert proposed_rows["BTC-USDC"]["change_type"] == "ADDED"
    assert proposed_rows["ETH-USDC"]["change_type"] == "ADDED"
    assert repository.get_goal_budget()["cycle_count"] == 1
    assert repository.get_goal_budget()["logical_read_count"] == 1
    assert repository.get_goal_budget()["page_count"] == 1

    approved = repository.approve_revision(
        revision_id=proposed["revision_id"],
        expected_revision=proposed["revision"],
        snapshot_sha256=proposed["snapshot_sha256"],
        actor_id="operator",
        operator_reason="approve reviewed metadata diff",
        correlation_id="catalog-approve",
        idempotency_key="catalog-approve",
        acknowledgement=True,
    )
    assert approved["state"] == "APPROVED"
    assert approved["active"] is True
    approved_replay = repository.approve_revision(
        revision_id=proposed["revision_id"],
        expected_revision=proposed["revision"],
        snapshot_sha256=proposed["snapshot_sha256"],
        actor_id="operator",
        operator_reason="approve reviewed metadata diff",
        correlation_id="catalog-approve",
        idempotency_key="catalog-approve",
        acknowledgement=True,
    )
    assert approved_replay["revision_id"] == approved["revision_id"]
    assert approved_replay["command_replayed"] is True
    with pytest.raises(
        OperatorProductCatalogError,
        match="product_catalog_idempotency_conflict",
    ):
        repository.approve_revision(
            revision_id=proposed["revision_id"],
            expected_revision=proposed["revision"],
            snapshot_sha256=proposed["snapshot_sha256"],
            actor_id="different-operator",
            operator_reason="different approval reason",
            correlation_id="catalog-approve-different",
            idempotency_key="catalog-approve",
            acknowledgement=True,
        )

    enabled = repository.change_product_lifecycle(
        product_id="BTC-USDC",
        action="ENABLE",
        expected_active_revision_id=approved["revision_id"],
        expected_active_revision=approved["revision"],
        actor_id="operator",
        operator_reason="enable catalog row",
        correlation_id="catalog-enable",
        idempotency_key="catalog-enable",
        acknowledgement=True,
    )
    assert enabled["state"] == "APPLIED"
    rows = {
        row["product_id"]: row
        for row in repository.list_revision_products(enabled["revision_id"])
    }
    assert rows["BTC-USDC"]["lifecycle"] == ProductCatalogLifecycle.ENABLED.value
    assert rows["BTC-USDC"]["change_type"] == "LIFECYCLE_CHANGED"
    assert rows["ETH-USDC"]["lifecycle"] == ProductCatalogLifecycle.PENDING.value
    assert rows["ETH-USDC"]["change_type"] == "UNCHANGED"

    disabled = repository.change_product_lifecycle(
        product_id="BTC-USDC",
        action="DISABLE",
        expected_active_revision_id=enabled["revision_id"],
        expected_active_revision=enabled["revision"],
        actor_id="operator",
        operator_reason="disable catalog row",
        correlation_id="catalog-disable",
        idempotency_key="catalog-disable",
        acknowledgement=True,
    )
    retired = repository.change_product_lifecycle(
        product_id="ETH-USDC",
        action="RETIRE",
        expected_active_revision_id=disabled["revision_id"],
        expected_active_revision=disabled["revision"],
        actor_id="operator",
        operator_reason="retire catalog row",
        correlation_id="catalog-retire",
        idempotency_key="catalog-retire",
        acknowledgement=True,
    )
    retired_rows = {
        row["product_id"]: row
        for row in repository.list_revision_products(retired["revision_id"])
    }
    assert retired_rows["BTC-USDC"]["lifecycle"] == "DISABLED"
    assert retired_rows["ETH-USDC"]["lifecycle"] == "RETIRED"

    rolled_back = repository.rollback_revision(
        target_revision_id=enabled["revision_id"],
        expected_active_revision_id=retired["revision_id"],
        expected_active_revision=retired["revision"],
        target_snapshot_sha256=enabled["snapshot_sha256"],
        actor_id="operator",
        operator_reason="restore enabled catalog snapshot",
        correlation_id="catalog-rollback",
        idempotency_key="catalog-rollback",
        acknowledgement=True,
    )
    rollback_rows = {
        row["product_id"]: row
        for row in repository.list_revision_products(
            rolled_back["revision_id"]
        )
    }
    assert rolled_back["state"] == "ROLLED_BACK"
    assert rolled_back["rollback_of_revision_id"] == enabled["revision_id"]
    assert rollback_rows["BTC-USDC"]["lifecycle"] == "ENABLED"
    assert rollback_rows["ETH-USDC"]["lifecycle"] == "PENDING"
    assert {
        row["change_type"] for row in rollback_rows.values()
    } == {"ROLLBACK_RESTORED"}
    assert repository.list_events(limit=50)


def test_goal_budget_is_shared_and_stops_at_ten(
    repository: OperatorProductCatalogRepository,
) -> None:
    for index in range(10):
        claim = repository.begin_refresh(
            expected_active_revision_id=repository.get_active_revision_id(),
            actor_id="operator",
            operator_reason="bounded refresh",
            correlation_id=f"catalog-cycle-{index}",
            idempotency_key=f"catalog-cycle-{index}",
            acknowledgement=True,
        )
        repository.fail_refresh(
            cycle_id=claim["cycle_id"],
            diagnostic_code="product_catalog_read_failed",
            read_state="NOT_RETURNED",
            actor_id="operator",
            correlation_id=claim["correlation_id"],
        )

    with pytest.raises(
        ValueError,
        match="product_catalog_cycles_exhausted",
    ):
        repository.begin_refresh(
            expected_active_revision_id=repository.get_active_revision_id(),
            actor_id="operator",
            operator_reason="eleventh refresh",
            correlation_id="catalog-cycle-11",
            idempotency_key="catalog-cycle-11",
            acknowledgement=True,
        )


def test_restart_recovery_consumes_claimed_page_without_retry(
    repository: OperatorProductCatalogRepository,
) -> None:
    claim = repository.begin_refresh(
        expected_active_revision_id=None,
        actor_id="operator",
        operator_reason="interrupt refresh",
        correlation_id="catalog-interrupted",
        idempotency_key="catalog-interrupted",
        acknowledgement=True,
    )
    repository.record_page_call(
        cycle_id=claim["cycle_id"],
        page_ordinal=1,
        cursor_sha256=None,
    )

    repository.ensure_schema()

    cycle = repository.get_cycle(claim["cycle_id"])
    assert cycle["state"] == "UNKNOWN"
    assert cycle["read_state"] == "UNKNOWN_AFTER_PAGE_CLAIM"
    assert repository.get_goal_budget()["cycle_count"] == 1
    assert repository.get_goal_budget()["logical_read_count"] == 1
    assert repository.get_goal_budget()["page_count"] == 1
    events = repository.list_events(limit=20)
    assert any(
        event["event_type"] == "CATALOG_REFRESH_RECOVERED_UNKNOWN"
        and event["cycle_id"] == claim["cycle_id"]
        and event["evidence"] == {
            "diagnostic_code":
                "product_catalog_refresh_interrupted_unknown",
            "read_state": "UNKNOWN_AFTER_PAGE_CLAIM",
            "state": "UNKNOWN",
        }
        for event in events
    )


def test_restart_before_page_call_is_closed_and_audited(
    repository: OperatorProductCatalogRepository,
) -> None:
    claim = repository.begin_refresh(
        expected_active_revision_id=None,
        actor_id="operator",
        operator_reason="interrupt before first page",
        correlation_id="catalog-interrupted-before-call",
        idempotency_key="catalog-interrupted-before-call",
        acknowledgement=True,
    )

    repository.ensure_schema()

    cycle = repository.get_cycle(claim["cycle_id"])
    assert cycle["state"] == "FAILED"
    assert cycle["read_state"] == "NOT_RETURNED"
    events = repository.list_events(limit=20)
    assert any(
        event["event_type"] == "CATALOG_REFRESH_RECOVERED_NOT_RETURNED"
        and event["cycle_id"] == claim["cycle_id"]
        for event in events
    )


def test_restart_after_returned_page_is_terminal_and_operator_readable(
    repository: OperatorProductCatalogRepository,
) -> None:
    claim = repository.begin_refresh(
        expected_active_revision_id=None,
        actor_id="operator",
        operator_reason="interrupt after returned page",
        correlation_id="catalog-interrupted-after-return",
        idempotency_key="catalog-interrupted-after-return",
        acknowledgement=True,
    )
    repository.record_page_call(
        cycle_id=claim["cycle_id"],
        page_ordinal=1,
        cursor_sha256=None,
    )
    repository.record_page_returned(
        cycle_id=claim["cycle_id"],
        page_ordinal=1,
    )

    repository.ensure_schema()

    cycle = repository.get_cycle(claim["cycle_id"])
    assert cycle["state"] == "FAILED"
    assert cycle["read_state"] == "RETURNED_INCOMPLETE"
    assert cycle["diagnostic_code"] == (
        "product_catalog_refresh_interrupted_after_return"
    )
    cycle_events = repository.list_events(
        cycle_id=claim["cycle_id"],
        limit=20,
    )
    assert any(
        event["event_type"] == "CATALOG_REFRESH_RECOVERED_INCOMPLETE"
        and event["cycle_id"] == claim["cycle_id"]
        for event in cycle_events
    )


def test_revision_activation_and_lifecycle_recompute_stored_snapshot(
    repository: OperatorProductCatalogRepository,
) -> None:
    proposed = _complete_refresh(
        repository,
        products=[_raw_product("BTC-USDC", base="BTC")],
    )
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE {repository.prefix}operator_product_catalog_product
            SET base_min_size = '0.00002'
            WHERE revision_id = %s::uuid AND product_id = 'BTC-USDC'
            """,
            (proposed["revision_id"],),
        )
    with pytest.raises(
        OperatorProductCatalogError,
        match="product_catalog_revision_snapshot_invalid",
    ):
        repository.approve_revision(
            revision_id=proposed["revision_id"],
            expected_revision=proposed["revision"],
            snapshot_sha256=proposed["snapshot_sha256"],
            actor_id="operator",
            operator_reason="approve tampered revision",
            correlation_id="catalog-tampered-approve",
            idempotency_key="catalog-tampered-approve",
            acknowledgement=True,
        )

    clean = _complete_refresh(
        repository,
        products=[_raw_product("ETH-USDC", base="ETH")],
    )
    approved = repository.approve_revision(
        revision_id=clean["revision_id"],
        expected_revision=clean["revision"],
        snapshot_sha256=clean["snapshot_sha256"],
        actor_id="operator",
        operator_reason="approve clean revision",
        correlation_id="catalog-clean-approve",
        idempotency_key="catalog-clean-approve",
        acknowledgement=True,
    )
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE {repository.prefix}operator_product_catalog_product
            SET base_min_size = '0.00002'
            WHERE revision_id = %s::uuid AND product_id = 'ETH-USDC'
            """,
            (approved["revision_id"],),
        )
    with pytest.raises(
        OperatorProductCatalogError,
        match="product_catalog_revision_snapshot_invalid",
    ):
        repository.change_product_lifecycle(
            product_id="ETH-USDC",
            action="ENABLE",
            expected_active_revision_id=approved["revision_id"],
            expected_active_revision=approved["revision"],
            actor_id="operator",
            operator_reason="enable tampered active revision",
            correlation_id="catalog-tampered-lifecycle",
            idempotency_key="catalog-tampered-lifecycle",
            acknowledgement=True,
        )


def test_rejected_local_command_is_durable_audited_and_actor_bound(
    repository: OperatorProductCatalogRepository,
) -> None:
    proposed = _complete_refresh(
        repository,
        products=[_raw_product("BTC-USDC", base="BTC")],
    )
    service = OperatorProductCatalogService(
        repository=repository,
        rest_client=None,
        rest_client_available=False,
    )
    body = ProductCatalogApproveRequest(
        expected_revision=proposed["revision"],
        snapshot_sha256="f" * 64,
        operator_reason="reject mismatched reviewed catalog hash",
        confirm_catalog_approval=True,
    )

    for _ in range(2):
        with pytest.raises(
            OperatorProductCatalogError,
            match="product_catalog_approval_conflict",
        ):
            service.approve_revision(
                revision_id=proposed["revision_id"],
                body=body,
                actor_id="operator",
                correlation_id="catalog-rejected-approval",
                idempotency_key="catalog-rejected-approval",
            )
    rejected_events = [
        event
        for event in repository.list_events(limit=20)
        if event["event_type"] == "CATALOG_COMMAND_REJECTED"
    ]
    assert len(rejected_events) == 1
    assert rejected_events[0]["evidence"] == {
        "operation": "approve",
        "diagnostic_code": "product_catalog_approval_conflict",
    }

    with pytest.raises(
        OperatorProductCatalogError,
        match="product_catalog_idempotency_conflict",
    ):
        service.approve_revision(
            revision_id=proposed["revision_id"],
            body=body.model_copy(
                update={"operator_reason": "different audited reason"}
            ),
            actor_id="different-operator",
            correlation_id="catalog-rejected-approval-different",
            idempotency_key="catalog-rejected-approval",
        )


def test_event_pagination_is_stable_when_timestamps_are_tied(
    repository: OperatorProductCatalogRepository,
) -> None:
    for operation in ("APPROVE", "ENABLE"):
        repository.record_local_command_rejection(
            operation=operation,
            command_fields={
                "operation": operation.lower(),
                "revision_id": str(uuid.uuid4()),
            },
            actor_id="operator",
            operator_reason=f"record tied {operation.lower()} rejection",
            correlation_id=f"catalog-tied-{operation.lower()}",
            idempotency_key=f"catalog-tied-{operation.lower()}",
            acknowledgement=True,
            diagnostic_code="product_catalog_command_conflict",
        )
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            sql.SQL(
                "UPDATE {}.operator_product_catalog_event "
                "SET recorded_at = %s::timestamptz"
            ).format(sql.Identifier(repository.schema)),
            ("2026-07-23T16:00:00+00:00",),
        )

    all_events = repository.list_events(limit=10)
    first_page = repository.list_events(limit=1, offset=0)
    second_page = repository.list_events(limit=1, offset=1)

    assert [event["event_id"] for event in all_events] == sorted(
        (event["event_id"] for event in all_events),
        reverse=True,
    )
    assert first_page[0]["event_id"] == all_events[0]["event_id"]
    assert second_page[0]["event_id"] == all_events[1]["event_id"]
    assert first_page[0]["event_id"] != second_page[0]["event_id"]


def test_terminal_refresh_idempotency_replay_never_repeats_catalog_read(
    repository: OperatorProductCatalogRepository,
) -> None:
    body = ProductCatalogRefreshRequest(
        expected_active_revision_id=None,
        operator_reason="one terminal unavailable catalog read",
        confirm_one_no_retry_product_catalog_read=True,
    )
    unavailable = OperatorProductCatalogService(
        repository=repository,
        rest_client=None,
        rest_client_available=False,
    )
    first = unavailable.refresh_catalog(
        body=body,
        actor_id="operator",
        correlation_id="catalog-terminal-replay",
        idempotency_key="catalog-terminal-replay",
    )

    class _Client:
        calls = 0

        def get_product_catalog_page(self, **_kwargs):
            self.calls += 1
            raise AssertionError("terminal replay must not read Coinbase")

    client = _Client()
    available = OperatorProductCatalogService(
        repository=repository,
        rest_client=client,
        rest_client_available=True,
    )
    replay = available.refresh_catalog(
        body=body,
        actor_id="operator",
        correlation_id="catalog-terminal-replay",
        idempotency_key="catalog-terminal-replay",
    )

    assert first.status == "rejected"
    assert replay.status == "replayed"
    assert replay.coinbase_read_state == "NOT_RETURNED"
    assert replay.local_state_mutated is False
    assert client.calls == 0
    assert repository.get_goal_budget()["cycle_count"] == 1
